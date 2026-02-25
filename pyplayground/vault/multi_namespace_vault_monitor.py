#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Enhanced Vault monitoring script for testing Kubernetes authentication across vault namespaces.

This script extends the original test_vault_secret_access.py to support testing
Vault Kubernetes authentication across multiple vault namespaces. It can test different
Vault mount paths, read KV2 secrets, and provide comprehensive monitoring and
reporting capabilities.

Example usage:
    python pyplayground/vault/multi_namespace_vault_monitor.py \
        --namespace "namespace" \
        --secret-paths "secret1,secret2" \
        --vault-namespaces "vault-ns1,vault-ns2" \
        --px-namespace "portworx"
"""

import base64
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import click
import hvac
import urllib3
from kubernetes import client
from kubernetes.client.rest import ApiException
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

# Add project root to path for utils
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from pyplayground.utils.k8s_utils import (
    get_k8s_client,
    get_service_account_jwt,
    load_kube_config_auto,
)
from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.vault_utils import create_vault_client, get_secret, login_with_kubernetes

# --- Constants ---
DEFAULT_PX_NAMESPACE = "portworx"
VAULT_ADDR_SECRET_NAME = "px-vault"
VAULT_ADDR_SECRET_KEY = "VAULT_ADDR"
VAULT_BACKEND_PATH_KEY = "VAULT_BACKEND_PATH"
VAULT_AUTH_ROLE_KEY = "VAULT_AUTH_KUBERNETES_ROLE"
VAULT_AUTH_MOUNT_PATH_KEY = "VAULT_AUTH_MOUNT_PATH"
VAULT_AUTH_NAMESPACE_KEY = "VAULT_NAMESPACE"
VAULT_SA_NAME = "portworx"


# --- Data Classes ---
@dataclass
class TestResult:
    """Represents the result of a single Vault test."""

    namespace: str
    secret_path: str
    vault_namespace: str
    success: bool
    status: str
    data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    auth_success: bool = False
    secret_access_success: bool = False


@dataclass
class VaultConnectionInfo:
    """Represents Vault connection information."""

    addr: str
    backend_path: str
    auth_role: str
    auth_mount_path: str


# --- Globals ---
console = Console()
logger = get_logger(__name__)

# Disable SSL warnings - due to self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Helper Functions ---


def get_vault_connection_info(core_v1_client: client.CoreV1Api, namespace: str) -> Optional[VaultConnectionInfo]:
    """Retrieves Vault connection and auth info from the 'px-vault' secret."""
    logger.debug(f"Attempting to read secret '{VAULT_ADDR_SECRET_NAME}' in namespace '{namespace}'.")
    try:
        secret = core_v1_client.read_namespaced_secret(VAULT_ADDR_SECRET_NAME, namespace)
        secret_data = secret.data

        required_keys = {
            "addr": VAULT_ADDR_SECRET_KEY,
            "backend_path": VAULT_BACKEND_PATH_KEY,
            "auth_role": VAULT_AUTH_ROLE_KEY,
            "auth_mount_path": VAULT_AUTH_MOUNT_PATH_KEY,
        }

        conn_info = {}
        for key, secret_key in required_keys.items():
            value_b64 = secret_data.get(secret_key)
            if not value_b64:
                logger.error(f"Secret '{VAULT_ADDR_SECRET_NAME}' is missing the key '{secret_key}'.")
                return None
            conn_info[key] = base64.b64decode(value_b64).decode("utf-8").strip()

        logger.info("Successfully retrieved Vault connection and auth info.")
        return VaultConnectionInfo(**conn_info)
    except ApiException as e:
        if e.status == 404:
            logger.error(f"Secret '{VAULT_ADDR_SECRET_NAME}' not found in namespace '{namespace}'.")
        else:
            logger.error(f"API error reading Vault connection secret: {e.reason}", exc_info=True)
        return None


# Removed - using get_service_account_jwt from utils instead


def test_vault_authentication(
    vault_conn_info: VaultConnectionInfo,
    sa_jwt: str,
    vault_namespace: str,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Test Vault authentication and return success status, token, and error message."""
    try:
        logger.info(f"Testing Vault authentication for namespace '{vault_namespace}'.")
        vault_client = login_with_kubernetes(
            role=vault_conn_info.auth_role,
            jwt=sa_jwt,
            url=vault_conn_info.addr,
            mount_point=vault_conn_info.auth_mount_path,
            namespace=vault_namespace,
        )
        vault_token = vault_client.token
        if not vault_token:
            return False, None, "Authentication successful but client token is empty."
        return True, vault_token, None
    except Exception as e:
        error_msg = f"Failed to authenticate with Vault: {e}"
        logger.error(error_msg, exc_info=True)
        return False, None, error_msg


