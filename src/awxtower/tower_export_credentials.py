#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to export Tower credentials to JSON."""

import json
import os
import sys
from pathlib import Path

import typer

from utils.ansible_tower_utils import get_awx_or_tower_client, list_resources
from utils.logging_utils import get_logger, setup_logging

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name=os.path.basename(__file__).replace(".py", ""))
logger = get_logger(__name__)


@app.command()
def export(
    output: Path = typer.Option(
        "credentials.json",
        help="Output JSON file path",
        exists=False,
        dir_okay=False,
        writable=True,
    )
) -> None:
    """Export Tower credentials to JSON."""
    try:
        # Get Tower client configuration
        client_config = get_awx_or_tower_client("TOWER")
        tower_url = client_config["url"]
        headers = client_config["headers"]
        verify = client_config["verify"]

        logger.info("Fetching credentials from Tower...")

        credentials = list_resources(tower_url, headers, "credentials", verify)

        if not credentials:
            logger.warning("No credentials found in Tower.")
            sys.exit(0)

        # Save to file
        with open(output, "w") as f:
            json.dump(credentials, f, indent=2)
        logger.info(f"Successfully exported {len(credentials)} credentials to {output}")

    except Exception as e:
        logger.error(f"Failed to export credentials: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
