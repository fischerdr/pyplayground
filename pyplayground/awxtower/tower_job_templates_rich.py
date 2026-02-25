#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script to export Tower job templates and workflows to JSON.

This script exports job templates and workflows from Tower to a JSON file.
It also displays the data in a rich formatted table.

Usage:
    python tower_export_job_templates_rich.py --include-workflows --verify --search "my_search_term" --order-by "name"

"""
import os
from typing import Any, Dict, List, Optional

import typer
from rich.console import Console
from rich.table import Table

from pyplayground.utils.ansible_tower_utils import (
    export_all_resources,
    find_resource_by_attribute_name,
    find_resource_by_id,
    get_awx_or_tower_client,
)
from pyplayground.utils.logging_utils import get_logger, setup_logging

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name=os.path.basename(__file__).replace(".py", ""))
logger = get_logger(__name__)

console = Console()


def get_username(
    user_field: Optional[Dict[str, Any]],
    tower_url: str,
    headers: Dict[str, str],
    verify: bool,
) -> str:
    """Get username from summary_fields or fetch by user ID."""
    if user_field and "username" in user_field:
        return user_field["username"]
    if user_field and "id" in user_field:
        user_id = user_field["id"]
        user = find_resource_by_id(tower_url, headers, "users", user_id, verify)
        if user and user.get("results"):
            return user["results"][0].get("username", "N/A")
    return "N/A"


def get_dependency_names(jt: Dict[str, Any]) -> str:
    """Extract dependency names from job template.

    Args:
        jt: Job template dictionary

    Returns:
        Comma-separated string of dependency names
    """
    related = jt.get("summary_fields", {}).get("related", {})
    dependencies = related.get("dependencies", [])

    if not dependencies:
        return "None"

    # Get dependency names from the job template dict
    dependency_names = []
    for dep_id in dependencies:
        # Look up the dependency name by ID in the job templates
        # This is a simplified approach - in a real scenario, you might need to fetch dependency details
        dependency_names.append(f"ID:{dep_id}")

    return ", ".join(dependency_names)


@app.command()
def export(  # noqa: C901
    include_workflows: bool = typer.Option(False, help="Include workflow job templates in export"),
    verify: bool = typer.Option(False, help="Verify the connection to Tower"),
    search: Optional[str] = typer.Option(None, help="Search term for filtering workflows"),
    order_by: Optional[str] = typer.Option(None, help="Sort workflows by field (e.g., 'name', '-name')"),
) -> None:
    """Export Tower job templates and workflows to JSON or Rich table.

    This function fetches job templates and workflows from Tower, sorts them alphabetically by name,
    and then exports them either as a JSON file or in a rich formatted table.
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
            logger.error("Failed to fetch job templates from Tower")
            console.print("[red]Failed to fetch job templates from Tower[/red]")
            return

        if include_workflows:
            workflows: List[Dict[str, Any]] = []
            logger.info("Fetching workflow job templates from Tower...")

            # Build query parameters for workflow API
            params = {}
            if search:
                params["search"] = search
            if order_by:
                params["order_by"] = order_by

            workflows_result = export_all_resources(tower_url, headers, "workflow_job_templates", verify, params)
            if workflows_result is None:
                logger.error("Failed to fetch workflows from Tower")
                console.print("[red]Failed to fetch workflows from Tower[/red]")
            else:
                workflows = workflows_result

        if not job_templates and not include_workflows:
            logger.warning("No job templates or workflows found in Tower.")
            console.print("[yellow]No job templates or workflows found in Tower.[/yellow]")
            return

        # Sort job templates and workflows by name (case-insensitive)
        sorted_job_templates = sorted(job_templates, key=lambda x: x.get("name", "").lower())
        if include_workflows:
            sorted_workflows = sorted(workflows, key=lambda x: x.get("name", "").lower())

        # Create table for job templates
        job_table = Table(title="Job Templates")
        job_table.add_column("ID", style="bold", width=5)
        job_table.add_column("Name", style="bold", width=30, justify="left")
        job_table.add_column(
            "Description",
            style="italic",
            width=45,  # Set a fixed width for the description column
            justify="left",  # Align text to the left
        )
        job_table.add_column(
            "Owner",
            style="bold",
            width=10,  # Set a fixed width for the owner column
            justify="left",  # Align text to the left
        )
        job_table.add_column(
            "Project",
            style="bold",
            width=20,  # Set a fixed width for the project column
            justify="left",  # Align text to the left
        )
        job_table.add_column(
            "Created",
            style="bold",
            width=28,  # Set a fixed width for the created column
            justify="left",  # Align text to the left
        )
        job_table.add_column(
            "Modified",
            style="bold",
            width=10,  # Set a fixed width for the modified column
            justify="left",  # Align text to the left
        )
        job_table.add_column(
            "Last Modified",
            style="bold",
            width=28,  # Set a fixed width for the last modified by column
            justify="left",  # Align text to the left
        )
        job_table.add_column("Job Runs", style="bold", width=15, justify="left")

        for jt in sorted_job_templates:

            project_id = str(jt.get("project", ""))
            if project_id and project_id.lower() != "none":
                project = find_resource_by_id(tower_url, headers, "projects", project_id, verify)
                project_results = project.get("results", [])
                if project_results:
                    project_name = project_results[0].get("name", "N/A")
                else:
                    logger.warning(f"No project found for job template {jt['id']} {jt['name']}")
                    project_name = "N/A"
            else:
                logger.warning(f"No project ID for job template {jt['id']} {jt['name']}")
                project_name = "N/A"
            create_by_name = get_username(jt.get("summary_fields", {}).get("created_by"), tower_url, headers, verify)
            create_datetime = jt.get("created", "N/A")
            modified_by_name = get_username(jt.get("summary_fields", {}).get("modified_by"), tower_url, headers, verify)
            modify_datetime = jt.get("modified", "N/A")
            count_job_runs = find_resource_by_attribute_name(tower_url, headers, "jobs", "job_template", jt["id"], verify)
            job_runs = count_job_runs.get("count", 0)

            job_table.add_row(
                str(jt["id"]),
                jt["name"],
                jt.get("description", "N/A"),
                project_name,
                create_by_name,
                create_datetime,
                modified_by_name,
                modify_datetime,
                str(job_runs),
            )

        # Display job templates table
        console.print(job_table)

        if include_workflows:
            # Create table for workflows
            workflow_table = Table(title="Workflows")
            workflow_table.add_column("ID", style="bold", width=5)
            workflow_table.add_column("Name", style="bold")
            workflow_table.add_column(
                "Description",
                style="italic",
                width=80,  # Set a fixed width for the description column
                justify="left",  # Align text to the left
            )

            for wf in sorted_workflows:
                workflow_table.add_row(str(wf["id"]), wf["name"], wf.get("description", "N/A"))

            # Display workflows table
            console.print(workflow_table)

    except Exception as e:
        logger.error(f"Failed to export job templates: {e}", exc_info=True)
        console.print("[red]An error occurred while exporting data.[/red]")


if __name__ == "__main__":
    app()
