#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script to find Portworx PVC usage per pod in a Kubernetes cluster.

This script identifies Portworx PersistentVolumes (PVs), finds pods using them,
and for each pod/container, determines the number of files and total disk usage
for the mounted PVC.


Usage:

```
./get_pod_pv_usage.py --output-file pod_pv_usage_summary --format console --skip-namespace-prefix kube- --skip-namespace-regex test-.* --container-shell /bin/bash --debug
```
"""
import csv
import json
import logging
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import click
from kubernetes import client, stream  # type: ignore
from kubernetes.client.rest import ApiException  # type: ignore
from rich import box
from rich.console import Console
from rich.table import Table

try:
    from utils.k8s_utils import get_k8s_client, load_kube_config_auto
    from utils.logging_utils import get_logger, setup_logging
except ImportError:
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
    from utils.k8s_utils import get_k8s_client, load_kube_config_auto
    from utils.logging_utils import get_logger, setup_logging

# --- Constants ---
PORTWORX_PROVISIONER = "pxd.portworx.com"
DEFAULT_OUTPUT_FILENAME_BASE = "pod_pv_usage_summary"

# Initialize Rich Console
console = Console()
# Logger will be configured in main()

# --- Helper Functions ---


def _run_command_in_container(  # noqa: C901
    v1_client: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    container_name: str,
    command: List[str],
) -> Tuple[int, str, str]:
    """Executes a command in a pod container and returns exit code, stdout, stderr.

    Args:
        v1_client: Initialized CoreV1Api client.
        namespace: Namespace of the pod.
        pod_name: Name of the pod.
        container_name: Name of the target container.
        command: The command list to execute.

    Returns:
        Tuple (exit_code, stdout_data, stderr_data).
    """
    logger = get_logger(__name__)
    stdout_data = ""
    stderr_data = ""
    exit_code = -1
    resp = None
    try:
        logger.debug(
            f"Executing in pod '{pod_name}/{container_name}' (ns: {namespace}): {' '.join(command)}"
        )
        resp = stream.stream(
            v1_client.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=namespace,
            container=container_name,
            command=command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _preload_content=False,
        )

        while resp.is_open():
            resp.update(timeout=1)
            if resp.peek_stdout():
                stdout_data += resp.read_stdout()
            if resp.peek_stderr():
                stderr_data += resp.read_stderr()
    except ApiException as e:
        logger.error(
            f"ApiException during command execution in {pod_name}/{container_name}: {e.status} - {e.reason}",
            exc_info=False,  # Reduce noise for common handshake errors, details are in e.reason
        )
        reason_str = str(e.reason).lower()
        if "container not found" in reason_str:
            stderr_data = f"Container '{container_name}' not found in pod '{pod_name}'."
            logger.warning(f"Command execution failed: {stderr_data}")
        elif "dial-http" in reason_str and "connect: no route to host" in reason_str:
            stderr_data = f"Cannot connect to pod '{pod_name}': No route to host. Pod may be terminating or network issue."
            logger.warning(f"Command execution failed: {stderr_data}")
        else:
            stderr_data = f"API Error: {e.reason}"  # Keep full reason for other API errors
        # exit_code remains -1 or its previous value
    except Exception as e:
        logger.error(
            f"Exception during command execution in {pod_name}/{container_name}: {e}", exc_info=True
        )
        stderr_data = str(e)
    finally:
        if resp:
            resp.close()
            if resp.returncode is not None:  # Ensure returncode is not None
                exit_code = resp.returncode

    if stdout_data:
        logger.debug(f"Cmd stdout (first 200 chars): {stdout_data[:200]}")
    if stderr_data:
        logger.debug(f"Cmd stderr (first 200 chars): {stderr_data[:200]}")

    return exit_code, stdout_data.strip(), stderr_data.strip()


def command_exists_in_container(
    v1_client: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    container_name: str,
    command_to_check: str,
    shell: str = "/bin/sh",
) -> bool:
    """Checks if a command exists in the specified container."""
    logger = get_logger(__name__)
    check_command = [shell, "-c", f"command -v {command_to_check}"]
    exit_code, _, stderr_data = _run_command_in_container(
        v1_client, namespace, pod_name, container_name, check_command
    )
    if exit_code != 0:
        logger.warning(
            f"Command '{command_to_check}' not found in {pod_name}/{container_name}. Stderr: {stderr_data}"
        )
        return False
    return True


def _try_count_with_find(
    v1_client: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    container_name: str,
    mount_path: str,
    shell: str,
) -> Tuple[Optional[int], Optional[str]]:
    """Tries to count files using the 'find | wc -l' method."""
    logger = get_logger(__name__)
    command_template_find_wc = 'find "$1" -type f | wc -l'
    find_wc_command = [shell, "-c", command_template_find_wc, "inline_script", mount_path]
    exit_code, stdout, stderr = _run_command_in_container(
        v1_client, namespace, pod_name, container_name, find_wc_command
    )
    if exit_code == 0 and stdout.isdigit():
        return int(stdout), None
    elif exit_code == 0 and not stdout:  # No files found
        return 0, None
    else:
        error = f"Error running 'find | wc -l' (code {exit_code}): {stderr or stdout}"
        logger.warning(error)
        return None, error


def _try_count_with_ls(
    v1_client: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    container_name: str,
    mount_path: str,
    shell: str,
) -> Tuple[Optional[int], Optional[str]]:
    """Tries to count files using the 'ls | grep | wc -l' method."""
    logger = get_logger(__name__)
    command_template_ls_wc = "ls -ARp \"$1\" | grep -v '/$' | wc -l"
    ls_wc_command = [shell, "-c", command_template_ls_wc, "inline_script", mount_path]
    exit_code, stdout, stderr = _run_command_in_container(
        v1_client, namespace, pod_name, container_name, ls_wc_command
    )
    if exit_code == 0 and stdout.isdigit():
        return int(stdout), None
    elif exit_code == 0 and not stdout:  # No files found
        return 0, None
    else:
        error = f"Error running 'ls | grep | wc' (code {exit_code}): {stderr or stdout}"
        logger.warning(error)
        return None, error


def _determine_file_count(
    v1_client: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    container_name: str,
    mount_path: str,
    shell: str,
) -> Tuple[Optional[int], Optional[str]]:
    """Determines file count in a container, trying 'find' then 'ls | grep | wc'."""
    logger = get_logger(__name__)

    find_available = command_exists_in_container(
        v1_client, namespace, pod_name, container_name, "find", shell
    )
    wc_available = command_exists_in_container(
        v1_client, namespace, pod_name, container_name, "wc", shell
    )

    if find_available and wc_available:
        logger.debug(f"Using 'find' method for file counting in {pod_name}/{container_name}.")
        return _try_count_with_find(
            v1_client, namespace, pod_name, container_name, mount_path, shell
        )
    elif not find_available:
        logger.info(
            f"'find' command not found in {pod_name}/{container_name}. Attempting fallback with 'ls | grep | wc'."
        )
        ls_available = command_exists_in_container(
            v1_client, namespace, pod_name, container_name, "ls", shell
        )
        grep_available = command_exists_in_container(
            v1_client, namespace, pod_name, container_name, "grep", shell
        )

        if ls_available and grep_available and wc_available:
            logger.debug(
                f"Using 'ls | grep | wc' method for file counting in {pod_name}/{container_name}."
            )
            return _try_count_with_ls(
                v1_client, namespace, pod_name, container_name, mount_path, shell
            )
        else:
            missing_cmds_fallback = []
            if not ls_available:
                missing_cmds_fallback.append("ls")
            if not grep_available:
                missing_cmds_fallback.append("grep")
            if not wc_available:  # wc_available check is important here too for the fallback path
                missing_cmds_fallback.append("wc (for fallback)")
            error_msg = f"'find' not found. Fallback failed due to missing: {', '.join(missing_cmds_fallback)}."
            logger.warning(error_msg)
            return None, error_msg
    elif find_available and not wc_available:  # find is there, but wc is not
        error_msg = "'wc' command not found, cannot count files with 'find' method."
        logger.warning(error_msg)
        return None, error_msg

    # Should not be reached if logic is correct, but as a safeguard:
    return None, "File counting could not be performed due to an unexpected state."


def get_pvc_usage_in_container(
    v1_client: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    container_name: str,
    mount_path: str,
    shell: str = "/bin/sh",
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Gets file count and total size for a given mount path in a container.

    Returns:
        Tuple (num_files, total_size_str, error_message).
        num_files or total_size_str will be None if they cannot be determined.
        error_message contains details if an error occurred.
    """
    logger = get_logger(__name__)
    num_files: Optional[int] = None
    total_size_str: Optional[str] = None
    accumulated_error_message: Optional[str] = None

    # --- File Counting --- #
    num_files, file_count_error = _determine_file_count(
        v1_client, namespace, pod_name, container_name, mount_path, shell
    )
    if file_count_error:
        accumulated_error_message = file_count_error
    # --- End File Counting ---

    # --- Size Calculation (du) ---
    du_available = command_exists_in_container(
        v1_client, namespace, pod_name, container_name, "du", shell
    )
    if du_available:
        logger.debug(f"Using 'du' method for size calculation in {pod_name}/{container_name}.")
        command_template_du = 'du -sh "$1"'
        du_command = [shell, "-c", command_template_du, "inline_script", mount_path]
        du_exit_code, du_stdout, du_stderr = _run_command_in_container(
            v1_client, namespace, pod_name, container_name, du_command
        )

        if du_exit_code == 0 and du_stdout:
            parts = du_stdout.split()
            if parts:
                total_size_str = parts[0]
            else:
                total_size_str = "N/A (du output parse error)"
                logger.warning(
                    f"Could not parse 'du -sh' output: '{du_stdout}' for {pod_name}/{container_name}:{mount_path}"
                )
        else:
            du_error_msg = f"Error running 'du -sh' (code {du_exit_code}): {du_stderr or du_stdout}"
            logger.warning(du_error_msg)
            if accumulated_error_message:
                accumulated_error_message = f"{accumulated_error_message}; {du_error_msg}"
            else:
                accumulated_error_message = du_error_msg
    else:
        du_missing_error = f"'du' command not found in container {container_name}"
        logger.warning(du_missing_error)
        if accumulated_error_message:
            accumulated_error_message = f"{accumulated_error_message}; {du_missing_error}"
        else:
            accumulated_error_message = du_missing_error
    # --- End Size Calculation ---

    return num_files, total_size_str, accumulated_error_message


