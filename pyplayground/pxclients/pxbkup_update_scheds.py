#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PX-Backup Schedule Manager.

This script manages PX-Backup schedules by updating their suspend status.
It allows for bulk suspension or resumption of schedules based on command-line arguments.

"""
import json
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
from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.px_api import PXBackupClient, generate_token

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


def _parse_schedules_response(response: Any, endpoint: str) -> List[Dict[str, Any]]:
    """Parses the API response to extract the list of schedules."""
    schedules = []
    if isinstance(response, dict):
        if "backup_schedules" in response:
            schedules = response.get("backup_schedules", [])
            if not isinstance(schedules, list):
                logger.warning("'backup_schedules' key found but value is not a list.")
                schedules = []
        elif "schedules" in response:
            schedules = response.get("schedules", [])
            if not isinstance(schedules, list):
                logger.warning("'schedules' key found but value is not a list.")
                schedules = []
    elif isinstance(response, list):
        schedules = response

    if not schedules and response:  # Check if response wasn't empty but parsing failed
        logger.error(
            f"Unexpected response format from {endpoint}. Expected list under 'backup_schedules' or 'schedules', or a direct list. Got type {type(response)}."
        )
        raise ValueError(f"Unexpected API response format for schedules from {endpoint}.")

    return schedules


def get_schedules(
    client: PXBackupClient, org_id: str, cluster_uid: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Retrieve backup schedules, optionally filtered by cluster UID via API."""
    target_info = f"cluster UID {cluster_uid}" if cluster_uid else "all clusters"
    logger.info(f"Fetching schedules for organization ID: {org_id} ({target_info}).")
    # Use the v1 endpoint
    endpoint = f"v1/backupschedule/{org_id}"
    # Re-add server-side filtering parameter if cluster_uid is provided
    params = {}
    if cluster_uid:
        params["enumerate_options.cluster_uid_filter"] = cluster_uid

    try:
        # Pass params to make_request
        response = client.make_request("GET", endpoint, params=params)
        logger.debug(
            f"Raw API response for schedules ({endpoint}): {json.dumps(response, indent=2)}"
        )

        # Use the parsing helper which expects backup_schedules key
        schedules = _parse_schedules_response(response, endpoint)

        logger.info(f"Successfully fetched {len(schedules)} schedules for {target_info}.")
        return schedules

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to retrieve schedules for {target_info}: {e}")
        raise
    except ValueError as e:
        logger.error(f"Error processing schedule response for {target_info}: {e}")
        raise


def update_schedule_suspend_status(
    client: PXBackupClient, schedule: Dict[str, Any], suspend: bool
) -> bool:
    """Update the suspend status of a specific schedule using the v1 PUT endpoint.

    Args:
        client: The initialized PXBackupClient.
        schedule: The full schedule dictionary object to update.
        suspend (bool): True to suspend the schedule, False to resume.

    Returns:
        bool: True if the update was successful, False otherwise.
    """
    schedule_name = schedule.get("metadata", {}).get("name", "[UNKNOWN]")
    schedule_uid = schedule.get("metadata", {}).get("uid", "[UNKNOWN]")
    logger.info(f"Updating schedule {schedule_name} ({schedule_uid}) suspend status to: {suspend}")

    # Modify the schedule object directly
    # Assuming 'suspended' is a top-level key or within backup_schedule_info
    # Check both possibilities - adapt based on actual object structure if needed
    if "suspended" in schedule:
        schedule["suspended"] = suspend
        logger.debug(f"Set top-level 'suspended' to {suspend}")
    elif "backup_schedule_info" in schedule and isinstance(schedule["backup_schedule_info"], dict):
        schedule["backup_schedule_info"]["suspended"] = suspend
        logger.debug(f"Set backup_schedule_info.suspended to {suspend}")
    else:
        # Attempt to add it to backup_schedule_info if missing
        if "backup_schedule_info" not in schedule:
            schedule["backup_schedule_info"] = {}
        if isinstance(schedule["backup_schedule_info"], dict):
            schedule["backup_schedule_info"]["suspended"] = suspend
            logger.warning("Added 'suspended' key to backup_schedule_info.")
        else:
            logger.error(
                f"Could not set suspended status for schedule {schedule_name}: Neither top-level key nor backup_schedule_info dict found."
            )
            return False

    # Use the v1 general update endpoint
    endpoint = "v1/backupschedule"

    try:
        # Send the entire modified schedule object as the payload
        client.make_request("PUT", endpoint, data=schedule)
        logger.info(f"Successfully updated suspend status for schedule {schedule_name}.")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to update schedule {schedule_name} ({schedule_uid}): {e}")
        return False


