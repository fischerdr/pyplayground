#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script to check Vault secrets referenced by Portworx PVC annotations."""

import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

import click
import urllib3
from rich.console import Console
from rich.table import Table

# Disable SSL warnings - due to self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Add project root to path for utils
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from pyplayground.utils.k8s_utils import (
    get_k8s_client,
    load_kube_config_auto,
)
from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.px_api import (
    DEFAULT_PX_NAMESPACE,
    VAULT_NAMESPACE_ANNOTATION,
    VAULT_SECRET_NAME_ANNOTATION,
    execute_pxctl_command,
    filter_volume_labels,
    get_annotated_portworx_pvcs,
    initialize_pvc_vault_environment,
)
from pyplayground.utils.vault_utils import (
    create_vault_client,
    get_secret,
    get_token_for_namespace,
)

# --- Constants ---
# (Vault and Portworx constants now imported from px_api)

# --- Globals ---
console = Console()
logger = get_logger(__name__)


# --- Helper Functions ---


def format_labels_for_table(labels: Optional[Dict[str, str]]) -> str:
    """Formats volume labels for display in a Rich table, filtering for specific prefixes."""
    if not labels:
        return ""

    filtered_labels = filter_volume_labels(labels)

    if not filtered_labels:
        return "[dim]No relevant labels found[/dim]"

    return json.dumps(filtered_labels, indent=2)


def check_vault_secret_status(
    vault_addr: str,
    vault_token: str,
    secret_path: str,
    mount_point: str,
    vault_namespace: Optional[str] = None,
) -> tuple[str, Optional[Dict[str, Any]]]:
    """Checks for a secret in Vault and returns its status and data."""
    logger.debug(
        f"Checking Vault for secret at path '{secret_path}' in mount '{mount_point}' (namespace: {vault_namespace or 'root'})."
    )

    try:
        vault_client = create_vault_client(
            url=vault_addr, token=vault_token, namespace=vault_namespace
        )
        secret_data = get_secret(vault_client, secret_path, mount_point=mount_point)

        if secret_data is None:
            return "[red]Not Found / Forbidden[/red]", None
        elif not secret_data:
            return "[yellow]Found (No Data)[/yellow]", {}
        else:
            return "[green]Found[/green]", secret_data
    except Exception as e:
        logger.error(f"Error reading Vault secret '{secret_path}': {e}", exc_info=True)
        return f"[red]Error: {type(e).__name__}[/red]", None


def _initialize_check_environment(core_v1_client, px_namespace):
    """Gets Vault/PX connection info and returns it, or None if setup fails."""
    return initialize_pvc_vault_environment(core_v1_client, px_namespace)


def _process_single_pvc(
    pvc,
    core_v1,
    px_namespace,
    px_pod,
    effective_env_vars,
    vault_conn_info,
    sa_jwt,
    vault_tokens,
):
    """Processes a single PVC, performing Vault and pxctl checks."""
    pvc_info = {
        "pvc_namespace": pvc.metadata.namespace,
        "pvc_name": pvc.metadata.name,
        "secret_path": pvc.metadata.annotations.get(VAULT_SECRET_NAME_ANNOTATION),
        "vault_namespace": pvc.metadata.annotations.get(VAULT_NAMESPACE_ANNOTATION, ""),
        "status": "[red]Unknown[/red]",
        "secret_data": None,
        "volume_labels": None,
    }

    # Vault Secret Check
    if not pvc_info["vault_namespace"]:
        pvc_info["status"] = "[red]No Vault Namespace Annotation[/red]"
    else:
        vault_token = get_token_for_namespace(
            pvc_info["vault_namespace"], vault_tokens, vault_conn_info, sa_jwt
        )
        if vault_token:
            pvc_info["status"], pvc_info["secret_data"] = check_vault_secret_status(
                vault_conn_info["addr"],
                vault_token,
                pvc_info["secret_path"],
                mount_point=vault_conn_info.get("backend_path", "secret"),
                vault_namespace=pvc_info["vault_namespace"],
            )
        else:
            pvc_info["status"] = "[red]Auth Failed[/red]"

    # Get Volume Labels from pxctl
    pv_name = pvc.spec.volume_name
    if pv_name:
        pxctl_json, _, _ = execute_pxctl_command(
            px_namespace=px_namespace,
            px_pod_name=px_pod.metadata.name,
            px_container_name=px_pod.spec.containers[0].name,
            command=f"pxctl volume inspect {pv_name} -j",
            env_vars=effective_env_vars,
            v1_client=core_v1,
        )
        if pxctl_json:
            pvc_info["volume_labels"] = pxctl_json.get("spec", {}).get("volume_labels")

    return pvc_info


