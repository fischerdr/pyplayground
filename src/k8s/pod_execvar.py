#! /usr/bin/env python3
"""Script to execute a command in a Kubernetes pod, setting environment variables.

This script allows you to connect to a specific Kubernetes pod, set environment variables,
and then execute a command within that pod.

Usage:
    pod_execvar.py <pod_name> --namespace <namespace> --env_var <env_var> --command <command> --kubeconfig <path_to_kubeconfig> --container <container_name>

Arguments:
    pod_name: Name of the pod to connect to.
    namespace: Namespace of the pod.
    env_var: Environment variable in the format VAR=VALUE.
    command: Command to run in the pod.
    kubeconfig: Path to the kubeconfig file.
    container: Container name in the pod.

"""
import logging  # Add logging import
import os
import sys
from typing import Dict, List, Tuple  # Add typing imports

import click
from kubernetes import client, stream  # Need client for v1 type hint
from kubernetes.client.rest import ApiException  # Import ApiException explicitly
from rich.console import Console  # Import Rich Console

from utils.k8s_utils import (
    determine_target_container,
    get_k8s_client,
    load_kube_config_auto,
)

# Import utility functions
from utils.logging_utils import get_logger, setup_logging

# Setup logging
# Consider making log level configurable if needed
setup_logging(level=logging.INFO, script_name="pod_execvar")
logger = get_logger(__name__)
console = Console()  # Create a Rich Console instance


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


def _execute_and_stream_output(
    v1_client: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    container_name: str,
    full_command_str: str,
) -> int:
    """Executes a command in a pod container and streams output to the console.

    Args:
        v1_client: Initialized CoreV1Api client.
        namespace: The namespace of the pod.
        pod_name: The name of the pod.
        container_name: The name of the target container.
        full_command_str: The complete command string to execute via /bin/sh -c.

    Returns:
        The exit code of the executed command.

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

    logger.info("Command execution finished.")
    if stdout_output:
        console.print("[bold green]--- STDOUT ---[/bold green]")
        console.print(stdout_output.strip())
    if stderr_output:
        console.print("[bold red]--- STDERR ---[/bold red]", style="bold red", stderr=True)
        console.print(stderr_output.strip(), style="bold red", stderr=True)

    return exit_code


@click.command()
@click.argument("pod_name")
@click.option("--namespace", "-n", default="default", help="Namespace of the pod")
@click.option("--env_var", "-e", multiple=True, help="Environment variable in the format VAR=VALUE")
@click.option("--command", "-c", required=True, help="Command to run in the pod")
@click.option("--kubeconfig", "-k", default=None, help="Path to the kubeconfig file")
@click.option(
    "--container",
    "-C",
    default=None,
    help="Container name in the pod (required if pod has multiple containers)",
)  # Changed short flag
@click.option("--debug", "-d", is_flag=True, default=False, help="Enable debug logging")
def exec_in_pod(pod_name, namespace, env_var, command, kubeconfig, container_name, debug):
    """Connect to a Kubernetes pod, set environment variables, and run a command."""
    # Setup Logging
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Starting pod exec script.")

    # Load Kubernetes configuration using utility function
    if not load_kube_config_auto(config_file=kubeconfig):
        sys.exit(1)  # Exit if config loading fails

    # Initialize the API client using utility function
    try:
        v1 = get_k8s_client("CoreV1Api")
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes API client: {e}", exc_info=True)
        sys.exit(1)

    try:
        # Prepare command string
        full_command_str, _ = _prepare_execution_command(env_var, command)

        # Get pod details
        logger.debug(f"Reading pod details for '{pod_name}'...")
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        logger.debug(f"Successfully read details for pod '{pod_name}'.")

        # Determine container
        actual_container_name = determine_target_container(pod, container_name)

        # Execute command and stream output
        exit_code = _execute_and_stream_output(
            v1, namespace, pod_name, actual_container_name, full_command_str
        )

        # Handle exit code
        if exit_code != 0:
            logger.error(f"Command exited with non-zero status code: {exit_code}")
            sys.exit(exit_code)  # Exit with the command's exit code

    except ValueError as e:
        logger.error(f"Input error: {e}")
        sys.exit(1)
    except ApiException as e:
        if e.status == 404:
            logger.error(f"Pod '{pod_name}' not found in namespace '{namespace}'.")
        else:
            logger.error(f"Kubernetes API error: {e.status} {e.reason} - {e.body}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    exec_in_pod()
