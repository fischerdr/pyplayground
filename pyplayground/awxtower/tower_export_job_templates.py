#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to export Tower job templates and workflows to JSON."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer

from pyplayground.utils.ansible_tower_utils import (
    export_all_resources,
    get_awx_or_tower_client,
)
from pyplayground.utils.logging_utils import get_logger, setup_logging

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
    verify: bool = typer.Option(True, help="Verify the connection to Tower"),
    search: Optional[str] = typer.Option(None, help="Search term for filtering workflows"),
    order_by: Optional[str] = typer.Option(
        None, help="Sort workflows by field (e.g., 'name', '-name')"
    ),
) -> None:
    """Export Tower job templates and workflows to JSON.

    This function fetches job templates and workflows from Tower, sorts them alphabetically by name,
    and then exports them to a specified JSON file. It handles logging throughout the process to provide feedback
    about the operations being performed.

    Args:
        output: Path to the output JSON file where job templates and workflows will be exported.
        include_workflows: Boolean flag indicating whether to include workflow job templates in the export.
        verify: Boolean flag indicating whether to verify the connection to Tower.
        search: Search term for filtering workflows.
        order_by: Sort workflows by field (e.g., 'name', '-name').
    """
    try:
        # Get Tower client configuration
        client_config = get_awx_or_tower_client("TOWER", verify=verify)
        tower_url = client_config["url"]
        headers = client_config["headers"]
        verify = client_config["verify"]

        logger.info("Fetching job templates from Tower...")
        job_templates = export_all_resources(tower_url, headers, "job_templates", verify)
        if job_templates is None:
            logger.error("Failed to fetch job templates from Tower.")
            print("Failed to fetch job templates from Tower.")
            return

        workflows: List[Dict[str, Any]] = []
        if include_workflows:
            logger.info("Fetching workflow job templates from Tower...")

            # Build query parameters for workflow API
            params = {}
            if search:
                params["search"] = search
            if order_by:
                params["order_by"] = order_by

            workflows_result = export_all_resources(
                tower_url, headers, "workflow_job_templates", verify, params
            )
            if workflows_result is None:
                logger.error("Failed to fetch workflows from Tower.")
                print("Failed to fetch workflows from Tower.")
            else:
                workflows = workflows_result

        if not job_templates and not workflows:
            logger.warning("No job templates or workflows found in Tower.")
            print("No job templates or workflows found in Tower.")
            return

        # Sort job templates and workflows by name (case-insensitive)
        sorted_job_templates = sorted(job_templates, key=lambda x: x.get("name", "").lower())
        sorted_workflows = sorted(workflows, key=lambda x: x.get("name", "").lower())

        export_data = {
            "job_templates": sorted_job_templates,
            "workflows": sorted_workflows,
        }

        # Export data to JSON file
        with open(output, "w") as f:
            json.dump(export_data, f, indent=2)
        logger.info(
            f"Successfully exported {len(sorted_job_templates)} job templates and "
            f"{len(sorted_workflows)} workflows to {output}"
        )
        print(
            f"Successfully exported {len(sorted_job_templates)} job templates and {len(sorted_workflows)} workflows to {output}"
        )

    except Exception as e:
        logger.error(f"Failed to export job templates: {e}", exc_info=True)
        print(f"An error occurred while exporting data: {e}")


if __name__ == "__main__":
    app()
