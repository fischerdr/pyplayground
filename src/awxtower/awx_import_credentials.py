#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to import credentials JSON into AWX."""

import json
import os
import sys
from pathlib import Path

import typer

from utils.ansible_tower_utils import get_awx_or_tower_client
from utils.logging_utils import get_logger, setup_logging

# Initialize Typer app
app = typer.Typer()

# Setup logging
setup_logging(script_name=os.path.basename(__file__).replace(".py", ""))
logger = get_logger(__name__)


@app.command()
def import_creds(
    input_file: Path = typer.Option(
        "credentials.json",
        help="Input JSON file path",
        exists=True,
        dir_okay=False,
        readable=True,
    )
) -> None:
    """Import credentials from JSON into AWX."""
    try:
        awx = get_awx_or_tower_client("AWX")

        with open(input_file, "r") as f:
            creds_data = json.load(f)

        logger.info(f"Importing {len(creds_data)} credentials into AWX...")
        for cred_data in creds_data:
            cred_name = cred_data.get("name")
            try:
                # To prevent duplicates, check if a credential with the same name exists
                if not awx.credentials.find(name=cred_name):
                    awx.credentials.create(payload=cred_data)
                    logger.info(f"Successfully imported credential: {cred_name}")
                else:
                    logger.warning(f"Credential '{cred_name}' already exists. Skipping.")
            except Exception as e:
                logger.error(f"Failed to import credential {cred_name}: {e}", exc_info=True)
                continue

        logger.info("Credential import completed.")

    except Exception as e:
        logger.error(f"Failed to import credentials: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
