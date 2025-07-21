#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script to migrate Portworx volume encryption keys from Vault to Kubernetes Secrets."""

import json
import logging
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

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


def normalize_secret_name(secret_key: str, pvc_name: str) -> Tuple[str, bool]:
    """Normalize SECRET_KEY to a valid Kubernetes secret name.

    IMPORTANT: Preserves '-pvc' suffixes as Portworx requires this naming
    pattern to locate encryption keys correctly.

    Returns:
        Tuple of (normalized_name, was_changed)
    """
    original_key = secret_key

    # If secret_key is already valid, use it
    if len(secret_key) <= MAX_SECRET_NAME_LENGTH and VALID_SECRET_NAME_PATTERN.match(secret_key):
        return secret_key, False

    # Convert to lowercase and replace invalid characters with hyphens
    normalized = re.sub(r"[^a-z0-9-]", "-", secret_key.lower())

    # Replace multiple consecutive hyphens with single hyphen
    normalized = re.sub(r"-+", "-", normalized)

    # Remove leading/trailing hyphens only (preserve alphanumeric + internal hyphens)
    normalized = normalized.strip("-")

    # Truncate if too long, but preserve the -pvc suffix if present
    if len(normalized) > MAX_SECRET_NAME_LENGTH:
        if normalized.endswith("-pvc") and len(normalized) > 4:
            # Preserve -pvc suffix, truncate the beginning part
            max_prefix_length = MAX_SECRET_NAME_LENGTH - 4  # Save space for "-pvc"
            prefix = normalized[:-4][:max_prefix_length].rstrip("-")
            old_normalized = normalized
            normalized = f"{prefix}-pvc"
            logger.debug(
                f"Preserved -pvc suffix during truncation: '{old_normalized}' → '{normalized}'"
            )
        else:
            normalized = normalized[:MAX_SECRET_NAME_LENGTH].rstrip("-")

    # If result is empty or still invalid, use PVC name as fallback
    if not normalized or not VALID_SECRET_NAME_PATTERN.match(normalized):
        normalized = pvc_name.lower()
        # For PVC names, preserve the structure but ensure K8s compliance
        normalized = re.sub(r"[^a-z0-9-]", "-", normalized)
        normalized = re.sub(r"-+", "-", normalized).strip("-")

    # Final validation - if still invalid, use a generic name
    if not VALID_SECRET_NAME_PATTERN.match(normalized):
        normalized = f"px-secret-{hash(original_key) & 0x7fffffff}"

    return normalized, True


