#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test script for Vault Namespace Review.

This script demonstrates how to use the vault_namespace_review module
and provides a simple way to test the functionality.
"""

import os
import sys
from typing import Any, Dict

from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.vault_utils import perform_namespace_review


def test_namespace_review(namespace: str = "root", debug: bool = True) -> Dict[str, Any]:
    """Test the namespace review functionality.

    Args:
        namespace: The namespace to review
        debug: Whether to enable debug logging

    Returns:
        Dict containing the review results
    """
    logger = get_logger(__name__)

    # Setup logging
    import logging

    log_level = logging.DEBUG if debug else logging.INFO
    script_name = "test_vault_namespace_review"
    setup_logging(level=log_level, script_name=script_name)

    logger.info(f"Testing namespace review for: {namespace}")

    try:
        # Check environment variables
        vault_addr = os.getenv("VAULT_ADDR")
        vault_token = os.getenv("VAULT_TOKEN")

        if not vault_addr:
            logger.error("VAULT_ADDR environment variable not set")
            return {"error": "VAULT_ADDR not set"}

        if not vault_token:
            logger.error("VAULT_TOKEN environment variable not set")
            return {"error": "VAULT_TOKEN not set"}

        logger.info(f"Using Vault at: {vault_addr}")

        # Perform the review
        results = perform_namespace_review(namespace, debug)

        # Print summary
        summary = results.get("summary", {})
        logger.info("Review completed successfully!")
        logger.info(f"  Policies: {summary.get('total_policies', 0)}")
        logger.info(f"  Groups: {summary.get('total_groups', 0)}")
        logger.info(f"  Auth Methods: {summary.get('total_auth_methods', 0)}")
        logger.info(f"  Errors: {len(summary.get('errors', []))}")

        return results

    except Exception as e:
        logger.error(f"Test failed: {e}")
        return {"error": str(e)}


def main():
    """Main test function."""
    import argparse

    parser = argparse.ArgumentParser(description="Test Vault Namespace Review")
    parser.add_argument("--namespace", default="root", help="Namespace to test")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--output", help="Output file for results")

    args = parser.parse_args()

    # Run the test
    results = test_namespace_review(args.namespace, args.debug)

    # Output results
    import json

    json_output = json.dumps(results, indent=2, default=str)

    if args.output:
        with open(args.output, "w") as f:
            f.write(json_output)
        print(f"Results written to: {args.output}")
    else:
        print(json_output)

    # Exit with error if there was an error
    if "error" in results:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
