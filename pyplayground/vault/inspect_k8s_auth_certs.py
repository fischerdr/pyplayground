#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inspects SSL certificates configured on Vault Kubernetes auth methods.

This script connects to a Vault instance, iterates through Kubernetes auth
methods within a specified namespace, and inspects their CA certificates.
It extracts certificate details, saves the certificates to files, and
provides additional troubleshooting information for each auth method.
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

import click
import hvac
from cryptography import x509
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.pretty import Pretty
from rich.table import Table

from pyplayground.utils.logging_utils import get_project_root, setup_logging
from pyplayground.utils.vault_utils import create_vault_client, get_auth_methods

# Get a logger instance
logger = logging.getLogger(__name__)


def format_cert_details(cert: x509.Certificate) -> dict:
    """Formats a certificate object into a dictionary of details."""
    subject = cert.subject.rfc4514_string()
    issuer = cert.issuer.rfc4514_string()
    return {
        "subject": subject,
        "issuer": issuer,
        "serial_number": cert.serial_number,
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": cert.not_valid_after_utc.isoformat(),
    }


def parse_pem_bundle(pem_data: bytes) -> list[x509.Certificate]:
    """Parses PEM data and returns a list of certificate objects."""
    return x509.load_pem_x509_certificates(pem_data)


def _get_certificate_info(
    ca_cert_pem_str: Optional[str], namespace: str, path: str, output_dir: str
) -> list[dict]:
    """Extracts, parses, and saves a CA certificate bundle."""
    if not ca_cert_pem_str:
        logger.debug("No certificate data found for auth path '%s'", path)
        return []
    try:
        pem_data = ca_cert_pem_str.encode("utf-8")
        certs = parse_pem_bundle(pem_data)
        if not certs:
            return []

        # Save the raw bundle to a file
        sanitized_namespace = namespace.strip("/").replace("/", "_")
        cert_filename = f"{sanitized_namespace}-{path.replace('/', '_')}.pem"
        cert_filepath = Path(output_dir) / cert_filename
        cert_filepath.write_bytes(pem_data)
        logger.info("Saved certificate bundle for %s to %s", path, cert_filepath)

        # Format details for each certificate
        return [format_cert_details(cert) for cert in certs]
    except Exception as e:
        logger.warning(
            "Could not process certificate for auth path '%s'. Error: %s", path, e, exc_info=True
        )
        return []


def _get_role_count(client: hvac.Client, path: str) -> str:
    """Gets the number of roles for a given auth path."""
    try:
        roles = client.list(f"auth/{path}/role")
        return str(len(roles["data"]["keys"])) if roles and "keys" in roles.get("data", {}) else "0"
    except hvac.exceptions.Forbidden:
        logger.warning("Permission denied to list roles for auth path '%s'", path)
        return "Permission Denied"
    except Exception as e:
        logger.warning("Could not list roles for auth path '%s': %s", path, e)
        return "N/A"


