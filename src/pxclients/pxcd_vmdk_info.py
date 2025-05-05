#!/usr/bin/env python3
"""Get VM Drive Details Script.

Retrieves vSphere config from K8s (like parse_clouddrive_map.py)
and then lists the actual virtual disks attached to each VM found in the
specified cloud drive configmap, showing their provisioned size.
"""

import base64
import logging
import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, Optional, Tuple

import click
from kubernetes import client
from pyVmomi import vim
from rich.console import Console
from rich.table import Table

# Assume utils are in the python path or adjust import accordingly
from utils.px_api import get_cloud_drive_config  # Needed to read the configmap data
from utils.k8s_utils import (
    get_custom_objects_api,
    get_k8s_client,
    load_kube_config_auto,
)
from utils.logging_utils import get_logger, setup_logging
from utils.vmware_utils import connect, extract_path_from_datastore_path

# Configure logging
logger = get_logger(__name__)
console = Console()


# --- Components Copied/Adapted from parse_clouddrive_map.py ---


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


# TODO: Reduce complexity (currently McCabe complexity 15) - Consider refactoring K8s calls
def get_vsphere_config(namespace: str, verify_ssl: bool) -> Optional[VSphereConfig]:  # noqa: C901
    """Get vSphere configuration from Kubernetes secrets."""
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
        return config

    except Exception as e:  # General fallback catcher
        logger.error(
            "Unexpected outer error in get_vsphere_config for namespace '%s': %s",
            namespace,
            str(e),
            exc_info=True,
        )
        return None


def _initialize_resources(
    portworx_namespace: str, verify_vsphere_ssl: bool
) -> Optional[VSphereConfig]:
    """Load kubeconfig and get vSphere configuration."""
    logger.debug("Initializing Kubernetes and vSphere resources...")

    # Step 1: Load Kubeconfig
    try:
        logger.debug("Attempting to load Kubernetes configuration...")
        if not load_kube_config_auto():
            logger.error("load_kube_config_auto() returned False. Cannot proceed.")
            return None
        logger.debug("Kubernetes configuration loaded successfully.")
    except Exception as e:
        logger.error("Failed during Kubernetes configuration loading: %s", str(e), exc_info=True)
        return None

    # Step 2: Get vSphere config from Kubernetes
    vsphere_config = None
    try:
        logger.debug(
            "Attempting to retrieve vSphere configuration from K8s namespace '%s'...",
            portworx_namespace,
        )
        vsphere_config = get_vsphere_config(portworx_namespace, verify_vsphere_ssl)
        if not vsphere_config:
            logger.error("get_vsphere_config returned None.")
            return None
        logger.debug("vSphere configuration retrieved successfully from K8s.")
    except Exception as e:
        logger.error(
            "Failed retrieving vSphere configuration from K8s namespace '%s': %s",
            portworx_namespace,
            str(e),
            exc_info=True,
        )
        return None

    return vsphere_config


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


