#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to export Tower credentials to JSON."""

import sys
from pathlib import Path

import typer
from awxcli import Tower

from utils.logging_utils import setup_logging, get_logger
from utils.config_utils import load_env_file, get_env_var, save_json_config

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name="tower_export_credentials")
logger = get_logger(__name__)


def get_tower_client() -> Tower:
    """Get Tower client with credentials from environment.
    
    Returns:
        Tower: Initialized Tower client
        
    Raises:
        ValueError: If required environment variables are not set
    """
    # Load environment variables
    load_env_file()
    
    # Get Tower credentials from environment
    tower_host = get_env_var("TOWER_HOST", required=True)
    tower_token = get_env_var("TOWER_TOKEN", required=True)
    
    try:
        return Tower(host=tower_host, token=tower_token)
    except Exception as e:
        logger.error(f"Failed to initialize Tower client: {e}")
        raise


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
        # Get Tower client
        tower = get_tower_client()
        
        # Get credentials
        logger.info("Fetching credentials from Tower...")
        creds = tower.credentials.list()
        
        # Convert to dict for JSON serialization
        creds_data = [cred.dict() for cred in creds]
        
        # Save to file
        save_json_config(creds_data, output)
        logger.info(f"Successfully exported {len(creds_data)} credentials to {output}")
        
    except Exception as e:
        logger.error(f"Failed to export credentials: {e}")
        sys.exit(1)


if __name__ == "__main__":
    app() 