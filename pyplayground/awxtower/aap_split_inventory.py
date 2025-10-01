#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Split AAP inventory JSON file into individual files.

This script processes a JSON file containing multiple inventory entries and splits
them into individual JSON files, one per inventory entry. It also removes the
variables field from inventory entries, adds variables to hosts, and updates
organization names from "Default" to "HYDRA-ENG".
"""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import click

from pyplayground.utils.config_utils import get_env_var, load_env_file
from pyplayground.utils.logging_utils import get_logger, setup_logging

# Setup logging
logger = get_logger(__name__)

# Add project root to path for utils
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


def validate_inventory_names(inventory_entries: List[Dict[str, Any]]) -> tuple[List[str], Set[str]]:
    """Validate uniqueness of inventory names.

    Args:
        inventory_entries: List of inventory entry dictionaries

    Returns:
        Tuple of (valid_inventory_names, duplicate_names)
    """
    inventory_names: List[str] = []
    duplicate_names: Set[str] = set()

    for item in inventory_entries:
        inventory_name = item.get("name")
        if not inventory_name:
            logger.warning("Skipping item with missing name")
            continue

        if inventory_name in inventory_names:
            duplicate_names.add(inventory_name)
        else:
            inventory_names.append(inventory_name)

    return inventory_names, duplicate_names


def _update_inventory_organization(item: Dict[str, Any], target_org: str) -> None:
    """Update organization in inventory entry."""
    if "organization" in item:
        if item["organization"].get("name") == "Default":
            item["organization"]["name"] = target_org
            logger.debug(f"Updated inventory organization to {target_org}")


def _update_related_organizations(item: Dict[str, Any], target_org: str) -> None:
    """Update organizations in related items."""
    if "related" not in item:
        return

    for key, value in item["related"].items():
        if not isinstance(value, list):
            continue
        for related_item in value:
            if isinstance(related_item, dict) and "organization" in related_item:
                if related_item["organization"].get("name") == "Default":
                    related_item["organization"]["name"] = target_org
                    logger.debug(f"Updated related item {key} organization to {target_org}")


def update_organization_names(item: Dict[str, Any], target_org: str = "HYDRA-ENG") -> None:
    """Update organization names from "Default" to target organization.

    Args:
        item: Inventory entry to update
        target_org: Target organization name (default: "HYDRA-ENG")
    """
    _update_inventory_organization(item, target_org)
    _update_related_organizations(item, target_org)


def remove_variables_field(item: Dict[str, Any]) -> None:
    """Remove the variables field from inventory entry.

    Args:
        item: Inventory entry to modify
    """
    if "variables" in item:
        del item["variables"]
        logger.debug("Removed variables field from inventory entry")


def clean_filename(name: str) -> str:
    """Clean a name to be a proper filename.

    Args:
        name: The name to clean

    Returns:
        Cleaned filename
    """
    # Replace invalid filename characters with underscores
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name)
    # Remove multiple consecutive underscores
    cleaned = re.sub(r"_+", "_", cleaned)
    # Remove leading/trailing underscores and dots
    cleaned = cleaned.strip("_.")
    # Ensure it's not empty
    if not cleaned:
        cleaned = "unnamed_inventory"
    return cleaned


def _parse_host_variables(host: Dict[str, Any]) -> Dict[str, Any]:
    """Parse existing variables from a host.

    Args:
        host: Host dictionary

    Returns:
        Parsed variables dictionary
    """
    host_name = host.get("name", "unknown")
    existing_vars = {}

    if "variables" in host and host["variables"]:
        logger.debug(f"Original variables for {host_name}: {repr(host['variables'])}")
        try:
            if isinstance(host["variables"], str):
                existing_vars = json.loads(host["variables"])
            elif isinstance(host["variables"], dict):
                existing_vars = host["variables"]
        except json.JSONDecodeError as e:
            logger.warning(
                f"JSON decode error for host {host_name}: {e}. "
                f"Variables content: {repr(host['variables'])}"
            )
        except TypeError as e:
            logger.warning(
                f"Type error for host {host_name}: {e}. "
                f"Variables type: {type(host['variables'])}, content: {repr(host['variables'])}"
            )
        except Exception as e:
            logger.warning(
                f"Unexpected error parsing variables for host {host_name}: {e}. "
                f"Variables type: {type(host['variables'])}, content: {repr(host['variables'])}"
            )

    return existing_vars


def _clean_ssh_variables(variables: Dict[str, Any], host_name: str) -> None:
    """Remove SSH-related variables from the variables dictionary.

    Args:
        variables: Variables dictionary to clean
        host_name: Name of the host for logging
    """
    ssh_vars_to_remove = [
        "ansible_ssh_host",
        "ansible_ssh_port",
        "ansible_ssh_user",
        "ansible_ssh_private_key_file",
        "ansible_ssh_common_args",
        "ansible_ssh_extra_args",
        "ansible_ssh_pipelining",
        "ansible_ssh_executable",
    ]

    for var in ssh_vars_to_remove:
        if var in variables:
            del variables[var]
            logger.debug(f"Removed {var} from host {host_name}")


def add_host_variables(hosts: List[Dict[str, Any]]) -> None:
    """Add and clean variables for hosts in the inventory.

    Args:
        hosts: List of host dictionaries to modify
    """
    for host in hosts:
        if isinstance(host, dict):
            host_name = host.get("name", "unknown")
            logger.debug(f"Processing host: {host_name}")

            # Parse existing variables
            existing_vars = _parse_host_variables(host)

            # Remove SSH-related variables
            _clean_ssh_variables(existing_vars, host_name)

            # Add ansible_connection: local
            existing_vars["ansible_connection"] = "local"

            # Update host variables
            host["variables"] = json.dumps(existing_vars)
            logger.debug(f"Updated variables for host {host_name}: {existing_vars}")


def process_inventory_entry(
    item: Dict[str, Any], output_dir: Path, target_org: str = "HYDRA-ENG"
) -> Optional[str]:
    """Process a single inventory entry.

    Args:
        item: Inventory entry to process
        output_dir: Directory to save the output file
        target_org: Target organization name

    Returns:
        Path to the saved file if successful, None otherwise
    """
    inventory_name = item.get("name")
    if not inventory_name:
        logger.warning("Skipping item with missing name")
        return None

    # Create a copy of the item to modify
    modified_item = item.copy()

    # Remove variables field from inventory entry
    remove_variables_field(modified_item)

    # Update organization names
    update_organization_names(modified_item, target_org)

    # Add variables to hosts if they exist in related items
    if "related" in modified_item and "hosts" in modified_item["related"]:
        add_host_variables(modified_item["related"]["hosts"])

    # Create new structure with only this object
    output_data = {"inventory": [modified_item]}

    # Clean the inventory name for filename
    clean_name = clean_filename(inventory_name)
    filename = f"{clean_name}.json"
    filepath = output_dir / filename

    try:
        # Write the structured object to a JSON file
        with open(filepath, "w") as f:
            json.dump(output_data, f, indent=4)

        logger.info(f"Saved: {filepath}")
        return str(filepath)
    except IOError as e:
        logger.error(f"Failed to write file {filepath}: {e}")
        return None


def _load_json_file(input_file: str) -> Optional[Dict[str, Any]]:
    """Load and parse JSON file.

    Args:
        input_file: Path to input JSON file

    Returns:
        Parsed JSON data or None if failed
    """
    try:
        with open(input_file, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Input file not found: {input_file}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in input file: {e}")
        return None


def _validate_and_prepare_data(data: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Validate JSON data and extract inventory entries.

    Args:
        data: Parsed JSON data

    Returns:
        List of inventory entries or None if validation failed
    """
    inventory_entries = data.get("inventory", [])
    if not inventory_entries:
        logger.warning("No inventory entries found in input file")
        return None

    logger.info(f"Found {len(inventory_entries)} inventory entries")

    # Validate uniqueness of inventory names
    inventory_names, duplicate_names = validate_inventory_names(inventory_entries)

    # Report duplicates if any
    if duplicate_names:
        logger.error("Duplicate inventory names found:")
        for name in duplicate_names:
            logger.error(f"  - {name}")
        logger.error("Please fix the input file before proceeding.")
        return None

    if not inventory_names:
        logger.warning("No valid inventory names found.")
        return None

    return inventory_entries


