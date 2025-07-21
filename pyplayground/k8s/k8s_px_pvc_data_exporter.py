#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script to export Portworx PVC data to a JSON file."""

import json
import logging
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional

import click
import urllib3
from kubernetes import client
from rich.console import Console

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


def get_vault_secret_details(
    vault_addr: str,
    vault_token: str,
    secret_path: str,
    mount_point: str,
    vault_namespace: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Reads a secret from Vault and returns its full data (including metadata)."""
    logger.debug(
        f"Reading Vault secret at path '{secret_path}' in mount '{mount_point}' (namespace: {vault_namespace or 'root'})."
    )
    try:
        vault_client = create_vault_client(
            url=vault_addr, token=vault_token, namespace=vault_namespace
        )
        secret_content = get_secret(vault_client, secret_path, mount_point=mount_point)

        if secret_content is None:
            return {"error": "Secret not found or access forbidden"}
        return {"data": secret_content}  # Nest data for consistency

    except Exception as e:
        logger.error(f"Error reading Vault secret '{secret_path}': {e}", exc_info=True)
        return {"error": f"Error reading secret: {type(e).__name__}"}


def _initialize_export_environment(
    core_v1_client: client.CoreV1Api, px_namespace: str
) -> Optional[tuple[Dict[str, str], str, client.V1Pod, List[str]]]:
    """Gets Portworx and Vault connection info and returns it, or None if setup fails."""
    return initialize_pvc_vault_environment(core_v1_client, px_namespace)


def gather_pvc_data(
    core_v1: client.CoreV1Api, storage_v1: client.StorageV1Api, px_namespace: str
) -> Dict[str, List[Dict[str, Any]]]:
    """Gathers data from PVCs, PVs, and pxctl inspect and returns a dictionary."""
    init_result = _initialize_export_environment(core_v1, px_namespace)
    if not init_result:
        console.print(
            "[bold red]Failed to initialize export environment. Check logs for details.[/bold red]"
        )
        sys.exit(1)
    vault_conn_info, sa_jwt, px_pod, effective_env_vars = init_result

    annotated_pvcs = get_annotated_portworx_pvcs(core_v1, storage_v1)
    if not annotated_pvcs:
        console.print("[yellow]No Portworx PVCs with required Vault annotations found.[/yellow]")
        return {}

    export_data = defaultdict(list)
    vault_tokens: Dict[str, Optional[str]] = {}

    with console.status("[bold green]Processing PVCs...") as status:
        for pvc in annotated_pvcs:
            namespace = pvc.metadata.namespace
            pvc_name = pvc.metadata.name
            pv_name = pvc.spec.volume_name

            status.update(f"Processing {namespace}/{pvc_name}...")

            pvc_data_entry = {
                "pvc": pvc_name,
                "pv": pv_name,
                "vaultpath": pvc.metadata.annotations.get(VAULT_SECRET_NAME_ANNOTATION),
                "vaultnamespace": pvc.metadata.annotations.get(VAULT_NAMESPACE_ANNOTATION),
                "portworxvolumeinspect_labels": {},
                "vault_data": None,
            }

            vault_namespace = pvc_data_entry["vaultnamespace"]
            if vault_namespace:
                vault_token = get_token_for_namespace(
                    vault_namespace, vault_tokens, vault_conn_info, sa_jwt
                )
                if vault_token:
                    pvc_data_entry["vault_data"] = get_vault_secret_details(
                        vault_conn_info["addr"],
                        vault_token,
                        pvc_data_entry["vaultpath"],
                        mount_point=vault_conn_info.get("backend_path", "secret"),
                        vault_namespace=vault_namespace,
                    )
                else:
                    pvc_data_entry["vault_data"] = {"error": "Vault authentication failed"}
            else:
                pvc_data_entry["vault_data"] = {"error": "No Vault namespace annotation on PVC"}

            if pv_name:
                pxctl_json, _, err_msg = execute_pxctl_command(
                    px_namespace=px_namespace,
                    px_pod_name=px_pod.metadata.name,
                    px_container_name=px_pod.spec.containers[0].name,
                    command=f"pxctl volume inspect {pv_name} -j",
                    env_vars=effective_env_vars,
                    v1_client=core_v1,
                )

                if err_msg:
                    logger.error(f"Error inspecting volume '{pv_name}': {err_msg}")
                    pvc_data_entry["portworxvolumeinspect_labels"] = {"error": err_msg}
                elif pxctl_json and "spec" in pxctl_json:
                    all_labels = pxctl_json.get("spec", {}).get("volume_labels") or {}
                    pvc_data_entry["portworxvolumeinspect_labels"] = filter_volume_labels(
                        all_labels
                    )
            else:
                logger.warning(f"PVC {namespace}/{pvc_name} has no PV name (unbound?).")

            export_data[namespace].append(pvc_data_entry)

    console.print(f"[bold green]✓[/bold green] Processed {len(annotated_pvcs)} PVCs.")
    return dict(export_data)


def write_json_output(data: Dict, output_file: str):
    """Writes the collected data to a JSON file."""
    try:
        with open(output_file, "w") as f:
            json.dump(data, f, indent=4)
        console.print(f"[green]Successfully wrote data to {output_file}[/green]")
    except IOError as e:
        console.print(f"[bold red]Error writing to file '{output_file}': {e}[/bold red]")
        sys.exit(1)


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
@click.option(
    "--output-file",
    required=True,
    type=click.Path(dir_okay=False, writable=True),
    help="Path to the output JSON file.",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(kubeconfig: Optional[str], px_namespace: str, output_file: str, debug: bool):
    """Exports Portworx PVC data (PV, annotations, volume labels) to a JSON file."""
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

    exported_data = gather_pvc_data(core_v1, storage_v1, px_namespace)

    if exported_data:
        write_json_output(exported_data, output_file)
    else:
        console.print("[yellow]No data was gathered to export.[/yellow]")

    logger.info("Script finished.")


if __name__ == "__main__":
    main()
