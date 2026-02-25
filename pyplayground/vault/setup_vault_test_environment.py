#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Setup script for creating Vault test environment with multiple namespaces.

This script creates the necessary Kubernetes namespaces, Vault policies, roles,
and test data for testing Vault Kubernetes authentication across multiple vault namespaces.

Example usage:
    python pyplayground/vault/setup_vault_test_environment.py \
        --namespace "test-namespace" \
        --vault-namespaces "vault-ns1,vault-ns2" \
        --secret-paths "test/secret1,test/secret2" \
        --vault-addr "https://vault.example.com" \
        --vault-token "your-vault-token"
"""

import base64
import logging
import os
import sys
from typing import Dict, List, Optional

import click
import hvac
import urllib3
from kubernetes import client
from kubernetes.client.rest import ApiException
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

# Add project root to path for utils
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from pyplayground.utils.k8s_utils import get_k8s_client, load_kube_config_auto, namespace_exists
from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.vault_utils import create_vault_client

# --- Constants ---
DEFAULT_VAULT_MOUNT_PATH = "kubernetes"
DEFAULT_KV_MOUNT_PATH = "secret"
DEFAULT_POLICY_PREFIX = "test-policy"
DEFAULT_ROLE_PREFIX = "test-role"

# --- Globals ---
console = Console()
logger = get_logger(__name__)

# Disable SSL warnings - due to self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Helper Functions ---


def create_kubernetes_namespace(core_v1_client: client.CoreV1Api, namespace: str) -> bool:
    """Create a Kubernetes namespace if it doesn't exist."""
    try:
        # Check if namespace already exists using utility function
        if namespace_exists(namespace, core_v1_client.api_client):
            logger.info(f"Namespace '{namespace}' already exists.")
            return True

        # Create namespace
        namespace_body = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
        core_v1_client.create_namespace(namespace_body)
        logger.info(f"Successfully created namespace '{namespace}'.")
        return True
    except ApiException as e:
        logger.error(f"Failed to create namespace '{namespace}': {e.reason}", exc_info=True)
        return False


def create_service_account(core_v1_client: client.CoreV1Api, namespace: str, sa_name: str = "vault-auth") -> bool:
    """Create a service account for Vault authentication."""
    try:
        # Check if service account already exists
        try:
            core_v1_client.read_namespaced_service_account(sa_name, namespace)
            logger.info(f"Service account '{sa_name}' already exists in namespace '{namespace}'.")
            return True
        except ApiException as e:
            if e.status != 404:
                raise

        # Create service account
        sa_body = client.V1ServiceAccount(metadata=client.V1ObjectMeta(name=sa_name, namespace=namespace))
        core_v1_client.create_namespaced_service_account(namespace, sa_body)
        logger.info(f"Successfully created service account '{sa_name}' in namespace '{namespace}'.")
        return True
    except ApiException as e:
        logger.error(
            f"Failed to create service account '{sa_name}' in namespace '{namespace}': {e.reason}",
            exc_info=True,
        )
        return False


def create_vault_policy(vault_client: hvac.Client, policy_name: str, secret_path: str, kv_mount_path: str) -> bool:
    """Create a Vault policy for accessing specific secrets."""
    try:
        # Define policy rules
        policy_rules = f"""
path "{kv_mount_path}/data/{secret_path}" {{
    capabilities = ["read"]
}}
path "{kv_mount_path}/metadata/{secret_path}" {{
    capabilities = ["read"]
}}
"""

        # Create or update policy
        vault_client.sys.create_or_update_policy(name=policy_name, policy=policy_rules)
        logger.info(f"Successfully created/updated Vault policy '{policy_name}'.")
        return True
    except Exception as e:
        logger.error(f"Failed to create Vault policy '{policy_name}': {e}", exc_info=True)
        return False


def create_vault_role(
    vault_client: hvac.Client,
    role_name: str,
    policy_name: str,
    namespace: str,
    sa_name: str = "vault-auth",
    mount_path: str = DEFAULT_VAULT_MOUNT_PATH,
) -> bool:
    """Create a Vault role for Kubernetes authentication."""
    try:
        # Configure role
        role_config = {
            "bound_service_account_names": [sa_name],
            "bound_service_account_namespaces": [namespace],
            "policies": [policy_name],
            "ttl": "1h",
        }

        vault_client.auth.kubernetes.create_role(name=role_name, mount_point=mount_path, **role_config)
        logger.info(f"Successfully created Vault role '{role_name}' for namespace '{namespace}'.")
        return True
    except Exception as e:
        logger.error(f"Failed to create Vault role '{role_name}': {e}", exc_info=True)
        return False


