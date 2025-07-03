#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Counts Kubernetes resources in namespaces filtered by label and storage type (NFS vs non-NFS)."""

import concurrent.futures
import csv
import datetime
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple, Union

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
    parse_storage_string,
)
from pyplayground.utils.logging_utils import get_logger, setup_logging

# --- Logging Setup ---
# Logger will be initialized in main after setup_logging
logger = logging.getLogger(__name__)

# --- Constants ---
# Define default output directory relative to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "tmp")


# === Helper Functions (Combined & Adapted) ===


def handle_datetime(obj):
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def get_object_size(obj: Any) -> int:
    """Serializes an object to JSON and returns its size in bytes."""
    try:
        if hasattr(obj, "to_dict"):
            obj_dict = obj.to_dict()
        elif isinstance(obj, dict):
            obj_dict = obj
        else:
            logger.warning(f"Cannot determine size for object of type {type(obj)}")
            return 0
        json_str = json.dumps(obj_dict, ensure_ascii=False, default=handle_datetime)
        return len(json_str.encode("utf-8"))
    except Exception as e:
        logger.error(f"Error serializing object to calculate size: {e}")
        return 0


def sanitize_filename(name: str) -> str:
    """Removes or replaces characters invalid for typical filenames."""
    name = name.strip().replace(" ", "_")
    # Remove characters that are generally problematic in filenames across OSes
    # Escape the hyphen to treat it literally
    name = re.sub(r'[<>:"/\\|?*\-]', "", name)
    # Replace sequences of underscores or invalid replacements with a single underscore
    name = re.sub(r"_+", "_", name)
    # Handle potential empty string after sanitization
    return name if name else "invalid_name"


# === Storage Analysis Functions (Adapted from k8s_pv_pvc_volume_check.py) ===


def _is_nfs_pv(pv: Dict) -> bool:
    """Check if a PV is NFS type."""
    is_nfs = pv.get("spec", {}).get("nfs") is not None
    logger.debug(f"PV '{pv.get('metadata', {}).get('name', 'N/A')}' is NFS: {is_nfs}")
    return is_nfs


def _build_pv_type_map(pvs: List[Dict]) -> Dict[str, bool]:
    """Build a map of PV name to its NFS status."""
    pv_type_map = {
        pv["metadata"]["name"]: _is_nfs_pv(pv)
        for pv in pvs
        if "metadata" in pv and "name" in pv["metadata"]
    }
    logger.debug(f"Built PV type map for {len(pv_type_map)} PVs.")
    return pv_type_map


def _calculate_namespace_storage_types(
    pvcs: List[Dict], pv_type_map: Dict[str, bool]
) -> Dict[str, Dict[str, bool]]:
    """Calculate storage types used per namespace based on PVCs."""
    namespace_storage: Dict[str, Dict[str, bool]] = defaultdict(
        lambda: {"nfs": False, "non_nfs": False}
    )
    for pvc in pvcs:
        namespace = pvc.get("metadata", {}).get("namespace")
        pv_name = pvc.get("spec", {}).get("volume_name")
        pvc_name = pvc.get("metadata", {}).get("name") or "N/A"

        if not namespace:
            logger.warning(f"Skipping PVC with missing namespace: {pvc_name}")
            continue

        if pv_name and pv_name in pv_type_map:
            is_nfs = pv_type_map[pv_name]
            if is_nfs and not namespace_storage[namespace]["nfs"]:
                logger.debug(
                    f"Namespace '{namespace}' uses NFS storage (via PVC '{pvc_name}' -> PV '{pv_name}')."
                )
                namespace_storage[namespace]["nfs"] = True
            elif not is_nfs and not namespace_storage[namespace]["non_nfs"]:
                logger.debug(
                    f"Namespace '{namespace}' uses non-NFS storage (via PVC '{pvc_name}' -> PV '{pv_name}')."
                )
                namespace_storage[namespace]["non_nfs"] = True
        elif pv_name:
            logger.warning(
                f"PVC '{namespace}/{pvc_name}' references PV '{pv_name}' which was not found in the PV map."
            )
        else:
            pvc_status = pvc.get("status", {}).get("phase", "Unknown")
            logger.debug(
                f"PVC '{namespace}/{pvc_name}' is in phase '{pvc_status}' and has no volumeName."
            )

    return dict(namespace_storage)  # Convert back to regular dict


def perform_cluster_storage_analysis(api_client: ApiClient) -> Dict[str, Dict[str, bool]]:
    """Fetches all PVs/PVCs and determines storage types used by each namespace."""
    logger.info("Performing cluster-wide storage analysis...")
    core_v1 = client.CoreV1Api(api_client)
    pvs_data = []
    pvcs_data = []

    try:
        logger.debug("Fetching all PersistentVolumes.")
        pvs = core_v1.list_persistent_volume()
        pvs_data = [pv.to_dict() for pv in pvs.items]
        logger.info(f"Found {len(pvs_data)} PersistentVolumes.")
    except ApiException as e:
        logger.error(f"Failed to get PVs: {e.status} - {e.reason}")
        # Allow continuing without PVs, but storage analysis will be incomplete
    except Exception as e:
        logger.exception(f"Unexpected error getting PVs: {e}")

    try:
        logger.debug("Fetching all PersistentVolumeClaims.")
        pvcs = core_v1.list_persistent_volume_claim_for_all_namespaces()
        pvcs_data = [pvc.to_dict() for pvc in pvcs.items]
        logger.info(f"Found {len(pvcs_data)} PersistentVolumeClaims across all namespaces.")
    except ApiException as e:
        logger.error(f"Failed to get PVCs: {e.status} - {e.reason}")
        # Allow continuing without PVCs, but storage analysis will be incomplete
    except Exception as e:
        logger.exception(f"Unexpected error getting PVCs: {e}")

    if not pvs_data:
        logger.warning("No PVs found or retrieved. Storage type analysis may be inaccurate.")
        return {}
    if not pvcs_data:
        logger.info("No PVCs found. No namespaces appear to be using persistent storage.")
        return {}

    pv_type_map = _build_pv_type_map(pvs_data)
    namespace_storage_map = _calculate_namespace_storage_types(pvcs_data, pv_type_map)
    logger.info("Cluster-wide storage analysis complete.")
    return namespace_storage_map


