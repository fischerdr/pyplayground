"""Manage Kubernetes pods: find and inspect."""

import logging
from typing import Any, Dict, List, Optional

import click
from kubernetes import client
from kubernetes.client.rest import ApiException
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from utils.k8s_utils import load_kube_config_auto
from utils.logging_utils import get_logger, setup_logging

# Initialize console
console = Console()
logger = get_logger(__name__)  # Logger setup done per command


def _setup_command_logging(ctx: click.Context, command_name: str):
    """Sets up logging based on verbosity context and command name."""
    verbose = ctx.obj.get("VERBOSE", False)
    log_level = logging.DEBUG if verbose else logging.INFO
    script_name = f"k8s_pod_cli_{command_name}"
    setup_logging(level=log_level, script_name=script_name)


# --- Helper functions from k8s_find_pod ---


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
        # Return formatted error string for display
        return "[yellow]Error fetching node info[/yellow]"
    except Exception as node_e:
        logger.exception(f"Unexpected error fetching node '{node_name}': {node_e}")
        # Return formatted error string for display
        return "[red]Error fetching node info[/red]"


def get_pod_info(pod_name: str) -> Optional[Dict[str, Any]]:
    """Searches for a pod by name across all namespaces and returns its details.

    Used by the 'find' command.

    Args:
        pod_name: The name of the pod to search for.

    Returns:
        A dictionary containing pod information (namespace, node_name, pod_ip,
        node_external_ip) if found, otherwise None.
    """
    try:
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


# --- Helper functions from k8s_inspect_pod ---


def get_pod_details(namespace: str, pod_name: str) -> Optional[client.V1Pod]:
    """Fetches the details of a specific pod from the Kubernetes cluster.

    Used by the 'inspect' command.

    Args:
        namespace: The namespace of the pod.
        pod_name: The name of the pod.

    Returns:
        A V1Pod object containing the pod details, or None if not found or error occurred.
    """
    logger.info(f"Attempting to fetch details for pod '{pod_name}' in namespace '{namespace}'.")
    try:
        v1 = client.CoreV1Api()
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        logger.info(f"Successfully fetched details for pod '{pod_name}'.")
        return pod
    except ApiException as e:
        if e.status == 404:
            logger.error(f"Pod '{pod_name}' not found in namespace '{namespace}'.")
            console.print(
                f"[bold red]Error:[/bold red] Pod '{pod_name}' not found in namespace '{namespace}'."
            )
        else:
            logger.error(
                f"API error fetching pod '{pod_name}' in '{namespace}': {e.status} - {e.reason}"
            )
            console.print(
                f"[bold red]Error:[/bold red] Could not fetch pod '{pod_name}' in namespace '{namespace}'. Reason: {e.reason}"
            )
        return None
    except Exception as e:
        logger.exception(f"Unexpected error fetching pod '{pod_name}' in '{namespace}': {e}")
        console.print(f"[bold red]Error:[/bold red] An unexpected error occurred: {e}")
        return None


