#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Update AAP (Ansible Automation Platform) credential fields.

This script provides functionality to update specific fields in AAP custom credentials
using the AAP REST API. It supports environment-based configuration and proper logging.
"""

import json
import logging
import os
import sys
from typing import Any, Dict, Optional

import click

from pyplayground.utils.ansible_tower_utils import (
    get_awx_or_tower_client,
    get_resource,
    update_resource,
)
from pyplayground.utils.config_utils import load_env_file
from pyplayground.utils.logging_utils import get_logger, setup_logging

# Setup logging
logger = get_logger(__name__)


def update_aap_credential_field(
    aap_host: str,
    username: str,
    password: str,
    credential_id: int,
    field_name: str,
    new_value: str,
    verify_ssl: bool = True,
) -> Optional[Dict[str, Any]]:
    """Update a single field in an AAP custom credential.

    Args:
        aap_host: The AAP server URL (e.g., 'https://aap-server.example.com')
        username: AAP username
        password: AAP password
        credential_id: ID of the credential to update
        field_name: Name of the field to update
        new_value: New value for the field
        verify_ssl: Whether to verify SSL certificates

    Returns:
        Response from AAP API or None if failed
    """
    logger.info(f"Updating credential {credential_id}, field '{field_name}'")

    # Get authenticated client using ansible_tower_utils
    try:
        # Set environment variables for the client
        os.environ["AAP_HOST"] = aap_host
        os.environ["AAP_USERNAME"] = username
        os.environ["AAP_PASSWORD"] = password

        client_config = get_awx_or_tower_client("AAP", verify=verify_ssl)
        tower_url = client_config["url"]
        headers = client_config["headers"]

        logger.debug(f"Using authenticated client for {tower_url}")
    except Exception as e:
        logger.error(f"Failed to get authenticated client: {e}")
        return None

    # Get current credential data
    current_data = get_resource(
        tower_url=tower_url,
        headers=headers,
        endpoint="credentials",
        resource_id=credential_id,
        verify=verify_ssl,
    )

    if not current_data:
        logger.error(f"Failed to retrieve credential {credential_id}")
        return None

    logger.debug(f"Retrieved current credential data: {current_data.get('name', 'Unknown')}")

    # Update only the specified field
    if field_name in current_data.get("inputs", {}):
        old_value = current_data["inputs"][field_name]
        current_data["inputs"][field_name] = new_value
        logger.info(f"Updating field '{field_name}': '{old_value}' -> '{new_value}'")
    else:
        # If field doesn't exist in inputs, create it
        current_data["inputs"] = current_data.get("inputs", {})
        current_data["inputs"][field_name] = new_value
        logger.info(f"Adding new field '{field_name}' with value '{new_value}'")

    # Prepare the update payload (only send modified fields)
    payload = {"inputs": current_data["inputs"]}

    # Update the credential using ansible_tower_utils
    result = update_resource(
        tower_url=tower_url,
        headers=headers,
        endpoint="credentials",
        resource_id=credential_id,
        payload=payload,
        verify=verify_ssl,
    )

    if result:
        logger.info(f"Successfully updated credential {credential_id}")
    else:
        logger.error(f"Failed to update credential {credential_id}")

    return result


@click.command()
@click.option(
    "--aap-host",
    envvar="AAP_HOST",
    help="AAP server URL (default: from AAP_HOST env var)",
    required=True,
)
@click.option(
    "--username",
    envvar="AAP_USERNAME",
    help="AAP username (default: from AAP_USERNAME env var)",
    required=True,
)
@click.option(
    "--password",
    envvar="AAP_PASSWORD",
    help="AAP password (default: from AAP_PASSWORD env var)",
    required=True,
)
@click.option(
    "--credential-id",
    type=int,
    help="ID of the credential to update",
    required=True,
)
@click.option(
    "--field-name",
    help="Name of the field to update",
    required=True,
)
@click.option(
    "--new-value",
    help="New value for the field",
    required=True,
)
@click.option(
    "--verify-ssl/--no-verify-ssl",
    default=True,
    help="Whether to verify SSL certificates (default: True)",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
def main(
    aap_host: str,
    username: str,
    password: str,
    credential_id: int,
    field_name: str,
    new_value: str,
    verify_ssl: bool,
    debug: bool,
) -> None:
    r"""Update AAP credential field.

    This script updates a specific field in an AAP custom credential using the AAP REST API.
    Configuration can be provided via command line arguments or environment variables.

    Examples:
        # Using command line arguments
        python aap_updatecredential.py --aap-host https://aap.example.com \\
            --username admin --password secret --credential-id 123 \\
            --field-name api_key --new-value new_key_value

        # Using environment variables
        export AAP_HOST=https://aap.example.com
        export AAP_USERNAME=admin
        export AAP_PASSWORD=secret
        python aap_updatecredential.py --credential-id 123 \\
            --field-name api_key --new-value new_key_value
    """
    # Setup logging
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Starting AAP credential update script.")

    # Load environment file if it exists
    try:
        load_env_file()
        logger.debug("Loaded environment variables from .env file")
    except Exception as e:
        logger.debug(f"Could not load .env file: {e}")

    # Update the credential
    result = update_aap_credential_field(
        aap_host=aap_host,
        username=username,
        password=password,
        credential_id=credential_id,
        field_name=field_name,
        new_value=new_value,
        verify_ssl=verify_ssl,
    )

    if result:
        click.echo("Credential updated successfully!")
        if debug:
            click.echo(json.dumps(result, indent=2))
    else:
        click.echo("Failed to update credential", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
