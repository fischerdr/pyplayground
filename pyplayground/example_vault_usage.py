#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Example usage of Vault Namespace Review functionality.

This script demonstrates how to use the vault namespace review
functionality programmatically.
"""

import json
import os
from typing import Any, Dict

from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.vault_utils import perform_namespace_review


def example_basic_usage():
    """Example of basic usage."""
    logger = get_logger(__name__)

    # Setup logging
    import logging

    setup_logging(level=logging.INFO, script_name="example_vault_usage")

    logger.info("Starting basic usage example")

    # Check environment
    if not os.getenv("VAULT_ADDR") or not os.getenv("VAULT_TOKEN"):
        logger.error("Please set VAULT_ADDR and VAULT_TOKEN environment variables")
        return

    # Perform review
    try:
        results = perform_namespace_review("root", debug=False)

        # Print summary
        summary = results.get("summary", {})
        logger.info(f"Found {summary.get('total_policies', 0)} policies")
        logger.info(f"Found {summary.get('total_groups', 0)} groups")
        logger.info(f"Found {summary.get('total_auth_methods', 0)} auth methods")

        return results

    except Exception as e:
        logger.error(f"Example failed: {e}")
        return None


def example_policy_analysis(results: Dict[str, Any]):
    """Example of analyzing policy results."""
    logger = get_logger(__name__)

    policies = results.get("policies", {}).get("policies", [])

    logger.info("Policy Analysis:")
    for policy in policies:
        name = policy.get("name", "Unknown")
        policy_type = policy.get("type", "Unknown")
        rules = policy.get("rules", "")

        logger.info(f"  Policy: {name} (Type: {policy_type})")
        logger.info(f"    Rules length: {len(rules)} characters")

        # Simple rule analysis
        if "secret" in rules.lower():
            logger.info("    Contains 'secret' references")
        if "auth" in rules.lower():
            logger.info("    Contains 'auth' references")


def example_group_analysis(results: Dict[str, Any]):
    """Example of analyzing group results."""
    logger = get_logger(__name__)

    groups = results.get("groups", {}).get("groups", [])

    logger.info("Group Analysis:")
    for group in groups:
        name = group.get("name", "Unknown")
        group_type = group.get("type", "Unknown")
        member_entities = len(group.get("member_entity_ids", []))
        member_groups = len(group.get("member_group_ids", []))
        policies = group.get("policies", [])

        logger.info(f"  Group: {name} (Type: {group_type})")
        logger.info(f"    Member entities: {member_entities}")
        logger.info(f"    Member groups: {member_groups}")
        logger.info(f"    Policies: {', '.join(policies) if policies else 'None'}")


def example_auth_method_analysis(results: Dict[str, Any]):
    """Example of analyzing auth method results."""
    logger = get_logger(__name__)

    auth_methods = results.get("auth_methods", {}).get("auth_methods", [])

    logger.info("Auth Method Analysis:")
    for auth_method in auth_methods:
        path = auth_method.get("path", "Unknown")
        auth_type = auth_method.get("type", "Unknown")
        description = auth_method.get("description", "")

        logger.info(f"  Auth Method: {path} (Type: {auth_type})")
        if description:
            logger.info(f"    Description: {description}")


def example_error_handling():
    """Example of error handling."""
    logger = get_logger(__name__)

    logger.info("Testing error handling...")

    # This will likely fail if environment is not set up
    try:
        results = perform_namespace_review("non-existent-namespace", debug=False)

        # Check for errors
        errors = results.get("summary", {}).get("errors", [])
        if errors:
            logger.warning(f"Found {len(errors)} errors:")
            for error in errors:
                logger.warning(f"  - {error}")

        return results

    except Exception as e:
        logger.error(f"Error handling example failed: {e}")
        return None


def main():
    """Main example function."""
    logger = get_logger(__name__)

    # Setup logging
    import logging

    setup_logging(level=logging.INFO, script_name="example_vault_usage")

    logger.info("Starting Vault Namespace Review examples")

    # Example 1: Basic usage
    logger.info("=" * 50)
    logger.info("Example 1: Basic Usage")
    logger.info("=" * 50)

    results = example_basic_usage()

    if results:
        # Example 2: Policy analysis
        logger.info("=" * 50)
        logger.info("Example 2: Policy Analysis")
        logger.info("=" * 50)
        example_policy_analysis(results)

        # Example 3: Group analysis
        logger.info("=" * 50)
        logger.info("Example 3: Group Analysis")
        logger.info("=" * 50)
        example_group_analysis(results)

        # Example 4: Auth method analysis
        logger.info("=" * 50)
        logger.info("Example 4: Auth Method Analysis")
        logger.info("=" * 50)
        example_auth_method_analysis(results)

        # Example 5: Save results
        logger.info("=" * 50)
        logger.info("Example 5: Saving Results")
        logger.info("=" * 50)

        with open("example_results.json", "w") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info("Results saved to example_results.json")

    # Example 6: Error handling
    logger.info("=" * 50)
    logger.info("Example 6: Error Handling")
    logger.info("=" * 50)
    example_error_handling()

    logger.info("Examples completed")


if __name__ == "__main__":
    main()
