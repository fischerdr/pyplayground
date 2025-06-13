#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to import job templates and workflows into AWX."""

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


def import_job_templates_from_data(awx, job_templates):
    """Import job templates into AWX from a list of data."""
    logger.info(f"Importing {len(job_templates)} job templates into AWX...")
    for template_data in job_templates:
        template_name = template_data.get("name")
        try:
            if not awx.job_templates.find(name=template_name):
                awx.job_templates.create(payload=template_data)
                logger.info(f"Successfully imported job template: {template_name}")
            else:
                logger.warning(f"Job template '{template_name}' already exists. Skipping.")
        except Exception as e:
            logger.error(f"Failed to import job template {template_name}: {e}", exc_info=True)
            continue


def import_workflows_from_data(awx, workflows):
    """Import workflows into AWX from a list of data."""
    logger.info(f"Importing {len(workflows)} workflows into AWX...")
    for workflow_data in workflows:
        workflow_name = workflow_data.get("name")
        try:
            if not awx.workflow_job_templates.find(name=workflow_name):
                awx.workflow_job_templates.create(payload=workflow_data)
                logger.info(f"Successfully imported workflow: {workflow_name}")
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
        awx = get_awx_or_tower_client("AWX")

        with open(input_file, "r") as f:
            data = json.load(f)

        import_job_templates_from_data(awx, data.get("job_templates", []))
        import_workflows_from_data(awx, data.get("workflows", []))

        logger.info("Job templates and workflows import completed.")

    except Exception as e:
        logger.error(f"Failed to import job templates and workflows: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
