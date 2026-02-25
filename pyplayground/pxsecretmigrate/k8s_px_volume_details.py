#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script to query Portworx PVs/PVCs in Kubernetes and enrich with pxctl details.

This script connects to a Kubernetes cluster, identifies PersistentVolumes (PVs)
provisioned by Portworx (pxd.portworx.com), executes 'pxctl volume inspect'
for each PV within a Portworx pod, and combines the Kubernetes metadata
with the pxctl output into a structured JSON format.

Example usage:

```
    python src/k8s/k8s_px_volume_details.py --kubeconfig ...
    python src/k8s/k8s_px_volume_details.py --kubeconfig ... --output-file px-volume-summary --format json
    python src/k8s/k8s_px_volume_details.py --kubeconfig ... --output-file px-volume-summary --format csv
    python src/k8s/k8s_px_volume_details.py --kubeconfig ... --output-file px-volume-summary --format console
```
"""

import base64
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import click
from kubernetes import client, stream
from kubernetes.client.rest import ApiException
from rich import box
from rich.console import Console
from rich.table import Table

# Assuming utils are in the python path or PYTHONPATH is set correctly
# If running as a script, ensure the parent directory of 'utils' is in sys.path
try:
    from pyplayground.utils.k8s_utils import get_k8s_client, load_kube_config_auto
    from pyplayground.utils.logging_utils import get_logger, setup_logging
except ImportError:
    # Basic fallback for path issues
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
    from pyplayground.utils.k8s_utils import get_k8s_client, load_kube_config_auto
    from pyplayground.utils.logging_utils import get_logger, setup_logging


# --- Constants ---
PORTWORX_PROVISIONER = "pxd.portworx.com"
PORTWORX_POD_LABEL_SELECTOR = "name=portworx,storage=true"
DEFAULT_PORTWORX_NAMESPACE = "kube-system"  # Default namespace for Portworx pods

# Initialize Rich Console and Logger
console = Console()
# Logger will be configured in main()


# --- Helper Functions ---


# NEW: Helper to format bytes into human-readable sizes
def format_bytes(size_bytes: Optional[Union[int, str]]) -> str:
    """Converts bytes to a human-readable string (KiB, MiB, GiB, TiB)."""
    if size_bytes is None:
        return "N/A"
    try:
        size_bytes = int(size_bytes)
    except (ValueError, TypeError):
        return str(size_bytes)  # Return original if not convertible to int

    if size_bytes == 0:
        return "0 B"
    size_name = ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB")
    i = 0
    while size_bytes >= 1024 and i < len(size_name) - 1:
        size_bytes /= 1024.0
        i += 1
    s = f"{size_bytes:.2f}"
    # Remove unnecessary .00
    s = s.rstrip("0").rstrip(".") if "." in s else s
    return f"{s} {size_name[i]}"


def find_portworx_pod(v1_client: client.CoreV1Api, namespace: str) -> Optional[Tuple[str, str]]:
    """Finds the first running Portworx pod based on labels in the specified namespace.

    Args:
        v1_client: Initialized CoreV1Api client.
        namespace: The namespace to search for the Portworx pod.

    Returns:
        A tuple (pod_name, container_name) if found and running, None otherwise.
    """
    logger = get_logger(__name__)
    logger.info(f"Searching for Portworx pod with labels '{PORTWORX_POD_LABEL_SELECTOR}' in namespace '{namespace}'...")
    try:
        pods = v1_client.list_namespaced_pod(namespace=namespace, label_selector=PORTWORX_POD_LABEL_SELECTOR)
        if not pods.items:
            logger.warning(f"No pods found with labels '{PORTWORX_POD_LABEL_SELECTOR}' in namespace '{namespace}'.")
            return None

        for pod in pods.items:
            pod_name = pod.metadata.name
            if pod.status.phase == "Running":
                # Assuming the main container is the one we need, usually named 'portworx'
                # If multiple containers exist, might need refinement
                if pod.spec.containers:
                    container_name = pod.spec.containers[0].name  # Assume first container
                    logger.info(f"Found running Portworx pod: '{pod_name}', container: '{container_name}'")
                    return pod_name, container_name
                else:
                    logger.warning(f"Portworx pod '{pod_name}' found but has no containers defined.")

        logger.warning(f"No *running* Portworx pods found in namespace '{namespace}'.")
        return None
    except ApiException as e:
        logger.error(
            f"API error finding Portworx pod in namespace '{namespace}': {e.status} - {e.reason}",
            exc_info=True,
        )
        return None
    except Exception as e:
        logger.exception(f"Unexpected error finding Portworx pod: {e}")
        return None


def get_portworx_storage_classes(storage_v1_client: client.StorageV1Api) -> List[str]:
    """Gets the names of StorageClasses provisioned by Portworx.

    Args:
        storage_v1_client: Initialized StorageV1Api client.

    Returns:
        A list of Portworx StorageClass names.
    """
    logger = get_logger(__name__)
    logger.debug("Fetching StorageClasses...")
    portworx_sc_names = []
    try:
        storage_classes = storage_v1_client.list_storage_class()
        for sc in storage_classes.items:
            if sc.provisioner == PORTWORX_PROVISIONER:
                portworx_sc_names.append(sc.metadata.name)
        logger.info(f"Found {len(portworx_sc_names)} Portworx StorageClasses: {', '.join(portworx_sc_names)}")
        return portworx_sc_names
    except ApiException as e:
        logger.error(f"API error listing StorageClasses: {e.status} - {e.reason}", exc_info=True)
        return []
    except Exception as e:
        logger.exception(f"Unexpected error listing StorageClasses: {e}")
        return []


def filter_portworx_pvcs(
    core_v1_client: client.CoreV1Api,
    portworx_sc_names: List[str],
    skip_prefixes: List[str],
) -> List[client.V1PersistentVolumeClaim]:
    """Fetches all PVCs and filters those using Portworx StorageClasses,excluding those in namespaces matching skip_prefixes.

    Args:
        core_v1_client: Initialized CoreV1Api client.
        portworx_sc_names: List of Portworx StorageClass names.
        skip_prefixes: List of namespace prefixes to exclude.

    Returns:
        A list of V1PersistentVolumeClaim objects using Portworx storage in allowed namespaces.
    """
    logger = get_logger(__name__)
    logger.debug("Fetching all PVCs across all namespaces...")
    portworx_pvcs = []
    skipped_count = 0
    try:
        all_pvcs = core_v1_client.list_persistent_volume_claim_for_all_namespaces()
        for pvc in all_pvcs.items:
            namespace = pvc.metadata.namespace
            pvc_name = pvc.metadata.name

            # Check if namespace should be skipped
            if any(namespace.startswith(prefix) for prefix in skip_prefixes):
                logger.debug(f"Skipping PVC '{namespace}/{pvc_name}' due to namespace prefix.")
                skipped_count += 1
                continue  # Skip this PVC

            sc_name = pvc.spec.storage_class_name
            # Check if the PVC's storage class is one of the Portworx SCs
            if sc_name in portworx_sc_names:
                portworx_pvcs.append(pvc)
            # Also consider PVCs that don't specify SC but are bound to a Portworx PV (less common)
            # This requires cross-referencing with PVs later if needed. For now, rely on SC name.
        log_msg = f"Found {len(portworx_pvcs)} PVCs using Portworx StorageClasses."
        if skipped_count > 0:
            log_msg += f" Skipped {skipped_count} PVCs due to namespace prefixes."
        logger.info(log_msg)
        return portworx_pvcs
    except ApiException as e:
        logger.error(f"API error listing PVCs: {e.status} - {e.reason}", exc_info=True)
        return []
    except Exception as e:
        logger.exception(f"Unexpected error listing PVCs: {e}")
        return []


def filter_portworx_pvs(  # noqa: C901
    core_v1_client: client.CoreV1Api,
    portworx_sc_names: List[str],
    skip_prefixes: List[str],
) -> List[client.V1PersistentVolume]:
    """Fetches all PVs and filters those using Portworx StorageClasses,excluding those bound to PVCs in namespaces matching skip_prefixes.

    Args:
        core_v1_client: Initialized CoreV1Api client.
        portworx_sc_names: List of Portworx StorageClass names.
        skip_prefixes: List of namespace prefixes to exclude claims from.

    Returns:
        A list of V1PersistentVolume objects using Portworx storage and not bound to skipped namespaces.
    """
    logger = get_logger(__name__)
    logger.debug("Fetching all PVs...")
    portworx_pvs = []
    skipped_count = 0
    try:
        all_pvs = core_v1_client.list_persistent_volume()
        for pv in all_pvs.items:
            is_portworx_pv = False
            pv_name = pv.metadata.name

            # Check if it's a Portworx PV based on SC or CSI driver
            if pv.spec.storage_class_name in portworx_sc_names or (pv.spec.csi and pv.spec.csi.driver == PORTWORX_PROVISIONER):
                is_portworx_pv = True
                # logger.debug(f"Identified PV {pv.metadata.name} via CSI driver.") # Debug logged later if added

            if is_portworx_pv:
                # Now check if it's bound to a skipped namespace
                claim_namespace = None
                if pv.spec.claim_ref:
                    claim_namespace = pv.spec.claim_ref.namespace
                    if any(claim_namespace.startswith(prefix) for prefix in skip_prefixes):
                        logger.debug(f"Skipping PV '{pv_name}' because it is bound to skipped namespace '{claim_namespace}'.")
                        skipped_count += 1
                        continue  # Skip this PV

                # If it is a Portworx PV and not bound to a skipped namespace, add it
                if pv not in portworx_pvs:  # Avoid potential duplicates if matched by both SC and CSI
                    portworx_pvs.append(pv)
                    if claim_namespace:  # Log reason if CSI driver was the match
                        if pv.spec.storage_class_name not in portworx_sc_names and pv.spec.csi:
                            logger.debug(f"Identified PV {pv_name} via CSI driver, adding.")
                    elif pv.spec.csi:  # Also log if CSI driver match and unbound
                        logger.debug(f"Identified unbound PV {pv_name} via CSI driver, adding.")

        log_msg = f"Found {len(portworx_pvs)} PVs associated with Portworx StorageClasses and allowed namespaces."
        if skipped_count > 0:
            log_msg += f" Skipped {skipped_count} PVs bound to excluded namespaces."
        logger.info(log_msg)
        return portworx_pvs
    except ApiException as e:
        logger.error(f"API error listing PVs: {e.status} - {e.reason}", exc_info=True)
        return []
    except Exception as e:
        logger.exception(f"Unexpected error listing PVs: {e}")
        return []


# Add helper function to prepare command string with env vars
def _prepare_execution_command(env_var_list: List[str], base_command: str) -> Tuple[str, Dict[str, str]]:
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
    logger = get_logger(__name__)
    env_vars = {}
    for var in env_var_list:
        if "=" not in var:
            error_msg = f"Invalid environment variable format: '{var}'. Use VAR=VALUE."
            logger.error(error_msg)
            raise ValueError(error_msg)
        key, value = var.split("=", 1)
        # Basic quoting for safety, might need more robust shell escaping for complex values
        # Using double quotes assuming standard sh behavior
        env_vars[key] = value

    if env_vars:
        # Construct the export commands
        env_exports = " && ".join([f'export {key}="{value}"' for key, value in env_vars.items()])
        full_command_str = f"{env_exports} && {base_command}"
    else:
        full_command_str = base_command

    logger.debug(f"Prepared full command (env vars included): {full_command_str}")
    return full_command_str, env_vars


# NEW: Helper function to run command and get output/error/code
def _run_command_in_pod(
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

    Raises:
        ApiException: If the Kubernetes API call fails during connection/streaming.
        Exception: For other unexpected errors during streaming.
    """
    stdout_data = ""
    stderr_data = ""
    exit_code = -1
    resp = None  # Initialize resp
    try:
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
            _preload_content=False,  # Important for reading streams
        )

        while resp.is_open():
            resp.update(timeout=1)
            if resp.peek_stdout():
                stdout_data += resp.read_stdout()
            if resp.peek_stderr():
                stderr_data += resp.read_stderr()

    finally:
        if resp:
            resp.close()
            exit_code = resp.returncode if resp.returncode is not None else -1  # Ensure exit_code has a value

    return exit_code, stdout_data, stderr_data


