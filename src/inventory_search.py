#!/usr/bin/env python
"""
Inventory Search Script.

This script provides a command-line interface for searching inventory clusters
with flexible filtering options.
"""

import json
import logging
import os
import sys
from typing import Any, List, Optional

import certifi
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
    type=click.Choice(["table", "json", "text", "csv"]),
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
    help="Disable SSL certificate verification. Use only in trusted environments.",
)
@click.option(
    "--cert-path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
    envvar="INVENTORY_CERT_PATH",
    help="Path to a custom SSL certificate file or CA bundle for verification.",
)
@click.option(
    "--use-certifi",
    is_flag=True,
    default=True,
    help="Use certifi's default CA bundle for SSL verification (default: True).",
)
@click.option(
    "--show-ca-bundle-path",
    is_flag=True,
    help="Display the path to the CA bundle being used and exit.",
)
@click.option(
    "--fields",
    envvar="INVENTORY_DISPLAY_FIELDS",
    help="Additional fields to display (comma-separated). Use '*' for all fields.",
)
@click.option(
    "--display-fields-only",
    envvar="INVENTORY_DISPLAY_FIELDS_ONLY",
    help="Only display these fields (comma-separated). Overrides --fields and default fields.",
)
@click.option(
    "--display-fields-config",
    envvar="INVENTORY_DISPLAY_FIELDS_CONFIG",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
    help="Path to a JSON file containing field display configuration.",
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
    use_certifi: bool,
    show_ca_bundle_path: bool,
    fields: Optional[str],
    display_fields_only: Optional[str],
    display_fields_config: Optional[str],
) -> None:
    """
    Search for inventory clusters with flexible filtering options.

    This command allows you to search for clusters in the inventory with
    various filter criteria. Results can be displayed as a table, JSON, text, or CSV.

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

    # Handle CA bundle configuration
    if show_ca_bundle_path:
        ca_bundle_path = os.environ.get("REQUESTS_CA_BUNDLE") or certifi.where()
        console.print(f"[bold]Current CA bundle path:[/bold] {ca_bundle_path}")
        if os.path.exists(ca_bundle_path):
            console.print("[green]✓ CA bundle file exists[/green]")
            try:
                with open(ca_bundle_path, "r", encoding="utf-8") as f:
                    cert_count = f.read().count("-----BEGIN CERTIFICATE-----")
                console.print(f"[green]✓ CA bundle contains {cert_count} certificates[/green]")
            except Exception as e:
                console.print(f"[red]Error reading CA bundle: {e}[/red]")
        else:
            console.print("[red]✗ CA bundle file does not exist[/red]")
        return

    # Configure SSL verification
    if no_verify_ssl:
        verify_ssl = False
        logger.warning(
            "SSL certificate verification is disabled. This is not recommended for production use."
        )
    elif cert_path:
        verify_ssl = True
        logger.debug(f"Using custom certificate path: {cert_path}")
    elif use_certifi:
        # Use certifi's CA bundle
        cert_path = certifi.where()
        verify_ssl = True
        logger.debug(f"Using certifi's CA bundle: {cert_path}")
        # Set environment variable for requests
        os.environ["REQUESTS_CA_BUNDLE"] = cert_path
    else:
        verify_ssl = True
        logger.debug("Using system default CA certificates")

    # Check for REQUESTS_CA_BUNDLE environment variable
    if os.environ.get("REQUESTS_CA_BUNDLE") and not cert_path and not no_verify_ssl:
        cert_path = os.environ.get("REQUESTS_CA_BUNDLE")
        logger.debug(f"Using REQUESTS_CA_BUNDLE environment variable: {cert_path}")

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

        # Load field configuration if specified
        fields_config = load_fields_configuration(
            display_fields_only, fields, display_fields_config
        )

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
            verify_ssl=verify_ssl,
            cert_path=cert_path,
            debug_request=debug,
        )

        # Display results based on output format
        if output == "json":
            console.print(json.dumps(results, indent=2))
        elif output == "csv":
            display_results_as_csv(results, fields_config)
        elif output == "text":
            display_results_as_text(results, fields_config)
        else:  # table
            display_results_as_table(results, fields_config)

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        if debug:
            logger.exception("Detailed error information:")
        sys.exit(1)


def load_fields_configuration(
    display_fields_only: Optional[str], extra_fields: Optional[str], config_file: Optional[str]
) -> dict:
    """
    Load and process field display configuration from various sources.

    Priority order:
    1. --display-fields-only parameter or INVENTORY_DISPLAY_FIELDS_ONLY env var
    2. --display-fields-config parameter or INVENTORY_DISPLAY_FIELDS_CONFIG env var
    3. --fields parameter or INVENTORY_DISPLAY_FIELDS env var
    4. Default priority fields

    Args:
        display_fields_only: Comma-separated list of fields to display exclusively
        extra_fields: Comma-separated list of additional fields to display
        config_file: Path to a JSON configuration file

    Returns:
        Dictionary with field configuration
    """
    # Default configuration
    config = {
        "mode": "priority",  # Can be "priority", "only", or "custom"
        "fields": None,  # List of fields for "only" mode
        "extra_fields": None,  # List of extra fields for "priority" mode
    }

    # Check for display_fields_only (highest priority)
    if display_fields_only:
        config["mode"] = "only"
        config["fields"] = [field.strip() for field in display_fields_only.split(",")]
        return config

    # Check for config file
    if config_file:
        try:
            with open(config_file, "r") as f:
                file_config = json.load(f)

            # Validate and use file configuration
            if isinstance(file_config, dict):
                if "mode" in file_config and file_config["mode"] in ["priority", "only", "custom"]:
                    config["mode"] = file_config["mode"]

                if "fields" in file_config and isinstance(file_config["fields"], list):
                    config["fields"] = file_config["fields"]

                if "extra_fields" in file_config and isinstance(file_config["extra_fields"], list):
                    config["extra_fields"] = file_config["extra_fields"]

                # If mode is "custom" but no fields defined, fall back to priority
                if config["mode"] == "custom" and not config["fields"]:
                    config["mode"] = "priority"

                return config
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Error loading field configuration file: {str(e)}")
            # Continue with other options

    # Check for extra_fields
    if extra_fields:
        config["mode"] = "priority"
        if extra_fields.strip() == "*":
            config["extra_fields"] = "*"
        else:
            config["extra_fields"] = [field.strip() for field in extra_fields.split(",")]

    return config


def get_display_fields(clusters: list, fields_config: dict) -> tuple:
    """
    Determine which fields to display based on configuration.

    Args:
        clusters: The list of clusters from the results
        fields_config: Field configuration dictionary

    Returns:
        Tuple of (display_fields, priority_mode)
    """
    # Default priority fields
    priority_fields = [
        "name",
        "environment",
        "region",
        "zone",
        "status",
        "network",
        "tenant_name",
        "install_type",
        "is_under_maintenance",
    ]

    # Define fields that should be skipped (complex nested objects)
    skip_fields = ["infrastructures", "kubernetes_platform"]

    # Handle different modes
    mode = fields_config.get("mode", "priority")

    if mode == "only" and fields_config.get("fields"):
        # Only show specified fields
        return fields_config["fields"], False

    if mode == "custom" and fields_config.get("fields"):
        # Custom field order
        return fields_config["fields"], False

    # Default to priority mode
    display_fields = []

    # Add priority fields first
    for field in priority_fields:
        if clusters and field in clusters[0]:
            display_fields.append(field)

    # Add extra fields
    extra_fields = fields_config.get("extra_fields")
    if extra_fields:
        if extra_fields == "*":
            # Include all fields except complex objects
            if clusters:
                for field in clusters[0].keys():
                    if (
                        field not in display_fields
                        and field not in skip_fields
                        and not isinstance(clusters[0].get(field), (dict, list))
                        and "_timestamp" not in field
                    ):
                        display_fields.append(field)
        else:
            # Include only the specified extra fields
            for field in extra_fields:
                if field not in display_fields:
                    display_fields.append(field)

    return display_fields, True


def display_results_as_table(results: dict, fields_config: Optional[dict] = None) -> None:
    """
    Display inventory search results as a rich table.

    Args:
        results: The inventory search results
        fields_config: Configuration for which fields to display
    """
    # Check if we have results in the response
    clusters = results.get("results", [])
    if not clusters:
        console.print("[yellow]No clusters found matching the criteria[/yellow]")
        return

    # Create a table
    table = Table(title="Inventory Clusters")

    # Get fields to display
    if fields_config is None:
        fields_config = {}

    display_fields, priority_mode = get_display_fields(clusters, fields_config)

    # Track which columns we've added to the table
    added_columns = []

    # Add columns for all display fields
    for field in display_fields:
        column_name = field.upper()
        table.add_column(column_name)
        added_columns.append(field)

    # Add rows
    for cluster in clusters:
        row = []

        # Process each column in the order they were added
        for field in added_columns:
            if "." in field:
                # This is a nested field
                value = extract_nested_field(cluster, field)
            else:
                value = cluster.get(field)

            # Format the value based on its type
            if value is None:
                row.append("")
            elif isinstance(value, bool):
                row.append("Yes" if value else "No")
            elif isinstance(value, list):
                row.append(", ".join(str(item) for item in value))
            else:
                row.append(str(value))

        table.add_row(*row)

    # Print the table
    console.print(table)

    # Print summary
    total = results.get("size", 0)
    console.print(f"[green]Total clusters: {total}[/green]")


def display_results_as_csv(results: dict, fields_config: Optional[dict] = None) -> None:
    """
    Display inventory search results as CSV.

    Args:
        results: The inventory search results
        fields_config: Configuration for which fields to display
    """
    import csv
    import io

    # Check if we have results in the response
    clusters = results.get("results", [])
    if not clusters:
        console.print("[yellow]No clusters found matching the criteria[/yellow]")
        return

    # Get fields to display
    if fields_config is None:
        fields_config = {}

    display_fields, priority_mode = get_display_fields(clusters, fields_config)

    # Create CSV output
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow([field.upper() for field in display_fields])

    # Write data rows
    for cluster in clusters:
        row = []
        for field in display_fields:
            if "." in field:
                # This is a nested field
                value = extract_nested_field(cluster, field)
            else:
                value = cluster.get(field)

            # Format the value based on its type
            if value is None:
                row.append("")
            elif isinstance(value, bool):
                row.append("Yes" if value else "No")
            elif isinstance(value, list):
                row.append(", ".join(str(item) for item in value))
            else:
                row.append(str(value))

        writer.writerow(row)

    # Print the CSV
    console.print(output.getvalue())

    # Print summary
    total = results.get("size", 0)
    console.print(f"[green]Total clusters: {total}[/green]")


def display_results_as_text(results: dict, fields_config: Optional[dict] = None) -> None:
    """
    Display inventory search results as plain text.

    Args:
        results: The inventory search results
        fields_config: Configuration for which fields to display
    """
    # Check if we have results in the response
    clusters = results.get("results", [])
    if not clusters:
        console.print("[yellow]No clusters found matching the criteria[/yellow]")
        return

    # Get fields to display
    if fields_config is None:
        fields_config = {}

    display_fields, priority_mode = get_display_fields(clusters, fields_config)

    # Print each cluster as a text block
    for i, cluster in enumerate(clusters):
        console.print(f"\n[bold]Cluster {i + 1}:[/bold]")

        for field in display_fields:
            if "." in field:
                # This is a nested field
                value = extract_nested_field(cluster, field)
            else:
                value = cluster.get(field)

            # Format the value based on its type
            if value is None:
                formatted_value = ""
            elif isinstance(value, bool):
                formatted_value = "Yes" if value else "No"
            elif isinstance(value, list):
                formatted_value = ", ".join(str(item) for item in value)
            else:
                formatted_value = str(value)

            console.print(f"  [bold]{field.upper()}:[/bold] {formatted_value}")

    # Print summary
    total = results.get("size", 0)
    console.print(f"\n[green]Total clusters: {total}[/green]")


def extract_nested_field(data: dict, field_path: str) -> Any:
    """
    Extract a nested field from a dictionary using dot notation.

    Args:
        data: The dictionary to extract from
        field_path: The path to the field in dot notation (e.g., "kubernetes_platform.version")

    Returns:
        The value of the nested field, or None if not found
    """
    if not data or not field_path:
        return None

    parts = field_path.split(".")
    current = data

    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None

    return current


def process_extra_fields(clusters: list, extra_fields: Optional[str] = None) -> list:
    """
    Process extra fields specification and return a list of fields to display.

    Args:
        clusters: The list of clusters from the results
        extra_fields: Comma-separated list of additional fields to display

    Returns:
        List of additional fields to display
    """
    # Define priority fields that should be displayed first
    priority_fields = [
        "name",
        "environment",
        "region",
        "zone",
        "status",
        "network",
        "tenant_name",
        "install_type",
        "is_under_maintenance",
    ]

    # Define fields that should be skipped (complex nested objects)
    skip_fields = ["infrastructures", "kubernetes_platform"]

    additional_fields = []
    if extra_fields:
        if extra_fields.strip() == "*":
            # Include all fields except complex objects
            if clusters:
                additional_fields = [
                    field
                    for field in clusters[0].keys()
                    if field not in priority_fields
                    and field not in skip_fields
                    and not isinstance(clusters[0].get(field), (dict, list))
                    and "_timestamp" not in field
                ]
        else:
            # Include only the specified extra fields
            for field in extra_fields.split(","):
                field = field.strip()
                if "." in field:
                    # This is a nested field
                    additional_fields.append(field)
                elif field not in priority_fields:
                    additional_fields.append(field)

    return additional_fields


if __name__ == "__main__":
    cli()