def manage_schedules(
    client: PXBackupClient, org_id: str, suspend: bool, schedules: List[Dict[str, Any]]
) -> Tuple[int, int, int, int]:
    """Manage backup schedules by updating their suspend status using the v1 API."""
    total_schedules = len(schedules)
    successful_updates = 0
    already_in_state = 0
    failed_updates = 0

    for schedule in schedules:
        # Metadata needed for logging/identification if update fails
        metadata = schedule.get("metadata", {})
        schedule_name = metadata.get("name", "[UNKNOWN_NAME]")
        schedule_uid = metadata.get("uid", "[UNKNOWN_UID]")

        # Check current state - check top-level first, then backup_schedule_info
        current_state = schedule.get("suspended")  # Check top level
        if (
            current_state is None
            and "backup_schedule_info" in schedule
            and isinstance(schedule.get("backup_schedule_info"), dict)
        ):
            current_state = schedule["backup_schedule_info"].get("suspended", False)  # Check nested
        else:
            current_state = (
                current_state if current_state is not None else False
            )  # Default to False if not found anywhere

        if current_state == suspend:
            already_in_state += 1
            logger.debug(
                f"Schedule {schedule_name} ({schedule_uid}) already in desired state (suspended={suspend})."
            )
            continue

        # Attempt update by passing the full schedule object
        try:
            if update_schedule_suspend_status(client, schedule, suspend):
                successful_updates += 1
            else:
                failed_updates += 1
        except Exception as e:
            logger.error(
                f"Unexpected error updating schedule {schedule_name} ({schedule_uid}): {e}",
                exc_info=True,
            )
            failed_updates += 1

    return total_schedules, successful_updates, already_in_state, failed_updates


def _filter_schedules_locally(
    schedules: List[Dict[str, Any]],
    target_cluster_uid: Optional[str],
    backup_schedule_name_pattern: Optional[str],
    target_cluster_display_name: str,
    console: Console,
) -> List[Dict[str, Any]]:
    """Applies local filtering based on cluster UID and schedule name pattern."""
    schedules_to_process = schedules
    original_count = len(schedules_to_process)
    cluster_filter_applied = False

    # --- Filter by Cluster UID (Optional local check/redundant if API filter works) ---
    if target_cluster_uid:
        cluster_filter_applied = True
        schedules_to_process_cluster = [
            s
            for s in schedules_to_process
            if s.get("backup_schedule_info", {}).get("cluster_ref", {}).get("uid")
            == target_cluster_uid
        ]
        if len(schedules_to_process_cluster) < len(schedules_to_process):
            logger.warning(
                "Local cluster filter removed schedules missed by API filter. This might indicate an issue."
            )
        schedules_to_process = schedules_to_process_cluster

        filtered_count = len(schedules_to_process)
        # Only log if local filter actually changed the list size from original API fetch
        if filtered_count < original_count:
            logger.info(
                f"Locally filtered {original_count} schedules down to {filtered_count} for {target_cluster_display_name}."
            )
        if not schedules_to_process:
            console.print(
                f"[yellow]No schedules found specifically for {target_cluster_display_name} after local filter.[/yellow]"
            )
            sys.exit(0)
        original_count = filtered_count  # Reset count for potential name filtering log

    # --- Filter by Name Pattern ---
    if backup_schedule_name_pattern:
        try:
            filtered_schedules = [
                s
                for s in schedules_to_process
                if re.match(backup_schedule_name_pattern, s.get("metadata", {}).get("name", ""))
            ]
            filtered_count = len(filtered_schedules)
            log_suffix = " (after cluster filtering)" if cluster_filter_applied else ""
            logger.info(
                f"Filtered {original_count} schedules down to {filtered_count} matching name pattern '{backup_schedule_name_pattern}'{log_suffix}."
            )
            if not filtered_schedules:
                console.print(
                    f"[yellow]No schedules found matching name pattern '{backup_schedule_name_pattern}'{log_suffix}.[/yellow]"
                )
                sys.exit(0)
            schedules_to_process = filtered_schedules
        except re.error as e:
            logger.error(
                f"Invalid regex pattern for schedule name '{backup_schedule_name_pattern}': {e}. Skipping name filtering."
            )
            # Proceed without name filtering if regex is invalid

    return schedules_to_process


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
# Schedule Name Filtering Option
@click.option(
    "--backup-schedule-name",
    required=False,
    help="Filter schedules by name (regex pattern). Applies after cluster filtering.",
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
    suspend: bool,
    debug: bool,
    cluster_name: Optional[str],
    cluster_uid: Optional[str],
    backup_schedule_name: Optional[str],
):
    """Manages PX-Backup schedules by suspending or resuming them.

    Optionally filters schedules based on cluster name/UID and/or schedule name.
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

        # --- Cluster Filtering Logic (Resolve target UID) ---
        target_cluster_uid, target_cluster_display_name = _get_target_cluster(
            client, org_id, cluster_name, cluster_uid
        )

        # --- Fetch Schedules (using API filter if target_cluster_uid is set) ---
        logger.info(
            f"Fetching schedules for organization ID: {org_id} (API filter: {target_cluster_display_name})..."
        )
        all_schedules = get_schedules(client, org_id, target_cluster_uid)
        if not all_schedules:
            console.print(f"[yellow]No schedules found for {target_cluster_display_name}.[/yellow]")
            sys.exit(0)

        # --- Apply Local Filters (primarily for schedule name) ---
        schedules_to_process = _filter_schedules_locally(
            all_schedules,  # Start with API-filtered list
            None,  # Don't re-apply cluster UID filter locally
            backup_schedule_name,  # Apply name filter locally
            target_cluster_display_name,
            console,
        )

        # --- Perform Operation on filtered schedules ---
        logger.info(
            f"Starting schedule management for {len(schedules_to_process)} schedules. Target state: suspended={suspend}"
        )
        total, successful, already_done, failed = manage_schedules(
            client,
            org_id,
            suspend,
            schedules_to_process,  # Use the finally filtered list
        )

        # --- Output Summary ---
        console.print(
            f"\n[bold green]Operation Summary ({target_cluster_display_name} / Name Filter: '{backup_schedule_name if backup_schedule_name else 'None'}'):[/bold green]"
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
