#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""Counts and sizes Kubernetes resources in a namespace."""
import concurrent.futures  # Import for threading
import csv
import datetime
import json
import logging
import os
import re
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import click
from filelock import FileLock
from kubernetes import client
from kubernetes.client import ApiClient
from kubernetes.client.rest import ApiException

# Import utilities from k8s_utils
from pyplayground.utils.k8s_utils import (
    format_duration,
    list_all_namespaces,
    load_kube_config_auto,
    namespace_exists,
    parse_storage_string,
)
from pyplayground.utils.logging_utils import setup_logging  # Import the new logging setup function

# --- Logging Setup ---
logger = logging.getLogger(__name__)
# Basic logging configuration (can be enhanced) - Removed basicConfig
# logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def handle_datetime(obj):
    """JSON serializer for objects not serializable by default json code."""
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


def _calculate_crd_items_size(
    custom_api: client.CustomObjectsApi,
    namespace: str,
    group: str,
    version: str,
    plural: str,
    kind: str,  # Added kind for logging
    items: List[Dict[str, Any]],
) -> int:
    """Calculates the total size of items for a specific CRD kind.

    Args:
        custom_api: Initialized CustomObjectsApi client.
        namespace: The namespace being processed.
        group: CRD group.
        version: CRD version.
        plural: CRD plural name.
        kind: CRD kind (for logging).
        items: List of CRD items (usually from list_namespaced_custom_object).

    Returns:
        Total size in bytes of the processed items.
    """
    total_size = 0
    for item in items:
        try:
            item_name = item.get("metadata", {}).get("name")
            if not item_name:
                logging.warning(f"Skipping CR item size calculation in {namespace} for kind {kind} due to missing metadata.name")
                continue

            # Fetch the full custom object to calculate its size
            full_cr = custom_api.get_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                name=item_name,
            )
            total_size += get_object_size(full_cr)
        except client.exceptions.ApiException as e_get:
            # Log error getting specific instance but continue with others
            logging.error(f"Could not read CR {kind} instance {item_name} in {namespace}: {e_get}")
        except Exception as e_size:
            logging.error(f"Error calculating size for CR {kind} instance {item_name} in {namespace}: {e_size}")
    return total_size


def _process_custom_resources(
    custom_api: client.CustomObjectsApi,
    namespace: str,
    crd_list: List[Any],
) -> Tuple[Dict[str, int], int]:
    """Processes custom resources (CRDs) for counting and sizing.

    Args:
        custom_api: Initialized CustomObjectsApi client.
        namespace: The namespace to process.
        crd_list: The list of CRDs to check.

    Returns:
        A tuple containing a dictionary of CRD counts by Kind and the total size.
    """
    cr_counts = defaultdict(int)
    total_cr_size_bytes = 0

    for crd in crd_list:
        # Ensure basic CRD structure is present before proceeding
        if not (crd.spec and crd.spec.group and crd.spec.versions and crd.spec.names and crd.spec.names.plural and crd.spec.names.kind):
            logging.warning(f"Skipping CRD with incomplete spec: {crd.metadata.name}")
            continue

        group = crd.spec.group
        versions = crd.spec.versions
        plural = crd.spec.names.plural
        kind = crd.spec.names.kind

        if not versions:
            logging.warning(f"Skipping CRD {kind} as it has no versions defined.")
            continue
        version = versions[0].name  # Assuming at least one version exists

        try:
            # List instances of this CRD in the namespace
            custom_objects = custom_api.list_namespaced_custom_object(group=group, version=version, namespace=namespace, plural=plural)
            items = custom_objects.get("items", [])
            cr_counts[kind] = len(items)  # Count CR instances by Kind

            # Calculate total size for instances of this CRD
            total_cr_size_bytes += _calculate_crd_items_size(custom_api, namespace, group, version, plural, kind, items)

        except client.exceptions.ApiException as e_list:
            if e_list.status != 404:
                logging.error(f"Could not list instances for {kind} ({group}/{version}) in namespace {namespace}: {e_list.reason}")
        except Exception as e_general:
            logging.error(f"Unexpected error processing CRD {kind} in namespace {namespace}: {e_general}")

    return cr_counts, total_cr_size_bytes


