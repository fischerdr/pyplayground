#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script to migrate Portworx volume encryption keys from Vault to Kubernetes Secrets."""

import logging
import os
import re
import sys
from typing import Any, Dict, List

import click
import urllib3
from kubernetes import client
from kubernetes.client.rest import ApiException
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
from pyplayground.utils.migration_utils import (
    normalize_secret_name,
    parse_export_data,
    validate_pvc_entry,
)
from pyplayground.utils.px_api import (
    DEFAULT_PX_NAMESPACE,
    execute_pxctl_command,
    initialize_pvc_vault_environment,
)

# --- Constants ---
SECRET_KEY_LABEL = "SECRET_KEY"
SECRET_CONTEXT_LABEL = "SECRET_CONTEXT"
VALID_SECRET_NAME_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
MAX_SECRET_NAME_LENGTH = 253

# --- Globals ---
console = Console()
logger = get_logger(__name__)


# --- Helper Functions ---


def create_kubernetes_secret(
    core_v1: client.CoreV1Api,
    secret_name: str,
    namespace: str,
    secret_key: str,
    encryption_key: str,
    dry_run: bool = False,
) -> bool:
    """Create a Kubernetes secret with the encryption key.

    Returns:
        True if successful (or would be successful in dry-run), False otherwise
    """
    logger.debug(f"Handling secret '{secret_name}' in namespace '{namespace}' (dry-run: {dry_run})")

    if dry_run:
        console.print(f"[bright_blue]DRY-RUN: Would check for and create secret '{secret_name}' in namespace '{namespace}' with key '{secret_key}' if not present.[/bright_blue]")
        logger.info(f"DRY-RUN: Would create secret '{secret_name}' in namespace '{namespace}'")
        return True

    # Check if secret already exists
    try:
        core_v1.read_namespaced_secret(name=secret_name, namespace=namespace)
        console.print(f"[yellow]Secret '{secret_name}' already exists in namespace '{namespace}', skipping[/yellow]")
        logger.info(f"Secret '{secret_name}' already exists in namespace '{namespace}'")
        return True
    except ApiException as e:
        if e.status != 404:
            logger.error(f"Error checking for existing secret: {e}")
            return False

    # Prepare secret data
    secret_data = {secret_key: encryption_key}

    secret_manifest = client.V1Secret(
        api_version="v1",
        kind="Secret",
        metadata=client.V1ObjectMeta(name=secret_name, namespace=namespace),
        type="Opaque",
        string_data=secret_data,
    )

    try:
        core_v1.create_namespaced_secret(namespace=namespace, body=secret_manifest)
        console.print(f"[green]✓[/green] Created secret '{secret_name}' in namespace '{namespace}'")
        logger.info(f"Successfully created secret '{secret_name}' in namespace '{namespace}'")
        return True
    except ApiException as e:
        logger.error(f"Failed to create secret '{secret_name}': {e}")
        console.print(f"[red]✗[/red] Failed to create secret '{secret_name}': {e}")
        return False


def update_portworx_labels(
    pv_name: str,
    secret_name: str,
    current_labels: Dict[str, str],
    px_namespace: str,
    px_pod: client.V1Pod,
    effective_env_vars: List[str],
    core_v1: client.CoreV1Api,
    dry_run: bool = False,
) -> bool:
    """Update Portworx volume labels if needed.

    Returns:
        True if successful or no update needed, False otherwise
    """
    # Prepare update command early to show in dry-run
    labels_to_update = [
        f"SECRET_NAME={secret_name}",
        f"px/secret-name={secret_name}",
        "px/vault-namespace",
    ]
    command = f"pxctl volume update --label {','.join(labels_to_update)} {pv_name}"

    if dry_run:
        console.print(f"[bright_blue]DRY-RUN: Would check labels and potentially run command: {command}[/bright_blue]")
        logger.info(f"DRY-RUN: Would run pxctl command: {command}")
        return True

    # Check if labels need updating
    current_secret_name = current_labels.get("SECRET_NAME") or current_labels.get("px/secret-name")

    if current_secret_name == secret_name:
        logger.debug(f"Volume '{pv_name}' labels already correct")
        return True

    # Prepare update command
    labels_to_update = [
        f"SECRET_NAME={secret_name}",
        f"px/secret-name={secret_name}",
        "px/vault-namespace",
    ]
    command = f"pxctl volume update --label {','.join(labels_to_update)} {pv_name}"

    try:
        logger.debug(f"Running pxctl command: {command}")
        _, stdout, error_msg = execute_pxctl_command(
            px_namespace=px_namespace,
            px_pod_name=px_pod.metadata.name,
            px_container_name=px_pod.spec.containers[0].name,
            command=command,
            env_vars=effective_env_vars,
            v1_client=core_v1,
            expect_json=False,
        )

        if error_msg:
            logger.error(f"pxctl command failed for volume '{pv_name}': {error_msg}")
            console.print(f"[red]✗[/red] Failed to update labels for volume '{pv_name}': {error_msg}")
            return False
        else:
            console.print(f"[green]✓[/green] Updated labels for volume '{pv_name}'")
            logger.info(f"Successfully updated labels for volume '{pv_name}'")
            if stdout:
                logger.debug(f"pxctl output: {stdout}")
            return True

    except Exception as e:
        logger.error(f"Unexpected error running pxctl for volume '{pv_name}': {e}")
        console.print(f"[red]✗[/red] Unexpected error updating volume '{pv_name}': {e}")
        return False


