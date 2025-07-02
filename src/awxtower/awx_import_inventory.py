#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to import inventories and hosts JSON into AWX."""

import json
import os
import sys
from pathlib import Path

import typer

from utils.ansible_tower_utils import (
    add_host_to_inventory,
    create_resource,
    find_resource_by_name,
    get_awx_or_tower_client,
    get_inventory_hosts,
)
from utils.logging_utils import get_logger, setup_logging

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name=os.path.basename(__file__).replace(".py", ""))
logger = get_logger(__name__)


def import_hosts_to_inventory(
    tower_url: str,
    headers: dict,
    inventory_id: int,
    hosts: list,
    inv_name: str,
    verify: bool = True,
):
    """Import a list of hosts into a given inventory."""
    for host_data in hosts:
        host_name = host_data.get("name")
        try:
            # Check if host already exists in this inventory
            existing_hosts = get_inventory_hosts(tower_url, headers, inventory_id, verify)
            host_exists = any(host.get("name") == host_name for host in existing_hosts or [])

            if not host_exists:
                created_host = add_host_to_inventory(
                    tower_url, headers, inventory_id, host_data, verify
                )
                if created_host:
                    logger.info(
                        f"Successfully imported host '{host_name}' to inventory '{inv_name}'"
                    )
                else:
                    logger.error(f"Failed to create host '{host_name}' in inventory '{inv_name}'")
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
        # Get AWX client configuration
        client_config = get_awx_or_tower_client("AWX")
        tower_url = client_config["url"]
        headers = client_config["headers"]
        verify = client_config["verify"]

        with open(input_file, "r") as f:
            inventories_data = json.load(f)

        logger.info(f"Importing {len(inventories_data)} inventories into AWX...")
        for inv_data in inventories_data:
            inv_name = inv_data.get("name")
            try:
                # Check if inventory already exists
                existing_inv = find_resource_by_name(
                    tower_url, headers, "inventories", inv_name, verify
                )

                if not existing_inv:
                    # Remove hosts from inventory data before creating inventory
                    hosts = inv_data.pop("hosts", [])
                    created_inv = create_resource(
                        tower_url, headers, "inventories", inv_data, verify
                    )
                    if created_inv:
                        inventory_id = created_inv.get("id")
                        logger.info(f"Successfully created inventory: {inv_name}")
                        # Import hosts to the newly created inventory
                        if hosts:
                            import_hosts_to_inventory(
                                tower_url, headers, inventory_id, hosts, inv_name, verify
                            )
                    else:
                        logger.error(f"Failed to create inventory: {inv_name}")
                else:
                    inventory_id = existing_inv.get("id")
                    hosts = inv_data.get("hosts", [])
                    logger.warning(f"Inventory '{inv_name}' already exists. Skipping creation.")
                    # Still import hosts to existing inventory
                    if hosts:
                        import_hosts_to_inventory(
                            tower_url, headers, inventory_id, hosts, inv_name, verify
                        )

            except Exception as e:
                logger.error(f"Failed to process inventory {inv_name}: {e}", exc_info=True)
                continue

        logger.info("Inventory import completed.")

    except Exception as e:
        logger.error(f"Failed to import inventories: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
