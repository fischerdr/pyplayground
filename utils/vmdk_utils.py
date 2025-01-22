#!/usr/bin/env python3
"""
VMDK Utility Functions.

This module provides utility functions for VMDK operations and path management.
These functions are shared across the vmdk_manager and related scripts.

Author: Codeium AI
Date: 2025-01-16
"""

import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class VMDKInfo:
    """Data class to store VMDK information."""

    filename: str
    datastore: str
    capacity_gb: float
    path: str


def read_json_config(config_file: str) -> Dict[str, Any]:
    """
    Read and parse JSON configuration file.

    Args:
        config_file: Path to the JSON configuration file

    Returns:
        Dictionary containing the parsed JSON data
    """
    try:
        with open(config_file, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read JSON config file: {str(e)}")
        raise


def write_json_config(config: Dict[str, Any], output_file: str) -> None:
    """
    Write configuration to JSON file.

    Args:
        config: Configuration dictionary to write
        output_file: Path to the output file
    """
    try:
        with open(output_file, "w") as f:
            json.dump(config, f, indent=4)
        logger.info(f"Configuration written to {output_file}")
    except Exception as e:
        logger.error(f"Failed to write JSON config: {str(e)}")
        raise


def read_mapping_file(mapping_file: str) -> List[Tuple[str, str]]:
    """
    Read path mapping from CSV file.

    Args:
        mapping_file: Path to CSV mapping file

    Returns:
        List of tuples containing old and new paths
    """
    try:
        with open(mapping_file, "r") as f:
            return [(row[0], row[1]) for row in csv.reader(f) if len(row) == 2]
    except Exception as e:
        logger.error(f"Failed to read mapping file: {str(e)}")
        raise


def write_mapping_file(mappings: List[Tuple[str, str]], output_file: str) -> None:
    """
    Write path mappings to CSV file.

    Args:
        mappings: List of tuples containing old and new paths
        output_file: Path to the output CSV file
    """
    try:
        with open(output_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(mappings)
        logger.info(f"Mapping file written to {output_file}")
    except Exception as e:
        logger.error(f"Failed to write mapping file: {str(e)}")
        raise


def extract_path_from_datastore_path(datastore_path: str) -> str:
    """
    Extract the file path portion from a datastore path.

    Args:
        datastore_path: Full datastore path (e.g., "[datastore] path/to/file.vmdk")

    Returns:
        File path portion without datastore prefix
    """
    return datastore_path.split("] ", 1)[1] if "] " in datastore_path else datastore_path


def generate_mapping_from_diff(
    config_paths: Dict[str, float], actual_paths: Dict[str, VMDKInfo], mapping_file: str
) -> None:
    """
    Generate mapping file from differences between config and actual paths.

    Args:
        config_paths: Dictionary of paths from configuration
        actual_paths: Dictionary of actual VMDK paths and info
        mapping_file: Path to output mapping file
    """
    mappings: List[Tuple[str, str]] = []

    # Create mapping for paths that exist in both but might need updating
    for config_path, config_size in config_paths.items():
        for actual_path, vmdk_info in actual_paths.items():
            if abs(config_size - vmdk_info.capacity_gb) < 0.1:  # Size matches within 0.1GB
                if config_path != actual_path:
                    mappings.append((config_path, actual_path))
                break

    if mappings:
        write_mapping_file(mappings, mapping_file)
        logger.info(f"Generated mapping file with {len(mappings)} entries")
    else:
        logger.info("No path mappings needed")


def ensure_directory_exists(file_path: str) -> None:
    """
    Ensure the directory for a file exists, create if it doesn't.

    Args:
        file_path: Path to the file
    """
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
