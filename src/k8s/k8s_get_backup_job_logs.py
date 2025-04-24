#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Finds running PX-Backup backups, locates the corresponding Kubernetes Jobs, and fetches recent logs from the 'kopiaexecutor' container in the job's pods."""

import logging
import os
from typing import Dict, List, Optional

import click
import requests
import urllib3
from dotenv import load_dotenv
from kubernetes import client
from kubernetes.client.rest import ApiException
from rich import box
from rich.console import Console
from rich.panel import Panel

from utils.k8s_utils import load_kube_config_auto
from utils.logging_utils import get_logger, setup_logging
from utils.px_api import PXBackupClient, generate_token

# Disable SSL warnings - due to self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Constants ---
KOPIAEXECUTOR_CONTAINER_NAME = "kopiaexecutor"
RUNNING_BACKUP_STATUS = "InProgress"  # Adjust if PX-Backup uses a different status

# --- Initialize Logger and Console ---
# Logging will be fully configured in the main function based on debug flag
logger = get_logger(__name__)
console = Console()

# Load environment variables from .env file, if it exists
load_dotenv()


# --- Helper Functions ---


def fetch_clusters(px_client: PXBackupClient, org_id: str) -> List[Dict]:
    """Fetches the list of all clusters for the given organization."""
    logger.info(f"Fetching clusters for organization ID: {org_id}")
    endpoint = f"v1/cluster/{org_id}"
    try:
        response = px_client.make_request("GET", endpoint)
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


def _filter_clusters_by_name(clusters: List[Dict], name_pattern: str) -> List[Dict[str, str]]:
    """Filters clusters based on a regex name pattern.

    Args:
        clusters: The list of cluster dictionaries to filter.
        name_pattern: Regex pattern to match cluster name.

    Returns:
        A list of matched cluster dictionaries, each containing 'name' and 'uid'.
    """
    import re  # Import here as it's only used in this function

    matched = []
    logger.info(f"Filtering {len(clusters)} clusters using name pattern: '{name_pattern}'")
    try:
        pattern = re.compile(name_pattern)
    except re.error as e:
        logger.error(f"Invalid regex pattern '{name_pattern}': {e}. Skipping filtering.")
        # Return empty list if pattern is invalid, as we can't match
        return []

    for cluster in clusters:
        metadata = cluster.get("metadata", {})
        cluster_name = metadata.get("name")
        cluster_uid = metadata.get("uid")

        if not cluster_name or not cluster_uid:
            logger.warning(f"Skipping cluster due to missing name or UID: {metadata}")
            continue

        if pattern.match(cluster_name):
            match_info = {"name": cluster_name, "uid": cluster_uid}
            if match_info not in matched:
                matched.append(match_info)
                logger.debug(f"Matched cluster by name: {cluster_name} (UID: {cluster_uid})")

    logger.info(f"Found {len(matched)} cluster(s) matching name pattern.")
    return matched


def _fetch_all_backups_for_cluster(
    px_client: PXBackupClient, org_id: str, cluster_uid: str
) -> List[Dict]:
    """Fetches all backups associated with a specific cluster UID."""
    logger.info(f"Fetching all backups for cluster UID: {cluster_uid}")
    params = {"enumerate_options.cluster_uid_filter": cluster_uid}
    endpoint = f"v1/backup/{org_id}"
    try:
        response = px_client.make_request("GET", endpoint, params=params)
        backups = response.get("backups", [])
        if not isinstance(backups, list):
            logger.warning(
                f"API response for backups for cluster {cluster_uid} was not a list: {type(backups)}. Returning empty list."
            )
            return []
        logger.info(f"Fetched {len(backups)} total backups for cluster {cluster_uid}.")
        return backups
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch backups for cluster {cluster_uid}: {e}")
        raise  # Re-raise for handling in the caller


