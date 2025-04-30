#!/usr/bin/env python3
"""Cloud Drive Map Parser.

This script parses cloud drive configuration from Kubernetes configmaps
and provides disk mapping information.

Author: Updated version
Date Created: 2025-01-25
Last Modified: 2025-01-25

Dependencies:
    - kubernetes
    - pyVmomi
    - typer
    - utils.k8s_utils
    - utils.logging_utils
    - utils.vmware_utils
"""

import base64
from dataclasses import dataclass
from typing import Dict, Optional

import typer
from pyVmomi import vim

from utils.k8s_utils import (
    get_cloud_drive_config,
    get_custom_objects_api,
    get_k8s_client,
    load_kube_config,
)
from utils.logging_utils import get_logger, setup_logging
from utils.vmware_utils import connect, extract_path_from_datastore_path

# Configure logging
setup_logging()
logger = get_logger(__name__)

# Create typer app
app = typer.Typer(
    name="parse_clouddrive_map",
    help="Parse cloud drive configuration from Kubernetes configmaps",
    add_completion=False,
)


@dataclass
class VSphereConfig:
    """vSphere connection configuration."""

    host: str
    username: str
    password: str
    port: int = 443
    disable_ssl_verification: bool = True

    def to_args(self) -> object:
        """Convert config to args for vmware_utils.connect()."""
        args = object()
        args.host = self.host
        args.user = self.username
        args.password = self.password
        args.port = self.port
        args.disable_ssl_verification = self.disable_ssl_verification
        return args


def get_vsphere_config(namespace: str) -> Optional[VSphereConfig]:
    """Get vSphere configuration from Kubernetes secrets.

    Args:
        namespace: Kubernetes namespace containing the secrets

    Returns:
        VSphereConfig object if successful, None otherwise
    """
    try:
        v1 = get_k8s_client()

        # Get vSphere credentials
        secret = v1.read_namespaced_secret("px-vsphere-secret", namespace)
        username = base64.b64decode(secret.data["VSPHERE_USER"]).decode()
        password = base64.b64decode(secret.data["VSPHERE_PASSWORD"]).decode()

        # Get vCenter URL from StorageCluster
        custom_api = get_custom_objects_api()
        storage_clusters = custom_api.list_namespaced_custom_object(
            group="core.libopenstorage.org",
            version="v1",
            namespace=namespace,
            plural="storageclusters",
        )

        vcenter = None
        for cluster in storage_clusters.get("items", []):
            env = cluster.get("spec", {}).get("env", [])
            for param in env:
                if param.get("name") == "VSPHERE_VCENTER":
                    vcenter = param.get("value")
                    break
            if vcenter:
                break

        if not vcenter:
            logger.error("Could not find VSPHERE_VCENTER in StorageCluster")
            return None

        return VSphereConfig(host=vcenter, username=username, password=password)
    except Exception as e:
        logger.error("Failed to get vSphere configuration: %s", str(e))
        return None


def get_vm_info(vsphere_config: VSphereConfig, vm_uuid: str) -> Optional[Dict[str, float]]:
    """Get VM disk information using pyVmomi.

    Args:
        vsphere_config: VSphereConfig object with connection details
        vm_uuid: UUID of the VM to query

    Returns:
        Dictionary mapping disk paths to sizes in GB, or None if error occurs
    """
    vmdk_info: Dict[str, float] = {}
    si = None

    try:
        # Connect to vSphere using utility function
        si = connect(vsphere_config.to_args())

        # Search for VM by UUID
        vm = si.content.searchIndex.FindByUuid(None, vm_uuid, True)
        if not vm:
            logger.error("VM with UUID %s not found", vm_uuid)
            return None

        # Get disk information
        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualDisk):
                backing = device.backing
                if backing and hasattr(backing, "fileName"):
                    filename = backing.fileName
                    file_path = extract_path_from_datastore_path(filename)
                    ds = backing.datastore.name
                    key = f"[{ds}] {file_path}"
                    value = device.capacityInKB / (1024 * 1024)  # Convert to GB
                    vmdk_info[key] = value

        return vmdk_info

    except Exception as e:
        logger.error("Error getting VM info: %s", str(e))
        return None


