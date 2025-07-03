#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lists all PX-Backup backups from the specified PX-Backup instance, similar to the pxbackup_list_all_backups.yml playbook."""

import logging
import os  # Import os module
import re  # Import re at the top level
from typing import Any, Dict, List, Optional

import click
import requests
import urllib3
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from pyplayground.utils.logging_utils import setup_logging  # Import the new logging setup function
from pyplayground.utils.px_api import PXBackupClient, generate_token  # Import shared utilities
from pyplayground.utils.report_utils import (  # Add import for the new function
    save_inspect_backup_report,
)

# Disable SSL warnings - due to self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Logging Setup ---
logger = logging.getLogger(__name__)
# Basic logging configuration (can be enhanced) - Removed basicConfig
# logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load environment variables from .env file, if it exists
load_dotenv()


# --- Helper Functions for Main Logic ---


def _handle_authentication(
    token: Optional[str],
    auth_url: Optional[str],
    client_id: str,
    username: Optional[str],
    password: Optional[str],
    validate_certs: bool,
) -> str:
    """Handles token retrieval or generation.

    Returns:
        The authentication token.

    Raises:
        click.ClickException: If authentication fails.
    """
    if token:
        logger.info("Using provided authentication token.")
        return token

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
        raise click.ClickException(
            f"Error: Token not provided, and missing required options for token generation: {', '.join(missing_auth)}"
        )
    try:
        generated_token = generate_token(auth_url, client_id, username, password, validate_certs)
        click.echo("Successfully generated authentication token.")
        return generated_token
    except (requests.exceptions.RequestException, ValueError) as auth_err:
        raise click.ClickException(
            f"[bold red]Authentication Error:[/bold red] Failed to generate token: {auth_err}"
        )


def _run_list_operation(
    client: PXBackupClient,
    org_id: str,
    cluster_name_filter: Optional[str],
    cluster_uid_filter: Optional[str],
) -> None:
    """Executes the list operation: fetches and displays backups.

    Raises:
        requests.exceptions.RequestException: If API calls fail.
    """
    console = Console()
    # 1. Fetch all clusters
    all_clusters_raw = fetch_clusters(client, org_id)

    # 2. Filter clusters
    matched_clusters = filter_clusters(all_clusters_raw, cluster_name_filter, cluster_uid_filter)

    if not matched_clusters:
        console.print(
            f"[yellow]No clusters found matching the criteria (Name: '{cluster_name_filter}', UID: '{cluster_uid_filter}').[/yellow]"
        )
        return

    console.print(f"Found {len(matched_clusters)} cluster(s) matching criteria:")
    for cluster in matched_clusters:
        console.print(f"- {cluster.get('name', 'N/A')} ({cluster.get('uid', 'N/A')})")
    console.print("-" * 20)

    # 3. Fetch backups for each matched cluster
    all_backups = []
    fetch_errors = 0
    for cluster_info in matched_clusters:
        try:
            cluster_backups = fetch_backups_for_cluster(client, org_id, cluster_info)
            all_backups.extend(cluster_backups)
        except requests.exceptions.RequestException:
            console.print(
                f"[red]Error fetching backups for cluster {cluster_info.get('name', 'N/A')}. Skipping.[/red]"
            )
            fetch_errors += 1
            continue

    # 4. Display list results
    console.print(f"\nTotal Backups Found: {len(all_backups)}")
    if fetch_errors > 0:
        console.print(
            f"[yellow]Note: Failed to fetch backups for {fetch_errors} cluster(s).[/yellow]"
        )

    if not all_backups:
        return

    _display_backup_list(all_backups)


