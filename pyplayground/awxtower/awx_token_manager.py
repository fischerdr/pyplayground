#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""This module provides functionality to manage AWX/Tower authentication tokens."""

import re
from pathlib import Path
from typing import Optional

import click
import urllib3

from pyplayground.utils.ansible_tower_utils import get_tower_token_from_credentials

# Disable SSL warnings - due to self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def update_env_file(env_path: str, key: str, value: str) -> None:
    """Update or add a key-value pair in the .env file.

    Args:
        env_path: Path to the .env file
        key: Environment variable key
        value: Environment variable value
    """
    env_path = Path(env_path)

    # Create .env file if it doesn't exist
    if not env_path.exists():
        env_path.touch()

    # Read existing content
    content = env_path.read_text()

    # Check if key exists
    pattern = rf"^{key}=.*$"
    if re.search(pattern, content, re.MULTILINE):
        # Update existing key
        new_content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
    else:
        # Add new key
        new_content = f"{content}\n{key}={value}\n"

    # Write back to file
    env_path.write_text(new_content)


def get_token(tower_url: str, username: str, password: str, verify_ssl: bool = True) -> Optional[str]:
    """Get authentication token from AWX/Tower.

    Args:
        tower_url: The URL of the AWX/Tower instance
        username: Username for authentication
        password: Password for authentication
        verify_ssl: Whether to verify SSL certificates

    Returns:
        Authentication token if successful, None otherwise
    """
    try:
        # Use the existing utility function
        token = get_tower_token_from_credentials(tower_url, username, password, verify_ssl)
        return token

    except Exception as e:
        click.echo(f"Error: Failed to get token - {str(e)}", err=True)
        return None


@click.command()
@click.option(
    "--tower-url",
    envvar="TOWER_URL",
    required=True,
    help="AWX/Tower URL. Can also be set via TOWER_URL env var.",
)
@click.option(
    "--username",
    envvar="TOWER_USER",
    required=True,
    help="AWX/Tower username. Can also be set via TOWER_USER env var.",
)
@click.option(
    "--password",
    envvar="TOWER_PASSWORD",
    required=True,
    prompt=True,
    hide_input=True,
    help="AWX/Tower password. Can also be set via TOWER_PASSWORD env var.",
)
@click.option(
    "--env-file",
    default=".env",
    help="Path to .env file (default: .env)",
)
@click.option(
    "--insecure",
    is_flag=True,
    default=False,
    help="Disable SSL certificate verification.",
)
def main(
    tower_url: str,
    username: str,
    password: str,
    env_file: str,
    insecure: bool,
) -> None:
    """Get AWX/Tower authentication token and update .env file."""
    # Get token
    token = get_token(tower_url, username, password, not insecure)

    if token:
        # Update .env file
        update_env_file(env_file, "TOWER_TOKEN", token)
        click.echo(f"Successfully updated token in {env_file}")
    else:
        raise click.Abort()


if __name__ == "__main__":
    main()
