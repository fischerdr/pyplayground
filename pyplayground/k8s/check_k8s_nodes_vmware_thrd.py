"""Check Kubernetes nodes against VMware VM status with threading.

This module provides functionality to check Kubernetes nodes and correlate them
with VMware virtual machine status. It uses a thread pool for concurrent processing
with one connection per thread following the pool pattern.
"""

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import click
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim
from rich.table import Table

from pyplayground.utils.k8s_utils import console, get_k8s_client
from pyplayground.utils.logging_utils import get_logger

logger = get_logger(__name__)


@dataclass
class VMInfo:
    """Structured VM information."""

    name: str
    power_state: str
    ip_address: Optional[str]
    disks: List[Dict[str, Any]]
    network_interfaces: List[Dict[str, Any]]


def get_vcenter_connection(
    vcenter_host: str,
    username: str,
    password: str,
    disable_ssl: bool,
) -> Optional[vim.ServiceInstance]:
    """Establish a connection to vCenter.

    Args:
        vcenter_host: The vCenter server host.
        username: The vCenter server username.
        password: The vCenter server password.
        disable_ssl: Whether to disable SSL certificate validation.

    Returns:
        vim.ServiceInstance object upon successful connection, None otherwise.
    """
    try:
        si = SmartConnect(
            host=vcenter_host,
            user=username,
            pwd=password,
            disableSslCertValidation=disable_ssl,
        )
        logger.debug("Successfully connected to vCenter: %s", vcenter_host)
        return si  # type: ignore[no-any-return]
    except vim.fault.InvalidLogin as e:
        logger.error("vCenter login failed for %s: %s", vcenter_host, e.msg)
        return None
    except IOError as e:
        logger.error("vCenter connection error for %s: %s", vcenter_host, str(e))
        return None
    except Exception as e:
        logger.error(
            "Unexpected error connecting to vCenter %s: %s",
            vcenter_host,
            str(e),
            exc_info=True,
        )
        return None


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


def create_vm_cache(si: vim.ServiceInstance) -> Dict[str, vim.VirtualMachine]:
    """Create a cache of VMs by name for faster lookup.

    Args:
        si: The vCenter ServiceInstance.

    Returns:
        Dictionary mapping VM names to vim.VirtualMachine objects.
    """
    vm_cache: Dict[str, vim.VirtualMachine] = {}
    content = si.RetrieveContent()
    container = content.viewManager.CreateContainerView(  # type: ignore[attr-defined]
        content.rootFolder,  # type: ignore[attr-defined]
        [vim.VirtualMachine],
        True,
    )
    try:
        for vm in container.view:
            vm_cache[vm.name] = vm
        logger.debug("Cached %d VMs from vCenter", len(vm_cache))
    finally:
        container.Destroy()
    return vm_cache


def process_node_thread(
    node_name: str,
    vcenter_host: str,
    vm_cache: Dict[str, vim.VirtualMachine],
) -> Optional[VMInfo]:
    """Process a single node in its own thread with dedicated connection.

    Args:
        node_name: The name of the Kubernetes node to process.
        vcenter_host: The vCenter server host.
        vm_cache: Pre-fetched cache of VMs from vCenter.

    Returns:
        VMInfo object if VM found and details retrieved, None otherwise.
    """
    logger.debug("Processing node: %s", node_name)

    vm = vm_cache.get(node_name)
    if not vm:
        logger.error("VM for node %s not found in vCenter", node_name)
        return None

    try:
        vm_details = get_vm_details(vm)
        logger.info("Successfully retrieved VM details for node: %s", node_name)
        return vm_details
    except Exception as e:
        logger.error(
            "Failed to retrieve details for VM '%s': %s",
            node_name,
            str(e),
            exc_info=True,
        )
        return None


@click.command()
@click.option(
    "--vcenter_host",
    required=True,
    prompt="vCenter Host",
    help="The vCenter server host.",
)
@click.option(
    "--username",
    required=True,
    prompt="vCenter Username",
    help="The vCenter server username.",
)
@click.option(
    "--password",
    required=True,
    help="The vCenter server password.",
    hide_input=True,
    prompt="vCenter Password",
    default=None,
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
    "--pool_size",
    default=5,
    help="Number of connections in the vCenter connection pool.",
)
@click.option(
    "--output-format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format: text (default) or json.",
)
@click.pass_context
def check_k8s_nodes(
    ctx: click.Context,
    vcenter_host: str,
    username: str,
    password: Optional[str],
    kubeconfig: Optional[str],
    node_search: str,
    label_selector: str,
    disable_k8s_ssl: bool,
    disable_vcenter_ssl: bool,
    threads: int,
    pool_size: int,
    output_format: str,
) -> None:
    """Check Kubernetes nodes against VMware VM status with threading.

    This command checks all Kubernetes nodes and correlates them with
    VMware virtual machine status. It processes nodes concurrently using
    a thread pool with dedicated vCenter connections per thread.
    """
    if len(sys.argv) == 1:
        click.echo(ctx.get_help())
        ctx.exit()

    if password is None:
        password = click.prompt("vCenter Password", hide_input=True)

    try:
        if kubeconfig:
            config.load_kube_config(config_file=kubeconfig)
            logger.info("Using custom kubeconfig at %s", kubeconfig)
        else:
            config.load_kube_config()
            logger.info("Using default kubeconfig")

        if disable_k8s_ssl:
            client.Configuration().verify_ssl = False
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
        si = get_vcenter_connection(vcenter_host, username, password, disable_vcenter_ssl)
        if not si:
            logger.error("Failed to connect to vCenter. Exiting.")
            sys.exit(1)
        logger.info("Connected to vCenter: %s", vcenter_host)
    except Exception as e:
        logger.error("Unexpected error connecting to vCenter: %s", str(e), exc_info=True)
        sys.exit(1)

    try:
        vm_cache = create_vm_cache(si)
        logger.info("Cached %d VMs from vCenter for lookup", len(vm_cache))
    except Exception as e:
        logger.error("Failed to create VM cache: %s", str(e), exc_info=True)
        Disconnect(si)
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
        Disconnect(si)
        sys.exit(1)
    except Exception as e:
        logger.error(
            "Unexpected error retrieving nodes from Kubernetes: %s",
            str(e),
            exc_info=True,
        )
        Disconnect(si)
        sys.exit(1)

    results: Dict[str, Optional[VMInfo]] = {}

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {
            executor.submit(
                process_node_thread,
                node.metadata.name,
                vcenter_host,
                vm_cache,
            ): node.metadata.name
            for node in nodes
        }

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
        click.echo(json.dumps(json_output, indent=2))
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