def _process_secrets(v1: client.CoreV1Api, namespace: str) -> Tuple[int, int]:
    """Processes Secrets for counting and sizing.

    Args:
        v1: Initialized CoreV1Api client.
        namespace: The namespace to process.

    Returns:
        A tuple containing the count and total size of secrets.
    """
    secret_count = 0
    total_secret_size_bytes = 0

    try:
        secrets = v1.list_namespaced_secret(namespace)
        secret_count = len(secrets.items)
        for secret in secrets.items:
            try:
                if secret.data:
                    secret_size_bytes = sum(len(value) for value in secret.data.values())
                    total_secret_size_bytes += secret_size_bytes
                else:
                    logging.warning(f"Secret {secret.metadata.name} in {namespace} has no data.")
            except Exception as e:
                logging.error(f"Error processing secret {secret.metadata.name} in {namespace}: {e}")
    except client.exceptions.ApiException as e:
        logging.error(f"Could not list secrets in {namespace}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error processing secrets in {namespace}: {e}")

    return secret_count, total_secret_size_bytes


def _process_pvcs(v1: client.CoreV1Api, namespace: str) -> Tuple[int, int]:
    """Processes PersistentVolumeClaims (PVCs) for counting and sizing.

    Args:
        v1: Initialized CoreV1Api client.
        namespace: The namespace to process.

    Returns:
        A tuple containing the count and total size of PVCs.
    """
    pvc_count = 0
    total_pvc_capacity_bytes = 0

    try:
        pvcs = v1.list_namespaced_persistent_volume_claim(namespace)
        pvc_count = len(pvcs.items)
        for pvc in pvcs.items:
            try:
                if pvc.status and pvc.status.capacity:
                    storage_size_str = pvc.status.capacity.get("storage")
                    if storage_size_str:
                        pvc_bytes = parse_storage_string(storage_size_str)
                        if pvc_bytes is not None:
                            total_pvc_capacity_bytes += pvc_bytes
                        else:
                            logging.warning(f"Could not parse PVC capacity for {pvc.metadata.name} in {namespace}: '{storage_size_str}'")
            except Exception as e:
                logging.error(f"Error processing PVC {pvc.metadata.name} capacity in {namespace}: {e}")
    except client.exceptions.ApiException as e:
        logging.error(f"Could not list PVCs in {namespace}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error processing PVCs in {namespace}: {e}")

    return pvc_count, total_pvc_capacity_bytes


def count_resources(
    namespace: str,
    include_crds: bool,
    api_client: Optional[ApiClient] = None,
    crd_list: Optional[List[Any]] = None,  # Add crd_list parameter
) -> Optional[Dict[str, Any]]:
    """Counts and sizes Kubernetes resources in a namespace.

    Args:
        namespace (str): The namespace to count and size resources in.
        include_crds (bool): Whether to include custom resources (CRDs) in the count and size calculations.
        api_client (Optional[ApiClient], optional): The Kubernetes API client to use. Defaults to None.
        crd_list (Optional[List[Any]], optional): A list of CRDs to process. Defaults to None.

    Returns:
        Optional[Dict[str, Any]]: A dictionary containing the resource counts and sizes for the namespace.
    """
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
        secret_count, total_secret_size_bytes = _process_secrets(v1, namespace)
        namespace_resources["Secrets"] = secret_count

        # PersistentVolumeClaims (Count and Capacity Size)
        pvc_count, total_pvc_capacity_bytes = _process_pvcs(v1, namespace)
        namespace_resources["PersistentVolumeClaims"] = pvc_count
        namespace_resources["TotalPVCCapacityGiB"] = round(total_pvc_capacity_bytes / (1024**3), 2)

        # ServiceAccounts (Count only)
        service_accounts = v1.list_namespaced_service_account(namespace)
        namespace_resources["ServiceAccounts"] = len(service_accounts.items)

        # Endpoints (Count only)
        endpoints = v1.list_namespaced_endpoints(namespace)
        namespace_resources["Endpoints"] = len(endpoints.items)

        # --- Count Apps Resources (Counts only for now) ---
        namespace_resources["Deployments"] = len(apps_v1.list_namespaced_deployment(namespace).items)
        namespace_resources["ReplicaSets"] = len(apps_v1.list_namespaced_replica_set(namespace).items)
        namespace_resources["StatefulSets"] = len(apps_v1.list_namespaced_stateful_set(namespace).items)
        namespace_resources["DaemonSets"] = len(apps_v1.list_namespaced_daemon_set(namespace).items)

        # --- Count Batch Resources (Counts only for now) ---
        namespace_resources["Jobs"] = len(batch_v1.list_namespaced_job(namespace).items)
        namespace_resources["CronJobs"] = len(batch_v1.list_namespaced_cron_job(namespace).items)

        # Process Custom Resources if requested and list is available
        if include_crds:
            if crd_list is not None:
                cr_counts, total_cr_size_bytes = _process_custom_resources(custom_api, namespace, crd_list)
                namespace_resources.update(cr_counts)
                namespace_resources["TotalCustomResourceSizeKiB"] = round(total_cr_size_bytes / 1024, 2)
            else:
                logging.error(f"CRD list not provided for namespace {namespace} when include_crds=True. Skipping CRDs.")
                namespace_resources["TotalCustomResourceSizeKiB"] = 0  # Explicitly set to 0

        # Add calculated sizes to the results
        namespace_resources["TotalCoreResourcesSizeKiB"] = round(total_core_resources_size_bytes / 1024, 2)

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


