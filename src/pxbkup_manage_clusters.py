#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Manages PX-Backup Clusters: listing and inspecting.
"""

import logging
from typing import Any, Dict, List, Optional

import click
import requests
from dotenv import load_dotenv
from rich import print as rprint  # For pretty printing dicts
from rich.console import Console
from rich.table import Table

from utils.logging_utils import setup_logging
from utils.px_api import PXBackupClient, generate_token

# --- Logging Setup ---
logger = logging.getLogger(__name__)
# Basic logging configuration (can be enhanced)
# logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load environment variables from .env file, if it exists
load_dotenv()


# --- Helper Functions ---


def fetch_clusters(client: PXBackupClient, org_id: str) -> List[Dict[str, Any]]:
    """
    Fetches the list of all clusters for the given organization.

    Args:
        client: The initialized PXBackupClient.
        org_id: The organization ID.

    Returns:
        A list of cluster dictionaries.

    Raises:
        requests.exceptions.RequestException: If the API call fails.
    """
    logger.info(f"Fetching clusters for organization ID: {org_id}")
    # Endpoint confirmed from cluster.py's enumerate_clusters function
    endpoint = f"v1/cluster/{org_id}"
    try:
        # Parameters like include_secrets are not used by default
        response = client.make_request("GET", endpoint)
        clusters = response.get("clusters", [])
        if not isinstance(clusters, list):
            logger.warning(
                f"API response for clusters was not a list: {type(clusters)}. Returning empty list."
            )
            return []
        logger.info(f"Successfully fetched {len(clusters)} clusters.")
        return clusters
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch clusters: {e}")
        raise  # Re-raise the exception for handling in main


def inspect_cluster(
    client: PXBackupClient, org_id: str, cluster_name: str, cluster_uid: str, include_secrets: bool
) -> Dict[str, Any]:
    """
    Fetches details for a specific cluster.

    Args:
        client: The initialized PXBackupClient.
        org_id: The organization ID.
        cluster_name: The name of the cluster.
        cluster_uid: The UID of the cluster.
        include_secrets: Whether to include secrets in the output.

    Returns:
        A dictionary containing the cluster details.

    Raises:
        requests.exceptions.RequestException: If the API call fails.
        ValueError: If the cluster is not found or the response is invalid.
    """
    logger.info(f"Fetching details for cluster: {cluster_name} (UID: {cluster_uid})")
    # Endpoint confirmed from cluster.py's inspect_cluster function
    endpoint = f"v1/cluster/{org_id}/{cluster_name}/{cluster_uid}"
    # include_secrets=false is default, matching playbook unless overridden
    params = {"include_secrets": include_secrets}

    try:
        response = client.make_request("GET", endpoint, params=params)
        # cluster.py returns the raw response which seems to be the cluster object itself
        if isinstance(response, dict) and response:
            cluster_details = response
        else:
            logger.error(f"Unexpected response structure for inspect cluster: {response}")
            raise ValueError(
                f"Could not find cluster details in response for {cluster_name}/{cluster_uid}"
            )

        logger.info(f"Successfully fetched details for cluster {cluster_name}.")
        return cluster_details
    except requests.exceptions.RequestException as e:
        # Check for 404 explicitly
        if hasattr(e, "response") and e.response is not None and e.response.status_code == 404:
            logger.error(
                f"Cluster not found: {cluster_name} (UID: {cluster_uid}) - API returned 404"
            )
            raise ValueError(f"Cluster not found: {cluster_name} (UID: {cluster_uid})") from e
        logger.error(f"Failed to inspect cluster {cluster_name}: {e}")
        raise  # Re-raise other request exceptions


# --- Click Command ---
@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
# API/Auth Options
@click.option(
    "--api-url",
    required=True,
    envvar="PX_BACKUP_API_URL",
    help="PX-Backup API URL (e.g., px-backup.example.com). Env: PX_BACKUP_API_URL",
)
@click.option(
    "--org-id",
    required=True,
    envvar="PX_BACKUP_ORG_ID",
    help="Organization ID. Env: PX_BACKUP_ORG_ID",
)
@click.option(
    "--token",
    required=False,
    envvar="PX_BACKUP_TOKEN",
    help="Authentication token (recommended). Env: PX_BACKUP_TOKEN",
)
@click.option(
    "--no-validate-certs", is_flag=True, default=False, help="Disable SSL certificate validation."
)
# Token Generation Options (if --token is not used)
@click.option(
    "--auth-url",
    required=False,
    envvar="PX_AUTH_URL",
    help="Authentication server URL (if generating token). Env: PX_AUTH_URL",
)
@click.option(
    "--client-id",
    default="px-backup",
    show_default=True,
    envvar="PX_CLIENT_ID",
    help="Client ID for authentication (if generating token). Env: PX_CLIENT_ID",
)
@click.option(
    "--username",
    required=False,
    envvar="PX_USERNAME",
    help="Username for authentication (if generating token). Env: PX_USERNAME",
)
@click.option(
    "--password",
    required=False,
    envvar="PX_PASSWORD",
    help="Password for authentication (if generating token). Env: PX_PASSWORD",
    hide_input=True,
)
# Operation Selection
@click.option(
    "--operation",
    type=click.Choice(["list", "inspect"], case_sensitive=False),
    default="list",
    help="Operation to perform.",
)
# Inspect Options
@click.option(
    "--cluster-name",
    required=False,
    help="Name of the cluster to inspect (required for inspect operation).",
)
@click.option(
    "--cluster-uid",
    required=False,
    help="UID of the cluster to inspect (required for inspect operation).",
)
@click.option(
    "--include-secrets",
    is_flag=True,
    default=False,
    help="Include secrets in the output when inspecting a cluster.",
)
# Control Options
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(
    api_url: str,
    org_id: str,
    token: Optional[str],
    no_validate_certs: bool,
    auth_url: Optional[str],
    client_id: str,
    username: Optional[str],
    password: Optional[str],
    operation: str,
    cluster_name: Optional[str],
    cluster_uid: Optional[str],
    debug: bool,
    include_secrets: bool,
):
    """
    Lists PX-Backup clusters or inspects a single cluster.
    Authenticates using a provided token or generates one using username/password.
    """
    # --- Setup Logging ---
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level)
    logger.debug("Logging setup complete.")

    console = Console()
    validate_certs = not no_validate_certs
    current_token = token  # Start with the provided token

    try:
        # --- Authentication ---
        if not current_token:
            logger.info("Token not provided, attempting to generate one using credentials.")
            if not all([auth_url, username, password]):
                missing_auth = [
                    p
                    for p, v in [
                        ("auth-url", auth_url),
                        ("username", username),
                        ("password", password),
                    ]
                    if not v
                ]
                # Use ClickException for error handling
                raise click.ClickException(
                    f"Error: Token not provided, and missing required options for token generation: {', '.join(missing_auth)}"
                )
            try:
                current_token = generate_token(
                    auth_url, client_id, username, password, validate_certs
                )
                click.echo("Successfully generated authentication token.")
            except (requests.exceptions.RequestException, ValueError) as auth_err:
                # Use ClickException for error handling
                raise click.ClickException(
                    f"[bold red]Authentication Error:[/bold red] Failed to generate token: {auth_err}"
                )

        # --- Initialize Client ---
        client = PXBackupClient(api_url, current_token, validate_certs)

        # --- Perform Operation ---
        if operation == "list":
            clusters = fetch_clusters(client, org_id)
            console.print(f"\nTotal Clusters Found: {len(clusters)}")

            if not clusters:
                console.print("[yellow]No clusters found.[/yellow]")
                # No need to exit here, just inform the user
                return  # Exit cleanly if no clusters found

            table = Table(title="PX-Backup Clusters", show_header=True, header_style="bold magenta")
            table.add_column("Name", style="dim", width=30, overflow="fold")
            table.add_column("UID", width=36)
            table.add_column("Status")
            table.add_column("Kubeconfig Source", overflow="fold")  # Added based on observation
            table.add_column("Cloud Type")  # Added based on observation
            table.add_column("Created Time", overflow="fold")

            # Sort clusters by creation time (descending) if possible
            try:
                clusters.sort(
                    key=lambda c: c.get("metadata", {}).get("create_time", ""), reverse=True
                )
            except Exception:
                logger.warning("Could not sort clusters by creation time.", exc_info=False)

            for cluster in clusters:
                metadata = cluster.get("metadata", {})
                status = cluster.get("status", "N/A")  # Status might be top-level or nested
                cluster_info = cluster.get("clusterinfo", {})  # Cluster Info might contain details

                # Determine status string
                status_str = status if isinstance(status, str) else status.get("status", "N/A")

                # Determine kubeconfig source
                kube_source = "N/A"
                if cluster.get("kubeconfig"):
                    kube_source = "Direct Input"  # Indication it was provided
                elif cluster_info.get("service_token"):
                    kube_source = "Service Token"

                table.add_row(
                    metadata.get("name", "N/A"),
                    metadata.get("uid", "N/A"),
                    status_str,
                    kube_source,
                    cluster.get("cloud_type", "N/A"),
                    metadata.get("create_time", "N/A"),
                )

            console.print(table)

        elif operation == "inspect":
            if not cluster_name or not cluster_uid:
                # Use ClickException for error handling
                raise click.ClickException(
                    "Error: --cluster-name and --cluster-uid are required for the 'inspect' operation."
                )

            try:
                # Pass include_secrets flag to the function
                cluster_details = inspect_cluster(
                    client, org_id, cluster_name, cluster_uid, include_secrets
                )
                console.print(f"Details for Cluster: {cluster_name} (UID: {cluster_uid})")
                rprint(cluster_details)  # Pretty print the dictionary
            except ValueError as e:  # Catch the specific error for not found
                # Use ClickException for error handling
                raise click.ClickException(f"[bold red]Error:[/bold red] {e}")

    except requests.exceptions.RequestException as e:
        # Use ClickException for error handling
        raise click.ClickException(f"[bold red]API Request Error:[/bold red] {e}")
    except click.ClickException:
        raise  # Re-raise Click exceptions to let Click handle them
    except Exception as e:
        logger.exception(
            "An unexpected error occurred."
        )  # Log the full traceback for unexpected errors
        # Use ClickException for error handling
        raise click.ClickException(f"[bold red]An unexpected error occurred:[/bold red] {e}")


if __name__ == "__main__":
    main()
