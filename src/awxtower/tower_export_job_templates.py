#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to export Tower job templates and workflows to JSON."""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer
from awxkit import config
from awxkit.api import ApiV2
from awxkit.api.resources import resources
from awxkit.exceptions import AuthError, ConnectionError, NotFound

from utils.config_utils import get_env_var, load_env_file, save_json_config
from utils.logging_utils import get_logger, setup_logging

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name="tower_export_job_templates")
logger = get_logger(__name__)

# Constants
DEFAULT_PAGE_SIZE = 100
API_VERSION = "v2"


def get_tower_client() -> ApiV2:
    """Get Tower client with credentials from environment.

    Returns:
        ApiV2: Initialized Tower client

    Raises:
        ValueError: If required environment variables are not set
        ConnectionError: If connection to Tower fails
        AuthError: If authentication fails
    """
    # Load environment variables
    load_env_file()

    # Get Tower credentials from environment
    tower_host = get_env_var("TOWER_HOST", required=True)
    tower_token = get_env_var("TOWER_TOKEN", required=True)

    try:
        # Configure base URL
        config.base_url = tower_host

        # Initialize API client
        awx_api_client = ApiV2()

        # Login with token
        awx_api_client.connection.login(token=tower_token)

        # Load available resources
        awx_api_client.get(resources)

        return awx_api_client
    except ConnectionError as e:
        logger.error(f"Failed to connect to Tower at {tower_host}: {e}")
        raise
    except AuthError as e:
        logger.error(f"Authentication failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to initialize Tower client: {e}")
        raise


def get_paginated_resources(
    client: ApiV2,
    resource_type: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Get paginated resources from Tower.

    Args:
        client: Tower API client
        resource_type: Type of resource to fetch (e.g. 'job_templates', 'workflow_job_templates')
        page_size: Number of items per page
        filters: Optional filters to apply

    Returns:
        List[Dict[str, Any]]: List of resource data

    Raises:
        NotFound: If resource type not found
        AuthError: If access denied
    """
    try:
        # Get resource endpoint
        resource = getattr(client, resource_type)

        # Apply filters if provided
        if filters:
            resource = resource.get(**filters)
        else:
            resource = resource.get()

        # Get all pages
        all_results = []
        while resource:
            all_results.extend(resource.results)
            if not resource.next:
                break
            resource = resource.next.get()

        return [item.dict() for item in all_results]

    except NotFound as e:
        logger.error(f"Resource type {resource_type} not found: {e}")
        raise
    except AuthError as e:
        logger.error(f"Access denied to {resource_type}: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to fetch {resource_type}: {e}")
        raise


@app.command()
def export(
    output: Path = typer.Option(
        "job_templates.json",
        help="Output JSON file path",
        exists=False,
        dir_okay=False,
        writable=True,
    ),
    page_size: int = typer.Option(
        DEFAULT_PAGE_SIZE, help="Number of items per page", min=1, max=200
    ),
    include_workflows: bool = typer.Option(True, help="Include workflow job templates in export"),
) -> None:
    """Export Tower job templates and workflows to JSON.

    Args:
        output: Output JSON file path
        page_size: Number of items per page
        include_workflows: Whether to include workflow job templates
    """
    try:
        # Get Tower client
        tower = get_tower_client()

        # Get job templates
        logger.info("Fetching job templates from Tower...")
        job_templates = get_paginated_resources(tower, "job_templates", page_size=page_size)

        # Get workflows if requested
        workflows = []
        if include_workflows:
            logger.info("Fetching workflows from Tower...")
            workflows = get_paginated_resources(
                tower, "workflow_job_templates", page_size=page_size
            )

        # Combine data
        export_data = {
            "api_version": API_VERSION,
            "job_templates": job_templates,
            "workflows": workflows,
        }

        # Save to file
        save_json_config(export_data, output)
        logger.info(
            f"Successfully exported {len(job_templates)} job templates and "
            f"{len(workflows)} workflows to {output}"
        )

    except Exception as e:
        logger.error(f"Failed to export job templates and workflows: {e}")
        sys.exit(1)


if __name__ == "__main__":
    app()
