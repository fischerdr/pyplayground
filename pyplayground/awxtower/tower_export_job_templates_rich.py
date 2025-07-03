#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to export Tower job templates and workflows to JSON."""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer
from rich.console import Console
from rich.table import Table

from pyplayground.utils.ansible_tower_utils import (
    export_job_templates,
    export_workflow_job_templates,
    get_awx_or_tower_client,
)
from pyplayground.utils.logging_utils import get_logger, setup_logging

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name=os.path.basename(__file__).replace(".py", ""))
logger = get_logger(__name__)

console = Console()


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
        job_templates = export_job_templates(tower_url, headers, verify)
        if job_templates is None:
            logger.error("Failed to fetch job templates from Tower")
            console.print("[red]Failed to fetch job templates from Tower[/red]")
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

            workflows_result = export_workflow_job_templates(tower_url, headers, verify, params)
            if workflows_result is None:
                logger.error("Failed to fetch workflows from Tower")
                console.print("[red]Failed to fetch workflows from Tower[/red]")
            else:
                workflows = workflows_result

        if not job_templates and not workflows:
            logger.warning("No job templates or workflows found in Tower.")
            console.print("[yellow]No job templates or workflows found in Tower.[/yellow]")
            return

        # Sort job templates and workflows by name (case-insensitive)
        sorted_job_templates = sorted(job_templates, key=lambda x: x.get("name", "").lower())
        sorted_workflows = sorted(workflows, key=lambda x: x.get("name", "").lower())

        # Create table for job templates
        job_table = Table(title="Job Templates")
        job_table.add_column("ID", style="bold", width=5)
        job_table.add_column("Name", style="bold")
        job_table.add_column("Description", style="italic")
        job_table.add_column("Dependencies", style="dim")

        for jt in sorted_job_templates:
            job_table.add_row(
                str(jt["id"]), jt["name"], jt.get("description", "N/A"), get_dependency_names(jt)
            )

        # Create table for workflows
        workflow_table = Table(title="Workflows")
        workflow_table.add_column("ID", style="bold", width=5)
        workflow_table.add_column("Name", style="bold")
        workflow_table.add_column("Description", style="italic")

        for wf in sorted_workflows:
            workflow_table.add_row(str(wf["id"]), wf["name"], wf.get("description", "N/A"))

        # Display tables
        console.print(job_table)
        console.print(workflow_table)

        if output:
            with open(output, "w") as f:
                json.dump(
                    {"job_templates": sorted_job_templates, "workflows": sorted_workflows},
                    f,
                    indent=2,
                )
            logger.info(
                f"Successfully exported {len(sorted_job_templates)} job templates and {len(sorted_workflows)} workflows to {output}"
            )

    except Exception as e:
        logger.error(f"Failed to export job templates: {e}", exc_info=True)
        console.print("[red]An error occurred while exporting data.[/red]")


if __name__ == "__main__":
    app()