def parse_export_data(input_file: str) -> Dict[str, List[Dict[str, Any]]]:
    """Parse and validate the JSON export file."""
    logger.debug(f"Parsing export data from {input_file}")

    try:
        with open(input_file, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Input file not found: {input_file}")
        console.print(f"[bold red]Error: Input file '{input_file}' not found.[/bold red]")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in input file: {e}")
        console.print(f"[bold red]Error: Invalid JSON in input file: {e}[/bold red]")
        sys.exit(1)

    if not isinstance(data, dict):
        logger.error("Input data must be a dictionary with namespaces as keys")
        console.print(
            "[bold red]Error: Input data must be a dictionary with namespaces as keys[/bold red]"
        )
        sys.exit(1)

    # Validate structure
    total_entries = 0
    for namespace, pvc_list in data.items():
        if not isinstance(pvc_list, list):
            logger.warning(f"Namespace '{namespace}' does not contain a list of PVCs, skipping")
            continue
        total_entries += len(pvc_list)

    console.print(f"[green]Loaded {total_entries} PVC entries from {len(data)} namespaces[/green]")
    return data


def validate_pvc_entry(pvc_entry: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Validate a PVC entry and extract required fields.

    Returns:
        Dict with required fields or None if validation fails
    """
    required_fields = ["pvc", "pv", "portworxvolumeinspect_labels", "vault_data"]

    for field in required_fields:
        if field not in pvc_entry:
            logger.warning(f"Missing required field '{field}' in PVC entry")
            return None

    # Check for vault_data errors
    vault_data = pvc_entry["vault_data"]
    if not isinstance(vault_data, dict) or "error" in vault_data:
        error_msg = (
            vault_data.get("error", "Unknown vault error")
            if isinstance(vault_data, dict)
            else "Invalid vault data"
        )
        logger.warning(f"Vault data error for PVC '{pvc_entry['pvc']}': {error_msg}")
        return None

    # Extract volume labels
    volume_labels = pvc_entry["portworxvolumeinspect_labels"]
    if not isinstance(volume_labels, dict):
        logger.warning(f"Invalid volume labels for PVC '{pvc_entry['pvc']}'")
        return None

    secret_key = volume_labels.get(SECRET_KEY_LABEL)
    secret_context = volume_labels.get(SECRET_CONTEXT_LABEL)

    if not secret_key:
        logger.warning(f"Missing SECRET_KEY label for PVC '{pvc_entry['pvc']}'")
        return None

    if not secret_context:
        logger.warning(f"Missing SECRET_CONTEXT label for PVC '{pvc_entry['pvc']}'")
        return None

    # Extract the first key from vault_data as the encryption key
    vault_data_content = vault_data.get("data", {})
    if not vault_data_content:
        logger.warning(f"No data found in vault for PVC '{pvc_entry['pvc']}'")
        return None

    encryption_key = next(iter(vault_data_content.values()), None)
    if not encryption_key:
        logger.warning(f"No encryption key found in vault data for PVC '{pvc_entry['pvc']}'")
        return None

    return {
        "pvc_name": pvc_entry["pvc"],
        "pv_name": pvc_entry["pv"],
        "secret_key": secret_key,
        "secret_context": secret_context,
        "encryption_key": encryption_key,
    }


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
    logger.debug(f"Creating secret '{secret_name}' in namespace '{namespace}' (dry-run: {dry_run})")

    # Check if secret already exists
    try:
        core_v1.read_namespaced_secret(name=secret_name, namespace=namespace)
        console.print(
            f"[yellow]Secret '{secret_name}' already exists in namespace '{namespace}', skipping[/yellow]"
        )
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

    if dry_run:
        console.print(
            f"[blue]DRY-RUN: Would create secret '{secret_name}' in namespace '{namespace}' with key '{secret_key}'[/blue]"
        )
        logger.info(f"DRY-RUN: Would create secret '{secret_name}' in namespace '{namespace}'")
        return True

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
    # Check if labels need updating
    current_secret_name = current_labels.get("SECRET_NAME") or current_labels.get("px/secret-name")

    if current_secret_name == secret_name:
        logger.debug(f"Volume '{pv_name}' labels already correct")
        return True

    # Prepare update command
    labels_to_update = [f"SECRET_NAME={secret_name}", f"px/secret-name={secret_name}"]
    command = f"pxctl volume update --label {','.join(labels_to_update)} {pv_name}"

    if dry_run:
        console.print(f"[blue]DRY-RUN: Would run command: {command}[/blue]")
        logger.info(f"DRY-RUN: Would run pxctl command: {command}")
        return True

    try:
        logger.debug(f"Running pxctl command: {command}")
        _, stdout, error_msg = execute_pxctl_command(
            px_namespace=px_namespace,
            px_pod_name=px_pod.metadata.name,
            px_container_name=px_pod.spec.containers[0].name,
            command=command,
            env_vars=effective_env_vars,
            v1_client=core_v1,
        )

        if error_msg:
            logger.error(f"pxctl command failed for volume '{pv_name}': {error_msg}")
            console.print(
                f"[red]✗[/red] Failed to update labels for volume '{pv_name}': {error_msg}"
            )
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
        pvc_suffix_info = (
            " (-pvc suffix preserved)" if normalized_secret_name.endswith("-pvc") else ""
        )
        console.print(
            f"[yellow]Secret name normalized: '{secret_key}' → '{normalized_secret_name}'{pvc_suffix_info}[/yellow]"
        )
        logger.info(
            f"Secret name normalized for PVC '{pvc_name}': '{secret_key}' → '{normalized_secret_name}'{pvc_suffix_info}"
        )

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

    return secret_success and label_success


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
        console.print(
            "[bold red]Failed to initialize Portworx environment. Check logs for details.[/bold red]"
        )
        sys.exit(1)
    _, _, px_pod, effective_env_vars = init_result

    with console.status("[bold green]Migrating encryption keys...") as status:
        for namespace, pvc_list in export_data.items():
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
                    logger.error(
                        f"Unexpected error processing PVC '{pvc_name}': {e}", exc_info=True
                    )
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
        console.print("[bold blue]DRY-RUN MODE: No changes will be made[/bold blue]")
        logger.info("Running in dry-run mode")

    # Parse input data
    export_data = parse_export_data(input)

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
    results = migrate_vault_to_k8s_secrets(
        export_data=export_data, core_v1=core_v1, px_namespace=px_namespace, dry_run=dry_run
    )

    # Display results
    console.print("\n[bold]Migration Results:[/bold]")
    console.print(f"  Total entries: {results['total']}")
    console.print(f"  [green]Successful: {results['success']}[/green]")
    console.print(f"  [red]Failed: {results['failed']}[/red]")

    if results["failed"] > 0:
        console.print("\n[yellow]Some entries failed to migrate. Check logs for details.[/yellow]")
        logger.warning(
            f"Migration completed with {results['failed']} failures out of {results['total']} total entries"
        )
    else:
        console.print("\n[bold green]All entries processed successfully![/bold green]")
        logger.info("Migration completed successfully")

    logger.info("Migration script finished")


if __name__ == "__main__":
    main()