def _get_all_backups(
    px_client: PXBackupClient, org_id: str, cluster_filter_uid: Optional[str] = None
) -> List[Dict]:
    """Fetches all backups, optionally filtered by a specific cluster UID."""
    if cluster_filter_uid:
        # Fetch backups only for the specified cluster
        return _fetch_all_backups_for_cluster(px_client, org_id, cluster_filter_uid)
    else:
        # Fetch all clusters first, then backups for each
        all_backups = []
        logger.info("Fetching all clusters to find all backups.")
        cluster_endpoint = f"v1/cluster/{org_id}"
        cluster_response = px_client.make_request("GET", cluster_endpoint)
        clusters_raw = cluster_response.get("clusters", [])
        if not isinstance(clusters_raw, list):
            logger.warning("Cluster list API response was not a list.")
            clusters_raw = []

        cluster_uids = [
            c.get("metadata", {}).get("uid")
            for c in clusters_raw
            if c.get("metadata", {}).get("uid")
        ]
        logger.info(f"Found {len(cluster_uids)} clusters. Fetching backups for each.")

        for uid in cluster_uids:
            try:
                cluster_backups = _fetch_all_backups_for_cluster(px_client, org_id, uid)
                all_backups.extend(cluster_backups)
            except requests.exceptions.RequestException:
                logger.warning(f"Skipping backups for cluster {uid} due to fetch error.")
                continue  # Continue to next cluster
        return all_backups


def fetch_running_backups(
    px_client: PXBackupClient, org_id: str, cluster_filter_uid: Optional[str] = None
) -> List[Dict[str, str]]:
    """Fetches backups from PX-Backup and filters for those in a running state.

    Args:
        px_client: Initialized PXBackupClient.
        org_id: PX-Backup Organization ID.
        cluster_filter_uid: Optional UID of a specific cluster to filter by.

    Returns:
        A list of dictionaries, each containing the 'name' and 'uid' of a running backup.
    """
    all_backups = []
    try:
        all_backups = _get_all_backups(px_client, org_id, cluster_filter_uid)
    except requests.exceptions.RequestException as e:
        # Error logged in helper, re-raise to be caught by main
        logger.error(f"Failed to retrieve backup list: {e}")
        raise

    running_backups_info = []
    logger.info(f"Filtering {len(all_backups)} backups for status '{RUNNING_BACKUP_STATUS}'.")
    for backup in all_backups:
        metadata = backup.get("metadata", {})
        backup_info = backup.get("backup_info", {})
        status_info = backup_info.get("status", {})
        status = status_info.get("status")

        if status == RUNNING_BACKUP_STATUS:
            name = metadata.get("name")
            uid = metadata.get("uid")
            if name and uid:
                running_backups_info.append({"name": name, "uid": uid})
                logger.debug(f"Found running backup: {name} (UID: {uid})")
            else:
                logger.warning(f"Running backup found but missing name or UID: {metadata}")

    logger.info(f"Found {len(running_backups_info)} backups in '{RUNNING_BACKUP_STATUS}' state.")
    return running_backups_info


def find_jobs_for_backup(batch_v1_api: client.BatchV1Api, backup_uid: str) -> List[client.V1Job]:
    """Finds Kubernetes Jobs associated with a given backup UID via labels.

    Args:
        batch_v1_api: Initialized Kubernetes BatchV1Api client.
        backup_uid: The UID of the PX-Backup backup object.

    Returns:
        A list of V1Job objects matching the label selector.
    """
    label_selector = f"kdmp.portworx.com/backupobject-uid={backup_uid}"
    logger.info(f"Searching for Kubernetes Jobs with label selector: {label_selector}")
    try:
        # Search across all namespaces
        job_list = batch_v1_api.list_job_for_all_namespaces(label_selector=label_selector)
        logger.info(f"Found {len(job_list.items)} job(s) matching backup UID {backup_uid}.")
        return job_list.items
    except ApiException as e:
        logger.error(
            f"API error searching for jobs with label '{label_selector}': {e.status} - {e.reason}"
        )
        console.print(
            f"[bold red]K8s API Error:[/bold red] Could not list jobs. Reason: {e.reason}"
        )
        return []  # Return empty list on error
    except Exception as e:
        logger.exception(f"Unexpected error finding jobs for backup UID {backup_uid}: {e}")
        console.print(f"[bold red]Error:[/bold red] Unexpected error searching for jobs: {e}")
        return []


