#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fix AAP job templates JSON file and split into individual files.

This script processes a JSON file containing multiple job templates and:
1. Updates credentials based on a configurable mapping
2. Updates organization names from "Default" to "HYDRA-ENG"
3. Splits them into individual JSON files, one per job template
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

# Add project root to path for utils
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

# Default credential mapping
DEFAULT_CREDENTIAL_MAPPING = {
    "ssh-key": {
        "name": "Localhost",
        "credential_type": {
            "name": "Machine",
            "kind": "ssh",
            "type": "credential_type",
        },
    },
    "vault-token": {
        "name": "hydra_cloud_amex_vault_token_credentials",
        "credential_type": {
            "name": "hydra_cloud_amex_vault_token_credential_type",
            "kind": "cloud",
            "type": "credential_type",
        },
    },
}


def validate_job_template_names(job_templates: List[Dict[str, Any]]) -> tuple[List[str], Set[str]]:
    """Validate uniqueness of job template names.

    Args:
        job_templates: List of job template dictionaries

    Returns:
        Tuple of (valid_template_names, duplicate_names)
    """
    template_names: List[str] = []
    duplicate_names: Set[str] = set()

    for item in job_templates:
        template_name = item.get("name")
        if not template_name:
            logger.warning("Skipping item with missing name")
            continue

        if template_name in template_names:
            duplicate_names.add(template_name)
        else:
            template_names.append(template_name)

    return template_names, duplicate_names


def _update_organization_in_dict(data: Dict[str, Any], target_org: str, path: str = "") -> None:
    """Recursively update organization names in a dictionary.

    Args:
        data: Dictionary to update
        target_org: Target organization name
        path: Current path in the dictionary (for logging)
    """
    if not isinstance(data, dict):
        return

    # Check if this dict has an organization field
    if "organization" in data and isinstance(data["organization"], dict):
        if data["organization"].get("name") == "Default":
            data["organization"]["name"] = target_org
            logger.debug(f"Updated organization to {target_org} at path: {path}")

    # Recursively process nested dictionaries and lists
    for key, value in data.items():
        current_path = f"{path}.{key}" if path else key

        if isinstance(value, dict):
            _update_organization_in_dict(value, target_org, current_path)
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, dict):
                    _update_organization_in_dict(item, target_org, f"{current_path}[{idx}]")


def update_credentials(
    item: Dict[str, Any],
    credential_mapping: Optional[Dict[str, Any]] = None,
    target_org: str = "HYDRA-ENG",
) -> None:
    """Update credentials in job template based on mapping.

    Args:
        item: Job template item to update
        credential_mapping: Mapping of old credential names to new configuration
        target_org: Target organization name
    """
    if credential_mapping is None:
        credential_mapping = DEFAULT_CREDENTIAL_MAPPING

    # Handle both direct credentials and related.credentials paths
    credentials_path = None
    if "related" in item and "credentials" in item.get("related", {}):
        credentials_path = "related"
        credentials = item["related"].get("credentials", [])
    elif "credentials" in item:
        credentials_path = "direct"
        credentials = item.get("credentials", [])
    else:
        logger.debug("No credentials found in job template")
        return

    if not credentials:
        logger.debug("Credentials list is empty")
        return

    updated_credentials = []

    for cred in credentials:
        old_name = cred.get("name")
        if old_name in credential_mapping:
            # Create new credential based on mapping
            new_cred = {
                "organization": {
                    "name": target_org,
                    "type": "organization",
                },
                "name": credential_mapping[old_name]["name"],
                "credential_type": credential_mapping[old_name]["credential_type"].copy(),
                "type": "credential",
            }
            updated_credentials.append(new_cred)
            logger.debug(f"Replaced credential '{old_name}' with '{new_cred['name']}'")
        else:
            # Keep the credential but update organization if needed
            if "organization" in cred and isinstance(cred["organization"], dict):
                if cred["organization"].get("name") == "Default":
                    cred["organization"]["name"] = target_org
            updated_credentials.append(cred)
            logger.debug(f"Kept credential '{old_name}' with updated organization")

    # Update the credentials list in the correct location
    if credentials_path == "related":
        item["related"]["credentials"] = updated_credentials
    else:
        item["credentials"] = updated_credentials


def update_organization_names(item: Dict[str, Any], target_org: str = "HYDRA-ENG") -> None:
    """Update organization names from "Default" to target organization.

    Args:
        item: Job template item to update
        target_org: Target organization name (default: "HYDRA-ENG")
    """
    _update_organization_in_dict(item, target_org)


