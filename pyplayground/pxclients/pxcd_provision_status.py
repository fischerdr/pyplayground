#! /usr/bin/env python3
"""Script to get Portworx provision status from a running pod."""

import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import click
from kubernetes import client, stream
from kubernetes.client.rest import ApiException
from rich.console import Console
from rich.table import Table
from rich.text import Text

# Import utility functions from utils
# We might need determine_target_container later, but keep it for now
from pyplayground.utils.k8s_utils import (
    determine_target_container,
    get_k8s_client,
    load_kube_config_auto,
)
from pyplayground.utils.logging_utils import get_logger, setup_logging

# Setup logging initially (will be reconfigured in main function)
script_base_name = os.path.basename(__file__).replace(".py", "")
setup_logging(level=logging.INFO, script_name=script_base_name)
logger = get_logger(__name__)
console = Console()  # For stdout
stderr_console = Console(stderr=True)  # For stderr


def _find_running_portworx_pod(v1_client: client.CoreV1Api, namespace: str) -> str:
    """Finds the name of the first running pod with labels 'name=portworx' and 'storage=true'.

    Args:
        v1_client: Initialized CoreV1Api client.
        namespace: The namespace to search within.

    Returns:
        The name of the first running Portworx pod found matching the labels.

    Raises:
        ValueError: If no running Portworx pod matching the labels is found.
        ApiException: If the Kubernetes API call fails.
    """
    target_labels = "name=portworx,storage=true"
    logger.debug(
        f"Searching for running pods in namespace '{namespace}' with labels '{target_labels}'..."
    )
    try:
        pod_list = v1_client.list_namespaced_pod(namespace=namespace, label_selector=target_labels)
    except ApiException as e:
        logger.error(
            f"API error listing pods in namespace '{namespace}' with labels '{target_labels}': {e}",
            exc_info=True,
        )
        raise  # Re-raise the ApiException

    running_pod_name = None
    for pod in pod_list.items:
        if pod.status.phase == "Running":
            running_pod_name = pod.metadata.name
            logger.debug(f"Found running pod matching labels: '{running_pod_name}'")
            break  # Found the first one, stop searching

    if not running_pod_name:
        error_msg = (
            f"No running pod with labels '{target_labels}' found in namespace '{namespace}'."
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    return running_pod_name


def _prepare_execution_command(
    env_var_list: List[str], base_command: str
) -> Tuple[str, Dict[str, str]]:
    """Parses environment variables and constructs the full command string.

    Args:
        env_var_list: List of environment variables in "VAR=VALUE" format.
        base_command: The base command to execute after setting env vars.

    Returns:
        A tuple containing:
            - The full command string (e.g., "export VAR=VAL && command").
            - The parsed environment variables dictionary.

    Raises:
        ValueError: If an environment variable format is invalid.
    """
    env_vars = {}
    for var in env_var_list:
        if "=" not in var:
            error_msg = f"Invalid environment variable format: '{var}'. Use VAR=VALUE."
            logger.error(error_msg)
            raise ValueError(error_msg)
        key, value = var.split("=", 1)
        env_vars[key] = value

    if env_vars:
        # Consider more robust shell escaping if values can be complex
        env_command = " && ".join([f'export {key}="{value}"' for key, value in env_vars.items()])
        full_command_str = f"{env_command} && {base_command}"
    else:
        full_command_str = base_command

    logger.debug(f"Prepared full command: {full_command_str}")
    return full_command_str, env_vars


def _format_bytes(size_bytes: int) -> str:
    """Converts bytes into a human-readable string (TiB, GiB, MiB)."""
    if size_bytes == 0:
        return "0 B"
    power = 1024
    n = 0
    power_labels = {0: "", 1: "Ki", 2: "Mi", 3: "Gi", 4: "Ti"}
    while size_bytes >= power and n < 4:
        size_bytes /= power
        n += 1
    # Format to one decimal place, adjust precision as needed
    return f"{size_bytes:.1f} {power_labels[n]}B"


def _execute_and_stream_output(
    v1_client: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    container_name: str,
    full_command_str: str,
) -> Tuple[int, Optional[str]]:
    """Executes a command in a pod container, prints stderr, returns exit code and stdout.

    Args:
        v1_client: Initialized CoreV1Api client.
        namespace: The namespace of the pod.
        pod_name: The name of the pod.
        container_name: The name of the target container.
        full_command_str: The complete command string to execute via /bin/sh -c.

    Returns:
        A tuple containing:
            - The integer exit code of the executed command.
            - The captured standard output as a string, or None if the command failed.

    Raises:
        ApiException: If the Kubernetes API call fails.
        Exception: For other unexpected errors during streaming.
    """
    logger.info(f"Executing command in container '{container_name}' of pod '{pod_name}'...")
    response = stream.stream(
        v1_client.connect_get_namespaced_pod_exec,
        name=pod_name,
        namespace=namespace,
        container=container_name,
        command=["/bin/sh", "-c", full_command_str],
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False,
        _preload_content=False,  # Get raw response
    )

    # Read stdout and stderr
    stdout_output = ""
    stderr_output = ""
    try:
        while response.is_open():
            response.update(timeout=1)
            if response.peek_stdout():
                stdout_output += response.read_stdout()
            if response.peek_stderr():
                stderr_output += response.read_stderr()
    finally:
        response.close()

    exit_code = response.returncode
    logger.info(f"Command execution finished with exit code {exit_code}.")

    # Always print stderr if it exists, using the dedicated stderr console
    if stderr_output:
        logger.warning("Command produced output on stderr:")
        stderr_console.print("[bold red]--- STDERR ---[/bold red]", style="bold red")
        stderr_console.print(stderr_output.strip(), style="bold red")

    # Return exit code and stdout data (or None if failed)
    if exit_code == 0:
        return exit_code, stdout_output
    else:
        # Don't return stdout if the command failed
        return exit_code, None


def _parse_provision_info(
    provision_info: Dict[str, Any],
) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    """Parses raw provisionInfo data and extracts relevant details.

    Args:
        provision_info: The dictionary extracted from the 'provisionInfo' JSON key.

    Returns:
        A tuple containing:
            - summary_data: Dict with counts (total_nodes, up_nodes, storage_nodes).
            - storage_node_details: List of dicts, each containing details for one storage node.
    """
    storage_node_details = []
    total_nodes = 0
    up_nodes = 0

    for node_id, node_data in provision_info.items():
        total_nodes += 1
        node_status = node_data.get("Status", "N/A")
        if node_status == "Up":
            up_nodes += 1

        provision_list = node_data.get("Provision")
        if isinstance(provision_list, list) and provision_list:
            try:
                # Extract data for storage nodes
                pool_data = provision_list[0].get("Pool", {})
                pool_info = pool_data.get("Info", {})
                pool_labels = pool_data.get("labels", {})

                hostname = pool_labels.get("kubernetes.io/hostname", "N/A")
                pool_status = pool_info.get("Status", "N/A")
                total_size_bytes = pool_info.get("TotalSize", 0)
                used_size_bytes = pool_info.get("Used", 0)
                drive_count = pool_info.get("ResourcesCount", 0)

                node_details_dict = {
                    "px_node_id": node_id,
                    "k8s_hostname": hostname,
                    "node_status": node_status,
                    "pool_status": pool_status,
                    "pool_size_bytes": total_size_bytes,
                    "pool_used_bytes": used_size_bytes,
                    "drive_count": drive_count,
                }
                storage_node_details.append(node_details_dict)

            except Exception as e:
                logger.error(f"Error processing data for node '{node_id}': {e}", exc_info=True)
                # Optionally add error marker to details if needed for JSON output
                # storage_node_details.append({"px_node_id": node_id, "error": str(e)})

    summary_data = {
        "total_nodes": total_nodes,
        "up_nodes": up_nodes,
        "storage_nodes_reporting_pools": len(storage_node_details),
    }
    return summary_data, storage_node_details


def _save_json_output(summary_data: Dict[str, int], node_details: List[Dict[str, Any]]) -> bool:
    """Saves the processed data to a JSON file in tmp/."""
    output_dir = os.path.join(os.getcwd(), "tmp")
    output_filename = os.path.join(output_dir, "pxcd_provision_status.json")

    # Calculate total used bytes for summary
    total_used_bytes = sum(node.get("pool_used_bytes", 0) for node in node_details)
    summary_data["total_pool_used_bytes"] = total_used_bytes  # Add to summary

    final_output = {"summary": summary_data, "storage_node_details": node_details}

    try:
        logger.debug(f"Attempting to create directory: {output_dir}")
        os.makedirs(output_dir, exist_ok=True)
        logger.debug(f"Directory ensured: {output_dir}")

        logger.debug(f"Attempting to write JSON to: {output_filename}")
        with open(output_filename, "w") as f:
            json.dump(final_output, f, indent=4)
        logger.info(f"JSON output saved successfully to: {output_filename}")
        return True
    except TypeError as e:
        logger.error(f"Failed to serialize data to JSON: {e}", exc_info=True)
        return False
    except OSError as e:
        logger.error(
            f"Failed to create directory or write JSON output file '{output_filename}': {e}",
            exc_info=True,
        )
        return False
    except Exception as e:
        logger.error(f"Unexpected error saving JSON file: {e}", exc_info=True)
        return False


def _print_rich_table(summary_data: Dict[str, int], node_details: List[Dict[str, Any]]) -> None:
    """Prints the processed data as a Rich table with a totals row."""
    if node_details:
        # Calculate total used bytes
        total_used_bytes = sum(node.get("pool_used_bytes", 0) for node in node_details)
        total_used_formatted = _format_bytes(total_used_bytes)
        storage_node_count = len(node_details)

        table = Table(
            title="Portworx Storage Node Provision Status",
            show_header=True,
            header_style="bold magenta",
            caption=f"Total Nodes Found: {summary_data['total_nodes']}, Nodes Up: {summary_data['up_nodes']}",
        )
        table.add_column("PX Node ID", style="dim", width=36)
        table.add_column("K8s Hostname", style="cyan")
        table.add_column("Node Status", justify="center")
        table.add_column("Pool Status", justify="center")
        table.add_column("Pool Size", justify="right")
        table.add_column("Pool Used", justify="right")
        table.add_column("Drives", justify="center")

        for node_detail in node_details:
            node_status_text = Text(
                node_detail["node_status"],
                style="green" if node_detail["node_status"] == "Up" else "bold red",
            )
            pool_status_text = Text(
                node_detail["pool_status"],
                style="green" if node_detail["pool_status"] == "Up" else "bold red",
            )
            total_size_formatted = _format_bytes(node_detail["pool_size_bytes"])
            used_size_formatted = _format_bytes(node_detail["pool_used_bytes"])
            drive_count_str = str(node_detail["drive_count"])

            table.add_row(
                node_detail["px_node_id"],
                node_detail["k8s_hostname"],
                node_status_text,
                pool_status_text,
                total_size_formatted,
                used_size_formatted,
                drive_count_str,
            )

        # Add separator and totals row
        table.add_section()
        table.add_row(
            f"[bold]Totals ({storage_node_count} storage nodes)[/bold]",
            "",  # Span K8s Hostname
            "",  # Span Node Status
            "",  # Span Pool Status
            "",  # Span Pool Size
            f"[bold]{total_used_formatted}[/bold]",  # Total Used
            "",  # Span Drives
            style="on grey23",  # Style the totals row
        )

        console.print(table)
    else:
        # Print summary even if no storage nodes found
        console.print(
            f"Total Nodes Found: {summary_data['total_nodes']}, Nodes Up: {summary_data['up_nodes']}. "
            f"No storage nodes with provisioned pools found in the output."
        )


def _display_provision_status(json_output: str, as_json: bool) -> bool:
    """Parses the JSON output and displays/saves provisioned nodes info."""
    try:
        data = json.loads(json_output)
        provision_info = data.get("provisionInfo")
        if not provision_info:
            logger.error("'provisionInfo' key not found in JSON output.")
            return False
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON output: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error loading JSON data: {e}", exc_info=True)
        return False

    # Process the raw data
    try:
        summary_data, node_details = _parse_provision_info(provision_info)
    except Exception as e:
        logger.error(f"Unexpected error parsing provision info: {e}", exc_info=True)
        return False

    # Output based on the flag
    if as_json:
        return _save_json_output(summary_data, node_details)
    else:
        _print_rich_table(summary_data, node_details)
        return True  # Assume printing success unless an exception occurred during parsing


def _initialize_script(debug: bool, kubeconfig: Optional[str]) -> client.CoreV1Api:
    """Sets up logging, loads kubeconfig, and initializes the K8s client."""
    # Setup Logging
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Starting Portworx provision status script.")

    # Load Kubernetes configuration
    if not load_kube_config_auto(config_file=kubeconfig):
        logger.critical("Failed to load Kubernetes configuration. Exiting.")
        sys.exit(1)
    logger.debug("Kubernetes configuration loaded successfully.")

    # Initialize API client
    try:
        v1 = get_k8s_client("CoreV1Api")
        logger.debug("Kubernetes API client initialized successfully.")
        return v1
    except Exception as e:
        logger.critical(f"Failed to initialize Kubernetes API client: {e}", exc_info=True)
        sys.exit(1)


@click.command()
@click.option(
    "--namespace",
    "-n",
    default="kube-system",  # Default namespace for Portworx
    help="Namespace where Portworx pods are running.",
    show_default=True,
)
@click.option(
    "--kubeconfig",
    "-k",
    default=None,
    help="Path to the kubeconfig file.",
    type=click.Path(exists=True, dir_okay=False),
)
@click.option(
    "--env-var",
    "-e",
    multiple=True,
    help="Environment variable to set in the pod (VAR=VALUE format).",
)
@click.option(
    "--output-json",
    "-j",
    is_flag=True,
    default=False,
    help="Output the processed data as JSON instead of a table.",
)
@click.option("--debug", "-d", is_flag=True, default=False, help="Enable debug logging.")
def get_px_status(namespace, kubeconfig, env_var, output_json, debug):
    """Gets the Portworx cluster provision status from a running pod."""
    # Initialize script (logging, config, client)
    v1 = _initialize_script(debug, kubeconfig)

    try:
        # Prepare command string using the helper
        base_command = "/opt/pwx/bin/pxctl cluster provision-status -j"
        full_command_str, _ = _prepare_execution_command(env_var, base_command)

        # Find a running Portworx pod
        pod_name = _find_running_portworx_pod(v1, namespace)

        # Get pod details (needed for determine_target_container)
        logger.debug(f"Reading pod details for '{pod_name}'...")
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        logger.debug(f"Successfully read details for pod '{pod_name}'.")

        # Determine the target container (should be 'portworx')
        container_name = determine_target_container(pod, "portworx")

        # Execute the command and stream output
        exit_code, stdout_data = _execute_and_stream_output(
            v1, namespace, pod_name, container_name, full_command_str
        )

        # Handle exit code from the executed command
        if exit_code != 0:
            logger.error(f"pxctl command failed with exit code: {exit_code}")
            # Attempt to display partial/error info if possible?
            # Or just exit as currently implemented.
            sys.exit(exit_code)

        # If command succeeded, process and display/save the output
        if stdout_data:
            if not _display_provision_status(stdout_data, output_json):
                logger.error("Failed to process or display/save the command output.")
                sys.exit(1)
        else:
            logger.error("Command succeeded but no output was received.")
            sys.exit(1)

    except ValueError as e:
        # Handle errors from pod finding, container determination or env var parsing
        logger.error(f"Configuration or Input error: {e}")
        sys.exit(1)
    except ApiException as e:
        # Handle Kubernetes API errors
        if e.status == 404:
            logger.error(
                f"Could not find/read pod details in namespace '{namespace}'. Ensure Portworx is running and RBAC permissions are correct."
            )
        else:
            logger.error(f"Kubernetes API error: {e.status} {e.reason} - {e.body}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        # Handle any other unexpected errors
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    get_px_status()