def find_pods_for_job(core_v1_api: client.CoreV1Api, job: client.V1Job) -> List[client.V1Pod]:
    """Finds Kubernetes Pods managed by a given Job.

    Args:
        core_v1_api: Initialized Kubernetes CoreV1Api client.
        job: The V1Job object.

    Returns:
        A list of V1Pod objects associated with the job.
    """
    job_name = job.metadata.name
    job_namespace = job.metadata.namespace
    logger.info(f"Searching for pods for job '{job_name}' in namespace '{job_namespace}'.")

    # Get label selector from job spec
    if not job.spec or not job.spec.selector or not job.spec.selector.match_labels:
        logger.warning(f"Job '{job_name}' has no valid label selector. Cannot find pods.")
        return []

    match_labels = job.spec.selector.match_labels
    pod_label_selector = ",".join([f"{k}={v}" for k, v in match_labels.items()])
    logger.debug(f"Using pod label selector: {pod_label_selector}")

    try:
        pod_list = core_v1_api.list_namespaced_pod(
            namespace=job_namespace, label_selector=pod_label_selector
        )
        logger.info(f"Found {len(pod_list.items)} pod(s) for job '{job_name}'.")
        return pod_list.items
    except ApiException as e:
        logger.error(
            f"API error listing pods for job '{job_name}' in ns '{job_namespace}': {e.status} - {e.reason}"
        )
        console.print(
            f"[bold red]K8s API Error:[/bold red] Could not list pods for job '{job_name}'. Reason: {e.reason}"
        )
        return []
    except Exception as e:
        logger.exception(f"Unexpected error finding pods for job '{job_name}': {e}")
        console.print(f"[bold red]Error:[/bold red] Unexpected error finding pods: {e}")
        return []


def get_kopia_logs_from_pod(
    core_v1_api: client.CoreV1Api, pod: client.V1Pod, tail_lines: int
) -> Optional[str]:
    """Attempts to get logs from the kopiaexecutor container within a pod.

    Args:
        core_v1_api: Initialized Kubernetes CoreV1Api client.
        pod: The V1Pod object to inspect.
        tail_lines: The number of log lines to fetch.

    Returns:
        The log string if successful, or None if the container is not found or logs cannot be fetched.
    """
    pod_name = pod.metadata.name
    pod_namespace = pod.metadata.namespace
    target_container = KOPIAEXECUTOR_CONTAINER_NAME
    logger.debug(f"Checking for container '{target_container}' in pod '{pod_name}'.")

    container_found = False
    if pod.spec and pod.spec.containers:
        for container in pod.spec.containers:
            if container.name == target_container:
                container_found = True
                break

    if not container_found:
        logger.warning(f"Container '{target_container}' not found in pod '{pod_name}'.")
        # Don't print to console here, let the main loop indicate no logs found
        return None

    logger.info(
        f"Attempting to fetch last {tail_lines} logs for '{target_container}' in pod '{pod_name}'."
    )
    try:
        logs = core_v1_api.read_namespaced_pod_log(
            name=pod_name,
            namespace=pod_namespace,
            container=target_container,
            tail_lines=tail_lines,
        )
        logger.info(f"Successfully fetched logs for '{target_container}' in pod '{pod_name}'.")
        return logs
    except ApiException as e:
        logger.error(
            f"API error fetching logs for container '{target_container}' in pod '{pod_name}': {e.status} - {e.reason}"
        )
        # Check common reasons
        if (
            "container not found" in str(e.body).lower()
        ):  # Should not happen due to check above, but handle defensively
            console.print(
                f"  [yellow]Warning:[/yellow] K8s API reported '{target_container}' not found in pod '{pod_name}' (unexpected)."
            )
        elif (
            "container is waiting" in str(e.body).lower()
            or "waiting to start" in str(e.body).lower()
        ):
            console.print(
                f"  [yellow]Warning:[/yellow] Container '{target_container}' in pod '{pod_name}' is waiting, logs not available yet."
            )
        else:
            console.print(
                f"  [red]Error:[/red] Could not fetch logs for '{target_container}' in pod '{pod_name}'. Reason: {e.reason}"
            )
        return None
    except Exception as e:
        logger.exception(
            f"Unexpected error fetching logs for '{target_container}' in pod '{pod_name}': {e}"
        )
        console.print(
            f"  [red]Error:[/red] Unexpected error fetching logs for '{target_container}' in '{pod_name}': {e}"
        )
        return None


