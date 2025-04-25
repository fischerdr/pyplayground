#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lists PX-Backup schedules, optionally filtered by cluster.

This script provides a comprehensive view of PX-Backup schedules,
allowing for filtering by cluster name or UID. It supports pagination
and displays detailed information about each schedule, including:


"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import click
import requests
import urllib3
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

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


# --- Cluster Fetch/Filter Helper Functions (Adapted from update_scheds.py) ---


def fetch_clusters(client: PXBackupClient, org_id: str) -> List[Dict[str, Any]]:
    """Fetches the list of all clusters for the given organization."""
    logger.info(f"Fetching clusters for organization ID: {org_id}")
    endpoint = f"v1/cluster/{org_id}"
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
    """Checks if a single cluster matches the given filters."""
    metadata = cluster.get("metadata", {})
    cluster_name = metadata.get("name")
    cluster_uid = metadata.get("uid")

    if not cluster_name or not cluster_uid:
        logger.warning(f"Skipping cluster due to missing name or UID: {metadata}")
        return None

    match_info = {"name": cluster_name, "uid": cluster_uid}

    if uid and cluster_uid == uid:
        logger.debug(f"Matched cluster by UID: {cluster_name} ({cluster_uid})")
        return match_info

    if name_pattern:
        try:
            if re.match(name_pattern, cluster_name):
                logger.debug(
                    f"Matched cluster by name pattern '{name_pattern}': {cluster_name} ({cluster_uid})"
                )
                return match_info
        except re.error as e:
            logger.error(
                f"Invalid regex pattern '{name_pattern}': {e}. Skipping name pattern matching."
            )
            return None

    return None


def filter_clusters(
    clusters: List[Dict[str, Any]], name_pattern: Optional[str], uid: Optional[str]
) -> List[Dict[str, Any]]:
    """Filters clusters based on name pattern or UID."""
    if not name_pattern and not uid:
        logger.info("No cluster filter provided, using all found clusters.")
        return [
            {"name": c.get("metadata", {}).get("name"), "uid": c.get("metadata", {}).get("uid")}
            for c in clusters
            if c.get("metadata", {}).get("name") and c.get("metadata", {}).get("uid")
        ]

    matched = []
    for cluster in clusters:
        match_result = _get_matching_cluster_info(cluster, name_pattern, uid)
        if match_result and match_result not in matched:
            matched.append(match_result)

    logger.info(f"Filtered down to {len(matched)} clusters based on criteria.")
    return matched


# --- Authentication Helper (Copied from update_scheds.py) ---


def _handle_authentication(
    token: Optional[str],
    auth_url: Optional[str],
    client_id: str,
    username: Optional[str],
    password: Optional[str],
    validate_certs: bool,
) -> str:
    """Handles token retrieval or generation."""
    if token:
        logger.info("Using provided authentication token.")
        return token

    logger.info("Token not provided, attempting to generate one using credentials.")
    if not all([auth_url, username, password]):
        missing_auth = [
            p
            for p, v in [("auth-url", auth_url), ("username", username), ("password", password)]
            if not v
        ]
        raise click.ClickException(
            f"Error: Token not provided, missing options: {', '.join(missing_auth)}"
        )
    try:
        if not validate_certs:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        generated_token = generate_token(auth_url, client_id, username, password, validate_certs)
        click.echo("Successfully generated authentication token.")
        return generated_token
    except (requests.exceptions.RequestException, ValueError) as auth_err:
        raise click.ClickException(
            f"[bold red]Authentication Error:[/bold red] Failed to generate token: {auth_err}"
        )


# --- Schedule Fetching (Optimized) ---


