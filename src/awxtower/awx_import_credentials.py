#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to import credentials JSON into AWX."""

import sys
from pathlib import Path

import typer
from awxcli import AWX

from utils.config_utils import get_env_var, load_env_file, load_json_config
from utils.logging_utils import get_logger, setup_logging

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name="awx_import_credentials")
logger = get_logger(__name__)


def get_awx_client() -> AWX:
    """Get AWX client with credentials from environment.

    Returns:
        AWX: Initialized AWX client

    Raises:
        ValueError: If required environment variables are not set
    """
    # Load environment variables
    load_env_file()

    # Get AWX credentials from environment
    awx_host = get_env_var("AWX_HOST", required=True)
    awx_token = get_env_var("AWX_TOKEN", required=True)

    try:
        return AWX(host=awx_host, token=awx_token)
    except Exception as e:
        logger.error(f"Failed to initialize AWX client: {e}")
        raise


@app.command()
def import_creds(
    input_file: Path = typer.Option(
        "credentials.json",
        help="Input JSON file path",
        exists=True,
        dir_okay=False,
        readable=True,
    )
) -> None:
    """Import credentials from JSON into AWX.

    Args:
        input_file: Input JSON file path
    """
    try:
        # Get AWX client
        awx = get_awx_client()

        # Load credentials from file
        logger.info(f"Loading credentials from {input_file}...")
        creds_data = load_json_config(input_file)

        # Import credentials
        logger.info("Importing credentials into AWX...")
        for cred_data in creds_data:
            try:
                # Create credential
                awx.credentials.create(**cred_data)
                logger.info(f"Successfully imported credential: {cred_data.get('name')}")
            except Exception as e:
                logger.error(f"Failed to import credential {cred_data.get('name')}: {e}")
                continue

        logger.info("Credential import completed")

    except Exception as e:
        logger.error(f"Failed to import credentials: {e}")
        sys.exit(1)


if __name__ == "__main__":
    app()
