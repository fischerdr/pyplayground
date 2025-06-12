#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to import schedules and notification templates into AWX."""

import json
import logging

import typer
from awxcli import AWX

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = typer.Typer()


@app.command()
def import_schedules(
    awx_host: str = typer.Option(
        "https://awx.example.com",
        help="AWX host URL"
    ),
    awx_token: str = typer.Option(
        "YOUR_AWX_TOKEN",
        help="AWX API token"
    ),
    input_file: str = typer.Option(
        "schedules.json",
        help="Input JSON file path"
    )
) -> None:
    """Import schedules and notification templates into AWX.
    
    Args:
        awx_host: AWX host URL
        awx_token: AWX API token
        input_file: Input JSON file path
    """
    try:
        awx = AWX(host=awx_host, token=awx_token)
        
        with open(input_file) as f:
            data = json.load(f)
            
        for sch in data:
            awx.schedules.create(**sch)
            logger.info(f"Imported schedule {sch['name']}")
            
    except Exception as e:
        logger.error(f"Failed to import schedules: {str(e)}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app() 