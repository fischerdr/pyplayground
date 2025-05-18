#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vault Path Traversal Tool.

This script helps traverse and list secrets in a Vault instance.

Example Usage:
    python vault-pathtraversal.py --url="https://vault.example.com" --token="s.1234567890" --path="secret/data"
"""

import logging
from pathlib import Path
from typing import List, Optional

import click
import hvac

from utils.logging_utils import setup_logging
from utils.vault_utils import (
    collect_secrets,
    create_vault_client,
    get_token_info,
    validate_path_access,
)

logger = logging.getLogger(__name__)

# Create a specific logger for hvac client operations
hvac_logger = logging.getLogger("hvac.client")
hvac_logger.setLevel(logging.DEBUG)


def _initialize_vault_client(
    url: Optional[str],
    token: Optional[str],
    namespace: Optional[str],
    verify: Optional[str],
) -> hvac.Client:
    """Initialize and return an authenticated Vault client."""
    try:
        client = create_vault_client(url=url, token=token, namespace=namespace, verify=verify)
        logger.debug("Vault client initialized successfully.")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize Vault client: {str(e)}")
        raise  # Re-raise the exception to be caught by the main error handler


def _display_token_info(client: hvac.Client) -> None:
    """Display detailed information about the current Vault token."""
    token_info = get_token_info(client)
    if token_info:
        click.echo("\nToken Information:")
        click.echo("-" * 20)
        for key, value in token_info.items():
            click.echo(f"{key}: {value}")
    else:
        click.echo("Could not retrieve token information.")


def _get_vaults_to_traverse(
    client: hvac.Client, path: Optional[str], mount_point: str
) -> List[tuple[str, str]]:
    """Determine the list of (mount_point, base_path) tuples to traverse."""
    vaults_to_traverse: List[tuple[str, str]] = []
    if path:
        if not validate_path_access(client, path, mount_point):
            click.echo(f"Unable to access path: {mount_point}/{path}")
            click.echo("Please verify:")
            click.echo("1. The path exists and is a valid KV v2 secrets path")
            click.echo("2. Your token has the required permissions")
            click.echo("3. The namespace is correct (if using namespaces)")
            return []  # Return empty list to indicate failure
        vaults_to_traverse.append((mount_point, path.rstrip("/")))
    else:
        try:
            mounts = client.sys.list_mounted_secrets_engines()["data"]
            for mount, details in mounts.items():
                if details["type"] == "kv" and details.get("options", {}).get("version") == "2":
                    mount_p = mount.rstrip("/")
                    if validate_path_access(client, "", mount_p):
                        vaults_to_traverse.append((mount_p, ""))
                    else:
                        logger.info(f"Skipping inaccessible mount: {mount_p}")

            if not vaults_to_traverse:
                click.echo("No accessible KV v2 secret mounts found.")
                click.echo(
                    "Please verify your token has the required permissions to list mounts and access KV v2 engines."
                )
                return []  # Return empty list
        except Exception as e:
            if "permission denied" in str(e).lower():
                logger.error(
                    "Permission denied when listing secret engines. Please check your token permissions."
                )
            else:
                logger.error(f"Error listing secret engines: {str(e)}")
            return []  # Return empty list

    return vaults_to_traverse


def _traverse_and_display_secrets(client: hvac.Client, vaults: List[tuple[str, str]]) -> None:
    """Traverse specified vaults and display the secrets found."""
    if not vaults:
        logger.info("No vaults provided for traversal.")
        return

    for mp, base_p in vaults:
        secrets_list: List[str] = []
        try:
            collect_secrets(client, base_p, mp, secrets_list)

            if secrets_list:
                click.echo(f"\nSecrets found in {mp} (path: '{base_p if base_p else '/'}'):")
                for secret_path_item in secrets_list:
                    click.echo(f"  {secret_path_item}")
            else:
                click.echo(f"\nNo secrets found in {mp} (path: '{base_p if base_p else '/'}')")
        except Exception as e:
            logger.error(f"Error collecting secrets from {mp} at path '{base_p}': {str(e)}")
            # Optionally, continue to the next vault or re-raise


@click.command()
@click.option("--url", default=None, help="Vault server URL")
@click.option("--token", default=None, help="Vault token or path to token file")
@click.option("--username", default=None, help="Username for Vault login")
@click.option("--path", default=None, help="Starting path for traversal")
@click.option("--mount-point", default="", help="KV store mount point")
@click.option("--namespace", default=None, help="Vault namespace")
@click.option("--cert", default=None, help="Path to SSL certificate (PEM) file for verification")
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging")
@click.option(
    "--show-token-info", is_flag=True, help="Show detailed token information and permissions"
)
def main(
    url: Optional[str],
    token: Optional[str],
    username: Optional[str],
    path: Optional[str],
    mount_point: str,
    namespace: Optional[str],
    cert: Optional[str],
    debug: bool = False,
    show_token_info: bool = False,
) -> None:
    """Main entry point for Vault path traversal tool.

    This function is the main entry point for the Vault path traversal tool.
    It creates a Vault client, validates the path, and traverses the Vault instance.

    Args:
        url: Vault server URL
        token: Vault token or path to token file
        username: Username for Vault login
        path: Starting path for traversal
        mount_point: KV store mount point
        namespace: Vault namespace
        cert: Path to SSL certificate (PEM) file for verification
        show_token_info: Flag to show detailed token information

    Returns:
        None

    Raises:
        Exception: If an error occurs during the Vault path traversal
    """
    script_base_name = Path(__file__).stem
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Logging setup complete.")

    try:
        # Create Vault client
        client = _initialize_vault_client(url=url, token=token, namespace=namespace, verify=cert)

        # Show token information if requested
        if show_token_info:
            _display_token_info(client)
            if not path:  # If no path specified, exit after showing token info
                return

        vaults = _get_vaults_to_traverse(client, path, mount_point)
        if not vaults:
            return  # Error messages handled in _get_vaults_to_traverse

        _traverse_and_display_secrets(client, vaults)

    except Exception as e:
        logger.error(f"Error during vault traversal: {str(e)}")
        return


if __name__ == "__main__":
    main()
