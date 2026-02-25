#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validates a Vault Kubernetes auth path by using its configuration to perform a TokenReview.

This script fetches the configuration from a specified Vault Kubernetes auth path,
including the Kubernetes host and CA certificate. It then uses this information
to dynamically configure a Kubernetes client and attempts to validate a
service account token via the TokenReview API.
"""

import json
import logging
import os
import sys
import tempfile
from typing import Any, Dict

import click
import hvac
import requests
from kubernetes import client
from kubernetes.client.rest import ApiException
from rich.console import Console
from rich.panel import Panel
from rich.pretty import Pretty

# Add project root to path to allow imports from pyplayground
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, project_root)

from pyplayground.utils.k8s_utils import get_service_account_jwt, load_kube_config_auto
from pyplayground.utils.logging_utils import setup_logging
from pyplayground.utils.report_utils import save_summary_report
from pyplayground.utils.vault_utils import create_vault_client

logger = logging.getLogger(__name__)


def get_vault_k8s_auth_config(vault_client: hvac.Client, auth_path: str) -> dict:
    """Fetches the configuration for a specific K8s auth path from Vault."""
    config_path = f"auth/{auth_path.strip('/')}/config"
    logger.debug("Reading Vault K8s auth config from: %s", config_path)
    try:
        config_response = vault_client.read(config_path)
        if not config_response or "data" not in config_response:
            raise ValueError(f"No configuration data found at Vault path '{config_path}'")
        return config_response["data"]
    except hvac.exceptions.Forbidden:
        logger.error("Permission denied reading Vault path: %s", config_path)
        raise
    except Exception as e:
        logger.error("Failed to read from Vault path %s: %s", config_path, e)
        raise


def create_custom_k8s_client(k8s_host: str, ca_cert_path: str, reviewer_jwt: str, no_verify_ssl: bool) -> client.AuthenticationV1Api:
    """Creates a Kubernetes client dynamically configured with Vault data."""
    config = client.Configuration.get_default_copy()
    config.host = k8s_host
    config.ssl_ca_cert = ca_cert_path
    config.verify_ssl = not no_verify_ssl
    config.api_key["authorization"] = reviewer_jwt
    config.api_key_prefix["authorization"] = "Bearer"
    return client.AuthenticationV1Api(client.ApiClient(config))


def _perform_ca_pre_check(k8s_host: str, ca_cert_path: str, console: Console):
    """Performs a direct TLS check to validate the CA cert against the K8s host."""
    console.print(f"--> Performing pre-check: Validating CA certificate against [magenta]{k8s_host}[/magenta]...")
    try:
        # Make a simple GET request, telling `requests` to use our temp file as the only trusted CA
        requests.get(k8s_host, verify=ca_cert_path, timeout=15)
        console.print("[green]Success:[/green] Pre-check passed. The CA from Vault is trusted by the Kubernetes API server.")
    except requests.exceptions.SSLError:
        console.print("[bold red]✖ Error: Pre-check FAILED.[/bold red]")
        console.print("  The `kubernetes_ca_cert` stored in Vault does NOT trust the certificate presented by the Kubernetes API server.")
        console.print("  [bold]Common Causes:[/bold]")
        console.print("    - The Kubernetes cluster's certificates have been rotated, but Vault was not updated.")
        console.print("    - The `kubernetes_host` URL points to the wrong cluster.")
        console.print("    - The `kubernetes_ca_cert` in Vault is incorrect or malformed.")
        sys.exit(1)  # Exit immediately, as further steps will fail
    except requests.exceptions.RequestException as e:
        console.print("[bold red]✖ Error: Pre-check FAILED.[/bold red]")
        console.print(f"  An error occurred while trying to connect to {k8s_host}: {e}")
        sys.exit(1)


def _fetch_vault_config(vault_client, auth_path, console):
    """Fetches and validates the K8s auth config from Vault."""
    k8s_auth_config = get_vault_k8s_auth_config(vault_client, auth_path)
    console.print("Success: Successfully connected to Vault.")
    console.print(
        Panel(
            Pretty(k8s_auth_config),
            title=f"[bold]Vault K8s Auth Config for '{auth_path}'[/bold]",
            expand=False,
        )
    )
    k8s_host = k8s_auth_config.get("kubernetes_host")
    ca_cert_pem = k8s_auth_config.get("kubernetes_ca_cert")
    if not k8s_host or not ca_cert_pem:
        console.print("[red]Error:[/red] Vault config is missing 'kubernetes_host' or 'kubernetes_ca_cert'.")
        sys.exit(1)
    return k8s_host, ca_cert_pem


def _fetch_service_account_jwts(
    target_namespace,
    target_service_account,
    reviewer_namespace,
    reviewer_service_account,
    core_v1_api,
    console,
):
    """Fetches JWTs for the target and reviewer service accounts."""
    console.print(f"--> Fetching JWT for target SA [cyan]{target_namespace}/{target_service_account}[/cyan]...")
    target_jwt = get_service_account_jwt(target_namespace, target_service_account, v1_client=core_v1_api)
    if not target_jwt:
        console.print("[red]Error:[/red] Could not retrieve JWT for target SA.")
        sys.exit(1)

    console.print(f"--> Fetching JWT for reviewer SA [cyan]{reviewer_namespace}/{reviewer_service_account}[/cyan]...")
    reviewer_jwt = get_service_account_jwt(reviewer_namespace, reviewer_service_account, v1_client=core_v1_api)
    if not reviewer_jwt:
        console.print("[red]Error:[/red] Could not retrieve JWT for reviewer SA.")
        sys.exit(1)
    return target_jwt, reviewer_jwt


def _perform_token_review(custom_k8s_client, target_jwt, console) -> Dict[str, Any]:
    """Performs the TokenReview API call and prints the results."""
    token_review_spec = client.V1TokenReviewSpec(token=target_jwt)
    token_review = client.V1TokenReview(spec=token_review_spec)

    try:
        # The custom_k8s_client is already the auth_v1 instance
        api_response = custom_k8s_client.create_token_review(token_review)

        console.print("Success: TokenReview API call successful.")
        console.print(
            Panel(
                Pretty(api_response.status.to_dict()),
                title="[bold]TokenReview Status[/bold]",
                expand=False,
            )
        )

        status_dict = api_response.status.to_dict()

        if api_response.status.authenticated:
            console.print("[bold green]---> Validation Successful: Token is authentic.[/bold green]")
            return {"success": True, "status": "Authenticated", "details": status_dict}
        else:
            console.print("[bold red]---> Validation Failed: Token is not authentic.[/bold red]")
            return {"success": False, "status": "Not Authenticated", "details": status_dict}

    except ApiException as e:
        console.print(f"[red]Error during TokenReview:[/red] {e.reason}")
        console.print(Panel(e.body, title="[bold red]API Error Details[/bold red]"))
        return {
            "success": False,
            "status": "API Error",
            "details": {"reason": e.reason, "body": e.body},
        }


@click.command()
@click.option(
    "--vault-namespace",
    required=True,
    envvar="VAULT_NAMESPACE",
    help="Vault namespace where the auth path resides.",
)
@click.option(
    "--auth-path",
    required=True,
    help="The full path of the Kubernetes auth method in Vault (e.g., k8s-a-1).",
)
@click.option(
    "--target-namespace",
    required=True,
    help="The namespace of the target service account whose token will be validated.",
)
@click.option("--target-service-account", required=True, help="The name of the target service account.")
@click.option(
    "--reviewer-namespace",
    help="Namespace of the SA that will perform the TokenReview. Defaults to target-namespace.",
)
@click.option(
    "--reviewer-service-account",
    help="Name of the SA that will perform the TokenReview. Defaults to target-service-account.",
)
@click.option(
    "--no-verify-ssl",
    is_flag=True,
    default=False,
    help="Disable SSL verification for the initial Kubernetes connection.",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(
    vault_namespace: str,
    auth_path: str,
    target_namespace: str,
    target_service_account: str,
    reviewer_namespace: str,
    reviewer_service_account: str,
    no_verify_ssl: bool,
    debug: bool,
):
    """Validates a Vault K8s auth path by performing a live TokenReview."""
    console = Console()
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)

    logger.debug("Starting Kubernetes auth path validation process.")
    # Set default reviewer if not provided
    if not reviewer_namespace:
        reviewer_namespace = target_namespace
    if not reviewer_service_account:
        reviewer_service_account = target_service_account

    temp_ca_file = None
    try:
        # 1. Connect to Vault and get K8s auth config
        console.print(f"--> Connecting to Vault namespace [cyan]{vault_namespace}[/cyan]...")
        vault_client = create_vault_client(namespace=vault_namespace)
        k8s_host, ca_cert_pem = _fetch_vault_config(vault_client, auth_path, console)

        # 2. Save CA cert and perform pre-check
        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".pem") as f:
            f.write(ca_cert_pem)
            temp_ca_file = f.name
        logger.debug("Saved K8s CA cert from Vault to temporary file: %s", temp_ca_file)

        _perform_ca_pre_check(k8s_host, temp_ca_file, console)

        # 3. Connect to K8s with ambient credentials to get service account tokens
        console.print("--> Connecting to Kubernetes with local kubeconfig to fetch SA tokens...")
        if not load_kube_config_auto(verify_ssl=not no_verify_ssl):
            console.print("[red]Error:[/red] Failed to load Kubernetes configuration.")
            sys.exit(1)
        core_v1_api = client.CoreV1Api()
        console.print("Success: Successfully connected to Kubernetes.")

        # 4. Get JWTs for target and reviewer SAs
        target_jwt, reviewer_jwt = _fetch_service_account_jwts(
            target_namespace,
            target_service_account,
            reviewer_namespace,
            reviewer_service_account,
            core_v1_api,
            console,
        )

        # 5. Create the custom K8s client and perform TokenReview
        console.print(f"--> Performing TokenReview against [magenta]{k8s_host}[/magenta]...")
        custom_k8s_client = create_custom_k8s_client(k8s_host, temp_ca_file, reviewer_jwt, no_verify_ssl)
        review_result = _perform_token_review(custom_k8s_client, target_jwt, console)

        # Generate and save summary report
        summary_data = {
            "Vault Namespace": vault_namespace,
            "Auth Path": auth_path,
            "Target Service Account": f"{target_namespace}/{target_service_account}",
            "Reviewer Service Account": f"{reviewer_namespace}/{reviewer_service_account}",
            "Kubernetes Host": k8s_host,
            "Validation Status": review_result.get("status", "Unknown"),
            "Authenticated": review_result.get("success", False),
            "Details": json.dumps(review_result.get("details"), indent=2),
        }

        report_title = f"K8s Auth Path Validation Summary for {auth_path}"
        save_summary_report(
            summary_data,
            report_title=report_title,
            script_name=script_base_name,
        )

        if not review_result["success"]:
            sys.exit(1)

    except (ValueError, hvac.exceptions.VaultError) as e:
        console.print(f"\n[bold red]✖ Validation Failed: A critical error occurred: {e}[/bold red]")
        logger.error("A critical error occurred during validation.", exc_info=debug)
        sys.exit(1)
    finally:
        # 6. Clean up the temporary CA file
        if temp_ca_file and os.path.exists(temp_ca_file):
            os.remove(temp_ca_file)
            logger.debug("Cleaned up temporary CA file: %s", temp_ca_file)


if __name__ == "__main__":
    main()