def process_pvc_vault_checks(core_v1, storage_v1, px_namespace):
    """Gathers PVCs, checks vault secrets, fetches labels, and returns results."""
    init_result = _initialize_check_environment(core_v1, px_namespace)
    if not init_result:
        console.print(
            "[bold red]Failed to initialize check environment. Check logs for details.[/bold red]"
        )
        sys.exit(1)
    vault_conn_info, sa_jwt, px_pod, effective_env_vars = init_result

    annotated_pvcs = get_annotated_portworx_pvcs(core_v1, storage_v1)
    if not annotated_pvcs:
        console.print("[yellow]No Portworx PVCs with required Vault annotations found.[/yellow]")
        return []

    results = []
    vault_tokens: Dict[str, Optional[str]] = {}
    for pvc in annotated_pvcs:
        pvc_result = _process_single_pvc(
            pvc,
            core_v1,
            px_namespace,
            px_pod,
            effective_env_vars,
            vault_conn_info,
            sa_jwt,
            vault_tokens,
        )
        results.append(pvc_result)

    return results


def display_results(results: List[Dict[str, Any]], mask_values: bool):
    """Displays the results in a Rich table."""
    if not results:
        return

    table = Table(title="Portworx PVC Vault Secret Check Results")
    table.add_column("PVC Namespace", style="cyan")
    table.add_column("PVC Name", style="magenta")
    table.add_column("Vault Path", style="green")
    table.add_column("Vault Namespace", style="blue")
    table.add_column("Status", style="bold")
    table.add_column("Secret Data", style="yellow")
    table.add_column("Volume Labels", style="white")

    for item in results:
        secret_data_str = ""
        if item["secret_data"] is not None:
            if mask_values:
                secret_data_str = ", ".join(item["secret_data"].keys()) + " (values masked)"
            else:
                secret_data_str = json.dumps(item["secret_data"], indent=2)

        table.add_row(
            item["pvc_namespace"],
            item["pvc_name"],
            item["secret_path"],
            item["vault_namespace"] or "[dim]N/A[/dim]",
            item["status"],
            secret_data_str,
            format_labels_for_table(item["volume_labels"]),
        )
    console.print(table)


# --- Main Command ---


@click.command()
@click.option(
    "--kubeconfig",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the kubeconfig file. If not provided, uses default lookup.",
    envvar="KUBECONFIG",
)
@click.option(
    "--px-namespace",
    default=DEFAULT_PX_NAMESPACE,
    show_default=True,
    help="Namespace for Portworx and where to look for Vault credential secrets.",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
@click.option(
    "--mask/--no-mask",
    "mask_values",
    default=True,
    help="Mask/unmask sensitive values in the output.",
    show_default=True,
)
def main(kubeconfig: Optional[str], px_namespace: str, debug: bool, mask_values: bool):
    """Checks Vault secrets referenced by Portworx PVCs."""
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=os.path.basename(__file__).replace(".py", ""))

    logger.info("Script started.")

    if not load_kube_config_auto(config_file=kubeconfig):
        console.print("[bold red]Error: Failed to load Kubernetes configuration.[/bold red]")
        sys.exit(1)

    try:
        core_v1 = get_k8s_client("CoreV1Api")
        storage_v1 = get_k8s_client("StorageV1Api")
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes API clients: {e}", exc_info=True)
        console.print(f"[bold red]Error initializing Kubernetes clients: {e}[/bold red]")
        sys.exit(1)

    results = process_pvc_vault_checks(core_v1, storage_v1, px_namespace)
    display_results(results, mask_values)

    logger.info("Script finished.")


if __name__ == "__main__":
    main()
