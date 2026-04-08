"""Check Kubernetes nodes and map to ESXi cluster and datastore information.

This module provides functionality to check Kubernetes nodes and correlate them
with their actual ESXi cluster and datastore locations in vCenter. It reads the
actual infrastructure location from vCenter inventory to detect drift from
MachineSet resourcePool configurations.
"""

import json
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

from pyplayground.utils.config_utils import get_env_var, load_env_file
from pyplayground.utils.k8s_utils import console, get_k8s_client
from pyplayground.utils.logging_utils import get_logger
from pyplayground.utils.vmware_utils import (
    get_datastore_info,
    get_vm_cluster_info,
    get_vm_datastores,
)

logger = get_logger(__name__)


@dataclass
class NodeESXiInfo:
    """Structured ESXi infrastructure information for a node."""

    node_name: str
    cluster_name: Optional[str]
    current_host_name: Optional[str]
    datastores: List[Dict[str, Any]]


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


def get_vm_details(si: vim.ServiceInstance, vm: vim.VirtualMachine) -> NodeESXiInfo:
    """Extract ESXi infrastructure information from a VM object.

    Args:
        si: The vCenter ServiceInstance connection.
        vm: The vim.VirtualMachine object to extract information from.

    Returns:
        NodeESXiInfo object containing ESXi infrastructure details.
    """
    cluster_info = get_vm_cluster_info(si, vm)
    datastores = get_vm_datastores(vm)

    return NodeESXiInfo(
        node_name=vm.name,
        cluster_name=cluster_info.get("cluster_name"),
        current_host_name=cluster_info.get("current_host_name"),
        datastores=datastores,
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
    vm_cache: Dict[str, vim.VirtualMachine],
    si: vim.ServiceInstance,
) -> Optional[NodeESXiInfo]:
    """Process a single node and extract ESXi infrastructure info.

    Args:
        node_name: The name of the Kubernetes node to process.
        vm_cache: Pre-fetched cache of VMs from vCenter.
        si: The vCenter ServiceInstance connection.

    Returns:
        NodeESXiInfo object if VM found and details retrieved, None otherwise.
    """
    logger.debug("Processing node: %s", node_name)

    vm = vm_cache.get(node_name)
    if not vm:
        logger.error("VM for node %s not found in vCenter", node_name)
        return None

    try:
        node_info = get_vm_details(si, vm)
        logger.info("Successfully retrieved ESXi info for node: %s", node_name)
        return node_info
    except Exception as e:
        logger.error(
            "Failed to retrieve ESXi info for VM '%s': %s",
            node_name,
            str(e),
            exc_info=True,
        )
        return None