# === Resource Counting Functions (Adapted from k8s_rcrscountsize_threaded.py) ===


def _calculate_crd_items_size(
    custom_api: client.CustomObjectsApi,
    namespace: str,
    group: str,
    version: str,
    plural: str,
    kind: str,
    items: List[Dict[str, Any]],
) -> int:
    """Calculates the total size of items for a specific CRD kind."""
    total_size = 0
    for item in items:
        try:
            item_name = item.get("metadata", {}).get("name")
            if not item_name:
                logger.warning(
                    f"Skipping CR item size calculation in {namespace} for kind {kind} due to missing metadata.name"
                )
                continue
            full_cr = custom_api.get_namespaced_custom_object(
                group=group, version=version, namespace=namespace, plural=plural, name=item_name
            )
            total_size += get_object_size(full_cr)
        except ApiException as e_get:
            if e_get.status == 404:
                logger.warning(
                    f"CR {kind} instance {item_name} not found in {namespace} during size calculation (may have been deleted)."
                )
            else:
                logger.error(
                    f"Could not read CR {kind} instance {item_name} in {namespace}: {e_get.status} - {e_get.reason}"
                )
        except Exception as e_size:
            logger.error(
                f"Error calculating size for CR {kind} instance {item_name} in {namespace}: {e_size}"
            )
    return total_size


def _list_custom_resource_items(
    custom_api: client.CustomObjectsApi,
    namespace: str,
    group: str,
    version: str,
    plural: str,
    kind: str,  # For logging
) -> Optional[List[Dict[str, Any]]]:
    """Lists all items for a specific custom resource, handling pagination.

    Returns:
        List of items if successful or no items found, None if a listing error occurred.
    """
    items: List[Dict[str, Any]] = []
    continue_token = None
    try:
        while True:
            logger.debug(
                f"Listing CRD {kind} ({group}/{version}) in {namespace} (continue={continue_token is not None})..."
            )
            custom_objects = custom_api.list_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                limit=500,
                _continue=continue_token,
            )
            current_items = custom_objects.get("items", [])
            items.extend(current_items)

            # Safely get the next continue token from metadata
            continue_token = getattr(getattr(custom_objects, "metadata", None), "_continue", None)
            if not continue_token:
                break  # Exit loop if no more pages
        logger.debug(f"Found {len(items)} total items for CRD {kind} in {namespace}.")
        return items
    except ApiException as e_list:
        if e_list.status == 403:
            logger.warning(
                f"Permission denied listing {kind} ({group}/{version}) in {namespace}. Skipping."
            )
        elif e_list.status != 404:  # Log other API errors
            logger.error(
                f"Could not list instances for {kind} ({group}/{version}) in namespace {namespace}: {e_list.status} - {e_list.reason}"
            )
        # If 404, it might just mean no instances exist, which is fine, return empty list implicitly handled by return items
        return None  # Indicate error or no permissions
    except Exception as e_general:
        logger.error(f"Unexpected error listing CRD {kind} in namespace {namespace}: {e_general}")
        return None  # Indicate error


def _process_custom_resources(
    custom_api: client.CustomObjectsApi,
    namespace: str,
    crd_list: List[Any],
) -> Tuple[Dict[str, int], int]:
    """Processes custom resources (CRDs) for counting and sizing."""
    cr_counts = defaultdict(int)
    total_cr_size_bytes = 0

    for crd in crd_list:
        # --- CRD Spec Validation ---
        if not (
            hasattr(crd, "spec")
            and crd.spec
            and crd.spec.group
            and crd.spec.versions
            and hasattr(crd, "metadata")
            and crd.metadata
            and crd.metadata.name  # Check metadata existence
            and crd.spec.names
            and crd.spec.names.plural
            and crd.spec.names.kind
        ):
            crd_name = getattr(getattr(crd, "metadata", None), "name", "Unknown CRD")
            logger.warning(f"Skipping CRD with incomplete spec: {crd_name}")
            continue

        group = crd.spec.group
        versions = crd.spec.versions
        plural = crd.spec.names.plural
        kind = crd.spec.names.kind

        if not versions:
            logger.warning(
                f"Skipping CRD {kind} ({crd.metadata.name}) as it has no versions defined."
            )
            continue

        stored_version = next((v.name for v in versions if v.storage), None)
        version = stored_version if stored_version else versions[0].name
        # --- End CRD Spec Validation ---

        logger.debug(f"Processing CRD {kind} using version {version} in namespace {namespace}")

        # --- List Items using Helper ---
        items = _list_custom_resource_items(custom_api, namespace, group, version, plural, kind)
        # --- End List Items ---

        if items is not None:  # Proceed only if listing was successful (or returned empty list)
            cr_counts[kind] = len(items)
            if items:  # Only calculate size if items exist
                total_cr_size_bytes += _calculate_crd_items_size(
                    custom_api, namespace, group, version, plural, kind, items
                )
        # If items is None, an error occurred during listing and was logged by the helper

    return dict(cr_counts), total_cr_size_bytes


def _get_single_secret_size(v1: client.CoreV1Api, name: str, namespace: str) -> int:
    """Reads a single secret and returns its object size, handling errors."""
    try:
        full_secret = v1.read_namespaced_secret(name=name, namespace=namespace)
        return get_object_size(full_secret)
    except ApiException as e_read:
        if e_read.status == 404:
            logger.warning(
                f"Secret {name} not found during size calculation in {namespace} (deleted?)."
            )
        else:
            logger.error(
                f"Could not read Secret {name} in {namespace} for size: {e_read.status} - {e_read.reason}"
            )
        return 0  # Return 0 size on read error
    except Exception as e_size:
        logger.error(f"Error calculating size for Secret {name} in {namespace}: {e_size}")
        return 0  # Return 0 size on calculation error