# --- Helper function for Kubernetes Initialization and PV Count --- #
def _initialize_k8s_and_log_pv_count(kubeconfig_path: Optional[str]) -> Optional[ApiClient]:
    """Initializes Kubernetes client and logs the cluster-wide PV count.

    Args:
        kubeconfig_path: Optional path to the kubeconfig file.

    Returns:
        An initialized ApiClient instance or None if initialization fails.
    """
    # --- Use utility function for config loading --- #
    if not load_kube_config_auto(config_file=kubeconfig_path):
        # Error is logged within load_kube_config_auto
        return None

    # --- Get API client *after* config is loaded --- #
    try:
        api_client = client.ApiClient()  # Initialize once
        logger.debug("Kubernetes API client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes API client: {e}")
        return None

    # --- Count Cluster-Wide Persistent Volumes --- #
    try:
        v1_core = client.CoreV1Api(api_client)
        pv_list = v1_core.list_persistent_volume()
        pv_count = len(pv_list.items)
        logging.info(f"Cluster-wide PersistentVolume count: {pv_count}")
    except client.exceptions.ApiException as e:
        # Log error but don't fail initialization just because PV count failed
        logging.error(f"Could not list PersistentVolumes: {e}. Skipping PV count.")
    except Exception as e:
        logging.error(f"Unexpected error counting PersistentVolumes: {e}")

    return api_client


# --- Helper function to handle scanning all namespaces --- #
def _handle_scan_all_namespaces(api_client: ApiClient) -> Optional[List[str]]:
    """Handles the logic for listing all namespaces, including warnings and pauses."""
    logger.info("Attempting to list all namespaces...")
    all_ns = list_all_namespaces(api_client=api_client)
    if all_ns is None:
        logger.error("Could not list namespaces. Please check permissions.")
        return None

    num_ns = len(all_ns)
    logger.info(f"Found {num_ns} total namespaces.")
    if num_ns > 75:
        warning_msg = (
            f"WARNING: Preparing to scan {num_ns} namespaces. "
            "This may take a long time and put significant load on the API server. "
            "Consider using --namespace or --label-selector to limit the scope."
        )
        logger.warning(warning_msg)
        click.echo(
            f"\n{warning_msg}\nPausing for 15 seconds. Press Ctrl+C to cancel scan.\n",
            err=True,
        )
        try:
            time.sleep(15)
            logger.info("Resuming scan...")
        except KeyboardInterrupt:
            logger.warning("Scan cancelled by user during pause.")
            click.echo("Scan cancelled.", err=True)
            return None  # Indicate cancellation
    logger.info(f"Targeting all {num_ns} namespaces for scan.")
    return all_ns


# --- Pre-fetch CRD list if needed --- #
def _pre_fetch_crd_list(include_crds: bool, api_client: ApiClient) -> Optional[List[Any]]:
    """Pre-fetches the CRD list if requested and returns it."""
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
    return cluster_crd_list


# --- Validate mutually exclusive options --- #
def _validate_mutually_exclusive_options(
    target_namespace: Optional[str],
    label_selector: Optional[str],
) -> bool:
    """Validates that only one of target_namespace or label_selector is provided."""
    if target_namespace and label_selector:
        logging.error("Cannot use --namespace and --label-selector simultaneously.")
        click.echo("Error: Cannot use --namespace and --label-selector simultaneously.", err=True)
        return True
    return False