def create_test_secret(
    vault_client: hvac.Client,
    secret_path: str,
    secret_data: Dict[str, str],
    kv_mount_path: str = DEFAULT_KV_MOUNT_PATH,
) -> bool:
    """Create a test secret in Vault."""
    try:
        vault_client.secrets.kv.v2.create_or_update_secret(path=secret_path, mount_point=kv_mount_path, secret=secret_data)
        logger.info(f"Successfully created test secret '{secret_path}'.")
        return True
    except Exception as e:
        logger.error(f"Failed to create test secret '{secret_path}': {e}", exc_info=True)
        return False


def create_vault_connection_secret(
    core_v1_client: client.CoreV1Api,
    namespace: str,
    vault_addr: str,
    backend_path: str,
    auth_role: str,
    auth_mount_path: str,
    vault_namespace: Optional[str] = None,
) -> bool:
    """Create a Kubernetes secret with Vault connection information."""
    try:
        # Prepare secret data
        secret_data = {
            "VAULT_ADDR": base64.b64encode(vault_addr.encode()).decode(),
            "VAULT_BACKEND_PATH": base64.b64encode(backend_path.encode()).decode(),
            "VAULT_AUTH_KUBERNETES_ROLE": base64.b64encode(auth_role.encode()).decode(),
            "VAULT_AUTH_MOUNT_PATH": base64.b64encode(auth_mount_path.encode()).decode(),
        }

        if vault_namespace:
            secret_data["VAULT_NAMESPACE"] = base64.b64encode(vault_namespace.encode()).decode()

        # Create secret
        secret_body = client.V1Secret(
            metadata=client.V1ObjectMeta(name="px-vault", namespace=namespace),
            data=secret_data,
            type="Opaque",
        )

        try:
            core_v1_client.create_namespaced_secret(namespace, secret_body)
            logger.info(f"Successfully created Vault connection secret in namespace '{namespace}'.")
        except ApiException as e:
            if e.status == 409:  # Secret already exists
                core_v1_client.replace_namespaced_secret("px-vault", namespace, secret_body)
                logger.info(f"Successfully updated Vault connection secret in namespace '{namespace}'.")
            else:
                raise

        return True
    except ApiException as e:
        logger.error(
            f"Failed to create Vault connection secret in namespace '{namespace}': {e.reason}",
            exc_info=True,
        )
        return False


def setup_single_namespace(
    namespace: str,
    vault_namespace: str,
    secret_path: str,
    vault_client: hvac.Client,
    core_v1_client: client.CoreV1Api,
    vault_addr: str,
    backend_path: str,
    auth_mount_path: str,
    kv_mount_path: str,
) -> Dict[str, bool]:
    """Setup a single namespace with all required components."""
    results = {
        "namespace_created": False,
        "service_account_created": False,
        "policy_created": False,
        "role_created": False,
        "secret_created": False,
        "connection_secret_created": False,
    }

    # Generate names
    policy_name = f"{DEFAULT_POLICY_PREFIX}-{namespace}"
    role_name = f"{DEFAULT_ROLE_PREFIX}-{namespace}"

    # Create Kubernetes namespace
    results["namespace_created"] = create_kubernetes_namespace(core_v1_client, namespace)
    if not results["namespace_created"]:
        return results

    # Create service account
    results["service_account_created"] = create_service_account(core_v1_client, namespace)
    if not results["service_account_created"]:
        return results

    # Create Vault policy
    results["policy_created"] = create_vault_policy(vault_client, policy_name, secret_path, kv_mount_path)
    if not results["policy_created"]:
        return results

    # Create Vault role
    results["role_created"] = create_vault_role(vault_client, role_name, policy_name, namespace, "vault-auth", auth_mount_path)
    if not results["role_created"]:
        return results

    # Create test secret
    test_data = {
        "username": f"test-user-{namespace}",
        "password": f"test-password-{namespace}",
        "database": f"test-db-{namespace}",
        "api_key": f"api-key-{namespace}-{hash(namespace) % 10000:04d}",
    }
    results["secret_created"] = create_test_secret(vault_client, secret_path, test_data, kv_mount_path)
    if not results["secret_created"]:
        return results

    # Create Vault connection secret
    results["connection_secret_created"] = create_vault_connection_secret(
        core_v1_client,
        namespace,
        vault_addr,
        backend_path,
        role_name,
        auth_mount_path,
        vault_namespace,
    )

    return results