def _process_secrets(v1: client.CoreV1Api, namespace: str) -> Tuple[int, int]:
    """Processes Secrets for counting and full object sizing."""
    total_secret_object_size_bytes = 0

    # Use helper to get count and names, handles listing errors/pagination
    list_result = _list_and_count_resource(
        v1.list_namespaced_secret, "Secrets", namespace, return_names=True
    )

    # Check the type returned by the helper
    if isinstance(list_result, tuple):
        secret_count, secret_names = list_result
    else:
        # Should not happen if return_names=True, but handle defensively
        logger.error(f"_list_and_count_resource did not return names for Secrets in {namespace}")
        secret_count = list_result
        secret_names = []

    if secret_count > 0 and secret_names:
        logger.debug(f"Calculating size for {secret_count} Secrets in {namespace}")
        # Read each secret individually using names to calculate its object size
        for secret_name in secret_names:
            total_secret_object_size_bytes += _get_single_secret_size(v1, secret_name, namespace)
    elif secret_count > 0:
        logger.warning(
            f"Secret count is {secret_count} but no names were retrieved for sizing in {namespace}. Size will be 0."
        )

    # Note: The size reported is the full object definition size (JSON), not just the data size.
    return secret_count, total_secret_object_size_bytes


def _process_resource_page(
    list_func,
    resource_name: str,
    namespace: str,
    continue_token: Optional[str],
) -> Tuple[
    Optional[List[Any]], Optional[str], bool
]:  # Returns: (items, next_token, error_occurred)
    """Processes a single page of resources from a list function."""
    try:
        logger.debug(
            f"Listing page of {resource_name} in {namespace} (continue={continue_token is not None})..."
        )
        listed_objects = list_func(namespace, limit=500, _continue=continue_token)
        items = listed_objects.items
        next_token = getattr(getattr(listed_objects, "metadata", None), "_continue", None)
        return items, next_token, False  # No error
    except ApiException as e_list:
        if e_list.status != 404:
            logger.error(
                f"API error listing {resource_name} page in {namespace}: {e_list.status} - {e_list.reason}"
            )
        # Treat 404 as non-fatal for a single page, but signal error for others
        return None, None, e_list.status != 404
    except Exception as e:
        logger.error(f"Unexpected error listing {resource_name} page in {namespace}: {e}")
        return None, None, True  # Signal error


def _process_items_page(
    current_items: List[Any],
    return_names: bool,
    return_items: bool,
    all_item_names: List[str],
    all_items: List[Dict[str, Any]],
) -> int:
    """Processes a page of items, updating names/items lists and returning count."""
    count = len(current_items)
    if return_names:
        all_item_names.extend(
            [
                item.metadata.name
                for item in current_items
                if hasattr(item, "metadata") and hasattr(item.metadata, "name")
            ]
        )
    elif return_items:
        all_items.extend([item.to_dict() for item in current_items if hasattr(item, "to_dict")])
    return count


def _list_and_count_resource(
    list_func,
    resource_name: str,
    namespace: str,
    return_names: bool = False,
    return_items: bool = False,
) -> Union[int, Tuple[int, List[str]], Tuple[int, List[Dict[str, Any]]]]:
    """Lists a specific resource type, handling pagination.

    Returns count, count & names, or count & full items based on flags.
    """
    total_count = 0
    all_items: List[Dict[str, Any]] = []  # Store dict representation if return_items
    all_item_names: List[str] = []  # Store names if return_names
    continue_token: Optional[str] = ""  # Use empty string to start the first iteration
    error_occurred = False

    if return_names and return_items:
        raise ValueError("Cannot set both return_names and return_items to True.")

    while continue_token is not None:
        current_items, next_token, page_error = _process_resource_page(
            list_func,
            resource_name,
            namespace,
            continue_token if continue_token else None,  # Pass None for first call
        )

        if page_error:
            error_occurred = True
            break  # Stop processing if a page fails critically

        if current_items is not None:
            # Process the items from the current page using the helper
            page_count = _process_items_page(
                current_items, return_names, return_items, all_item_names, all_items
            )
            total_count += page_count

        continue_token = next_token  # Move to next page or stop if None

    logger.debug(
        f"Finished listing {resource_name} in {namespace}. Total found: {total_count}. Error status: {error_occurred}"
    )

    # Simplified return logic
    if error_occurred:
        # Return default error values based on requested type
        if return_items:
            return 0, []
        elif return_names:
            return 0, []
        else:
            return 0
    else:
        # Return successfully collected data
        if return_items:
            return total_count, all_items
        elif return_names:
            return total_count, all_item_names
        else:
            return total_count


def _get_pvc_capacity(pvc_item: Dict[str, Any]) -> int:
    """Parses the storage capacity from a single PVC item dictionary.

    Args:
        pvc_item: A dictionary representing a PVC object.

    Returns:
        The capacity in bytes, or 0 if not found or unparsable.
    """
    pvc_name = pvc_item.get("metadata", {}).get("name", "Unknown")
    namespace = pvc_item.get("metadata", {}).get("namespace", "Unknown")
    try:
        storage_size_str = None
        # Prefer status.capacity if available (actual provisioned size)
        if pvc_item.get("status") and pvc_item["status"].get("capacity"):
            storage_size_str = pvc_item["status"]["capacity"].get("storage")
        # Fallback to spec.resources.requests if status/capacity not present
        elif (
            pvc_item.get("spec")
            and pvc_item["spec"].get("resources")
            and pvc_item["spec"]["resources"].get("requests")
        ):
            storage_size_str = pvc_item["spec"]["resources"]["requests"].get("storage")

        if storage_size_str:
            pvc_bytes = parse_storage_string(storage_size_str)
            if pvc_bytes is not None:
                return pvc_bytes
            else:
                logger.warning(
                    f"Could not parse PVC size for {pvc_name} in {namespace}: '{storage_size_str}'"
                )
                return 0
        else:
            # logger.debug(f"PVC {pvc_name} in {namespace} has no storage size specified/provisioned.")
            return 0
    except Exception as e:
        logger.error(f"Error processing PVC {pvc_name} size in {namespace}: {e}")
        return 0


