#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Example usage of Vault Namespace Review functionality.

This script demonstrates how to use the vault namespace review
functionality programmatically.
"""
import json
import logging
import os
from typing import Any, Dict, Optional

import click
from rich.console import Console

from pyplayground.utils.config_utils import get_env_var, load_env_file
from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.vault_utils import VaultError, perform_namespace_review

logger = get_logger(__name__)


def example_basic_usage(namespace: str, debug: bool) -> Optional[Dict[str, Any]]:
    """Performs a basic namespace review and logs a summary of the findings.

    Args:
        namespace: The target Vault namespace to review.
        debug: A flag to enable verbose debug logging.

    Returns:
        A dictionary containing the review results, or None if the review fails.
    """
    logger.info("Starting basic usage example")

    # Load environment variables from .env file
    load_env_file()

    # Check only VAULT_ADDR since perform_namespace_review will handle token resolution
    vault_addr = get_env_var("VAULT_ADDR", required=True)

    if not vault_addr:
        logger.error("Please set VAULT_ADDR environment variable")
        return None

    # Perform review
    try:
        results = perform_namespace_review(namespace, debug=debug)

        # Log summary
        summary = results.get("summary", {})
        logger.info(f"Found {summary.get('total_policies', 0)} policies")
        logger.info(f"Found {summary.get('total_groups', 0)} groups")
        logger.info(f"Found {summary.get('total_auth_methods', 0)} auth methods")

        return results

    except VaultError as e:
        logger.error(f"Example failed due to a Vault API error: {e}", exc_info=debug)
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred in basic example: {e}", exc_info=debug)
        return None


def example_policy_analysis(results: Dict[str, Any]):
    """Analyzes and logs details from the 'policies' section of the review results.

    Args:
        results: The review results to analyze.
    """
    policies = results.get("policies", {}).get("policies", [])
    logger.info(f"Analyzing {len(policies)} policies...")
    for policy in policies:
        name = policy.get("name", "Unknown")
        rules = policy.get("rules", "")
        logger.info(f"  - Policy: {name} (Rules length: {len(rules)} chars)")
        if "secret" in rules.lower():
            logger.info("    Contains 'secret' path references.")
        if "deny" in rules.lower() or "forbidden" in rules.lower():
            logger.warning("    Contains 'deny' or 'forbidden' rules.")


def example_group_analysis(results: Dict[str, Any]):
    """Analyzes and logs details from the 'groups' section of the review results.

    Args:
        results: The review results to analyze.
    """
    groups = results.get("groups", {}).get("groups", [])
    logger.info(f"Analyzing {len(groups)} groups...")
    for group in groups:
        name = group.get("name", "Unknown")
        policies = group.get("policies", [])
        logger.info(f"  - Group: {name} (Policies: {', '.join(policies) if policies else 'None'})")


def example_auth_method_analysis(results: Dict[str, Any]):
    """Analyzes and logs details from the 'auth_methods' section of the review results.

    Args:
        results: The review results to analyze.
    """
    auth_methods = results.get("auth_methods", {}).get("auth_methods", [])
    logger.info(f"Analyzing {len(auth_methods)} auth methods...")
    for auth_method in auth_methods:
        path = auth_method.get("path", "Unknown")
        auth_type = auth_method.get("type", "Unknown")
        logger.info(f"  - Auth Method: {path} (Type: {auth_type})")


def example_role_binding_analysis(results: Dict[str, Any]):
    """Analyzes and logs details from the 'role_bindings' section of the review results.

    Args:
        results: The review results to analyze.
    """
    role_bindings = results.get("role_bindings", {}).get("role_bindings", [])
    total_roles = results.get("summary", {}).get("total_roles", 0)
    logger.info(f"Analyzing role bindings for {len(role_bindings)} auth methods ({total_roles} total roles)...")

    for auth_method_binding in role_bindings:
        auth_path = auth_method_binding.get("auth_method", "Unknown")
        auth_type = auth_method_binding.get("auth_type", "Unknown")
        roles = auth_method_binding.get("roles", [])
        errors = auth_method_binding.get("errors", [])

        logger.info(f"  - Auth Method: {auth_path} (Type: {auth_type})")
        logger.info(f"    Roles: {len(roles)}, Errors: {len(errors)}")

        for role in roles:
            role_name = role.get("name", "Unknown")
            role_type = role.get("type", "Unknown")
            policies = role.get("token_policies", role.get("policies", []))
            logger.info(f"    - Role: {role_name} (Type: {role_type}, Policies: {len(policies)})")

            # Log specific details based on auth type
            if auth_type == "kubernetes":
                bound_sa = role.get("bound_service_account_names", [])
                bound_ns = role.get("bound_service_account_namespaces", [])
                logger.info(f"      Service Accounts: {bound_sa}")
                logger.info(f"      Namespaces: {bound_ns}")
            elif auth_type == "aws":
                bound_accounts = role.get("bound_account_id", [])
                bound_arns = role.get("bound_arn", [])
                logger.info(f"      AWS Accounts: {bound_accounts}")
                logger.info(f"      Bound ARNs: {len(bound_arns)} configured")
            elif auth_type == "ldap":
                if role_type == "ldap_group":
                    logger.info(f"      LDAP Group with {len(policies)} policies")
                elif role_type == "ldap_user":
                    groups = role.get("groups", [])
                    logger.info(f"      LDAP User in groups: {groups}")

        if errors:
            logger.warning("    Errors encountered:")
            for error in errors:
                logger.warning(f"      - {error}")


def example_error_handling(debug: bool):
    """Demonstrates how errors are captured and reported during a review of a non-existent namespace.

    Args:
        debug: A flag to enable verbose debug logging.
    """
    logger.info("Testing error handling with a non-existent namespace...")

    # This will fail because the namespace does not exist.
    results = perform_namespace_review("non-existent-namespace", debug=debug)
    errors = results.get("summary", {}).get("errors", [])
    if errors:
        logger.warning(f"Successfully captured {len(errors)} errors:")
        for error in errors:
            logger.warning(f"  - {error}")
    else:
        logger.info("No errors were captured (this may be unexpected).")


@click.command()
@click.option(
    "--namespace",
    default=None,
    help="The target Vault namespace to review. If not provided, uses VAULT_NAMESPACE env var or defaults to 'root'.",
    show_default=False,
)
@click.option(
    "--debug",
    is_flag=True,
    default=None,
    help="Enable debug logging. Overrides VAULT_DEBUG env var.",
)
def main(namespace: Optional[str], debug: Optional[bool]):
    """Runs a series of examples demonstrating how to use and interpret the results of the `perform_namespace_review` utility.

    Prerequisites:
        - VAULT_ADDR environment variable must be set.
        - Authentication: Set VAULT_TOKEN env var, or use 'vault login' (creates ~/.vault-token).
        - Optional: VAULT_NAMESPACE, VAULT_DEBUG, VAULT_LOG_LEVEL environment variables.
    """
    # Load environment variables from .env file
    load_env_file()

    # Get configuration from environment variables with defaults
    namespace = namespace or get_env_var("VAULT_NAMESPACE", default="root")
    debug = debug if debug is not None else get_env_var("VAULT_DEBUG", default=False, as_type=bool)
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
    setup_logging(level=log_level, script_name="example_vault_usage")
    console = Console()

    console.rule("[bold]Vault Namespace Review Examples[/bold]")

    # Example 1: Basic usage
    console.rule("Example 1: Basic Usage")
    results = example_basic_usage(namespace, debug)

    if results:
        # Example 2: Policy analysis
        console.rule("Example 2: Policy Analysis")
        example_policy_analysis(results)

        # Example 3: Group analysis
        console.rule("Example 3: Group Analysis")
        example_group_analysis(results)

        # Example 4: Auth method analysis
        console.rule("Example 4: Auth Method Analysis")
        example_auth_method_analysis(results)

        # Example 5: Role binding analysis
        console.rule("Example 5: Role Binding Analysis")
        example_role_binding_analysis(results)

        # Example 6: Save results
        console.rule("Example 6: Saving Results")
        output_dir = get_env_var("VAULT_OUTPUT_DIR", default="./tmp")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        output_file = os.path.join(output_dir, "example_results.json")
        try:
            with open(output_file, "w") as f:
                json.dump(results, f, indent=2, default=str)
            logger.info(f"Results saved to '{output_file}'")
        except IOError as e:
            logger.error(f"Failed to save results to '{output_file}': {e}")

    # Example 7: Error handling
    console.rule("Example 7: Error Handling")
    example_error_handling(debug)

    logger.info("Examples completed.")


if __name__ == "__main__":
    main()
