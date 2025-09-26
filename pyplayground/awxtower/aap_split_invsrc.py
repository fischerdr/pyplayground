#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Split AAP inventory sources JSON file into individual files.

This script processes a JSON file containing multiple inventory sources and splits
them into individual JSON files, one per inventory source. It also updates
organization names from "Default" to "HYDRA-ENG" and validates for duplicate
inventory names.
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import click

from pyplayground.utils.config_utils import get_env_var, load_env_file
from pyplayground.utils.logging_utils import get_logger, setup_logging

# Setup logging
logger = get_logger(__name__)


def validate_inventory_names(inventory_sources: List[Dict[str, Any]]) -> tuple[List[str], Set[str]]:
    """Validate uniqueness of inventory names.

    Args:
        inventory_sources: List of inventory source dictionaries

    Returns:
        Tuple of (valid_inventory_names, duplicate_names)
    """
    inventory_names: List[str] = []
    duplicate_names: Set[str] = set()

    for item in inventory_sources:
        inventory_name = item.get("inventory", {}).get("name")
        if not inventory_name:
            logger.warning("Skipping item with missing inventory.name")
            continue

        if inventory_name in inventory_names:
            duplicate_names.add(inventory_name)
        else:
            inventory_names.append(inventory_name)

    return inventory_names, duplicate_names


def _update_inventory_organization(item: Dict[str, Any], target_org: str) -> None:
    """Update organization in inventory section."""
    if "organization" in item.get("inventory", {}):
        if item["inventory"]["organization"].get("name") == "Default":
            item["inventory"]["organization"]["name"] = target_org
            logger.debug(f"Updated inventory organization to {target_org}")


def _update_source_project_organization(item: Dict[str, Any], target_org: str) -> None:
    """Update organization in source_project section."""
    if "source_project" in item and "organization" in item["source_project"]:
        if item["source_project"]["organization"].get("name") == "Default":
            item["source_project"]["organization"]["name"] = target_org
            logger.debug(f"Updated source_project organization to {target_org}")


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
        item: Inventory source item to update
        target_org: Target organization name (default: "HYDRA-ENG")
    """
    _update_inventory_organization(item, target_org)
    _update_source_project_organization(item, target_org)
    _update_related_organizations(item, target_org)


def process_inventory_source(
    item: Dict[str, Any], output_dir: Path, target_org: str = "HYDRA-ENG"
) -> Optional[str]:
    """Process a single inventory source item.

    Args:
        item: Inventory source item to process
        output_dir: Directory to save the output file
        target_org: Target organization name

    Returns:
        Path to the saved file if successful, None otherwise
    """
    inventory_name = item.get("inventory", {}).get("name")
    if not inventory_name:
        logger.warning("Skipping item with missing inventory.name")
        return None

    # Create a copy of the item to modify
    modified_item = item.copy()

    # Update organization names
    update_organization_names(modified_item, target_org)

    # Change the .name field to be the .inventory.name
    modified_item["name"] = inventory_name

    # Create new structure with only this object in the array
    output_data = {"inventory_sources": [modified_item]}

    # Define output file path using inventory name
    filename = f"{inventory_name}.json"
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
    """Validate JSON data and extract inventory sources.

    Args:
        data: Parsed JSON data

    Returns:
        List of inventory sources or None if validation failed
    """
    inventory_sources = data.get("inventory_sources", [])
    if not inventory_sources:
        logger.warning("No inventory_sources found in input file")
        return None

    logger.info(f"Found {len(inventory_sources)} inventory sources")

    # Validate uniqueness of inventory names
    inventory_names, duplicate_names = validate_inventory_names(inventory_sources)

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

    return inventory_sources


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
    """Split JSON file containing inventory sources into individual files.

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

    # Validate and prepare inventory sources
    inventory_sources = _validate_and_prepare_data(data)
    if not inventory_sources:
        return False

    # Create output directory
    output_path = _create_output_directory(output_dir)
    if not output_path:
        return False

    # Process each inventory source
    successful_files = 0
    for item in inventory_sources:
        filepath = process_inventory_source(item, output_path, target_org)
        if filepath:
            successful_files += 1

    logger.info(
        f"Successfully processed {successful_files} out of {len(inventory_sources)} inventory sources."
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
    """Split AAP inventory sources JSON file into individual files.

    This script processes a JSON file containing multiple inventory sources and splits
    them into individual JSON files, one per inventory source. It also updates
    organization names from "Default" to the specified target organization.

    Examples:
        # Basic usage
        python aap_split_invsrc.py inventory_sources.json

        # Custom output directory and target organization
        python aap_split_invsrc.py inventory_sources.json --output-dir /tmp/split --target-org MY-ORG

        # With debug logging
        python aap_split_invsrc.py inventory_sources.json --debug
    """
    # Setup logging
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Starting AAP inventory source split script.")

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
        click.echo("Successfully processed inventory sources!")
    else:
        click.echo("Failed to process inventory sources", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
