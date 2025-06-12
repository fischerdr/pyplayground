#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script to export Tower schedules and notifications to JSON."""

import json
import logging

import typer
from awxcli import Tower

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = typer.Typer()


@app.command()
def export(
    tower_host: str = typer.Option(
        "https://tower.example.com",
        help="Tower host URL"
    ),
    tower_token: str = typer.Option(
        "YOUR_TOWER_TOKEN",
        help="Tower API token"
    ),
    output: str = typer.Option(
        "schedules.json",
        help="Output JSON file path"
    )
) -> None:
    """Export Tower schedules and notifications to JSON.
    
    Args:
        tower_host: Tower host URL
        tower_token: Tower API token
        output: Output JSON file path
    """
    try:
        tower = Tower(host=tower_host, token=tower_token)
        sch = tower.schedules.list()
        
        with open(output, "w") as f:
            json.dump(sch, f, indent=2)
            
        logger.info(f"Exported {len(sch)} schedules to {output}")
    except Exception as e:
        logger.error(f"Failed to export schedules: {str(e)}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app() 