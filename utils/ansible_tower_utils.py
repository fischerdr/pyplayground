"""Utility functions for interacting with Ansible Tower/Controller API."""

import json
import logging
from time import sleep
from typing import Any, Dict, List, Optional

import requests
from requests.auth import HTTPBasicAuth

# It's better to get a logger instance per module
logger = logging.getLogger(__name__)


def get_tower_token_from_credentials(
    tower_url: str, username: str, password: str, verify: bool = True
) -> Optional[str]:
    """Obtain an API token from Tower using username and password."""
    token_url = f"{tower_url.rstrip('/')}/api/v2/tokens/"
    payload = {
        "description": "Token for run_template_restapi.py script",
        "scope": "write",
        # Not including "application" to request a personal access token (PAT)
        # If this fails, an Application with "password" grant_type might need to be created in Tower
        # and its ID passed here, or the user must generate a PAT manually.
    }
    try:
        logger.info(f"Attempting to obtain token for user '{username}' from {token_url}")
        response = requests.post(
            token_url,
            auth=HTTPBasicAuth(username, password),
            json=payload,
            verify=verify,
            timeout=30,
        )
        response.raise_for_status()
        token_data = response.json()
        access_token = token_data.get("token")
        if access_token:
            logger.info(f"Successfully obtained token for user '{username}'.")
            return access_token
        else:
            logger.error("Token request successful, but no token found in response.")
            return None
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error obtaining token: {e.response.status_code} - {e.response.text}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error obtaining token: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON response when obtaining token: {e}")
        return None


def search_resource_by_name(
    tower_url: str, headers: Dict[str, str], endpoint: str, partial_name: str, verify: bool = True
) -> Optional[List[Dict[str, Any]]]:
    """Search for a resource by partial name (e.g., job_templates, inventories)."""
    url = f"{tower_url}/api/v2/{endpoint}/?name__icontains={partial_name}"
    try:
        response = requests.get(url, headers=headers, verify=verify, timeout=30)
        response.raise_for_status()
        data = response.json()
        if data.get("count", 0) > 0:
            results = data.get("results", [])
            logger.info(f"Found {len(results)} {endpoint}(s) matching '{partial_name}':")
            for idx, resource in enumerate(results):
                logger.info(f"  [{idx + 1}] {resource.get('name')} (ID: {resource.get('id')})")
            return results
        else:
            logger.info(f"No {endpoint} found with partial name '{partial_name}'.")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to search {endpoint}: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON response when searching {endpoint}: {e}")
        return None


def select_resource(resources: Optional[List[Dict[str, Any]]], resource_type: str) -> Optional[int]:
    """Allow the user to select a resource from the list interactively."""
    if not resources:
        logger.warning(f"No {resource_type}s provided to select from.")
        return None

    if len(resources) == 1:
        selected_resource = resources[0]
        logger.info(
            f"Automatically selecting {resource_type}: "
            f"{selected_resource.get('name')} (ID: {selected_resource.get('id')})"
        )
        return selected_resource.get("id")

    logger.info(f"Please select a {resource_type} from the following list:")
    for idx, resource in enumerate(resources):
        logger.info(f"  [{idx + 1}] {resource.get('name')} (ID: {resource.get('id')})")

    while True:
        try:
            selection = input(
                f"Enter the number for the desired {resource_type} (1-{len(resources)}): "
            )
            selection_int = int(selection)
            if 1 <= selection_int <= len(resources):
                selected = resources[selection_int - 1]
                logger.info(
                    f"Selected {resource_type}: {selected.get('name')} (ID: {selected.get('id')})"
                )
                return selected.get("id")
            else:
                logger.warning(
                    f"Invalid selection. Please choose a number between 1 and {len(resources)}."
                )
        except ValueError:
            logger.warning("Invalid input. Please enter a number.")
        except KeyboardInterrupt:
            logger.info("\nSelection cancelled by user.")
            return None