def display_setup_results(
    namespace_results: Dict[str, Dict[str, bool]],
    vault_namespaces: List[str],
) -> None:
    """Display setup results in a formatted table."""
    # Create summary table
    from rich.table import Table

    table = Table(title="Vault Test Environment Setup Results", show_header=True, header_style="bold magenta")
    table.add_column("Vault Namespace", style="cyan", no_wrap=True)
    table.add_column("K8s Namespace", style="green")
    table.add_column("Service Account", style="green")
    table.add_column("Vault Policy", style="blue")
    table.add_column("Vault Role", style="blue")
    table.add_column("Test Secret", style="yellow")
    table.add_column("Connection Secret", style="yellow")
    table.add_column("Overall", style="bold")

    for vault_namespace, results in namespace_results.items():
        overall_success = all(results.values())
        overall_status = "[green]✓[/green]" if overall_success else "[red]✗[/red]"

        table.add_row(
            vault_namespace,
            "[green]✓[/green]" if results["namespace_created"] else "[red]✗[/red]",
            "[green]✓[/green]" if results["service_account_created"] else "[red]✗[/red]",
            "[green]✓[/green]" if results["policy_created"] else "[red]✗[/red]",
            "[green]✓[/green]" if results["role_created"] else "[red]✗[/red]",
            "[green]✓[/green]" if results["secret_created"] else "[red]✗[/red]",
            "[green]✓[/green]" if results["connection_secret_created"] else "[red]✗[/red]",
            overall_status,
        )

    console.print(table)
    console.print()

    # Display detailed results for each Vault namespace
    for vault_namespace, results in namespace_results.items():
        panel_title = f"Setup Results for Vault Namespace {vault_namespace}"

        content_lines = [
            f"[bold]Kubernetes Namespace:[/bold] {'[green]Created[/green]' if results['namespace_created'] else '[red]Failed[/red]'}",
            f"[bold]Service Account:[/bold] {'[green]Created[/green]' if results['service_account_created'] else '[red]Failed[/red]'}",
            f"[bold]Vault Policy:[/bold] {'[green]Created[/green]' if results['policy_created'] else '[red]Failed[/red]'}",
            f"[bold]Vault Role:[/bold] {'[green]Created[/green]' if results['role_created'] else '[red]Failed[/red]'}",
            f"[bold]Test Secret:[/bold] {'[green]Created[/green]' if results['secret_created'] else '[red]Failed[/red]'}",
            f"[bold]Connection Secret:[/bold] {'[green]Created[/green]' if results['connection_secret_created'] else '[red]Failed[/red]'}",
        ]

        overall_success = all(results.values())
        status_text = "[green]Success[/green]" if overall_success else "[red]Failed[/red]"
        content_lines.append(f"[bold]Overall Status:[/bold] {status_text}")

        console.print(
            Panel(
                "\n".join(content_lines),
                title=panel_title,
                border_style="bold blue" if overall_success else "bold red",
                expand=False,
            )
        )


# --- Main Command ---