def _process_auth_method(
    client: hvac.Client, method: dict, namespace: str, output_dir: str
) -> list:
    """Processes a single K8s auth method and returns data for the table row."""
    path = method["path"].strip("/")
    try:
        config_path = f"auth/{path}/config"
        config_response = client.read(config_path)
        if not config_response or "data" not in config_response:
            logger.warning("No config data found for auth path '%s'", path)
            return [
                path,
                "No Config Found",
                "N/A",
                "N/A",
                "N/A",
                "N/A",
                "N/A",
                "N/A",
                "N/A",
            ]

        config = config_response["data"]

        logger.debug("Keys in Vault config for path '%s': %s", path, list(config.keys()))

        k8s_host = config.get("kubernetes_host", "N/A")
        ca_cert_pem_str = config.get("kubernetes_ca_cert")

        all_cert_details = _get_certificate_info(
            ca_cert_pem_str, namespace, path, output_dir
        )

        if not ca_cert_pem_str:
            cert_subject = "Not Found"
            cert_issuer, not_before, not_after, serial, cert_count = (
                "N/A",
                "N/A",
                "N/A",
                "N/A",
                "0",
            )
        elif not all_cert_details:
            cert_subject = "Parse Error"
            cert_issuer, not_before, not_after, serial, cert_count = (
                "N/A",
                "N/A",
                "N/A",
                "N/A",
                "N/A",
            )
        else:
            first_cert = all_cert_details[0]
            cert_subject = first_cert.get("subject", "N/A")
            cert_issuer = first_cert.get("issuer", "N/A")
            not_before = first_cert.get("not_before", "N/A")
            not_after = first_cert.get("not_after", "N/A")
            serial = str(first_cert.get("serial_number", "N/A"))
            cert_count = str(len(all_cert_details))

        auth_type = "token_reviewer_jwt" if config.get("token_reviewer_jwt") else "use_env/other"

        role_count = _get_role_count(client, path)

        return [
            path,
            k8s_host,
            cert_subject,
            cert_issuer,
            not_before,
            not_after,
            serial,
            cert_count,
            auth_type,
            role_count,
        ]
    except hvac.exceptions.Forbidden:
        logger.error("Permission denied reading config for auth path '%s'", path)
        return [
            path,
            "Permission Denied",
            "N/A",
            "N/A",
            "N/A",
            "N/A",
            "N/A",
            "N/A",
            "N/A",
        ]
    except Exception as e:
        logger.error("Could not process auth path '%s': %s", path, e, exc_info=True)
        return [path, "Error", str(e), "N/A", "N/A", "N/A", "N/A", "N/A", "N/A"]


def inspect_single_auth_path(
    client: hvac.Client, namespace: str, auth_path: str, output_dir: str, console: Console
) -> None:
    """Inspects a single Kubernetes auth method in detail."""
    console.print(f"Inspecting details for auth path: [bold cyan]{auth_path}[/bold cyan]")
    path = auth_path.strip("/")
    try:
        config_path = f"auth/{path}/config"
        config_response = client.read(config_path)
        if not config_response or "data" not in config_response:
            console.print(f"[bold red]No configuration found for auth path '{path}'[/bold red]")
            return

        config = config_response["data"]
        console.print(
            Panel(Pretty(config), title="[bold]General Configuration[/bold]", expand=False)
        )

        # Certificate Details
        ca_cert_pem_str = config.get("kubernetes_ca_cert")
        all_cert_details = _get_certificate_info(
            ca_cert_pem_str, namespace, path, output_dir
        )
        if all_cert_details:
            total_certs = len(all_cert_details)
            for i, cert_details in enumerate(all_cert_details, 1):
                panel_title = f"[bold]Certificate {i} of {total_certs}[/bold]"
                console.print(
                    Panel(Pretty(cert_details), title=panel_title, expand=False)
                )
        else:
            console.print(
                Panel(
                    "[yellow]No certificate found or failed to parse.[/yellow]",
                    title="[bold]Certificate Details[/bold]",
                )
            )

        # Associated Roles
        try:
            roles_response = client.list(f"auth/{path}/role")
            roles = (
                roles_response["data"]["keys"]
                if roles_response and "keys" in roles_response.get("data", {})
                else []
            )
            if roles:
                console.print(
                    Panel(
                        Pretty(roles),
                        title=f"[bold]Associated Roles ({len(roles)})[/bold]",
                        expand=False,
                    )
                )
            else:
                console.print(
                    Panel(
                        "[yellow]No roles found for this auth path.[/yellow]",
                        title="[bold]Associated Roles (0)[/bold]",
                    )
                )
        except hvac.exceptions.Forbidden:
            console.print(
                Panel(
                    "[red]Permission denied to list roles.[/red]",
                    title="[bold]Associated Roles[/bold]",
                )
            )

    except hvac.exceptions.Forbidden:
        console.print(
            f"[bold red]Permission denied when reading config for auth path '{path}'[/bold red]"
        )
    except Exception as e:
        logger.error("Could not process auth path '%s': %s", path, e, exc_info=True)
        console.print(
            f"[bold red]An error occurred while processing auth path '{path}': {e}[/bold red]"
        )


