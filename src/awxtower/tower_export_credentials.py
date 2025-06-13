#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to export Tower credentials to JSON."""

import sys
from pathlib import Path
from typing import Dict, List, Optional

import requests
import typer

from utils.ansible_tower_utils import get_tower_token_from_credentials
from utils.config_utils import get_env_var, load_env_file, save_json_config
from utils.logging_utils import get_logger, setup_logging

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name="tower_export_credentials")
logger = get_logger(__name__)


def get_tower_headers() -> Optional[Dict[str, str]]:
    """Get Tower API headers with token from environment or credentials.

    Returns:
        Optional[Dict[str, str]]: Headers dict with token if successful, None if failed
    """
    # Load environment variables
    load_env_file()

    # Try to get token from environment first
    tower_token = get_env_var("TOWER_TOKEN", required=False)

    # If no token in env, try to get one using credentials
    if not tower_token:
        tower_host = get_env_var("TOWER_HOST", required=True)
        username = get_env_var("TOWER_USERNAME", required=True)
        password = get_env_var("TOWER_PASSWORD", required=True)

        tower_token = get_tower_token_from_credentials(
            tower_url=tower_host, username=username, password=password, verify=True
        )

        if not tower_token:
            logger.error("Failed to obtain Tower token")
            return None

    return {"Authorization": f"Bearer {tower_token}", "Content-Type": "application/json"}


def get_credentials(tower_url: str, headers: Dict[str, str]) -> Optional[List[Dict]]:
    """Get all credentials from Tower.

    Args:
        tower_url: Tower API URL
        headers: API request headers

    Returns:
        Optional[List[Dict]]: List of credential dicts if successful, None if failed
    """
    url = f"{tower_url.rstrip('/')}/api/v2/credentials/"
    try:
        response = requests.get(url, headers=headers, verify=True, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch credentials: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching credentials: {e}")
        return None


@app.command()
def export(
    output: Path = typer.Option(
        "credentials.json",
        help="Output JSON file path",
        exists=False,
        dir_okay=False,
        writable=True,
    )
) -> None:
    """Export Tower credentials to JSON.

    Args:
        output: Output JSON file path
    """
    try:
        # Get Tower URL and headers
        tower_url = get_env_var("TOWER_HOST", required=True)
        headers = get_tower_headers()

        if not headers:
            logger.error("Failed to get Tower API headers")
            sys.exit(1)

        # Get credentials
        logger.info("Fetching credentials from Tower...")
        creds = get_credentials(tower_url, headers)

        if not creds:
            logger.error("No credentials found or failed to fetch credentials")
            sys.exit(1)

        # Save to file
        save_json_config(creds, output)
        logger.info(f"Successfully exported {len(creds)} credentials to {output}")

    except Exception as e:
        logger.error(f"Failed to export credentials: {e}")
        sys.exit(1)


if __name__ == "__main__":
    app()
