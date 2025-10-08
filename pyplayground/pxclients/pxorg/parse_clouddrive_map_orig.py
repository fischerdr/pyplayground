#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cloud drive configuration parser for VMware environments.

This module provides functionality to parse cloud drive configurations and extract
VMDK information from VMware environments using govc commands.

Instructions to use it:
govc is required
export PX_NS=<px-namespace>
export GOVC_USERNAME=$(kubectl get secrets px-vsphere-secret -ojson -n $PX_NS| jq -r '.data.VSPHERE_USER'| base64 -d)
export GOVC_PASSWORD=$(kubectl get secrets px-vsphere-secret -ojson -n $PX_NS| jq -r '.data.VSPHERE_PASSWORD'| base64 -d)
export GOVC_URL=$(kubectl get stc -n $PX_NS -ojson | jq -r '.items[0].spec.env[] | select(.name=="VSPHERE_VCENTER") | .value')/sdk
export GOVC_INSECURE=true
export GOVC_DATACENTER= # if multiple Datacenters are there

Create a cd.json from the configmap
kubectl get cm <cluster-name> -ojson -n kube-system | jq -r '.data."cloud-drive"'| jq . > cd.json

python parse_cd.py cd.json
"""
import json
import logging
import os
import subprocess
import sys
from typing import Any, Dict, List, Tuple

import click

from pyplayground.utils.logging_utils import setup_logging

logger = logging.getLogger(__name__)


def extract_vmdk_info(json_string: str) -> Dict[str, float]:
    """Extract VMDK information from JSON string.

    Args:
        json_string (str): JSON string containing virtual machine data.

    Returns:
        dict: Dictionary mapping VM UUIDs to their VMDK information.
    """
    data = json.loads(json_string)

    vmdk_info = {}

    for vm in data["VirtualMachines"]:
        for device in vm["Config"]["Hardware"]["Device"]:
            if device is None:
                continue
            if "Backing" in device:
                if device["Backing"] is None:
                    continue

            if "FileName" in device["Backing"]:
                filename = device["Backing"]["FileName"]
                filePath = filename.split()[1]
                ds = device["Backing"]["Datastore"]["Value"]
                key = "[" + ds + "] " + filePath
                value = device["CapacityInKB"] / (1024 * 1024)
                vmdk_info[key] = value

    return vmdk_info


def get_vm_drives(instance_id: str) -> Dict[str, float]:
    """Get VMDK drives for a VM instance."""
    if not instance_id:
        return {}

    try:
        result = subprocess.run(
            ["govc", "vm.info", f"-vm.uuid={instance_id}", "-json"],
            capture_output=True,
            text=True,
            check=True,  # Raise exception on non-zero exit code
        )
        return extract_vmdk_info(result.stdout)
    except FileNotFoundError:
        logger.error("`govc` command not found. Please ensure it is installed and in your PATH.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error getting VM info for instance {instance_id}: {e.stderr}")
        return {}


def create_drive_mappings(all_drives: Dict[str, float]) -> Tuple[Dict[float, str], bool]:
    """Create mappings from drive sizes to drive paths."""
    all_drives_map = {}
    good = True

    for key, value in all_drives.items():
        if value in all_drives_map:
            good = False
        else:
            all_drives_map[value] = key

    return all_drives_map, good


def process_configs(
    configs: Dict[str, Any], all_drives: Dict[str, float], good: bool
) -> Tuple[List[str], Dict[float, str], bool, bool]:
    """Process configuration mismatches and return expected configs and mappings."""
    expected = []
    exp_map = {}
    mismatch = False

    for config_key, config_value in configs.items():
        if config_key not in all_drives:
            expected.append(f"{config_key}| {config_value['Size']} GB| {config_value['Path']}")
            mismatch = True
            if good:
                if config_value["Size"] in exp_map:
                    good = False
                else:
                    exp_map[config_value["Size"]] = config_key

    return expected, exp_map, mismatch, good


def handle_mismatch(
    mismatch: bool,
    good: bool,
    scheduler: str,
    expected: List[str],
    all_drives: Dict[str, float],
    exp_map: Dict[float, str],
    all_drives_map: Dict[float, str],
    all_replaces: Dict[str, str],
):
    """Handle configuration mismatches and update replacements."""
    if mismatch:
        if good:
            for key, value in exp_map.items():
                all_replaces[value] = all_drives_map[key]
        else:
            logger.warning(f"Mismatch found for node: {scheduler}")
            logger.warning("\tExpected drives:")
            for i in expected:
                logger.warning(f"\t\t{i}")
            logger.warning("\tAttached drives on VM:")
            for key, value in all_drives.items():
                logger.warning(f"\t\t{key}: {value} GB")
    else:
        logger.info(f"Configuration match for node: {scheduler}")


@click.command()
@click.argument("config_file", type=click.Path(exists=True, dir_okay=False, readable=True))
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(config_file: str, debug: bool):
    """Parses a Portworx cloud drive config map JSON file to identify drive path mismatches.

    This script compares the drive configuration stored in the Portworx config map
    with the actual drives attached to the VMs as reported by `govc`. It generates a
    mapping of old paths to new paths for drives that have the same size but different paths.
    """
    # Setup Logging
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)

    logger.debug(f"Loading configuration from {config_file}")
    # Read JSON data from file
    with open(config_file, "r") as f:
        data = json.load(f)

    logger.info("Processing storage nodes only")
    # Loop through each key in the JSON object
    all_replaces = {}
    for key, value in data.items():
        instance_id = value.get("InstanceID")
        scheduler = value.get("SchedulerNodeName")

        if not instance_id or not scheduler:
            logger.debug(f"Skipping entry {key} due to missing InstanceID or SchedulerNodeName.")
            continue

        logger.debug(f"Processing node {scheduler} with instance ID {instance_id}")

        all_drives = get_vm_drives(instance_id)
        configs = value.get("Configs", {})

        if configs:
            all_drives_map, good = create_drive_mappings(all_drives)
            expected, exp_map, mismatch, good = process_configs(configs, all_drives, good)
            handle_mismatch(
                mismatch,
                good,
                scheduler,
                expected,
                all_drives,
                exp_map,
                all_drives_map,
                all_replaces,
            )
    logger.info("Final replacement mapping:")
    for key, value in all_replaces.items():
        # Using print here for final, clean output as requested by original script's behavior
        print(f"{key},{value}")


if __name__ == "__main__":
    main()
