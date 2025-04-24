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
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import click
from filelock import FileLock
from kubernetes import client
from kubernetes.client import ApiClient
from kubernetes.client.rest import ApiException

# Import utilities
from utils.k8s_utils import (
    format_duration,
    load_kube_config_auto,
    parse_storage_string,
)
from utils.logging_utils import get_logger, setup_logging

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


def _process_custom_resources(
    custom_api: client.CustomObjectsApi,
    namespace: str,
    crd_list: List[Any],
) -> Tuple[Dict[str, int], int]:
    """Processes custom resources (CRDs) for counting and sizing."""
    cr_counts = defaultdict(int)
    total_cr_size_bytes = 0

    for crd in crd_list:
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

        # Prioritize storedVersions if available, otherwise take the first one
        stored_version = next((v.name for v in versions if v.storage), None)
        version = stored_version if stored_version else versions[0].name
        logger.debug(f"Processing CRD {kind} using version {version} in namespace {namespace}")

        try:
            custom_objects = custom_api.list_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                limit=500,  # Add limit
            )
            items = custom_objects.get("items", [])
            cr_counts[kind] = len(items)

            # Handle potential pagination if 'continue' token exists
            continue_token = custom_objects.get("metadata", {}).get("continue")
            while continue_token:
                logger.debug(f"Paginating CRD list for {kind} in {namespace}...")
                custom_objects = custom_api.list_namespaced_custom_object(
                    group=group,
                    version=version,
                    namespace=namespace,
                    plural=plural,
                    limit=500,
                    _continue=continue_token,
                )
                more_items = custom_objects.get("items", [])
                items.extend(more_items)
                cr_counts[kind] += len(more_items)
                continue_token = custom_objects.get("metadata", {}).get("continue")

            # Calculate size after fetching all items
            if items:  # Only calculate if items exist
                total_cr_size_bytes += _calculate_crd_items_size(
                    custom_api, namespace, group, version, plural, kind, items
                )

        except ApiException as e_list:
            # 403 likely means no permission to list this CRD type in this namespace
            # 404 might mean the CRD version/plural is incorrect *for this namespace* (less likely cluster-wide if pre-fetched)
            if e_list.status == 403:
                logger.warning(
                    f"Permission denied listing {kind} ({group}/{version}) in {namespace}. Skipping."
                )
            elif e_list.status != 404:  # Log other API errors
                logger.error(
                    f"Could not list instances for {kind} ({group}/{version}) in namespace {namespace}: {e_list.status} - {e_list.reason}"
                )
            # If 404, it might just mean no instances exist, which is fine.
        except Exception as e_general:
            logger.error(
                f"Unexpected error processing CRD {kind} in namespace {namespace}: {e_general}"
            )

    return dict(cr_counts), total_cr_size_bytes


def _process_secrets(v1: client.CoreV1Api, namespace: str) -> Tuple[int, int]:
    """Processes Secrets for counting and full object sizing."""
    secret_count = 0
    total_secret_object_size_bytes = 0
    secret_names: List[str] = []

    try:
        # List secrets with pagination to get all names
        continue_token = None
        while True:
            logger.debug(
                f"Listing secrets in {namespace} (continue={continue_token is not None})..."
            )
            secrets = v1.list_namespaced_secret(namespace, limit=500, _continue=continue_token)
            current_items = secrets.items
            secret_names.extend(
                [s.metadata.name for s in current_items if s.metadata and s.metadata.name]
            )

            # Safely get the next continue token
            continue_token = getattr(getattr(secrets, "metadata", None), "_continue", None)
            if not continue_token:
                break  # Exit loop if no more pages

        secret_count = len(secret_names)
        logger.debug(f"Found {secret_count} secret names in {namespace}.")

        # Now read each secret individually to calculate its object size
        for secret_name in secret_names:
            try:
                full_secret = v1.read_namespaced_secret(name=secret_name, namespace=namespace)
                total_secret_object_size_bytes += get_object_size(full_secret)
            except ApiException as e_read:
                if e_read.status == 404:
                    logger.warning(
                        f"Secret {secret_name} not found during size calculation in {namespace} (deleted?)."
                    )
                else:
                    logger.error(
                        f"Could not read Secret {secret_name} in {namespace} for size: {e_read.status} - {e_read.reason}"
                    )
            except Exception as e_size:
                logger.error(
                    f"Error calculating size for Secret {secret_name} in {namespace}: {e_size}"
                )

    except ApiException as e_list:
        logger.error(f"Could not list secrets in {namespace}: {e_list.status} - {e_list.reason}")
        # Return 0 count and size if listing fails
        return 0, 0
    except Exception as e_list_unexpected:
        logger.error(f"Unexpected error listing secrets in {namespace}: {e_list_unexpected}")
        return 0, 0

    # Note: The size reported is the full object definition size (JSON), not just the data size.
    return secret_count, total_secret_object_size_bytes


