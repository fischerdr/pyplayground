"""Check Kubernetes nodes against VMware VM status with threading.

This module provides functionality to check Kubernetes nodes and correlate them
with VMware virtual machine status. It uses a thread pool for concurrent processing
with one connection per thread following the pool pattern.
"""

import datetime
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import click
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from pyVim.connect import Disconnect
from pyVmomi import vim
from rich.table import Table

from pyplayground.utils.config_utils import get_env_var, load_env_file
from pyplayground.utils.k8s_utils import console, get_k8s_client, get_ocp_cluster_name
from pyplayground.utils.logging_utils import get_logger, get_project_root, setup_logging
from pyplayground.utils.vmware_utils import connect, get_cluster_vms

logger = get_logger(__name__)


@dataclass
class VMInfo:
    """Structured VM information."""

    name: str
    power_state: str
    ip_address: Optional[str]
    disks: List[Dict[str, Any]]
    network_interfaces: List[Dict[str, Any]]


def get_vm_details(vm: vim.VirtualMachine) -> VMInfo:
    """Extract detailed information from a VM object.

    Args:
        vm: The vim.VirtualMachine object to extract information from.

    Returns:
        VMInfo object containing structured VM details.
    """
    ip_address: Optional[str] = None
    # pyVmomi type stubs are incomplete, suppressing mypy errors
    if vm.guest and vm.guest.ipAddress:  # type: ignore
        ip_address = vm.guest.ipAddress  # type: ignore

    network_interfaces: List[Dict[str, Any]] = []
    if vm.guest and vm.guest.net:  # type: ignore
        for nic in vm.guest.net:  # type: ignore
            nic_info: Dict[str, Any] = {
                "mac_address": nic.macAddress,
                "ip_addresses": [],
            }
            if nic.ipConfig and nic.ipConfig.ipAddress:
                for adr in nic.ipConfig.ipAddress:
                    ip_info: Dict[str, Any] = {
                        "ip_address": adr.ipAddress,
                        "prefix_length": adr.prefixLength,
                    }
                    nic_info["ip_addresses"].append(ip_info)
            network_interfaces.append(nic_info)

    disks: List[Dict[str, Any]] = []
    for device in vm.config.hardware.device:  # type: ignore[attr-defined]
        if isinstance(device, vim.vm.device.VirtualDisk):
            disks.append(
                {
                    "disk_label": device.deviceInfo.label,
                    "disk_capacity_gb": device.capacityInKB / (1024**2),
                }
            )

    return VMInfo(
        name=vm.name,
        power_state=vm.runtime.powerState,  # type: ignore[attr-defined]
        ip_address=ip_address,
        disks=disks,
        network_interfaces=network_interfaces,
    )


def create_vm_cache(si: vim.ServiceInstance, cluster_name: Optional[str] = None) -> Dict[str, VMInfo]:
    """Create a cache of pre-fetched VM details by name.

    Uses optimized get_cluster_vms() with PropertyCollector pagination to:
    - Fetch only required VM properties (not full objects)
    - Handle large inventories (1000+ VMs) efficiently
    - Filter VMs by cluster name prefix when provided

    All vCenter API calls happen here in a single-threaded context.
    Threads later just do dictionary lookups - no shared connection needed.

    Args:
        si: The vCenter ServiceInstance.
        cluster_name: Optional cluster name prefix to filter VMs by.

    Returns:
        Dictionary mapping VM names to pre-computed VMInfo objects.
    """
    if cluster_name:
        logger.info("Using cluster name filtering: %s", cluster_name)
        vms = get_cluster_vms(si, cluster_name)
    else:
        logger.warning("No cluster name provided, caching all VMs from vCenter")
        content = si.RetrieveContent()
        container = content.viewManager.CreateContainerView(  # type: ignore[attr-defined]
            content.rootFolder,  # type: ignore[attr-defined]
            [vim.VirtualMachine],
            True,
        )
        try:
            vms = {vm.name: vm for vm in container.view}
            logger.debug("Cached %d VMs from vCenter", len(vms))
        finally:
            container.Destroy()

    vm_details: Dict[str, VMInfo] = {}
    for name, vm in vms.items():
        try:
            details = get_vm_details(vm)
            vm_details[name] = details
            logger.debug("Pre-fetched details for VM: %s", name)
        except Exception as e:
            logger.warning("Failed to fetch details for VM '%s': %s", name, str(e))

    return vm_details


