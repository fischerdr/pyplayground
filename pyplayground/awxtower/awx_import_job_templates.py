#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to import job templates and workflows into AWX."""

import json
import os
import sys
from pathlib import Path

import typer

from pyplayground.utils.ansible_tower_utils import (
    create_resource,
    find_resource_by_name,
    get_awx_or_tower_client,
)
from pyplayground.utils.logging_utils import get_logger, setup_logging

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name=os.path.basename(__file__).replace(".py", ""))
logger = get_logger(__name__)


def import_job_templates_from_data(
    tower_url: str, headers: dict, job_templates: list, verify: bool = True
):
    """Import job templates into AWX from a list of data."""
    logger.info(f"Importing {len(job_templates)} job templates into AWX...")
    for template_data in job_templates:
        template_name = template_data.get("name")
        try:
            # Check if job template already exists
            existing_template = find_resource_by_name(
                tower_url, headers, "job_templates", template_name, verify
            )
            if not existing_template:
                created_template = create_resource(
                    tower_url, headers, "job_templates", template_data, verify
                )
                if created_template:
                    logger.info(f"Successfully imported job template: {template_name}")
                else:
                    logger.error(f"Failed to create job template: {template_name}")
            else:
                logger.warning(f"Job template '{template_name}' already exists. Skipping.")
        except Exception as e:
            logger.error(f"Failed to import job template {template_name}: {e}", exc_info=True)
            continue


def import_workflows_from_data(tower_url: str, headers: dict, workflows: list, verify: bool = True):
    """Import workflows into AWX from a list of data."""
    logger.info(f"Importing {len(workflows)} workflows into AWX...")
    for workflow_data in workflows:
        workflow_name = workflow_data.get("name")
        try:
            # Check if workflow already exists
            existing_workflow = find_resource_by_name(
                tower_url, headers, "workflow_job_templates", workflow_name, verify
            )
            if not existing_workflow:
                created_workflow = create_resource(
                    tower_url, headers, "workflow_job_templates", workflow_data, verify
                )
                if created_workflow:
                    logger.info(f"Successfully imported workflow: {workflow_name}")
                else:
                    logger.error(f"Failed to create workflow: {workflow_name}")
            else:
                logger.warning(f"Workflow '{workflow_name}' already exists. Skipping.")
        except Exception as e:
            logger.error(f"Failed to import workflow {workflow_name}: {e}", exc_info=True)
            continue


@app.command()
def import_job_templates(
    input_file: Path = typer.Option(
        "job_templates.json",
        help="Input JSON file path",
        exists=True,
        dir_okay=False,
        readable=True,
    )
) -> None:
    """Import job templates and workflows from JSON into AWX."""
    try:
        # Get AWX client configuration
        client_config = get_awx_or_tower_client("AWX")
        tower_url = client_config["url"]
        headers = client_config["headers"]
        verify = client_config["verify"]

        with open(input_file, "r") as f:
            data = json.load(f)

        import_job_templates_from_data(tower_url, headers, data.get("job_templates", []), verify)
        import_workflows_from_data(tower_url, headers, data.get("workflows", []), verify)

        logger.info("Job templates and workflows import completed.")

    except Exception as e:
        logger.error(f"Failed to import job templates and workflows: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
