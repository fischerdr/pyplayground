#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to export Tower job templates and workflows to JSON."""

import json
import os
import sys
from collections import defaultdict, deque
from pathlib import Path

import typer

from utils.ansible_tower_utils import get_awx_or_tower_client, list_resources
from utils.logging_utils import get_logger, setup_logging

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name=os.path.basename(__file__).replace(".py", ""))
logger = get_logger(__name__)


def sort_job_templates_by_dependencies(job_templates):
    """
    Sort job templates by their dependencies using topological sorting.

    This function constructs a dependency graph and computes the indegree for each job template.
    It then performs a topological sort to ensure that job templates with no dependencies are processed first,
    followed by those that depend on them. If cyclic dependencies are detected, it raises a ValueError.

    :param job_templates: List of job templates fetched from Tower
    :return: Sorted list of job templates based on their dependencies
    """
    job_template_dict = {jt["id"]: jt for jt in job_templates}
    dependency_graph = defaultdict(list)
    indegree = defaultdict(int)

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
) -> None:
    """
    Export Tower job templates and workflows to JSON.

    This function fetches job templates and workflows from Tower, sorts the job templates based on their dependencies,
    and then exports them to a specified JSON file. It handles logging throughout the process to provide feedback
    about the operations being performed.

    :param output: Path to the output JSON file where job templates and workflows will be exported.
    :param include_workflows: Boolean flag indicating whether to include workflow job templates in the export.
    """
    try:
        # Get Tower client configuration
        client_config = get_awx_or_tower_client("TOWER")
        tower_url = client_config["url"]
        headers = client_config["headers"]
        verify = client_config["verify"]

        logger.info("Fetching job templates from Tower...")
        job_templates = list_resources(tower_url, headers, "job_templates", verify)

        workflows = []
        if include_workflows:
            logger.info("Fetching workflow job templates from Tower...")
            workflows = list_resources(tower_url, headers, "workflow_job_templates", verify)

        if not job_templates and not workflows:
            logger.warning("No job templates or workflows found in Tower.")
            sys.exit(0)

        # Sort job templates by dependencies
        sorted_job_templates = sort_job_templates_by_dependencies(job_templates)

        export_data = {
            "job_templates": sorted_job_templates,
            "workflows": workflows,
        }

        with open(output, "w") as f:
            json.dump(export_data, f, indent=2)
        logger.info(
            f"Successfully exported {len(sorted_job_templates)} job templates and "
            f"{len(workflows)} workflows to {output}"
        )

    except Exception as e:
        logger.error(f"Failed to export job templates: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    app()