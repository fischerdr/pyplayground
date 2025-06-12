#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to export Tower job templates and workflows to JSON."""

import sys
from pathlib import Path

import typer
from awxcli import Tower

from utils.logging_utils import setup_logging, get_logger
from utils.config_utils import load_env_file, get_env_var, save_json_config

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name="tower_export_job_templates")
logger = get_logger(__name__)


def get_tower_client() -> Tower:
    """Get Tower client with credentials from environment.
    
    Returns:
        Tower: Initialized Tower client
        
    Raises:
        ValueError: If required environment variables are not set
    """
    # Load environment variables
    load_env_file()
    
    # Get Tower credentials from environment
    tower_host = get_env_var("TOWER_HOST", required=True)
    tower_token = get_env_var("TOWER_TOKEN", required=True)
    
    try:
        return Tower(host=tower_host, token=tower_token)
    except Exception as e:
        logger.error(f"Failed to initialize Tower client: {e}")
        raise


@app.command()
def export(
    output: Path = typer.Option(
        "job_templates.json",
        help="Output JSON file path",
        exists=False,
        dir_okay=False,
        writable=True,
    )
) -> None:
    """Export Tower job templates and workflows to JSON.
    
    Args:
        output: Output JSON file path
    """
    try:
        # Get Tower client
        tower = get_tower_client()
        
        # Get job templates
        logger.info("Fetching job templates from Tower...")
        job_templates = tower.job_templates.list()
        
        # Get workflows
        logger.info("Fetching workflows from Tower...")
        workflows = tower.workflows.list()
        
        # Convert to dict for JSON serialization
        job_templates_data = [template.dict() for template in job_templates]
        workflows_data = [workflow.dict() for workflow in workflows]
        
        # Combine data
        export_data = {
            "job_templates": job_templates_data,
            "workflows": workflows_data
        }
        
        # Save to file
        save_json_config(export_data, output)
        logger.info(
            f"Successfully exported {len(job_templates_data)} job templates and "
            f"{len(workflows_data)} workflows to {output}"
        )
        
    except Exception as e:
        logger.error(f"Failed to export job templates and workflows: {e}")
        sys.exit(1)


if __name__ == "__main__":
    app() 