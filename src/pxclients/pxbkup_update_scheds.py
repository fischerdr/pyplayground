#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PX-Backup Schedule Manager.

This script manages PX-Backup schedules by updating their suspend status.
It allows for bulk suspension or resumption of schedules based on command-line arguments.

"""
import logging
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

import click
import requests
import urllib3
from dotenv import load_dotenv
from rich.console import Console

# Import shared utilities
from utils.logging_utils import get_logger, setup_logging
from utils.px_api import PXBackupClient, generate_token

# Disable SSL warnings if necessary (handled by click option)
# urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Logging Setup ---
# Logger will be configured in main based on debug flag
logger = get_logger(__name__)

# Load environment variables from .env file, if it exists
load_dotenv()


# --- Cluster Fetch/Filter Helper Functions ---


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
    endpoint = (
        f"v1/cluster/{org_id}"  # Use relative path convention if applicable for PXBackupClient
    )
    try:
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
        raise


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
            return None

    return None


def filter_clusters(
    clusters: List[Dict[str, Any]], name_pattern: Optional[str], uid: Optional[str]
) -> List[Dict[str, Any]]:
    """Filters clusters based on name pattern or UID.

    Args:
        clusters: The list of clusters to filter.
        name_pattern: Regex pattern to match cluster name.
        uid: Exact UID to match cluster UID.

    Returns:
        A list of matched cluster dictionaries, each containing 'name' and 'uid'.
        Returns all clusters if both name_pattern and uid are None.
    """
    if not name_pattern and not uid:
        logger.info("No cluster name or UID filter provided, using all found clusters.")
        # Extract essential info even when returning all
        return [
            {"name": c.get("metadata", {}).get("name"), "uid": c.get("metadata", {}).get("uid")}
            for c in clusters
            if c.get("metadata", {}).get("name") and c.get("metadata", {}).get("uid")
        ]

    matched = []
    for cluster in clusters:
        match_result = _get_matching_cluster_info(cluster, name_pattern, uid)
        if match_result:
            if match_result not in matched:
                matched.append(match_result)

    logger.info(f"Filtered down to {len(matched)} clusters based on criteria.")
    return matched


# --- Helper Functions ---


def _get_target_cluster(
    client: PXBackupClient,
    org_id: str,
    cluster_name: Optional[str],
    cluster_uid: Optional[str],
) -> Tuple[Optional[str], str]:
    """Fetches and filters clusters to find the target UID and display name.

    Args:
        client: Initialized PXBackupClient.
        org_id: Organization ID.
        cluster_name: Optional cluster name filter (regex).
        cluster_uid: Optional exact cluster UID filter.

    Returns:
        A tuple containing: (target_cluster_uid, target_cluster_display_name)

    Raises:
        click.ClickException: If fetching fails or filtering yields no/multiple results.
    """
    target_cluster_uid: Optional[str] = None
    target_cluster_display_name: str = "all clusters"

    if cluster_name or cluster_uid:
        logger.info("Cluster filter provided, fetching cluster list...")
        all_clusters = fetch_clusters(client, org_id)
        if not all_clusters:
            raise click.ClickException("Failed to fetch clusters for filtering.")

        matched_clusters = filter_clusters(all_clusters, cluster_name, cluster_uid)

        if not matched_clusters:
            filter_criteria = (
                f"name pattern '{cluster_name}'" if cluster_name else f"UID '{cluster_uid}'"
            )
            raise click.ClickException(
                f"[bold yellow]No cluster found matching criteria: {filter_criteria}[/bold yellow]"
            )
        elif len(matched_clusters) > 1:
            cluster_list = ", ".join([c["name"] for c in matched_clusters])
            raise click.ClickException(
                f"[bold yellow]Multiple clusters matched name pattern '{cluster_name}': {cluster_list}. Use --cluster-uid.[/bold yellow]"
            )
        else:
            target_cluster_uid = matched_clusters[0]["uid"]
            target_cluster_display_name = (
                f"cluster '{matched_clusters[0]['name']}' (UID: {target_cluster_uid})"
            )
            logger.info(f"Targeting schedules for {target_cluster_display_name}.")
    else:
        logger.info("No cluster filter specified. Processing schedules for all clusters.")

    return target_cluster_uid, target_cluster_display_name


# --- Authentication Helper ---


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
        # Ensure no warnings if validate_certs is False for the token generation call
        if not validate_certs:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        generated_token = generate_token(auth_url, client_id, username, password, validate_certs)
        click.echo("Successfully generated authentication token.")
        return generated_token
    except (requests.exceptions.RequestException, ValueError) as auth_err:
        raise click.ClickException(
            f"[bold red]Authentication Error:[/bold red] Failed to generate token: {auth_err}"
        )


def get_schedules(client: PXBackupClient, org_id: str) -> List[Dict[str, Any]]:
    """Retrieve all backup schedules from PX-Backup.

    Args:
        client: The initialized PXBackupClient.
        org_id: The organization ID.

    Returns:
        List of schedule dictionaries.

    Raises:
        requests.exceptions.RequestException: If the API call fails.
        ValueError: If the response format is unexpected.
    """
    logger.info(f"Fetching schedules for organization ID: {org_id}")
    # Endpoint derived from original script context
    endpoint = "api/schedules"  # Use relative path for PXBackupClient - removed pointless f-string
    try:
        response = client.make_request("GET", endpoint)
        # Assuming the response *is* the list of schedules based on original code
        if isinstance(response, list):
            logger.info(f"Successfully fetched {len(response)} schedules.")
            return response
        else:
            # Handle potential nesting or unexpected format
            schedules = response.get("schedules") if isinstance(response, dict) else None
            if isinstance(schedules, list):
                logger.info(f"Successfully fetched {len(schedules)} schedules.")
                return schedules
            else:
                logger.error(
                    f"Unexpected response format when fetching schedules. Expected list, got {type(response)}. Response: {response}"
                )
                raise ValueError("Unexpected API response format for schedules.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to retrieve schedules: {e}")
        raise
    except ValueError as e:
        logger.error(f"Error processing schedule response: {e}")
        raise


def update_schedule_suspend_status(client: PXBackupClient, schedule_id: str, suspend: bool) -> bool:
    """Update the suspend status of a specific schedule.

    Args:
        client: The initialized PXBackupClient.
        schedule_id: ID of the schedule to update
        suspend (bool): True to suspend the schedule, False to resume

    Returns:
        bool: True if the update was successful, False otherwise.

    Raises:
        requests.exceptions.RequestException: If the API call fails.
    """
    logger.info(f"Updating schedule {schedule_id} suspend status to: {suspend}")
    # Endpoint derived from original script context
    endpoint = f"api/schedules/{schedule_id}/suspend"  # Use relative path
    data = {"suspended": suspend}

    try:
        # PXBackupClient handles JSON conversion and headers
        client.make_request("PUT", endpoint, data=data)
        logger.info(f"Successfully updated suspend status for schedule {schedule_id}.")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to update schedule {schedule_id}: {e}")
        # Optionally, re-raise or just return False based on desired behavior
        # raise # Re-raise if caller should handle API errors explicitly
        return False  # Return False to indicate failure


def manage_schedules(
    client: PXBackupClient, org_id: str, suspend: bool, schedules: List[Dict[str, Any]]
) -> Tuple[int, int, int, int]:
    """Manage all backup schedules by updating their suspend status.

    Args:
        client: The initialized PXBackupClient.
        org_id: The organization ID.
        suspend (bool): True to suspend schedules, False to resume them
        schedules: The list of schedules to manage

    Returns:
        Tuple[int, int, int, int]: (total_schedules, successful_updates, already_in_state, failed_updates)
    """
    total_schedules = len(schedules)
    successful_updates = 0
    already_in_state = 0
    failed_updates = 0

    for schedule in schedules:
        schedule_id = schedule.get("id")
        if not schedule_id:
            logger.warning(f"Skipping schedule due to missing ID: {schedule}")
            failed_updates += 1  # Count as failed if ID is missing
            continue

        # Check current state - assume False if 'suspended' key is missing
        current_state = schedule.get("suspended", False)

        if current_state == suspend:
            already_in_state += 1
            logger.debug(f"Schedule {schedule_id} already in desired state (suspended={suspend}).")
            continue

        # Attempt update
        try:
            # update_schedule_suspend_status now returns bool
            if update_schedule_suspend_status(client, schedule_id, suspend):
                successful_updates += 1
            else:
                # Logged within update_schedule_suspend_status
                failed_updates += 1
        except Exception as e:
            # Catch any unexpected errors during the update call itself
            logger.error(f"Unexpected error updating schedule {schedule_id}: {e}", exc_info=True)
            failed_updates += 1

    return total_schedules, successful_updates, already_in_state, failed_updates


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
# Operation Arguments
@click.option(
    "--suspend", is_flag=True, default=False, help="Suspend all schedules (default is to resume)."
)
# Cluster Filtering Options
@click.option(
    "--cluster-name",
    required=False,
    help="Filter schedules by cluster name (regex pattern).",
)
@click.option("--cluster-uid", required=False, help="Filter schedules by exact cluster UID.")
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
    suspend: bool,
    debug: bool,
    cluster_name: Optional[str],
    cluster_uid: Optional[str],
):
    """Manages PX-Backup schedules by suspending or resuming them.

    Optionally filters schedules based on cluster name or UID.
    """
    # --- Setup Logging ---
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Logging setup complete.")

    validate_certs = not no_validate_certs
    console = Console()  # Initialize console for output

    # Disable warnings globally if needed (careful with this)
    if not validate_certs:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.warning("SSL certificate verification is disabled.")

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

        # --- Initialize Client ---
        client = PXBackupClient(api_url, current_token, validate_certs)

        # --- Cluster Filtering Logic ---
        target_cluster_uid, target_cluster_display_name = _get_target_cluster(
            client, org_id, cluster_name, cluster_uid
        )

        # --- Fetch Schedules ---
        logger.info(f"Fetching schedules for organization ID: {org_id}...")
        # Always fetch all schedules, filtering happens next
        all_schedules = get_schedules(client, org_id)
        if not all_schedules:
            console.print("[yellow]No schedules found for the organization.[/yellow]")
            sys.exit(0)

        # --- Filter Schedules Locally if Cluster was Specified ---
        schedules_to_process = all_schedules
        if target_cluster_uid:
            original_count = len(all_schedules)
            schedules_to_process = [
                s for s in all_schedules if s.get("clusterRef", {}).get("uid") == target_cluster_uid
            ]
            filtered_count = len(schedules_to_process)
            logger.info(
                f"Filtered {original_count} total schedules down to {filtered_count} for cluster UID {target_cluster_uid}."
            )
            if not schedules_to_process:
                console.print(
                    f"[yellow]No schedules found specifically for {target_cluster_display_name}.[/yellow]"
                )
                sys.exit(0)

        # --- Perform Operation on (filtered) schedules ---
        logger.info(
            f"Starting schedule management for {target_cluster_display_name}. Target state: suspended={suspend}"
        )
        total, successful, already_done, failed = manage_schedules(
            client, org_id, suspend, schedules_to_process
        )

        # --- Output Summary ---
        console.print(
            f"\n[bold green]Operation Summary ({target_cluster_display_name}):[/bold green]"
        )
        console.print(f"  Schedules considered: {total}")
        console.print(f"  Successfully {'suspended' if suspend else 'resumed'}: {successful}")
        console.print(f"  Already {'suspended' if suspend else 'resumed'}: {already_done}")
        console.print(f"  [bold red]Failed updates:[/bold red] {failed}")

        # Exit with appropriate code
        sys.exit(1 if failed > 0 else 0)

    except requests.exceptions.RequestException as e:
        raise click.ClickException(f"[bold red]API Request Error:[/bold red] {e}")
    except click.ClickException:
        raise  # Re-raise Click exceptions to let Click handle them
    except ValueError as e:  # Catch ValueErrors from API response parsing or filtering
        raise click.ClickException(f"[bold red]Data Error:[/bold red] {e}")
    except Exception as e:
        logger.exception("An unexpected error occurred.")
        raise click.ClickException(f"[bold red]An unexpected error occurred:[/bold red] {e}")


if __name__ == "__main__":
    main()