def _authenticate_and_setup_clients(
    api_url: str,
    token: Optional[str],
    validate_certs: bool,
    auth_url: Optional[str],
    client_id: str,
    username: Optional[str],
    password: Optional[str],
) -> tuple[PXBackupClient, client.CoreV1Api, client.BatchV1Api]:
    """Handles authentication and initializes API clients."""
    current_token = token
    # --- Authentication (PX-Backup) ---
    if not current_token:
        logger.info("Token not provided, attempting to generate one.")
        if not all([auth_url, username, password]):
            missing = [
                p
                for p, v in [
                    ("auth-url", auth_url),
                    ("username", username),
                    ("password", password),
                ]
                if not v
            ]
            raise click.ClickException(
                f"Missing options for token generation: {', '.join(missing)}"
            )
        try:
            current_token = generate_token(auth_url, client_id, username, password, validate_certs)
            logger.info("Successfully generated authentication token.")
        except (requests.exceptions.RequestException, ValueError) as auth_err:
            # Wrap authentication errors in ClickException for consistent handling
            raise click.ClickException(f"Authentication Error: {auth_err}")

    px_client = PXBackupClient(api_url, current_token, validate_certs)

    # --- Load Kubernetes Config & Initialize Clients ---
    if not load_kube_config_auto():
        raise click.ClickException("Could not load Kubernetes configuration.")
    k8s_core_v1 = client.CoreV1Api()
    k8s_batch_v1 = client.BatchV1Api()

    return px_client, k8s_core_v1, k8s_batch_v1


def _determine_target_cluster_uid(
    px_client: PXBackupClient,
    org_id: str,
    cluster_name: Optional[str],
    cluster_uid: Optional[str],
) -> Optional[str]:
    """Determines the target cluster UID based on provided CLI options."""
    target_cluster_uid: Optional[str] = None
    if cluster_uid and cluster_name:
        logger.warning(
            "Both --cluster-name and --cluster-uid provided. Prioritizing --cluster-uid."
        )
        target_cluster_uid = cluster_uid
    elif cluster_uid:
        target_cluster_uid = cluster_uid
        logger.info(f"Targeting specific cluster UID: {target_cluster_uid}")
    elif cluster_name:
        logger.info(f"Filtering clusters by name pattern: '{cluster_name}'")
        try:
            all_clusters = fetch_clusters(px_client, org_id)
            matched_clusters = _filter_clusters_by_name(all_clusters, cluster_name)

            if len(matched_clusters) == 0:
                raise click.UsageError(f"No clusters found matching name pattern: '{cluster_name}'")
            elif len(matched_clusters) > 1:
                cluster_names_found = [c["name"] for c in matched_clusters]
                raise click.UsageError(
                    f"Multiple clusters found matching name pattern '{cluster_name}': {cluster_names_found}. Please use --cluster-uid or a more specific pattern."
                )
            else:
                target_cluster_uid = matched_clusters[0]["uid"]
                logger.info(
                    f"Found matching cluster: {matched_clusters[0]['name']} (UID: {target_cluster_uid})"
                )
        except requests.exceptions.RequestException as e:
            # Raised by fetch_clusters
            raise click.ClickException(f"Failed to fetch cluster list: {e}")
    else:
        logger.info("No cluster filter specified. Processing backups from all clusters.")
        # target_cluster_uid remains None

    return target_cluster_uid


def _process_backup_logs(
    px_client: PXBackupClient,
    org_id: str,
    k8s_core_v1: client.CoreV1Api,
    k8s_batch_v1: client.BatchV1Api,
    tail_lines: int,
    cluster_filter_uid: Optional[str] = None,
):
    """Handles the core workflow of fetching backups, jobs, pods, and logs."""
    running_backups = fetch_running_backups(px_client, org_id, cluster_filter_uid)

    if not running_backups:
        console.print(f"[yellow]No backups found in '{RUNNING_BACKUP_STATUS}' state.[/yellow]")
        return

    console.print(f"Found {len(running_backups)} running backup(s).")

    results_found = False
    for backup in running_backups:
        backup_name = backup["name"]
        backup_uid = backup["uid"]
        console.print(
            f"\n--- Processing Backup: [cyan]{backup_name}[/cyan] (UID: {backup_uid}) ---"
        )

        jobs = find_jobs_for_backup(k8s_batch_v1, backup_uid)
        if not jobs:
            console.print(
                f"  [yellow]No Kubernetes Job found for backup UID {backup_uid}.[/yellow]"
            )
            continue

        for job in jobs:
            job_name = job.metadata.name
            job_namespace = job.metadata.namespace
            console.print(f"  Found Job: [green]{job_name}[/green] (Namespace: {job_namespace})")

            pods = find_pods_for_job(k8s_core_v1, job)
            if not pods:
                console.print(f"    [yellow]No Pods found for Job {job_name}.[/yellow]")
                continue

            for pod in pods:
                pod_name = pod.metadata.name
                # pod_namespace = pod.metadata.namespace # Unused variable
                console.print(f"    Checking Pod: [blue]{pod_name}[/blue]")

                logs = get_kopia_logs_from_pod(k8s_core_v1, pod, tail_lines)

                if logs is not None:
                    results_found = True
                    log_title = f"Last {tail_lines} logs for [magenta]{KOPIAEXECUTOR_CONTAINER_NAME}[/magenta] in Pod [blue]{pod_name}[/blue]"
                    console.print(Panel(logs.strip(), title=log_title, box=box.SIMPLE_HEAD))
                else:
                    # Message printed within get_kopia_logs_from_pod if container missing or error
                    # Added a generic message here for clarity when no logs are retrieved
                    console.print(
                        f"      [grey50]Logs not retrieved for {KOPIAEXECUTOR_CONTAINER_NAME} in pod {pod_name}.[/grey50]"
                    )

    if not results_found:
        console.print(
            "\n[bold]Process complete. No kopiaexecutor logs found for any running backup jobs.[/bold]"
        )
    else:
        console.print("\n[bold]Process complete.[/bold]")


