import json
import logging
import os
import sys
import datetime
from typing import Any, Dict, Optional

import click
import yaml
from kubernetes import client
from kubernetes.client.rest import ApiException

# Import utilities from k8s_utils
from utils.k8s_utils import load_kube_config_auto


def setup_logging(log_file_path: str):
    """Configures logging to file and console."""
    log_dir = os.path.dirname(log_file_path)
    os.makedirs(log_dir, exist_ok=True)

    log_formatter_file = logging.Formatter(
        "%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s"
    )
    log_formatter_console = logging.Formatter("%(levelname)s: %(message)s")

    root_logger = logging.getLogger()
    # Clear existing handlers to avoid duplicate logs if re-running
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    # File Handler (INFO level and above)
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setFormatter(log_formatter_file)
    file_handler.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)

    # Console Handler (INFO level and above for this script for better feedback)
    console_handler = logging.StreamHandler(sys.stderr)  # Log to stderr
    console_handler.setFormatter(log_formatter_console)
    console_handler.setLevel(logging.INFO)  # Show info on console
    root_logger.addHandler(console_handler)


def load_json_data(file_path: str) -> Optional[Dict[str, Any]]:
    """Loads JSON data from a file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
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
        with open(file_path, 'r', encoding='utf-8') as f:
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


def patch_namespace_label(
    v1_api: client.CoreV1Api,
    namespace_name: str,
    label_key: str,
    label_value: str,
    dry_run: bool = False,
) -> bool:
    """Applies a single label to a namespace using patching."""
    patch_body = {
        "metadata": {
            "labels": {
                label_key: label_value
            }
        }
    }

    action = f"Label namespace '{namespace_name}' with '{label_key}={label_value}'"
    if dry_run:
        logging.info(f"DRY RUN: Would {action}")
        return True  # Simulate success in dry run

    logging.info(f"Attempting: {action}")
    try:
        v1_api.patch_namespace(name=namespace_name, body=patch_body)
        logging.info(f"Successfully applied label to namespace '{namespace_name}'")
        return True
    except ApiException as e:
        if e.status == 404:
            logging.error(f"Namespace '{namespace_name}' not found. Cannot apply label.")
        else:
            logging.error(f"Failed to patch namespace '{namespace_name}': {e.status} - {e.reason} - {e.body}")
        return False
    except Exception as e:
        logging.exception(f"Unexpected error patching namespace '{namespace_name}': {e}")
        return False


@click.command()
@click.option(
    "--input-json",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to the schedule groups JSON file from schedule_balancer.py.",
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
def main(
    input_json: str,
    config_yaml: str,
    label_key: str,
    kubeconfig: Optional[str],
    dry_run: bool,
):
    """Reads namespace group assignments and applies labels based on a mapping config."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = "logs"
    log_file = os.path.join(log_dir, f"k8s_label_namespaces_{timestamp}.log")
    setup_logging(log_file)

    logging.info("Namespace Labeling Script Started.")
    if dry_run:
        logging.info("*** DRY RUN MODE ENABLED *** No changes will be applied to the cluster.")
    logging.info(f"Input JSON: {input_json}")
    logging.info(f"Config YAML: {config_yaml}")
    logging.info(f"Label Key: {label_key}")
    logging.info(f"Kubeconfig: {kubeconfig if kubeconfig else 'Default'}")

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
        logging.error("Failed to load group assignments from JSON.")
        sys.exit(1)

    label_mapping = load_yaml_config(config_yaml)
    if label_mapping is None:
        logging.error("Failed to load label mapping from YAML.")
        sys.exit(1)

    # --- Process Groups and Apply Labels ---
    labeled_count = 0
    skipped_count = 0
    error_count = 0
    unmapped_groups = set()

    logging.info("Starting namespace labeling process...")

    for group_id, group_info in groups_data.items():
        if not isinstance(group_info, dict):
            logging.warning(f"Skipping invalid group data for ID '{group_id}' in JSON.")
            continue

        namespaces = group_info.get("namespaces", [])
        if not isinstance(namespaces, list):
            logging.warning(f"Skipping group '{group_id}' due to invalid 'namespaces' format.")
            continue

        # Look up label value in the mapping
        label_value = label_mapping.get(group_id)

        if label_value is None:
            if group_id not in unmapped_groups:
                logging.warning(f"No label mapping found for group '{group_id}'. Skipping namespaces in this group.")
                unmapped_groups.add(group_id)
            skipped_count += len(namespaces)
            continue  # Skip this group

        if not isinstance(label_value, str):
            logging.warning(f"Invalid label value '{label_value}' defined for group '{group_id}' in YAML (must be a string). Skipping.")
            unmapped_groups.add(group_id)  # Treat as unmapped
            skipped_count += len(namespaces)
            continue

        logging.info(f"Processing group '{group_id}' with label '{label_key}={label_value}'...")

        for ns_name in namespaces:
            if not isinstance(ns_name, str) or not ns_name:
                logging.warning(f"Skipping invalid namespace name '{ns_name}' in group '{group_id}'.")
                skipped_count += 1
                continue

            success = patch_namespace_label(
                v1_api, ns_name, label_key, label_value, dry_run
            )
            if success:
                labeled_count += 1
            else:
                error_count += 1

    # --- Summary ---
    logging.info("Namespace labeling process finished.")
    logging.info("--- Summary ---")
    if dry_run:
        logging.info(f"DRY RUN: Would have attempted to label {labeled_count} namespaces.")
    else:
        logging.info(f"Successfully labeled: {labeled_count} namespaces.")
    logging.info(f"Skipped (invalid name/group not mapped/invalid mapping): {skipped_count} namespaces.")
    logging.info(f"Errors during patching: {error_count} namespaces.")
    if unmapped_groups:
        logging.warning(f"Groups found in JSON but not in YAML mapping: {', '.join(sorted(list(unmapped_groups)))}")

    if error_count > 0 and not dry_run:
        logging.error("Completed with errors. Please check the logs above for details.")
        sys.exit(1)
    elif dry_run:
        logging.info("Dry run complete. No changes were made.")
    else:
        logging.info("Labeling complete.")


if __name__ == "__main__":
    main()