def _process_pvcs(v1: client.CoreV1Api, namespace: str) -> Tuple[int, int]:
    """Processes PersistentVolumeClaims (PVCs) for counting and capacity sizing."""
    total_pvc_capacity_bytes = 0

    # Use helper to get count and items
    list_result = _list_and_count_resource(
        v1.list_namespaced_persistent_volume_claim, "PVCs", namespace, return_items=True
    )

    # Check the type returned by the helper
    if isinstance(list_result, tuple) and len(list_result) == 2:
        pvc_count, pvc_items = list_result
    else:
        # Should not happen if return_items=True, but handle defensively
        logger.error(f"_list_and_count_resource did not return items for PVCs in {namespace}")
        pvc_count = list_result if isinstance(list_result, int) else 0
        pvc_items = []

    if pvc_count > 0 and pvc_items:
        logger.debug(f"Calculating capacity for {pvc_count} PVCs in {namespace}")
        for pvc_item in pvc_items:
            total_pvc_capacity_bytes += _get_pvc_capacity(pvc_item)
    elif pvc_count > 0:
        logger.warning(
            f"PVC count is {pvc_count} but no items were retrieved for sizing in {namespace}. Capacity will be 0."
        )

    return pvc_count, total_pvc_capacity_bytes


def _count_core_v1_standard_resources(
    v1: client.CoreV1Api, namespace: str
) -> Tuple[Dict[str, int], int]:
    """Counts standard CoreV1 resources and sizes ConfigMaps."""
    counts = defaultdict(int)
    total_cm_size_bytes = 0
    cm_names: List[str] = []  # Store CM names here

    core_resources = {
        "Pods": v1.list_namespaced_pod,
        "Services": v1.list_namespaced_service,
        "ConfigMaps": v1.list_namespaced_config_map,
        "ServiceAccounts": v1.list_namespaced_service_account,
        "Endpoints": v1.list_namespaced_endpoints,
    }

    for name, list_func in core_resources.items():
        if name == "ConfigMaps":
            # Request names along with the count for ConfigMaps
            count_result, name_result = _list_and_count_resource(
                list_func, name, namespace, return_names=True
            )
            counts[name] = count_result
            cm_names = name_result  # Store names for sizing below
        else:
            # Just get the count for other resources
            counts[name] = _list_and_count_resource(list_func, name, namespace)

    # ConfigMap sizing using the fetched names
    if counts["ConfigMaps"] > 0 and cm_names:
        logger.debug(f"Calculating size for {len(cm_names)} ConfigMaps in {namespace}")
        for cm_name in cm_names:
            try:
                full_cm = v1.read_namespaced_config_map(name=cm_name, namespace=namespace)
                total_cm_size_bytes += get_object_size(full_cm)
            except ApiException as e_read:
                if e_read.status == 404:
                    logger.warning(
                        f"ConfigMap {cm_name} not found in {namespace} during size calc (deleted?)."
                    )
                else:
                    logger.error(
                        f"Could not read ConfigMap {cm_name} in {namespace} for size: {e_read.status} - {e_read.reason}"
                    )
            except Exception as e_size:
                logger.error(
                    f"Error calculating size for ConfigMap {cm_name} in {namespace}: {e_size}"
                )
    elif counts["ConfigMaps"] > 0 and not cm_names:
        # This case might happen if _list_and_count_resource fails partially or names couldn't be extracted
        logger.warning(
            f"ConfigMap count is {counts['ConfigMaps']} but no names were retrieved for sizing in {namespace}. Size will be 0."
        )

    return dict(counts), total_cm_size_bytes


def _count_apps_v1_resources(apps_v1: client.AppsV1Api, namespace: str) -> Dict[str, int]:
    """Counts standard AppsV1 resources."""
    counts = defaultdict(int)
    apps_resources = {
        "Deployments": apps_v1.list_namespaced_deployment,
        "ReplicaSets": apps_v1.list_namespaced_replica_set,
        "StatefulSets": apps_v1.list_namespaced_stateful_set,
        "DaemonSets": apps_v1.list_namespaced_daemon_set,
    }
    for name, list_func in apps_resources.items():
        counts[name] = _list_and_count_resource(list_func, name, namespace)
    return dict(counts)


def _count_batch_v1_resources(batch_v1: client.BatchV1Api, namespace: str) -> Dict[str, int]:
    """Counts standard BatchV1 resources."""
    counts = defaultdict(int)
    batch_resources = {
        "Jobs": batch_v1.list_namespaced_job,
        "CronJobs": batch_v1.list_namespaced_cron_job,
    }
    for name, list_func in batch_resources.items():
        counts[name] = _list_and_count_resource(list_func, name, namespace)
    return dict(counts)


