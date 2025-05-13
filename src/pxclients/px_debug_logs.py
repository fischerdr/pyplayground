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
    --debug            Enable debug logging
    --help             Show this help message
"""

import logging
import os
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

import click
from kubernetes import client
from kubernetes.client.rest import ApiException
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

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


def find_portworx_pods(v1_client: client.CoreV1Api, pod_name: Optional[str] = None) -> List[Dict]:
    """Search for Portworx pods across all namespaces.

    Args:
        v1_client: Kubernetes CoreV1Api client
        pod_name: Optional pod name to filter by

    Returns:
        List of dictionaries containing pod information
    """
    try:
        pods = v1_client.list_namespaced_pod(
            namespace=DEFAULT_NAMESPACE,
            label_selector=PORTWORX_POD_LABEL,
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


def display_pod_table(pods: List[Dict]) -> None:
    """Display a table of found Portworx pods.

    Args:
        pods: List of pod information dictionaries
    """
    if not pods:
        console.print("[yellow]No Portworx pods found.[/yellow]")
        return

    table = Table(title="Portworx Pods")
    table.add_column("Name", style="cyan")
    table.add_column("Namespace", style="magenta")
    table.add_column("Node", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Pod IP", style="blue")

    for pod in pods:
        table.add_row(pod["name"], pod["namespace"], pod["node"], pod["status"], pod["pod_ip"])

    console.print(table)


def select_pod(pods: List[Dict]) -> Optional[Dict]:
    """Allow user to select a pod from the list.

    Args:
        pods: List of pod information dictionaries

    Returns:
        Selected pod information dictionary or None if cancelled
    """
    if not pods:
        return None

    if len(pods) == 1:
        return pods[0]

    display_pod_table(pods)

    while True:
        pod_name = Prompt.ask("\nEnter pod name to debug (or 'q' to quit)", default="q")

        if pod_name.lower() == "q":
            return None

        selected_pod = next((pod for pod in pods if pod["name"] == pod_name), None)

        if selected_pod:
            return selected_pod

        console.print("[red]Invalid pod name. Please try again.[/red]")


def execute_debug_session(node_name: str) -> Tuple[int, Optional[str]]:
    """Execute oc debug command to establish a debug session.

    Args:
        node_name: Name of the target node

    Returns:
        Tuple of (exit_code, error_message)
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
        "journalctl -flu portworx*",
    ]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate()
        return process.returncode, stderr if stderr else None
    except Exception as e:
        return 1, str(e)


def stream_journal_logs() -> None:
    """Stream and colorize Portworx journal logs in real-time."""
    cmd = ["journalctl", "-flu", "portworx*"]

    # Define log level patterns (both full words and short forms)
    log_patterns = {
        "error": ["error", "err", "failed", "fail", "fatal", "critical"],
        "warning": ["warning", "warn", "wrn"],
        "info": ["info", "inf"],
        "debug": ["debug", "dbg"],
        "timestamp": TIMESTAMP_MONTHS,
    }

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
                for level, patterns in log_patterns.items():
                    if any(pattern in line_lower for pattern in patterns):
                        text.stylize(level)
                        break
                else:
                    # If no log level found, check for timestamps
                    if any(month in line for month in TIMESTAMP_MONTHS):
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
    default=DEFAULT_NAMESPACE,
    help="OpenShift namespace where Portworx is running",
)
@click.option(
    "--kubeconfig",
    type=click.Path(exists=True),
    help="Path to the kubeconfig file",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
def main(pod_name: Optional[str], namespace: str, kubeconfig: Optional[str], debug: bool) -> None:
    """Debug into an OpenShift node and stream Portworx service logs with enhanced readability."""
    # --- Setup Logging ---
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)  # Pass script_name
    logger.debug("Logging setup complete.")

    # Initialize Kubernetes client
    v1_client = setup_kubernetes_client(kubeconfig)

    # Search for Portworx pods
    logger.info("Searching for Portworx pods...")
    pods = find_portworx_pods(v1_client, pod_name)

    # Allow user to select a pod
    selected_pod = select_pod(pods)
    if not selected_pod:
        logger.info("No pod selected. Exiting.")
        sys.exit(0)

    node_name = selected_pod["node"]
    logger.info(f"Selected pod {selected_pod['name']} on node {node_name}")

    # Establish debug session
    logger.info("Establishing debug session...")
    exit_code, error = execute_debug_session(node_name)

    if exit_code != 0:
        logger.error(f"Failed to establish debug session: {error}")
        sys.exit(exit_code)

    logger.info("Debug session established. Streaming Portworx logs...")
    # The logs are now streamed directly from the debug session
    # No need to call stream_journal_logs() separately


if __name__ == "__main__":
    main()