def _initialize_resources(portworx_namespace: str) -> Optional[VSphereConfig]:
    """Load kubeconfig and get vSphere configuration."""
    try:
        load_kube_config()
        vsphere_config = get_vsphere_config(portworx_namespace)
        if not vsphere_config:
            logger.error(
                "Failed to get vSphere configuration for namespace '%s'.",
                portworx_namespace,
            )
            return None
        return vsphere_config
    except Exception as e:
        logger.error("Failed during resource initialization: %s", str(e))
        return None


def _fetch_cluster_drive_data(namespace: str, cluster_name: str) -> Optional[Dict]:
    """Fetch cloud drive configuration data from Kubernetes configmap."""
    try:
        cloud_drive_data = get_cloud_drive_config(namespace, cluster_name)
        if not cloud_drive_data:
            logger.error(
                "Failed to get cloud drive configuration for cluster '%s' in namespace '%s'.",
                cluster_name,
                namespace,
            )
            return None
        logger.info("Successfully fetched cloud drive data for cluster '%s'.", cluster_name)
        return cloud_drive_data
    except Exception as e:
        logger.error("Failed to fetch cloud drive data: %s", str(e))
        return None


def _build_actual_drive_map(
    actual_drives: Dict[str, float],
    node_scheduler_name: str,
    node_instance_id: str,
) -> tuple[Dict[float, str], bool]:
    """Builds a map of actual drive sizes to their keys and checks for duplicates."""
    actual_size_map: Dict[float, str] = {}
    actual_sizes_good = True
    for key, size_gb in actual_drives.items():
        if size_gb in actual_size_map:
            actual_sizes_good = False
            logger.warning(
                "Duplicate actual drive size %.2f GB found on node %s (%s): %s and %s. Cannot map reliably.",
                size_gb,
                node_scheduler_name,
                node_instance_id,
                actual_size_map[size_gb],
                key,
            )
            break  # Stop processing if duplicates are found
        else:
            actual_size_map[size_gb] = key
    return actual_size_map, actual_sizes_good


def _process_expected_configs(
    expected_configs: Dict[str, Dict],
    actual_drives: Dict[str, float],
    node_scheduler_name: str,
    node_instance_id: str,
) -> tuple[Dict[float, str], list[str], bool, bool]:
    """Processes expected configs, identifies mismatches, and checks for duplicate expected sizes."""
    exp_size_map: Dict[float, str] = {}
    expected_details: list[str] = []
    mismatch_found = False
    expected_sizes_good = True

    for config_key, config_value in expected_configs.items():
        size_gb = config_value.get("Size")
        path = config_value.get("Path", "N/A")
        if size_gb is None:
            logger.warning(
                "Missing 'Size' in config for %s on node %s. Skipping.",
                config_key,
                node_scheduler_name,
            )
            continue

        detail_entry = f"{config_key}| {size_gb} GB| {path}"
        is_mismatched = False

        if config_key not in actual_drives:
            is_mismatched = True
            detail_entry = f"{config_key}| {size_gb} GB| {path} (Not Found)"
        elif actual_drives[config_key] != size_gb:
            is_mismatched = True
            detail_entry = f"{config_key}| Expected {size_gb} GB, Found {actual_drives[config_key]:.2f} GB | {path}"

        if is_mismatched:
            mismatch_found = True
            expected_details.append(detail_entry)
            # Track expected sizes only for mismatched entries needed for potential mapping
            if size_gb in exp_size_map:
                if (
                    exp_size_map[size_gb] != config_key
                ):  # Check if it's a different key with same size
                    expected_sizes_good = False
                    logger.warning(
                        "Duplicate expected size %.2f GB in config for node %s (%s): %s and %s. Cannot map reliably.",
                        size_gb,
                        node_scheduler_name,
                        node_instance_id,
                        exp_size_map[size_gb],
                        config_key,
                    )
            else:
                exp_size_map[size_gb] = config_key

    return exp_size_map, expected_details, mismatch_found, expected_sizes_good