def count_resources(
    namespace: str,
    include_crds: bool,
    api_client: ApiClient,  # Must be passed for thread safety
    cluster_crd_list: Optional[List[Any]],
) -> Optional[Dict[str, Any]]:
    """Counts and sizes Kubernetes resources in a single namespace."""
    # Create API client instances *within* the function for thread safety
    # Using the passed api_client which should be thread-safe or configured appropriately
    try:
        v1 = client.CoreV1Api(api_client)
        apps_v1 = client.AppsV1Api(api_client)
        batch_v1 = client.BatchV1Api(api_client)
        custom_api = client.CustomObjectsApi(api_client)
        # Add other required API groups here if needed (e.g., networking.k8s.io)
        # net_v1 = client.NetworkingV1Api(api_client)

    except Exception as e:
        logger.error(f"Failed to initialize API clients for namespace {namespace}: {e}")
        return None

    namespace_resources = defaultdict(int)
    total_cm_size_bytes = 0
    total_cr_size_bytes = 0
    total_pvc_capacity_bytes = 0
    total_secret_size_bytes = 0

    try:
        # --- Count Standard Resources --- #
        logger.debug(f"Counting standard resources in namespace: {namespace}")

        core_counts, total_cm_size_bytes = _count_core_v1_standard_resources(v1, namespace)
        namespace_resources.update(core_counts)

        apps_counts = _count_apps_v1_resources(apps_v1, namespace)
        namespace_resources.update(apps_counts)

        batch_counts = _count_batch_v1_resources(batch_v1, namespace)
        namespace_resources.update(batch_counts)

        # Add other API group counts here if needed (e.g., networking)
        # net_counts = _count_networking_v1_resources(net_v1, namespace)
        # namespace_resources.update(net_counts)

        # --- Process Secrets --- #
        secret_count, total_secret_size_bytes = _process_secrets(v1, namespace)
        namespace_resources["Secrets"] = secret_count
        namespace_resources["TotalSecretObjectSizeKiB"] = round(total_secret_size_bytes / 1024, 2)

        # --- Process PVCs --- #
        pvc_count, total_pvc_capacity_bytes = _process_pvcs(v1, namespace)
        namespace_resources["PersistentVolumeClaims"] = pvc_count
        namespace_resources["TotalPVCCapacityGiB"] = round(total_pvc_capacity_bytes / (1024**3), 2)

        # --- Process Custom Resources (Optional) --- #
        if include_crds:
            if cluster_crd_list is not None:
                logger.debug(f"Processing CRDs in namespace: {namespace}")
                cr_counts, total_cr_size_bytes = _process_custom_resources(
                    custom_api, namespace, cluster_crd_list
                )
                namespace_resources.update(cr_counts)
                namespace_resources["TotalCustomResourceSizeKiB"] = round(
                    total_cr_size_bytes / 1024, 2
                )
            else:
                logger.warning(
                    f"CRD list not available for namespace {namespace} when include_crds=True. Skipping CRDs."
                )
                namespace_resources["TotalCustomResourceSizeKiB"] = 0

        # --- Final Size Aggregation --- #
        # Note: TotalCoreResourcesSizeKiB is currently only CM size.
        # Secrets size is reported separately as TotalSecretObjectSizeKiB.
        namespace_resources["TotalConfigMapSizeKiB"] = round(total_cm_size_bytes / 1024, 2)

    except ApiException as e:
        # Handle potential 403 Forbidden for the entire namespace
        if e.status == 403:
            logger.error(
                f"Permission denied accessing resources in namespace {namespace}. Skipping."
            )
        else:
            logger.error(
                f"General K8s API error counting resources in namespace {namespace}: {e.status} - {e.reason}"
            )
        return None
    except Exception as e:
        logger.error(
            f"Unexpected error counting resources in namespace {namespace}: {e}", exc_info=True
        )  # Add traceback
        return None

    return dict(namespace_resources)  # Convert back to regular dict


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
            # Explicitly exit the script
            sys.exit(1)  # Use exit code 1 for cancellation
    logger.info(f"Targeting all {num_ns} namespaces for scan.")
    return all_ns


# --- Namespace Filtering and Processing ---
def _determine_namespaces_to_scan(
    api_client: ApiClient,
    target_namespace: Optional[str],
    label_selector: str,
) -> Optional[List[str]]:
    """Determines the list of namespaces to scan based on label selector or target namespace."""
    v1_core_for_ns = client.CoreV1Api(api_client)
    namespaces_to_scan: List[str] = []

    if target_namespace:
        namespaces_to_scan.append(target_namespace)
    elif label_selector:
        logger.info(f"Attempting to list namespaces with label selector: '{label_selector}'")
        try:
            selected_ns_list = v1_core_for_ns.list_namespace(label_selector=label_selector)
            namespaces_to_scan = [ns.metadata.name for ns in selected_ns_list.items]
            if not namespaces_to_scan:
                logger.warning(f"No namespaces found matching label selector: '{label_selector}'")
                return None
            logger.info(
                f"Found {len(namespaces_to_scan)} namespaces matching selector: {', '.join(namespaces_to_scan)}"
            )
        except ApiException as e:
            logger.error(
                f"Error listing namespaces with selector '{label_selector}': {e.status} - {e.reason}"
            )
            return None
        except Exception as e:
            logger.error(f"Unexpected error listing namespaces with selector: {e}")
            return None
    else:
        namespaces_to_scan = _handle_scan_all_namespaces(api_client)
        if namespaces_to_scan is None:
            return None

    return namespaces_to_scan


def _filter_namespaces_by_storage(
    target_namespaces: List[str],
    namespace_storage_map: Dict[str, Dict[str, bool]],
    filter_mode: str,
) -> Tuple[List[str], List[str]]:
    """Filters the target namespace list based on storage type and filter mode."""
    namespaces_to_process: List[str] = []
    filtered_out_namespaces: List[str] = []

    for ns in target_namespaces:
        storage_info = namespace_storage_map.get(ns, {"nfs": False, "non_nfs": False})
        is_nfs_only = storage_info["nfs"] and not storage_info["non_nfs"]

        if filter_mode == "exclude-nfs":
            if is_nfs_only:
                filtered_out_namespaces.append(ns)
                logger.debug(
                    f"Filtering out namespace '{ns}' (NFS Only) based on mode '{filter_mode}'."
                )
            else:  # Includes non-NFS only, mixed, and those with no PVCs/PVs found
                namespaces_to_process.append(ns)
                logger.debug(
                    f"Including namespace '{ns}' for processing based on mode '{filter_mode}'."
                )
        elif filter_mode == "only-nfs":
            if is_nfs_only:
                namespaces_to_process.append(ns)
                logger.debug(
                    f"Including namespace '{ns}' (NFS Only) for processing based on mode '{filter_mode}'."
                )
            else:
                filtered_out_namespaces.append(ns)
                logger.debug(f"Filtering out namespace '{ns}' based on mode '{filter_mode}'.")

    logger.info(
        f"Filter mode '{filter_mode}': {len(namespaces_to_process)} namespaces will be processed, {len(filtered_out_namespaces)} namespaces filtered out."
    )
    return namespaces_to_process, filtered_out_namespaces