def _merge_with_template(item: Dict[str, Any], template: Dict[str, Any]) -> Dict[str, Any]:
    """Merge job template item with template to add missing keys.

    Args:
        item: Job template item to merge
        template: Template with default values

    Returns:
        Merged job template item
    """
    # Create a deep copy of the template
    merged_item = json.loads(json.dumps(template))

    # Update with values from the input item, preserving template defaults for missing keys
    for key, value in item.items():
        if key in merged_item:
            if isinstance(value, dict) and isinstance(merged_item[key], dict):
                # Recursively merge nested dictionaries
                merged_item[key] = _merge_nested_dicts(merged_item[key], value)
            else:
                # Override template value with input value
                merged_item[key] = value
        else:
            # Add new keys from input that aren't in template
            merged_item[key] = value

    # Add missing keys from template that aren't in input
    for key, value in template.items():
        if key not in item:
            merged_item[key] = json.loads(json.dumps(value))  # Deep copy template value

    logger.debug("Merged item with template, added missing keys")
    return merged_item


def _merge_nested_dicts(
    template_dict: Dict[str, Any], input_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Recursively merge nested dictionaries.

    Args:
        template_dict: Template dictionary with default values
        input_dict: Input dictionary with actual values

    Returns:
        Merged dictionary
    """
    result = template_dict.copy()

    for key, value in input_dict.items():
        if key in result and isinstance(value, dict) and isinstance(result[key], dict):
            result[key] = _merge_nested_dicts(result[key], value)
        else:
            result[key] = value

    return result


def process_job_template(
    item: Dict[str, Any],
    output_dir: Path,
    target_org: str = "HYDRA-ENG",
    credential_mapping: Optional[Dict[str, Any]] = None,
    template: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Process a single job template item.

    Args:
        item: Job template item to process
        output_dir: Directory to save the output file
        target_org: Target organization name
        credential_mapping: Mapping for credential updates
        template: Template to merge with item (optional)

    Returns:
        Path to the saved file if successful, None otherwise
    """
    template_name = item.get("name")
    if not template_name:
        logger.warning("Skipping item with missing name")
        return None

    # Merge with template if provided
    if template:
        modified_item = _merge_with_template(item, template)
        logger.debug(f"Merged item with template for {template_name}")
    else:
        # Create a copy of the item to modify
        modified_item = json.loads(json.dumps(item))  # Deep copy

    # Always set inventory to null
    modified_item["inventory"] = None
    logger.debug("Set inventory to null")

    # Ensure related section exists and initialize credentials/schedules
    if "related" not in modified_item:
        modified_item["related"] = {}
    if "schedules" not in modified_item["related"]:
        modified_item["related"]["schedules"] = []
    else:
        # Always reset schedules to empty array
        modified_item["related"]["schedules"] = []
    logger.debug("Initialized related.schedules to []")

    # Update credentials first
    update_credentials(modified_item, credential_mapping, target_org)

    # Update organization names throughout the structure
    update_organization_names(modified_item, target_org)

    # Remove custom_virtualenv key if it exists
    if "custom_virtualenv" in modified_item:
        del modified_item["custom_virtualenv"]
        logger.debug("Removed custom_virtualenv key")

    # Create new structure with only this object in the array
    output_data = {"job_templates": [modified_item]}

    # Define output file path using template name
    # Sanitize filename by replacing spaces and special chars
    safe_name = template_name.replace(" ", "_").replace("/", "_")
    filename = f"{safe_name}.json"
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


def _load_credential_mapping(mapping_file: str) -> Optional[Dict[str, Any]]:
    """Load credential mapping from JSON file.

    Args:
        mapping_file: Path to credential mapping JSON file

    Returns:
        Credential mapping or None if failed
    """
    try:
        with open(mapping_file, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Credential mapping file not found: {mapping_file}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in credential mapping file: {e}")
        return None


def _load_template_file(template_file: str) -> Optional[Dict[str, Any]]:
    """Load and parse template JSON file.

    Args:
        template_file: Path to template JSON file

    Returns:
        Parsed template data or None if failed
    """
    try:
        with open(template_file, "r") as f:
            data = json.load(f)

        # If the template has a job_templates array, extract the first item
        if "job_templates" in data and isinstance(data["job_templates"], list):
            if len(data["job_templates"]) > 0:
                logger.debug("Template has job_templates wrapper, extracting first template")
                return data["job_templates"][0]
            else:
                logger.error("Template file has empty job_templates array")
                return None

        # Otherwise, assume it's a direct template object
        return data
    except FileNotFoundError:
        logger.error(f"Template file not found: {template_file}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in template file: {e}")
        return None


def _validate_and_prepare_data(data: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Validate JSON data and extract job templates.

    Args:
        data: Parsed JSON data

    Returns:
        List of job templates or None if validation failed
    """
    job_templates = data.get("job_templates", [])
    if not job_templates:
        logger.warning("No job_templates found in input file")
        return None

    logger.info(f"Found {len(job_templates)} job templates")

    # Validate uniqueness of template names
    template_names, duplicate_names = validate_job_template_names(job_templates)

    # Report duplicates if any
    if duplicate_names:
        logger.error("Duplicate job template names found:")
        for name in duplicate_names:
            logger.error(f"  - {name}")
        logger.error("Please fix the input file before proceeding.")
        return None

    if not template_names:
        logger.warning("No valid job template names found.")
        return None

    return job_templates


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


def fix_job_templates(
    input_file: str,
    output_dir: str = "output",
    target_org: str = "HYDRA-ENG",
    credential_mapping_file: Optional[str] = None,
    template_file: Optional[str] = None,
) -> bool:
    """Fix and split JSON file containing job templates into individual files.

    Args:
        input_file: Path to input JSON file
        output_dir: Directory to save output files
        target_org: Target organization name for updates
        credential_mapping_file: Path to credential mapping JSON file (optional)
        template_file: Path to template JSON file (optional)

    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Processing input file: {input_file}")

    # Load and validate JSON file
    data = _load_json_file(input_file)
    if not data:
        return False

    # Load credential mapping if provided, otherwise use defaults
    credential_mapping = None
    if credential_mapping_file:
        logger.info(f"Loading credential mapping file: {credential_mapping_file}")
        credential_mapping = _load_credential_mapping(credential_mapping_file)
        if not credential_mapping:
            logger.warning("Failed to load credential mapping, using defaults")
            credential_mapping = DEFAULT_CREDENTIAL_MAPPING
        else:
            logger.info("Credential mapping loaded successfully")
    else:
        logger.info("Using default credential mapping")
        credential_mapping = DEFAULT_CREDENTIAL_MAPPING

    # Load template file if provided
    template = None
    if template_file:
        logger.info(f"Loading template file: {template_file}")
        template = _load_template_file(template_file)
        if not template:
            logger.warning("Failed to load template file, proceeding without template")
        else:
            logger.info("Template loaded successfully")

    # Validate and prepare job templates
    job_templates = _validate_and_prepare_data(data)
    if not job_templates:
        return False

    # Create output directory
    output_path = _create_output_directory(output_dir)
    if not output_path:
        return False

    # Process each job template
    successful_files = 0
    for item in job_templates:
        filepath = process_job_template(item, output_path, target_org, credential_mapping, template)
        if filepath:
            successful_files += 1

    logger.info(
        f"Successfully processed {successful_files} out of {len(job_templates)} job templates."
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
    "--credential-mapping",
    "-c",
    help="JSON file containing credential mapping configuration",
    type=click.Path(exists=True, readable=True),
)
@click.option(
    "--template",
    "-T",
    help="Template JSON file to merge with input data",
    type=click.Path(exists=True, readable=True),
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
def main(
    input_file: str,
    output_dir: str,
    target_org: str,
    credential_mapping: Optional[str],
    template: Optional[str],
    debug: bool,
) -> None:
    """Fix AAP job templates JSON file and split into individual files.

    This script processes a JSON file containing multiple job templates and:
    1. Updates credentials based on a configurable mapping
    2. Updates organization names from "Default" to the specified target organization
    3. Splits them into individual JSON files, one per job template
    4. Optionally merges with a template to add missing fields

    Default credential mapping:
    - ssh-key → Localhost (Machine/ssh)
    - vault-token → hydra_cloud_amex_vault_token_credentials (cloud)

    Examples:
        # Basic usage with default credential mapping
        python aap_fix_job_templates.py job_templates.json

        # Custom output directory and target organization
        python aap_fix_job_templates.py job_templates.json --output-dir /tmp/fixed --target-org MY-ORG

        # With custom credential mapping file
        python aap_fix_job_templates.py job_templates.json --credential-mapping mapping.json

        # With template file to add missing fields
        python aap_fix_job_templates.py job_templates.json --template template.json

        # With debug logging
        python aap_fix_job_templates.py job_templates.json --debug
    """
    # Setup logging
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Starting AAP job template fix script.")

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
    if credential_mapping:
        logger.info(f"Credential mapping file: {credential_mapping}")
    if template:
        logger.info(f"Template file: {template}")

    # Process the file
    success = fix_job_templates(input_file, output_dir, target_org, credential_mapping, template)

    if success:
        click.echo("Successfully processed job templates!")
    else:
        click.echo("Failed to process job templates", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