def _create_output_directory(output_dir: str) -> Optional[Path]:
    """Create output directory if it doesn't exist.

    Args:
        output_dir: Directory path to create

    Returns:
        Path object or None if failed
    """
    output_path = Path(output_dir)
    try:
        output_path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Created output directory: {output_path}")
        return output_path
    except OSError as e:
        logger.error(f"Failed to create output directory {output_path}: {e}")
        return None


def split_json_file(
    input_file: str, output_dir: str = "output", target_org: str = "HYDRA-ENG"
) -> bool:
    """Split JSON file containing inventory entries into individual files.

    Args:
        input_file: Path to input JSON file
        output_dir: Directory to save output files
        target_org: Target organization name for updates

    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Processing input file: {input_file}")

    # Load and validate JSON file
    data = _load_json_file(input_file)
    if not data:
        return False

    # Validate and prepare inventory entries
    inventory_entries = _validate_and_prepare_data(data)
    if not inventory_entries:
        return False

    # Create output directory
    output_path = _create_output_directory(output_dir)
    if not output_path:
        return False

    # Process each inventory entry
    successful_files = 0
    for item in inventory_entries:
        filepath = process_inventory_entry(item, output_path, target_org)
        if filepath:
            successful_files += 1

    logger.info(
        f"Successfully processed {successful_files} out of {len(inventory_entries)} inventory entries."
    )
    return successful_files > 0


@click.command()
@click.argument("input_file", type=click.Path(exists=True, readable=True))
@click.option(
    "--output-dir",
    "-o",
    default="output",
    help="Output directory for split files (default: output)",
    type=click.Path(),
)
@click.option(
    "--target-org",
    "-t",
    default="HYDRA-ENG",
    help="Target organization name for updates (default: HYDRA-ENG)",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
def main(input_file: str, output_dir: str, target_org: str, debug: bool) -> None:
    """Split AAP inventory JSON file into individual files.

    This script processes a JSON file containing multiple inventory entries and splits
    them into individual JSON files, one per inventory entry. It also removes the
    variables field from inventory entries, adds variables to hosts, and updates
    organization names from "Default" to the specified target organization.

    Examples:
        # Basic usage
        python aap_split_inventory.py inventory.json

        # Custom output directory and target organization
        python aap_split_inventory.py inventory.json --output-dir /tmp/split --target-org MY-ORG

        # With debug logging
        python aap_split_inventory.py inventory.json --debug
    """
    # Setup logging
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Starting AAP inventory split script.")

    # Load environment file if it exists
    try:
        load_env_file()
        logger.debug("Loaded environment variables from .env file")
    except Exception as e:
        logger.debug(f"Could not load .env file: {e}")

    # Get configuration from environment variables if not provided
    if not output_dir or output_dir == "output":
        output_dir = get_env_var("OUTPUT_DIR", default="output")
    if not target_org or target_org == "HYDRA-ENG":
        target_org = get_env_var("TARGET_ORG", default="HYDRA-ENG")

    logger.info(f"Input file: {input_file}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Target organization: {target_org}")

    # Process the file
    success = split_json_file(input_file, output_dir, target_org)

    if success:
        click.echo("Successfully processed inventory entries!")
    else:
        click.echo("Failed to process inventory entries", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