def _pre_fetch_crd_list(api_client: ApiClient) -> Optional[List[Any]]:
    """Pre-fetches the CRD list."""
    cluster_crd_list: Optional[List[Any]] = None
    logger.info("Pre-fetching Custom Resource Definition list...")
    try:
        # Use ApiextensionsV1Api for CRD listing
        apiext_v1 = client.ApiextensionsV1Api(api_client)
        crd_list_resp = apiext_v1.list_custom_resource_definition()
        cluster_crd_list = crd_list_resp.items
        logger.info(f"Found {len(cluster_crd_list)} CRDs cluster-wide.")
    except ApiException as e:
        logger.error(f"Could not pre-fetch CRD list: {e.status} - {e.reason}. Cannot process CRDs.")
        # Don't disable include_crds flag here, let the main logic handle the None list
    except Exception as e:
        logger.error(f"Unexpected error pre-fetching CRD list: {e}. Cannot process CRDs.")

    return cluster_crd_list


def _process_future_result(
    future: concurrent.futures.Future,
    future_to_ns: Dict[concurrent.futures.Future, str],
    all_resources_data: List[Dict[str, Any]],
    all_field_names: set[str],
    failed_namespaces: List[str],
) -> int:
    """Processes the result of a single future, updating result lists.

    Returns:
        1 if processed successfully, 0 otherwise.
    """
    ns = future_to_ns[future]
    try:
        resources = future.result()  # Get result from future
        if resources is not None:
            # Successfully processed, add Namespace key
            ns_data = {"Namespace": ns, **resources}
            all_resources_data.append(ns_data)
            all_field_names.update(ns_data.keys())
            logger.debug(
                f"Successfully processed namespace: {ns}. Resources found: {len(resources)}"
            )
            return 1  # Indicate success
        else:
            # count_resources returned None, indicating failure
            logger.warning(f"Namespace {ns} failed processing (returned None).")
            failed_namespaces.append(ns)
            return 0  # Indicate failure
    except Exception as exc:
        # Catch exceptions raised during future execution
        logger.error(
            f"Namespace {ns} generated an exception during processing: {exc}", exc_info=True
        )
        failed_namespaces.append(ns)
        return 0  # Indicate failure


def _process_namespaces_concurrently(
    namespaces_to_scan: List[str],
    include_crds: bool,
    api_client: ApiClient,
    cluster_crd_list: Optional[List[Any]],
    max_workers: int,
) -> Tuple[List[Dict[str, Any]], set[str], List[str]]:
    """Processes namespaces concurrently using ThreadPoolExecutor."""
    all_resources_data: List[Dict[str, Any]] = []
    all_field_names = set(["Namespace"])  # Start with Namespace
    processed_count = 0
    failed_namespaces = []

    if not namespaces_to_scan:
        logger.info("No namespaces to process after filtering.")
        return [], set(), []

    logging.info(
        f"Starting processing for {len(namespaces_to_scan)} namespaces with up to {max_workers} worker threads..."
    )

    show_progress = len(namespaces_to_scan) > 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ns = {
            executor.submit(count_resources, ns, include_crds, api_client, cluster_crd_list): ns
            for ns in namespaces_to_scan
        }

        iterable_futures = concurrent.futures.as_completed(future_to_ns)
        progress_label = "Processing namespaces"

        if show_progress:
            logger.info(f"Processing {len(namespaces_to_scan)} namespaces with progress bar.")
            # Use click progressbar as context manager
            with click.progressbar(
                iterable=iterable_futures,
                length=len(namespaces_to_scan),
                label=progress_label,
                item_show_func=lambda p: f"Processed {future_to_ns.get(p, '...')}" if p else "",
            ) as bar:
                for future in bar:
                    processed_count += _process_future_result(
                        future, future_to_ns, all_resources_data, all_field_names, failed_namespaces
                    )
        else:
            logger.info(f"Processing {len(namespaces_to_scan)} namespace(s)...")
            for future in iterable_futures:
                processed_count += _process_future_result(
                    future, future_to_ns, all_resources_data, all_field_names, failed_namespaces
                )

    logging.info(
        f"Finished processing namespaces. Successful: {processed_count}, Failed: {len(failed_namespaces)}."
    )
    if failed_namespaces:
        logging.warning(f"Failed namespaces: {', '.join(failed_namespaces)}")

    return all_resources_data, all_field_names, failed_namespaces


# --- Output Functions ---


def _determine_output_file_path(
    output_file_param: Optional[str],
    label_selector: str,  # Use label selector for default name
    filter_mode: str,
    include_crds: bool,
    sizes_only: bool,
    timestamp: str,
    output_dir: str,  # Pass output dir explicitly
) -> str:
    """Determines the final output file path for the main results."""
    final_output_file: str
    if output_file_param:
        final_output_file = output_file_param
        logger.info(f"Using specified output file: {final_output_file}")
    else:
        # Generate default name
        safe_label = sanitize_filename(label_selector.replace("=", "_").replace(",", "_"))
        suffix = f"_resources_{filter_mode}"
        if include_crds:
            suffix += "_with_crds"
        if sizes_only:
            suffix += "_sizes_only"
        filename = f"{safe_label}{suffix}_{timestamp}.csv"
        final_output_file = os.path.join(output_dir, filename)  # Use output_dir
        logger.info(f"Using generated default output file: {final_output_file}")
    return final_output_file


