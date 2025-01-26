#!/usr/bin/env python3
"""
Cloud Drive Map Parser

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
    """
    Get vSphere configuration from Kubernetes secrets.

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
    """
    Get VM disk information using pyVmomi.

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
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """
    Parse cloud drive configuration from Kubernetes configmaps and provide disk mapping information.

    This tool helps identify and map cloud drives in a vSphere environment by:
    1. Getting vSphere configuration from Kubernetes secrets
    2. Retrieving cloud drive configuration from configmaps
    3. Mapping drives between expected and actual configurations
    """
    try:
        # Initialize Kubernetes client
        load_kube_config()

        # Get vSphere configuration
        vsphere_config = get_vsphere_config("portworx")
        if not vsphere_config:
            logger.error("Failed to get vSphere configuration")
            raise typer.Exit(1)

        # Get cloud drive configuration directly from configmap
        cloud_drive_data = get_cloud_drive_config(namespace, cluster_name)
        if not cloud_drive_data:
            logger.error("Failed to get cloud drive configuration")
            raise typer.Exit(1)

        logger.info("Processing storage nodes...")
        all_replaces: Dict[str, str] = {}

        for key, value in cloud_drive_data.items():
            instance_id = value.get("InstanceID")
            scheduler = value.get("SchedulerNodeName")

            if not instance_id:
                continue

            # Get VM information using pyVmomi
            all_drives = get_vm_info(vsphere_config, instance_id)
            if not all_drives:
                logger.error("Failed to get VM information for %s", instance_id)
                continue

            configs = value.get("Configs", {})
            if not configs:
                continue

            # Process VM configuration
            expected = []
            exp_map: Dict[float, str] = {}
            all_drives_map: Dict[float, str] = {}
            good = True

            for key, value in all_drives.items():
                if value in all_drives_map:
                    good = False
                else:
                    all_drives_map[value] = key
            if configs:
                mismatch = False
                for config_key, config_value in configs.items():
                    if config_key not in all_drives:
                        expected.append(
                            f"{config_key}| {config_value['Size']} GB| {config_value['Path']}"
                        )
                        mismatch = True
                        if good:
                            if config_value["Size"] in exp_map:
                                good = False
                            else:
                                exp_map[config_value["Size"]] = config_key

                if mismatch:
                    if good:
                        for key, value in exp_map.items():
                            all_replaces[value] = all_drives_map[key]
                    else:
                        logger.warning("Mismatch found for node: %s", scheduler)
                        if verbose:
                            logger.warning("Expected configurations:")
                            for exp in expected:
                                logger.warning("\t%s", exp)
                            logger.warning("Attached on VM:")
                            for key, value in all_drives.items():
                                logger.warning("\t%s: %.2f GB", key, value)
                else:
                    logger.info("Good: Node: %s", scheduler)

        # Output final mapping
        logger.info("\nDrive Mapping:")
        for key, value in all_replaces.items():
            logger.info("%s -> %s", key, value)

    except Exception as e:
        logger.error("Error processing cloud drive data: %s", str(e))
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
