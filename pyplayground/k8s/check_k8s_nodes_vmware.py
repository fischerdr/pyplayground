#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check Kubernetes nodes on VMware vSphere.

This script checks the status of Kubernetes nodes on a VMware vSphere environment.
It connects to the vCenter server, retrieves the list of VMs, and checks their power state.
"""

import logging
import ssl
from typing import Any, Dict, Optional, cast

import click
from kubernetes import client, config  # type: ignore
from pyVim.connect import Disconnect, SmartConnect, SmartConnectNoSSL  # type: ignore
from pyVmomi import vim

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
# Console handler for info level messages
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_format = logging.Formatter("%(message)s")
console_handler.setFormatter(console_format)
logger.addHandler(console_handler)
# File handler for errors
file_handler = logging.FileHandler("vm_status_errors.log")
file_handler.setLevel(logging.ERROR)
file_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(file_format)
logger.addHandler(file_handler)


def connect_to_vcenter(
    vcenter_host: str, username: str, password: str, disable_ssl: bool
) -> Optional[vim.ServiceInstance]:
    """Connect to VMware vCenter.

    Establishes a connection to a VMware vCenter server using the pyVim library.
    Supports both SSL and non-SSL connections.

    Args:
        vcenter_host: The hostname or IP address of the vCenter server.
        username: The username for the vCenter server.
        password: The password for the vCenter server.
        disable_ssl: Whether to disable SSL verification.

    Returns:
        Optional[vim.ServiceInstance]: ServiceInstance object if connection succeeds,
            None if the connection fails.

    Raises:
        Exception: If connection fails for any reason (logged but not re-raised).
    """
    try:
        if disable_ssl:
            si = SmartConnectNoSSL(host=vcenter_host, user=username, pwd=password)
        else:
            context = ssl.create_default_context()
            si = SmartConnect(host=vcenter_host, user=username, pwd=password, sslContext=context)
        return cast(vim.ServiceInstance, si)
    except Exception as e:
        logger.error(f"Failed to connect to vCenter: {e}")
        return None


def get_vm_details(vm: vim.VirtualMachine, info_type: str = "all") -> Dict[str, Any]:
    """Get details about a VM.

    Retrieves details about a virtual machine from a VMware vSphere environment.
    Can return all details or specific types of information based on info_type.

    Args:
        vm: The virtual machine object from pyVmomi.
        info_type: The type of information to retrieve. Options: "all" or "disk".
            Defaults to "all".

    Returns:
        Dict[str, Any]: Dictionary containing VM details with keys:
            - name: VM name
            - power_state: Current power state
            - ip_address: Guest IP address (may be None)
            - disk_status: List of disk information dictionaries (if info_type
              includes "disk"), each containing disk_label and disk_capacity_gb.
    """
    details = {
        "name": vm.name,
        # Type ignore: pyVmomi type stubs don't fully define RuntimeInfo.powerState
        "power_state": vm.runtime.powerState,  # type: ignore[attr-defined]
        # Type ignore: pyVmomi type stubs don't fully define GuestInfo.ipAddress
        "ip_address": vm.guest.ipAddress,  # type: ignore[attr-defined]
        "disk_status": [],
    }
    if info_type in ["all", "disk"]:
        # Type ignore: pyVmomi type stubs don't fully define VirtualMachineConfigInfo.hardware.device
        for device in vm.config.hardware.device:  # type: ignore[attr-defined]
            if isinstance(device, vim.vm.device.VirtualDisk):
                details["disk_status"].append(
                    {
                        "disk_label": device.deviceInfo.label,
                        "disk_capacity_gb": device.capacityInKB / (1024**2),
                    }
                )  # Convert KB to GB
    return details


def find_vm_by_name(
    content: vim.ServiceInstanceContent, vm_name: str
) -> Optional[vim.VirtualMachine]:
    """Find a VM by name.

    Searches for a virtual machine in a VMware vSphere environment by its name.
    Creates a container view of all VMs and checks if any of them match the provided name.

    Args:
        content: The ServiceInstanceContent object for the vSphere environment.
        vm_name: The name of the VM to search for.

    Returns:
        Optional[vim.VirtualMachine]: The VM object if found, None if not found.
    """
    # Type ignore: pyVmomi type stubs don't fully define ViewManager.CreateContainerView
    container = content.viewManager.CreateContainerView(  # type: ignore[attr-defined]
        content.rootFolder, [vim.VirtualMachine], True
    )
    for vm in container.view:
        if vm.name == vm_name:
            return cast(vim.VirtualMachine, vm)
    return None


@click.command()
@click.option("--vcenter_host", prompt="vCenter Host", help="The vCenter server host.")
@click.option("--username", prompt="vCenter Username", help="The vCenter server username.")
@click.option(
    "--password",
    help="The vCenter server password.",
    hide_input=True,
    prompt="vCenter Password",
    default=None,
)
@click.option("--kubeconfig", default=None, help="Path to the kubeconfig file.")
@click.option(
    "--node_search", default="", help="Optional substring to filter Kubernetes nodes by name."
)
@click.option(
    "--label_selector", default="", help="Optional label selector to filter Kubernetes nodes."
)
@click.option(
    "--disable_k8s_ssl", is_flag=True, help="Disable SSL verification for Kubernetes API."
)
@click.option(
    "--disable_vcenter_ssl", is_flag=True, help="Disable SSL verification for vCenter connection."
)
def check_k8s_nodes(  # noqa: C901
    vcenter_host: str,
    username: str,
    password: Optional[str],
    kubeconfig: Optional[str],
    node_search: str,
    label_selector: str,
    disable_k8s_ssl: bool,
    disable_vcenter_ssl: bool,
) -> None:
    """Check Kubernetes nodes on VMware vSphere.

    Checks the status of Kubernetes nodes on a VMware vSphere environment.
    Connects to the vCenter server, retrieves the list of VMs, and checks their power state.
    Displays VM details including power state, IP address, and disk information for each
    matching Kubernetes node.

    Args:
        vcenter_host: The hostname or IP address of the vCenter server.
        username: The username for the vCenter server.
        password: The password for the vCenter server. If None, will prompt for it.
        kubeconfig: Optional path to the kubeconfig file. If None, uses default kubeconfig.
        node_search: Optional substring to filter Kubernetes nodes by name.
        label_selector: Optional label selector to filter Kubernetes nodes.
        disable_k8s_ssl: If True, disable SSL verification for Kubernetes API.
        disable_vcenter_ssl: If True, disable SSL verification for vCenter connection.

    Raises:
        Exception: If Kubernetes config loading fails or vCenter connection fails
            (errors are logged and function returns early).
    """
    # If password is not provided, prompt for it securely
    if password is None:
        password = click.prompt("vCenter Password", hide_input=True)

    # Load Kubernetes configuration
    try:
        if kubeconfig:
            config.load_kube_config(config_file=kubeconfig)
            logger.info(f"Using custom kubeconfig at {kubeconfig}")
        else:
            config.load_kube_config()
            logger.info("Using default kubeconfig")

        if disable_k8s_ssl:
            client.Configuration().verify_ssl = False
            logger.info("SSL verification disabled for Kubernetes API")
    except Exception as e:
        logger.error(f"Failed to load Kubernetes config: {e}")
        return

    k8s_api = client.CoreV1Api()

    # Connect to vCenter
    si = connect_to_vcenter(vcenter_host, username, password, disable_vcenter_ssl)
    if not si:
        logger.error("Could not connect to vCenter.")
        return
    content = si.RetrieveContent()

    # Get the list of Kubernetes nodes, filtered by label selector and/or substring
    try:
        nodes = k8s_api.list_node(label_selector=label_selector).items
        if node_search:
            nodes = [node for node in nodes if node_search in node.metadata.name]
        logger.info(
            f"Found {len(nodes)} nodes matching search '{node_search}' and label selector '{label_selector}'."
        )
    except Exception as e:
        logger.error(f"Failed to retrieve nodes from Kubernetes: {e}")
        Disconnect(si)
        return

    for node in nodes:
        node_name = node.metadata.name
        logger.info(f"\nNode: {node_name}")

        # Attempt to find the VM corresponding to this node
        try:
            vm = find_vm_by_name(content, node_name)
            if not vm:
                logger.error(f"VM for node {node_name} not found in vCenter.")
                continue

            # Get VM details
            vm_details = get_vm_details(vm)

            # Display VM details
            logger.info(f"  VM Name: {vm_details['name']}")
            logger.info(f"  Power State: {vm_details['power_state']}")
            logger.info(f"  IP Address: {vm_details['ip_address']}")

            logger.info("  Disks:")
            for disk in vm_details["disk_status"]:
                logger.info(f"    {disk['disk_label']}: {disk['disk_capacity_gb']} GB")

        except Exception as e:
            logger.error(f"Failed to retrieve details for VM '{node_name}': {e}")

    # Disconnect from vCenter
    Disconnect(si)
    logger.info("\nFinished checking Kubernetes nodes and VM statuses.")


if __name__ == "__main__":
    check_k8s_nodes()