def test_vault_secret_access(
    vault_conn_info: VaultConnectionInfo,
    vault_token: str,
    secret_path: str,
    vault_namespace: str,
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """Test access to a specific Vault secret and return success status, data, and error message."""
    try:
        logger.debug(f"Testing access to secret '{secret_path}' in mount '{vault_conn_info.backend_path}' " f"(namespace: {vault_namespace or 'root'}).")
        vault_client = create_vault_client(url=vault_conn_info.addr, token=vault_token, namespace=vault_namespace)

        # Use utility function to get secret
        secret_data = get_secret(vault_client, secret_path, vault_conn_info.backend_path)
        if secret_data:
            return True, secret_data, None
        else:
            return False, None, "Secret found but contains no data."
    except hvac.exceptions.InvalidPath as e:
        error_msg = f"Invalid Vault path '{secret_path}'. Reason: {e}"
        logger.warning(error_msg, exc_info=True)
        return False, None, error_msg
    except hvac.exceptions.Forbidden as e:
        error_msg = f"Vault access forbidden for '{secret_path}'. Reason: {e}"
        logger.warning(error_msg, exc_info=True)
        return False, None, error_msg
    except Exception as e:
        error_msg = f"Error reading Vault secret '{secret_path}': {e}"
        logger.error(error_msg, exc_info=True)
        return False, None, error_msg


def run_single_test(
    namespace: str,
    secret_path: str,
    vault_namespace: str,
    core_v1_client: client.CoreV1Api,
    px_namespace: str,
) -> TestResult:
    """Run a single test for a specific namespace and secret path."""
    logger.info(f"Running test for namespace '{namespace}', secret '{secret_path}', vault namespace '{vault_namespace}'")

    # Initialize result
    result = TestResult(
        namespace=namespace,
        secret_path=secret_path,
        vault_namespace=vault_namespace,
        success=False,
        status="Unknown",
    )

    try:
        # Get Vault connection info
        vault_conn_info = get_vault_connection_info(core_v1_client, px_namespace)
        if not vault_conn_info:
            result.status = "[red]Failed to get Vault connection info[/red]"
            result.error_message = "Could not retrieve Vault connection information from Kubernetes secret"
            return result

        # Get service account JWT
        sa_jwt = get_service_account_jwt(px_namespace, VAULT_SA_NAME, core_v1_client)
        if not sa_jwt:
            result.status = "[red]Failed to get service account JWT[/red]"
            result.error_message = "Could not retrieve service account JWT for Vault authentication"
            return result

        # Test authentication
        auth_success, vault_token, auth_error = test_vault_authentication(vault_conn_info, sa_jwt, vault_namespace)
        result.auth_success = auth_success

        if not auth_success:
            result.status = "[red]Authentication Failed[/red]"
            result.error_message = auth_error
            return result

        # Test secret access
        secret_success, secret_data, secret_error = test_vault_secret_access(vault_conn_info, vault_token, secret_path, vault_namespace)
        result.secret_access_success = secret_success

        if secret_success:
            result.status = "[green]Success[/green]"
            result.data = secret_data
            result.success = True
        else:
            result.status = "[red]Secret Access Failed[/red]"
            result.error_message = secret_error

    except Exception as e:
        logger.error(f"Unexpected error during test: {e}", exc_info=True)
        result.status = "[red]Unexpected Error[/red]"
        result.error_message = f"Unexpected error: {e}"

    return result


def display_results(results: List[TestResult], mask_values: bool = False) -> None:
    """Display test results in a formatted table and detailed panels."""
    # Create summary table
    table = Table(title="Vault Multi-Namespace Test Results", show_header=True, header_style="bold magenta")
    table.add_column("Namespace", style="cyan", no_wrap=True)
    table.add_column("Secret Path", style="green")
    table.add_column("Vault Namespace", style="blue")
    table.add_column("Auth", style="yellow")
    table.add_column("Secret Access", style="yellow")
    table.add_column("Overall Status", style="bold")

    for result in results:
        auth_status = "[green]✓[/green]" if result.auth_success else "[red]✗[/red]"
        secret_status = "[green]✓[/green]" if result.secret_access_success else "[red]✗[/red]"

        table.add_row(
            result.namespace,
            result.secret_path,
            result.vault_namespace,
            auth_status,
            secret_status,
            result.status,
        )

    console.print(table)
    console.print()

    # Display detailed results for each test
    for i, result in enumerate(results, 1):
        panel_title = f"Test {i}: {result.namespace} - {result.secret_path}"

        content_lines = [
            f"[bold]Namespace:[/bold] {result.namespace}",
            f"[bold]Secret Path:[/bold] {result.secret_path}",
            f"[bold]Vault Namespace:[/bold] {result.vault_namespace}",
            f"[bold]Authentication:[/bold] {'[green]Success[/green]' if result.auth_success else '[red]Failed[/red]'}",
            f"[bold]Secret Access:[/bold] {'[green]Success[/green]' if result.secret_access_success else '[red]Failed[/red]'}",
            f"[bold]Overall Status:[/bold] {result.status}",
        ]

        if result.error_message:
            content_lines.append(f"[bold]Error:[/bold] [red]{result.error_message}[/red]")

        if result.data:
            content_lines.append("[bold]Secret Data:[/bold]")
            for key, value in result.data.items():
                display_value = "********" if mask_values else value
                content_lines.append(f"  [bold cyan]{key}:[/bold cyan] {display_value}")
        else:
            content_lines.append("[bold]Secret Data:[/bold] None")

        console.print(
            Panel(
                "\n".join(content_lines),
                title=panel_title,
                border_style="bold blue" if result.success else "bold red",
                expand=False,
            )
        )


# --- Main Command ---


@click.command()
@click.option(
    "--namespace",
    required=True,
    help="Single Kubernetes namespace to test.",
)
@click.option(
    "--secret-paths",
    required=True,
    help="Comma-separated list of secret paths to test (must match vault namespaces order).",
)
@click.option(
    "--vault-namespaces",
    required=True,
    help="Comma-separated list of Vault namespaces to test.",
)
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
    help="Kubernetes namespace for Portworx and where to find Vault credential secrets.",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
@click.option(
    "--mask/--no-mask",
    "mask_values",
    default=True,
    help="Mask/unmask sensitive values in the output. Defaults to masking.",
    show_default=True,
)
@click.option(
    "--k8s-verify-ssl/--k8s-no-verify-ssl",
    "k8s_verify_ssl",
    default=True,
    help="Enable/disable SSL verification for Kubernetes API.",
    show_default=True,
)
@click.option(
    "--k8s-ssl-ca-cert",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a custom CA certificate file for Kubernetes API.",
    default=None,
)
def main(
    namespace: str,
    secret_paths: str,
    vault_namespaces: str,
    kubeconfig: Optional[str],
    px_namespace: str,
    debug: bool,
    mask_values: bool,
    k8s_verify_ssl: bool,
    k8s_ssl_ca_cert: Optional[str],
):
    """Enhanced Vault monitoring script for testing Kubernetes authentication across multiple namespaces."""
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=os.path.basename(__file__).replace(".py", ""))
    logger.info("Starting multi-namespace Vault monitoring script.")

    # Parse input lists
    secret_path_list = [path.strip() for path in secret_paths.split(",")]
    vault_namespace_list = [vns.strip() for vns in vault_namespaces.split(",")]

    # Validate input lengths
    if len(secret_path_list) != len(vault_namespace_list):
        console.print("[bold red]Error: Secret paths and Vault namespaces must have the same number of elements.[/bold red]")
        sys.exit(1)

    console.print(f"[bold blue]Testing Kubernetes namespace '{namespace}' with {len(vault_namespace_list)} Vault namespace(s)...[/bold blue]")

    if not load_kube_config_auto(config_file=kubeconfig, verify_ssl=k8s_verify_ssl, ssl_ca_cert=k8s_ssl_ca_cert):
        console.print("[bold red]Error: Failed to load Kubernetes configuration.[/bold red]")
        sys.exit(1)

    try:
        core_v1 = get_k8s_client("CoreV1Api")
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes API client: {e}", exc_info=True)
        console.print(f"[bold red]Error initializing Kubernetes client: {e}[/bold red]")
        sys.exit(1)

    # Run tests with progress indicator
    results = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Running Vault tests...", total=len(vault_namespace_list))

        for i, (secret_path, vault_namespace) in enumerate(zip(secret_path_list, vault_namespace_list)):
            progress.update(task, description=f"Testing Vault namespace {vault_namespace}...")
            result = run_single_test(namespace, secret_path, vault_namespace, core_v1, px_namespace)
            results.append(result)
            progress.advance(task)

    # Display results
    display_results(results, mask_values)

    # Summary
    successful_tests = sum(1 for result in results if result.success)
    total_tests = len(results)

    console.print(f"\n[bold]Summary:[/bold] {successful_tests}/{total_tests} tests passed")

    if successful_tests == total_tests:
        console.print("[bold green]All tests passed![/bold green]")
        sys.exit(0)
    else:
        console.print(f"[bold red]{total_tests - successful_tests} test(s) failed.[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
