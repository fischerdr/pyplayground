#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""Applies labels to namespaces based on a mapping configuration.

This script applies labels to namespaces based on a mapping configuration,
outputting a log file and console output.
"""
import json
import logging
import os
import sys
from typing import Any, Dict, Optional

import click
import yaml
from kubernetes import client
from kubernetes.client.rest import ApiException
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Import utilities
from utils.k8s_utils import load_kube_config_auto
from utils.logging_utils import get_logger, setup_logging

# --- Global Logger --- #
# Initialize logger at the module level
logger = get_logger(__name__)

# --- Global Console --- #
console = Console()


def load_json_data(file_path: str) -> Optional[Dict[str, Any]]:
    """Loads JSON data from a file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Input JSON file not found: {file_path}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON file {file_path}: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error loading JSON file {file_path}: {e}")
        return None


def load_yaml_config(file_path: str) -> Optional[Dict[str, Any]]:
    """Loads YAML configuration from a file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Configuration YAML file not found: {file_path}")
        return None
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML file {file_path}: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error loading YAML file {file_path}: {e}")
        return None


def patch_namespace_label(
    v1_api: client.CoreV1Api,
    namespace_name: str,
    label_key: str,
    label_value: str,
    dry_run: bool = False,
) -> bool:
    """Applies a single label to a namespace using patching."""
    patch_body = {"metadata": {"labels": {label_key: label_value}}}

    action = f"Label namespace [cyan]{namespace_name}[/cyan] with [yellow]{label_key}[/yellow]=[green]{label_value}[/green]"
    if dry_run:
        console.print(f":wrench: DRY RUN: Would {action}")
        return True  # Simulate success in dry run

    console.print(f":gear: Attempting: {action}")
    try:
        v1_api.patch_namespace(name=namespace_name, body=patch_body)
        console.print(
            f":white_check_mark: Successfully applied label to namespace [cyan]{namespace_name}[/cyan]"
        )
        logger.info(f"Successfully applied label to namespace '{namespace_name}'")
        return True
    except ApiException as e:
        if e.status == 404:
            console.print(
                f":x: Namespace [cyan]{namespace_name}[/cyan] not found. Cannot apply label."
            )
            logger.error(f"Namespace '{namespace_name}' not found. Cannot apply label.")
        else:
            console.print(
                f":x: Failed to patch namespace [cyan]{namespace_name}[/cyan]: [red]{e.status} - {e.reason}[/red]"
            )
            logger.error(
                f"Failed to patch namespace '{namespace_name}': {e.status} - {e.reason} - {e.body}"
            )
        return False
    except Exception as e:
        console.print(
            f":x: Unexpected error patching namespace [cyan]{namespace_name}[/cyan]: [red]{e}[/red]"
        )
        logger.exception(f"Unexpected error patching namespace '{namespace_name}': {e}")
        return False


def _initialize_kubernetes(kubeconfig: Optional[str]) -> Optional[client.CoreV1Api]:
    """Loads Kubernetes configuration and initializes CoreV1Api client."""
    if not load_kube_config_auto(config_file=kubeconfig):
        return None
    try:
        return client.CoreV1Api()
    except Exception as e:
        logger.exception(f"Failed to initialize Kubernetes CoreV1Api: {e}")
        return None


def _process_groups_and_label(
    v1_api: client.CoreV1Api,
    groups_data: Dict[str, Any],
    label_mapping: Dict[str, Any],
    label_key: str,
    dry_run: bool,
) -> tuple[int, int, int, set[str]]:
    """Processes groups, applies labels, and returns counts."""
    labeled_count = 0
    skipped_count = 0
    error_count = 0
    unmapped_groups: set[str] = set()

    # logger.info("Starting namespace labeling process...") # Keep this in log only
    console.print("[bold blue]Starting namespace labeling process...[/bold blue]")

    for group_id, group_info in groups_data.items():
        if not isinstance(group_info, dict):
            logger.warning(f"Skipping invalid group data for ID '{group_id}' in JSON.")
            continue

        namespaces = group_info.get("namespaces", [])
        if not isinstance(namespaces, list):
            logger.warning(f"Skipping group '{group_id}' due to invalid 'namespaces' format.")
            continue

        label_value = label_mapping.get(group_id)

        if label_value is None:
            if group_id not in unmapped_groups:
                logger.warning(
                    f"No label mapping found for group '{group_id}'. Skipping namespaces in this group."
                )
                unmapped_groups.add(group_id)
            skipped_count += len(namespaces)
            continue

        if not isinstance(label_value, str):
            logger.warning(
                f"Invalid label value '{label_value}' defined for group '{group_id}' in YAML (must be a string). Skipping."
            )
            unmapped_groups.add(group_id)
            skipped_count += len(namespaces)
            continue

        # logger.info(f"Processing group '{group_id}' with label '{label_key}={label_value}'...") # Keep in log only
        console.print(
            f"\nProcessing group [bold magenta]{group_id}[/bold magenta] with label [yellow]{label_key}[/yellow]=[green]{label_value}[/green]..."
        )

        for ns_name in namespaces:
            if not isinstance(ns_name, str) or not ns_name:
                logger.warning(
                    f"Skipping invalid namespace name '{ns_name}' in group '{group_id}'."
                )
                skipped_count += 1
                continue

            success = patch_namespace_label(v1_api, ns_name, label_key, label_value, dry_run)
            if success:
                labeled_count += 1
            else:
                error_count += 1

    return labeled_count, skipped_count, error_count, unmapped_groups


def _log_summary(
    labeled_count: int,
    skipped_count: int,
    error_count: int,
    unmapped_groups: set[str],
    dry_run: bool,
):
    """Logs the summary of the labeling process."""
    summary_lines = []
    if dry_run:
        summary_lines.append(
            f"DRY RUN: Would have attempted to label [bold yellow]{labeled_count}[/bold yellow] namespaces."
        )
    else:
        summary_lines.append(
            f"Successfully labeled: [bold green]{labeled_count}[/bold green] namespaces."
        )

    summary_lines.append(
        f"Skipped (invalid/unmapped/bad value): [bold cyan]{skipped_count}[/bold cyan] namespaces."
    )
    summary_lines.append(f"Errors during patching: [bold red]{error_count}[/bold red] namespaces.")

    panel_title = "Dry Run Summary" if dry_run else "Labeling Summary"
    panel_color = "yellow" if dry_run else "blue"

    summary_text = Text("\n".join(summary_lines), justify="left")
    console.print(Panel(summary_text, title=panel_title, border_style=panel_color, expand=False))

    # Keep detailed warnings in the log file
    logger.info("Namespace labeling process finished.")  # Log completion
    logger.info("--- Summary ---")
    if dry_run:
        logger.info(f"DRY RUN: Would have attempted to label {labeled_count} namespaces.")
    else:
        logger.info(f"Successfully labeled: {labeled_count} namespaces.")
    logger.info(
        f"Skipped (invalid name/group not mapped/invalid mapping): {skipped_count} namespaces."
    )
    logger.info(f"Errors during patching: {error_count} namespaces.")
    if unmapped_groups:
        unmapped_str = ", ".join(sorted(list(unmapped_groups)))
        console.print(
            f"[bold yellow]Warning:[/bold yellow] Groups found in JSON but not in YAML mapping: {unmapped_str}"
        )
        logger.warning(f"Groups found in JSON but not in YAML mapping: {unmapped_str}")


@click.command()
@click.option(
    "--input-json",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to the schedule groups JSON file from k8s_schedule_balancer.py.",
)
@click.option(
    "--config-yaml",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to the YAML configuration file mapping group IDs to label values.",
)
@click.option(
    "--label-key",
    required=True,
    type=str,
    help="The Kubernetes label key to apply (e.g., 'backup-schedule-group').",
)
@click.option(
    "--kubeconfig",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
    default=None,
    help="Path to the kubeconfig file to use (overrides default locations).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="If set, show actions that would be taken without applying labels.",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="If set, enable debug logging.",
)
def main(
    input_json: str,
    config_yaml: str,
    label_key: str,
    kubeconfig: Optional[str],
    dry_run: bool,
    debug: bool,
):
    """Reads namespace group assignments and applies labels based on a mapping config."""
    # --- Setup Logging ---
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    # Use setup_logging from utils, ensuring logs go to output_dir/logs if possible
    # For simplicity, keeping default log dir logic within setup_logging for now.

    setup_logging(level=log_level, script_name=script_base_name)
    # Re-assign logger now that setup is complete
    logger = get_logger(__name__)  # Use utils get_logger

    # Add an early debug message
    logger.debug("Logger setup complete. Script starting main execution.")

    # --- Start Script --- #
    # logger.info("Namespace Labeling Script Started.") # Keep in log only
    console.print("[bold blue]Namespace Labeling Script Started.[/bold blue]")
    if dry_run:
        console.print(
            ":warning: [bold yellow]*** DRY RUN MODE ENABLED ***[/bold yellow] No changes will be applied to the cluster."
        )
        # logger.info("*** DRY RUN MODE ENABLED *** No changes will be applied to the cluster.") # Keep in log
    console.print(f"  [dim]Input JSON:[/dim] [italic]{input_json}[/italic]")
    console.print(f"  [dim]Config YAML:[/dim] [italic]{config_yaml}[/italic]")
    console.print(f"  [dim]Label Key:[/dim] [yellow]{label_key}[/yellow]")
    console.print(
        f"  [dim]Kubeconfig:[/dim] [italic]{kubeconfig if kubeconfig else 'Default locations'}[/italic]"
    )
    # Keep detailed logs
    logger.info(f"Input JSON: {input_json}")
    logger.info(f"Config YAML: {config_yaml}")
    logger.info(f"Label Key: {label_key}")
    logger.info(f"Kubeconfig: {kubeconfig if kubeconfig else 'Default'}")

    # --- Initialize Kubernetes ---
    v1_api = _initialize_kubernetes(kubeconfig)
    if v1_api is None:
        sys.exit(1)

    # --- Load Input Data ---
    groups_data = load_json_data(input_json)
    if groups_data is None:
        logger.error("Failed to load group assignments from JSON.")
        sys.exit(1)

    label_mapping = load_yaml_config(config_yaml)
    if label_mapping is None:
        logger.error("Failed to load label mapping from YAML.")
        sys.exit(1)

    # --- Process Groups and Apply Labels ---
    labeled_count, skipped_count, error_count, unmapped_groups = _process_groups_and_label(
        v1_api, groups_data, label_mapping, label_key, dry_run
    )

    # --- Summary ---
    _log_summary(labeled_count, skipped_count, error_count, unmapped_groups, dry_run)

    # --- Exit Status ---
    if error_count > 0 and not dry_run:
        console.print(
            "[bold red]:x: Completed with errors.[/bold red] Please check the logs for details."
        )
        # logger.error("Completed with errors. Please check the logs above for details.") # Keep in log
        sys.exit(1)
    elif dry_run:
        console.print(
            "[bold yellow]:information: Dry run complete. No changes were made.[/bold yellow]"
        )
        # logger.info("Dry run complete. No changes were made.") # Keep in log
    else:
        console.print("[bold green]:white_check_mark: Labeling complete.[/bold green]")
        # logger.info("Labeling complete.") # Keep in log


if __name__ == "__main__":
    main()
