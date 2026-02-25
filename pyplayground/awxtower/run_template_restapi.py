#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""This module provides a command-line interface to launch Ansible Tower job templates."""

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

import click
import urllib3

from pyplayground.utils.ansible_tower_utils import (
    fetch_job_events,
    fetch_job_output,
    get_tower_token_from_credentials,
    launch_job_template,
    monitor_job_status,
    search_resource_by_name,
    select_resource,
)
from pyplayground.utils.config_utils import load_env_file
from pyplayground.utils.logging_utils import setup_logging

# Disable SSL warnings - due to self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Logging Setup ---
logger = logging.getLogger(__name__)
# Basic logging configuration (can be enhanced)
# logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load environment variables using the utility function
load_env_file()


def _resolve_resource_ids(
    tower_url: str,
    headers: Dict[str, str],
    template_name: str,
    inventory_name: str,
    interactive: bool,
    verify: bool,
) -> Tuple[Optional[int], Optional[int]]:
    """Finds and selects job template and inventory IDs.

    Args:
        tower_url: The URL of the Ansible Tower/Controller API.
        headers: The headers for the API request.
        template_name: The partial name of the job template.
        inventory_name: The partial name of the inventory.
        interactive: Whether to interactively select the job template and inventory.
        verify: SSL verification flag for requests.

    Returns:
        A tuple containing the job template ID and inventory ID.
        If the job template or inventory is not found, returns None for the respective ID.
    """
    job_templates = search_resource_by_name(tower_url, headers, "job_templates", template_name, verify=verify)
    inventories = search_resource_by_name(tower_url, headers, "inventories", inventory_name, verify=verify)

    job_template_id: Optional[int] = None
    inventory_id: Optional[int] = None

    if interactive:
        job_template_id = select_resource(job_templates, "job template")
        inventory_id = select_resource(inventories, "inventory")
    else:
        if job_templates and len(job_templates) > 0:
            job_template_id = job_templates[0].get("id")
            if job_template_id:
                logger.info(f"Automatically selected job template: {job_templates[0].get('name')} (ID: {job_template_id})")
            else:
                logger.error(f"Could not determine ID for job template matching '{template_name}'.")
        else:
            logger.error(f"No job template found matching '{template_name}'.")

        if inventories and len(inventories) > 0:
            inventory_id = inventories[0].get("id")
            if inventory_id:
                logger.info(f"Automatically selected inventory: {inventories[0].get('name')} (ID: {inventory_id})")
            else:
                logger.error(f"Could not determine ID for inventory matching '{inventory_name}'.")
        else:
            logger.error(f"No inventory found matching '{inventory_name}'.")

    return job_template_id, inventory_id


def _execute_and_manage_job(
    tower_url: str,
    headers: Dict[str, str],
    job_template_id: int,
    inventory_id: int,
    extra_vars: str,
    output_file: Optional[str],
    verify_ssl: bool,
) -> None:
    """Launches, monitors, and processes the job results."""
    job_details = launch_job_template(
        tower_url,
        headers,
        job_template_id,
        inventory_id=inventory_id,
        extra_vars=extra_vars,
        verify=verify_ssl,
    )

    if job_details and job_details.get("id"):
        job_id = job_details.get("id")
        final_job_details = monitor_job_status(tower_url, headers, job_id, verify=verify_ssl)
        if final_job_details:
            fetch_job_events(tower_url, headers, job_id, verify=verify_ssl)
            if output_file:
                output = fetch_job_output(tower_url, headers, job_id, verify=verify_ssl)
                if output is not None:
                    try:
                        with open(output_file, "w", encoding="utf-8") as f:
                            f.write(output)
                        logger.info(f"Job output saved to {output_file}")
                    except IOError as e:
                        logger.error(f"Failed to write job output to {output_file}: {e}")
                else:
                    logger.warning(f"No output content fetched for job ID {job_id} to save to {output_file}.")
            final_status = final_job_details.get("status")
            logger.info(f"Job ID {job_id} completed with final status: {final_status}")
        else:
            logger.error(f"Failed to monitor job ID {job_id} to completion or monitoring was cancelled.")
    elif job_details is None and extra_vars != "{}":
        logger.error("Job launch failed. This might be due to invalid extra_vars. Please check the format.")
    else:
        logger.error("Job launch failed or job details are incomplete.")


@click.command()
@click.option(
    "--tower-url",
    envvar="TOWER_URL",
    required=False,
    help="Ansible Tower/Controller URL. Can also be set via TOWER_URL env var.",
)
@click.option(
    "--token",
    envvar="TOWER_TOKEN",
    required=False,
    help="API Token for authentication. Can also be set via TOWER_TOKEN env var.",
)
@click.option(
    "--tower-user",
    "tower_user",
    envvar="TOWER_USER",
    required=False,
    help="Ansible Tower username. Can also be set via TOWER_USER env var.",
)
@click.option(
    "--tower-password",
    "tower_password",
    envvar="TOWER_PASSWORD",
    required=False,
    help="Ansible Tower password. Can also be set via TOWER_PASSWORD env var.",
    hide_input=True,
)
@click.option("--template-name", required=True, help="Partial name of the job template.")
@click.option("--inventory-name", required=True, help="Partial name of the inventory.")
@click.option("--extra-vars", default="{}", help='Extra variables as JSON string (e.g., \'{"key": "value"}\')')
@click.option(
    "--interactive",
    is_flag=True,
    help="Enable interactive mode for selecting templates and inventories.",
)
@click.option(
    "--output-file",
    default=None,
    type=click.Path(dir_okay=False, writable=True),
    help="File to save job output.",
)
@click.option("--insecure", is_flag=True, default=False, help="Disable SSL certificate verification.")
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def run_job(
    tower_url: Optional[str],
    token: Optional[str],
    tower_user: Optional[str],
    tower_password: Optional[str],
    template_name: str,
    inventory_name: str,
    extra_vars: str,
    interactive: bool,
    output_file: Optional[str],
    insecure: bool,
    debug: bool,
):
    """Launch an Ansible Tower job template with specified parameters."""
    script_base_name = Path(__file__).stem
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Logging setup complete.")

    verify_ssl = not insecure
    if insecure:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.warning("SSL certificate verification is disabled.")

    # Validate TOWER_URL
    if not tower_url:
        logger.error("Tower URL not provided. Set TOWER_URL environment variable or use --tower-url option.")
        return

    final_token = token
    if not final_token:
        if tower_user and tower_password:
            logger.info(f"No token provided, attempting to fetch token for user '{tower_user}'.")
            final_token = get_tower_token_from_credentials(tower_url, tower_user, tower_password, verify=verify_ssl)
            if not final_token:
                logger.error("Failed to obtain token using user credentials. Exiting.")
                return
        else:
            logger.error("Authentication required: Provide TOWER_TOKEN, or TOWER_USER and TOWER_PASSWORD. Exiting.")
            return

    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {final_token}",
    }

    job_template_id, inventory_id = _resolve_resource_ids(tower_url, headers, template_name, inventory_name, interactive, verify=verify_ssl)

    if not job_template_id:
        logger.error("Job template ID not determined or selected. Exiting.")
        return
    if not inventory_id:
        logger.error("Inventory ID not determined or selected. Exiting.")
        return

    # Call the new helper function to execute and manage the job
    _execute_and_manage_job(
        tower_url,
        headers,
        job_template_id,
        inventory_id,
        extra_vars,
        output_file,
        verify_ssl,
    )


if __name__ == "__main__":
    run_job()
