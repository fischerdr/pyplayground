import concurrent.futures  # Import for threading
import csv
import datetime
import json
import logging
import os
import re
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

import click
from filelock import FileLock
from kubernetes import client
from kubernetes.client import ApiClient
from kubernetes.client.rest import ApiException

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
    namespace: str,
    include_crds: bool,
    api_client: Optional[ApiClient] = None,
    crd_list: Optional[List[Any]] = None,  # Add crd_list parameter
) -> Optional[Dict[str, Any]]:  # Allow returning None on failure
    # API Clients - Initialize using the passed client or default
    # Important for threading: Create API client instances *within* the function/thread
    # if the original api_client object is not thread-safe, or pass a thread-safe one.
    v1 = client.CoreV1Api(api_client)
    apps_v1 = client.AppsV1Api(api_client)
    batch_v1 = client.BatchV1Api(api_client)
    custom_api = client.CustomObjectsApi(api_client)

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
            # Use the pre-fetched CRD list passed as argument
            if crd_list is None:
                logging.error(
                    f"CRD list not provided to count_resources for namespace {namespace} when include_crds is True. Skipping CRDs."
                )
                crds_to_process = []
            else:
                crds_to_process = crd_list

            for crd in crds_to_process:
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
        namespace_resources["TotalCoreResourcesSizeKiB"] = round(
            total_core_resources_size_bytes / 1024, 2
        )
        namespace_resources["TotalPVCCapacityGiB"] = round(total_pvc_capacity_bytes / (1024**3), 2)
        if include_crds:
            namespace_resources["TotalCustomResourceSizeKiB"] = round(total_cr_size_bytes / 1024, 2)

    except client.exceptions.ApiException as e:
        logging.error(f"General K8s API error counting resources in namespace {namespace}: {e}")
        return None  # Indicate failure for this namespace
    except Exception as e:  # Catch any other unexpected errors
        logging.error(f"Unexpected error counting resources in namespace {namespace}: {e}")
        return None  # Indicate failure for this namespace

    return namespace_resources


