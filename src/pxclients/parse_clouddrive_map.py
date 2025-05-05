#!/usr/bin/env python3
"""Cloud Drive Map Parser.

This script parses cloud drive configuration from Kubernetes configmaps
and provides disk mapping information.

Dependencies:
    - kubernetes
    - pyVmomi
    - typer
    - utils.k8s_utils
    - utils.logging_utils
    - utils.vmware_utils
"""

import base64
import logging
import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, Optional

import click
from kubernetes import client
from pyVmomi import vim

from utils.px_api import get_cloud_drive_config
from utils.k8s_utils import (
    get_custom_objects_api,
    get_k8s_client,
    load_kube_config_auto,
)
from utils.logging_utils import get_logger, setup_logging
from utils.vmware_utils import connect, extract_path_from_datastore_path

# Configure logging
logger = get_logger(__name__)


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
        args = SimpleNamespace()
        args.host = self.host
        args.user = self.username
        args.password = self.password
        args.port = self.port
        args.disable_ssl_verification = self.disable_ssl_verification
        return args


def get_vsphere_config(namespace: str, verify_ssl: bool) -> Optional[VSphereConfig]:  # noqa: C901
    """Get vSphere configuration from Kubernetes secrets.

    Args:
        namespace: Kubernetes namespace containing the secrets
        verify_ssl: If True, SSL verification will be enabled.

    Returns:
        VSphereConfig object if successful, None otherwise
    """
    logger.debug("Attempting to get vSphere config from namespace: %s", namespace)
    vcenter = None
    username = None
    password = None

    try:
        v1 = get_k8s_client()

        # Step 2.1: Get vSphere credentials from Secret
        try:
            secret_name = "px-vsphere-secret"
            logger.debug("Reading secret '%s'...", secret_name)
            secret = v1.read_namespaced_secret(secret_name, namespace)
            username = base64.b64decode(secret.data["VSPHERE_USER"]).decode().strip()
            password = base64.b64decode(secret.data["VSPHERE_PASSWORD"]).decode().strip()
            logger.debug("Successfully decoded and stripped vSphere username from secret.")
        except client.ApiException as e:
            logger.error("K8s API error reading secret '%s': %s", secret_name, str(e))
            return None
        except KeyError as e:
            logger.error("Secret '%s' is missing expected key: %s", secret_name, str(e))
            return None
        except Exception as e:
            logger.error("Failed processing secret '%s': %s", secret_name, str(e), exc_info=True)
            return None

        # Step 2.2: Get vCenter URL from StorageCluster CRD
        try:
            custom_api = get_custom_objects_api()
            storage_cluster_group = "core.libopenstorage.org"
            storage_cluster_version = "v1"
            storage_cluster_plural = "storageclusters"
            logger.debug(
                "Listing StorageClusters (group=%s, version=%s, plural=%s)...",
                storage_cluster_group,
                storage_cluster_version,
                storage_cluster_plural,
            )
            storage_clusters = custom_api.list_namespaced_custom_object(
                group=storage_cluster_group,
                version=storage_cluster_version,
                namespace=namespace,
                plural=storage_cluster_plural,
            )

            vcenter = None
            logger.debug("Searching for VSPHERE_VCENTER env var in StorageClusters...")
            for cluster in storage_clusters.get("items", []):
                cluster_name_debug = cluster.get("metadata", {}).get("name", "Unknown")
                logger.debug("Checking StorageCluster: %s", cluster_name_debug)
                env = cluster.get("spec", {}).get("env", [])
                for param in env:
                    if param.get("name") == "VSPHERE_VCENTER":
                        vcenter = param.get("value")
                        logger.debug(
                            "Found VSPHERE_VCENTER=%s in StorageCluster %s",
                            vcenter,
                            cluster_name_debug,
                        )
                        break
                if vcenter:
                    break

            if not vcenter:
                logger.error(
                    "Could not find VSPHERE_VCENTER in any StorageCluster in namespace '%s'",
                    namespace,
                )
                return None
        except client.ApiException as e:
            logger.error("K8s API error listing StorageClusters: %s", str(e))
            return None
        except Exception as e:
            logger.error("Failed processing StorageClusters: %s", str(e), exc_info=True)
            return None

        # Step 2.3: Create and return VSphereConfig object
        # Set disable_ssl_verification based on the verify_ssl flag
        disable_verification = not verify_ssl
        logger.debug("vSphere SSL verification %s", "enabled" if verify_ssl else "disabled")

        config = VSphereConfig(
            host=vcenter,
            username=username,
            password=password,  # Note: Password will not be logged
            disable_ssl_verification=disable_verification,
        )
        logger.debug(
            "Created VSphereConfig: host=%s, user=%s, port=%d, disable_ssl=%s",
            config.host,
            config.username,
            config.port,
            config.disable_ssl_verification,
        )
        # logger.debug("vSphere config retrieved successfully.") # Redundant, part of _initialize_resources log
        return config

    except Exception as e:  # General fallback catcher (less likely to be hit now)
        logger.error(
            "Unexpected outer error in get_vsphere_config for namespace '%s': %s",
            namespace,
            str(e),
            exc_info=True,
        )
        return None