def _display_backup_list(backups: List[Dict[str, Any]]) -> None:
    """Displays the list of backups in a formatted table.

    Args:
        backups: A list of backup dictionaries.
    """
    if not backups:
        # Already handled in _run_list_operation, but good to double-check
        return

    console = Console()

    # Calculate max name length
    max_name_len = 0
    try:
        backup_names = [backup.get("metadata", {}).get("name", "") for backup in backups]
        backup_names = [name for name in backup_names if name]
        if backup_names:
            max_name_len = max(len(name) for name in backup_names)
    except Exception as e:
        logger.warning(f"Could not calculate max backup name length: {e}", exc_info=False)
        max_name_len = 30  # Fallback

    name_col_width = max(max_name_len + 2, 20)

    table = Table(title="PX-Backup Backups", show_header=True, header_style="bold magenta")
    table.add_column("Name", style="dim", width=name_col_width, overflow="fold")
    table.add_column("UID", width=36)
    table.add_column("Cluster")
    table.add_column("Backup Location")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Created Time", overflow="fold")

    # Sort backups by creation time (descending) if possible
    try:
        backups.sort(key=lambda b: b.get("metadata", {}).get("create_time", ""), reverse=True)
    except Exception:
        logger.warning("Could not sort backups by creation time.", exc_info=False)

    # Populate table rows
    for backup in backups:
        metadata = backup.get("metadata", {})
        backup_info = backup.get("backup_info", {})
        cluster_ref = backup_info.get("cluster_ref", {})
        location_ref = backup_info.get("backup_location_ref", {})
        backup_type_info = backup_info.get("backup_type", {})
        status_info = backup_info.get("status", {})

        backup_type_str = (
            backup_type_info.get("type", "N/A") if isinstance(backup_type_info, dict) else "N/A"
        )
        status_str = status_info.get("status", "N/A") if isinstance(status_info, dict) else "N/A"

        table.add_row(
            metadata.get("name", "N/A"),
            metadata.get("uid", "N/A"),
            cluster_ref.get("name", "N/A"),
            location_ref.get("name", "N/A"),
            backup_type_str,
            status_str,
            metadata.get("create_time", "N/A"),
        )

    console.print(table)


def _run_inspect_operation(
    client: PXBackupClient,
    org_id: str,
    backup_name: str,
    backup_uid: str,
    script_base_name: str,
) -> None:
    """Executes the inspect operation: fetches and displays backup details.

    Raises:
        click.ClickException: If required args are missing or backup not found.
        requests.exceptions.RequestException: If API calls fail.
    """
    console = Console()  # Need console for output and potential errors
    if not backup_name or not backup_uid:
        raise click.ClickException(
            "Error: --backup-name and --backup-uid are required for the 'inspect' operation."
        )

    try:
        backup_details = inspect_backup(client, org_id, backup_name, backup_uid)
        console.print(f"Details for Backup: {backup_name} (UID: {backup_uid})")

        # Create table for detailed output
        table = Table(
            title=f"Backup Details: {backup_name}",
            show_header=False,
            box=None,
            padding=(0, 2),
        )
        table.add_column("Field", style="bold cyan")
        table.add_column("Value")

        # Extract data
        metadata = backup_details.get("metadata", {})
        backup_info = backup_details.get("backup_info", {})
        cluster_ref = backup_info.get("cluster_ref", {})
        location_ref = backup_info.get("backup_location_ref", {})
        backup_type_info = backup_info.get("backup_type", {})
        status_info = backup_info.get("status", {})
        schedule_ref = backup_info.get("schedule_ref", {})
        namespaces = backup_info.get("namespaces", [])
        volumes = backup_info.get("volumes", [])

        backup_type_str = (
            backup_type_info.get("type", "N/A") if isinstance(backup_type_info, dict) else "N/A"
        )
        status_str = status_info.get("status", "N/A") if isinstance(status_info, dict) else "N/A"

        # Populate main details table
        table.add_row("Name:", metadata.get("name", "N/A"))
        table.add_row("UID:", metadata.get("uid", "N/A"))
        table.add_row("Status:", status_str)
        table.add_row("Backup Type:", backup_type_str)
        table.add_row("Cluster:", cluster_ref.get("name", "N/A"))
        table.add_row("Backup Location:", location_ref.get("name", "N/A"))
        table.add_row("Namespace Count:", str(len(namespaces)))
        table.add_row("Created Time:", metadata.get("create_time", "N/A"))
        table.add_row("Start Time:", backup_info.get("start_time", "N/A"))
        table.add_row("Completion Time:", backup_info.get("completion_time", "N/A"))
        schedule_name = schedule_ref.get("name")
        if schedule_name:
            table.add_row("Schedule Name:", schedule_name)

        # Add Volume Status Summary
        if volumes:
            from collections import Counter

            volume_statuses = Counter(
                vol.get("status", {}).get("status", "Unknown") for vol in volumes
            )
            table.add_row("", "")
            table.add_row("[bold]Volume Status Summary:[/bold]", "")
            for status, count in sorted(volume_statuses.items()):
                table.add_row(f"  {status}:", str(count))
        else:
            table.add_row("Volumes:", "0")

        console.print(table)

        # Save Detailed Inspect Report
        save_inspect_backup_report(
            backup_details=backup_details,
            script_name=script_base_name,
        )

        # Create and Print Detailed Volume Table
        if volumes:
            volume_table = Table(
                title="Included Volumes",
                show_header=True,
                header_style="bold magenta",
                padding=(0, 1),
            )
            volume_table.add_column("Name", style="dim", overflow="fold")
            volume_table.add_column("Namespace")
            volume_table.add_column("PVC")
            volume_table.add_column("Status")
            volume_table.add_column("Reason", overflow="fold")

            status_order = {
                "Pending": 0,
                "Failed": 1,
                "InProgress": 2,
                "Successful": 3,
                "Unknown": 4,
            }

            def get_status_sort_key(volume):
                status = volume.get("status", {}).get("status", "Unknown")
                return status_order.get(status, 99)

            sorted_volumes = sorted(volumes, key=get_status_sort_key)

            for vol in sorted_volumes:
                vol_status_info = vol.get("status", {})
                vol_status = vol_status_info.get("status", "Unknown")
                vol_reason = vol_status_info.get("reason", "")

                volume_table.add_row(
                    vol.get("name", "N/A"),
                    vol.get("namespace", "N/A"),
                    vol.get("pvc", "N/A"),
                    vol_status,
                    vol_reason,
                )
            console.print("")
            console.print(volume_table)

    except ValueError as e:
        raise click.ClickException(f"[bold red]Error:[/bold red] {e}")