# --- Helper function to determine namespaces to scan --- #
def _determine_namespaces_to_scan(
    api_client: ApiClient,
    target_namespace: Optional[str] = None,
    label_selector: Optional[str] = None,
) -> Optional[List[str]]:
    """Determines the list of namespaces to scan based on input arguments.

    Args:
        api_client: Initialized Kubernetes ApiClient.
        target_namespace: Specific namespace to target (if provided).
        label_selector: Label selector to filter namespaces (if provided).

    Returns:
        A list of namespace names to scan, or None if an error occurs or none are found.
    """
    v1_core_for_ns = client.CoreV1Api(api_client)
    namespaces_to_scan: List[str] = []

    if label_selector:
        logger.info(f"Attempting to list namespaces with label selector: '{label_selector}'")
        try:
            selected_ns_list = v1_core_for_ns.list_namespace(label_selector=label_selector)
            namespaces_to_scan = [ns.metadata.name for ns in selected_ns_list.items]
            if not namespaces_to_scan:
                logger.warning(f"No namespaces found matching label selector: '{label_selector}'")
                return None  # Explicitly return None if no namespaces match
            logger.info(f"Found {len(namespaces_to_scan)} namespaces matching selector.")
        except ApiException as e:
            logger.error(f"Error listing namespaces with selector '{label_selector}': {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error listing namespaces with selector: {e}")
            return None
    elif target_namespace:
        if namespace_exists(target_namespace, api_client=api_client):
            namespaces_to_scan = [target_namespace]
            logger.info(f"Targeting specified namespace: {target_namespace}")
        else:
            logger.error(f"Specified namespace '{target_namespace}' not found or could not be accessed.")
            return None
    else:
        # Delegate to the specific handler for scanning all namespaces
        namespaces_to_scan = _handle_scan_all_namespaces(api_client)
        if namespaces_to_scan is None:
            return None  # Handle errors or cancellation from the helper

    return namespaces_to_scan


# --- Process namespaces concurrently --- #
def _process_namespaces_concurrently(
    namespaces_to_scan: List[str],
    include_crds: bool,
    api_client: ApiClient,
    cluster_crd_list: Optional[List[Any]],
    max_workers: int,
    target_namespace: Optional[str],  # Needed to decide on progress bar
) -> Tuple[List[Dict[str, Any]], set[str], List[str]]:
    """Processes namespaces concurrently using ThreadPoolExecutor.

    Returns:
        A tuple containing:
          - List of dictionaries with resource data per namespace.
          - Set of all unique field names encountered.
          - List of names of namespaces that failed processing.
    """
    all_resources_data: List[Dict[str, Any]] = []
    all_field_names = set(["Namespace"])  # Start with Namespace
    processed_count = 0
    failed_namespaces = []

    logging.info(f"Starting namespace processing with up to {max_workers} worker threads...")
    show_progress = not target_namespace and namespaces_to_scan and len(namespaces_to_scan) > 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ns = {executor.submit(count_resources, ns, include_crds, api_client, cluster_crd_list): ns for ns in namespaces_to_scan}

        iterable_futures = concurrent.futures.as_completed(future_to_ns)
        progress_label = "Processing namespaces"

        if show_progress:
            logging.info(f"Processing {len(namespaces_to_scan)} namespaces with progress bar.")
            iterable_futures = click.progressbar(
                iterable_futures,
                length=len(namespaces_to_scan),
                label=progress_label,
                # item_show_func not practical here as results are out of order
            )
        else:
            if namespaces_to_scan:
                logging.info(f"Processing {len(namespaces_to_scan)} namespace(s).")

        for future in iterable_futures:  # Iterate through futures (with or without progress bar)
            ns = future_to_ns[future]
            try:
                resources = future.result()
                if resources:
                    ns_data = {"Namespace": ns, **resources}
                    all_resources_data.append(ns_data)
                    all_field_names.update(ns_data.keys())
                    logging.info(f"Successfully processed namespace: {ns}. Resources found: {len(resources)}")
                    processed_count += 1
                else:
                    logging.warning(f"No data returned for namespace: {ns}. It might have failed processing.")
                    failed_namespaces.append(ns)
            except Exception as exc:
                logging.error(f"Namespace {ns} generated an exception during processing: {exc}")
                failed_namespaces.append(ns)
            # No bar.update() needed here, click.progressbar handles it when iterating

    logging.info(f"Finished processing namespaces. Successful: {processed_count}, Failed: {len(failed_namespaces)}.")
    if failed_namespaces:
        logging.warning(f"Failed namespaces: {', '.join(failed_namespaces)}")

    return all_resources_data, all_field_names, failed_namespaces


def _determine_output_file_path(
    output_file: Optional[str],
    target_namespace: Optional[str],
    include_crds: bool,
    sizes_only: bool,
    timestamp: str,
) -> str:
    """Determines the final output file path based on provided arguments."""
    final_output_file: str
    if output_file:
        final_output_file = output_file
        logging.info(f"Using specified output file: {final_output_file}")
    else:
        scope_name = sanitize_filename(target_namespace) if target_namespace else "all_namespaces"
        suffix = "_resources"
        if include_crds:
            suffix += "_with_crds"
        if sizes_only:
            suffix += "_sizes_only"
        final_output_file = f"tmp/{scope_name}{suffix}_{timestamp}.csv"
        logging.info(f"Using generated default output file: {final_output_file}")
    return final_output_file