def _process_pvcs(v1: client.CoreV1Api, namespace: str) -> Tuple[int, int]:
    """Processes PersistentVolumeClaims (PVCs) for counting and capacity sizing."""
    pvc_count = 0
    total_pvc_capacity_bytes = 0
    try:
        pvcs = v1.list_namespaced_persistent_volume_claim(namespace, limit=500)  # Add limit
        items = pvcs.items
        pvc_count = len(items)

        continue_token = pvcs.metadata._continue
        while continue_token:
            logger.debug(f"Paginating PVC list in {namespace}...")
            pvcs = v1.list_namespaced_persistent_volume_claim(
                namespace, limit=500, _continue=continue_token
            )
            more_items = pvcs.items
            items.extend(more_items)
            pvc_count += len(more_items)
            continue_token = pvcs.metadata._continue

        for pvc in items:
            try:
                # Use spec.resources.requests for requested size, status.capacity for actual provisioned size
                storage_size_str = None
                if pvc.status and pvc.status.capacity:
                    storage_size_str = pvc.status.capacity.get("storage")
                elif pvc.spec and pvc.spec.resources and pvc.spec.resources.requests:
                    # Fallback to requested size if capacity not available (e.g., pending PVC)
                    storage_size_str = pvc.spec.resources.requests.get("storage")

                if storage_size_str:
                    pvc_bytes = parse_storage_string(storage_size_str)
                    if pvc_bytes is not None:
                        total_pvc_capacity_bytes += pvc_bytes
                    else:
                        logger.warning(
                            f"Could not parse PVC size for {pvc.metadata.name} in {namespace}: '{storage_size_str}'"
                        )
                # else: # Don't log if no storage request/capacity unless debugging
                #     logger.debug(f"PVC {pvc.metadata.name} in {namespace} has no storage size specified/provisioned.")
            except Exception as e:
                logger.error(f"Error processing PVC {pvc.metadata.name} size in {namespace}: {e}")
    except ApiException as e:
        logger.error(f"Could not list PVCs in {namespace}: {e.status} - {e.reason}")
    except Exception as e:
        logger.error(f"Unexpected error processing PVCs in {namespace}: {e}")

    return pvc_count, total_pvc_capacity_bytes


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
    total_core_resources_size_bytes = 0  # Size of CMs only for now
    total_cr_size_bytes = 0
    total_pvc_capacity_bytes = 0
    total_secret_size_bytes = 0  # Track secret data size separately

    resource_getters = {
        "Pods": lambda: v1.list_namespaced_pod(namespace, limit=1).items,  # Limit 1 just to count
        "Services": lambda: v1.list_namespaced_service(namespace, limit=1).items,
        "ConfigMaps": lambda: v1.list_namespaced_config_map(
            namespace, limit=500
        ).items,  # Need items for size
        # Secrets and PVCs handled by specific functions below
        "ServiceAccounts": lambda: v1.list_namespaced_service_account(namespace, limit=1).items,
        "Endpoints": lambda: v1.list_namespaced_endpoints(namespace, limit=1).items,
        "Deployments": lambda: apps_v1.list_namespaced_deployment(namespace, limit=1).items,
        "ReplicaSets": lambda: apps_v1.list_namespaced_replica_set(namespace, limit=1).items,
        "StatefulSets": lambda: apps_v1.list_namespaced_stateful_set(namespace, limit=1).items,
        "DaemonSets": lambda: apps_v1.list_namespaced_daemon_set(namespace, limit=1).items,
        "Jobs": lambda: batch_v1.list_namespaced_job(namespace, limit=1).items,
        "CronJobs": lambda: batch_v1.list_namespaced_cron_job(namespace, limit=1).items,
        # Add other resource types here
        # "Ingresses": lambda: net_v1.list_namespaced_ingress(namespace, limit=1).items,
        # "NetworkPolicies": lambda: net_v1.list_namespaced_network_policy(namespace, limit=1).items,
    }

    try:
        logger.debug(f"Counting standard resources in namespace: {namespace}")
        for name, getter in resource_getters.items():
            try:
                # For counting, a simple list call is okay. For sizing, more logic is needed.
                # Exception: CMs need items for sizing below.
                if name == "ConfigMaps":
                    cm_items = getter()
                    namespace_resources[name] = len(cm_items)
                    # Calculate CM size
                    for cm in cm_items:
                        try:
                            # Fetch full CM for accurate JSON size
                            # Note: This can be slow for many large CMs. Consider alternative sizing if needed.
                            full_cm = v1.read_namespaced_config_map(
                                name=cm.metadata.name, namespace=namespace
                            )
                            total_core_resources_size_bytes += get_object_size(full_cm)
                        except ApiException as e_read:
                            if e_read.status == 404:
                                logger.warning(
                                    f"ConfigMap {cm.metadata.name} not found in {namespace} during size calc."
                                )
                            else:
                                logger.error(
                                    f"Could not read ConfigMap {cm.metadata.name} in {namespace} for size: {e_read.status} - {e_read.reason}"
                                )
                        except Exception as e_size:
                            logger.error(
                                f"Error calculating size for ConfigMap {cm.metadata.name} in {namespace}: {e_size}"
                            )

                else:
                    # Perform list operation to get count (items might be empty if limit=1 used effectively)
                    # A more robust way is to use list with limit=1 and check metadata.remainingItemCount if available,
                    # but a simple len() works for basic counting if list returns items.
                    # Using limit=1 might be inefficient if the API doesn't optimize it well.
                    # A HEAD request might be better if the API supports it for counts.
                    # Sticking to list for now for broad compatibility.
                    # Update: Let's just call list() without limit=1 for accurate counts, relying on pagination if needed.
                    items = []
                    list_func = None
                    if name == "Pods":
                        list_func = v1.list_namespaced_pod
                    elif name == "Services":
                        list_func = v1.list_namespaced_service
                    elif name == "ServiceAccounts":
                        list_func = v1.list_namespaced_service_account
                    elif name == "Endpoints":
                        list_func = v1.list_namespaced_endpoints
                    elif name == "Deployments":
                        list_func = apps_v1.list_namespaced_deployment
                    elif name == "ReplicaSets":
                        list_func = apps_v1.list_namespaced_replica_set
                    elif name == "StatefulSets":
                        list_func = apps_v1.list_namespaced_stateful_set
                    elif name == "DaemonSets":
                        list_func = apps_v1.list_namespaced_daemon_set
                    elif name == "Jobs":
                        list_func = batch_v1.list_namespaced_job
                    elif name == "CronJobs":
                        list_func = batch_v1.list_namespaced_cron_job
                    # Add others...

                    if list_func:
                        try:
                            listed_objects = list_func(namespace, limit=500)
                            items = listed_objects.items
                            count = len(items)
                            continue_token = listed_objects.metadata._continue
                            while continue_token:
                                logger.debug(f"Paginating {name} list in {namespace}...")
                                listed_objects = list_func(
                                    namespace, limit=500, _continue=continue_token
                                )
                                more_items = listed_objects.items
                                items.extend(
                                    more_items
                                )  # Collect all items if needed later? Not currently.
                                count += len(more_items)
                                continue_token = listed_objects.metadata._continue
                            namespace_resources[name] = count
                        except ApiException as e_list:
                            logger.error(
                                f"Could not list {name} in {namespace}: {e_list.status} - {e_list.reason}"
                            )
                            namespace_resources[name] = 0  # Set count to 0 on error
                    else:
                        # Should not happen if resource_getters is defined correctly
                        logger.error(f"No list function found for resource type {name}")

            except ApiException as e:
                logger.error(f"Error listing {name} in {namespace}: {e.status} - {e.reason}")
                namespace_resources[name] = 0  # Set count to 0 on error
            except Exception as e:
                logger.error(f"Unexpected error listing {name} in {namespace}: {e}")
                namespace_resources[name] = 0

        # Process Secrets separately for count and size
        secret_count, total_secret_size_bytes = _process_secrets(v1, namespace)
        namespace_resources["Secrets"] = secret_count
        # Add secret size to results
        namespace_resources["TotalSecretDataSizeKiB"] = round(total_secret_size_bytes / 1024, 2)

        # Process PVCs separately for count and capacity size
        pvc_count, total_pvc_capacity_bytes = _process_pvcs(v1, namespace)
        namespace_resources["PersistentVolumeClaims"] = pvc_count
        # Add PVC capacity to results
        namespace_resources["TotalPVCCapacityGiB"] = round(total_pvc_capacity_bytes / (1024**3), 2)

        # Process Custom Resources if requested
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
                namespace_resources["TotalCustomResourceSizeKiB"] = 0  # Explicitly set to 0

        # Add calculated sizes to the results
        namespace_resources["TotalConfigMapSizeKiB"] = round(
            total_core_resources_size_bytes / 1024, 2
        )

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


