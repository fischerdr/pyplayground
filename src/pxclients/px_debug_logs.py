#!/usr/bin/env python3
"""Portworx Node Debug Logs Script.

This script provides functionality to debug into a specific OpenShift node running Portworx
and retrieve real-time service logs with enhanced readability through terminal colorization.

The script performs the following steps:
1. Searches for Portworx pods across the cluster
2. Allows user to select a pod and its node
3. Validates the target node is running Portworx pods
4. Establishes a debug session on the node
5. Streams and colorizes Portworx service logs in real-time

Usage:
    python px_debug_logs.py [OPTIONS]

Options:
    --pod-name TEXT     Name of the Portworx pod to search for
    --namespace TEXT    OpenShift namespace where Portworx is running [default: portworx]
    --kubeconfig TEXT   Path to the kubeconfig file
    --config TEXT       Path to the configuration file [default: config/px_debug_logs.json]
    --debug            Enable debug logging
    --help             Show this help message
"""

import logging
import os
import subprocess
import sys
from typing import Dict, List, Optional

import click
from kubernetes import client
from kubernetes.client.rest import ApiException
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from utils.config_utils import load_json_config
from utils.k8s_utils import get_k8s_client, load_kube_config
from utils.logging_utils import setup_logging

# Constants
DEFAULT_NAMESPACE = "portworx"
PORTWORX_POD_LABEL = "name=portworx"
TIMESTAMP_MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

# Configure rich console with custom theme
console = Console(
    theme=Theme(
        {
            "timestamp": "blue",
            "warning": "yellow",
            "error": "red",
            "info": "dim",
        }
    )
)

# Get logger
logger = logging.getLogger(__name__)


def load_config(config_path: Optional[str] = None) -> Dict:
    """Load configuration from file.

    Args:
        config_path: Optional path to config file

    Returns:
        Dict containing configuration
    """
    try:
        if config_path is None:
            config_path = "config/px_debug_logs.json"
        return load_json_config(config_path)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)


def setup_kubernetes_client(kubeconfig: Optional[str] = None) -> client.CoreV1Api:
    """Initialize and return a Kubernetes CoreV1Api client.

    Args:
        kubeconfig: Optional path to kubeconfig file

    Returns:
        CoreV1Api client instance

    Raises:
        SystemExit: If client initialization fails
    """
    try:
        load_kube_config(config_file=kubeconfig)
        return get_k8s_client("CoreV1Api")
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes client: {e}")
        sys.exit(1)


def find_portworx_pods(
    v1_client: client.CoreV1Api, config: Dict, pod_name: Optional[str] = None
) -> List[Dict]:
    """Search for Portworx pods across all namespaces.

    Args:
        v1_client: Kubernetes CoreV1Api client
        config: Configuration dictionary
        pod_name: Optional pod name to filter by

    Returns:
        List of dictionaries containing pod information
    """
    try:
        pods = v1_client.list_namespaced_pod(
            namespace=config["defaults"]["namespace"],
            label_selector=config["defaults"]["pod_label"],
        )

        pod_info_list = []
        for pod in pods.items:
            if pod_name and pod.metadata.name != pod_name:
                continue

            pod_info = {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "node": pod.spec.node_name,
                "status": pod.status.phase,
                "pod_ip": pod.status.pod_ip,
            }
            pod_info_list.append(pod_info)

        return pod_info_list
    except ApiException as e:
        logger.error(f"Failed to list pods: {e}")
        return []


def display_pod_table(pods: List[Dict], config: Dict) -> None:
    """Display a table of found Portworx pods.

    Args:
        pods: List of pod information dictionaries
        config: Configuration dictionary
    """
    if not pods:
        console.print("[yellow]No Portworx pods found.[/yellow]")
        return

    table = Table(title="Portworx Pods")
    columns = config["display"]["table"]["columns"]

    # Add columns with their individual configurations
    table.add_column("Name", style=columns["name"]["style"], no_wrap=columns["name"]["no_wrap"])
    table.add_column(
        "Namespace", style=columns["namespace"]["style"], no_wrap=columns["namespace"]["no_wrap"]
    )
    table.add_column("Node", style=columns["node"]["style"], no_wrap=columns["node"]["no_wrap"])
    table.add_column(
        "Status", style=columns["status"]["style"], no_wrap=columns["status"]["no_wrap"]
    )
    table.add_column(
        "Pod IP", style=columns["pod_ip"]["style"], no_wrap=columns["pod_ip"]["no_wrap"]
    )

    for pod in pods:
        table.add_row(pod["name"], pod["namespace"], pod["node"], pod["status"], pod["pod_ip"])

    console.print(table)


