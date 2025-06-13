#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to import schedules into AWX."""

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


@app.command()
def import_schedules(
    input_file: Path = typer.Option(
        "schedules.json",
        help="Input JSON file path",
        exists=True,
        dir_okay=False,
        readable=True,
    )
) -> None:
    """Import schedules from JSON into AWX."""
    try:
        awx = get_awx_or_tower_client("AWX")

        with open(input_file, "r") as f:
            schedules_data = json.load(f)

        logger.info(f"Importing {len(schedules_data)} schedules into AWX...")
        for schedule_data in schedules_data:
            schedule_name = schedule_data.get("name")
            try:
                # Note: awxkit does not have a .find() for schedules.
                # A simple check by name is performed here.
                # More robust checking may require iterating over existing schedules.
                existing = awx.schedules.get(name=schedule_name)
                if not existing.results:
                    awx.schedules.create(payload=schedule_data)
                    logger.info(f"Successfully imported schedule: {schedule_name}")
                else:
                    logger.warning(f"Schedule '{schedule_name}' already exists. Skipping.")
            except Exception as e:
                logger.error(f"Failed to import schedule {schedule_name}: {e}", exc_info=True)
                continue

        logger.info("Schedule import completed.")

    except Exception as e:
        logger.error(f"Failed to import schedules: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