def _attempt_size_based_mapping(
    exp_size_map: Dict[float, str],
    actual_size_map: Dict[float, str],
    expected_configs: Dict[str, Dict],  # Added to log unexpected drives
    actual_drives: Dict[str, float],  # Added to log unexpected drives
    node_scheduler_name: str,
    node_instance_id: str,
) -> Dict[str, str]:
    """Attempts 1:1 mapping based on unique sizes when mismatches are found."""
    node_replaces: Dict[str, str] = {}
    logger.info(
        "Mismatch found for node %s (%s). Attempting size-based mapping.",
        node_scheduler_name,
        node_instance_id,
    )
    for expected_size, expected_key in exp_size_map.items():
        if expected_size in actual_size_map:
            actual_key = actual_size_map[expected_size]
            if expected_key != actual_key:
                logger.info(
                    "Suggesting replacement for node %s: %s -> %s (Size: %.2f GB)",
                    node_scheduler_name,
                    expected_key,
                    actual_key,
                    expected_size,
                )
                node_replaces[expected_key] = actual_key
        else:
            logger.warning(
                "Node %s (%s): Expected drive %s (%.2f GB) not found among actual drives.",
                node_scheduler_name,
                node_instance_id,
                expected_key,
                expected_size,
            )

    # Log drives present on VM but not in expected config (based on size)
    for actual_size, actual_key in actual_size_map.items():
        if actual_size not in exp_size_map and actual_key not in expected_configs:
            logger.warning(
                "Node %s (%s): Found unexpected drive %s (%.2f GB) not referenced by size in expected config.",
                node_scheduler_name,
                node_instance_id,
                actual_key,
                actual_size,
            )

    return node_replaces


def _log_complex_mismatch(
    expected_details: list[str],
    actual_drives: Dict[str, float],
    node_scheduler_name: str,
    node_instance_id: str,
    verbose: bool,
) -> None:
    """Logs details when automatic mapping fails due to complexity or duplicates."""
    logger.warning(
        "Complex mismatch or duplicate sizes found for node %s (%s). Cannot automatically map. Manual check needed.",
        node_scheduler_name,
        node_instance_id,
    )
    if verbose:
        logger.warning("Expected configurations (Missing/Mismatched):")
        for exp in expected_details:
            logger.warning("\t%s", exp)
        logger.warning("Actual drives found on VM:")
        for key, value in actual_drives.items():
            logger.warning("\t%s: %.2f GB", key, value)


def _compare_drives(
    expected_configs: Dict[str, Dict],
    actual_drives: Dict[str, float],
    node_scheduler_name: str,
    node_instance_id: str,
    verbose: bool,
) -> Dict[str, str]:
    """Compare expected drive configurations with actual drives found on the VM."""
    # 1. Build map of actual drives and check for unique sizes
    actual_size_map, actual_sizes_good = _build_actual_drive_map(
        actual_drives, node_scheduler_name, node_instance_id
    )
    if not actual_sizes_good:
        return {}  # Cannot proceed if actual sizes aren't unique

    # 2. Process expected configs, find mismatches, check expected sizes
    (
        exp_size_map,
        expected_details,
        mismatch_found,
        expected_sizes_good,
    ) = _process_expected_configs(
        expected_configs, actual_drives, node_scheduler_name, node_instance_id
    )

    # 3. Handle based on mismatch status
    if not mismatch_found:
        logger.info(
            "Configuration matches for node: %s (%s)", node_scheduler_name, node_instance_id
        )
        return {}
    else:
        # Attempt mapping only if both actual and expected sizes are unique
        if actual_sizes_good and expected_sizes_good:
            return _attempt_size_based_mapping(
                exp_size_map,
                actual_size_map,
                expected_configs,  # Pass for logging unexpected
                actual_drives,  # Pass for logging unexpected
                node_scheduler_name,
                node_instance_id,
            )
        else:
            # Log details for complex mismatches/duplicates
            _log_complex_mismatch(
                expected_details,
                actual_drives,
                node_scheduler_name,
                node_instance_id,
                verbose,
            )
            return {}  # Mapping unreliable


