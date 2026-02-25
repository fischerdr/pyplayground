#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Test script to check a specific Vault secret path using K8s auth.

This script provides a streamlined way to debug Vault access by focusing on a
single secret. It authenticates to Vault using the same Kubernetes service
account method as the main PVC checker script but targets a specific secret
path provided via the command line.

Example usage:
    python pyplayground/k8s/test_vault_secret_access.py \
        --secret-path "my/secret/path" \
        --vault-namespace "my-vault-ns" \
        --px-namespace "portworx"
"""

import base64
import logging
import os
import sys
from typing import Any, Dict, Optional

import click
import hvac
import urllib3
from kubernetes import client
from kubernetes.client.rest import ApiException
from rich.console import Console
from rich.panel import Panel

# Add project root to path for utils
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from pyplayground.utils.k8s_utils import get_k8s_client, load_kube_config_auto
from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.vault_utils import create_vault_client, login_with_kubernetes

# --- Constants ---
# These are copied from the main script to ensure consistency
DEFAULT_PX_NAMESPACE = "kube-system"
VAULT_ADDR_SECRET_NAME = "px-vault"
VAULT_ADDR_SECRET_KEY = "VAULT_ADDR"
VAULT_BACKEND_PATH_KEY = "VAULT_BACKEND_PATH"
VAULT_AUTH_ROLE_KEY = "VAULT_AUTH_KUBERNETES_ROLE"
VAULT_AUTH_MOUNT_PATH_KEY = "VAULT_AUTH_MOUNT_PATH"
VAULT_AUTH_NAMESPACE_KEY = "VAULT_NAMESPACE"  # For the auth call
VAULT_SA_NAME = "portworx"

# --- Globals ---
console = Console()
logger = get_logger(__name__)


# Disable SSL warnings - due to self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Helper Functions (Reused from the main script) ---


def get_vault_connection_info(core_v1_client: client.CoreV1Api, namespace: str) -> Optional[Dict[str, str]]:
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
        return conn_info
    except ApiException as e:
        if e.status == 404:
            logger.error(f"Secret '{VAULT_ADDR_SECRET_NAME}' not found in namespace '{namespace}'.")
        else:
            logger.error(f"API error reading Vault connection secret: {e.reason}", exc_info=True)
        return None


def get_service_account_jwt(core_v1_client: client.CoreV1Api, namespace: str) -> Optional[str]:
    """Retrieves an existing K8s service account token (JWT) from a secret."""
    logger.info(f"Searching for an existing secret for SA '{VAULT_SA_NAME}' containing '{VAULT_SA_NAME}-token' in its name.")
    try:
        secrets = core_v1_client.list_namespaced_secret(namespace)
        for secret in secrets.items:
            secret_name = secret.metadata.name
            annotations = secret.metadata.annotations
            if (
                secret.type == "kubernetes.io/service-account-token"
                and annotations
                and annotations.get("kubernetes.io/service-account.name") == VAULT_SA_NAME
                and f"{VAULT_SA_NAME}-token" in secret_name
            ):
                if "token" in secret.data:
                    token_b64 = secret.data["token"]
                    token = base64.b64decode(token_b64).decode("utf-8").strip()
                    logger.info(f"Found and decoded service account JWT from secret '{secret_name}'.")
                    return token
    except ApiException as e:
        logger.error(f"API error listing secrets: {e.reason}", exc_info=True)

    logger.error(f"Could not retrieve token for ServiceAccount '{VAULT_SA_NAME}'.")
    return None


def check_vault_secret(
    vault_addr: str,
    vault_token: str,
    secret_path: str,
    mount_point: str,
    vault_namespace: Optional[str] = None,
) -> tuple[str, Optional[Dict[str, Any]]]:
    """Checks for a secret in Vault and returns its status and data."""
    logger.debug(f"Checking Vault for secret at path '{secret_path}' in mount '{mount_point}' (namespace: {vault_namespace or 'root'}).")
    status = "Unknown"
    data = None
    try:
        vault_client = create_vault_client(url=vault_addr, token=vault_token, namespace=vault_namespace)
        response = vault_client.secrets.kv.v2.read_secret_version(path=secret_path, mount_point=mount_point)
        if response and "data" in response and "data" in response["data"]:
            status = "[green]Found[/green]"
            data = response["data"]["data"]
        else:
            status = "[yellow]Found (No Data)[/yellow]"
    except hvac.exceptions.InvalidPath as e:
        logger.warning(f"Invalid Vault path '{secret_path}'. Reason: {e}", exc_info=True)
        status = "[red]Not Found[/red]"
    except hvac.exceptions.Forbidden as e:
        logger.warning(f"Vault access forbidden for '{secret_path}'. Reason: {e}", exc_info=True)
        status = "[red]Forbidden[/red]"
    except Exception as e:
        logger.error(f"Error reading Vault secret '{secret_path}': {e}", exc_info=True)
        status = f"[red]Error: {type(e).__name__}[/red]"
    return status, data


# --- Main Command ---


@click.command()
@click.option("--secret-path", required=True, help="The full path of the secret to check in Vault.")
@click.option("--vault-namespace", required=True, help="The Vault namespace where the secret resides.")
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
    default=False,
    help="Mask/unmask sensitive values in the output. Defaults to not masking.",
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
    secret_path: str,
    vault_namespace: str,
    kubeconfig: Optional[str],
    px_namespace: str,
    debug: bool,
    mask_values: bool,
    k8s_verify_ssl: bool,
    k8s_ssl_ca_cert: Optional[str],
):
    """A targeted script to test access to a single Vault secret path."""
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=os.path.basename(__file__).replace(".py", ""))
    logger.info("Starting Vault secret access test script.")

    if not load_kube_config_auto(config_file=kubeconfig, verify_ssl=k8s_verify_ssl, ssl_ca_cert=k8s_ssl_ca_cert):
        console.print("[bold red]Error: Failed to load Kubernetes configuration.[/bold red]")
        sys.exit(1)

    try:
        core_v1 = get_k8s_client("CoreV1Api")
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes API client: {e}", exc_info=True)
        console.print(f"[bold red]Error initializing Kubernetes client: {e}[/bold red]")
        sys.exit(1)

    vault_conn_info = get_vault_connection_info(core_v1, px_namespace)
    if not vault_conn_info:
        console.print("[bold red]Failed to retrieve Vault connection info from Kubernetes. Exiting.[/bold red]")
        sys.exit(1)

    sa_jwt = get_service_account_jwt(core_v1, px_namespace)
    if not sa_jwt:
        console.print("[bold red]Failed to retrieve Service Account JWT for Vault auth. Exiting.[/bold red]")
        sys.exit(1)

    try:
        logger.info("Authenticating to Vault using Kubernetes auth method.")
        vault_client = login_with_kubernetes(
            role=vault_conn_info["auth_role"],
            jwt=sa_jwt,
            url=vault_conn_info["addr"],
            mount_point=vault_conn_info["auth_mount_path"],
            namespace=vault_namespace,  # Use the namespace from CLI args for auth
        )
        vault_token = vault_client.token
        if not vault_token:
            raise ValueError("Authentication successful but client token is empty.")
    except Exception as e:
        logger.error(f"Failed to authenticate with Vault: {e}", exc_info=True)
        console.print(f"[bold red]Failed to authenticate with Vault: {e}[/bold red]")
        sys.exit(1)

    console.print(f"[bold blue]Checking secret:[/bold blue] [green]{secret_path}[/green] in Vault namespace [green]{vault_namespace}[/green]")

    status, data = check_vault_secret(
        vault_addr=vault_conn_info["addr"],
        vault_token=vault_token,
        secret_path=secret_path,
        mount_point=vault_conn_info["backend_path"],
        vault_namespace=vault_namespace,
    )

    output_content = f"[bold]Status:[/bold] {status}\n\n"
    if data:
        # Format the data dictionary into a string for the panel
        data_str = "\n".join(f"  [bold cyan]{key}:[/bold cyan] {'********' if mask_values else value}" for key, value in data.items())
        output_content += f"[bold]Data:[/bold]\n{data_str}"
    else:
        output_content += "[bold]Data:[/bold] None"

    console.print(
        Panel(
            output_content,
            title="Vault Secret Check Result",
            border_style="bold magenta",
            expand=False,
        )
    )

    logger.info("Script finished.")


if __name__ == "__main__":
    main()
