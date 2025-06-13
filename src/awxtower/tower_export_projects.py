#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to export Tower project definitions to JSON."""

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
        "projects.json",
        help="Output JSON file path",
        exists=False,
        dir_okay=False,
        writable=True,
    )
) -> None:
    """Export Tower project definitions to JSON."""
    try:
        tower = get_awx_or_tower_client("TOWER")
        logger.info("Fetching projects from Tower...")

        projects = [project.json for project in tower.projects.pget()]

        if not projects:
            logger.warning("No projects found in Tower.")
            sys.exit(0)

        with open(output, "w") as f:
            json.dump(projects, f, indent=2)
        logger.info(f"Successfully exported {len(projects)} projects to {output}")

    except NoContent:
        logger.warning("No projects found in Tower.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Failed to export projects: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
