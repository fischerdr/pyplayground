#!/usr/bin/env python3
"""
Inventory Search Script

This script provides a command-line interface for searching inventory clusters
with flexible filtering options.
"""

import json
import logging
import os
import sys
from typing import List, Optional

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

# Add the parent directory to the path so we can import the utils module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils.inventory import search_inventory

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger("inventory_search")

# Load environment variables
load_dotenv()

# Create console for rich output
console = Console()


@click.command()
@click.option(
    "--base-url",
    required=True,
    envvar="INVENTORY_API_URL",
    help="Base URL for the inventory API",
)
@click.option(
    "--api-key",
    envvar="INVENTORY_API_KEY",
    help="API key for authentication",
)
@click.option(
    "--offset",
    type=int,
    default=0,
    help="Pagination offset",
)
@click.option(
    "--limit",
    type=int,
    default=100,
    help="Maximum number of results to return",
)
@click.option(
    "--env",
    help="Filter by environment (e.g., 'prod', 'dev', 'test')",
)
@click.option(
    "--install-type",
    help="Filter by installation type (e.g., 'upi')",
)
@click.option(
    "--network",
    help="Filter by network type (e.g., 'internet')",
)
@click.option(
    "--region",
    help="Filter by region (e.g., 'euswest1')",
)
@click.option(
    "--zone",
    help="Filter by zone (e.g., 'a', 'b', 'c')",
)
@click.option(
    "--tenancy",
    help="Filter by tenancy type (e.g., 'single-tenancy')",
)
@click.option(
    "--tier",
    help="Filter by tier",
)
@click.option(
    "--status",
    help="Filter by status (e.g., 'provisioned')",
)
@click.option(
    "--is-under-maintenance",
    is_flag=True,
    help="Filter by maintenance status",
)
@click.option(
    "--car-id",
    multiple=True,
    help="Filter by CAR ID (can be specified multiple times)",
)
@click.option(
    "--feature",
    multiple=True,
    help="Filter by feature (can be specified multiple times)",
)
@click.option(
    "--tag",
    multiple=True,
    help="Filter by tag (can be specified multiple times or as comma-separated list: --tag tag1,tag2,tag3)",
)
@click.option(
    "--workload",
    multiple=True,
    help="Filter by workload (can be specified multiple times)",
)
@click.option(
    "--timeout",
    type=int,
    default=30,
    help="Request timeout in seconds",
)
@click.option(
    "--output",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
@click.option(
    "--no-verify-ssl",
    is_flag=True,
    help="Disable SSL certificate verification",
)
@click.option(
    "--cert-path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
    help="Path to a custom SSL certificate file",
)
def cli(
    base_url: str,
    api_key: Optional[str],
    offset: int,
    limit: int,
    env: Optional[str],
    install_type: Optional[str],
    network: Optional[str],
    region: Optional[str],
    zone: Optional[str],
    tenancy: Optional[str],
    tier: Optional[str],
    status: Optional[str],
    is_under_maintenance: bool,
    car_id: List[str],
    feature: List[str],
    tag: List[str],
    workload: List[str],
    timeout: int,
    output: str,
    debug: bool,
    no_verify_ssl: bool,
    cert_path: Optional[str],
) -> None:
    """
    Search for inventory clusters with flexible filtering options.

    This command allows you to search for clusters in the inventory with
    various filter criteria. Results can be displayed as a table or JSON.

    Examples:
        # Search for production clusters
        inventory_search.py --base-url https://api.example.com --env prod

        # Search for clusters with specific features and tags
        inventory_search.py --base-url https://api.example.com --feature feature1 --feature feature2 --tag tag1

        # Get results in JSON format
        inventory_search.py --base-url https://api.example.com --output json

        # Handle self-signed certificates
        inventory_search.py --base-url https://api.example.com --no-verify-ssl
        inventory_search.py --base-url https://api.example.com --cert-path /path/to/certificate.pem
    """
    # Set debug logging if requested
    if debug:
        logger.setLevel(logging.DEBUG)
        # Also set the root logger to debug
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("urllib3").setLevel(logging.DEBUG)
        logging.getLogger("requests").setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    try:
        # Convert tier to appropriate type if provided
        converted_tier = None
        if tier is not None:
            try:
                # Try to convert to int or float
                if "." in tier:
                    converted_tier = float(tier)
                else:
                    converted_tier = int(tier)
            except ValueError:
                # If conversion fails, use as string
                converted_tier = tier

        # Process tags - support both multiple --tag options and comma-separated lists
        processed_tags = []
        if tag:
            for tag_item in tag:
                if "," in tag_item:
                    # Split comma-separated tags and add them individually
                    processed_tags.extend([t.strip() for t in tag_item.split(",")])
                else:
                    processed_tags.append(tag_item)

        # Log request details in debug mode
        if debug:
            logger.debug(f"Request URL: {base_url.rstrip('/')}/v1/inventory/clusters")
            logger.debug(f"SSL Verification: {'Disabled' if no_verify_ssl else 'Enabled'}")
            if cert_path:
                logger.debug(f"Using custom certificate: {cert_path}")

            # Log all parameters
            params_log = {
                "offset": offset,
                "limit": limit,
                "env": env,
                "install_type": install_type,
                "network": network,
                "region": region,
                "zone": zone,
                "tenancy": tenancy,
                "tier": converted_tier,
                "status": status,
                "is_under_maintenance": is_under_maintenance if is_under_maintenance else None,
                "car_ids": list(car_id) if car_id else None,
                "features": list(feature) if feature else None,
                "tags": processed_tags if processed_tags else None,
                "workloads": list(workload) if workload else None,
            }
            logger.debug(f"Request parameters: {json.dumps(params_log, default=str, indent=2)}")

        # Search for inventory
        logger.info("Searching inventory...")
        results = search_inventory(
            base_url=base_url,
            api_key=api_key,
            offset=offset,
            limit=limit,
            env=env,
            install_type=install_type,
            network=network,
            region=region,
            zone=zone,
            tenancy=tenancy,
            tier=converted_tier,
            status=status,
            is_under_maintenance=is_under_maintenance if is_under_maintenance else None,
            car_ids=list(car_id) if car_id else None,
            features=list(feature) if feature else None,
            tags=processed_tags if processed_tags else None,
            workloads=list(workload) if workload else None,
            timeout=timeout,
            verify_ssl=not no_verify_ssl,
            cert_path=cert_path,
            debug_request=debug,
        )

        # Display results based on output format
        if output == "json":
            console.print(json.dumps(results, indent=2))
        else:  # table
            display_results_as_table(results)

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        if debug:
            logger.exception("Detailed error information:")
        sys.exit(1)


def display_results_as_table(results: dict) -> None:
    """
    Display inventory search results as a rich table.

    Args:
        results: The inventory search results
    """
    # Check if we have clusters in the results
    clusters = results.get("clusters", [])
    if not clusters:
        console.print("[yellow]No clusters found matching the criteria[/yellow]")
        return

    # Create a table
    table = Table(title="Inventory Clusters")

    # Add columns based on the first cluster's keys
    if clusters:
        # Get all possible keys from all clusters
        all_keys = set()
        for cluster in clusters:
            all_keys.update(cluster.keys())

        # Add columns for common fields first, then others
        priority_fields = ["id", "name", "env", "region", "zone", "status"]
        for field in priority_fields:
            if field in all_keys:
                table.add_column(field.upper())
                all_keys.remove(field)

        # Add remaining fields
        for field in sorted(all_keys):
            table.add_column(field.upper())

        # Add rows
        for cluster in clusters:
            row = []
            # Add priority fields first
            for field in priority_fields:
                if field in table.columns:
                    value = cluster.get(field, "")
                    row.append(str(value) if value is not None else "")

            # Add remaining fields
            for field in sorted(all_keys):
                value = cluster.get(field, "")
                row.append(str(value) if value is not None else "")

            table.add_row(*row)

    # Print the table
    console.print(table)

    # Print summary
    total = results.get("total", 0)
    console.print(f"[green]Total clusters: {total}[/green]")


if __name__ == "__main__":
    cli()
