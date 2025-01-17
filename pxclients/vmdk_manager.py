#!/usr/bin/env python3
"""
VMDKManager: A utility for managing VMDK operations and path replacements using pyvmomi.

This script combines the functionality of parse_cd.py and path_replace.py while using
pyvmomi instead of govc for VMware operations. It provides capabilities to:
1. Extract VMDK information from VMs
2. Replace VMDK paths using mapping files
3. Verify storage node configurations

Requirements:
    - pyvmomi
    - click
    - typing
    - logging

Author: Codeium AI
Date: 2025-01-16
"""

import json
import csv
import logging
import os
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
import click
from pyVmomi import vim
from pyVim.connect import SmartConnect, Disconnect
import ssl
import atexit
from utils.vmdk_utils import (
    VMDKInfo, read_json_config, write_json_config,
    read_mapping_file, write_mapping_file, extract_path_from_datastore_path,
    generate_mapping_from_diff, ensure_directory_exists
)
from utils.k8s_utils import (
    load_kube_config, get_cloud_drive_config, update_cloud_drive_config
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/vmdk_manager.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class VMDKManager:
    """Manager class for VMDK operations using pyvmomi."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        disable_ssl_verification: bool = True
    ) -> None:
        """
        Initialize VMDKManager with vSphere connection parameters.

        Args:
            host: vSphere host address
            username: vSphere username
            password: vSphere password
            port: vSphere port (default: 443)
            disable_ssl_verification: Whether to disable SSL verification (default: True)
        """
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.disable_ssl_verification = disable_ssl_verification
        self.service_instance = None
        self._connect()

    def _connect(self) -> None:
        """Establish connection to vSphere."""
        try:
            if self.disable_ssl_verification:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS)
                context.verify_mode = ssl.CERT_NONE
            else:
                context = None

            self.service_instance = SmartConnect(
                host=self.host,
                user=self.username,
                pwd=self.password,
                port=self.port,
                sslContext=context
            )
            atexit.register(Disconnect, self.service_instance)
            logger.info("Successfully connected to vSphere")
        except Exception as e:
            logger.error(f"Failed to connect to vSphere: {str(e)}")
            raise

    def get_vmdk_info(self, vm_uuid: str) -> Dict[str, VMDKInfo]:
        """
        Get VMDK information for a specific VM.

        Args:
            vm_uuid: UUID of the virtual machine

        Returns:
            Dictionary mapping datastore paths to VMDKInfo objects
        """
        content = self.service_instance.RetrieveContent()
        search_index = content.searchIndex
        vm = search_index.FindByUuid(None, vm_uuid, True)
        
        if not vm:
            logger.error(f"VM with UUID {vm_uuid} not found")
            return {}

        vmdk_info: Dict[str, VMDKInfo] = {}
        
        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualDisk):
                backing = device.backing
                if backing and hasattr(backing, "fileName"):
                    datastore = backing.datastore.name
                    filename = backing.fileName
                    path = extract_path_from_datastore_path(filename)
                    capacity_gb = device.capacityInKB / (1024 * 1024)
                    
                    key = f"[{datastore}] {path}"
                    vmdk_info[key] = VMDKInfo(
                        filename=filename,
                        datastore=datastore,
                        capacity_gb=capacity_gb,
                        path=path
                    )

        return vmdk_info

    def verify_storage_config(
        self,
        cloud_drive_config: Dict[str, Any],
        vmdk_info: Dict[str, VMDKInfo],
        mapping_file: Optional[str] = None
    ) -> bool:
        """
        Verify storage configuration against actual VMDK information.

        Args:
            cloud_drive_config: Cloud drive configuration
            vmdk_info: Dictionary of VMDK information
            mapping_file: Optional path to output mapping file for mismatches

        Returns:
            True if configuration matches, False otherwise
        """
        config_paths: Dict[str, float] = {}
        mismatches = []

        for key, value in cloud_drive_config.items():
            configs = value.get("Configs", {})
            for config_key, config_value in configs.items():
                config_paths[config_key] = float(config_value["Size"])
                if config_key not in vmdk_info:
                    mismatches.append(f"Missing VMDK: {config_key}")
                else:
                    expected_size = config_value["Size"]
                    actual_size = vmdk_info[config_key].capacity_gb
                    if abs(expected_size - actual_size) > 0.1:  # Allow small difference
                        mismatches.append(
                            f"Size mismatch for {config_key}: "
                            f"expected {expected_size}GB, got {actual_size}GB"
                        )

        if mapping_file:
            generate_mapping_from_diff(config_paths, vmdk_info, mapping_file)

        if mismatches:
            logger.warning("Storage configuration verification failed:")
            for mismatch in mismatches:
                logger.warning(mismatch)
            return False
        
        logger.info("Storage configuration verification passed")
        return True

@click.group()
def cli() -> None:
    """VMDK Manager CLI tool for VMware operations."""
    pass

@cli.command()
@click.option("--host", required=True, help="vSphere host address")
@click.option("--username", required=True, help="vSphere username")
@click.option("--password", required=True, help="vSphere password")
@click.option("--vm-uuid", required=True, help="UUID of the virtual machine")
@click.option("--k8s-namespace", help="Kubernetes namespace containing the ConfigMap")
@click.option("--k8s-configmap", help="Name of the Kubernetes ConfigMap")
@click.option("--config-file", help="Path to cloud drive configuration file (if not using K8s)")
@click.option("--mapping-file", help="Optional path to output mapping file for mismatches")
def verify(
    host: str,
    username: str,
    password: str,
    vm_uuid: str,
    k8s_namespace: Optional[str],
    k8s_configmap: Optional[str],
    config_file: Optional[str],
    mapping_file: Optional[str]
) -> None:
    """Verify VMDK configuration against actual VM configuration."""
    try:
        # Ensure logs directory exists
        ensure_directory_exists("logs/vmdk_manager.log")
        
        manager = VMDKManager(host, username, password)
        vmdk_info = manager.get_vmdk_info(vm_uuid)
        
        # Get configuration from either K8s ConfigMap or file
        if k8s_namespace and k8s_configmap:
            load_kube_config()
            config = get_cloud_drive_config(k8s_namespace, k8s_configmap)
            if config_file:
                # Also save to file if requested
                write_json_config(config, config_file)
        elif config_file:
            config = read_json_config(config_file)
        else:
            raise click.UsageError(
                "Either provide --k8s-namespace and --k8s-configmap, "
                "or --config-file"
            )
        
        if mapping_file:
            ensure_directory_exists(mapping_file)
        
        manager.verify_storage_config(config, vmdk_info, mapping_file)
    except Exception as e:
        logger.error(f"Verification failed: {str(e)}")
        raise click.ClickException(str(e))

@cli.command()
@click.option("--k8s-namespace", help="Kubernetes namespace containing the ConfigMap")
@click.option("--k8s-configmap", help="Name of the Kubernetes ConfigMap")
@click.option("--config-file", help="Path to cloud drive configuration file (if not using K8s)")
@click.option("--mapping-file", required=True, help="Path to CSV mapping file")
@click.option("--output-file", help="Path to output modified configuration (if not updating K8s)")
def replace_paths(
    k8s_namespace: Optional[str],
    k8s_configmap: Optional[str],
    config_file: Optional[str],
    mapping_file: str,
    output_file: Optional[str]
) -> None:
    """Replace VMDK paths in configuration using mapping file."""
    try:
        # Read mapping file
        path_mappings = read_mapping_file(mapping_file)
        
        # Get configuration from either K8s ConfigMap or file
        if k8s_namespace and k8s_configmap:
            load_kube_config()
            config = get_cloud_drive_config(k8s_namespace, k8s_configmap)
        elif config_file:
            config = read_json_config(config_file)
        else:
            raise click.UsageError(
                "Either provide --k8s-namespace and --k8s-configmap, "
                "or --config-file"
            )
        
        # Replace paths in JSON
        json_str = json.dumps(config)
        for old_path, new_path in path_mappings:
            old_path = extract_path_from_datastore_path(old_path)
            new_path = extract_path_from_datastore_path(new_path)
            json_str = json_str.replace(old_path, new_path)
        
        new_config = json.loads(json_str)
        
        # Update configuration in either K8s ConfigMap or file
        if k8s_namespace and k8s_configmap:
            load_kube_config()
            update_cloud_drive_config(k8s_namespace, k8s_configmap, new_config)
            if output_file:
                # Also save to file if requested
                write_json_config(new_config, output_file)
        elif output_file:
            ensure_directory_exists(output_file)
            write_json_config(new_config, output_file)
        else:
            raise click.UsageError(
                "Either provide --k8s-namespace and --k8s-configmap, "
                "or --output-file"
            )
        
        logger.info("Successfully updated configuration")
    except Exception as e:
        logger.error(f"Path replacement failed: {str(e)}")
        raise click.ClickException(str(e))

if __name__ == "__main__":
    cli()
