import csv
import json
import logging
import datetime
from collections import defaultdict
from typing import Any, Dict, List, Optional

import click
from filelock import FileLock
from kubernetes import client
from kubernetes.client import ApiClient

# Import utilities from k8s_utils
from utils.k8s_utils import (
    list_all_namespaces,
    load_kube_config_auto,
    namespace_exists,
    parse_storage_string,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def handle_datetime(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def get_object_size(obj: Any) -> int:
    """Serializes an object to JSON and returns its size in bytes."""
    try:
        # Convert k8s client object to dict if necessary
        if hasattr(obj, "to_dict"):
            obj_dict = obj.to_dict()
        elif isinstance(obj, dict):
            obj_dict = obj
        else:
            # Fallback for unexpected types, size is unknown
            logging.warning(f"Cannot determine size for object of type {type(obj)}")
            return 0
        # Use the custom handler for datetime objects
        json_str = json.dumps(obj_dict, ensure_ascii=False, default=handle_datetime)
        return len(json_str.encode("utf-8"))
    except Exception as e:
        logging.error(f"Error serializing object to calculate size: {e}")
        return 0  # Return 0 if serialization fails


def count_resources(
    namespace: str, include_crds: bool, api_client: Optional[ApiClient] = None
) -> Dict[str, Any]:
    # API Clients - Initialize using the passed client or default
    v1 = client.CoreV1Api(api_client)
    apps_v1 = client.AppsV1Api(api_client)
    batch_v1 = client.BatchV1Api(api_client)
    custom_api = client.CustomObjectsApi(api_client)
    apiext_v1 = client.ApiextensionsV1Api(api_client)

    # Dictionary to store resource counts and sizes for the namespace
    namespace_resources = defaultdict(int)
    # Combine CM and Secret sizes
    total_core_resources_size_bytes = 0
    total_cr_size_bytes = 0
    total_pvc_capacity_bytes = 0

    try:
        # --- Count and Size Core Resources ---
        # Pods (Count only)
        pods = v1.list_namespaced_pod(namespace)
        namespace_resources["Pods"] = len(pods.items)

        # Services (Count only)
        services = v1.list_namespaced_service(namespace)
        namespace_resources["Services"] = len(services.items)

        # ConfigMaps (Count and Size)
        configmaps = v1.list_namespaced_config_map(namespace)
        namespace_resources["ConfigMaps"] = len(configmaps.items)
        for cm in configmaps.items:
            try:
                full_cm = v1.read_namespaced_config_map(name=cm.metadata.name, namespace=namespace)
                # Add to combined size
                total_core_resources_size_bytes += get_object_size(full_cm)
            except client.exceptions.ApiException as e:
                logging.error(f"Could not read ConfigMap {cm.metadata.name} in {namespace}: {e}")

        # Secrets (Count and Size)
        secrets = v1.list_namespaced_secret(namespace)
        namespace_resources["Secrets"] = len(secrets.items)
        for secret in secrets.items:
            try:
                # Avoid fetching large secrets if possible, but need full object for size
                full_secret = v1.read_namespaced_secret(
                    name=secret.metadata.name, namespace=namespace
                )
                # Add to combined size
                total_core_resources_size_bytes += get_object_size(full_secret)
            except client.exceptions.ApiException as e:
                logging.error(f"Could not read Secret {secret.metadata.name} in {namespace}: {e}")

        # PersistentVolumeClaims (Count and Capacity Size)
        pvcs = v1.list_namespaced_persistent_volume_claim(namespace)
        namespace_resources["PersistentVolumeClaims"] = len(pvcs.items)
        for pvc in pvcs.items:
            try:
                if pvc.status and pvc.status.capacity:
                    storage_size_str = pvc.status.capacity.get("storage")
                    if storage_size_str:
                        pvc_bytes = parse_storage_string(storage_size_str)
                        if pvc_bytes is not None:
                            total_pvc_capacity_bytes += pvc_bytes
                        else:
                            logging.warning(
                                f"Could not parse PVC capacity for {pvc.metadata.name} in {namespace}: '{storage_size_str}'"
                            )
            except Exception as e:  # Catch broader exceptions during PVC processing
                logging.error(
                    f"Error processing PVC {pvc.metadata.name} capacity in {namespace}: {e}"
                )

        # ServiceAccounts (Count only)
        service_accounts = v1.list_namespaced_service_account(namespace)
        namespace_resources["ServiceAccounts"] = len(service_accounts.items)

        # Endpoints (Count only)
        endpoints = v1.list_namespaced_endpoints(namespace)
        namespace_resources["Endpoints"] = len(endpoints.items)

        # --- Count Apps Resources (Counts only for now) ---
        namespace_resources["Deployments"] = len(
            apps_v1.list_namespaced_deployment(namespace).items
        )
        namespace_resources["ReplicaSets"] = len(
            apps_v1.list_namespaced_replica_set(namespace).items
        )
        namespace_resources["StatefulSets"] = len(
            apps_v1.list_namespaced_stateful_set(namespace).items
        )
        namespace_resources["DaemonSets"] = len(apps_v1.list_namespaced_daemon_set(namespace).items)

        # --- Count Batch Resources (Counts only for now) ---
        namespace_resources["Jobs"] = len(batch_v1.list_namespaced_job(namespace).items)
        namespace_resources["CronJobs"] = len(batch_v1.list_namespaced_cron_job(namespace).items)

        # --- Count and Size Custom Resources (CRDs) ---
        if include_crds:
            try:
                crds = apiext_v1.list_custom_resource_definition().items
            except client.exceptions.ApiException as e:
                logging.error(f"Could not list CRDs: {e}. Skipping CRD processing.")
                crds = []  # Ensure crds is iterable even on failure

            for crd in crds:
                # Ensure basic CRD structure is present before proceeding
                if not (
                    crd.spec
                    and crd.spec.group
                    and crd.spec.versions
                    and crd.spec.names
                    and crd.spec.names.plural
                    and crd.spec.names.kind
                ):
                    logging.warning(f"Skipping CRD with incomplete spec: {crd.metadata.name}")
                    continue

                group = crd.spec.group
                versions = crd.spec.versions
                plural = crd.spec.names.plural
                kind = crd.spec.names.kind

                # Use the first listed version (often v1, v1alpha1, etc.)
                # More robust logic might try multiple versions if one fails
                if not versions:
                    logging.warning(f"Skipping CRD {kind} as it has no versions defined.")
                    continue
                version = versions[0].name  # Assuming at least one version exists

                try:
                    # List instances of this CRD in the namespace
                    custom_objects = custom_api.list_namespaced_custom_object(
                        group=group, version=version, namespace=namespace, plural=plural
                    )
                    cr_count = len(custom_objects.get("items", []))
                    namespace_resources[kind] = cr_count  # Count CR instances by Kind

                    # Calculate total size for instances of this CRD
                    for item in custom_objects.get("items", []):
                        try:
                            # Need item name to fetch the full object
                            item_name = item.get("metadata", {}).get("name")
                            if not item_name:
                                logging.warning(
                                    f"Skipping CR item in {namespace} for kind {kind} due to missing metadata.name"
                                )
                                continue

                            # Fetch the full custom object to calculate its size
                            full_cr = custom_api.get_namespaced_custom_object(
                                group=group,
                                version=version,
                                namespace=namespace,
                                plural=plural,
                                name=item_name,
                            )
                            total_cr_size_bytes += get_object_size(full_cr)
                        except client.exceptions.ApiException as e_get:
                            # Log error getting specific instance but continue with others
                            logging.error(
                                f"Could not read CR {kind} instance {item_name} in {namespace}: {e_get}"
                            )
                        except Exception as e_size:
                            logging.error(
                                f"Error calculating size for CR {kind} instance {item_name} in {namespace}: {e_size}"
                            )

                except client.exceptions.ApiException as e_list:
                    # Log errors listing specific CRD types (e.g., forbidden) but continue
                    # Don't log 404s aggressively if a CRD exists cluster-wide but not in this NS
                    if e_list.status != 404:
                        logging.error(
                            f"Could not list instances for {kind} ({group}/{version}) in namespace {namespace}: {e_list.reason}"
                        )
                except Exception as e_general:  # Catch other potential errors during CR processing
                    logging.error(
                        f"Unexpected error processing CRD {kind} in namespace {namespace}: {e_general}"
                    )

        # Add calculated sizes to the results
        namespace_resources["TotalCoreResourcesSizeKiB"] = round(total_core_resources_size_bytes / 1024, 2)
        namespace_resources["TotalPVCCapacityGiB"] = round(total_pvc_capacity_bytes / (1024**3), 2)
        if include_crds:
            namespace_resources["TotalCustomResourceSizeKiB"] = round(total_cr_size_bytes / 1024, 2)

    except client.exceptions.ApiException as e:
        logging.error(f"General K8s API error counting resources in namespace {namespace}: {e}")
    except Exception as e:  # Catch any other unexpected errors
        logging.error(f"Unexpected error counting resources in namespace {namespace}: {e}")

    return namespace_resources


@click.command()
@click.option(
    "--namespace",
    "target_namespace",
    default=None,
    help="Specify a single namespace (defaults to all namespaces).",
)
@click.option(
    "--include-crds",
    is_flag=True,
    help="Include custom resources (CRDs) in the count and size calculations.",
)
@click.option(
    "--output-file",
    type=click.Path(dir_okay=False, writable=True),
    default="namespace_resources.csv",
    help="Path to output CSV file.",
)
@click.option(
    "--kubeconfig",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
    default=None,
    help="Path to the kubeconfig file to use (overrides default locations).",
)
@click.option(
    "--sizes-only",
    is_flag=True,
    default=False,
    help="Output only namespace and size columns, omitting resource counts.",
)
def main(
    target_namespace: Optional[str], include_crds: bool, output_file: str, kubeconfig: Optional[str], sizes_only: bool
):
    """Counts Kubernetes resources and calculates sizes for ConfigMaps, Secrets,
    PVC capacity, and optionally Custom Resources within specified namespaces."""
    # --- Use utility function for config loading, passing the kubeconfig path --- #
    if not load_kube_config_auto(config_file=kubeconfig):
        return

    # Get API client *after* config is loaded
    api_client = client.ApiClient()  # Initialize once

    # --- Count Cluster-Wide Persistent Volumes --- #
    try:
        v1_core = client.CoreV1Api(api_client) # Need a CoreV1Api instance
        pv_list = v1_core.list_persistent_volume()
        pv_count = len(pv_list.items)
        logging.info(f"Cluster-wide PersistentVolume count: {pv_count}")
    except client.exceptions.ApiException as e:
        logging.error(f"Could not list PersistentVolumes: {e}. Skipping PV count.")
    except Exception as e:
        logging.error(f"Unexpected error counting PersistentVolumes: {e}")

    # --- Use utility functions for namespace handling --- #
    namespaces_to_scan: List[str] = []
    if target_namespace:
        # Check if the specified namespace exists
        if namespace_exists(target_namespace, api_client=api_client):
            namespaces_to_scan = [target_namespace]
            logging.info(f"Targeting specified namespace: {target_namespace}")
        else:
            logging.error(
                f"Specified namespace '{target_namespace}' not found or could not be accessed."
            )
            return
    else:
        logging.info("Attempting to list all namespaces...")
        all_ns = list_all_namespaces(api_client=api_client)
        if all_ns is not None:
            namespaces_to_scan = all_ns
            logging.info(f"Targeting all {len(namespaces_to_scan)} namespaces.")
        else:
            logging.error("Could not list namespaces. Please check permissions.")
            return

    # Prepare output data
    all_resources_data: List[Dict[str, Any]] = []
    all_field_names = set(["Namespace"])  # Start with Namespace

    for ns in namespaces_to_scan:
        logging.info(f"Processing namespace: {ns}...")
        resources = count_resources(ns, include_crds, api_client=api_client)
        if resources:  # Only add if data was collected
            # Combine namespace name with resource data
            ns_data = {"Namespace": ns, **resources}
            all_resources_data.append(ns_data)
            all_field_names.update(ns_data.keys())  # Dynamically collect all headers

            # Log summary for the namespace
            logging.info(f"Finished processing namespace: {ns}. Resources found: {len(resources)}")
            # Optional: Log detailed counts/sizes per namespace
            # for resource_type, value in resources.items():
            #     logging.debug(f"  {ns} - {resource_type}: {value}")
        else:
            logging.warning(f"No resources or data collected for namespace: {ns}")

    # Write output to CSV with file locking
    if not all_resources_data:
        logging.warning("No data collected from any namespace. CSV file will not be created.")
        return

    # Ensure a consistent order for columns, putting sizes at the end might be nice
    # Convert set to list and sort (optional, but good for consistency)
    size_fields = sorted([f for f in all_field_names if f.endswith(("KiB", "GiB"))])

    if sizes_only:
        # Only include Namespace and size columns
        ordered_fieldnames = ["Namespace"] + size_fields
        logging.info("Sizes only flag detected, outputting only namespace and size columns.")
    else:
        # Include Namespace, counts, and sizes
        count_fields = sorted(
            [f for f in all_field_names if not f.endswith(("KiB", "GiB")) and f != "Namespace"]
        ) # Includes the new ServiceAccounts, Endpoints
        ordered_fieldnames = ["Namespace"] + count_fields + size_fields

    lock_path = f"{output_file}.lock"
    logging.info(f"Attempting to write results to {output_file}...")
    lock = FileLock(lock_path)
    try:
        with lock:
            logging.info(f"Acquired lock on {lock_path}")
            with open(
                output_file, mode="w", newline="", encoding="utf-8"
            ) as csvfile:  # Added encoding
                # Use restval to handle missing keys gracefully if some namespaces lack certain resources/sizes
                writer = csv.DictWriter(
                    csvfile, fieldnames=ordered_fieldnames, restval="0"
                )  # Default missing values to '0'
                writer.writeheader()
                writer.writerows(all_resources_data)  # Use writerows for efficiency
                logging.info(
                    f"Successfully wrote data for {len(all_resources_data)} namespaces to {output_file}"
                )
    except IOError as e:
        logging.error(f"Error writing to output file {output_file}: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred during file writing: {e}")
    finally:
        # Clean up lock file if it exists (optional, FileLock might handle this)
        # import os
        # if os.path.exists(lock_path):
        #     try:
        #         os.remove(lock_path)
        #     except OSError as e_rm:
        #         logging.warning(f"Could not remove lock file {lock_path}: {e_rm}")
        pass  # FileLock should release on exit


if __name__ == "__main__":
    main()