@click.command()
@click.option(
    "--namespace",
    required=True,
    help="Single Kubernetes namespace to create.",
)
@click.option(
    "--vault-namespaces",
    required=True,
    help="Comma-separated list of Vault namespaces to configure.",
)
@click.option(
    "--secret-paths",
    required=True,
    help="Comma-separated list of secret paths to create (must match vault namespaces order).",
)
@click.option(
    "--vault-addr",
    required=True,
    help="Vault server address (e.g., https://vault.example.com).",
)
@click.option(
    "--vault-token",
    required=True,
    help="Vault root token for setup operations.",
)
@click.option(
    "--backend-path",
    default=DEFAULT_KV_MOUNT_PATH,
    show_default=True,
    help="Vault KV mount path for secrets.",
)
@click.option(
    "--auth-mount-path",
    default=DEFAULT_VAULT_MOUNT_PATH,
    show_default=True,
    help="Vault Kubernetes auth mount path.",
)
@click.option(
    "--kv-mount-path",
    default=DEFAULT_KV_MOUNT_PATH,
    show_default=True,
    help="Vault KV secrets engine mount path.",
)
@click.option(
    "--kubeconfig",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the kubeconfig file. If not provided, uses default lookup.",
    envvar="KUBECONFIG",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
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
    vault_namespaces: str,
    secret_paths: str,
    vault_addr: str,
    vault_token: str,
    backend_path: str,
    auth_mount_path: str,
    kv_mount_path: str,
    kubeconfig: Optional[str],
    debug: bool,
    k8s_verify_ssl: bool,
    k8s_ssl_ca_cert: Optional[str],
):
    """Setup script for creating Vault test environment with multiple namespaces."""
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=os.path.basename(__file__).replace(".py", ""))
    logger.info("Starting Vault test environment setup script.")

    # Parse input lists
    vault_namespace_list = [vns.strip() for vns in vault_namespaces.split(",")]
    secret_path_list = [path.strip() for path in secret_paths.split(",")]

    # Validate input lengths
    if len(vault_namespace_list) != len(secret_path_list):
        console.print("[bold red]Error: Vault namespaces and secret paths must have the same number of elements.[/bold red]")
        sys.exit(1)

    console.print(f"[bold blue]Setting up Kubernetes namespace '{namespace}' with {len(vault_namespace_list)} Vault namespace(s)...[/bold blue]")

    # Load Kubernetes configuration
    if not load_kube_config_auto(config_file=kubeconfig, verify_ssl=k8s_verify_ssl, ssl_ca_cert=k8s_ssl_ca_cert):
        console.print("[bold red]Error: Failed to load Kubernetes configuration.[/bold red]")
        sys.exit(1)

    try:
        core_v1 = get_k8s_client("CoreV1Api")
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes API client: {e}", exc_info=True)
        console.print(f"[bold red]Error initializing Kubernetes client: {e}[/bold red]")
        sys.exit(1)

    # Initialize Vault client
    try:
        vault_client = create_vault_client(url=vault_addr, token=vault_token)
        if not vault_client.is_authenticated():
            console.print("[bold red]Error: Failed to authenticate with Vault.[/bold red]")
            sys.exit(1)
        logger.info("Successfully authenticated with Vault.")
    except Exception as e:
        logger.error(f"Failed to initialize Vault client: {e}", exc_info=True)
        console.print(f"[bold red]Error initializing Vault client: {e}[/bold red]")
        sys.exit(1)

    # Setup single Kubernetes namespace with multiple Vault namespaces
    namespace_results = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Setting up Vault namespaces...", total=len(vault_namespace_list))

        for i, (vault_namespace, secret_path) in enumerate(zip(vault_namespace_list, secret_path_list)):
            progress.update(task, description=f"Setting up Vault namespace {vault_namespace}...")

            results = setup_single_namespace(
                namespace,
                vault_namespace,
                secret_path,
                vault_client,
                core_v1,
                vault_addr,
                backend_path,
                auth_mount_path,
                kv_mount_path,
            )
            namespace_results[vault_namespace] = results
            progress.advance(task)

    # Display results
    display_setup_results(namespace_results, vault_namespace_list)

    # Summary
    successful_setups = sum(1 for results in namespace_results.values() if all(results.values()))
    total_setups = len(namespace_results)

    console.print(f"\n[bold]Summary:[/bold] {successful_setups}/{total_setups} Vault namespace(s) setup successfully")

    if successful_setups == total_setups:
        console.print("[bold green]All Vault namespaces setup successfully![/bold green]")
        console.print("\n[bold blue]You can now run the multi-namespace Vault monitor script:[/bold blue]")
        console.print("python pyplayground/vault/multi_namespace_vault_monitor.py \\")
        console.print(f'    --namespaces "{namespace}" \\')
        console.print(f'    --secret-paths "{secret_paths}" \\')
        console.print(f'    --vault-namespaces "{vault_namespaces}"')
        sys.exit(0)
    else:
        console.print(f"[bold red]{total_setups - successful_setups} Vault namespace(s) setup failed.[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