def launch_job_template(
    tower_url: str,
    headers: Dict[str, str],
    job_template_id: int,
    inventory_id: Optional[int] = None,
    extra_vars: Optional[str] = None,
    verify: bool = True,
) -> Optional[Dict[str, Any]]:
    """Launch an Ansible Tower job template."""
    url = f"{tower_url}/api/v2/job_templates/{job_template_id}/launch/"
    payload: Dict[str, Any] = {}

    if inventory_id is not None:
        payload["inventory"] = inventory_id
    if extra_vars:
        try:
            payload["extra_vars"] = json.loads(extra_vars)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in extra_vars: '{extra_vars}'. Error: {e}")
            return None

    try:
        response = requests.post(url, headers=headers, json=payload, verify=verify, timeout=30)
        response.raise_for_status()
        job_data = response.json()
        logger.info(f"Job launched successfully. Job ID: {job_data.get('id')}")
        return job_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to launch job: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON response when launching job: {e}")
        return None


def monitor_job_status(
    tower_url: str, headers: Dict[str, str], job_id: int, verify: bool = True
) -> Optional[Dict[str, Any]]:
    """Monitor the status of a running job and return its details upon completion."""
    url = f"{tower_url}/api/v2/jobs/{job_id}/"
    logger.info(f"Monitoring job ID: {job_id} at {url}")

    while True:
        try:
            response = requests.get(url, headers=headers, verify=verify, timeout=30)
            response.raise_for_status()
            job_details = response.json()
            status = job_details.get("status")
            logger.info(f"Job ID {job_id} status: {status}")

            if status in ["successful", "failed", "error", "canceled"]:
                logger.info(f"Job ID {job_id} finished with status: {status}")
                return job_details

            sleep(5)  # Poll every 5 seconds
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch job status for job ID {job_id}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON for job status (ID {job_id}): {e}")
            return None
        except KeyboardInterrupt:
            logger.info(f"\nMonitoring of job ID {job_id} cancelled by user.")
            return None


def fetch_job_events(
    tower_url: str, headers: Dict[str, str], job_id: int, verify: bool = True
) -> None:
    """Fetch and log notable job events for a completed job."""
    url = f"{tower_url}/api/v2/jobs/{job_id}/job_events/"
    logger.info(f"Fetching events for job ID: {job_id}")
    try:
        response = requests.get(url, headers=headers, verify=verify, timeout=30)
        response.raise_for_status()
        events_data = response.json()
        events = events_data.get("results", [])

        if not events:
            logger.info(f"No events found for job ID {job_id}.")
            return

        for event in events:
            event_type = event.get("event")
            if event_type == "playbook_on_task_start":
                logger.info(f"  Task Started: {event.get('task')}")
            elif event_type == "runner_on_failed":
                failed_details = (
                    f"  Task Failed: {event.get('task')}\n"
                    f"    Host: {event.get('host')}\n"
                    f"    Message: {event.get('stdout', 'No stdout message').strip()}"
                )
                logger.error(failed_details)
            elif event_type == "runner_on_ok":
                # Reduce verbosity for runner_on_ok, could be many.
                # Consider logging only if a specific verbosity flag is set.
                pass  # logger.debug(f"  Task OK: {event.get('task')} on Host: {event.get('host')}")
            # Add more event types to log if needed

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch job events for job ID {job_id}: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON for job events (ID {job_id}): {e}")


def fetch_job_output(
    tower_url: str, headers: Dict[str, str], job_id: int, verify: bool = True
) -> Optional[str]:
    """Fetch the full stdout output of a completed job."""
    url = f"{tower_url}/api/v2/jobs/{job_id}/stdout/"
    logger.info(f"Fetching stdout for job ID: {job_id}")
    try:
        response = requests.get(
            url, headers=headers, params={"format": "txt"}, verify=verify, timeout=30
        )
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch job stdout for job ID {job_id}: {e}")
        return None