def select_pod(pods: List[Dict], config: Dict) -> Optional[Dict]:
    """Allow user to select a pod from the list.

    Args:
        pods: List of pod information dictionaries
        config: Configuration dictionary

    Returns:
        Selected pod information dictionary or None if cancelled
    """
    if not pods:
        return None

    if len(pods) == 1:
        return pods[0]

    display_pod_table(pods, config)

    while True:
        pod_name = Prompt.ask("\nEnter pod name to debug (or 'q' to quit)", default="q")

        if pod_name.lower() == "q":
            return None

        selected_pod = next((pod for pod in pods if pod["name"] == pod_name), None)

        if selected_pod:
            return selected_pod

        console.print("[red]Invalid pod name. Please try again.[/red]")


def get_selected_pod(
    pods: List[Dict], pod_name: Optional[str], config_data: Dict
) -> Optional[Dict]:
    """Get the selected pod based on pod_name or user selection.

    Args:
        pods: List of available pods
        pod_name: Optional specific pod name to find
        config_data: Configuration dictionary

    Returns:
        Selected pod dictionary or None if no selection made
    """
    if pod_name:
        selected_pod = next((pod for pod in pods if pod["name"] == pod_name), None)
        if not selected_pod:
            logger.error(
                f"Pod {pod_name} not found in namespace {config_data['defaults']['namespace']}"
            )
            sys.exit(1)
        return selected_pod

    return select_pod(pods, config_data)


def stream_node_logs(node_name: str, config_data: Dict) -> None:
    """Stream logs from a node using debug session.

    Args:
        node_name: Name of the node to stream logs from
        config_data: Configuration dictionary
    """
    cmd = [
        "oc",
        "debug",
        f"node/{node_name}",
        "--",
        "chroot",
        "/host",
        "bash",
        "-c",
        config_data["journalctl"]["command"],
    ]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                # Colorize the output based on content
                text = Text(line.strip())
                line_lower = line.lower()

                # Check for log levels first
                for level, patterns in config_data["log_patterns"].items():
                    if any(pattern in line_lower for pattern in patterns):
                        text.stylize(level)
                        break
                else:
                    # If no log level found, check for timestamps
                    if any(month in line for month in config_data["log_patterns"]["timestamp"]):
                        text.stylize("timestamp")
                    else:
                        text.stylize("info")
                console.print(text)

    except KeyboardInterrupt:
        logger.info("Log streaming interrupted by user")
    except Exception as e:
        logger.error(f"Error streaming logs: {e}")
    finally:
        if process.poll() is None:
            process.terminate()


@click.command()
@click.option(
    "--pod-name",
    help="Name of the Portworx pod to search for",
)
@click.option(
    "--namespace",
    help="OpenShift namespace where Portworx is running",
)
@click.option(
    "--kubeconfig",
    type=click.Path(exists=True),
    help="Path to the kubeconfig file",
)
@click.option(
    "--config",
    type=click.Path(exists=True),
    help="Path to the configuration file",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
def main(
    pod_name: Optional[str],
    namespace: Optional[str],
    kubeconfig: Optional[str],
    config: Optional[str],
    debug: bool,
) -> None:
    """Debug into an OpenShift node and stream Portworx service logs with enhanced readability."""
    # --- Setup Logging ---
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Logging setup complete.")

    # Load configuration
    config_data = load_config(config)
    if namespace:
        config_data["defaults"]["namespace"] = namespace

    # Initialize Kubernetes client
    v1_client = setup_kubernetes_client(kubeconfig)

    # Search for Portworx pods
    logger.info("Searching for Portworx pods...")
    pods = find_portworx_pods(v1_client, config_data, pod_name)

    if not pods:
        logger.error("No Portworx pods found.")
        sys.exit(1)

    # Get selected pod
    selected_pod = get_selected_pod(pods, pod_name, config_data)
    if not selected_pod:
        logger.info("No pod selected. Exiting.")
        sys.exit(0)

    node_name = selected_pod["node"]
    logger.info(f"Selected pod {selected_pod['name']} on node {node_name}")

    # Stream logs
    logger.info("Establishing debug session and streaming logs...")
    stream_node_logs(node_name, config_data)


if __name__ == "__main__":
    main()