def remove_pvc_vault_annotation(
    core_v1: client.CoreV1Api,
    pvc_name: str,
    namespace: str,
    dry_run: bool = False,
) -> bool:
    """Remove the 'px/vault-namespace' annotation from a PVC if it exists."""
    logger.debug(f"Handling 'px/vault-namespace' annotation for PVC '{pvc_name}' in namespace '{namespace}' (dry-run: {dry_run})")

    if dry_run:
        console.print(f"[bright_blue]DRY-RUN: Would check and remove 'px/vault-namespace' annotation from PVC '{namespace}/{pvc_name}' if it exists.[/bright_blue]")
        logger.info(f"DRY-RUN: Would remove 'px/vault-namespace' annotation from PVC '{namespace}/{pvc_name}'")
        return True

    try:
        pvc = core_v1.read_namespaced_persistent_volume_claim(name=pvc_name, namespace=namespace)
        annotations = pvc.metadata.annotations or {}

        if "px/vault-namespace" not in annotations:
            logger.debug(f"Annotation 'px/vault-namespace' not found on PVC '{pvc_name}', skipping.")
            return True

        # JSON Patch to remove the annotation. Note the escaping for the '/' in the key.
        patch_body = [{"op": "remove", "path": "/metadata/annotations/px~1vault-namespace"}]

        core_v1.patch_namespaced_persistent_volume_claim(name=pvc_name, namespace=namespace, body=patch_body)

        console.print(f"[green]✓[/green] Removed vault annotation from PVC '{namespace}/{pvc_name}'")
        logger.info(f"Successfully removed 'px/vault-namespace' annotation from PVC '{namespace}/{pvc_name}'")
        return True

    except ApiException as e:
        if e.status == 404:
            logger.error(f"PVC '{pvc_name}' not found in namespace '{namespace}'")
            console.print(f"[red]✗[/red] PVC '{pvc_name}' not found in '{namespace}'")
        else:
            logger.error(f"Failed to patch PVC '{pvc_name}': {e}")
            console.print(f"[red]✗[/red] Failed to patch PVC '{pvc_name}': {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error removing annotation from PVC '{pvc_name}': {e}")
        console.print(f"[red]✗[/red] Unexpected error patching PVC '{pvc_name}': {e}")
        return False