def get_pod_logs(
    namespace: str, pod_name: str, container_name: str, tail_lines: int
) -> Optional[str]:
    """Fetches the last N lines of logs for a specific container in a pod.

    Used by the 'inspect' command.

    Args:
        namespace: The namespace of the pod.
        pod_name: The name of the pod.
        container_name: The name of the container within the pod.
        tail_lines: The number of recent log lines to fetch.

    Returns:
        A string containing the fetched logs, or None if an error occurred.
    """
    logger.info(
        f"Attempting to fetch last {tail_lines} log lines for container '{container_name}' in pod '{pod_name}' (namespace: '{namespace}')."
    )
    try:
        v1 = client.CoreV1Api()
        logs = v1.read_namespaced_pod_log(
            name=pod_name, namespace=namespace, container=container_name, tail_lines=tail_lines
        )
        logger.info(f"Successfully fetched logs for container '{container_name}'.")
        return logs
    except ApiException as e:
        logger.error(
            f"API error fetching logs for container '{container_name}' in pod '{pod_name}': {e.status} - {e.reason}"
        )
        # Check if the container exists but logs are not ready (e.g., ContainerCreating)
        if "container not found" in str(e.body).lower():
            console.print(
                f"[bold yellow]Warning:[/bold yellow] Container '{container_name}' not found in pod '{pod_name}'."
            )
        elif "container is waiting" in str(e.body).lower():
            console.print(
                f"[bold yellow]Warning:[/bold yellow] Container '{container_name}' is still waiting to start, logs not available yet."
            )
        else:
            console.print(
                f"[bold red]Error:[/bold red] Could not fetch logs for container '{container_name}'. Reason: {e.reason}"
            )
        return None
    except Exception as e:
        logger.exception(
            f"Unexpected error fetching logs for container '{container_name}' in pod '{pod_name}': {e}"
        )
        console.print(
            f"[bold red]Error:[/bold red] An unexpected error occurred while fetching logs: {e}"
        )
        return None


def format_container_status(status: client.V1ContainerStatus) -> str:
    """Formats the container status into a readable string. Used by 'inspect' command."""
    state_str = "[grey50]Unknown State[/grey50]"
    if status.state:
        if status.state.running:
            started_at_str = (
                status.state.running.started_at.strftime("%Y-%m-%d %H:%M:%S")
                if status.state.running.started_at
                else "N/A"
            )
            state_str = f"[green]Running[/green] (started at {started_at_str})"
        elif status.state.terminated:
            finished_at_str = (
                status.state.terminated.finished_at.strftime("%Y-%m-%d %H:%M:%S")
                if status.state.terminated.finished_at
                else "N/A"
            )
            exit_code = status.state.terminated.exit_code
            reason = status.state.terminated.reason or "N/A"
            state_str = f"[yellow]Terminated[/yellow] (exit code {exit_code}, reason: {reason}, finished at {finished_at_str})"
        elif status.state.waiting:
            reason = status.state.waiting.reason or "N/A"
            message = status.state.waiting.message or "N/A"
            state_str = f"[blue]Waiting[/blue] (reason: {reason}, message: {message})"

    ready_str = "[green]Yes[/green]" if status.ready else "[yellow]No[/yellow]"
    return f"""Ready: {ready_str}
Restarts: {status.restart_count}
State: {state_str}"""


# --- Helper functions for displaying pod info (inspect command) ---


def _create_init_containers_table(pod: client.V1Pod) -> Optional[Table]:
    """Creates a Rich Table for init container information."""
    if not pod.spec.init_containers:
        return None

    init_table = Table(title="Init Containers", show_header=True, header_style="bold magenta")
    init_table.add_column("Name", style="dim", width=20)
    init_table.add_column("Image", style="cyan")
    init_table.add_column("Command", style="green")
    init_table.add_column("Args", style="blue")
    init_table.add_column("Status", style="yellow")

    init_container_statuses = {cs.name: cs for cs in pod.status.init_container_statuses or []}

    for container in pod.spec.init_containers:
        command_str = " ".join(container.command) if container.command else "[grey50]N/A[/grey50]"
        args_str = " ".join(container.args) if container.args else "[grey50]N/A[/grey50]"
        status_obj = init_container_statuses.get(container.name)
        status_str = (
            format_container_status(status_obj) if status_obj else "[red]Status not available[/red]"
        )
        init_table.add_row(container.name, container.image, command_str, args_str, status_str)
    return init_table