# --- Helper function to determine CSV headers --- #
def _determine_csv_headers(all_field_names: set[str], sizes_only: bool) -> List[str]:
    """Determines the order of field names for the CSV header."""
    size_fields = sorted([f for f in all_field_names if f.endswith(("KiB", "GiB"))])
    if sizes_only:
        ordered_fieldnames = ["Namespace"] + size_fields
        logging.info("Sizes only flag detected, outputting only namespace and size columns.")
    else:
        count_fields = sorted([f for f in all_field_names if not f.endswith(("KiB", "GiB")) and f != "Namespace"])
        ordered_fieldnames = ["Namespace"] + count_fields + size_fields
    return ordered_fieldnames


# --- Write output to CSV --- #
def _write_output_csv(
    all_resources_data: List[Dict[str, Any]],
    all_field_names: set[str],
    sizes_only: bool,
    output_file: Optional[str],
    target_namespace: Optional[str],
    include_crds: bool,
    timestamp: str,
) -> None:
    """Determines output file path and writes data to a CSV file with locking."""
    if not all_resources_data:
        logging.warning("No data collected from any namespace. CSV file will not be created.")
        return

    # Determine CSV Headers
    ordered_fieldnames = _determine_csv_headers(all_field_names, sizes_only)

    # Determine final output file path
    final_output_file = _determine_output_file_path(output_file, target_namespace, include_crds, sizes_only, timestamp)

    # Ensure the output directory exists
    try:
        output_dir = os.path.dirname(final_output_file)
        if output_dir:
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
            try:
                with open(final_output_file, mode="w", newline="", encoding="utf-8") as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=ordered_fieldnames, restval="0", extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(all_resources_data)
                    logging.info(f"Successfully wrote data for {len(all_resources_data)} namespaces to {final_output_file}")
            except IOError as e:
                logging.error(f"Error writing to output file {final_output_file}: {e}")
            except Exception as e:
                logging.error(f"An unexpected error occurred during file writing: {e}")
    finally:
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
                logging.debug(f"Removed lock file: {lock_path}")
            except OSError as e_rm:
                logging.warning(f"Could not remove lock file {lock_path}: {e_rm}")


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
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(
    target_namespace: Optional[str],
    include_crds: bool,
    output_file: str,
    kubeconfig: Optional[str],
    sizes_only: bool,
    label_selector: Optional[str],
    max_workers: int,
    debug: bool,
):
    """Counts Kubernetes resources and calculates sizes for ConfigMaps, Secrets, PVC capacity, and optionally Custom Resources within specified namespaces."""
    # --- Setup Timestamp --- #
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # --- Setup Logging --- #
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)  # Pass script_name
    logger.debug("Logging setup complete.")

    logging.info("Threaded script execution started.")

    start_time = time.monotonic()  # Record start time

    # --- Validate mutually exclusive options --- #
    if _validate_mutually_exclusive_options(target_namespace, label_selector):
        return

    # --- Initialize K8s Client and Log PV Count --- #
    api_client = _initialize_k8s_and_log_pv_count(kubeconfig)
    if api_client is None:
        # Errors should have been logged in the helper function
        return

    # --- Determine Namespaces to Scan --- #
    namespaces_to_scan = _determine_namespaces_to_scan(api_client, target_namespace, label_selector)
    if namespaces_to_scan is None:
        # Error or no namespaces found, message logged in helper
        return

    # --- Pre-fetch CRD list if needed --- #
    cluster_crd_list = _pre_fetch_crd_list(include_crds, api_client)

    # --- Process Namespaces Concurrently --- #
    all_resources_data, all_field_names, failed_namespaces = _process_namespaces_concurrently(
        namespaces_to_scan,
        include_crds,
        api_client,
        cluster_crd_list,
        max_workers,
        target_namespace,
    )

    # --- Write Output CSV --- #
    _write_output_csv(
        all_resources_data,
        all_field_names,
        sizes_only,
        output_file,
        target_namespace,
        include_crds,
        timestamp,
    )

    end_time = time.monotonic()  # Record end time
    duration = end_time - start_time
    logging.info(f"Total execution time: {format_duration(duration)}")  # Use the helper function
    logging.info("Script execution finished.")  # Goes to file log


if __name__ == "__main__":
    main()
