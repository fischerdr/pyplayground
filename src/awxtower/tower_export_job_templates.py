#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to export Tower job templates and workflows to JSON."""

import json
import os
import sys
from pathlib import Path

import typer

from utils.ansible_tower_utils import get_awx_or_tower_client, list_resources
from utils.logging_utils import get_logger, setup_logging

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name=os.path.basename(__file__).replace(".py", ""))
logger = get_logger(__name__)


@app.command()
def export(
    output: Path = typer.Option(
        "job_templates.json",
        help="Output JSON file path",
        exists=False,
        dir_okay=False,
        writable=True,
    ),
    include_workflows: bool = typer.Option(True, help="Include workflow job templates in export"),
) -> None:
    """Export Tower job templates and workflows to JSON."""
    try:
        # Get Tower client configuration
        client_config = get_awx_or_tower_client("TOWER")
        tower_url = client_config["url"]
        headers = client_config["headers"]
        verify = client_config["verify"]

        logger.info("Fetching job templates from Tower...")
        job_templates = list_resources(tower_url, headers, "job_templates", verify)

        workflows = []
        if include_workflows:
            logger.info("Fetching workflow job templates from Tower...")
            workflows = list_resources(tower_url, headers, "workflow_job_templates", verify)

        if not job_templates and not workflows:
            logger.warning("No job templates or workflows found in Tower.")
            sys.exit(0)

        export_data = {
            "job_templates": job_templates,
            "workflows": workflows,
        }

        with open(output, "w") as f:
            json.dump(export_data, f, indent=2)
        logger.info(
            f"Successfully exported {len(job_templates)} job templates and "
            f"{len(workflows)} workflows to {output}"
        )

    except Exception as e:
        logger.error(f"Failed to export job templates: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