def _create_containers_table(pod: client.V1Pod) -> Table:
    """Creates a Rich Table for main container information."""
    container_table = Table(title="Containers", show_header=True, header_style="bold magenta")
    container_table.add_column("Name", style="dim", width=20)
    container_table.add_column("Image", style="cyan")
    container_table.add_column("Command", style="green")
    container_table.add_column("Args", style="blue")
    container_table.add_column("Status", style="yellow")

    container_statuses = {cs.name: cs for cs in pod.status.container_statuses or []}

    for container in pod.spec.containers:
        command_str = " ".join(container.command) if container.command else "[grey50]N/A[/grey50]"
        args_str = " ".join(container.args) if container.args else "[grey50]N/A[/grey50]"
        status_obj = container_statuses.get(container.name)
        status_str = (
            format_container_status(status_obj) if status_obj else "[red]Status not available[/red]"
        )
        container_table.add_row(container.name, container.image, command_str, args_str, status_str)
    return container_table


def _find_mounts_for_volume(pod: client.V1Pod, volume_name: str) -> List[str]:
    """Finds all mount points for a specific volume name across all containers."""
    mount_details = []
    all_containers = (pod.spec.containers or []) + (pod.spec.init_containers or [])
    for container in all_containers:
        if container.volume_mounts:
            for mount in container.volume_mounts:
                if mount.name == volume_name:
                    read_only_str = " - RO" if mount.read_only else ""
                    detail = f"{container.name} ({mount.mount_path}{read_only_str})"
                    mount_details.append(detail)
    return mount_details


def _create_pvc_mounts_table(pod: client.V1Pod) -> Optional[Table]:
    """Creates a Rich Table for Persistent Volume Claim mount information."""
    pvc_volumes = [vol for vol in pod.spec.volumes or [] if vol.persistent_volume_claim]

    if not pvc_volumes:
        return None

    volume_table = Table(
        title="Persistent Volume Claim Mounts", show_header=True, header_style="bold magenta"
    )
    volume_table.add_column("PVC Name", style="cyan")
    volume_table.add_column("Volume Name (in Pod Spec)", style="dim")
    volume_table.add_column("Mounted In Containers (Path)", style="yellow")

    for volume in pvc_volumes:
        pvc_name = volume.persistent_volume_claim.claim_name
        volume_name = volume.name
        mounts = _find_mounts_for_volume(pod, volume_name)
        mount_str = "\n".join(mounts) if mounts else "[grey50]Not mounted[/grey50]"
        volume_table.add_row(pvc_name, volume_name, mount_str)

    return volume_table


def display_pod_info(
    pod: client.V1Pod,
    logs: Optional[str] = None,
    container_name_for_logs: Optional[str] = None,
    tail_lines: Optional[int] = None,
) -> None:
    """Displays the pod and container information using rich Table and Panel.

    Used by the 'inspect' command.

    Args:
        pod: The V1Pod object.
        logs: Optional string containing fetched logs for a specific container.
        container_name_for_logs: Optional name of the container logs were fetched for.
        tail_lines: Optional number of log lines fetched.
    """
    if not pod:
        return

    # --- Pod Information Panel ---
    pod_info_table = Table.grid(padding=(0, 1))
    pod_info_table.add_column(style="bold cyan")
    pod_info_table.add_column()
    pod_info_table.add_row("Name:", pod.metadata.name)
    pod_info_table.add_row("Namespace:", pod.metadata.namespace)
    pod_info_table.add_row("Node:", pod.spec.node_name or "[grey50]N/A[/grey50]")
    pod_info_table.add_row("Pod IP:", pod.status.pod_ip or "[grey50]N/A[/grey50]")
    pod_info_table.add_row("Status:", pod.status.phase or "[grey50]N/A[/grey50]")
    console.print(Panel(pod_info_table, title="[bold]Pod Information[/bold]", expand=False))

    # --- Init Containers Table (if any) ---
    init_table = _create_init_containers_table(pod)
    if init_table:
        console.print(Panel(init_table, title="[bold]Init Containers[/bold]", expand=False))

    # --- Containers Table ---
    container_table = _create_containers_table(pod)
    console.print(Panel(container_table, title="[bold]Containers[/bold]", expand=False))

    # --- Volume Mounts Table (PVCs only) ---
    volume_table = _create_pvc_mounts_table(pod)
    if volume_table:
        console.print(
            Panel(volume_table, title="[bold]Persistent Volume Claims[/bold]", expand=False)
        )

    # --- Container Logs Panel (if fetched) ---
    if logs is not None and container_name_for_logs and tail_lines is not None:
        log_title = f"[bold]Last {tail_lines} Log Lines for Container: [cyan]{container_name_for_logs}[/cyan][/bold]"
        console.print(Panel(logs.strip(), title=log_title, expand=True))
    elif container_name_for_logs:
        # Display message if logs couldn't be fetched for the requested container
        # (Error messages are printed directly in get_pod_logs)
        pass


