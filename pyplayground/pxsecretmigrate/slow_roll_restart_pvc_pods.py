#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script to read the JSON export from k8s_px_pvc_data_exporter and restart pods.

This script performs a slow-roll restart of pods that are bound to the PVCs/PVs
listed in the export file. It will:

1. Load the exported data from the JSON file.
2. For each namespace present in the data, find all Pods that reference any of the PVCs
   listed for that namespace.
3. Delete those Pods one by one with configurable pauses between deletes and between
   namespaces to avoid overwhelming the cluster.

The script uses the Kubernetes client from k8s_utils and requires a kubeconfig
file or the default lookup logic.

JSON Structure Expected:
    {
        "namespace1": [
            {"pvc": "pvc-name-1", "pv": "pv-name-1", ...},
            {"pvc": "pvc-name-2", "pv": "pv-name-2", ...}
        ],
        "namespace2": [...]
    }
"""

import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Set

import click
from kubernetes import client
from kubernetes.client.exceptions import ApiException
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pyplayground.utils.k8s_utils import (
    get_cluster_name_from_config,
    get_k8s_client,
    load_kube_config_auto,
)
from pyplayground.utils.logging_utils import get_logger, setup_logging

# --- Globals ---
console = Console()
logger = get_logger(__name__)


# --- Helper Functions ---


def load_export_data(file_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """Load and validate JSON export data from file.

    Args:
        file_path: Path to the JSON file produced by k8s_px_pvc_data_exporter.

    Returns:
        Dictionary mapping namespace names to lists of PVC data entries.

    Raises:
        SystemExit: If the file cannot be read or parsed.
    """
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
        logger.info(f"Successfully loaded export data from {file_path}")
        return data
    except (IOError, json.JSONDecodeError) as e:
        logger.error(f"Failed to read JSON file '{file_path}': {e}", exc_info=True)
        console.print(f"[bold red]Failed to read JSON file: {e}[/bold red]")
        sys.exit(1)


def get_pods_using_pvcs(
    core_v1: client.CoreV1Api, namespace: str, pvc_names: Set[str]
) -> List[str]:
    """Find all pods in a namespace that mount any of the specified PVCs.

    Args:
        core_v1: Kubernetes CoreV1Api client.
        namespace: Namespace to search for pods.
        pvc_names: Set of PVC names to look for.

    Returns:
        List of pod names that mount any of the specified PVCs.
    """
    target_pods = []

    try:
        pod_list = core_v1.list_namespaced_pod(namespace).items
    except ApiException as e:
        logger.error(f"Error listing pods in namespace '{namespace}': {e}", exc_info=True)
        console.print(f"[bold red]Error listing pods in {namespace}: {e}[/bold red]")
        return []

    for pod in pod_list:
        try:
            volumes = pod.spec.volumes or []
        except AttributeError as e:
            logger.debug(f"Pod {pod.metadata.name} missing spec.volumes: {e}")
            continue

        for vol in volumes:
            if hasattr(vol, "persistent_volume_claim") and vol.persistent_volume_claim is not None:
                claim_name = vol.persistent_volume_claim.claim_name
                if claim_name in pvc_names:
                    target_pods.append(pod.metadata.name)
                    logger.debug(
                        f"Found pod {namespace}/{pod.metadata.name} using PVC {claim_name}"
                    )
                    break

    return target_pods


def get_pvcs_for_pod(core_v1: client.CoreV1Api, namespace: str, pod_name: str) -> Set[str]:
    """Get the set of PVC names that a specific pod is using.

    Args:
        core_v1: Kubernetes CoreV1Api client.
        namespace: Namespace containing the pod.
        pod_name: Name of the pod.

    Returns:
        Set of PVC names used by the pod.
    """
    pvcs = set()
    try:
        pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        volumes = pod.spec.volumes or []
        for vol in volumes:
            if hasattr(vol, "persistent_volume_claim") and vol.persistent_volume_claim is not None:
                pvcs.add(vol.persistent_volume_claim.claim_name)
        logger.debug(f"Pod {namespace}/{pod_name} uses PVCs: {pvcs}")
    except ApiException as e:
        logger.warning(f"Could not read pod {namespace}/{pod_name}: {e}")
    return pvcs


def get_pod_events(core_v1: client.CoreV1Api, namespace: str, pod_name: str) -> List[str]:
    """Get recent events for a pod.

    Args:
        core_v1: Kubernetes CoreV1Api client.
        namespace: Namespace containing the pod.
        pod_name: Name of the pod.

    Returns:
        List of event messages (most recent first).
    """
    try:
        events = core_v1.list_namespaced_event(
            namespace=namespace,
            field_selector=f"involvedObject.name={pod_name}",
        )
        # Sort by last timestamp (most recent first)
        sorted_events = sorted(
            events.items,
            key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp,
            reverse=True,
        )
        # Get last 10 events
        event_messages = []
        for event in sorted_events[:10]:
            timestamp = (
                event.last_timestamp or event.event_time or event.metadata.creation_timestamp
            )
            message = f"[{event.type}] {event.reason}: {event.message} (at {timestamp})"
            event_messages.append(message)
        return event_messages
    except ApiException as e:
        logger.warning(f"Could not retrieve events for pod {namespace}/{pod_name}: {e}")
        return []


def check_pod_health(
    core_v1: client.CoreV1Api, namespace: str, pod_name: str
) -> tuple[bool, Optional[str]]:
    """Check if a pod is healthy or has failed.

    Args:
        core_v1: Kubernetes CoreV1Api client.
        namespace: Namespace containing the pod.
        pod_name: Name of the pod.

    Returns:
        Tuple of (is_healthy, error_message).
        is_healthy is False if pod is in a failed state.
        error_message contains details if pod has failed.
    """
    try:
        pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)

        # Check pod phase
        if pod.status.phase == "Failed":
            return False, f"Pod is in Failed phase: {pod.status.reason or 'Unknown reason'}"

        # Check container statuses for failures
        if pod.status.container_statuses:
            for cs in pod.status.container_statuses:
                # Check for CrashLoopBackOff or other waiting states
                if cs.state and cs.state.waiting:
                    reason = cs.state.waiting.reason
                    message = cs.state.waiting.message
                    if reason in ["CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"]:
                        return False, f"Container {cs.name} in {reason}: {message or 'No details'}"

                # Check for terminated containers
                if cs.state and cs.state.terminated:
                    if cs.state.terminated.exit_code != 0:
                        return (
                            False,
                            f"Container {cs.name} terminated with exit code "
                            f"{cs.state.terminated.exit_code}: {cs.state.terminated.reason}",
                        )

        return True, None
    except ApiException as e:
        logger.debug(f"Error checking pod health {namespace}/{pod_name}: {e}")
        return True, None  # Assume healthy if we can't check


def check_new_pod_status(
    core_v1: client.CoreV1Api, namespace: str, pod_name: str
) -> tuple[bool, bool]:
    """Check if a new pod is ready or has failed.

    Args:
        core_v1: Kubernetes CoreV1Api client.
        namespace: Namespace containing the pod.
        pod_name: Name of the pod.

    Returns:
        Tuple of (is_ready, has_failed).
        is_ready: True if pod is fully ready.
        has_failed: True if pod has entered a failed state.
    """
    try:
        pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)

        # Check for pod health/failure first
        is_healthy, error_msg = check_pod_health(core_v1, namespace, pod_name)
        if not is_healthy:
            logger.error(f"Pod {namespace}/{pod_name} entered failed state: {error_msg}")
            console.print(f"[bold red]  ERROR: Pod {namespace}/{pod_name} failed![/bold red]")
            console.print(f"[red]  Reason: {error_msg}[/red]")

            # Get and display pod events
            events = get_pod_events(core_v1, namespace, pod_name)
            if events:
                console.print("[yellow]  Recent pod events:[/yellow]")
                for event in events[:5]:  # Show top 5 events
                    console.print(f"    {event}")
            else:
                console.print("[yellow]  No events found for this pod.[/yellow]")

            return False, True

        # Check if containers are ready
        if pod.status.container_statuses:
            pod_ready = all(cs.ready for cs in pod.status.container_statuses)
            if pod_ready:
                return True, False
            else:
                logger.debug(f"Pod {namespace}/{pod_name} not ready yet")
                return False, False
        else:
            logger.debug(f"Pod {namespace}/{pod_name} has no container statuses yet")
            return False, False

    except ApiException as e:
        logger.debug(f"Error checking pod {namespace}/{pod_name}: {e}")
        return False, False


def wait_for_new_pods_ready(
    core_v1: client.CoreV1Api,
    namespace: str,
    pvc_names: Set[str],
    old_pod_names: Set[str],
    timeout: int = 300,
) -> bool:
    """Wait for new pods using the specified PVCs to be ready.

    After deleting a pod, Kubernetes creates a new pod with a different name.
    This function waits for new pods (not in old_pod_names) that use the
    specified PVCs to appear and become ready.

    Args:
        core_v1: Kubernetes CoreV1Api client.
        namespace: Namespace to search in.
        pvc_names: Set of PVC names to monitor.
        old_pod_names: Set of old pod names to exclude.
        timeout: Maximum seconds to wait.

    Returns:
        True if new pods are ready, False if timeout reached or pod failed.
    """
    import time

    start_time = time.time()
    check_interval = 5  # Check every 5 seconds

    logger.debug(
        f"Waiting for new pods in {namespace} using PVCs {pvc_names} (excluding {old_pod_names})"
    )

    while time.time() - start_time < timeout:
        current_pods = get_pods_using_pvcs(core_v1, namespace, pvc_names)
        new_pods = [pod for pod in current_pods if pod not in old_pod_names]

        if new_pods:
            logger.debug(f"Found new pod(s): {new_pods}")
            all_ready = True
            for pod_name in new_pods:
                is_ready, has_failed = check_new_pod_status(core_v1, namespace, pod_name)

                if has_failed:
                    return False

                if not is_ready:
                    all_ready = False
                    break

            if all_ready:
                logger.info(
                    f"All new pods in {namespace} using PVCs {pvc_names} are ready: {new_pods}"
                )
                return True

        elapsed = int(time.time() - start_time)
        logger.debug(f"Waiting for new pods... ({elapsed}/{timeout}s elapsed)")
        time.sleep(check_interval)

    logger.warning(f"Timeout waiting for new pods in {namespace} using PVCs {pvc_names}")
    return False


def restart_pods_in_namespace(
    core_v1: client.CoreV1Api,
    namespace: str,
    pod_names: List[str],
    pod_pause: int,
    dry_run: bool,
    wait_ready: bool = False,
    wait_timeout: int = 300,
) -> int:
    """Restart pods in a namespace by deleting them one by one.

    Args:
        core_v1: Kubernetes CoreV1Api client.
        namespace: Namespace containing the pods.
        pod_names: List of pod names to restart.
        pod_pause: Seconds to pause between pod deletions.
        dry_run: If True, only display what would be deleted without actually deleting.
        wait_ready: If True, wait for pod to be ready after deletion before continuing.
        wait_timeout: Maximum seconds to wait for pod to be ready (default: 300).

    Returns:
        Number of pods successfully deleted (or would be deleted in dry-run mode).
    """
    success_count = 0

    for pod_name in pod_names:
        if dry_run:
            console.print(f"[cyan]  Would delete pod {namespace}/{pod_name}[/cyan]")
            logger.info(f"DRY RUN: Would delete pod {namespace}/{pod_name}")
            success_count += 1
        else:
            # Get PVCs used by this pod before deletion
            pod_pvcs = get_pvcs_for_pod(core_v1, namespace, pod_name)

            # Get current list of all pods using these PVCs (before deletion)
            current_pods_set = set(get_pods_using_pvcs(core_v1, namespace, pod_pvcs))

            try:
                core_v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
                logger.info(f"Deleted pod {namespace}/{pod_name}")
                console.print(f"[green]  Deleted pod {namespace}/{pod_name}[/green]")
                success_count += 1

                # Wait for new pod to be ready if requested
                if wait_ready and pod_pvcs:
                    console.print(
                        f"[yellow]  Waiting for new pod in {namespace} to be ready "
                        f"(timeout: {wait_timeout}s)...[/yellow]"
                    )
                    with console.status(
                        f"[bold yellow]Waiting for new pod in {namespace}...[/bold yellow]"
                    ):
                        is_ready = wait_for_new_pods_ready(
                            core_v1=core_v1,
                            namespace=namespace,
                            pvc_names=pod_pvcs,
                            old_pod_names=current_pods_set,
                            timeout=wait_timeout,
                        )

                    if is_ready:
                        console.print(f"[green]  New pod in {namespace} is ready[/green]")
                        logger.info(f"New pod in {namespace} using PVCs {pod_pvcs} is ready")
                    else:
                        console.print(
                            f"[bold yellow]  Warning: New pod in {namespace} "
                            f"did not become ready within {wait_timeout}s[/bold yellow]"
                        )
                        logger.warning(
                            f"New pod in {namespace} using PVCs {pod_pvcs} did not become ready within timeout"
                        )

                if pod_pause > 0:
                    console.print(f"[dim]  Pausing {pod_pause}s before next pod...[/dim]")
                    time.sleep(pod_pause)

            except ApiException as e:
                logger.error(f"Failed to delete pod {namespace}/{pod_name}: {e}", exc_info=True)
                console.print(
                    f"[bold red]  Failed to delete {namespace}/{pod_name}: {e}[/bold red]"
                )

    return success_count


def process_namespaces(
    core_v1: client.CoreV1Api,
    data: Dict[str, List[Dict[str, Any]]],
    namespace_pause: int,
    pod_pause: int,
    dry_run: bool,
    wait_ready: bool = False,
    wait_timeout: int = 300,
) -> Dict[str, Dict[str, Any]]:
    """Process all namespaces and restart pods that use the annotated PVCs.

    Args:
        core_v1: Kubernetes CoreV1Api client.
        data: Export data mapping namespace to PVC entries.
        namespace_pause: Seconds to pause before processing each namespace.
        pod_pause: Seconds to pause between pod deletions within a namespace.
        dry_run: If True, only display what would be done without actually doing it.
        wait_ready: If True, wait for each pod to be ready after deletion.
        wait_timeout: Maximum seconds to wait for each pod to be ready.

    Returns:
        Dictionary with namespace names as keys and results as values.
        Results contain: pod_count, success_count, status.
    """
    results = {}

    for ns, pvc_entries in data.items():
        if not pvc_entries:
            logger.debug(f"Namespace '{ns}' has no PVC entries, skipping.")
            continue

        # Extract PVC names from the export data
        pvc_names = {entry.get("pvc") for entry in pvc_entries if entry.get("pvc")}
        if not pvc_names:
            logger.debug(f"Namespace '{ns}' has no valid PVC names, skipping.")
            continue

        logger.info(f"Processing namespace: {ns} (found {len(pvc_names)} PVC(s))")

        # Pause before processing this namespace
        if namespace_pause > 0:
            console.print(
                f"\n[bold yellow]Processing namespace: {ns}[/bold yellow] "
                f"[dim](pausing {namespace_pause}s before start...)[/dim]"
            )
            time.sleep(namespace_pause)
        else:
            console.print(f"\n[bold yellow]Processing namespace: {ns}[/bold yellow]")

        # Find pods using the PVCs
        target_pods = get_pods_using_pvcs(core_v1, ns, pvc_names)

        if not target_pods:
            logger.info(f"No pods found using PVCs in namespace '{ns}'")
            console.print(f"[yellow]  No pods found using PVCs in {ns}[/yellow]")
            results[ns] = {"pod_count": 0, "success_count": 0, "status": "No Pods"}
            continue

        console.print(f"[bold magenta]  Found {len(target_pods)} pod(s) to restart:[/bold magenta]")
        for pod_name in target_pods:
            console.print(f"    - {pod_name}")

        # Restart the pods
        success_count = restart_pods_in_namespace(
            core_v1, ns, target_pods, pod_pause, dry_run, wait_ready, wait_timeout
        )

        status = "Dry-Run" if dry_run else "Completed"
        results[ns] = {
            "pod_count": len(target_pods),
            "success_count": success_count,
            "status": status,
        }

        logger.info(
            f"Namespace '{ns}' processing complete: {success_count}/{len(target_pods)} pods processed"
        )

    return results


def display_summary(results: Dict[str, Dict[str, Any]], dry_run: bool) -> None:
    """Display a summary table of the pod restart operation.

    Args:
        results: Dictionary mapping namespace names to result dictionaries.
        dry_run: If True, indicates this was a dry-run operation.
    """
    if not results:
        console.print("\n[yellow]No namespaces were processed.[/yellow]")
        return

    # Create summary table
    table = Table(title="Pod Restart Summary", show_header=True, header_style="bold magenta")
    table.add_column("Namespace", style="cyan", no_wrap=True)
    table.add_column("Pod Count", justify="right", style="white")
    table.add_column("Success Count", justify="right", style="green")
    table.add_column("Status", style="yellow")

    total_pods = 0
    total_success = 0

    for ns, result in results.items():
        pod_count = result["pod_count"]
        success_count = result["success_count"]
        status = result["status"]

        total_pods += pod_count
        total_success += success_count

        table.add_row(ns, str(pod_count), str(success_count), status)

    # Add totals row
    table.add_row("", "", "", "", end_section=True)
    table.add_row(
        "[bold]TOTAL[/bold]",
        f"[bold]{total_pods}[/bold]",
        f"[bold]{total_success}[/bold]",
        "",
    )

    console.print("\n")
    console.print(table)

    if dry_run:
        console.print("\n[bold yellow]DRY RUN MODE - No pods were actually deleted[/bold yellow]")


# --- Main Command ---


@click.command(name="slow-roll-restart")
@click.option(
    "--input-file",
    type=click.Path(exists=True, dir_okay=False),
    required=True,
    help="Path to the JSON file produced by k8s_px_pvc_data_exporter.",
)
@click.option(
    "--kubeconfig",
    type=click.Path(exists=True, dir_okay=False),
    envvar="KUBECONFIG",
    help="Path to kubeconfig. If omitted, the default lookup is used.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Preview pods to be restarted without actually deleting them.",
)
@click.option(
    "--namespace-pause",
    default=5,
    type=int,
    show_default=True,
    help="Seconds to pause before processing each namespace.",
)
@click.option(
    "--pod-pause",
    default=2,
    type=int,
    show_default=True,
    help="Seconds to pause between pod deletions.",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable debug logging.",
)
@click.option(
    "--no-pause",
    is_flag=True,
    default=False,
    help="Skip all pauses (sets both namespace-pause and pod-pause to 0).",
)
@click.option(
    "--wait-ready",
    is_flag=True,
    default=False,
    help="Wait for each pod to be ready after deletion before proceeding to the next pod.",
)
@click.option(
    "--wait-timeout",
    default=300,
    type=int,
    show_default=True,
    help="Maximum seconds to wait for each pod to be ready (only used with --wait-ready).",
)
def main(
    input_file: str,
    kubeconfig: Optional[str],
    dry_run: bool,
    namespace_pause: int,
    pod_pause: int,
    debug: bool,
    no_pause: bool,
    wait_ready: bool,
    wait_timeout: int,
) -> None:
    """Restart pods that use PVCs defined in the input file.

    The script expects the JSON structure produced by k8s_px_pvc_data_exporter.py
    which maps namespace -> list of pvc dicts. Each dict contains a 'pvc' key with
    the name of the PVC.

    Pods are restarted by deleting them (Kubernetes will recreate them if they're
    managed by a controller like Deployment, StatefulSet, etc.).

    Use --no-pause to skip all pauses for faster execution (useful when you need
    to restart pods immediately without throttling).

    Use --wait-ready to ensure each pod is fully ready before proceeding to the
    next pod. This is safer but slower, as it waits for Kubernetes to recreate
    and ready each pod before moving on.
    """
    # Setup logging
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=os.path.basename(__file__).replace(".py", ""))

    logger.info("Script started.")

    # Override pauses if no-pause flag is set
    if no_pause:
        namespace_pause = 0
        pod_pause = 0
        logger.info("--no-pause flag enabled: All pauses disabled.")

    # Log wait-ready mode if enabled
    if wait_ready:
        logger.info(
            f"--wait-ready flag enabled: Will wait up to {wait_timeout}s for each pod to be ready."
        )

    # Display mode indicator
    if dry_run:
        panel = Panel(
            "[bold yellow]DRY RUN MODE[/bold yellow]\n"
            "No pods will be deleted. This is a preview of what would happen.",
            title="Operation Mode",
            border_style="yellow",
        )
        console.print(panel)

    # Load Kubernetes configuration
    if not load_kube_config_auto(config_file=kubeconfig):
        console.print("[bold red]Error: Failed to load Kubernetes configuration.[/bold red]")
        sys.exit(1)

    try:
        core_v1 = get_k8s_client("CoreV1Api")
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes API client: {e}", exc_info=True)
        console.print(f"[bold red]Error initializing Kubernetes client: {e}[/bold red]")
        sys.exit(1)

    # Display cluster information
    cluster_name = get_cluster_name_from_config()
    logger.info(f"Connected to cluster: {cluster_name}")
    console.print(f"\n[bold cyan]Cluster:[/bold cyan] {cluster_name}")

    # Load export data
    data = load_export_data(input_file)

    if not data:
        console.print("[yellow]No data found in export file.[/yellow]")
        logger.warning("Export file contains no data.")
        sys.exit(0)

    console.print(f"[green]Loaded data for {len(data)} namespace(s)[/green]")
    logger.info(f"Loaded data for {len(data)} namespace(s)")

    # Process all namespaces
    with console.status("[bold green]Processing namespaces...") as status:
        results = process_namespaces(
            core_v1, data, namespace_pause, pod_pause, dry_run, wait_ready, wait_timeout
        )

    # Display summary
    display_summary(results, dry_run)

    console.print("\n[bold green]Done.[/bold green]")
    logger.info("Script finished.")


if __name__ == "__main__":
    main()