# --- API Client Functions (Moved from original main logic, can be further refactored) ---
# These interact directly with the client object


def fetch_clusters(client: PXBackupClient, org_id: str) -> List[Dict[str, Any]]:
    """Fetches the list of all clusters for the given organization.

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
        # Parameters like include_secrets are not used by default, matching playbook
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


def _get_matching_cluster_info(
    cluster: Dict[str, Any], name_pattern: Optional[str], uid: Optional[str]
) -> Optional[Dict[str, str]]:
    """Checks if a single cluster matches the given filters.

    Args:
        cluster: The cluster dictionary.
        name_pattern: Regex pattern to match cluster name.
        uid: Exact UID to match cluster UID.

    Returns:
        A dictionary with 'name' and 'uid' if it matches, otherwise None.
    """
    metadata = cluster.get("metadata", {})
    cluster_name = metadata.get("name")
    cluster_uid = metadata.get("uid")

    if not cluster_name or not cluster_uid:
        logger.warning(f"Skipping cluster due to missing name or UID: {metadata}")
        return None

    match_info = {"name": cluster_name, "uid": cluster_uid}

    # Check UID first if provided
    if uid and cluster_uid == uid:
        logger.debug(f"Matched cluster by UID: {cluster_name} ({cluster_uid})")
        return match_info

    # Check name pattern if provided (only if UID didn't match or wasn't provided)
    if name_pattern:
        try:
            if re.match(name_pattern, cluster_name):
                logger.debug(
                    f"Matched cluster by name pattern '{name_pattern}': {cluster_name} ({cluster_uid})"
                )
                return match_info
        except re.error as e:
            logger.error(
                f"Invalid regex pattern '{name_pattern}': {e}. Skipping name pattern matching for this cluster."
            )
            # Don't attempt further matching with a bad pattern for this cluster
            return None

    # No match found
    return None


def filter_clusters(
    clusters: List[Dict[str, Any]], name_pattern: Optional[str], uid: Optional[str]
) -> List[Dict[str, Any]]:
    """Filters clusters based on name pattern or UID using a helper function.

    Args:
        clusters: The list of clusters to filter.
        name_pattern: Regex pattern to match cluster name.
        uid: Exact UID to match cluster UID.

    Returns:
        A list of matched cluster dictionaries, each containing 'name' and 'uid'.
    """
    if not name_pattern and not uid:
        logger.info("No cluster name or UID filter provided, using all clusters.")
        # Ensure metadata and required fields exist before adding
        return [
            {"name": c.get("metadata", {}).get("name"), "uid": c.get("metadata", {}).get("uid")}
            for c in clusters
            if c.get("metadata", {}).get("name") and c.get("metadata", {}).get("uid")
        ]

    matched = []
    for cluster in clusters:
        match_result = _get_matching_cluster_info(cluster, name_pattern, uid)
        if match_result:
            # Avoid adding duplicates if the input list itself had duplicates processed
            if match_result not in matched:
                matched.append(match_result)

    logger.info(f"Filtered down to {len(matched)} clusters.")
    return matched


def fetch_backups_for_cluster(
    client: PXBackupClient, org_id: str, cluster_info: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Fetches backups for a specific cluster.

    Args:
        client: The initialized PXBackupClient.
        org_id: The organization ID.
        cluster_info: Dictionary containing 'name' and 'uid' of the cluster.

    Returns:
        A list of backup dictionaries for the cluster.

    Raises:
        requests.exceptions.RequestException: If the API call fails.
    """
    cluster_name = cluster_info.get("name")
    cluster_uid = cluster_info.get("uid")
    logger.info(f"Fetching backups for cluster: {cluster_name} ({cluster_uid})")

    # Parameters match the 'enumerate_backups' function in the backup module
    params = {
        "enumerate_options.cluster_name_filter": cluster_name,
        "enumerate_options.cluster_uid_filter": cluster_uid,
        # Add other potential filters from playbook/module args if needed later
        # 'enumerate_options.max_objects': ...,
        # 'enumerate_options.include_detailed_resources': ...,
        # 'enumerate_options.name_filter': ...,
        # ... etc
    }
    # Remove None values from params
    params = {k: v for k, v in params.items() if v is not None}

    # Endpoint confirmed from backup.py's enumerate_backups function
    endpoint = f"v1/backup/{org_id}"
    try:
        response = client.make_request("GET", endpoint, params=params)
        backups = response.get("backups", [])
        if not isinstance(backups, list):
            logger.warning(
                f"API response for backups for cluster {cluster_name} was not a list: {type(backups)}. Returning empty list."
            )
            return []
        logger.info(f"Fetched {len(backups)} backups for cluster {cluster_name}.")
        return backups
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch backups for cluster {cluster_name}: {e}")
        raise  # Re-raise exception