def find_pvc_mount_info_in_pod(  # noqa: C901
    pod_object: client.V1Pod, target_pvc_name: str
) -> List[Tuple[str, str, bool]]:
    """Finds all container names and mount paths for a specific PVC within a given pod.

    Args:
        pod_object: The V1Pod object.
        target_pvc_name: The name of the PersistentVolumeClaim to find.

    Returns:
        A list of tuples, where each tuple is (container_name, mount_path, container_is_running).
        Returns an empty list if the PVC is not mounted or not found.
    """
    logger = get_logger(__name__)
    mount_infos: List[Tuple[str, str, bool]] = []
    pod_name = pod_object.metadata.name

    # Create a map of container statuses for quick lookup
    container_statuses: Dict[str, client.V1ContainerStatus] = {}
    if pod_object.status and pod_object.status.container_statuses:
        for cs in pod_object.status.container_statuses:
            container_statuses[cs.name] = cs

    init_container_statuses: Dict[str, client.V1ContainerStatus] = {}
    if pod_object.status and pod_object.status.init_container_statuses:
        for ics in pod_object.status.init_container_statuses:
            init_container_statuses[ics.name] = ics

    # 1. Find the volume name in pod.spec.volumes that maps to the target_pvc_name
    volume_name_for_pvc: Optional[str] = None
    if pod_object.spec.volumes:
        for vol in pod_object.spec.volumes:
            if (
                vol.persistent_volume_claim
                and vol.persistent_volume_claim.claim_name == target_pvc_name
            ):
                volume_name_for_pvc = vol.name
                logger.debug(
                    f"In pod '{pod_name}', PVC '{target_pvc_name}' corresponds to volume '{volume_name_for_pvc}'."
                )
                break

    if not volume_name_for_pvc:
        logger.debug(f"PVC '{target_pvc_name}' not found as a volume in pod '{pod_name}'.")
        return mount_infos

    # 2. Find all mounts of this volume_name_for_pvc in main containers
    if pod_object.spec.containers:
        for container in pod_object.spec.containers:
            if container.volume_mounts:
                for vm in container.volume_mounts:
                    if vm.name == volume_name_for_pvc:
                        # Check container status
                        cs = container_statuses.get(container.name)
                        is_running = cs and cs.state and cs.state.running is not None
                        logger.debug(
                            f"Found mount for PVC '{target_pvc_name}' in container '{container.name}' of pod '{pod_name}' at path '{vm.mount_path}'. Running: {is_running}"
                        )
                        mount_infos.append((container.name, vm.mount_path, is_running))

    # 3. Optionally, find mounts in init containers (if relevant to your use case)
    if pod_object.spec.init_containers:
        for init_container in pod_object.spec.init_containers:
            if init_container.volume_mounts:
                for vm in init_container.volume_mounts:
                    if vm.name == volume_name_for_pvc:
                        # Check init container status
                        ics = init_container_statuses.get(init_container.name)
                        is_running = (
                            ics and ics.state and ics.state.running is not None
                        )  # Init containers complete, so look for terminated with exit 0 if that's the goal
                        # For exec, it generally needs to be in a running-like state or have recently finished.
                        # Let's assume 'running' is the primary state for exec for now, or if it has terminated successfully (exit code 0)
                        # For simplicity, we only check if init container *was* running or *is* running.
                        # A more robust check might involve looking at `terminated` state with `exitCode == 0` if post-completion inspection is desired.
                        # However, exec usually implies an active container.
                        if ics and ics.state:
                            if ics.state.running:
                                is_running = True
                            elif ics.state.terminated and ics.state.terminated.exit_code == 0:
                                # Technically not "running", but might be exec-able briefly or for post-mortem if tools are there.
                                # For our use case of `du` and `find`, a completed init container is not a target.
                                # So, stick to `running` or adapt if a different use case for init arises.
                                pass  # is_running remains False or its previous value for init that are not actively running

                        logger.debug(
                            f"Found mount for PVC '{target_pvc_name}' in init_container '{init_container.name}' of pod '{pod_name}' at path '{vm.mount_path}'. Current status allows exec: {is_running}"
                        )
                        # Only add if actually exec-able for `du`/`find`.
                        # Init containers are usually short-lived. If they are not running, we usually can't exec.
                        # The exception might be a debug init container left running.
                        if (
                            is_running
                        ):  # Simplified: only add if init container is currently marked as running
                            mount_infos.append((init_container.name, vm.mount_path, is_running))
                        else:
                            logger.debug(
                                f"Init container '{init_container.name}' is not in a running state for PVC checks."
                            )

    if not mount_infos:
        logger.debug(
            f"No mount paths found for PVC '{target_pvc_name}' (volume '{volume_name_for_pvc}') in any container of pod '{pod_name}'."
        )

    return mount_infos


