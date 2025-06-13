#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to import project definitions into AWX."""

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
def import_projects(
    input_file: Path = typer.Option(
        "projects.json",
        help="Input JSON file path",
        exists=True,
        dir_okay=False,
        readable=True,
    )
) -> None:
    """Import project definitions from JSON into AWX."""
    try:
        awx = get_awx_or_tower_client("AWX")

        with open(input_file, "r") as f:
            projects_data = json.load(f)

        logger.info(f"Importing {len(projects_data)} projects into AWX...")
        for project_data in projects_data:
            project_name = project_data.get("name")
            try:
                if not awx.projects.find(name=project_name):
                    awx.projects.create(payload=project_data)
                    logger.info(f"Successfully imported project: {project_name}")
                else:
                    logger.warning(f"Project '{project_name}' already exists. Skipping.")
            except Exception as e:
                logger.error(f"Failed to import project {project_name}: {e}", exc_info=True)
                continue

        logger.info("Project import completed.")

    except Exception as e:
        logger.error(f"Failed to import projects: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