# Refactored to reduce complexity
def execute_pxctl_inspect(  # noqa: C901
    v1_client: client.CoreV1Api,
    px_namespace: str,
    px_pod_name: str,
    px_container_name: str,
    pv_name: str,
    env_vars: List[str],
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """Executes 'pxctl volume inspect -j <pv_name>' in the Portworx pod with specified environment variables.

    Args:
        v1_client: Initialized CoreV1Api client.
        px_namespace: Namespace of the Portworx pod.
        px_pod_name: Name of the Portworx pod.
        px_container_name: Name of the container within the Portworx pod.
        pv_name: The name of the PV (volume) to inspect.
        env_vars: List of environment variables ("VAR=VALUE") to set before execution.

    Returns:
        A tuple containing:
            - Parsed JSON output (dict) if successful and valid JSON, None otherwise.
            - Raw stdout string if JSON parsing fails or command returns error, None otherwise.
            - Stderr string if the command produced stderr output, None otherwise.
    """
    logger = get_logger(__name__)
    base_command = f"pxctl volume inspect {pv_name} -j"

    # Prepare the full command including environment variable exports
    try:
        full_command_str, parsed_env_vars = _prepare_execution_command(env_vars, base_command)
        if parsed_env_vars:
            logger.debug(f"Executing with environment variables: {parsed_env_vars}")  # Corrected indentation
    except ValueError as e:
        # Propagate error if env var format is invalid
        logger.error(f"Cannot execute command due to invalid environment variable: {e}")  # Corrected indentation
        return None, None, f"Invalid Environment Variable: {e}"  # Corrected indentation

    command_to_run = ["/bin/sh", "-c", full_command_str]
    logger.debug(f"Executing in pod '{px_pod_name}/{px_container_name}': {' '.join(command_to_run)}")

    try:
        # Use the helper to run the command
        exit_code, stdout_data, stderr_data = _run_command_in_pod(v1_client, px_namespace, px_pod_name, px_container_name, command_to_run)

        logger.debug(f"pxctl command for PV '{pv_name}' finished with exit code {exit_code}.")
        # Log truncated output
        if stdout_data:
            logger.debug(f"pxctl stdout for PV '{pv_name}':{stdout_data[:500]}...")
        if stderr_data:
            logger.warning(f"pxctl stderr for PV '{pv_name}':{stderr_data[:500]}...")

        # Process results
        if exit_code == 0 and stdout_data:
            try:
                parsed_json = json.loads(stdout_data)
                if isinstance(parsed_json, list) and len(parsed_json) == 1:
                    return parsed_json[0], None, None  # Return the dict inside the list
                elif isinstance(parsed_json, dict):
                    return parsed_json, None, None
                else:
                    logger.warning(f"pxctl output for PV '{pv_name}' was JSON but not the expected format (list of one dict or single dict): {type(parsed_json)}")
                    return None, stdout_data, stderr_data
            except json.JSONDecodeError as json_err:
                logger.error(
                    f"Failed to parse pxctl JSON output for PV '{pv_name}': {json_err}",
                    exc_info=True,
                )
                return None, stdout_data, stderr_data
        else:
            logger.warning(f"pxctl command for PV '{pv_name}' failed (code: {exit_code}) or produced no stdout.")
            return None, stdout_data, stderr_data

    except ApiException as e:
        # Check specifically for the connection timeout error
        if e.status == 0 and "[Errno 60] Operation timed out" in str(e.reason):
            logger.warning(f"Connection timed out while trying to execute command for PV '{pv_name}'. Skipping.")
            return None, None, "Connection Timeout"
        else:
            # Handle other API errors
            logger.error(
                f"API error executing command for PV '{pv_name}': {e.status} - {e.reason}",
                exc_info=True,
            )
            # Return the generic error reason to be stored
            return None, None, f"Kubernetes API Error: {e.reason}"
    except Exception as e:
        logger.exception(f"Unexpected error executing pxctl command for PV '{pv_name}': {e}")
        return None, None, f"Unexpected Error: {e}"


def combine_data(pvs: List[client.V1PersistentVolume], pvcs: List[client.V1PersistentVolumeClaim]) -> Dict[str, Dict[str, Any]]:
    """Combines PV and PVC information into a dictionary keyed by PV name.

    Extracts only the necessary fields.
    """
    logger = get_logger(__name__)
    combined_info = {}
    pvc_map = {(pvc.metadata.namespace, pvc.metadata.name): pvc for pvc in pvcs}  # Map for quick PVC lookup by claimRef

    for pv in pvs:
        pv_name = pv.metadata.name
        pv_info = {
            "pv_name": pv_name,
            # Keep capacity raw here for potential filtering later, format on output
            "capacity_bytes": pv.spec.capacity.get("storage") if pv.spec.capacity else None,
            "pvc_name": None,
            "pvc_namespace": None,
            # Add other potentially needed raw fields if required for filtering/logic
            # e.g., "pv_uid": pv.metadata.uid,
        }

        # Find associated PVC
        if pv.spec.claim_ref:
            claim_ns = pv.spec.claim_ref.namespace
            claim_name = pv.spec.claim_ref.name
            pvc = pvc_map.get((claim_ns, claim_name))
            if pvc:
                pv_info.update(
                    {
                        "pvc_name": pvc.metadata.name,
                        "pvc_namespace": pvc.metadata.namespace,
                    }
                )
            else:
                logger.warning(f"PV '{pv_name}' references PVC '{claim_ns}/{claim_name}', but PVC not found in provided list.")
        else:
            logger.debug(f"PV '{pv_name}' has no claimRef.")

        combined_info[pv_name] = pv_info

    # logger.info(f"Combined data for {len(combined_info)} PVs.") # Logging moved to caller
    return combined_info


def output_results_json(data: List[Dict[str, Any]], filename: Optional[str]):
    """Outputs the filtered combined data to a JSON file or stdout."""
    logger = get_logger(__name__)

    # Filter data to include only specified fields
    filtered_data = []
    for item in data:
        px_details = item.get("pxctl_details") or {}
        spec_details = px_details.get("spec") or {}

        filtered_item = {
            "pv_name": item.get("pv_name"),
            "pvc_name": item.get("pvc_name"),
            "namespace": item.get("pvc_namespace"),
            "pv_size": format_bytes(item.get("capacity_bytes")),
            "pv_used": format_bytes(px_details.get("usage")),
            "ha_level": spec_details.get("ha_level"),
        }
        filtered_data.append(filtered_item)

    output_json = json.dumps(filtered_data, indent=2, ensure_ascii=False)

    if filename:
        # Determine the full path based on whether filename is absolute
        if os.path.isabs(filename):
            full_path = filename
        else:
            # Construct path relative to current working directory
            current_dir = os.getcwd()
            full_path = os.path.join(current_dir, "tmp", filename)

        try:
            # Ensure output directory exists using the full path
            output_dir = os.path.dirname(full_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(output_json)
            logger.info(f"Successfully wrote filtered JSON output to '{full_path}'")
            console.print(f"[green]Filtered JSON output saved to:[/green] {full_path}")
        except IOError as e:
            logger.error(f"Failed to write JSON output to '{full_path}': {e}", exc_info=True)
            console.print(f"[bold red]Error writing JSON file '{full_path}': {e}[/bold red]")
            # Fallback to stdout?
            print("--- Filtered JSON Output (Fallback to STDOUT) ---")
            print(output_json)
            print("--- End Filtered JSON Output ---")
        except Exception as e:
            logger.exception(f"Unexpected error writing JSON file '{full_path}': {e}")
            console.print(f"[bold red]Unexpected error writing JSON file '{full_path}': {e}[/bold red]")
            # Fallback to stdout?
            print("--- Filtered JSON Output (Fallback to STDOUT) ---")
            print(output_json)
            print("--- End Filtered JSON Output ---")
    else:
        # Print filtered JSON directly to stdout if no filename provided
        print("--- Filtered JSON Output ---")
        print(output_json)
        print("--- End Filtered JSON Output ---")


def output_results_console(data: List[Dict[str, Any]]):
    """Outputs a brief summary table with specific fields to the console."""
    if not data:
        console.print("[yellow]No Portworx volumes found or processed.[/yellow]")
        return

    table = Table(
        title="Portworx Volume Summary",
        box=box.ASCII,
        show_lines=True,
        title_style="bold blue",
    )
    # Update columns based on requirements
    table.add_column("PV Name", style="cyan", no_wrap=True)
    table.add_column("Namespace", style="magenta")
    table.add_column("PVC Name", style="green")
    table.add_column("PV Size", style="yellow")  # Renamed
    table.add_column("PV Used", style="white")  # Added
    table.add_column("HA Level", style="white")  # Kept

    for item in data:
        px_details = item.get("pxctl_details") or {}
        spec_details = px_details.get("spec") or {}

        # Safely extract required fields
        pv_name = item.get("pv_name", "N/A")
        namespace = item.get("pvc_namespace", "[dim]N/A[/dim]")
        pvc_name = item.get("pvc_name", "[dim]N/A[/dim]")
        capacity_str = format_bytes(item.get("capacity_bytes"))  # Use helper
        usage_str = format_bytes(px_details.get("usage"))  # Use helper, handle missing
        ha_level = str(spec_details.get("ha_level", "N/A"))  # Handle missing

        table.add_row(
            pv_name,
            namespace,
            pvc_name,
            capacity_str,
            usage_str,
            ha_level,
        )

    console.print(table)


# NEW: Function to output results as CSV
def output_results_csv(data: List[Dict[str, Any]], filename: str):
    """Outputs the filtered combined data to a CSV file.

    Args:
        data: The list of filtered combined volume information dictionaries.
        filename: The path to the output CSV file.
    """
    import csv  # Import csv module locally

    logger = get_logger(__name__)

    # Define the exact order and names for CSV columns
    fieldnames = ["pv_name", "namespace", "pvc_name", "pv_size", "pv_used", "ha_level"]

    # Filter data to include only specified fields, ensuring order
    filtered_data_for_csv = []
    for item in data:
        px_details = item.get("pxctl_details") or {}
        spec_details = px_details.get("spec") or {}

        filtered_item = {
            "pv_name": item.get("pv_name", "N/A"),
            "namespace": item.get("pvc_namespace", "N/A"),
            "pvc_name": item.get("pvc_name", "N/A"),
            "pv_size": format_bytes(item.get("capacity_bytes")),
            "pv_used": format_bytes(px_details.get("usage")),
            "ha_level": spec_details.get("ha_level", "N/A"),
        }
        # Ensure only defined fieldnames are included (optional, good practice)
        filtered_data_for_csv.append({k: filtered_item.get(k, "N/A") for k in fieldnames})

    # Determine the full path based on whether filename is absolute
    if os.path.isabs(filename):
        full_path = filename
    else:
        current_dir = os.getcwd()
        full_path = os.path.join(current_dir, "tmp", filename)

    try:
        # Ensure output directory exists
        output_dir = os.path.dirname(full_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        with open(full_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(filtered_data_for_csv)

        logger.info(f"Successfully wrote filtered CSV output to '{full_path}'")
        console.print(f"[green]Filtered CSV output saved to:[/green] {full_path}")

    except IOError as e:
        logger.error(f"Failed to write CSV output to '{full_path}': {e}", exc_info=True)
        console.print(f"[bold red]Error writing CSV file '{full_path}': {e}[/bold red]")
    except Exception as e:
        logger.exception(f"Unexpected error writing CSV file '{full_path}': {e}")
        console.print(f"[bold red]Unexpected error writing CSV file '{full_path}': {e}[/bold red]")


# NEW: Helper to check Portworx security and get PXCTL_AUTH_TOKEN
def get_pxctl_auth_env(core_v1: client.CoreV1Api, px_namespace: str) -> Optional[str]:
    """Return PXCTL_AUTH_TOKEN env var if Portworx security is enabled in StorageCluster."""
    logger = get_logger(__name__)
    try:
        co_api = get_k8s_client("CustomObjectsApi")
        stc = co_api.list_namespaced_custom_object(
            group="core.libopenstorage.org",
            version="v1",
            namespace=px_namespace,
            plural="storageclusters",
        )
        if stc["items"]:
            sec_enabled = stc["items"][0].get("spec", {}).get("security", {}).get("enabled", False)
            if sec_enabled:
                # Use the provided core_v1 client for secret access (already from get_k8s_client)
                secret = core_v1.read_namespaced_secret("px-admin-token", px_namespace)
                token_b64 = secret.data.get("auth-token")
                if token_b64:
                    token = base64.b64decode(token_b64).decode("utf-8")
                    logger.info("Portworx security enabled; using PXCTL_AUTH_TOKEN from px-admin-token secret.")
                    return f"PXCTL_AUTH_TOKEN={token}"
                else:
                    logger.warning("px-admin-token secret found but 'auth-token' key missing.")
            else:
                logger.info("Portworx security is not enabled in StorageCluster.")
        else:
            logger.warning(f"No StorageCluster found in namespace '{px_namespace}'.")
    except Exception as e:
        logger.warning(f"Could not determine PXCTL_AUTH_TOKEN: {e}")
    return None


# NEW: Helper function containing the core logic extracted from main
def _gather_volume_details(
    core_v1: client.CoreV1Api,
    storage_v1: client.StorageV1Api,
    px_namespace: str,
    env_vars: List[str],
    skip_prefixes: List[str],
) -> List[Dict[str, Any]]:
    """Gathers Portworx volume details by querying K8s and executing pxctl.

    Args:
        core_v1: Initialized CoreV1Api client.
        storage_v1: Initialized StorageV1Api client.
        px_namespace: Namespace where Portworx pods run.
        env_vars: List of environment variables for pxctl command.
        skip_prefixes: List of namespace prefixes to exclude.

    Returns:
        A list of dictionaries, each containing combined K8s and pxctl info for a PV.

    Raises:
        RuntimeError: If the Portworx pod cannot be found or essential steps fail.
        SystemExit: If no Portworx SCs or PVs are found (graceful exit).
    """
    logger = get_logger(__name__)

    # 1. Find Portworx Pod
    px_pod_info = find_portworx_pod(core_v1, px_namespace)
    if not px_pod_info:
        msg = f"Could not find a running Portworx pod in namespace '{px_namespace}'."
        logger.error(msg)
        raise RuntimeError(msg)
    px_pod_name, px_container_name = px_pod_info

    # 2. Get Portworx Storage Classes
    px_sc_names = get_portworx_storage_classes(storage_v1)
    if not px_sc_names:
        logger.warning(f"No StorageClasses found with provisioner '{PORTWORX_PROVISIONER}'. Cannot identify Portworx volumes.")
        console.print(f"[yellow]Warning: No StorageClasses found with provisioner '{PORTWORX_PROVISIONER}'. Cannot identify Portworx volumes.[/yellow]")
        return []

    # 3. Filter Portworx PVs and PVCs, passing skip_prefixes
    portworx_pvs = filter_portworx_pvs(core_v1, px_sc_names, skip_prefixes)
    portworx_pvcs = filter_portworx_pvcs(core_v1, px_sc_names, skip_prefixes)

    if not portworx_pvs:
        logger.warning("No Portworx PVs found matching the criteria (StorageClass, allowed namespaces).")
        console.print("[yellow]No Portworx PVs found matching the criteria (StorageClass, allowed namespaces).[/yellow]")
        return []

    # 4. Combine PV/PVC Data (uses the already filtered lists)
    combined_k8s_data = combine_data(portworx_pvs, portworx_pvcs)
    total_pvs = len(combined_k8s_data)
    logger.info(f"Combined Kubernetes data for {total_pvs} Portworx PVs to process.")

    # --- NEW: Add PXCTL_AUTH_TOKEN if security is enabled ---
    pxctl_auth_env = get_pxctl_auth_env(core_v1, px_namespace)
    effective_env_vars = list(env_vars)  # Copy to avoid mutating input
    if pxctl_auth_env:
        effective_env_vars.append(pxctl_auth_env)

    # 5. Execute pxctl and enrich data
    final_results = []
    processed_pv_count = 0
    for pv_name, pv_data in combined_k8s_data.items():
        # Log progress at INFO level before processing each PV
        processed_pv_count += 1  # Increment counter first
        logger.info(f"Processing PV {processed_pv_count}/{total_pvs}: {pv_name}")

        pxctl_json, pxctl_raw, pxctl_err = execute_pxctl_inspect(core_v1, px_namespace, px_pod_name, px_container_name, pv_name, effective_env_vars)

        # Add pxctl results to the combined data
        pv_data["pxctl_details"] = pxctl_json  # Will be None if error or not JSON
        pv_data["pxctl_raw_output"] = pxctl_raw if pxctl_raw else None
        pv_data["pxctl_stderr"] = pxctl_err if pxctl_err else None
        pv_data["pxctl_error"] = pxctl_json is None and (pxctl_raw is not None or pxctl_err is not None)

        final_results.append(pv_data)

    # logger.info(f"Finished processing {processed_pv_count} Portworx PVs.") # Can keep or remove this line as the loop provides counts
    logger.info(f"Finished processing all {total_pvs} identified Portworx PVs.")  # More explicit final message
    return final_results


def setup_logging_from_cli(debug: bool, script_path: str) -> logging.Logger:
    """Set up logging based on CLI debug flag and script path.

    Returns a logger instance for the current module.
    """
    script_base_name = os.path.basename(script_path).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    return get_logger(__name__)


def load_kubeconfig_or_exit(kubeconfig: Optional[str], console: Console) -> None:
    """Load Kubernetes configuration or exit with error if it fails."""
    if not load_kube_config_auto(config_file=kubeconfig):
        console.print("[bold red]Error: Failed to load Kubernetes configuration.[/bold red]")
        sys.exit(1)


def get_k8s_clients() -> tuple:
    """Return CoreV1Api and StorageV1Api clients, or exit with error if initialization fails."""
    try:
        core_v1 = get_k8s_client("CoreV1Api")
        storage_v1 = get_k8s_client("StorageV1Api")
        return core_v1, storage_v1
    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Failed to initialize Kubernetes API clients: {e}", exc_info=True)
        console = Console()
        console.print(f"[bold red]Error initializing Kubernetes clients: {e}[/bold red]")
        sys.exit(1)


def gather_and_enrich_volume_details(core_v1, storage_v1, px_namespace, env_var, skip_namespace_prefix):
    """Gather and enrich Portworx volume details using K8s and pxctl."""
    return _gather_volume_details(core_v1, storage_v1, px_namespace, list(env_var), list(skip_namespace_prefix))


def handle_main_errors(e, logger, console):
    """Centralized error handling for main."""
    import sys

    if isinstance(e, RuntimeError):
        console.print(f"[bold red]Error: {e}[/bold red]")
        sys.exit(1)
    elif isinstance(e, ApiException):
        logger.error(f"Kubernetes API Error: {e.status} {e.reason} - {getattr(e, 'body', '')}", exc_info=True)
        console.print(f"[bold red]Kubernetes API Error: {e.reason}[/bold red]")
        sys.exit(1)
    elif isinstance(e, SystemExit):
        logger.info(f"Script exiting gracefully (code: {e.code}).")
        sys.exit(e.code)
    elif isinstance(e, KeyboardInterrupt):
        logger.warning("Script execution interrupted by user (Ctrl+C).")
        console.print("[yellow]\nExecution interrupted by user.[/yellow]")
        sys.exit(130)
    else:
        logger.exception(f"An unexpected error occurred: {e}")
        console.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
        sys.exit(1)


def process_clusters(
    kubeconfig_files,
    output_format,
    px_namespace,
    env_var,
    skip_namespace_prefix,
    logger,
    console,
):
    """Process each cluster, output per-cluster results, and log errors."""
    failed_clusters = []
    for kubeconfig_path in kubeconfig_files:
        cluster_name = os.path.splitext(os.path.basename(kubeconfig_path))[0]
        try:
            logger.info(f"Processing cluster: {cluster_name} (kubeconfig: {kubeconfig_path})")
            console.print(f"[bold blue]Processing cluster: {cluster_name}[/bold blue]")
            load_kubeconfig_or_exit(kubeconfig_path, console)
            core_v1, storage_v1 = get_k8s_clients()
            final_results = gather_and_enrich_volume_details(core_v1, storage_v1, px_namespace, env_var, skip_namespace_prefix)
            if not final_results:
                logger.info(f"No Portworx PVs or PVCs found for cluster: {cluster_name}. Skipping output.")
                console.print(f"[yellow]No Portworx PVs or PVCs found for cluster: {cluster_name}.[/yellow]")
                continue  # Move to next cluster
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_base = f"{cluster_name}_pxvoldetails_{timestamp}"
            if output_format == "json":
                output_filename = f"{output_base}.json"
                logger.info(f"JSON output file for cluster {cluster_name}: {output_filename}")
                output_results_json(final_results, output_filename)
            elif output_format == "csv":
                output_filename = f"{output_base}.csv"
                logger.info(f"CSV output file for cluster {cluster_name}: {output_filename}")
                output_results_csv(final_results, output_filename)
            else:
                console.print(f"[bold green]Results for cluster: {cluster_name}[/bold green]")
                output_results_console(final_results)
            logger.info(f"Finished processing cluster: {cluster_name}")
        except Exception as e:
            logger.error(
                f"Failed to process cluster '{cluster_name}' ({kubeconfig_path}): {e}",
                exc_info=True,
            )
            console.print(f"[bold red]Error processing cluster '{cluster_name}': {e}[/bold red]")
            failed_clusters.append(cluster_name)
            continue
    if failed_clusters:
        logger.warning(f"The following clusters failed to process: {', '.join(failed_clusters)}")
        console.print(f"[yellow]The following clusters failed to process: {', '.join(failed_clusters)}[/yellow]")


# --- Main Execution ---


@click.command()
@click.option(
    "--kubeconfig",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the kubeconfig file. If not provided, uses default lookup.",
    envvar="KUBECONFIG",
)
@click.option(
    "--clusterlist",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a file containing a list of kubeconfig files (one per line).",
)
@click.option(
    "--px-namespace",
    default=DEFAULT_PORTWORX_NAMESPACE,
    show_default=True,
    help="Namespace where Portworx pods are running.",
)
@click.option(
    "-f",
    "--format",
    "output_format",  # Variable name for the option
    type=click.Choice(["console", "json", "csv"], case_sensitive=False),
    default="console",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--skip-namespace-prefix",
    multiple=True,
    help="Prefix of namespaces to skip (e.g., 'kube-'). Can be used multiple times.",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
@click.option(
    "--env-var",
    "-e",
    multiple=True,
    help="Environment variable to set in the format VAR=VALUE. Can be used multiple times.",
)
def main(
    kubeconfig: Optional[str],
    clusterlist: Optional[str],
    px_namespace: str,
    output_format: str,  # Added format
    debug: bool,
    env_var: Tuple[str],
    skip_namespace_prefix: Tuple[str],
):
    """Query Portworx PVs/PVCs, enrich with pxctl details, and output results. Supports single or multiple clusters."""
    logger = setup_logging_from_cli(debug, __file__)
    logger.info("Starting Portworx Volume Detail script...")
    kubeconfig_files = []
    if clusterlist:
        try:
            with open(clusterlist, "r") as f:
                kubeconfig_files = [line.strip() for line in f if line.strip()]
        except Exception as e:
            logger.error(f"Failed to read clusterlist file '{clusterlist}': {e}", exc_info=True)
            console.print(f"[bold red]Error reading clusterlist file: {e}[/bold red]")
            sys.exit(1)
    elif kubeconfig:
        kubeconfig_files = [kubeconfig]
    else:
        console.print("[bold red]Error: Must provide either --kubeconfig or --clusterlist.[/bold red]")
        sys.exit(1)
    process_clusters(
        kubeconfig_files,
        output_format,
        px_namespace,
        env_var,
        skip_namespace_prefix,
        logger,
        console,
    )


if __name__ == "__main__":
    main()