def inspect_k8s_auth_methods(
    client: hvac.Client, namespace: str, output_dir: str, console: Console
) -> None:
    """Inspects Kubernetes auth methods, extracts certs, and prints a summary table."""
    auth_methods_result = get_auth_methods(client)
    if auth_methods_result.get("errors"):
        for error in auth_methods_result["errors"]:
            logger.error("Error retrieving auth methods: %s", error)
            console.print(f"[bold red]Error retrieving auth methods: {error}[/bold red]")

    auth_methods = auth_methods_result.get("auth_methods", [])
    k8s_auth_methods = [
        method
        for method in auth_methods
        if method.get("type") == "kubernetes"
        and re.match(r"k8s-[a-z]-[0-9]+/?$", method.get("path", ""))
    ]

    if not k8s_auth_methods:
        console.print(
            "[yellow]No Kubernetes auth methods found matching the pattern 'k8s-<zone>-<num>'[/yellow]"
        )
        return

    table = Table(title=f"Kubernetes Auth Methods in Namespace: {namespace}")
    table.add_column("Path", style="cyan")
    table.add_column("K8s Host", style="magenta")
    table.add_column("Cert Subject", style="green")
    table.add_column("Cert Issuer", style="green")
    table.add_column("Not Before", style="blue")
    table.add_column("Not After", style="blue")
    table.add_column("Serial Number", style="yellow")
    table.add_column("Cert Count", style="yellow")
    table.add_column("Auth Type", style="bold")
    table.add_column("Role Count", style="bold")

    for method in k8s_auth_methods:
        row_data = _process_auth_method(client, method, namespace, output_dir)
        table.add_row(*row_data)

    console.print(table)


@click.command()
@click.option(
    "--vault-namespace",
    required=True,
    envvar="VAULT_NAMESPACE",
    help="Vault namespace to inspect. Can also be set via VAULT_NAMESPACE env var.",
)
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(file_okay=False, dir_okay=True, writable=True, resolve_path=True),
    help="Directory to save certificate files. Defaults to '<project_root>/tmp/certificates'.",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
@click.option("--auth-path", default=None, help="Inspect a single auth path in detail.")
def main(
    vault_namespace: str,
    output_dir: Optional[str],
    debug: bool,
    auth_path: Optional[str],
) -> None:
    """Inspects SSL certificates on Vault Kubernetes auth methods for a given namespace."""
    # Setup Logging
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Starting script.")

    console = Console()
    console.print(
        f"Inspecting Kubernetes auth methods in Vault namespace: [bold cyan]{vault_namespace}[/bold cyan]"
    )

    # Determine output directory
    if output_dir is None:
        # Determine project root relative to this script's location
        project_root = get_project_root()
        output_dir = os.path.join(project_root, "tmp", "certificates")

    logger.info("Certificate output directory is set to: %s", output_dir)
    console.print(f"Certificate output directory is set to: [bold green]{output_dir}[/bold green]")

    # Create output directory if it doesn't exist
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    try:
        # Load .env file if it exists
        load_dotenv()
        client = create_vault_client(namespace=vault_namespace)
        if not client.is_authenticated():
            console.print(
                "[bold red]Error: Vault authentication failed. Check VAULT_ADDR and VAULT_TOKEN.[/bold red]"
            )
            return

        if auth_path:
            inspect_single_auth_path(client, vault_namespace, auth_path, output_dir, console)
        else:
            inspect_k8s_auth_methods(client, vault_namespace, output_dir, console)

    except Exception as e:
        logger.error("An unexpected error occurred: %s", e, exc_info=True)
        console.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")

    logger.debug("Script finished.")


if __name__ == "__main__":
    main()