# --- Click Command --- #
@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
# PX-Backup Connection Options
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
    help="PX-Backup Organization ID. Env: PX_BACKUP_ORG_ID",
)
@click.option(
    "--token",
    required=False,
    envvar="PX_BACKUP_TOKEN",
    help="PX-Backup Authentication token. Env: PX_BACKUP_TOKEN",
)
# Token Generation Options (if --token is not provided)
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
# Filtering and Control Options
@click.option(
    "--cluster-name", required=False, help="Filter backups by cluster name (regex pattern)."
)
@click.option("--cluster-uid", required=False, help="Filter backups by a specific cluster UID.")
@click.option(
    "--tail",
    "-t",
    type=int,
    default=5,
    show_default=True,
    help="Number of recent log lines to display from kopiaexecutor container.",
)
@click.option(
    "--no-validate-certs",
    is_flag=True,
    default=False,
    help="Disable SSL certificate validation.",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(
    api_url: str,
    org_id: str,
    token: Optional[str],
    auth_url: Optional[str],
    client_id: str,
    username: Optional[str],
    password: Optional[str],
    cluster_name: Optional[str],
    cluster_uid: Optional[str],
    tail: int,
    no_validate_certs: bool,
    debug: bool,
):
    """Finds running PX backups, associated K8s jobs, and fetches kopiaexecutor logs."""
    # --- Setup Logging --- #
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Logging setup complete.")

    validate_certs = not no_validate_certs
    # ## current_token = token

    try:
        # --- Setup Clients ---
        px_client, k8s_core_v1, k8s_batch_v1 = _authenticate_and_setup_clients(
            api_url=api_url,
            token=token,  # Pass the initial token value
            validate_certs=validate_certs,
            auth_url=auth_url,
            client_id=client_id,
            username=username,
            password=password,
        )

        # --- Determine Target Cluster UID ---
        target_cluster_uid = _determine_target_cluster_uid(
            px_client, org_id, cluster_name, cluster_uid
        )

        console.print("[bold]Starting backup job log fetch process...[/bold]")

        # --- Call the main workflow function ---
        _process_backup_logs(
            px_client=px_client,
            org_id=org_id,
            k8s_core_v1=k8s_core_v1,
            k8s_batch_v1=k8s_batch_v1,
            tail_lines=tail,
            cluster_filter_uid=target_cluster_uid,  # Pass the determined UID
        )

    except click.ClickException as e:
        # Log the click exception message as an error
        logger.error(f"CLI Error: {e}")
        # Click automatically prints the error message and exits
        raise  # Re-raise to let Click handle the exit
    except ApiException as e:
        logger.error(f"Kubernetes API Error: {e.status} - {e.reason}\nBody: {e.body}")
        console.print(f"[bold red]Kubernetes API Error:[/bold red] {e.reason} (Status: {e.status})")
    except requests.exceptions.RequestException as e:
        logger.error(f"PX-Backup API Request Error: {e}")
        console.print(f"[bold red]PX-Backup API Request Error:[/bold red] {e}")
    except Exception as e:
        logger.exception("An unexpected error occurred.")
        console.print(f"[bold red]An unexpected error occurred:[/bold red] {e}")


if __name__ == "__main__":
    main()
