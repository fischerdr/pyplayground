#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script to export Tower job templates and workflows to CSV files.

This script exports job templates and workflows from Tower to timestamped CSV files.
It uses the latest field extraction logic and utility functions.

Usage:
    python tower_export_job_templates.py --include-workflows --verify --search "my_search_term" --order-by "name"
"""

import csv
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import typer

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


def get_username_by_id(tower_url: str, headers: Dict[str, str], user_id: str, verify: bool) -> str:
    """Helper to get username by user ID."""
    user = find_resource_by_id(tower_url, headers, "users", user_id, verify)
    if user and user.get("results"):
        return user["results"][0].get("username", "N/A")
    return "N/A"


def get_job_run_count(tower_url: str, headers: Dict[str, str], jt_id: int, verify: bool) -> int:
    """Helper to get job run count for a job template."""
    count_job_runs = find_resource_by_attribute_name(tower_url, headers, "jobs", "job_template", jt_id, verify)
    if count_job_runs:
        return count_job_runs.get("count", 0)
    return 0


def extract_job_template_row(jt: Dict[str, Any], tower_url: str, headers: Dict[str, str], verify: bool) -> List[Any]:
    """Extract a row for the job template CSV."""
    # Project lookup logic (robust, as in tower_job_templates_rich.py)
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

    create_id = str(dict(jt["related"]).get("created_by", "1")).rstrip("/").split("/")[-1]
    create_by_name = get_username_by_id(tower_url, headers, create_id, verify)
    create_datetime = jt.get("created", "N/A")
    modified_id = str(dict(jt["related"]).get("modified_by", "1")).rstrip("/").split("/")[-1]
    modified_by_name = get_username_by_id(tower_url, headers, modified_id, verify)
    modify_datetime = jt.get("modified", "N/A")
    job_runs = get_job_run_count(tower_url, headers, jt["id"], verify)
    return [
        str(jt["id"]),
        jt["name"],
        jt.get("description", "N/A"),
        project_name,
        create_by_name,
        create_datetime,
        modified_by_name,
        modify_datetime,
        job_runs,
    ]


def extract_workflow_row(wf: Dict[str, Any]) -> List[Any]:
    """Extract a row for the workflow CSV."""
    return [str(wf["id"]), wf["name"], wf.get("description", "N/A")]


def write_csv(filename: str, header: List[str], rows: List[List[Any]]) -> None:
    """Write rows to a CSV file with the given header."""
    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(header)
        writer.writerows(rows)


@app.command()
def export(
    include_workflows: bool = typer.Option(False, help="Include workflow job templates in export"),
    verify: bool = typer.Option(False, help="Verify the connection to Tower"),
    search: Optional[str] = typer.Option(None, help="Search term for filtering workflows"),
    order_by: Optional[str] = typer.Option(None, help="Sort workflows by field (e.g., 'name', '-name')"),
) -> None:
    """Export Tower job templates and workflows to timestamped CSV files."""
    try:
        client_config = get_awx_or_tower_client("TOWER", verify=verify)
        tower_url = client_config["url"]
        headers = client_config["headers"]
        verify = client_config["verify"]

        logger.info("Fetching job templates from Tower...")
        job_templates = export_all_resources(tower_url, headers, "job_templates", verify)
        if job_templates is None:
            logger.error("Failed to fetch job templates from Tower")
            print("Failed to fetch job templates from Tower.")
            return

        workflows: List[Dict[str, Any]] = []
        if include_workflows:
            logger.info("Fetching workflow job templates from Tower...")
            params = {}
            if search:
                params["search"] = search
            if order_by:
                params["order_by"] = order_by
            workflows_result = export_all_resources(tower_url, headers, "workflow_job_templates", verify, params)
            if workflows_result is None:
                logger.error("Failed to fetch workflows from Tower")
                print("Failed to fetch workflows from Tower.")
            else:
                workflows = workflows_result

        if not job_templates and not (include_workflows and workflows):
            logger.warning("No job templates or workflows found in Tower.")
            print("No job templates or workflows found in Tower.")
            return

        sorted_job_templates = sorted(job_templates, key=lambda x: x.get("name", "").lower())
        sorted_workflows = sorted(workflows, key=lambda x: x.get("name", "").lower()) if include_workflows else []

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        jt_csv_filename = f"tmp/job_templates_{timestamp}.csv"
        wf_csv_filename = f"tmp/workflow_job_templates_{timestamp}.csv"

        jt_fields = [
            "ID",
            "Name",
            "Description",
            "Project",
            "Owner",
            "Created",
            "Modified",
            "Last Modified",
            "Job Runs",
        ]
        jt_rows = [extract_job_template_row(jt, tower_url, headers, verify) for jt in sorted_job_templates]
        write_csv(jt_csv_filename, jt_fields, jt_rows)
        logger.info(f"Exported {len(jt_rows)} job templates to {jt_csv_filename}")
        print(f"Exported {len(jt_rows)} job templates to {jt_csv_filename}")

        if include_workflows and sorted_workflows:
            wf_fields = ["ID", "Name", "Description"]
            wf_rows = [extract_workflow_row(wf) for wf in sorted_workflows]
            write_csv(wf_csv_filename, wf_fields, wf_rows)
            logger.info(f"Exported {len(wf_rows)} workflows to {wf_csv_filename}")
            print(f"Exported {len(wf_rows)} workflows to {wf_csv_filename}")

    except Exception as e:
        logger.error(f"Failed to export job templates: {e}", exc_info=True)
        print(f"An error occurred while exporting data: {e}")


if __name__ == "__main__":
    app()