def get_vm_info(vsphere_config: VSphereConfig, vm_uuid: str) -> Optional[Dict[str, float]]:
    """Get VM disk information using pyVmomi.

    Args:
        vsphere_config: VSphereConfig object with connection details
        vm_uuid: UUID of the VM to query

    Returns:
        Dictionary mapping disk paths to sizes in GB, or None if error occurs
    """
    logger.debug("Fetching VM info for UUID: %s", vm_uuid)
    vmdk_info: Dict[str, float] = {}
    si = None

    try:
        # Convert config to args and log (excluding password)
        connect_args = vsphere_config.to_args()
        logger.debug(
            "Attempting vSphere connection with args: host=%s, user=%s, port=%d, disable_ssl=%s",
            connect_args.host,
            connect_args.user,
            connect_args.port,
            connect_args.disable_ssl_verification,
        )

        # Connect to vSphere using utility function
        si = connect(connect_args)

        # Check if connection was successful
        if not si:
            logger.error(
                "Failed to connect to vSphere host: %s. Cannot get VM info.", vsphere_config.host
            )
            return None

        # Test the service instance connection by getting current time
        try:
            current_time = si.CurrentTime()
            logger.debug("vSphere connection test successful. Server time: %s", current_time)
        except Exception as service_test_e:
            logger.error(
                "vSphere connection test failed for host %s (unable to get server time): %s",
                vsphere_config.host,
                str(service_test_e),
                exc_info=True,  # Include traceback for debugging
            )
            return None

        # Search for VM by UUID
        logger.debug("Searching for VM by UUID: %s", vm_uuid)
        vm = si.content.searchIndex.FindByUuid(None, vm_uuid, True)
        if not vm:
            logger.error("FindByUuid search failed: VM with UUID %s not found", vm_uuid)
            return None

        # Get disk information
        logger.debug("Processing devices for VM: %s", vm.name)
        device_count = 0
        virtual_disk_count = 0
        for device in vm.config.hardware.device:
            device_count += 1
            if isinstance(device, vim.vm.device.VirtualDisk):
                virtual_disk_count += 1
                backing = device.backing
                if backing and hasattr(backing, "fileName"):
                    filename = backing.fileName
                    file_path = extract_path_from_datastore_path(filename)
                    ds = backing.datastore.name
                    key = f"[{ds}] {file_path}"
                    value = device.capacityInKB / (1024 * 1024)  # Convert to GB
                    vmdk_info[key] = value
                    logger.debug("Found disk: %s -> %.2f GB", key, value)

        logger.debug(
            "Processed %d devices, found %d virtual disks for VM %s.",
            device_count,
            virtual_disk_count,
            vm.name,
        )
        logger.debug("Returning VMDK info: %s", vmdk_info)
        return vmdk_info

    except Exception as e:
        logger.error("Error getting VM info: %s", str(e))
        return None


def _initialize_resources(
    portworx_namespace: str, verify_vsphere_ssl: bool
) -> Optional[VSphereConfig]:
    """Load kubeconfig and get vSphere configuration."""
    logger.debug("Initializing Kubernetes and vSphere resources...")
    try:
        # Load Kubernetes configuration (tries file, then in-cluster)
        if not load_kube_config_auto():
            logger.error("Failed to load Kubernetes configuration. Cannot proceed.")
            return None
        logger.debug("Kubernetes configuration loaded successfully.")

        vsphere_config = get_vsphere_config(portworx_namespace, verify_vsphere_ssl)
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


