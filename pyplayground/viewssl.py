#!/usr/bin/env python3
"""View SSL certificate.

This script provides functionality to view SSL certificate details.
It includes proper logging and type hints as per project guidelines.
"""
import base64
import logging
import os
from pathlib import Path
from typing import Optional

import certifi
import click
import requests
from kubernetes.config import ConfigException, KubeConfigMerger
from OpenSSL import crypto
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pyplayground.utils.logging_utils import get_logger, setup_logging

# Setup logger instance
logger = get_logger(__name__)


def get_pem_info(pem_content: str) -> Optional[Table]:
    """Parses a PEM-encoded certificate and extracts key details into a Rich Table.

    Args:
        pem_content: A string containing the PEM certificate content.

    Returns:
        A Rich Table containing the certificate's issuer, subject, and validity period,
        or None if parsing fails.
    """
    try:
        cert = crypto.load_certificate(crypto.FILETYPE_PEM, pem_content)
        issuer = ", ".join([f"{k.decode()}={v.decode()}" for k, v in cert.get_issuer().get_components()])
        subject = ", ".join([f"{k.decode()}={v.decode()}" for k, v in cert.get_subject().get_components()])
        valid_from = cert.get_notBefore().decode("utf-8")
        valid_to = cert.get_notAfter().decode("utf-8")

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column()
        table.add_column(style="cyan")
        table.add_row("Issuer:", issuer)
        table.add_row("Subject:", subject)
        table.add_row("Valid From:", f"{valid_from[:4]}-{valid_from[4:6]}-{valid_from[6:8]}")
        table.add_row("Valid To:", f"{valid_to[:4]}-{valid_to[4:6]}-{valid_to[6:8]}")
        return table
    except crypto.Error as e:
        logger.error(f"Failed to parse PEM certificate: {e}")
        return None


def display_cert_panel(console: Console, title: str, path: Optional[str], content: str):
    """Displays certificate information within a formatted Rich Panel.

    Args:
        console: The Rich Console instance for printing.
        title: The title for the panel.
        path: The file path to the certificate bundle, if applicable.
        content: The raw content of the certificate(s).
    """
    info_table = get_pem_info(content)
    path_info = f"[bold]Path:[/] [green]{path}[/]\n\n" if path else ""

    console.print(
        Panel(
            f"{path_info}{info_table if info_table else 'Could not parse certificate details.'}",
            title=title,
            border_style="blue",
            expand=False,
        )
    )


def display_certifi_certs(console: Console):
    """Displays the default CA bundle provided by certifi."""
    try:
        ca_path = certifi.where()
        with open(ca_path, "r") as f:
            content = f.read()
        display_cert_panel(console, "Default SSL CA Bundle (certifi)", ca_path, content)
    except FileNotFoundError:
        logger.error(f"Certifi CA bundle not found at expected path: {certifi.where()}")
    except IOError as e:
        logger.error(f"Error reading certifi CA bundle: {e}")


def display_requests_certs(console: Console):
    """Displays the CA bundle used by the Requests library."""
    try:
        ca_path = requests.utils.DEFAULT_CA_BUNDLE_PATH
        with open(ca_path, "r") as f:
            content = f.read()
        display_cert_panel(console, "Requests Library CA Bundle", ca_path, content)
    except FileNotFoundError:
        logger.error(f"Requests CA bundle not found at expected path: {requests.utils.DEFAULT_CA_BUNDLE_PATH}")
    except IOError as e:
        logger.error(f"Error reading Requests CA bundle: {e}")


def display_kubernetes_certs(console: Console, kube_config_path: Path):
    """Extracts and displays CA certificates from a Kubernetes configuration file.

    Overview:
    This function reads the Kubernetes configuration file and extracts certificate authority
    data from all configured clusters. The CA certificates can be embedded as base64-encoded
    data within the config file or referenced as external files.

    Args:
        console: The Rich Console instance for printing formatted output.
        kube_config_path: The path to the Kubernetes configuration file to process.
    """
    if not kube_config_path.exists():
        logger.error(f"Kubernetes config file not found at: {kube_config_path}")
        return

    try:
        kube_config = KubeConfigMerger(str(kube_config_path))
        clusters = kube_config.config.get("clusters", [])
        for cluster in clusters:
            name = cluster.get("name")
            cluster_data = cluster.get("cluster", {})
            ca_data = cluster_data.get("certificate-authority-data")
            ca_file = cluster_data.get("certificate-authority")

            title = f"Kubernetes Cluster CA: [bold]{name}[/]"
            content, path = None, None

            if ca_data:
                content = base64.b64decode(ca_data).decode("utf-8")
                path = "Embedded in kubeconfig"
            elif ca_file:
                path = ca_file
                try:
                    with open(ca_file, "r") as f:
                        content = f.read()
                except (FileNotFoundError, IOError) as e:
                    logger.error(f"Error reading Kubernetes CA file '{ca_file}': {e}")
                    continue

            if content:
                display_cert_panel(console, title, path, content)
            else:
                logger.warning(f"No CA certificate configured for cluster '{name}'.")

    except (ConfigException, TypeError) as e:
        logger.error(f"Error reading Kubernetes configuration: {e}")


@click.command()
@click.option(
    "--kubeconfig",
    type=click.Path(),
    help="Path to the Kubernetes configuration file. Overrides KUBECONFIG env var.",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(kubeconfig: Optional[str], debug: bool):
    """Displays the CA certificates used by Python's core SSL context (via certifi), the Requests library, and the Kubernetes client library.

    Prerequisites:
        - Python 3.6+
        - `pyopenssl`, `certifi`, `requests`, `python-kubernetes-client`, `rich`, `click` libraries installed.
    """
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, log_format_console="%(message)s")
    console = Console()

    # Determine the Kubernetes config file location
    kube_path = kubeconfig or os.environ.get("KUBECONFIG") or os.path.expanduser("~/.kube/config")
    kube_config_path = Path(kube_path)

    console.rule("[bold]CA Certificate Viewer[/bold]")
    display_certifi_certs(console)
    display_requests_certs(console)
    display_kubernetes_certs(console, kube_config_path)


if __name__ == "__main__":
    main()
