#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to export Tower job templates and workflows to JSON."""
import json
import os
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, List

import typer
from rich.console import Console
from rich.table import Table

from pyplayground.utils.ansible_tower_utils import get_awx_or_tower_client, list_resources
from pyplayground.utils.logging_utils import get_logger, setup_logging

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name=os.path.basename(__file__).replace(".py", ""))
logger = get_logger(__name__)

console = Console()


def sort_job_templates_by_dependencies(job_templates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort job templates by their dependencies using topological sorting.

    This function constructs a dependency graph and computes the indegree for each job template.
    It then performs a topological sort to ensure that job templates with no dependencies are processed first,
    followed by those that depend on them. If cyclic dependencies are detected, it raises a ValueError.

    Args:
        job_templates: List of job templates fetched from Tower

    Returns:
        Sorted list of job templates based on their dependencies

    Raises:
        ValueError: If cyclic dependencies are detected among job templates
    """
    job_template_dict = {jt["id"]: jt for jt in job_templates}
    dependency_graph = defaultdict(list)
    indegree: Dict[int, int] = defaultdict(int)

    # Build the graph and compute indegrees
    for jt in job_templates:
        related = jt.get("summary_fields", {}).get("related", {})
        depends_on = related.get("dependencies", [])
        for dep_id in depends_on:
            if dep_id in job_template_dict:
                dependency_graph[dep_id].append(jt["id"])
                indegree[jt["id"]] += 1

    # Initialize the queue with nodes having no dependencies
    queue = deque([jt["id"] for jt in job_templates if indegree[jt["id"]] == 0])
    sorted_job_ids = []

    # Process the queue and sort job templates
    while queue:
        current_id = queue.popleft()
        sorted_job_ids.append(current_id)
        for child_id in dependency_graph[current_id]:
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                queue.append(child_id)

    # Check for cyclic dependencies
    if len(sorted_job_ids) != len(job_templates):
        raise ValueError("Cyclic dependencies detected among job templates.")

    return [job_template_dict[job_id] for job_id in sorted_job_ids]


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
) -> None:
    """Export Tower job templates and workflows to JSON or Rich table.

    This function fetches job templates and workflows from Tower, sorts the job templates based on their dependencies,
    and then exports them either as a JSON file or in a rich formatted table.
    """
    try:
        # Get Tower client configuration
        client_config = get_awx_or_tower_client("TOWER", verify=verify)
        tower_url = client_config["url"]
        headers = client_config["headers"]

        logger.info("Fetching job templates from Tower...")
        job_templates = list_resources(tower_url, headers, "job_templates", verify)

        if job_templates is None:
            logger.error("Failed to fetch job templates from Tower")
            console.print("[red]Failed to fetch job templates from Tower[/red]")
            return

        workflows: List[Dict[str, Any]] = []
        if include_workflows:
            logger.info("Fetching workflow job templates from Tower...")
            workflows_result = list_resources(tower_url, headers, "workflow_job_templates", verify)
            
            if workflows_result is None:
                logger.error("Failed to fetch workflows from Tower")
                console.print("[red]Failed to fetch workflows from Tower[/red]")
            else:
                workflows = workflows_result

        # Filter and sort data
        sorted_job_templates = sort_job_templates_by_dependencies(job_templates)

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

        for wf in workflows:
            workflow_table.add_row(str(wf["id"]), wf["name"], wf.get("description", "N/A"))

        # Display tables
        console.print(job_table)
        console.print(workflow_table)

        if output:
            with open(output, "w") as f:
                json.dump(
                    {"job_templates": sorted_job_templates, "workflows": workflows}, f, indent=2
                )
            logger.info(
                f"Successfully exported {len(sorted_job_templates)} job templates and {len(workflows)} workflows to {output}"
            )

    except Exception as e:
        logger.error(f"Failed to export job templates: {e}", exc_info=True)
        console.print("[red]An error occurred while exporting data.[/red]")


if __name__ == "__main__":
    app()