# --- Namespace Filtering and Processing ---


def _determine_namespaces_to_scan_by_selector(
    api_client: ApiClient,
    label_selector: str,
) -> Optional[List[str]]:
    """Determines the list of namespaces to scan based *only* on label selector."""
    v1_core_for_ns = client.CoreV1Api(api_client)
    namespaces_to_scan: List[str] = []

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
        is_non_nfs_or_mixed = storage_info["non_nfs"] or (
            storage_info["nfs"] and storage_info["non_nfs"]
        )  # Include mixed here

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

    # Use click progressbar if more than one namespace
    show_progress = len(namespaces_to_scan) > 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Create futures
        future_to_ns = {
            executor.submit(count_resources, ns, include_crds, api_client, cluster_crd_list): ns
            for ns in namespaces_to_scan
        }

        iterable_futures = concurrent.futures.as_completed(future_to_ns)
        progress_label = "Processing namespaces"

        if show_progress:
            # Setup progress bar
            iterable_futures = click.progressbar(
                iterable=iterable_futures,
                length=len(namespaces_to_scan),
                label=progress_label,
                item_show_func=lambda p: (
                    f"Processed {p.metadata.name}" if p and hasattr(p, "metadata") else ""
                ),  # Show namespace name if possible
            )
            logger.info(f"Processing {len(namespaces_to_scan)} namespaces with progress bar.")
        else:
            logger.info(f"Processing {len(namespaces_to_scan)} namespace(s)...")

        # Process futures, using the progress bar as context manager if shown
        if show_progress:
            with iterable_futures as bar:
                for future in bar:  # Iterate using the context manager's variable
                    ns = future_to_ns[future]
                    try:
                        resources = future.result()  # Get result from future
                        if resources is not None:
                            # Successfully processed, add Namespace key
                            ns_data = {"Namespace": ns, **resources}
                            all_resources_data.append(ns_data)
                            all_field_names.update(ns_data.keys())
                            # Log success minimally unless debugging is high
                            logger.debug(
                                f"Successfully processed namespace: {ns}. Resources found: {len(resources)}"
                            )
                            processed_count += 1
                        else:
                            # count_resources returned None, indicating failure
                            logger.warning(f"Namespace {ns} failed processing (returned None).")
                            failed_namespaces.append(ns)
                    except Exception as exc:
                        # Catch exceptions raised during future execution
                        logger.error(
                            f"Namespace {ns} generated an exception during processing: {exc}",
                            exc_info=True,
                        )
                        failed_namespaces.append(ns)
        else:  # No progress bar, just iterate directly
            for future in iterable_futures:
                ns = future_to_ns[future]
                try:
                    resources = future.result()  # Get result from future
                    if resources is not None:
                        # Successfully processed, add Namespace key
                        ns_data = {"Namespace": ns, **resources}
                        all_resources_data.append(ns_data)
                        all_field_names.update(ns_data.keys())
                        # Log success minimally unless debugging is high
                        logger.debug(
                            f"Successfully processed namespace: {ns}. Resources found: {len(resources)}"
                        )
                        processed_count += 1
                    else:
                        # count_resources returned None, indicating failure
                        logger.warning(f"Namespace {ns} failed processing (returned None).")
                        failed_namespaces.append(ns)
                except Exception as exc:
                    # Catch exceptions raised during future execution
                    logger.error(
                        f"Namespace {ns} generated an exception during processing: {exc}",
                        exc_info=True,
                    )
                    failed_namespaces.append(ns)
            # No need for bar.update() when using click.progressbar as iterator wrapper

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
    """Counts Kubernetes resources and sizes within namespaces selected by a label,
    filtering based on whether the namespaces use NFS-only storage.

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

    # --- Determine Target Namespaces ---
    target_namespaces = _determine_namespaces_to_scan_by_selector(api_client, label_selector)
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