def process_node_thread(
    node_name: str,
    vm_cache: Dict[str, VMInfo],
) -> Optional[VMInfo]:
    """Process a single node by looking up pre-fetched VM details.

    Args:
        node_name: The name of the Kubernetes node to process.
        vm_cache: Pre-computed cache of VMInfo objects from vCenter.

    Returns:
        VMInfo object if VM found, None otherwise.
    """
    logger.debug("Processing node: %s", node_name)

    vm_info = vm_cache.get(node_name)
    if not vm_info:
        logger.error("VM for node %s not found in vCenter", node_name)
        return None

    logger.info("Successfully retrieved VM details for node: %s", node_name)
    return vm_info


@click.command()
@click.option(
    "--vcenter_host",
    default=None,
    envvar="VCENTER_HOST",
    help="The vCenter server host. Can also be set via VCENTER_HOST env var.",
)
@click.option(
    "--username",
    default=None,
    envvar="VCENTER_USERNAME",
    help="The vCenter server username. Can also be set via VCENTER_USERNAME env var.",
)
@click.option(
    "--password",
    default=None,
    envvar="VCENTER_PASSWORD",
    help="The vCenter server password. Can also be set via VCENTER_PASSWORD env var.",
    hide_input=True,
)
@click.option("--kubeconfig", default=None, help="Path to the kubeconfig file.")
@click.option(
    "--node_search",
    default="",
    help="Optional substring to filter Kubernetes nodes by name.",
)
@click.option(
    "--label_selector",
    default="",
    help="Optional label selector to filter Kubernetes nodes.",
)
@click.option(
    "--disable_k8s_ssl",
    is_flag=True,
    help="Disable SSL verification for Kubernetes API.",
)
@click.option(
    "--disable_vcenter_ssl",
    is_flag=True,
    help="Disable SSL verification for vCenter connection.",
)
@click.option("--threads", default=5, help="Number of threads for concurrent node processing.")
@click.option(
    "--output-format",
    type=click.Choice(["text", "json"]),
    default="json",
    help="Output format: text (default) or json.",
)
@click.option(
    "--output-file",
    default=None,
    help="Optional file path to save JSON output.",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging to logs directory.",
)
@click.pass_context
def check_k8s_nodes(
    ctx: click.Context,
    vcenter_host: Optional[str],
    username: Optional[str],
    password: Optional[str],
    kubeconfig: Optional[str],
    node_search: str,
    label_selector: str,
    disable_k8s_ssl: bool,
    disable_vcenter_ssl: bool,
    threads: int,
    output_format: str,
    output_file: Optional[str],
    debug: bool,
) -> None:
    """Check Kubernetes nodes against VMware VM status with threading.

    This command checks all Kubernetes nodes and correlates them with
    VMware virtual machine status. It processes nodes concurrently using
    a thread pool with dedicated vCenter connections per thread.
    """
    logging_level = logging.DEBUG if debug else logging.INFO
    script_name = os.path.basename(__file__).replace(".py", "")
    setup_logging(level=logging_level, script_name=script_name)
    logger.info("Logging initialized at %s level", logging.getLevelName(logging_level))

    try:
        load_env_file()
        logger.debug("Loaded environment variables from .env file")
    except Exception as e:
        logger.warning("Could not load .env file: %s", str(e))

    try:
        vcenter_host = get_env_var("VCENTER_HOST", default=vcenter_host, required=True, as_type=str)
        username = get_env_var("VCENTER_USERNAME", default=username, required=True, as_type=str)
        password = get_env_var("VCENTER_PASSWORD", default=password, required=False, as_type=str)
    except ValueError as e:
        logger.error("Missing required credentials: %s", str(e))
        sys.exit(1)

    if password is None:
        logger.error("vCenter password is required. Exiting.")
        sys.exit(1)

    logger.info("Using vCenter host: %s", vcenter_host)
    logger.info("Using username: %s", username)

    try:
        if kubeconfig:
            config.load_kube_config(config_file=kubeconfig)
            logger.info("Using custom kubeconfig at %s", kubeconfig)
        else:
            config.load_kube_config()
            logger.info("Using default kubeconfig")

        if disable_k8s_ssl:
            configuration = client.Configuration()
            configuration.verify_ssl = False
            client.Configuration.set_default(configuration)
            logger.info("SSL verification disabled for Kubernetes API")
    except config.config_exception.ConfigException as e:
        logger.error("Failed to load Kubernetes config: %s", str(e))
        sys.exit(1)
    except Exception as e:
        logger.error("Unexpected error loading Kubernetes config: %s", str(e), exc_info=True)
        sys.exit(1)

    try:
        k8s_api = get_k8s_client("CoreV1Api")
    except Exception as e:
        logger.error("Failed to create Kubernetes API client: %s", str(e))
        sys.exit(1)

    try:
        si = connect(
            type(
                "Args",
                (),
                {
                    "host": vcenter_host,
                    "user": username,
                    "password": password,
                    "port": 443,
                    "disable_ssl_verification": disable_vcenter_ssl,
                },
            )()
        )
        if not si:
            logger.error("Failed to connect to vCenter. Exiting.")
            sys.exit(1)
        logger.info("Connected to vCenter: %s", vcenter_host)
    except Exception as e:
        logger.error("Unexpected error connecting to vCenter: %s", str(e), exc_info=True)
        sys.exit(1)

    try:
        cluster_name = get_ocp_cluster_name(kubeconfig=kubeconfig)
        if cluster_name:
            logger.info("Detected OCP cluster name: %s", cluster_name)
        else:
            logger.warning("Could not detect OCP cluster name, will cache all VMs")
        vm_cache = create_vm_cache(si, cluster_name)
        logger.info("Cached %d VMs from vCenter for lookup", len(vm_cache))
    except Exception as e:
        logger.error("Failed to create VM cache: %s", str(e), exc_info=True)
        sys.exit(1)

    try:
        nodes = k8s_api.list_node(label_selector=label_selector).items
        if node_search:
            nodes = [node for node in nodes if node_search in node.metadata.name]
        logger.info(
            "Found %d nodes matching search '%s' and label selector '%s'",
            len(nodes),
            node_search,
            label_selector,
        )
    except ApiException as e:
        logger.error("Failed to retrieve nodes from Kubernetes: %s", str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(
            "Unexpected error retrieving nodes from Kubernetes: %s",
            str(e),
            exc_info=True,
        )
        sys.exit(1)

    results: Dict[str, Optional[VMInfo]] = {}

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(process_node_thread, node.metadata.name, vm_cache): node.metadata.name for node in nodes}

        for future in as_completed(futures):
            node_name = futures[future]
            try:
                result = future.result()
                results[node_name] = result
            except Exception as e:
                logger.error(f"Error processing {node_name}: {e}", exc_info=True)
                results[node_name] = None

    Disconnect(si)
    logger.info("Finished checking Kubernetes nodes and VM statuses.")

    if output_format == "json":
        import json

        json_output: Dict[str, Any] = {}
        for node_name, vm_info in results.items():
            if vm_info is None:
                json_output[node_name] = {"error": "VM not found or error retrieving details"}
            else:
                json_output[node_name] = {
                    "name": vm_info.name,
                    "power_state": vm_info.power_state,
                    "ip_address": vm_info.ip_address,
                    "disks": vm_info.disks,
                    "network_interfaces": vm_info.network_interfaces,
                }

        if not output_file:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            cluster_safe = cluster_name.replace("/", "_").replace("\\", "_") if cluster_name else "unknown"
            tmp_dir = os.path.join(get_project_root(), "tmp")
            os.makedirs(tmp_dir, exist_ok=True)
            output_file = os.path.join(tmp_dir, f"k8s_nodes_{cluster_safe}_{timestamp}.json")

        output_str = json.dumps(json_output, indent=2)
        with open(output_file, "w") as f:
            f.write(output_str)
        logger.info("JSON output written to %s", output_file)
    else:
        console.print("\n[bold]VM Information for all processed nodes:[/bold]")
        for node_name, vm_info in results.items():
            if vm_info is None:
                console.print(f"[red]Node: {node_name} - VM not found or error retrieving details[/red]")
            else:
                table = Table(title=f"Node: {node_name}")
                table.add_column("Property", style="cyan")
                table.add_column("Value", style="green")
                table.add_row("VM Name", vm_info.name)
                table.add_row("Power State", vm_info.power_state)
                table.add_row("IP Address", vm_info.ip_address or "N/A")

                for disk in vm_info.disks:
                    table.add_row(
                        f"Disk: {disk['disk_label']}",
                        f"{disk['disk_capacity_gb']} GB",
                    )

                for nic in vm_info.network_interfaces:
                    table.add_row(f"MAC: {nic['mac_address']}", "")
                    for ip in nic["ip_addresses"]:
                        table.add_row(
                            f"  IP: {ip['ip_address']}",
                            f"Prefix: {ip['prefix_length']}",
                        )

                console.print(table)


if __name__ == "__main__":
    check_k8s_nodes()
