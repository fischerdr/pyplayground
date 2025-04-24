"""Find a Kubernetes pod by name across all namespaces and display its details."""

import logging
from typing import Any, Dict, Optional

import click
from kubernetes import client
from kubernetes.client.rest import ApiException
from rich.console import Console

from utils.k8s_utils import load_kube_config_auto
from utils.logging_utils import get_logger, setup_logging

# Setup logging
setup_logging(level=logging.INFO, script_name="k8s_find_pod")
logger = get_logger(__name__)
console = Console()


def _get_node_external_ip(v1: client.CoreV1Api, node_name: str) -> Optional[str]:
    """Fetches the external IP address for a given node.

    Args:
        v1: Initialized CoreV1Api client.
        node_name: The name of the node.

    Returns:
        The external IP address string if found, specific error strings on failure,
        or None if no external IP is listed.
    """
    try:
        logger.debug(f"Fetching details for node '{node_name}'.")
        node = v1.read_node(node_name)
        for address in node.status.addresses:
            if address.type == "ExternalIP":
                logger.debug(f"Found ExternalIP '{address.address}' for node '{node_name}'.")
                return address.address
        logger.debug(f"No ExternalIP found for node '{node_name}' in status addresses.")
        return None  # No ExternalIP found
    except ApiException as node_e:
        logger.warning(
            f"Could not fetch node '{node_name}' details: {node_e.status} - {node_e.reason}"
        )
        return "[yellow]Error fetching node info[/yellow]"
    except Exception as node_e:
        logger.exception(f"Unexpected error fetching node '{node_name}': {node_e}")
        return "[red]Error fetching node info[/red]"


def get_pod_info(pod_name: str) -> Optional[Dict[str, Any]]:
    """Searches for a pod by name across all namespaces and returns its details.

    Args:
        pod_name: The name of the pod to search for.

    Returns:
        A dictionary containing pod information (namespace, node_name, pod_ip,
        node_external_ip) if found, otherwise None.
    """
    try:
        # Initialize the API client
        v1 = client.CoreV1Api()

        logger.info(f"Searching for pod '{pod_name}' across all namespaces.")
        pods = v1.list_pod_for_all_namespaces(watch=False)

        for pod in pods.items:
            if pod.metadata.name == pod_name:
                logger.info(f"Found pod '{pod_name}' in namespace '{pod.metadata.namespace}'.")
                node_name = pod.spec.node_name
                pod_ip = pod.status.pod_ip
                namespace = pod.metadata.namespace

                # Get the external IP address of the node
                external_ip = _get_node_external_ip(v1, node_name)

                return {
                    "namespace": namespace,
                    "node_name": node_name,
                    "pod_ip": pod_ip,
                    "node_external_ip": external_ip,
                }

        logger.warning(f"Pod '{pod_name}' not found in any namespace.")
        return None
    except ApiException as e:
        logger.error(f"API error searching for pod '{pod_name}': {e.status} - {e.reason}")
        console.print(
            f"[bold red]API Error:[/bold red] Could not search for pod. Reason: {e.reason}"
        )
        return None
    except Exception as e:
        logger.exception(f"Unexpected error searching for pod '{pod_name}': {e}")
        console.print(
            f"[bold red]Error:[/bold red] An unexpected error occurred during search: {e}"
        )
        return None


@click.command()
@click.argument("pod_name")
def find_pod(pod_name: str):
    """Search for a pod by name and display its node and IP details."""
    logger.info(f"Attempting to find pod '{pod_name}'.")

    # Load Kubernetes configuration
    if not load_kube_config_auto():
        console.print("[bold red]Error:[/bold red] Could not load Kubernetes configuration.")
        return

    pod_info = get_pod_info(pod_name)

    if pod_info:
        console.print(f"Pod [cyan]'{pod_name}'[/cyan] found:")
        console.print(f"  Namespace: [yellow]{pod_info['namespace']}[/yellow]")
        console.print(f"  Node:      [green]{pod_info['node_name']}[/green]")
        console.print(f"  Pod IP:    [blue]{pod_info['pod_ip']}[/blue]")
        ext_ip = pod_info.get("node_external_ip")
        if ext_ip:
            # Check if it's an error message from get_pod_info
            if "Error fetching" in ext_ip:
                console.print(f"  Node External IP: {ext_ip}")  # Already formatted with color
            else:
                console.print(f"  Node External IP: [magenta]{ext_ip}[/magenta]")
        else:
            console.print("  Node External IP: [dim]Not available[/dim]")
    else:
        console.print(f"[yellow]Pod '{pod_name}' not found in any namespace.[/yellow]")


if __name__ == "__main__":
    find_pod()
