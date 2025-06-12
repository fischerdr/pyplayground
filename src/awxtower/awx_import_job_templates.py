#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to import job templates and workflows into AWX."""

import sys
from pathlib import Path

import typer
from awxcli import AWX

from utils.logging_utils import setup_logging, get_logger
from utils.config_utils import load_env_file, get_env_var, load_json_config

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name="awx_import_job_templates")
logger = get_logger(__name__)


def get_awx_client() -> AWX:
    """Get AWX client with credentials from environment.
    
    Returns:
        AWX: Initialized AWX client
        
    Raises:
        ValueError: If required environment variables are not set
    """
    # Load environment variables
    load_env_file()
    
    # Get AWX credentials from environment
    awx_host = get_env_var("AWX_HOST", required=True)
    awx_token = get_env_var("AWX_TOKEN", required=True)
    
    try:
        return AWX(host=awx_host, token=awx_token)
    except Exception as e:
        logger.error(f"Failed to initialize AWX client: {e}")
        raise


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
    """Import job templates and workflows from JSON into AWX.
    
    Args:
        input_file: Input JSON file path
    """
    try:
        # Get AWX client
        awx = get_awx_client()
        
        # Load data from file
        logger.info(f"Loading job templates and workflows from {input_file}...")
        data = load_json_config(input_file)
        
        # Import job templates
        logger.info("Importing job templates into AWX...")
        for template_data in data.get("job_templates", []):
            try:
                # Create job template
                awx.job_templates.create(**template_data)
                logger.info(f"Successfully imported job template: {template_data.get('name')}")
            except Exception as e:
                logger.error(f"Failed to import job template {template_data.get('name')}: {e}")
                continue
        
        # Import workflows
        logger.info("Importing workflows into AWX...")
        for workflow_data in data.get("workflows", []):
            try:
                # Create workflow
                awx.workflows.create(**workflow_data)
                logger.info(f"Successfully imported workflow: {workflow_data.get('name')}")
            except Exception as e:
                logger.error(f"Failed to import workflow {workflow_data.get('name')}: {e}")
                continue
        
        logger.info("Job templates and workflows import completed")
        
    except Exception as e:
        logger.error(f"Failed to import job templates and workflows: {e}")
        sys.exit(1)


if __name__ == "__main__":
    app() 