def _process_single_node(
    vsphere_config: VSphereConfig,
    node_data: Dict,
    node_scheduler_name: str,
    node_instance_id: str,
    verbose: bool,
) -> Dict[str, str]:
    """Process the configuration for a single storage node."""
    logger.debug("Processing node: %s (InstanceID: %s)", node_scheduler_name, node_instance_id)

    # Get VM information (actual drives)
    actual_drives = get_vm_info(vsphere_config, node_instance_id)
    if actual_drives is None:  # Check for None explicitly, as empty dict is valid
        logger.error(
            "Failed to get VM information for %s (%s). Skipping node.",
            node_scheduler_name,
            node_instance_id,
        )
        return {}

    # Get expected configurations
    expected_configs = node_data.get("Configs", {})
    if not expected_configs:
        logger.info(
            "No 'Configs' section found for node %s (%s). Assuming no drives expected.",
            node_scheduler_name,
            node_instance_id,
        )
        if actual_drives:
            logger.warning(
                "Node %s (%s) has drives attached but none expected in config.",
                node_scheduler_name,
                node_instance_id,
            )
            if verbose:
                logger.warning("Actual drives found on VM:")
                for key, value in actual_drives.items():
                    logger.warning("\t%s: %.2f GB", key, value)
        return {}  # Nothing expected, nothing to replace

    # Compare expected vs actual and get replacements
    node_replaces = _compare_drives(
        expected_configs=expected_configs,
        actual_drives=actual_drives,
        node_scheduler_name=node_scheduler_name,
        node_instance_id=node_instance_id,
        verbose=verbose,
    )
    return node_replaces


def _output_drive_mapping(all_replaces: Dict[str, str]) -> None:
    """Log the final suggested drive path replacements."""
    if all_replaces:
        logger.info("\nSuggested Drive Path Replacements:")
        for old_path, new_path in all_replaces.items():
            logger.info("%s -> %s", old_path, new_path)
    else:
        logger.info("\nNo drive path replacements suggested based on size mapping.")


@app.command()
def main(
    cluster_name: str = typer.Argument(
        ...,
        help="Name of the cluster to process",
        show_default=False,
    ),
    namespace: str = typer.Option(
        "kube-system",
        "--namespace",
        "-n",
        help="Kubernetes namespace containing the secrets and StorageCluster",
    ),
    portworx_namespace: str = typer.Option(
        "portworx",
        "--portworx-namespace",
        "-p",
        help="Kubernetes namespace containing the vSphere secret",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """Parse cloud drive configuration from Kubernetes configmaps and provide disk mapping information.

    This tool helps identify and map cloud drives in a vSphere environment by:
    1. Getting vSphere configuration from Kubernetes secrets
    2. Retrieving cloud drive configuration from configmaps
    3. Mapping drives between expected and actual configurations based on size
    """
    # Set logging level
    if verbose:
        logger.setLevel("DEBUG")
        logger.debug("Verbose logging enabled.")
    else:
        logger.setLevel("INFO")

    try:
        # Initialize Kubernetes client and get vSphere config
        vsphere_config = _initialize_resources(portworx_namespace)
        if not vsphere_config:
            raise typer.Exit(1)

        # Get cloud drive configuration data
        cloud_drive_data = _fetch_cluster_drive_data(namespace, cluster_name)
        if not cloud_drive_data:
            raise typer.Exit(1)

        logger.info("Processing storage nodes for cluster '%s'...", cluster_name)
        all_replaces: Dict[str, str] = {}

        # Process each node
        for node_name, node_data in cloud_drive_data.items():
            instance_id = node_data.get("InstanceID")
            scheduler_name = node_data.get(
                "SchedulerNodeName", f"UnknownNode_{node_name}"
            )  # Use node_name as fallback

            if not instance_id:
                logger.warning("Skipping node entry '%s' due to missing InstanceID.", node_name)
                continue

            # Process this node's configuration
            node_replaces = _process_single_node(
                vsphere_config=vsphere_config,
                node_data=node_data,
                node_scheduler_name=scheduler_name,
                node_instance_id=instance_id,
                verbose=verbose,
            )
            all_replaces.update(node_replaces)

        # Output final mapping
        _output_drive_mapping(all_replaces)

    except Exception as e:
        logger.error("An unexpected error occurred in main execution: %s", str(e), exc_info=verbose)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