def update_pvc_annotations(
    core_v1: client.CoreV1Api,
    pvc_name: str,
    namespace: str,
    secret_key: str,
    secret_name: str,
    secret_namespace: str,
    dry_run: bool = False,
) -> bool:
    """Update the Kubernetes PVC with Portworx secret annotations."""
    logger.debug(f"Handling secret annotations for PVC '{pvc_name}' in namespace '{namespace}' (dry-run: {dry_run})")

    annotations_to_set = {
        "px/secret-key": secret_key,
        "px/secret-name": secret_name,
        "px/secret-namespace": secret_namespace,
    }

    if dry_run:
        console.print(f"[bright_blue]DRY-RUN: Would check and update annotations on PVC '{namespace}/{pvc_name}' with: {annotations_to_set}[/bright_blue]")
        logger.info(f"DRY-RUN: Would update annotations on PVC '{namespace}/{pvc_name}' with {annotations_to_set}")
        return True

    try:
        pvc = core_v1.read_namespaced_persistent_volume_claim(name=pvc_name, namespace=namespace)
        current_annotations = pvc.metadata.annotations or {}

        # Check if an update is needed to avoid unnecessary API calls
        if all(current_annotations.get(k) == v for k, v in annotations_to_set.items()):
            logger.debug(f"PVC '{pvc_name}' annotations are already correct. Skipping.")
            return True

        # Prepare the patch by updating the current annotations
        updated_annotations = current_annotations.copy()
        updated_annotations.update(annotations_to_set)

        patch_body = {"metadata": {"annotations": updated_annotations}}

        core_v1.patch_namespaced_persistent_volume_claim(name=pvc_name, namespace=namespace, body=patch_body)

        console.print(f"[green]✓[/green] Updated secret annotations on PVC '{namespace}/{pvc_name}'")
        logger.info(f"Successfully updated secret annotations on PVC '{namespace}/{pvc_name}'")
        return True

    except ApiException as e:
        if e.status == 404:
            logger.error(f"PVC '{pvc_name}' not found in namespace '{namespace}' for annotation update")
            console.print(f"[red]✗[/red] PVC '{pvc_name}' not found in '{namespace}'")
        else:
            logger.error(f"Failed to patch PVC '{pvc_name}' for annotation update: {e}")
            console.print(f"[red]✗[/red] Failed to patch PVC '{pvc_name}': {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error updating annotations on PVC '{pvc_name}': {e}")
        console.print(f"[red]✗[/red] Unexpected error patching PVC '{pvc_name}': {e}")
        return False


def process_pvc_entry(
    core_v1: client.CoreV1Api,
    namespace: str,
    pvc_entry: Dict[str, Any],
    px_namespace: str,
    px_pod: client.V1Pod,
    effective_env_vars: List[str],
    dry_run: bool = False,
) -> bool:
    """Process a single PVC entry for migration.

    Returns:
        True if successful, False otherwise
    """
    validated_entry = validate_pvc_entry(pvc_entry)
    if not validated_entry:
        return False

    pvc_name = validated_entry["pvc_name"]
    pv_name = validated_entry["pv_name"]
    secret_key = validated_entry["secret_key"]
    secret_context = validated_entry["secret_context"]
    encryption_key = validated_entry["encryption_key"]

    logger.info(f"Processing PVC '{pvc_name}' in namespace '{namespace}'")

    # Normalize secret name
    normalized_secret_name, name_changed = normalize_secret_name(secret_key, pvc_name)

    if name_changed:
        pvc_suffix_info = " (-pvc suffix preserved)" if normalized_secret_name.endswith("-pvc") else ""
        console.print(f"[yellow]Secret name normalized: '{secret_key}' → '{normalized_secret_name}'{pvc_suffix_info}[/yellow]")
        logger.info(f"Secret name normalized for PVC '{pvc_name}': '{secret_key}' → '{normalized_secret_name}'{pvc_suffix_info}")

    # Create Kubernetes secret
    secret_success = create_kubernetes_secret(
        core_v1=core_v1,
        secret_name=normalized_secret_name,
        namespace=secret_context,
        secret_key=secret_key,
        encryption_key=encryption_key,
        dry_run=dry_run,
    )

    if not secret_success:
        return False

    # Remove vault annotation from PVC
    annotation_success = remove_pvc_vault_annotation(
        core_v1=core_v1,
        pvc_name=pvc_name,
        namespace=namespace,
        dry_run=dry_run,
    )

    # Update Portworx labels if needed
    current_labels = pvc_entry.get("portworxvolumeinspect_labels", {})
    label_success = update_portworx_labels(
        pv_name=pv_name,
        secret_name=normalized_secret_name,
        current_labels=current_labels,
        px_namespace=px_namespace,
        px_pod=px_pod,
        effective_env_vars=effective_env_vars,
        core_v1=core_v1,
        dry_run=dry_run,
    )

    # Update PVC annotations
    pvc_annotation_success = update_pvc_annotations(
        core_v1=core_v1,
        pvc_name=pvc_name,
        namespace=namespace,
        secret_key=secret_key,
        secret_name=normalized_secret_name,
        secret_namespace=secret_context,
        dry_run=dry_run,
    )

    return secret_success and annotation_success and label_success and pvc_annotation_success