def get_vm_info(  # noqa: C901
    vsphere_config: VSphereConfig, vm_uuid: str
) -> Optional[Tuple[Dict[str, float], float]]:
    """Get VM disk information and total committed storage using pyVmomi."""
    logger.debug("Fetching VM info for UUID: %s", vm_uuid)
    vmdk_info: Dict[str, float] = {}
    si = None

    try:
        # Convert config to args and log (excluding password)
        connect_args = vsphere_config.to_args()
        logger.debug(
            "Attempting vSphere connection with args: host=%s, user=%s, port=%d, disable_ssl=%s",
            connect_args.host,
            connect_args.user,  # Username logged here
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
        skipped_disk_0 = False
        for device in vm.config.hardware.device:
            device_count += 1
            if isinstance(device, vim.vm.device.VirtualDisk):
                # Skip Disk 0 (usually the OS disk)
                if device.unitNumber == 0:
                    logger.debug("Skipping Disk 0 (UnitNumber 0): Key %d", device.key)
                    skipped_disk_0 = True
                    continue  # Skip to the next device

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
        if skipped_disk_0:
            logger.debug("Note: Disk 0 (unitNumber 0) was intentionally skipped.")

        # Get total committed storage
        total_committed_gb = 0.0
        if vm.summary.storage:
            committed_bytes = vm.summary.storage.committed
            total_committed_gb = committed_bytes / (1024 * 1024 * 1024)  # Bytes to GB
            logger.debug("VM total committed storage: %.2f GB", total_committed_gb)
        else:
            logger.warning("Could not retrieve storage summary for VM %s", vm.name)

        return vmdk_info, total_committed_gb

    except Exception as e:
        logger.error("Error getting VM info: %s", str(e))
        return None


# --- End of copied code ---


@click.command()
@click.option(
    "--namespace",
    "-n",
    default="kube-system",
    help="Kubernetes namespace containing the StorageCluster and ConfigMap.",
    show_default=True,
)
@click.option(
    "--portworx-namespace",
    "-p",
    default="portworx",
    help="Kubernetes namespace containing the vSphere secret (px-vsphere-secret).",
    show_default=True,
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
@click.option(
    "--configmap-name",
    "-c",
    default=None,
    help="Name of the cloud drive ConfigMap. If omitted, searches for 'px-cloud-drive-*'.",
    type=str,
)
@click.option(
    "--debug",
    "-d",
    is_flag=True,
    default=False,
    help="Enable debug logging (DEBUG level).",
)
def show_vm_drives(  # noqa: C901
    namespace: str,
    portworx_namespace: str,
    kubeconfig: Optional[str],
    vsphere_ssl_verify: bool,
    configmap_name: Optional[str],
    debug: bool,
):
    """Gets drive details for VMs specified in a cloud drive configmap."""
    # Setup Logging
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Starting VM drive details script.")

    # Load Kubeconfig and Initialize K8s client
    logger.info("Loading Kubernetes configuration...")
    if not load_kube_config_auto(config_file=kubeconfig):
        logger.error("Failed to load Kubernetes configuration.")
        click.echo("ERROR: Failed to load Kubernetes configuration.", err=True)
        raise click.Abort()
    logger.info("Kubernetes configuration loaded successfully.")
    k8s_v1_client = get_k8s_client("CoreV1Api")

    # Determine the configmap name
    if configmap_name is None:
        logger.info("ConfigMap name not specified, searching in namespace '%s'...", namespace)
        configmap_name = _find_cloud_drive_configmap(namespace, k8s_v1_client)
        if configmap_name is None:
            click.echo(
                "ERROR: Could not automatically find a unique px-cloud-drive-* ConfigMap.", err=True
            )
            raise click.Abort()
    else:
        logger.info("Using specified ConfigMap name: '%s'", configmap_name)
    click.echo(f"Using ConfigMap: {configmap_name}")

    # Get vSphere Config from K8s (needs portworx_namespace)
    logger.info(f"Retrieving vSphere connection details from namespace '{portworx_namespace}'...")
    vsphere_config = _initialize_resources(portworx_namespace, vsphere_ssl_verify)

    if not vsphere_config:
        logger.error("Failed to retrieve vSphere configuration from Kubernetes.")
        click.echo("ERROR: Failed to retrieve vSphere configuration from Kubernetes.", err=True)
        raise click.Abort()
    logger.info(f"Successfully retrieved vSphere config details for host: {vsphere_config.host}")

    # Fetch the cloud drive data (needs namespace where CM resides)
    logger.info(
        f"Fetching cloud drive data from ConfigMap '{configmap_name}' in namespace '{namespace}'..."
    )
    cloud_drive_data = _fetch_cluster_drive_data(namespace, configmap_name)
    if not cloud_drive_data:
        logger.error(f"Failed to fetch or parse data from ConfigMap '{configmap_name}'.")
        click.echo(f"ERROR: Failed to fetch data from ConfigMap '{configmap_name}'.", err=True)
        raise click.Abort()
    logger.info(f"Successfully fetched data for {len(cloud_drive_data)} nodes.")

    click.echo("--- VM Drive Details ---")
    # Create the consolidated table BEFORE the loop
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Node Name", style="cyan", no_wrap=True)
    table.add_column("Instance ID", style="green", no_wrap=True)
    table.add_column("Disk Path", style="dim", width=60)
    table.add_column("Provisioned Size (GB)", justify="right")

    # Process each node
    for node_name, node_data in cloud_drive_data.items():
        # Check if the node entry has a non-null 'Configs' key
        if not isinstance(node_data, dict) or not node_data.get("Configs"):
            logger.debug(
                "Skipping node entry '%s' as it does not contain a valid 'Configs' entry.",
                node_name,
            )
            continue  # Skip to the next node entry

        instance_id = node_data.get("InstanceID")
        scheduler_name = node_data.get("SchedulerNodeName", f"UnknownNode_{node_name}")

        if not instance_id:
            warn_msg = f"Skipping node entry '{node_name}' due to missing InstanceID."
            logger.warning(warn_msg)
            # click.echo(click.style(f"WARN: {warn_msg}", fg="yellow"))
            # No direct table add here, error is logged for the node below
            continue

        # click.echo(f"\nNode: {scheduler_name} (InstanceID: {instance_id})") # Removed per-node header
        logger.info(f"Processing node: {scheduler_name} (InstanceID: {instance_id})")

        # Get actual drive info for this VM
        vm_info_result = get_vm_info(vsphere_config, instance_id)

        if vm_info_result is None:
            err_msg = f"Failed to get drive information for VM {instance_id}. Check logs."
            logger.error(err_msg)
            # Add a row indicating failure for this node
            table.add_row(
                scheduler_name, instance_id, f"[bold red]ERROR:[/bold red] {err_msg}", "-"
            )
        else:
            actual_drives, total_committed_gb = vm_info_result
            # Display total committed storage - REMOVED - Cannot show per disk
            # commit_msg = f"Total Committed Storage: {total_committed_gb:.2f} GB"
            # logger.info(f"Node {scheduler_name}: {commit_msg}")
            # console.print(f"  {commit_msg}")

            if not actual_drives:
                ok_msg = "No virtual disks found attached to this VM."
                logger.info(f"Node {scheduler_name}: {ok_msg}")
                # Add a row indicating no disks for this node
                table.add_row(scheduler_name, instance_id, f"[dim]{ok_msg}[/dim]", "-")
            else:
                logger.info(f"Found {len(actual_drives)} drives for node {scheduler_name}.")
                # Add rows for each disk to the single table
                for drive_path, drive_size_gb in actual_drives.items():
                    table.add_row(scheduler_name, instance_id, drive_path, f"{drive_size_gb:.2f}")

    logger.info("Finished processing all nodes.")

    # Print the consolidated table AFTER the loop
    console.print(table)


if __name__ == "__main__":
    show_vm_drives()
