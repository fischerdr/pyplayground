#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test script for Vault Namespace Review.

This script demonstrates how to use the vault_namespace_review module
and provides a simple way to test the functionality.
"""
import json
import logging
import os
import sys
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.json import JSON

from pyplayground.utils.config_utils import get_env_var, load_env_file
from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.vault_utils import perform_namespace_review

logger = get_logger(__name__)


def run_review(namespace: str, debug: bool) -> Dict[str, Any]:
    """Executes the namespace review against a target Vault namespace.

    Args:
        namespace: The Vault namespace to review (e.g., "root").
        debug: A flag to enable verbose debug logging.

    Returns:
        A dictionary containing the complete review results or an error message.
    """
    logger.info(f"Starting namespace review for: '{namespace}'")
    try:
        # Load environment variables from .env file
        load_env_file()

        # Check only VAULT_ADDR since perform_namespace_review will handle token resolution
        vault_addr = get_env_var("VAULT_ADDR", required=True)

        if not vault_addr:
            msg = "VAULT_ADDR environment variable must be set."
            logger.error(msg)
            return {"error": msg}

        logger.info(f"Using Vault at: {vault_addr}")

        # Perform the review - this will handle token resolution including ~/.vault-token
        results = perform_namespace_review(namespace, debug)

        # Log summary
        summary = results.get("summary", {})
        logger.info("Review completed successfully!")
        logger.info(f"  Policies: {summary.get('total_policies', 0)}")
        logger.info(f"  Groups: {summary.get('total_groups', 0)}")
        logger.info(f"  Auth Methods: {summary.get('total_auth_methods', 0)}")
        logger.info(f"  Role Bindings: {summary.get('total_roles', 0)}")
        logger.info(f"  Errors: {len(summary.get('errors', []))}")

        return results

    except Exception as e:
        logger.error(f"Test failed with an unexpected error: {e}", exc_info=debug)
        return {"error": str(e)}


@click.command()
@click.option(
    "--namespace",
    default=None,
    help="The Vault namespace to review. If not provided, uses VAULT_NAMESPACE env var or defaults to 'root'.",
    show_default=False,
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable debug logging.",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, writable=True),
    help="Output file for results (JSON). If not provided, uses VAULT_OUTPUT_DIR env var.",
)
def main(namespace: Optional[str], debug: bool, output: Optional[str]):
    """A CLI tool to perform a comprehensive review of a HashiCorp Vault namespace.

    Prerequisites:
    - The VAULT_ADDR environment variable must be set.
    - Authentication: Set VAULT_TOKEN env var, or use 'vault login' (creates ~/.vault-token).
    - Optional: VAULT_NAMESPACE, VAULT_DEBUG, VAULT_LOG_LEVEL, VAULT_OUTPUT_DIR environment variables.
    - The script requires read permissions on policies, groups, and auth methods
      within the target namespace.
    """
    # Load environment variables from .env file
    load_env_file()

    # Get configuration from environment variables with defaults
    namespace = namespace or get_env_var("VAULT_NAMESPACE", default="root")

    # Set log level based on debug flag or environment variable
    if debug:
        log_level = logging.DEBUG
    else:
        log_level_str = get_env_var("VAULT_LOG_LEVEL", default="INFO")
        # Convert log level string to logging constant
        log_level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        log_level = log_level_map.get(log_level_str.upper(), logging.INFO)

    # Setup Logging
    script_name = os.path.basename(__file__).replace(".py", "")
    setup_logging(level=log_level, script_name=script_name)

    # Run the test
    results = run_review(namespace, debug)

    # Output results
    json_output = json.dumps(results, indent=2, default=str)

    # Determine output file
    if output:
        output_file = output
    else:
        output_dir = get_env_var("VAULT_OUTPUT_DIR", default="./tmp")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        output_file = os.path.join(output_dir, "vault_review_results.json")

    try:
        with open(output_file, "w") as f:
            f.write(json_output)
        logger.info(f"Results written to: {output_file}")
    except IOError as e:
        logger.error(f"Failed to write to output file '{output_file}': {e}")
        sys.exit(1)

    # Display results to console if no specific output file was requested
    if not output:
        console = Console()
        console.print(JSON(json_output))

    # Exit with error if there was an error
    if "error" in results or (results.get("summary", {}).get("errors")):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