def migrate_vault_to_k8s_secrets(
    export_data: Dict[str, List[Dict[str, Any]]],
    core_v1: client.CoreV1Api,
    px_namespace: str,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Perform the migration from Vault to Kubernetes secrets.

    Returns:
        Dict with success/failure counts
    """
    results = {"total": 0, "success": 0, "failed": 0, "skipped": 0}

    # Initialize Portworx environment for pxctl commands
    init_result = initialize_pvc_vault_environment(core_v1, px_namespace)
    if not init_result:
        console.print("[bold red]Failed to initialize Portworx environment. Check logs for details.[/bold red]")
        sys.exit(1)
    _, _, px_pod, effective_env_vars = init_result

    with console.status("[bold green]Migrating encryption keys...") as status:
        for namespace, pvc_list in export_data.items():
            console.print(f"\n[bold cyan]==> Processing Namespace: {namespace} ({len(pvc_list)} PVCs)[/bold cyan]")
            logger.info(f"--- Starting processing for namespace: {namespace} ---")
            for pvc_entry in pvc_list:
                results["total"] += 1
                pvc_name = pvc_entry.get("pvc", "unknown")

                status.update(f"Processing {namespace}/{pvc_name}...")

                try:
                    success = process_pvc_entry(
                        core_v1=core_v1,
                        namespace=namespace,
                        pvc_entry=pvc_entry,
                        px_namespace=px_namespace,
                        px_pod=px_pod,
                        effective_env_vars=effective_env_vars,
                        dry_run=dry_run,
                    )

                    if success:
                        results["success"] += 1
                    else:
                        results["failed"] += 1

                except Exception as e:
                    logger.error(f"Unexpected error processing PVC '{pvc_name}': {e}", exc_info=True)
                    console.print(f"[red]✗[/red] Unexpected error processing PVC '{pvc_name}': {e}")
                    results["failed"] += 1

    return results


# --- Main Command ---


@click.command()
@click.option(
    "--input",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to the JSON export file from k8s_px_pvc_data_exporter.py",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Simulate all actions without making any changes",
)
@click.option(
    "--px-namespace",
    default=DEFAULT_PX_NAMESPACE,
    show_default=True,
    help="Namespace for Portworx and where to look for Portworx pods",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(input: str, dry_run: bool, px_namespace: str, debug: bool):
    """Migrate Portworx volume encryption keys from HashiCorp Vault to Kubernetes Secrets.

    This script processes the JSON output from k8s_px_pvc_data_exporter.py and:
    1. Creates Kubernetes secrets with the encryption keys
    2. Updates Portworx volume labels to reference the new secrets
    3. Provides audit trail through comprehensive logging
    """
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=os.path.basename(__file__).replace(".py", ""))

    logger.info("Migration script started")

    if dry_run:
        console.print("[bold bright_blue]DRY-RUN MODE: No changes will be made[/bold bright_blue]")
        logger.info("Running in dry-run mode")

    # Parse input data
    try:
        export_data = parse_export_data(input)
    except (ValueError, FileNotFoundError) as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        sys.exit(1)

    # Load Kubernetes configuration
    if not load_kube_config_auto():
        console.print("[bold red]Error: Failed to load Kubernetes configuration.[/bold red]")
        sys.exit(1)

    try:
        core_v1 = get_k8s_client("CoreV1Api")
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes API client: {e}", exc_info=True)
        console.print(f"[bold red]Error initializing Kubernetes client: {e}[/bold red]")
        sys.exit(1)

    # Perform migration
    results = migrate_vault_to_k8s_secrets(export_data=export_data, core_v1=core_v1, px_namespace=px_namespace, dry_run=dry_run)

    # Display results
    console.print("\n[bold]Migration Results:[/bold]")
    console.print(f"  Total entries: {results['total']}")
    console.print(f"  [green]Successful: {results['success']}[/green]")
    console.print(f"  [red]Failed: {results['failed']}[/red]")

    if results["failed"] > 0:
        console.print("\n[yellow]Some entries failed to migrate. Check logs for details.[/yellow]")
        logger.warning(f"Migration completed with {results['failed']} failures out of {results['total']} total entries")
    else:
        console.print("\n[bold green]All entries processed successfully![/bold green]")
        logger.info("Migration completed successfully")

    logger.info("Migration script finished")


if __name__ == "__main__":
    main()