# --- Helper function to sanitize strings for use in filenames --- #
def sanitize_filename(name: str) -> str:
    """Removes or replaces characters invalid for typical filenames."""
    # Remove leading/trailing whitespace and replace spaces with underscores
    name = name.strip().replace(" ", "_")
    # Remove characters that are generally problematic in filenames across OSes
    name = re.sub(r'[<>:"/\|?*\x00-\x1F]', "", name)
    # Replace sequences of underscores or invalid replacements with a single underscore
    name = re.sub(r"_+", "_", name)
    # Handle potential empty string after sanitization
    return name if name else "invalid_name"


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
    default=None,  # Default will be determined dynamically
    help="Path to output CSV file.",
)
@click.option(
    "--kubeconfig",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
    default=None,
    help="Path to the kubeconfig file to use (overrides default locations).",
)
@click.option(
    "--label-selector",
    default=None,
    help="Filter namespaces using a Kubernetes label selector (e.g., 'env=prod'). Cannot be used with --namespace.",
)
@click.option(
    "--sizes-only",
    is_flag=True,
    default=False,
    help="Output only namespace and size columns, omitting resource counts.",
)
@click.option(
    "--max-workers",
    type=int,
    default=10,
    show_default=True,
    help="Maximum number of namespaces to process concurrently.",
)
def main(
    target_namespace: Optional[str],
    include_crds: bool,
    output_file: str,
    kubeconfig: Optional[str],
    sizes_only: bool,
    label_selector: Optional[str],
    max_workers: int,
):
    """Counts Kubernetes resources and calculates sizes for ConfigMaps, Secrets,
    PVC capacity, and optionally Custom Resources within specified namespaces."""
    # --- Validate mutually exclusive options --- #
    if target_namespace and label_selector:
        logging.error("Cannot use --namespace and --label-selector simultaneously.")
        click.echo("Error: Cannot use --namespace and --label-selector simultaneously.", err=True)
        return

    # --- Use utility function for config loading, passing the kubeconfig path --- #
    if not load_kube_config_auto(config_file=kubeconfig):
        return

    # Get API client *after* config is loaded
    api_client = client.ApiClient()  # Initialize once

    # --- Count Cluster-Wide Persistent Volumes --- #
    try:
        v1_core = client.CoreV1Api(api_client)  # Need a CoreV1Api instance
        pv_list = v1_core.list_persistent_volume()
        pv_count = len(pv_list.items)
        logging.info(f"Cluster-wide PersistentVolume count: {pv_count}")
    except client.exceptions.ApiException as e:
        logging.error(f"Could not list PersistentVolumes: {e}. Skipping PV count.")
    except Exception as e:
        logging.error(f"Unexpected error counting PersistentVolumes: {e}")

    # --- Use utility functions for namespace handling --- #
    namespaces_to_scan: List[str] = []
    v1_core_for_ns = client.CoreV1Api(api_client)  # API client for namespace listing

    if label_selector:
        logging.info(f"Attempting to list namespaces with label selector: '{label_selector}'")
        try:
            selected_ns_list = v1_core_for_ns.list_namespace(label_selector=label_selector)
            namespaces_to_scan = [ns.metadata.name for ns in selected_ns_list.items]
            if not namespaces_to_scan:
                logging.warning(f"No namespaces found matching label selector: '{label_selector}'")
                return  # Exit if no namespaces match
            logging.info(f"Found {len(namespaces_to_scan)} namespaces matching selector.")
        except ApiException as e:
            logging.error(f"Error listing namespaces with selector '{label_selector}': {e}")
            return
        except Exception as e:
            logging.error(f"Unexpected error listing namespaces with selector: {e}")
            return
    elif target_namespace:
        # Check if the specified namespace exists
        if namespace_exists(target_namespace, api_client=v1_core_for_ns.api_client):
            namespaces_to_scan = [target_namespace]
            logging.info(f"Targeting specified namespace: {target_namespace}")
        else:
            logging.error(
                f"Specified namespace '{target_namespace}' not found or could not be accessed."
            )
            return
    else:
        logging.info("Attempting to list all namespaces...")
        all_ns = list_all_namespaces(api_client=v1_core_for_ns.api_client)
        if all_ns is not None:
            namespaces_to_scan = all_ns
            num_ns = len(namespaces_to_scan)
            logging.info(f"Found {num_ns} total namespaces.")
            if num_ns > 75:
                warning_msg = (
                    f"WARNING: Preparing to scan {num_ns} namespaces. "
                    "This may take a long time and put significant load on the API server. "
                    "Consider using --namespace or --label-selector to limit the scope."
                )
                logging.warning(warning_msg)
                click.echo(
                    f"\n{warning_msg}\nPausing for 15 seconds. Press Ctrl+C to cancel scan.\n",
                    err=True,
                )
                try:
                    time.sleep(15)
                    logging.info("Resuming scan...")
                except KeyboardInterrupt:
                    logging.warning("Scan cancelled by user during pause.")
                    click.echo("Scan cancelled.", err=True)
                    return
            logging.info(f"Targeting all {num_ns} namespaces for scan.")
        else:
            logging.error("Could not list namespaces. Please check permissions.")
            return

    # --- Pre-fetch CRD list if needed --- #
    cluster_crd_list: Optional[List[Any]] = None
    if include_crds:
        logging.info("Pre-fetching Custom Resource Definition list...")
        try:
            apiext_v1_main = client.ApiextensionsV1Api(api_client)
            cluster_crd_list = apiext_v1_main.list_custom_resource_definition().items
            logging.info(f"Found {len(cluster_crd_list)} CRDs cluster-wide.")
        except ApiException as e:
            logging.error(f"Could not pre-fetch CRD list: {e}. Cannot process CRDs.")
            include_crds = False  # Disable CRD processing if list fails
            cluster_crd_list = []  # Ensure it's iterable later
        except Exception as e:
            logging.error(f"Unexpected error pre-fetching CRD list: {e}. Cannot process CRDs.")
            include_crds = False  # Disable CRD processing
            cluster_crd_list = []

    # Prepare output data
    all_resources_data: List[Dict[str, Any]] = []
    all_field_names = set(["Namespace"])  # Start with Namespace

    # --- Process namespaces using ThreadPoolExecutor --- #
    logging.info(f"Starting namespace processing with up to {max_workers} worker threads...")
    processed_count = 0
    failed_namespaces = []

    # Use a context manager for the executor to ensure threads are cleaned up
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Prepare arguments for map - api_client and crd_list are shared
        # Note: Ensure api_client is thread-safe or consider creating new ones per thread if issues arise.
        # The standard kubernetes client *should* be thread-safe, but heavy concurrent use might reveal edge cases.
        future_to_ns = {
            executor.submit(count_resources, ns, include_crds, api_client, cluster_crd_list): ns
            for ns in namespaces_to_scan
        }

        for future in concurrent.futures.as_completed(future_to_ns):
            ns = future_to_ns[future]
            try:
                resources = (
                    future.result()
                )  # Get result from thread, may raise exception if thread failed
                if resources:  # Check if count_resources returned data (not None)
                    ns_data = {"Namespace": ns, **resources}
                    all_resources_data.append(ns_data)
                    all_field_names.update(ns_data.keys())  # Dynamically collect headers
                    logging.info(
                        f"Successfully processed namespace: {ns}. Resources found: {len(resources)}"
                    )
                    processed_count += 1
                else:
                    # count_resources returned None, indicating handled error within the function
                    logging.warning(
                        f"No data returned for namespace: {ns}. It might have failed processing."
                    )
                    failed_namespaces.append(ns)

            except Exception as exc:
                # Catch exceptions raised *by* the count_resources function within the thread
                logging.error(f"Namespace {ns} generated an exception during processing: {exc}")
                failed_namespaces.append(ns)
            # No explicit logging for start needed as as_completed yields when done

    logging.info(
        f"Finished processing all namespaces. Successful: {processed_count}, Failed: {len(failed_namespaces)}."
    )
    if failed_namespaces:
        logging.warning(f"Failed namespaces: {', '.join(failed_namespaces)}")

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
        )  # Includes the new ServiceAccounts, Endpoints
        ordered_fieldnames = ["Namespace"] + count_fields + size_fields

    # --- Determine final output file path --- #
    final_output_file: str
    if output_file:
        # User specified an output file
        final_output_file = output_file
        logging.info(f"Using specified output file: {final_output_file}")
    else:
        # Generate default filename based on scope and flags
        if target_namespace:
            scope_name = sanitize_filename(target_namespace)
        else:
            scope_name = "all_namespaces"

        suffix = "_resources"
        if include_crds:
            suffix += "_with_crds"
        if sizes_only:
            suffix += "_sizes_only"

        final_output_file = f"tmp/{scope_name}{suffix}.csv"
        logging.info(f"Using generated default output file: {final_output_file}")

    # Ensure the output directory exists
    try:
        output_dir = os.path.dirname(final_output_file)
        if output_dir:  # Avoid trying to create directory if filename is in current dir
            os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        logging.error(f"Could not create output directory '{output_dir}': {e}")
        return

    lock_path = f"{final_output_file}.lock"
    logging.info(f"Attempting to write results to {final_output_file}...")
    lock = FileLock(lock_path)
    try:
        with lock:
            logging.info(f"Acquired lock on {lock_path}")
            with open(
                final_output_file, mode="w", newline="", encoding="utf-8"
            ) as csvfile:  # Added encoding
                # Use restval to handle missing keys gracefully if some namespaces lack certain resources/sizes
                # Add extrasaction='ignore' to handle cases where data has more fields than headers (e.g., --sizes-only)
                writer = csv.DictWriter(
                    csvfile, fieldnames=ordered_fieldnames, restval="0", extrasaction="ignore"
                )
                writer.writeheader()
                writer.writerows(all_resources_data)  # Use writerows for efficiency
                logging.info(
                    f"Successfully wrote data for {len(all_resources_data)} namespaces to {final_output_file}"
                )
    except IOError as e:
        logging.error(f"Error writing to output file {final_output_file}: {e}")
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