def _determine_filtered_output_file_path(
    filtered_output_file_param: Optional[str],
    label_selector: str,
    filter_mode: str,
    timestamp: str,
    output_dir: str,  # Pass output dir explicitly
) -> str:
    """Determines the final output file path for the filtered namespaces."""
    final_output_file: str
    if filtered_output_file_param:
        final_output_file = filtered_output_file_param
        logger.info(f"Using specified filtered output file: {final_output_file}")
    else:
        # Generate default name
        safe_label = sanitize_filename(label_selector.replace("=", "_").replace(",", "_"))
        filename = f"{safe_label}_filtered_{filter_mode}_{timestamp}.txt"
        final_output_file = os.path.join(output_dir, filename)  # Use output_dir
        logger.info(f"Using generated default filtered output file: {final_output_file}")
    return final_output_file


def _determine_csv_headers(all_field_names: set[str], sizes_only: bool) -> List[str]:
    """Determines the order of field names for the CSV header."""
    # Identify size fields (KiB or GiB)
    size_fields = sorted([f for f in all_field_names if f.endswith(("KiB", "GiB"))])
    # Identify standard count fields (exclude Namespace and size fields)
    count_fields = sorted(
        [f for f in all_field_names if not f.endswith(("KiB", "GiB")) and f != "Namespace"]
    )

    if sizes_only:
        ordered_fieldnames = ["Namespace"] + size_fields
        logger.info("Sizes only flag detected, outputting only namespace and size columns.")
    else:
        # Order: Namespace, Counts (sorted alphabetically), Sizes (sorted alphabetically)
        ordered_fieldnames = ["Namespace"] + count_fields + size_fields
        logger.debug(f"Determined CSV headers: {ordered_fieldnames}")

    return ordered_fieldnames


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


def _write_main_output_csv(
    all_resources_data: List[Dict[str, Any]],
    all_field_names: set[str],
    sizes_only: bool,
    output_file_param: Optional[str],  # Renamed to avoid conflict
    label_selector: str,
    filter_mode: str,
    include_crds: bool,
    timestamp: str,
    output_dir: str,  # Pass output dir
) -> None:
    """Writes the main processed data to a CSV file with locking."""
    if not all_resources_data:
        logger.warning(
            "No data collected from processed namespaces. Main CSV file will not be created."
        )
        return

    ordered_fieldnames = _determine_csv_headers(all_field_names, sizes_only)
    final_output_file = _determine_output_file_path(
        output_file_param,
        label_selector,
        filter_mode,
        include_crds,
        sizes_only,
        timestamp,
        output_dir,
    )

    # Ensure the output directory exists
    try:
        os.makedirs(os.path.dirname(final_output_file), exist_ok=True)
    except OSError as e:
        logger.error(
            f"Could not create output directory for main CSV '{os.path.dirname(final_output_file)}': {e}"
        )
        return

    lock_path = f"{final_output_file}.lock"
    logger.info(f"Attempting to write main results to {final_output_file}...")
    lock = FileLock(lock_path)
    try:
        with lock:
            logger.debug(f"Acquired lock on {lock_path}")
            try:
                with open(final_output_file, mode="w", newline="", encoding="utf-8") as csvfile:
                    # Use extrasaction='ignore' to handle cases where a namespace might miss a field
                    # Use restval='0' to fill missing counts/sizes with 0
                    writer = csv.DictWriter(
                        csvfile, fieldnames=ordered_fieldnames, restval="0", extrasaction="ignore"
                    )
                    writer.writeheader()
                    writer.writerows(all_resources_data)
                    logger.info(
                        f"Successfully wrote data for {len(all_resources_data)} processed namespaces to {final_output_file}"
                    )
            except IOError as e:
                logger.error(f"Error writing to main output file {final_output_file}: {e}")
            except Exception as e:
                logger.error(f"An unexpected error occurred during main file writing: {e}")
    finally:
        # Ensure lock file is removed
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
                logger.debug(f"Removed lock file: {lock_path}")
            except OSError as e_rm:
                # Log warning if lock removal fails but don't raise
                logger.warning(f"Could not remove lock file {lock_path}: {e_rm}")


def _write_filtered_namespaces(
    filtered_namespaces: List[str],
    filtered_output_file_param: Optional[str],  # Renamed
    label_selector: str,
    filter_mode: str,
    timestamp: str,
    output_dir: str,  # Pass output dir
) -> None:
    """Writes the list of filtered-out namespaces to a text file."""
    if not filtered_namespaces:
        logger.info("No namespaces were filtered out. Filtered output file will not be created.")
        return

    final_output_file = _determine_filtered_output_file_path(
        filtered_output_file_param, label_selector, filter_mode, timestamp, output_dir
    )

    # Ensure the output directory exists
    try:
        os.makedirs(os.path.dirname(final_output_file), exist_ok=True)
    except OSError as e:
        logger.error(
            f"Could not create output directory for filtered list '{os.path.dirname(final_output_file)}': {e}"
        )
        return

    logger.info(
        f"Writing list of {len(filtered_namespaces)} filtered namespaces to {final_output_file}..."
    )
    try:
        with open(final_output_file, mode="w", encoding="utf-8") as f:
            for ns in sorted(filtered_namespaces):  # Sort for consistency
                f.write(f"{ns}\n")
        logger.info(f"Successfully wrote filtered namespace list to {final_output_file}")
    except IOError as e:
        logger.error(f"Error writing to filtered output file {final_output_file}: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during filtered file writing: {e}")


# === Main Click Command ===


