#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script to display Tower project definitions in a rich table, including job template count per project."""

import os
from typing import Any, Dict, List, Optional

import typer
from rich.console import Console
from rich.table import Table

from pyplayground.utils.ansible_tower_utils import (
    export_all_resources,
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


def extract_project_row(
    project: Dict[str, Any],
    tower_url: str,
    headers: Dict[str, str],
    verify: bool,
) -> List[Any]:
    """Extract a row for the project table."""
    summary_fields = project.get("summary_fields", {})
    created_by = get_username(summary_fields.get("created_by"), tower_url, headers, verify)
    modified_by = get_username(summary_fields.get("modified_by"), tower_url, headers, verify)
    # Job template count for this project
    job_templates = export_all_resources(
        tower_url, headers, "job_templates", verify, params={"project": project["id"]}
    )
    job_template_count = len(job_templates) if job_templates else 0
    return [
        str(project.get("id", "")),
        project.get("name", ""),
        project.get("created", ""),
        project.get("modified", ""),
        project.get("scm_type", ""),
        project.get("scm_url", ""),
        project.get("scm_branch", ""),
        created_by,
        modified_by,
        str(job_template_count),
    ]


@app.command()
def show(
    verify: bool = typer.Option(False, help="Verify the connection to Tower"),
) -> None:
    """Display Tower project definitions in a rich table, including job template count per project."""
    try:
        client_config = get_awx_or_tower_client("TOWER", verify=verify)
        tower_url = client_config["url"]
        headers = client_config["headers"]
        verify = client_config["verify"]

        logger.info("Fetching projects from Tower...")
        projects = export_all_resources(tower_url, headers, "projects", verify)
        if not projects:
            logger.warning("No projects found in Tower.")
            console.print("[yellow]No projects found in Tower.[/yellow]")
            return

        sorted_projects = sorted(projects, key=lambda x: x.get("name", "").lower())

        table = Table(title="Tower Projects")
        table.add_column("ID", style="bold", width=5)
        table.add_column("Name", style="bold", width=30, justify="left")
        table.add_column("Created", style="", width=28, justify="left")
        table.add_column("Modified", style="", width=28, justify="left")
        table.add_column("SCM Type", style="", width=10, justify="left")
        table.add_column("SCM URL", style="", width=40, justify="left")
        table.add_column("SCM Branch", style="", width=20, justify="left")
        table.add_column("Created By", style="", width=15, justify="left")
        table.add_column("Modified By", style="", width=15, justify="left")
        table.add_column("Job Templates", style="bold", width=8, justify="right")

        for project in sorted_projects:
            row = extract_project_row(project, tower_url, headers, verify)
            table.add_row(*row)

        console.print(table)

    except Exception as e:
        logger.error(f"Failed to display projects: {e}", exc_info=True)
        console.print("[red]An error occurred while displaying data.[/red]")


if __name__ == "__main__":
    app()
