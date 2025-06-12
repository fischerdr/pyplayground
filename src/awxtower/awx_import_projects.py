#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to import project definitions into AWX."""

import sys
from pathlib import Path

import typer
from awxcli import AWX

from utils.logging_utils import setup_logging, get_logger
from utils.config_utils import load_env_file, get_env_var, load_json_config

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name="awx_import_projects")
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
def import_projects(
    input_file: Path = typer.Option(
        "projects.json",
        help="Input JSON file path",
        exists=True,
        dir_okay=False,
        readable=True,
    )
) -> None:
    """Import project definitions from JSON into AWX.
    
    Args:
        input_file: Input JSON file path
    """
    try:
        # Get AWX client
        awx = get_awx_client()
        
        # Load projects from file
        logger.info(f"Loading projects from {input_file}...")
        projects_data = load_json_config(input_file)
        
        # Import projects
        logger.info("Importing projects into AWX...")
        for project_data in projects_data:
            try:
                # Create project
                awx.projects.create(**project_data)
                logger.info(f"Successfully imported project: {project_data.get('name')}")
            except Exception as e:
                logger.error(f"Failed to import project {project_data.get('name')}: {e}")
                continue
        
        logger.info("Project import completed")
        
    except Exception as e:
        logger.error(f"Failed to import projects: {e}")
        sys.exit(1)


if __name__ == "__main__":
    app() 