def get_schedules(
    client: PXBackupClient, org_id: str, cluster_uid: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Retrieve backup schedules, optionally filtered by cluster UID via API."""
    target_info = f"cluster UID {cluster_uid}" if cluster_uid else "all clusters"
    logger.info(f"Fetching schedules for organization ID: {org_id} ({target_info}).")

    endpoint = f"v1/backupschedule/{org_id}"  # Endpoint from swagger
    params = {}
    if cluster_uid:
        # Use the API filter parameter based on swagger definition
        params["enumerate_options.cluster_uid_filter"] = cluster_uid
        # Potentially add name filter too if desired and supported by API
        # params["enumerate_options.cluster_name_filter"] = cluster_name

    logger.debug(f"Requesting schedules from endpoint: {endpoint} with params: {params}")

    try:
        response = client.make_request("GET", endpoint, params=params)
        # Log raw response at debug level
        logger.debug(f"Raw API response for schedules: {json.dumps(response, indent=2)}")

        schedules = response.get("schedules", [])
        if not isinstance(schedules, list):
            logger.error(
                f"Unexpected response format when fetching schedules. Expected list under 'schedules' key, got {type(schedules)}. Response: {response}"
            )
            raise ValueError("Unexpected API response format for schedules.")
        logger.info(f"Successfully fetched {len(schedules)} schedules for {target_info}.")
        return schedules
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to retrieve schedules for {target_info}: {e}")
        raise
    except ValueError as e:
        logger.error(f"Error processing schedule response for {target_info}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during schedule fetch or processing: {e}", exc_info=True)
        raise ValueError("Failed to process schedule response.")


# --- Display Function ---


def _display_schedules(schedules: List[Dict[str, Any]], console: Console) -> None:
    """Displays the list of schedules in a formatted table."""
    if not schedules:
        console.print("[yellow]No schedules found matching the criteria.[/yellow]")
        return

    console.print(f"Total Schedules Found: {len(schedules)}")

    table = Table(title="PX-Backup Backup Schedules", show_header=True, header_style="bold magenta")
    table.add_column("Name", style="dim", overflow="fold", min_width=20)
    table.add_column("UID", width=36)
    table.add_column("Cluster", overflow="fold")
    table.add_column("Backup Location", overflow="fold")
    table.add_column("Schedule Type", overflow="fold")
    table.add_column("Frequency", overflow="fold")
    table.add_column("Retention", overflow="fold")
    table.add_column("Suspended")
    table.add_column("Namespaces", overflow="fold")
    table.add_column("Resource Types", overflow="fold")
    table.add_column("Exclude Rsc Types", overflow="fold")
    table.add_column("Label Selectors", overflow="fold")
    table.add_column("NS Label Selectors", overflow="fold")
    table.add_column("Include Rsc Count", justify="right")
    table.add_column("Created Time", overflow="fold")

    # Sort schedules by creation time (descending) if possible
    try:
        schedules.sort(key=lambda s: s.get("metadata", {}).get("create_time", ""), reverse=True)
    except Exception:
        logger.warning("Could not sort schedules by creation time.", exc_info=False)

    for schedule in schedules:
        metadata = schedule.get("metadata", {})
        # Change: Extract from backup_schedule_info instead of spec
        backup_schedule_info = schedule.get("backup_schedule_info", {})
        # Change: Use backup_schedule_info as base for refs
        schedule_policy_ref = backup_schedule_info.get("schedule_policy_ref", {})
        cluster_ref = backup_schedule_info.get("cluster_ref", {})
        backup_location_ref = backup_schedule_info.get("backup_location_ref", {})

        # Change: Get policy details from dsMeta
        ds_meta = schedule.get("dsMeta", {})
        policy_details = ds_meta.get("policies", {})
        policy_info = policy_details.get("schedule_policy_info", {})

        # Determine schedule type from policy details if possible, fallback to ref
        schedule_type = "N/A"
        frequency = "N/A"
        retention = "N/A"

        if policy_info.get("daily"):
            schedule_type = "Daily"
            daily_policy = policy_info["daily"]
            frequency = f"Daily at {daily_policy.get('time', '?')}"
            retention = f"{daily_policy.get('retain', '?')} days"
        elif policy_info.get("weekly"):
            schedule_type = "Weekly"
            weekly_policy = policy_info["weekly"]
            frequency = (
                f"Weekly on {weekly_policy.get('day', '?')} at {weekly_policy.get('time', '?')}"
            )
            retention = f"{weekly_policy.get('retain', '?')} weeks"
        elif policy_info.get("monthly"):
            schedule_type = "Monthly"
            monthly_policy = policy_info["monthly"]
            frequency = f"Monthly on day {monthly_policy.get('day', '?')} at {monthly_policy.get('time', '?')}"
            retention = f"{monthly_policy.get('retain', '?')} months"
        elif policy_info.get("interval"):
            schedule_type = "Interval"
            interval_policy = policy_info["interval"]
            frequency = f"Every {interval_policy.get('intervalMinutes', '?')} mins"
            retention = f"{interval_policy.get('retain', '?')} backups"
        else:
            # Fallback if structure is different or missing
            schedule_type = schedule_policy_ref.get("type", "N/A")  # Get type from ref as fallback

        # --- Resource Selector Details ---
        namespaces = backup_schedule_info.get("namespaces", [])
        resource_types = backup_schedule_info.get("resource_types", [])
        exclude_resource_types = backup_schedule_info.get("exclude_resource_types", [])
        label_selectors = backup_schedule_info.get("label_selectors", {})  # Expecting dict
        ns_label_selectors = backup_schedule_info.get(
            "ns_label_selectors", {}
        )  # Expecting dict based on sample
        include_resources = backup_schedule_info.get("include_resources", [])  # Expecting list

        # Formatting for display
        namespaces_str = ", ".join(namespaces) if namespaces else "All"
        resource_types_str = ", ".join(resource_types) if resource_types else "All"
        exclude_resource_types_str = (
            ", ".join(exclude_resource_types) if exclude_resource_types else "None"
        )
        # Format dicts like k1=v1, k2=v2
        label_selectors_str = (
            ", ".join([f"{k}={v}" for k, v in label_selectors.items()])
            if label_selectors
            else "None"
        )
        ns_label_selectors_str = (
            ", ".join([f"{k}={v}" for k, v in ns_label_selectors.items()])
            if ns_label_selectors
            else "None"
        )
        include_resources_count = str(len(include_resources)) if include_resources else "0"

        table.add_row(
            metadata.get("name", "N/A"),
            metadata.get("uid", "N/A"),
            cluster_ref.get("name", "N/A"),
            backup_location_ref.get("name", "N/A"),
            schedule_type,
            frequency,
            retention,
            str(schedule.get("suspended", False)),
            namespaces_str,
            resource_types_str,
            exclude_resource_types_str,
            label_selectors_str,
            ns_label_selectors_str,
            include_resources_count,
            metadata.get("create_time", "N/A"),
        )

    console.print(table)


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
        logger.info("No cluster filter specified. Listing schedules for all clusters.")

    return target_cluster_uid, target_cluster_display_name


# --- Click Command ---
@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
# API/Auth Options
@click.option(
    "--api-url",
    required=True,
    envvar="PX_BACKUP_API_URL",
    help="PX-Backup API URL. Env: PX_BACKUP_API_URL",
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
    help="Authentication token. Env: PX_BACKUP_TOKEN",
)
@click.option(
    "--no-validate-certs",
    is_flag=True,
    default=False,
    help="Disable SSL certificate validation.",
)
# Token Generation Options
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
    help="Client ID for authentication. Env: PX_CLIENT_ID",
)
@click.option(
    "--username",
    required=False,
    envvar="PX_USERNAME",
    help="Username for authentication. Env: PX_USERNAME",
)
@click.option(
    "--password",
    required=False,
    envvar="PX_PASSWORD",
    help="Password for authentication. Env: PX_PASSWORD",
    hide_input=True,
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
    debug: bool,
    cluster_name: Optional[str],
    cluster_uid: Optional[str],
):
    """Lists PX-Backup backup schedules, optionally filtered by cluster."""
    # --- Setup Logging ---
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug(f"Starting {script_base_name}...")
    logger.debug(
        f"Provided options: api_url={api_url}, org_id={org_id}, token={'*' * 4 if token else None}, no_validate_certs={no_validate_certs}, auth_url={auth_url}, client_id={client_id}, username={username}, password={'*' * 4 if password else None}, cluster_name={cluster_name}, cluster_uid={cluster_uid}, debug={debug}"
    )

    validate_certs = not no_validate_certs
    console = Console()

    if not validate_certs:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.warning("SSL certificate verification is disabled.")

    try:
        # --- Authentication ---
        logger.debug("Attempting authentication...")
        current_token = _handle_authentication(
            token=token,
            auth_url=auth_url,
            client_id=client_id,
            username=username,
            password=password,
            validate_certs=validate_certs,
        )
        logger.debug("Authentication successful.")

        # --- Initialize Client ---
        logger.debug("Initializing PXBackupClient...")
        client = PXBackupClient(api_url, current_token, validate_certs)
        logger.debug("Client initialized.")

        # --- Cluster Filtering Logic ---
        logger.debug("Checking for cluster filters...")
        target_cluster_uid, target_cluster_display_name = _get_target_cluster(
            client, org_id, cluster_name, cluster_uid
        )
        logger.debug(
            f"Target cluster identified as: {target_cluster_display_name} (UID: {target_cluster_uid})"
        )

        # --- Fetch Schedules (using API filter if target_cluster_uid is set) ---
        logger.debug(f"Attempting to fetch schedules for {target_cluster_display_name}...")
        schedules = get_schedules(client, org_id, target_cluster_uid)
        logger.debug(f"Schedule fetch call completed. Found {len(schedules)} schedules.")

        # --- Display Results ---
        logger.debug("Preparing to display schedules...")
        _display_schedules(schedules, console)
        logger.debug("Display complete.")

    except requests.exceptions.RequestException as e:
        logger.error(f"API Request Error: {e}", exc_info=debug)
        raise click.ClickException(f"[bold red]API Request Error:[/bold red] {e}")
    except click.ClickException:
        logger.debug("ClickException raised, exiting.")
        raise  # Re-raise Click exceptions
    except ValueError as e:
        logger.error(f"Data Error: {e}", exc_info=debug)
        raise click.ClickException(f"[bold red]Data Error:[/bold red] {e}")
    except Exception as e:
        logger.exception("An unexpected error occurred.")
        raise click.ClickException(f"[bold red]An unexpected error occurred:[/bold red] {e}")


if __name__ == "__main__":
    main()
