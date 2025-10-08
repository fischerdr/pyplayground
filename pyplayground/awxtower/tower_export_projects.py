#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script to export Tower project definitions to CSV, including job template count per project."""

import csv
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import typer

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
    """Extract a row for the project CSV."""
    summary_fields = project.get("summary_fields", {})
    created_by = get_username(summary_fields.get("created_by"), tower_url, headers, verify)
    modified_by = get_username(summary_fields.get("modified_by"), tower_url, headers, verify)
    # Job template count for this project
    job_templates = export_all_resources(
        tower_url, headers, "job_templates", verify, params={"project": project["id"]}
    )
    job_template_count = len(job_templates) if job_templates else 0
    return [
        project.get("id", ""),
        project.get("name", ""),
        project.get("created", ""),
        project.get("modified", ""),
        project.get("scm_type", ""),
        project.get("scm_url", ""),
        project.get("scm_branch", ""),
        created_by,
        modified_by,
        job_template_count,
    ]


def write_csv(filename: str, header: List[str], rows: List[List[Any]]) -> None:
    """Write rows to a CSV file with the given header."""
    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(header)
        writer.writerows(rows)


@app.command()
def export(
    verify: bool = typer.Option(False, help="Verify the connection to Tower"),
) -> None:
    """Export Tower project definitions to CSV, including job template count per project."""
    try:
        client_config = get_awx_or_tower_client("TOWER", verify=verify)
        tower_url = client_config["url"]
        headers = client_config["headers"]
        verify = client_config["verify"]

        logger.info("Fetching projects from Tower...")
        projects = export_all_resources(tower_url, headers, "projects", verify)
        if not projects:
            logger.warning("No projects found in Tower.")
            typer.echo("No projects found in Tower.")
            return

        sorted_projects = sorted(projects, key=lambda x: x.get("name", "").lower())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"tmp/projects_{timestamp}.csv"
        fields = [
            "id",
            "name",
            "created_by",
            "created",
            "modified",
            "modified_by",
            "scm_type",
            "scm_url",
            "scm_branch",
            "job_template_count",
        ]
        rows = [extract_project_row(p, tower_url, headers, verify) for p in sorted_projects]
        write_csv(csv_filename, fields, rows)
        logger.info(f"Exported {len(rows)} projects to {csv_filename}")
        typer.echo(f"Exported {len(rows)} projects to {csv_filename}")
    except Exception as e:
        logger.error(f"Failed to export projects: {e}", exc_info=True)
        typer.echo(f"An error occurred while exporting data: {e}")


if __name__ == "__main__":
    app()