def _format_output_filename(base_filename: str, format_ext: str) -> str:
    """Generates a timestamped output filename in the 'tmp/' directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base, orig_ext = os.path.splitext(base_filename)
    if not orig_ext or orig_ext.lower() not in [
        ".json",
        ".csv",
    ]:  # if user accidentally included ext
        filename_with_ts = f"{base_filename}_{timestamp}.{format_ext}"
    else:  # user specified base name like "file.json", want "file_timestamp.json"
        filename_with_ts = f"{base}_{timestamp}.{format_ext}"

    # Ensure output is in tmp/ directory if not an absolute path
    if os.path.isabs(filename_with_ts):
        full_path = filename_with_ts
    else:
        current_dir = os.getcwd()
        full_path = os.path.join(current_dir, "tmp", filename_with_ts)

    # Ensure the directory exists
    output_dir = os.path.dirname(full_path)
    if output_dir:  # Could be empty if filename has no path components
        os.makedirs(output_dir, exist_ok=True)
    return full_path


def output_results_console(results: List[Dict[str, Any]]):
    """Outputs results to the console using Rich."""
    # logger = get_logger(__name__) # Unused logger
    if not results:
        console.print("[yellow]No PVC usage data to display.[/yellow]")
        return

    table = Table(
        title="Pod PVC Usage Summary",
        box=box.ASCII,
        show_lines=True,
        title_style="bold blue",
    )
    table.add_column("PV Name", style="dim", no_wrap=False)  # Added PV Name
    table.add_column("Pod Name", style="cyan", no_wrap=True)
    table.add_column("Namespace", style="magenta")
    table.add_column("PVC Name", style="green")
    table.add_column("Container", style="blue")
    table.add_column("Mount Path", style="yellow")
    table.add_column("Num Files", style="white")
    table.add_column("Total Size", style="white")
    table.add_column("Error", style="red", overflow="fold")

    for item in results:
        table.add_row(
            item.get("pv_name", "N/A"),  # Added PV Name
            item.get("pod_name", "N/A"),
            item.get("namespace", "N/A"),
            item.get("pvc_name", "N/A"),
            item.get("container_name", "N/A"),
            item.get("mount_path", "N/A"),
            str(item.get("num_files", "N/A")),
            item.get("total_size", "N/A"),
            item.get("error_message", ""),
        )
    console.print(table)


def output_results_json(results: List[Dict[str, Any]], filename_base: str):
    """Outputs results to a JSON file."""
    logger = get_logger(__name__)
    output_filename = _format_output_filename(filename_base, "json")

    try:
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        logger.info(f"Successfully wrote JSON output to '{output_filename}'")
        console.print(f"[green]JSON output saved to:[/green] {output_filename}")
    except IOError as e:
        logger.error(f"Failed to write JSON output to '{output_filename}': {e}", exc_info=True)
        console.print(f"[bold red]Error writing JSON file '{output_filename}': {e}[/bold red]")


def output_results_csv(results: List[Dict[str, Any]], filename_base: str):
    """Outputs results to a CSV file."""
    logger = get_logger(__name__)
    output_filename = _format_output_filename(filename_base, "csv")

    fieldnames = [
        "pv_name",  # Added PV Name
        "pod_name",
        "namespace",
        "pvc_name",
        "container_name",
        "mount_path",
        "num_files",
        "total_size",
        "error_message",
    ]
    try:
        with open(output_filename, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for item in results:
                # Ensure all keys are present, defaulting to "N/A" or empty string
                row_to_write = {key: item.get(key) for key in fieldnames}
                if row_to_write.get("num_files") is None:
                    row_to_write["num_files"] = "N/A"
                if row_to_write.get("total_size") is None:
                    row_to_write["total_size"] = "N/A"
                if row_to_write.get("error_message") is None:
                    row_to_write["error_message"] = ""
                writer.writerow(row_to_write)
        logger.info(f"Successfully wrote CSV output to '{output_filename}'")
        console.print(f"[green]CSV output saved to:[/green] {output_filename}")
    except IOError as e:
        logger.error(f"Failed to write CSV output to '{output_filename}': {e}", exc_info=True)
        console.print(f"[bold red]Error writing CSV file '{output_filename}': {e}[/bold red]")


# --- Main Click Command ---


@click.command()
@click.option(
    "--kubeconfig",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the kubeconfig file. Uses default lookup if not provided.",
    envvar="KUBECONFIG",
)
@click.option(
    "--output-file",
    default=DEFAULT_OUTPUT_FILENAME_BASE,
    show_default=True,
    help="Base name for the output file (without extension). Saved to ./tmp/ if relative.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["console", "json", "csv"], case_sensitive=False),
    default="console",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--skip-namespace-prefix",
    multiple=True,
    help="Prefix of namespaces to skip for PVC search (e.g., 'kube-'). Can be used multiple times.",
)
@click.option(
    "--skip-namespace-regex",
    multiple=True,
    help="Regular expression for namespaces to skip (e.g., 'test-.*'). Can be used multiple times.",
)
@click.option(
    "--container-shell",
    default="/bin/sh",
    show_default=True,
    help="Shell to use for 'command -v' and other shell executions in containers.",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(  # noqa: C901
    kubeconfig: Optional[str],
    output_file: str,
    output_format: str,
    skip_namespace_prefix: Tuple[str, ...],  # Type hint for tuple of strings
    skip_namespace_regex: Tuple[str, ...],  # Added new regex option
    container_shell: str,
    debug: bool,
):
    """Finds Portworx PVC usage per pod in a Kubernetes cluster."""
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger = get_logger(__name__)  # Get logger instance after setup

    logger.info("Starting Pod PV Usage script...")
    logger.info(f"Kubeconfig: {kubeconfig or 'Default lookup'}")
    logger.info(f"Output file base: {output_file}, Format: {output_format}")
    if skip_namespace_prefix:
        logger.info(f"Skipping namespaces with prefixes: {', '.join(skip_namespace_prefix)}")
    if skip_namespace_regex:
        logger.info(f"Skipping namespaces matching regexes: {', '.join(skip_namespace_regex)}")
    logger.info(f"Container shell for checks: {container_shell}")

    if not load_kube_config_auto(config_file=kubeconfig):
        console.print("[bold red]Error: Failed to load Kubernetes configuration.[/bold red]")
        sys.exit(1)

    try:
        core_v1 = get_k8s_client("CoreV1Api")
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes API client: {e}", exc_info=True)
        console.print(f"[bold red]Error initializing Kubernetes client: {e}[/bold red]")
        sys.exit(1)

    all_results: List[Dict[str, Any]] = []

    try:
        logger.info(f"Fetching Portworx PVs (driver: {PORTWORX_PROVISIONER})...")
        pvs_list = core_v1.list_persistent_volume()

        # First, count total Portworx PVs for progress logging
        total_portworx_pvs = sum(
            1
            for pv_item in pvs_list.items
            if pv_item.spec and pv_item.spec.csi and pv_item.spec.csi.driver == PORTWORX_PROVISIONER
        )

        if total_portworx_pvs == 0:
            logger.info(f"No Portworx PVs (driver: {PORTWORX_PROVISIONER}) found in the cluster.")
            console.print(
                f"[yellow]No Portworx PVs (driver: {PORTWORX_PROVISIONER}) found.[/yellow]"
            )
            if output_format == "console":  # Ensure empty results are handled by output functions
                output_results_console(all_results)
            elif output_format == "json":
                output_results_json(all_results, output_file)
            elif output_format == "csv":
                output_results_csv(all_results, output_file)
            sys.exit(0)

        logger.info(f"Found {total_portworx_pvs} Portworx PVs to process.")
        processed_pv_count = 0

        # Compile regexes once before the loop
        compiled_regexes = []
        if skip_namespace_regex:
            for pattern in skip_namespace_regex:
                try:
                    compiled_regexes.append(re.compile(pattern))
                except re.error as e:
                    logger.error(
                        f"Invalid regex pattern '{pattern}': {e} - This pattern will be ignored."
                    )
                    # Optionally, exit or raise an error:
                    # console.print(f"[bold red]Error: Invalid regex pattern '{pattern}': {e}[/bold red]")
                    # sys.exit(1)

        for pv_item in pvs_list.items:
            if not (
                pv_item.spec
                and pv_item.spec.csi
                and pv_item.spec.csi.driver == PORTWORX_PROVISIONER
            ):
                continue

            pv_name = pv_item.metadata.name
            processed_pv_count += 1
            progress_log_msg = (
                f"Processing Portworx PV {processed_pv_count}/{total_portworx_pvs}: {pv_name}"
            )

            if not pv_item.spec.claim_ref:
                logger.warning(f"{progress_log_msg} - has no claimRef, skipping.")
                all_results.append(
                    {
                        "pv_name": pv_name,
                        "pod_name": "N/A (PV unbound)",
                        "namespace": "N/A",
                        "pvc_name": "N/A (PV unbound)",
                        "container_name": "N/A",
                        "mount_path": "N/A",
                        "num_files": "N/A",
                        "total_size": "N/A",
                        "error_message": f"PV {pv_name} is unbound (no claimRef)",
                    }
                )
                continue

            pvc_name = pv_item.spec.claim_ref.name
            pvc_namespace = pv_item.spec.claim_ref.namespace
            logger.info(f"{progress_log_msg} -> PVC '{pvc_namespace}/{pvc_name}'")

            # Combine skip logic
            skipped_by_prefix = any(
                pvc_namespace.startswith(prefix) for prefix in skip_namespace_prefix
            )
            skipped_by_regex = False
            if compiled_regexes:
                if any(regex.fullmatch(pvc_namespace) for regex in compiled_regexes):
                    skipped_by_regex = True

            skip_reason = None
            if skipped_by_prefix:
                skip_reason = f"namespace prefix rule ({', '.join(skip_namespace_prefix)})"
            elif skipped_by_regex:
                skip_reason = f"namespace regex rule ({', '.join(skip_namespace_regex)})"

            if skip_reason:
                logger.info(f"Skipping PVC '{pvc_namespace}/{pvc_name}' due to {skip_reason}.")
                all_results.append(
                    {
                        "pv_name": pv_name,
                        "pod_name": "N/A (Namespace skipped)",
                        "namespace": pvc_namespace,
                        "pvc_name": pvc_name,
                        "container_name": "N/A",
                        "mount_path": "N/A",
                        "num_files": "N/A",
                        "total_size": "N/A",
                        "error_message": f"Namespace {pvc_namespace} skipped by {skip_reason}",
                    }
                )
                continue

            try:
                pods_in_namespace = core_v1.list_namespaced_pod(namespace=pvc_namespace)
            except ApiException as e:
                logger.error(
                    f"Failed to list pods in namespace '{pvc_namespace}' for PVC '{pvc_name}': {e.reason}",
                    exc_info=True,
                )
                all_results.append(
                    {
                        "pv_name": pv_name,
                        "pod_name": "N/A (API Error)",
                        "namespace": pvc_namespace,
                        "pvc_name": pvc_name,
                        "container_name": "N/A",
                        "mount_path": "N/A",
                        "num_files": "N/A",
                        "total_size": "N/A",
                        "error_message": f"API Error listing pods in {pvc_namespace}: {e.reason}",
                    }
                )
                continue

            found_pod_using_pvc = False
            for pod_obj in pods_in_namespace.items:
                pod_name_iter = pod_obj.metadata.name
                if pod_obj.status.phase != "Running":
                    logger.debug(
                        f"Skipping pod '{pod_name_iter}' in namespace '{pvc_namespace}' (status: {pod_obj.status.phase})."
                    )
                    continue

                mount_infos = find_pvc_mount_info_in_pod(pod_obj, pvc_name)
                if not mount_infos:
                    logger.debug(
                        f"Pod '{pod_name_iter}' (ns: {pvc_namespace}) does not appear to mount PVC '{pvc_name}'."
                    )
                    continue

                found_pod_using_pvc = True
                logger.info(
                    f"Pod '{pod_name_iter}' (ns: {pvc_namespace}) uses PVC '{pvc_name}'. Found mounts: {mount_infos}"
                )

                for container_name, mount_path, container_is_running in mount_infos:
                    if not container_is_running:
                        logger.warning(
                            f"Container '{container_name}' in pod '{pod_name_iter}' is not in a running state. Skipping PVC usage check for mount '{mount_path}'."
                        )
                        all_results.append(
                            {
                                "pv_name": pv_name,
                                "pod_name": pod_name_iter,
                                "namespace": pvc_namespace,
                                "pvc_name": pvc_name,
                                "container_name": container_name,
                                "mount_path": mount_path,
                                "num_files": "N/A",
                                "total_size": "N/A",
                                "error_message": f"Container {container_name} not running",
                            }
                        )
                        continue  # Skip to the next mount or pod

                    num_files, total_size, err_msg = get_pvc_usage_in_container(
                        core_v1,
                        pvc_namespace,
                        pod_name_iter,
                        container_name,
                        mount_path,
                        container_shell,
                    )
                    all_results.append(
                        {
                            "pv_name": pv_name,
                            "pod_name": pod_name_iter,
                            "namespace": pvc_namespace,
                            "pvc_name": pvc_name,
                            "container_name": container_name,
                            "mount_path": mount_path,
                            "num_files": num_files if num_files is not None else "N/A",
                            "total_size": total_size if total_size is not None else "N/A",
                            "error_message": err_msg if err_msg else "",
                        }
                    )

            if not found_pod_using_pvc:
                logger.info(
                    f"No running pods found actively using PVC '{pvc_namespace}/{pvc_name}'."
                )
                all_results.append(
                    {
                        "pv_name": pv_name,
                        "pod_name": "N/A (No pods found)",
                        "namespace": pvc_namespace,
                        "pvc_name": pvc_name,
                        "container_name": "N/A",
                        "mount_path": "N/A",
                        "num_files": "N/A",
                        "total_size": "N/A",
                        "error_message": f"No running pods found using PVC {pvc_namespace}/{pvc_name}",
                    }
                )

        logger.info(f"Finished processing all {total_portworx_pvs} identified Portworx PVs.")

    except ApiException as e:
        logger.error(
            f"Kubernetes API Error during main processing: {e.status} {e.reason} - {e.body}",
            exc_info=True,
        )
        console.print(f"[bold red]Kubernetes API Error: {e.reason}[/bold red]")
        all_results.append(
            {
                "pv_name": "N/A (Global API Error)",  # Added PV Name
                "pod_name": "N/A (Global API Error)",
                "namespace": "N/A",
                "pvc_name": "N/A",
                "container_name": "N/A",
                "mount_path": "N/A",
                "num_files": "N/A",
                "total_size": "N/A",
                "error_message": f"Global K8s API Error: {e.reason}",
            }
        )
    except KeyboardInterrupt:
        logger.warning("Script execution interrupted by user (Ctrl+C).")
        console.print("[yellow]\nExecution interrupted by user.[/yellow]")
        # Optionally add a partial result summary or just exit
        all_results.append(
            {
                "pv_name": "N/A (Interrupted)",  # Added PV Name
                "pod_name": "N/A (Interrupted)",
                "namespace": "N/A",
                "pvc_name": "N/A",
                "container_name": "N/A",
                "mount_path": "N/A",
                "num_files": "N/A",
                "total_size": "N/A",
                "error_message": "Script interrupted by user.",
            }
        )
        # Output whatever was collected so far before exiting
        if output_format == "console":
            output_results_console(all_results)
        elif output_format == "json":
            output_results_json(all_results, output_file)
        elif output_format == "csv":
            output_results_csv(all_results, output_file)
        sys.exit(130)
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")
        console.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
        all_results.append(
            {
                "pv_name": "N/A (Script Error)",  # Added PV Name
                "pod_name": "N/A (Script Error)",
                "namespace": "N/A",
                "pvc_name": "N/A",
                "container_name": "N/A",
                "mount_path": "N/A",
                "num_files": "N/A",
                "total_size": "N/A",
                "error_message": f"Unexpected script error: {str(e)}",
            }
        )

    # --- Output Results ---
    # Filter results to only include those from running pods with actual usage data or exec errors
    final_output_results = [
        item
        for item in all_results
        if item.get("pod_name") and not item.get("pod_name", "").startswith("N/A (")
    ]

    if not final_output_results:
        logger.info("No data from running pods to output after filtering.")
        # For console, print a message. For file outputs, an empty file will be created by the output functions.
        if output_format == "console":
            console.print(
                "[yellow]No data from PVs/PVCs actively used by running pods to display.[/yellow]"
            )
        # Fall through to output functions which will handle empty lists (e.g., write empty JSON array or CSV with headers)

    if output_format == "console":
        output_results_console(final_output_results)
    elif output_format == "json":
        output_results_json(final_output_results, output_file)
    elif output_format == "csv":
        output_results_csv(final_output_results, output_file)

    logger.info("Pod PV Usage script finished.")
    if any(item.get("error_message") for item in final_output_results if item.get("error_message")):
        console.print(
            "[yellow]Some errors occurred during processing. Please check logs and output for details.[/yellow]"
        )


if __name__ == "__main__":
    main()
