#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to import inventories and hosts JSON into AWX."""

import json
import os
import sys
from pathlib import Path

import typer

from utils.ansible_tower_utils import get_awx_or_tower_client
from utils.logging_utils import get_logger, setup_logging

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name=os.path.basename(__file__).replace(".py", ""))
logger = get_logger(__name__)


def import_hosts_to_inventory(inventory, hosts, inv_name):
    """Import a list of hosts into a given inventory."""
    for host_data in hosts:
        host_name = host_data.get("name")
        try:
            if not inventory.hosts.find(name=host_name):
                inventory.hosts.create(payload=host_data)
                logger.info(f"Successfully imported host '{host_name}' to inventory '{inv_name}'")
            else:
                logger.warning(
                    f"Host '{host_name}' already exists in inventory '{inv_name}'. Skipping."
                )
        except Exception as e:
            logger.error(
                f"Failed to import host '{host_name}' to inventory '{inv_name}': {e}",
                exc_info=True,
            )
            continue


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
    """Import inventories and hosts from JSON into AWX."""
    try:
        awx = get_awx_or_tower_client("AWX")

        with open(input_file, "r") as f:
            inventories_data = json.load(f)

        logger.info(f"Importing {len(inventories_data)} inventories into AWX...")
        for inv_data in inventories_data:
            inv_name = inv_data.get("name")
            try:
                inventory = awx.inventories.find(name=inv_name)
                if not inventory:
                    hosts = inv_data.pop("hosts", [])
                    inventory = awx.inventories.create(payload=inv_data)
                    logger.info(f"Successfully created inventory: {inv_name}")
                else:
                    hosts = inv_data.get("hosts", [])
                    logger.warning(f"Inventory '{inv_name}' already exists. Skipping creation.")

                import_hosts_to_inventory(inventory, hosts, inv_name)

            except Exception as e:
                logger.error(f"Failed to process inventory {inv_name}: {e}", exc_info=True)
                continue

        logger.info("Inventory import completed.")

    except Exception as e:
        logger.error(f"Failed to import inventories: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