# --- Click Command Group ---


@click.group()
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable verbose (DEBUG level) logging."
)
@click.pass_context
def pod_cli(ctx, verbose):  # Renamed from pod_manager
    """A tool to find and inspect Kubernetes pods."""
    ctx.ensure_object(dict)
    ctx.obj["VERBOSE"] = verbose
    # Logging setup will be handled within each command based on verbosity


# --- Find Subcommand ---


@pod_cli.command()  # Decorator updated
@click.argument("pod_name")
@click.pass_context
def find(ctx, pod_name: str):
    """Search for a pod by name across all namespaces and display its details."""
    _setup_command_logging(ctx, "find")
    logger = get_logger(__name__)  # Re-get logger after setup
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
            # Check if it's an error message from _get_node_external_ip
            if "Error fetching" in ext_ip:
                console.print(f"  Node External IP: {ext_ip}")  # Already formatted with color
            else:
                console.print(f"  Node External IP: [magenta]{ext_ip}[/magenta]")
        else:
            console.print("  Node External IP: [dim]Not available[/dim]")
    else:
        console.print(f"[yellow]Pod '{pod_name}' not found in any namespace.[/yellow]")


# --- Inspect Subcommand ---


@pod_cli.command()  # Decorator updated
@click.option("--pod-name", "-p", required=True, help="The name of the pod to inspect.")
@click.option("--namespace", "-n", required=True, help="The namespace where the pod resides.")
@click.option(
    "--container",
    "-c",
    "container_name",  # Use 'container_name' as the Python variable name
    help="Specify the container name to fetch logs from.",
)
@click.option(
    "--tail",
    "-t",
    type=int,
    default=5,
    show_default=True,
    help="Number of recent log lines to display.",
)
@click.pass_context
def inspect(ctx, pod_name: str, namespace: str, container_name: Optional[str], tail: int):
    """Inspect a pod and display details about its containers and logs."""
    _setup_command_logging(ctx, "inspect")
    logger = get_logger(__name__)  # Re-get logger after setup

    # Argument Validation
    if tail != 5 and container_name is None:
        raise click.UsageError(
            "The --container/-c option is required when explicitly setting --tail/-t."
        )

    logger.info(f"Attempting to inspect pod '{pod_name}' in namespace '{namespace}'.")
    if container_name:
        logger.info(f"Will attempt to fetch last {tail} logs for container '{container_name}'.")
    logger.debug(f"Verbose logging enabled: {ctx.obj.get('VERBOSE', False)}")

    # Load Kubernetes configuration
    if not load_kube_config_auto():
        console.print("[bold red]Error:[/bold red] Could not load Kubernetes configuration.")
        return

    # Get pod details
    pod_details = get_pod_details(namespace=namespace, pod_name=pod_name)

    # Fetch logs if requested and pod details are available
    fetched_logs: Optional[str] = None
    if pod_details and container_name:
        fetched_logs = get_pod_logs(
            namespace=namespace,
            pod_name=pod_name,
            container_name=container_name,
            tail_lines=tail,
        )

    # Display pod info if found
    if pod_details:
        display_pod_info(
            pod_details,
            logs=fetched_logs,
            container_name_for_logs=container_name,
            tail_lines=tail,
        )
    else:
        logger.warning(
            f"Could not display info because pod details were not found for '{pod_name}' in '{namespace}'."
        )


if __name__ == "__main__":
    pod_cli()  # Updated main call
