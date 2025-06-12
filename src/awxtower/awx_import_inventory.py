#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to import inventories and hosts JSON into AWX."""

import sys
from pathlib import Path

import typer
from awxcli import AWX

from utils.logging_utils import setup_logging, get_logger
from utils.config_utils import load_env_file, get_env_var, load_json_config

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name="awx_import_inventory")
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
def import_inventory(
    input_file: Path = typer.Option(
        "inventory.json",
        help="Input JSON file path",
        exists=True,
        dir_okay=False,
        readable=True,
    )
) -> None:
    """Import inventories and hosts from JSON into AWX.
    
    Args:
        input_file: Input JSON file path
    """
    try:
        # Get AWX client
        awx = get_awx_client()
        
        # Load inventories from file
        logger.info(f"Loading inventories from {input_file}...")
        inventories_data = load_json_config(input_file)
        
        # Import inventories and hosts
        logger.info("Importing inventories and hosts into AWX...")
        for inventory_data in inventories_data:
            try:
                # Extract hosts before creating inventory
                hosts = inventory_data.pop("hosts", [])
                
                # Create inventory
                inventory = awx.inventories.create(**inventory_data)
                logger.info(f"Successfully imported inventory: {inventory_data.get('name')}")
                
                # Create hosts
                for host_data in hosts:
                    try:
                        # Add inventory ID to host data
                        host_data["inventory"] = inventory.id
                        
                        # Create host
                        awx.hosts.create(**host_data)
                        logger.info(f"Successfully imported host: {host_data.get('name')}")
                    except Exception as e:
                        logger.error(f"Failed to import host {host_data.get('name')}: {e}")
                        continue
                
            except Exception as e:
                logger.error(f"Failed to import inventory {inventory_data.get('name')}: {e}")
                continue
        
        logger.info("Inventory import completed")
        
    except Exception as e:
        logger.error(f"Failed to import inventories: {e}")
        sys.exit(1)


if __name__ == "__main__":
    app() 