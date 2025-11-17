#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script to verify the migration of Portworx volume encryption keys from Vault to Kubernetes Secrets."""

import logging
import os
import sys
from typing import Any, Dict, List, Tuple

import click
import urllib3
from kubernetes import client
from kubernetes.client.rest import ApiException
from rich.console import Console
from rich.table import Table

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Add project root to path for utils
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from pyplayground.utils.k8s_utils import get_k8s_client, load_kube_config_auto
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

# --- Globals ---
console = Console()
logger = get_logger(__name__)


class VerificationResult:
    """Holds the results of a single PVC verification."""

    def __init__(self, pvc_name: str, namespace: str):
        """Initialize a VerificationResult object.

        Args:
            pvc_name (str): The name of the PVC.
            namespace (str): The namespace of the PVC.
        """
        self.pvc_name = pvc_name
        self.namespace = namespace
        self.checks: List[Dict[str, Any]] = []
        self.overall_status = "SUCCESS"

    def add_check(self, name: str, success: bool, message: str):
        """Add a verification check result."""
        self.checks.append({"name": name, "success": success, "message": message})
        if not success:
            self.overall_status = "FAILED"

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to a dictionary."""
        return {
            "pvc_name": self.pvc_name,
            "namespace": self.namespace,
            "overall_status": self.overall_status,
            "checks": self.checks,
        }


def verify_kubernetes_secret(
    core_v1: client.CoreV1Api,
    secret_name: str,
    namespace: str,
    expected_key: str,
    expected_value: str,
) -> Tuple[bool, str]:
    """Verify the existence and content of a Kubernetes secret."""
    try:
        secret = core_v1.read_namespaced_secret(name=secret_name, namespace=namespace)
        if expected_key not in secret.data:
            return False, f"Secret key '{expected_key}' not found."

        import base64

        decoded_value = base64.b64decode(secret.data[expected_key]).decode("utf-8")
        if decoded_value != expected_value:
            return False, "Secret value does not match expected value."

        return True, "Secret exists and content is correct."
    except ApiException as e:
        if e.status == 404:
            return False, "Secret not found."
        return False, f"API error checking secret: {e.reason}"
    except Exception as e:
        return False, f"Unexpected error checking secret: {e}"


def verify_portworx_volume_labels(
    pv_name: str,
    expected_secret_name: str,
    px_namespace: str,
    px_pod: client.V1Pod,
    effective_env_vars: List[str],
    core_v1: client.CoreV1Api,
) -> Tuple[bool, str]:
    """Verify the labels on a Portworx volume."""
    command = f"pxctl volume inspect {pv_name} -j"
    pxctl_json, _, err_msg = execute_pxctl_command(
        px_namespace=px_namespace,
        px_pod_name=px_pod.metadata.name,
        px_container_name=px_pod.spec.containers[0].name,
        command=command,
        env_vars=effective_env_vars,
        v1_client=core_v1,
    )

    if err_msg:
        return False, f"pxctl command failed: {err_msg}"

    if not pxctl_json:
        return False, "Failed to get volume details from pxctl."

    labels = pxctl_json.get("locator", {}).get("volume_labels", {})
    secret_name = labels.get("SECRET_NAME")
    px_secret_name = labels.get("px/secret-name")

    if secret_name != expected_secret_name or px_secret_name != expected_secret_name:
        return False, f"SECRET_NAME or px/secret-name label is incorrect. Found: {labels}"

    if "px/vault-namespace" in labels:
        return False, "px/vault-namespace label still exists on volume."

    return True, "Volume labels are correct."


def verify_pvc_annotations(
    core_v1: client.CoreV1Api,
    pvc_name: str,
    namespace: str,
    expected_secret_name: str,
    expected_secret_key: str,
    expected_secret_namespace: str,
) -> Tuple[bool, str]:
    """Verify annotations on a PersistentVolumeClaim."""
    try:
        pvc = core_v1.read_namespaced_persistent_volume_claim(name=pvc_name, namespace=namespace)
        annotations = pvc.metadata.annotations or {}

        if "px/vault-namespace" in annotations:
            return False, "'px/vault-namespace' annotation was not removed."

        if annotations.get("px/secret-name") != expected_secret_name:
            return (
                False,
                f"'px/secret-name' annotation has incorrect value: {annotations.get('px/secret-name')}",
            )

        if annotations.get("px/secret-key") != expected_secret_key:
            return (
                False,
                f"'px/secret-key' annotation has incorrect value: {annotations.get('px/secret-key')}",
            )

        if annotations.get("px/secret-namespace") != expected_secret_namespace:
            return (
                False,
                f"'px/secret-namespace' annotation has incorrect value: {annotations.get('px/secret-namespace')}",
            )

        return True, "PVC annotations are correct."
    except ApiException as e:
        return False, f"API error checking PVC: {e.reason}"
    except Exception as e:
        return False, f"Unexpected error checking PVC: {e}"


def run_verification(
    core_v1: client.CoreV1Api,
    export_data: Dict[str, List[Dict[str, Any]]],
    px_namespace: str,
) -> List[VerificationResult]:
    """Runs all verification checks for the PVCs in the export data."""
    init_result = initialize_pvc_vault_environment(core_v1, px_namespace)
    if not init_result:
        console.print("[bold red]Failed to initialize Portworx environment. Aborting.[/bold red]")
        sys.exit(1)
    _, _, px_pod, effective_env_vars = init_result

    all_results = []
    with console.status("[bold green]Verifying migration...") as status:
        for namespace, pvc_list in export_data.items():
            for pvc_entry in pvc_list:
                pvc_name = pvc_entry.get("pvc", "unknown")
                status.update(f"Verifying {namespace}/{pvc_name}...")

                result = VerificationResult(pvc_name, namespace)
                validated_entry = validate_pvc_entry(pvc_entry)

                if not validated_entry:
                    result.add_check(
                        "Initial Validation", False, "Skipped due to invalid data in export file."
                    )
                    all_results.append(result)
                    continue

                normalized_secret_name, _ = normalize_secret_name(
                    validated_entry["secret_key"], validated_entry["pvc_name"]
                )

                # 1. Verify K8s Secret
                success, msg = verify_kubernetes_secret(
                    core_v1,
                    normalized_secret_name,
                    validated_entry["secret_context"],
                    validated_entry["secret_key"],
                    validated_entry["encryption_key"],
                )
                result.add_check("Kubernetes Secret", success, msg)

                # 2. Verify Portworx Volume Labels
                success, msg = verify_portworx_volume_labels(
                    validated_entry["pv_name"],
                    normalized_secret_name,
                    px_namespace,
                    px_pod,
                    effective_env_vars,
                    core_v1,
                )
                result.add_check("Portworx Volume Labels", success, msg)

                # 3. Verify PVC Annotations
                success, msg = verify_pvc_annotations(
                    core_v1,
                    validated_entry["pvc_name"],
                    namespace,
                    normalized_secret_name,
                    validated_entry["secret_key"],
                    validated_entry["secret_context"],
                )
                result.add_check("PVC Annotations", success, msg)

                all_results.append(result)

    return all_results


def display_results(results: List[VerificationResult]):
    """Displays the verification results in a table on the console."""
    console.print("\n[bold]Migration Verification Summary[/bold]")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Namespace", style="dim")
    table.add_column("PVC")
    table.add_column("Overall Status")
    table.add_column("Details")

    success_count = 0
    failed_count = 0

    for result in results:
        if result.overall_status == "SUCCESS":
            status_style = "green"
            success_count += 1
        else:
            status_style = "bold red"
            failed_count += 1

        details = ""
        for check in result.checks:
            icon = "[green]✓[/green]" if check["success"] else "[red]✗[/red]"
            details += f"{icon} {check['name']}: {check['message']}\n"

        table.add_row(
            result.namespace,
            result.pvc_name,
            f"[{status_style}]{result.overall_status}[/{status_style}]",
            details.strip(),
        )

    console.print(table)
    console.print(f"\nTotal PVCs Verified: {len(results)}")
    console.print(f"[green]Successful: {success_count}[/green]")
    console.print(f"[red]Failed: {failed_count}[/red]")


@click.command()
@click.option(
    "--input",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to the JSON export file from k8s_px_pvc_data_exporter.py",
)
@click.option(
    "--px-namespace",
    default=DEFAULT_PX_NAMESPACE,
    show_default=True,
    help="Namespace for Portworx pods.",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(input: str, px_namespace: str, debug: bool):
    """Verifies the migration of Portworx encryption keys from Vault to Kubernetes Secrets."""
    log_level = logging.DEBUG if debug else logging.INFO
    script_name = os.path.basename(__file__).replace(".py", "")
    setup_logging(level=log_level, script_name=script_name)

    logger.info("Verification script started")

    try:
        export_data = parse_export_data(input)
    except (ValueError, FileNotFoundError) as e:
        console.print(f"[bold red]Error loading export data: {e}[/bold red]")
        sys.exit(1)

    if not load_kube_config_auto():
        console.print("[bold red]Error: Failed to load Kubernetes configuration.[/bold red]")
        sys.exit(1)

    try:
        core_v1 = get_k8s_client("CoreV1Api")
    except Exception as e:
        console.print(f"[bold red]Error initializing Kubernetes client: {e}[/bold red]")
        sys.exit(1)

    results = run_verification(core_v1, export_data, px_namespace)

    display_results(results)

    # Save detailed report
    report_data = {
        "summary": {
            "total": len(results),
            "successful": sum(1 for r in results if r.overall_status == "SUCCESS"),
            "failed": sum(1 for r in results if r.overall_status == "FAILED"),
        },
        "details": [r.to_dict() for r in results],
    }

    import datetime

    from pyplayground.utils.logging_utils import get_project_root

    tmp_dir = os.path.join(get_project_root(), "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(tmp_dir, f"migration_verification_report_{timestamp}.json")

    with open(report_path, "w") as f:
        import json

        json.dump(report_data, f, indent=4)

    console.print(f"\n[bold]Detailed report saved to: {report_path}[/bold]")
    logger.info(f"Verification script finished. Report at {report_path}")

    if any(r.overall_status == "FAILED" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
