#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to export Tower inventories and hosts to JSON."""

import json
import os
import sys
from pathlib import Path

import typer
from awxkit.exceptions import NoContent

from utils.ansible_tower_utils import get_awx_or_tower_client
from utils.logging_utils import get_logger, setup_logging

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name=os.path.basename(__file__).replace(".py", ""))
logger = get_logger(__name__)


@app.command()
def export(
    output: Path = typer.Option(
        "inventory.json",
        help="Output JSON file path",
        exists=False,
        dir_okay=False,
        writable=True,
    )
) -> None:
    """Export Tower inventories and hosts to JSON."""
    try:
        tower = get_awx_or_tower_client("TOWER")
        logger.info("Fetching inventories from Tower...")

        inventories_data = []
        for inventory in tower.inventories.pget():
            inventory_json = inventory.json
            logger.info(f"Fetching hosts for inventory: {inventory.name}")
            hosts = [h.json for h in inventory.hosts.pget()]
            inventory_json["hosts"] = hosts
            inventories_data.append(inventory_json)

        if not inventories_data:
            logger.warning("No inventories found in Tower.")
            sys.exit(0)

        with open(output, "w") as f:
            json.dump(inventories_data, f, indent=2)
        logger.info(f"Successfully exported {len(inventories_data)} inventories to {output}")

    except NoContent:
        logger.warning("No inventories found in Tower.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Failed to export inventories: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
