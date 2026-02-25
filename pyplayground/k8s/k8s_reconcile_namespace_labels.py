#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconciles namespace labels based on a mapping configuration."""
import datetime
import json
import logging
import os
import sys
from typing import Any, Dict, Optional, Set

import click
import yaml
from kubernetes import client
from kubernetes.client.rest import ApiException

# Import utilities from k8s_utils
from pyplayground.utils.k8s_utils import load_kube_config_auto

# --- Boilerplate Setup Functions (Copied from k8s_label_namespaces.py) ---


def setup_logging(log_file_path: str):
    """Configures logging to file and console."""
    log_dir = os.path.dirname(log_file_path)
    os.makedirs(log_dir, exist_ok=True)

    log_formatter_file = logging.Formatter("%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s")
    log_formatter_console = logging.Formatter("%(levelname)s: %(message)s")

    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_file_path)
    file_handler.setFormatter(log_formatter_file)
    file_handler.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(log_formatter_console)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)


def load_json_data(file_path: str) -> Optional[Dict[str, Any]]:
    """Loads JSON data from a file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error(f"Input JSON file not found: {file_path}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON file {file_path}: {e}")
        return None
    except Exception as e:
        logging.exception(f"Unexpected error loading JSON file {file_path}: {e}")
        return None


def load_yaml_config(file_path: str) -> Optional[Dict[str, Any]]:
    """Loads YAML configuration from a file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logging.error(f"Configuration YAML file not found: {file_path}")
        return None
    except yaml.YAMLError as e:
        logging.error(f"Error parsing YAML file {file_path}: {e}")
        return None
    except Exception as e:
        logging.exception(f"Unexpected error loading YAML file {file_path}: {e}")
        return None


# --- Reconciliation Logic ---


def reconcile_namespace_label(
    v1_api: client.CoreV1Api,
    namespace_name: str,
    label_key: str,
    desired_value: str,
    dry_run: bool = False,
) -> str:
    """Checks the current label and applies patch if needed. Returns status."""
    try:
        namespace = v1_api.read_namespace(name=namespace_name)
        current_labels = namespace.metadata.labels if namespace.metadata.labels else {}
        current_value = current_labels.get(label_key)

        action_prefix = "DRY RUN:" if dry_run else ""

        if current_value == desired_value:
            logging.debug(f"Namespace '{namespace_name}': Label '{label_key}' already set to '{desired_value}'. No change needed.")
            return "NO_CHANGE"
        elif current_value is None:
            action = f"Add label '{label_key}={desired_value}' to namespace '{namespace_name}'"
            patch_type = "ADD"
        else:
            action = f"Update label '{label_key}' from '{current_value}' to '{desired_value}' for namespace '{namespace_name}'"
            patch_type = "UPDATE"

        patch_body = {"metadata": {"labels": {label_key: desired_value}}}

        if dry_run:
            logging.info(f"{action_prefix} Would {action}")
            return patch_type  # Simulate success in dry run
        else:
            logging.info(f"Attempting: {action}")
            # Use merge-patch to only add/update the specific label
            v1_api.patch_namespace(name=namespace_name, body=patch_body, _content_type="application/merge-patch+json")
            logging.info(f"Successfully {'added' if patch_type == 'ADD' else 'updated'} label for namespace '{namespace_name}'")
            return patch_type

    except ApiException as e:
        if e.status == 404:
            logging.error(f"Namespace '{namespace_name}' not found. Cannot reconcile label.")
        else:
            logging.error(f"Failed to reconcile label for namespace '{namespace_name}': {e.status} - {e.reason} - {e.body}")
        return "ERROR"
    except Exception as e:
        logging.exception(f"Unexpected error reconciling label for namespace '{namespace_name}': {e}")
        return "ERROR"


def get_namespaces_with_label(v1_api: client.CoreV1Api, label_key: str) -> Optional[Set[str]]:
    """Gets a set of names for all namespaces that have the specified label key."""
    try:
        # List namespaces with the label key present
        namespaces = v1_api.list_namespace(label_selector=label_key)
        return {ns.metadata.name for ns in namespaces.items}
    except ApiException as e:
        logging.error(f"Failed to list namespaces with label '{label_key}': {e.status} - {e.reason}")
        return None
    except Exception as e:
        logging.exception(f"Unexpected error listing namespaces with label '{label_key}': {e}")
        return None