@click.command()
@click.option(
    "--kubeconfig",
    required=True,  # Changed to required as per original pv_pvc script logic
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
    envvar="KUBECONFIG",  # Allow setting via KUBECONFIG env var
    help="Path to the kubeconfig file to use.",
)
@click.option(
    "--namespace",
    "target_namespace",  # Explicit variable name
    type=str,
    default=None,
    help="Filter namespaces by name. Cannot be used with --label-selector.",
)
@click.option(
    "--label-selector",
    required=True,  # Make label selector required for this script's purpose
    help="Filter namespaces using a Kubernetes label selector (e.g., 'env=prod,team=alpha').",
)
@click.option(
    "--filter-mode",
    type=click.Choice(["exclude-nfs", "only-nfs"], case_sensitive=False),
    default="exclude-nfs",
    show_default=True,
    help="Filtering mode: 'exclude-nfs' (process non-NFS/mixed), 'only-nfs' (process NFS-only).",
)
@click.option(
    "--include-crds",
    is_flag=True,
    default=False,
    show_default=True,
    help="Include custom resources (CRDs) in the count and size calculations.",
)
@click.option(
    "--output-file",
    "main_output_file",  # Explicit variable name
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Path to output CSV file for processed namespaces. Defaults to tmp/<label>_resources_<mode>_<timestamp>.csv",
)
@click.option(
    "--filtered-output-file",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Path to output text file for filtered-out namespaces. Defaults to tmp/<label>_filtered_<mode>_<timestamp>.txt",
)
@click.option(
    "--sizes-only",
    is_flag=True,
    default=False,
    show_default=True,
    help="Output only namespace and size columns in the main CSV, omitting resource counts.",
)
@click.option(
    "--max-workers",
    type=int,
    default=10,
    show_default=True,
    help="Maximum number of namespaces to process concurrently.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, writable=True),
    default=DEFAULT_OUTPUT_DIR,
    show_default=True,
    help="Directory to save output files.",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(
    kubeconfig: str,
    target_namespace: Optional[str],
    label_selector: str,
    filter_mode: str,
    include_crds: bool,
    main_output_file: Optional[str],
    filtered_output_file: Optional[str],
    sizes_only: bool,
    max_workers: int,
    output_dir: str,
    debug: bool,
):
    """Counts Kubernetes resources and sizes within namespaces selected by a label, filtering based on whether the namespaces use NFS-only storage.

    Args:
        kubeconfig: Path to the kubeconfig file.
        label_selector: Kubernetes label selector for namespaces.
        filter_mode: 'exclude-nfs' or 'only-nfs'.
        include_crds: Flag to include CRD counts/sizes.
        main_output_file: Optional path for the main CSV output.
        filtered_output_file: Optional path for the filtered namespace list.
        sizes_only: Flag to output only size columns in the main CSV.
        max_workers: Max concurrent threads for namespace processing.
        output_dir: Directory to save output files.
        debug: Flag to enable debug logging.
        target_namespace: Optional namespace to filter. Cannot be used with label_selector.

    """
    # --- Setup Timestamp & Logging ---
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    # Use setup_logging from utils, ensuring logs go to output_dir/logs if possible
    # For simplicity, keeping default log dir logic within setup_logging for now.

    setup_logging(level=log_level, script_name=script_base_name)
    # Re-assign logger now that setup is complete
    logger = get_logger(__name__)  # Use utils get_logger

    # Add an early debug message
    logger.debug("Logger setup complete. Script starting main execution.")

    logger.info(f"Starting filtered resource count. Mode: {filter_mode}, Label: '{label_selector}'")
    start_time = time.monotonic()

    # --- Load K8s Config ---
    if not load_kube_config_auto(config_file=kubeconfig):
        logger.error("Failed to load Kubernetes configuration. Exiting.")
        return  # Exit if config fails

    # --- Initialize API Client ---
    try:
        # Consider client configuration options for threading if needed (e.g., pool size)
        api_client = ApiClient()
        logger.debug("Kubernetes API client initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes API client: {e}")
        return

    # --- Perform Cluster Storage Analysis ---
    # This needs to happen *before* filtering namespaces
    namespace_storage_map = perform_cluster_storage_analysis(api_client)

    # --- Validate mutually exclusive options --- #
    if _validate_mutually_exclusive_options(target_namespace, label_selector):
        return

    # --- Determine Target Namespaces ---
    target_namespaces = _determine_namespaces_to_scan(api_client, target_namespace, label_selector)
    if target_namespaces is None:
        logger.error(
            f"Could not find any namespaces matching selector '{label_selector}' or failed to list them. Exiting."
        )
        return

    # --- Filter Namespaces by Storage Type ---
    namespaces_to_process, filtered_out_namespaces = _filter_namespaces_by_storage(
        target_namespaces, namespace_storage_map, filter_mode
    )

    # --- Pre-fetch CRD List if needed ---
    cluster_crd_list = None
    if (
        include_crds and namespaces_to_process
    ):  # Only fetch if needed and if there are namespaces to process
        cluster_crd_list = _pre_fetch_crd_list(api_client)
        if cluster_crd_list is None:
            logger.warning("Proceeding without CRD counts/sizes due to fetch error.")
            include_crds = False  # Ensure CRDs are skipped if fetch failed

    # --- Process Selected Namespaces Concurrently ---
    all_resources_data, all_field_names, failed_namespaces = _process_namespaces_concurrently(
        namespaces_to_process,  # Pass the filtered list
        include_crds,
        api_client,
        cluster_crd_list,
        max_workers,
    )

    # --- Write Main Output CSV ---
    _write_main_output_csv(
        all_resources_data,
        all_field_names,
        sizes_only,
        main_output_file,  # Pass the parameter
        label_selector,
        filter_mode,
        include_crds,
        timestamp,
        output_dir,  # Pass output dir
    )

    # --- Write Filtered Namespace List ---
    _write_filtered_namespaces(
        filtered_out_namespaces,
        filtered_output_file,  # Pass the parameter
        label_selector,
        filter_mode,
        timestamp,
        output_dir,  # Pass output dir
    )

    end_time = time.monotonic()
    duration = end_time - start_time
    logger.info(f"Script finished. Total execution time: {format_duration(duration)}")


if __name__ == "__main__":
    main()
