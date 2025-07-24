#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script to migrate Portworx volume encryption keys from Vault to Kubernetes Secrets."""

import json
import logging
import os
import subprocess

# Add project root to path for utils
import sys
from typing import Any, Dict, List, Optional

import click
from kubernetes import client
from kubernetes.dynamic import DynamicClient
from rich.console import Console

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

# from pyplayground.utils.k8s_utils import (
#     get_k8s_client,
# )
from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.px_api import (
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

    export_data = {}
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

            export_data[namespace] = export_data.get(namespace, []) + [pvc_data_entry]

    console.print(f"[bold green]✓[/bold green] Processed {len(annotated_pvcs)} PVCs.")
    return export_data


def migrate_key(
    namespace: str,
    pvc_data: Dict,
    pxctl_path: str,
    dry_run: bool,
) -> None:
    """Migrates a single key from Vault to Kubernetes Secret."""
    secret_name = pvc_data["vaultpath"]
    normalized_secret_name = normalize_secret_name(secret_name)
    secret_key = pvc_data["portworxvolumeinspect_labels"]["SECRET_KEY"]

    if normalized_secret_name != secret_key:
        logger.info(
            f"Secret key '{secret_key}' will be migrated to secret '{normalized_secret_name}' in namespace '{namespace}'."
        )

    # Check if vault_data contains valid data
    if "error" in pvc_data["vault_data"]:
        logger.warning(
            f"Skipping migration for '{secret_key}' due to error: {pvc_data['vault_data']['error']}"
        )
        return

    key_value = pvc_data["vault_data"]["data"]
    secret = client.V1Secret(
        api_version="v1",
        kind="Secret",
        metadata=client.V1ObjectMeta(name=normalized_secret_name, namespace=namespace),
        type="Opaque",
        data={"key": (key_value).encode()},
    )

    try:
        dynamic_client = DynamicClient(client.ApiClient())
        existing_secret = dynamic_client.custom_objects(
            group="v1",
            version="secrets.core",
            plural="secrets",
            namespace=namespace,
        ).get_namespaced_custom_object(name=normalized_secret_name, namespace=namespace)
        if existing_secret:
            logger.info(
                f"Secret '{normalized_secret_name}' already exists in namespace '{namespace}'. Skipping creation."
            )
            return

        if not dry_run:
            secret.write_namespaced_secret(namespace=namespace)
            logger.info(f"Created secret '{normalized_secret_name}' in namespace '{namespace}'.")
        else:
            logger.info(
                f"Dry run: Would create secret '{normalized_secret_name}' in namespace '{namespace}'."
            )

        # Update Portworx volume label
        update_px_volume_label(pvc_data, normalized_secret_name, pxctl_path, dry_run)

    except client.exceptions.ApiException as e:
        logger.error(
            f"Error creating/updating secret '{normalized_secret_name}' in namespace '{namespace}': {e}",
            exc_info=True,
        )


def normalize_secret_name(secret_name: str) -> str:
    """Normalizes a secret name to be Kubernetes compliant."""
    normalized_name = secret_name.replace("/", "-")
    if not normalized_name:
        normalized_name = "temp-secret"
    return normalized_name


def update_px_volume_label(pvc_data: Dict, new_name: str, pxctl_path: str, dry_run: bool) -> None:
    """Updates the Portworx volume label with the new secret name."""
    pv_name = pvc_data["pv"]
    old_secret_name = pvc_data["portworxvolumeinspect_labels"].get("SECRET_KEY")
    px_secret_name = pvc_data["portworxvolumeinspect_labels"].get("px/secret-name")

    if (old_secret_name != new_name) or (px_secret_name != new_name):
        command = [
            pxctl_path,
            "volume",
            "update",
            "--label",
            f"SECRET_NAME={new_name},px/secret-name={new_name}",
            pv_name,
        ]
        logger.info(f"Running command: {' '.join(command)}")
        if not dry_run:
            try:
                result = subprocess.run(command, capture_output=True, text=True, check=True)
                logger.info(f"Command result: {result.stdout}")
            except subprocess.CalledProcessError as e:
                logger.error(f"Error updating volume label: {e}", exc_info=True)
        else:
            logger.info("Dry run: Would update volume label.")


# --- CLI Design ---


@click.command()
@click.option(
    "--input",
    type=click.Path(exists=True, dir_okay=False),
    required=True,
    help="Path to the exported JSON file.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Simulate all actions without changes.",
)
@click.option(
    "--pxctl-path",
    default="pxctl",
    show_default=True,
    help="Path to the pxctl binary.",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable verbose logging.",
)
def main(input: str, dry_run: bool, pxctl_path: str, debug: bool) -> None:
    """Migrates Portworx volume encryption keys from Vault to Kubernetes Secrets."""
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=os.path.basename(__file__).replace(".py", ""))

    logger.info("Script started.")

    try:
        with open(input, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Input file not found: {input}")
        console.print(f"[bold red]Error: Input file not found: {input}[/bold red]")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON in file {input}: {e}", exc_info=True)
        console.print(f"[bold red]Error decoding JSON in file '{input}': {e}[/bold red]")
        sys.exit(1)

    # try:
    #     core_v1 = get_k8s_client("CoreV1Api")
    #     storage_v1 = get_k8s_client("StorageV1Api")
    # except Exception as e:
    #     logger.error(f"Failed to initialize Kubernetes API clients: {e}", exc_info=True)
    #     console.print(f"[bold red]Error initializing Kubernetes clients: {e}[/bold red]")
    #     sys.exit(1)

    for namespace, pvc_data_list in data.items():
        for pvc_data in pvc_data_list:
            migrate_key(namespace, pvc_data, pxctl_path, dry_run)

    logger.info("Script finished.")


if __name__ == "__main__":
    main()