def inspect_backup(
    client: PXBackupClient, org_id: str, backup_name: str, backup_uid: str
) -> Dict[str, Any]:
    """Fetches details for a specific backup.

    Args:
        client: The initialized PXBackupClient.
        org_id: The organization ID.
        backup_name: The name of the backup.
        backup_uid: The UID of the backup.

    Returns:
        A dictionary containing the backup details.

    Raises:
        requests.exceptions.RequestException: If the API call fails.
        ValueError: If the backup is not found or the response is invalid.
    """
    logger.info(f"Fetching details for backup: {backup_name} (UID: {backup_uid})")
    # Endpoint confirmed from backup.py's inspect_backup function
    endpoint = f"v1/backup/{org_id}/{backup_name}"
    params = {"uid": backup_uid}

    try:
        response = client.make_request("GET", endpoint, params=params)
        # The backup module returns the raw response, which might contain the backup details
        # directly or nested under a key like 'backup'. Let's check common patterns.
        if "backup" in response:
            backup_details = response["backup"]
        elif (
            isinstance(response, dict) and response
        ):  # Check if the response itself is the backup dict
            backup_details = response
        else:
            logger.error(f"Unexpected response structure for inspect backup: {response}")
            raise ValueError(
                f"Could not find backup details in response for {backup_name}/{backup_uid}"
            )

        if not backup_details:
            raise ValueError(f"No backup found with name {backup_name} and uid {backup_uid}")

        logger.info(f"Successfully fetched details for backup {backup_name}.")
        return backup_details
    except requests.exceptions.RequestException as e:
        # Check for 404 explicitly
        if hasattr(e, "response") and e.response is not None and e.response.status_code == 404:
            logger.error(f"Backup not found: {backup_name} (UID: {backup_uid}) - API returned 404")
            raise ValueError(f"Backup not found: {backup_name} (UID: {backup_uid})") from e
        logger.error(f"Failed to inspect backup {backup_name}: {e}")
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
    "--no-validate-certs",
    is_flag=True,
    default=False,
    help="Disable SSL certificate validation.",
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
# List Filtering Options
@click.option("--cluster-name", required=False, help="Regex pattern to filter clusters by name.")
@click.option("--cluster-uid", required=False, help="Exact UID to filter clusters by.")
# Inspect Options
@click.option(
    "--backup-name",
    required=False,
    help="Name of the backup to inspect (required for inspect operation).",
)
@click.option(
    "--backup-uid",
    required=False,
    help="UID of the backup to inspect (required for inspect operation).",
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
    backup_name: Optional[str],
    backup_uid: Optional[str],
):
    """Lists PX-Backup backups or inspects a single backup.

    Authenticates using a provided token or generates one using username/password.
    """
    # --- Setup Logging --- #
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)  # Pass script_name
    logger.debug("Logging setup complete.")

    validate_certs = not no_validate_certs

    try:
        # --- Authentication ---
        current_token = _handle_authentication(
            token=token,
            auth_url=auth_url,
            client_id=client_id,
            username=username,
            password=password,
            validate_certs=validate_certs,
        )

        # --- Main Logic ---
        client = PXBackupClient(api_url, current_token, validate_certs)

        if operation == "list":
            _run_list_operation(client, org_id, cluster_name, cluster_uid)

        elif operation == "inspect":
            _run_inspect_operation(client, org_id, backup_name, backup_uid, script_base_name)

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