def _fetch_cluster_drive_data(namespace: str, configmap_name: str) -> Optional[Dict]:
    """Fetch cloud drive configuration data from Kubernetes configmap."""
    try:
        cloud_drive_data = get_cloud_drive_config(namespace, configmap_name)
        if not cloud_drive_data:
            logger.error(
                "Failed to get cloud drive configuration from configmap '%s' in namespace '%s'.",
                configmap_name,
                namespace,
            )
            return None
        logger.info("Successfully fetched cloud drive data from configmap '%s'.", configmap_name)
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
    """Processes expected configs, identifies mismatches, and checks for duplicate expected sizes.

    Args:
        expected_configs: Dictionary of expected drive configurations
        actual_drives: Dictionary of actual drive sizes
        node_scheduler_name: Name of the node scheduler
        node_instance_id: Instance ID of the node

    Returns:
        Tuple containing:
            - exp_size_map: Dictionary of expected size -> expected key
            - expected_details: List of expected drive details
            - mismatch_found: Boolean indicating if mismatches were found
            - expected_sizes_good: Boolean indicating if expected sizes are unique
    """
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

    logger.debug(
        "Processed expected configs for node %s. Mismatch found: %s. Expected sizes unique: %s",
        node_scheduler_name,
        mismatch_found,
        expected_sizes_good,
    )
    logger.debug("Expected size map (for mismatched/mapping): %s", exp_size_map)
    return exp_size_map, expected_details, mismatch_found, expected_sizes_good


def _attempt_size_based_mapping(
    exp_size_map: Dict[float, str],
    actual_size_map: Dict[float, str],
    expected_configs: Dict[str, Dict],  # Added to log unexpected drives
    actual_drives: Dict[str, float],  # Added to log unexpected drives
    node_scheduler_name: str,
    node_instance_id: str,
) -> Dict[str, str]:
    """Attempts 1:1 mapping based on unique sizes when mismatches are found.

    Args:
        exp_size_map: Dictionary of expected size -> expected key
        actual_size_map: Dictionary of actual size -> actual key
        expected_configs: Dictionary of expected drive configurations
        actual_drives: Dictionary of actual drive sizes
        node_scheduler_name: Name of the node scheduler
        node_instance_id: Instance ID of the node

    Returns:
        Dictionary mapping expected paths to actual paths for replacement
    """
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
    debug: bool,
) -> None:
    """Logs details when automatic mapping fails due to complexity or duplicates.

    Args:
        expected_details: List of expected drive details
        actual_drives: Dictionary of actual drive sizes
        node_scheduler_name: Name of the node scheduler
        node_instance_id: Instance ID of the node
        debug: Boolean indicating if debug logging is enabled

    Returns:
        None
    """
    logger.warning(
        "Complex mismatch or duplicate sizes found for node %s (%s). Cannot automatically map. Manual check needed.",
        node_scheduler_name,
        node_instance_id,
    )
    if debug:
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
    debug: bool,
) -> Dict[str, str]:
    """Compare expected drive configurations with actual drives found on the VM.

    Args:
        expected_configs: Dictionary of expected drive configurations
        actual_drives: Dictionary of actual drive sizes
        node_scheduler_name: Name of the node scheduler
        node_instance_id: Instance ID of the node
        debug: Boolean indicating if debug logging is enabled

    Returns:
        Dictionary mapping expected paths to actual paths for replacement
    """
    logger.debug("Comparing drives for node %s (%s)", node_scheduler_name, node_instance_id)
    # 1. Build map of actual drives and check for unique sizes
    actual_size_map, actual_sizes_good = _build_actual_drive_map(
        actual_drives, node_scheduler_name, node_instance_id
    )
    logger.debug("Actual size map: %s (Unique: %s)", actual_size_map, actual_sizes_good)
    if not actual_sizes_good:
        logger.warning("Cannot proceed with comparison due to duplicate actual drive sizes.")
        return {}

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
                debug,
            )
            return {}  # Mapping unreliable


def _process_single_node(
    vsphere_config: VSphereConfig,
    node_data: Dict,
    node_scheduler_name: str,
    node_instance_id: str,
    debug: bool,
) -> Dict[str, str]:
    """Process the configuration for a single storage node.

    Args:
        vsphere_config: VSphereConfig object with connection details
        node_data: Dictionary containing node configuration data
        node_scheduler_name: Name of the node scheduler
        node_instance_id: Instance ID of the node
        debug: Boolean indicating if debug logging is enabled

    Returns:
        Dictionary mapping expected paths to actual paths for replacement
    """
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
    logger.debug("Node %s - Expected Configs: %s", node_scheduler_name, expected_configs)
    logger.debug("Node %s - Actual Drives: %s", node_scheduler_name, actual_drives)

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
            if debug:
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
        debug=debug,
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