@click.command()
@click.option(
    "--vcenter_host",
    default=None,
    envvar="VCENTER_HOST",
    prompt="vCenter Host",
    help="The vCenter server host. Can also be set via VCENTER_HOST env var.",
)
@click.option(
    "--username",
    default=None,
    envvar="VCENTER_USERNAME",
    prompt="vCenter Username",
    help="The vCenter server username. Can also be set via VCENTER_USERNAME env var.",
)
@click.option(
    "--password",
    default=None,
    envvar="VCENTER_PASSWORD",
    help="The vCenter server password. Can also be set via VCENTER_PASSWORD env var.",
    hide_input=True,
    prompt="vCenter Password",
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
    default="text",
    help="Output format: text (default) or json.",
)
@click.option(
    "--output-file",
    default=None,
    help="Optional file path to save JSON output.",
)
@click.pass_context
def check_k8s_nodes_esxi_datastore(
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
) -> None:
    r"""Check Kubernetes nodes and map to ESXi cluster and datastore information.

    This command checks all Kubernetes nodes and correlates them with
    their actual ESXi cluster and datastore locations in vCenter. It reads
    the actual infrastructure location from vCenter inventory to detect
    drift from MachineSet resourcePool configurations.

    Example usage:
        check_k8s_nodes_esxi_datastore --vcenter_host vcenter.example.com \
            --username administrator@vsphere.local --password password \
            --output-format json --output-file esxi_mapping.json

    Environment variables:
        VCENTER_HOST - vCenter server host
        VCENTER_USERNAME - vCenter username
        VCENTER_PASSWORD - vCenter password
    """
    if len(sys.argv) == 1:
        click.echo(ctx.get_help())
        ctx.exit()

    try:
        load_env_file()
        logger.debug("Loaded environment variables from .env file")
    except Exception as e:
        logger.debug(f"Could not load .env file: {e}")

    vcenter_host = get_env_var("VCENTER_HOST", default=vcenter_host, required=True, as_type=str)
    username = get_env_var("VCENTER_USERNAME", default=username, required=True, as_type=str)
    password = get_env_var("VCENTER_PASSWORD", default=password, required=False, as_type=str)

    if password is None:
        password = click.prompt("vCenter Password", hide_input=True)

    logger.info("Using vCenter host: %s", vcenter_host)
    logger.info("Using username: %s", username)

    vcenter_host_str: str = vcenter_host  # type: ignore[assignment]
    username_str: str = username  # type: ignore[assignment]
    if password is None:
        logger.error("vCenter password is required. Exiting.")
        sys.exit(1)
    password_str: str = password

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
        si = get_vcenter_connection(vcenter_host_str, username_str, password_str, disable_vcenter_ssl)
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

    results: Dict[str, Optional[NodeESXiInfo]] = {}

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(process_node_thread, node.metadata.name, vm_cache, si): node.metadata.name for node in nodes}

        for future in as_completed(futures):
            node_name = futures[future]
            try:
                result = future.result()
                results[node_name] = result
            except Exception as e:
                logger.error("Error processing %s: %s", node_name, str(e), exc_info=True)
                results[node_name] = None

    Disconnect(si)
    logger.info("Finished checking Kubernetes nodes and ESXi infrastructure.")

    json_output: Dict[str, Any] = {}
    for node_name, node_info in results.items():
        if node_info is None:
            json_output[node_name] = {"error": "VM not found or error retrieving ESXi info"}
        else:
            datastore_info_list: List[Dict[str, Any]] = []
            if node_info.datastores:
                for ds_entry in node_info.datastores:
                    ds_mor = ds_entry["datastore_mor"]
                    ds_info = get_datastore_info(si, ds_mor)
                    datastore_info_list.append(ds_info)

            json_output[node_name] = {
                "cluster_name": node_info.cluster_name,
                "current_host_name": node_info.current_host_name,
                "datastores": datastore_info_list,
            }

    if output_format == "json":
        output_str = json.dumps(json_output, indent=2)
        if output_file:
            with open(output_file, "w") as f:
                f.write(output_str)
                logger.info("JSON output written to %s", output_file)
        else:
            click.echo(output_str)
    else:
        console.print("\n[bold]ESXi Infrastructure Mapping for all processed nodes:[/bold]")
        for node_name, node_info in results.items():
            if node_info is None:
                console.print(f"[red]Node: {node_name} - VM not found or error retrieving ESXi info[/red]")
                continue

            table = Table(title=f"Node: {node_name}")
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="green")
            table.add_row("Cluster Name", node_info.cluster_name or "N/A")
            table.add_row("Current ESXi Host", node_info.current_host_name or "N/A")

            if node_info.datastores:
                table.add_row(
                    "Datastores",
                    ", ".join(ds["datastore_name"] for ds in node_info.datastores),
                )
            else:
                table.add_row("Datastores", "N/A")

            console.print(table)

            if node_info.datastores:
                for ds_entry in node_info.datastores:
                    ds_mor = ds_entry["datastore_mor"]
                    ds_info = get_datastore_info(si, ds_mor)
                    ds_table = Table(title=f"Datastore: {ds_info['name']}")
                    ds_table.add_column("Property", style="cyan")
                    ds_table.add_column("Value", style="green")
                    ds_table.add_row("Type", ds_info.get("type", "N/A"))
                    ds_table.add_row("Capacity (GB)", f"{ds_info.get('capacity_gb') or 'N/A'}")
                    ds_table.add_row("Free Space (GB)", f"{ds_info.get('free_space_gb') or 'N/A'}")
                    ds_table.add_row(
                        "Usable Space (GB)",
                        f"{ds_info.get('usable_space_gb') or 'N/A'}",
                    )
                    console.print(ds_table)


if __name__ == "__main__":
    check_k8s_nodes_esxi_datastore()
