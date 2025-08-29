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
from typing import Any, Dict

import click
from rich.console import Console
from rich.json import JSON

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
        # Check environment variables
        if not os.getenv("VAULT_ADDR") or not os.getenv("VAULT_TOKEN"):
            msg = "VAULT_ADDR and VAULT_TOKEN environment variables must be set."
            logger.error(msg)
            return {"error": msg}

        logger.info(f"Using Vault at: {os.getenv('VAULT_ADDR')}")

        # Perform the review
        results = perform_namespace_review(namespace, debug)

        # Log summary
        summary = results.get("summary", {})
        logger.info("Review completed successfully!")
        logger.info(f"  Policies: {summary.get('total_policies', 0)}")
        logger.info(f"  Groups: {summary.get('total_groups', 0)}")
        logger.info(f"  Auth Methods: {summary.get('total_auth_methods', 0)}")
        logger.info(f"  Errors: {len(summary.get('errors', []))}")

        return results

    except Exception as e:
        logger.error(f"Test failed with an unexpected error: {e}", exc_info=debug)
        return {"error": str(e)}


@click.command()
@click.option(
    "--namespace", default="root", help="The Vault namespace to review.", show_default=True
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
@click.option(
    "--output",
    type=click.Path(dir_okay=False, writable=True),
    help="Output file for results (JSON).",
)
def main(namespace: str, debug: bool, output: str):
    """A CLI tool to perform a comprehensive review of a HashiCorp Vault namespace.

    Prerequisites:
    - The VAULT_ADDR and VAULT_TOKEN environment variables must be set.
    - The script requires read permissions on policies, groups, and auth methods
      within the target namespace.
    """
    # Setup Logging
    log_level = logging.DEBUG if debug else logging.INFO
    script_name = os.path.basename(__file__).replace(".py", "")
    setup_logging(level=log_level, script_name=script_name)

    # Run the test
    results = run_review(namespace, debug)

    # Output results
    json_output = json.dumps(results, indent=2, default=str)

    if output:
        try:
            with open(output, "w") as f:
                f.write(json_output)
            logger.info(f"Results written to: {output}")
        except IOError as e:
            logger.error(f"Failed to write to output file '{output}': {e}")
            sys.exit(1)
    else:
        console = Console()
        console.print(JSON(json_output))

    # Exit with error if there was an error
    if "error" in results or (results.get("summary", {}).get("errors")):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