def _find_cloud_drive_configmap(namespace: str, v1_client: client.CoreV1Api) -> Optional[str]:
    """Find a unique configmap starting with 'px-cloud-drive-' in the namespace."""
    prefix = "px-cloud-drive-"
    try:
        logger.debug(
            "Searching for ConfigMaps with prefix '%s' in namespace '%s'...", prefix, namespace
        )
        configmaps = v1_client.list_namespaced_config_map(namespace)
        matching_cms = [
            cm.metadata.name for cm in configmaps.items if cm.metadata.name.startswith(prefix)
        ]

        if len(matching_cms) == 1:
            found_name = matching_cms[0]
            logger.info("Found unique ConfigMap: '%s'", found_name)
            return found_name
        elif len(matching_cms) == 0:
            logger.error(
                "No ConfigMap found with prefix '%s' in namespace '%s'. Please specify using --configmap-name.",
                prefix,
                namespace,
            )
            return None
        else:
            logger.error(
                "Multiple ConfigMaps found with prefix '%s' in namespace '%s': %s. Please specify using --configmap-name.",
                prefix,
                namespace,
                ", ".join(matching_cms),
            )
            return None
    except client.ApiException as e:
        logger.error("API error listing ConfigMaps in namespace '%s': %s", namespace, str(e))
        return None
    except Exception as e:
        logger.error(
            "Unexpected error searching for ConfigMaps in namespace '%s': %s", namespace, str(e)
        )
        return None


@click.command(
    name="parse-clouddrive-map",  # Kebab-case is conventional for click command names
    help="Parse cloud drive configuration from Kubernetes configmaps and provide disk mapping information.",
)
@click.option(
    "--configmap-name",
    "-c",
    default=None,
    help="Name of the ConfigMap. If omitted, searches for 'px-cloud-drive-*'.",
    type=str,
)
@click.option(
    "--namespace",
    "-n",
    default="kube-system",
    help="Kubernetes namespace containing the secrets and StorageCluster.",
    show_default=True,
)
@click.option(
    "--portworx-namespace",
    "-p",
    default="portworx",
    help="Kubernetes namespace containing the vSphere secret.",
    show_default=True,
)
@click.option(
    "--debug",
    "-d",
    is_flag=True,
    default=False,
    help="Enable debug logging (DEBUG level).",
)
@click.option(
    "--kubeconfig",
    "-k",
    default=None,
    help="Path to the kubeconfig file to use.",
    type=click.Path(exists=True, dir_okay=False, readable=True),
)
@click.option(
    "--vsphere-ssl-verify",
    is_flag=True,
    default=False,  # Default is NOT to verify (disable_ssl_verification=True)
    help="Enable SSL verification for vSphere connection.",
)
def main(
    # cluster_name: str,
    namespace: str,
    portworx_namespace: str,
    debug: bool,
    configmap_name: Optional[str],
    kubeconfig: Optional[str],
    vsphere_ssl_verify: bool,
) -> None:
    """Parse cloud drive configuration from Kubernetes configmaps and provide disk mapping information.

    This tool helps identify and map cloud drives in a vSphere environment by:
    1. Getting vSphere configuration from Kubernetes secrets
    2. Retrieving cloud drive configuration from configmaps
    3. Mapping drives between expected and actual configurations based on size
    """
    # --- Setup Logging --- #
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)  # Pass script_name
    logger.debug("Logging setup complete.")

    try:
        # Initialize Kubernetes client (needed early for discovery)
        if not load_kube_config_auto(config_file=kubeconfig):
            logger.error("Failed to load Kubernetes configuration. Cannot proceed.")
            raise click.Abort()
        k8s_v1_client = get_k8s_client("CoreV1Api")

        # Determine the configmap name (discover if not provided)
        if configmap_name is None:
            configmap_name = _find_cloud_drive_configmap(namespace, k8s_v1_client)
            if configmap_name is None:
                raise click.Abort()  # Error logged in _find_cloud_drive_configmap

        # Now we have a configmap_name, proceed with getting vSphere config
        logger.debug("Using ConfigMap: %s", configmap_name)
        vsphere_config = _initialize_resources(portworx_namespace, vsphere_ssl_verify)
        if not vsphere_config:
            raise click.Abort()

        # Get cloud drive configuration data using the determined configmap_name
        cloud_drive_data = _fetch_cluster_drive_data(namespace, configmap_name)
        if not cloud_drive_data:
            raise click.Abort()

        # Use the determined configmap_name in log messages if relevant (example)
        logger.info("Processing storage nodes defined in ConfigMap '%s'...", configmap_name)
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
                debug=debug,
            )
            all_replaces.update(node_replaces)

        # Output final mapping
        logger.debug("Final suggested replacements map: %s", all_replaces)
        _output_drive_mapping(all_replaces)

    except Exception as e:
        logger.error("An unexpected error occurred in main execution: %s", str(e), exc_info=debug)
        # raise typer.Exit(1)
        raise click.Abort()


if __name__ == "__main__":
    # app()
    main()  # Click commands are called directly