@click.command()
@click.option(
    "--input-json",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to the LATEST schedule groups JSON file from k8s_schedule_balancer.py.",
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
    help="The Kubernetes label key to reconcile (e.g., 'backup-schedule-group').",
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
    "--check-orphans",
    is_flag=True,
    default=False,
    help="If set, check for namespaces with the label that are NOT in the input JSON.",
)
def main(  # noqa: C901
    input_json: str,
    config_yaml: str,
    label_key: str,
    kubeconfig: Optional[str],
    dry_run: bool,
    check_orphans: bool,
):
    """Reconciles namespace labels based on group assignments and a mapping config."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = "logs"
    log_file = os.path.join(log_dir, f"k8s_reconcile_labels_{timestamp}.log")
    setup_logging(log_file)

    logging.info("Namespace Label Reconciliation Script Started.")
    if dry_run:
        logging.info("*** DRY RUN MODE ENABLED *** No changes will be applied to the cluster.")
    logging.info(f"Input JSON (Desired State): {input_json}")
    logging.info(f"Config YAML (Group->Value Map): {config_yaml}")
    logging.info(f"Label Key to Reconcile: {label_key}")
    logging.info(f"Kubeconfig: {kubeconfig if kubeconfig else 'Default'}")
    logging.info(f"Check for Orphans: {check_orphans}")

    # --- Load Kubernetes Config ---
    if not load_kube_config_auto(config_file=kubeconfig):
        sys.exit(1)

    try:
        v1_api = client.CoreV1Api()
    except Exception as e:
        logging.exception(f"Failed to initialize Kubernetes CoreV1Api: {e}")
        sys.exit(1)

    # --- Load Input Data ---
    groups_data = load_json_data(input_json)
    if groups_data is None:
        logging.error("Failed to load desired state from JSON.")
        sys.exit(1)

    label_mapping = load_yaml_config(config_yaml)
    if label_mapping is None:
        logging.error("Failed to load label mapping from YAML.")
        sys.exit(1)

    # --- Build Desired State Map (Namespace -> Desired Label Value) ---
    desired_ns_labels: Dict[str, str] = {}
    unmapped_groups = set()
    processed_ns_from_json = set()

    logging.info("Building desired state map from inputs...")
    for group_id, group_info in groups_data.items():
        if not isinstance(group_info, dict):
            logging.warning(f"Skipping invalid group data for ID '{group_id}' in JSON.")
            continue
        namespaces = group_info.get("namespaces", [])
        if not isinstance(namespaces, list):
            logging.warning(f"Skipping group '{group_id}' due to invalid 'namespaces' format.")
            continue

        desired_value = label_mapping.get(group_id)
        if desired_value is None:
            if group_id not in unmapped_groups:
                logging.warning(f"No label mapping found for group '{group_id}'. Namespaces in this group will be skipped.")
                unmapped_groups.add(group_id)
            processed_ns_from_json.update(ns for ns in namespaces if isinstance(ns, str) and ns)
            continue  # Skip mapping for this group

        if not isinstance(desired_value, str):
            logging.warning(f"Invalid label value '{desired_value}' defined for group '{group_id}' in YAML (must be a string). Skipping.")
            unmapped_groups.add(group_id)
            processed_ns_from_json.update(ns for ns in namespaces if isinstance(ns, str) and ns)
            continue

        for ns_name in namespaces:
            if isinstance(ns_name, str) and ns_name:
                if ns_name in desired_ns_labels:
                    logging.warning(f"Namespace '{ns_name}' found in multiple groups in JSON. Using mapping from group '{group_id}'.")
                desired_ns_labels[ns_name] = desired_value
                processed_ns_from_json.add(ns_name)
            else:
                logging.warning(f"Skipping invalid namespace name '{ns_name}' in group '{group_id}'.")

    logging.info(f"Desired state map built for {len(desired_ns_labels)} namespaces.")
    if unmapped_groups:
        logging.warning(f"Skipped processing for groups not in YAML mapping: {', '.join(sorted(list(unmapped_groups)))}")

    # --- Reconcile Labels --- #
    results = {"ADD": 0, "UPDATE": 0, "NO_CHANGE": 0, "ERROR": 0, "SKIP_UNMAPPED": 0}

    logging.info("Starting label reconciliation process...")
    for ns_name, desired_value in desired_ns_labels.items():
        status = reconcile_namespace_label(v1_api, ns_name, label_key, desired_value, dry_run)
        results[status] += 1

    # Calculate skipped count based on unmapped groups found earlier
    skipped_count = len(processed_ns_from_json) - len(desired_ns_labels)

    # --- Orphan Check (Optional) ---
    orphans_found = set()
    if check_orphans:
        logging.info("Checking for orphaned namespaces (labeled but not in desired state)...")
        namespaces_with_label_in_cluster = get_namespaces_with_label(v1_api, label_key)
        if namespaces_with_label_in_cluster is not None:
            orphans_found = namespaces_with_label_in_cluster - processed_ns_from_json
            if orphans_found:
                logging.warning(f"Found {len(orphans_found)} potential orphan namespaces with label '{label_key}' but not in input JSON: {', '.join(sorted(list(orphans_found)))}")
            else:
                logging.info("No orphan namespaces found with the specified label.")
        else:
            logging.error("Could not perform orphan check due to error listing namespaces.")

    # --- Final Summary ---
    logging.info("Namespace label reconciliation finished.")
    logging.info("--- Summary ---")
    action_prefix = "DRY RUN: Would have " if dry_run else ""
    logging.info(f"{action_prefix}Added label: {results['ADD']} namespaces.")
    logging.info(f"{action_prefix}Updated label: {results['UPDATE']} namespaces.")
    logging.info(f"No change needed: {results['NO_CHANGE']} namespaces.")
    logging.info(f"Skipped (group not mapped in YAML, invalid NS name): {skipped_count} namespaces.")
    logging.info(f"Errors encountered: {results['ERROR']} namespaces.")
    if check_orphans:
        logging.info(f"Potential orphan namespaces found: {len(orphans_found)}")

    final_status = "DRY RUN complete" if dry_run else "Reconciliation complete"
    if results["ERROR"] > 0:
        logging.error(f"{final_status} with errors. Please check logs.")
        sys.exit(1)
    else:
        logging.info(f"{final_status}.")


if __name__ == "__main__":
    main()
