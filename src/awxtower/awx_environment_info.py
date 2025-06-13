#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""This module provides functionality to fetch and display AWX/Tower environment information."""

import json
import logging
import platform
import subprocess
from typing import Dict, Optional

import click
import urllib3
from awxkit import api

from utils.config_utils import load_env_file
from utils.logging_utils import setup_logging

# Disable SSL warnings - due to self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Logging Setup ---
logger = logging.getLogger(__name__)

# Load environment variables
load_env_file()


def get_system_info() -> Dict:
    """Get system information for migration planning.
    
    Returns:
        Dict containing system information
    """
    try:
        # Get OS information
        os_info = {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor()
        }
        
        # Get RHEL specific information if available
        if os_info["system"] == "Linux":
            try:
                rhel_version = subprocess.check_output(
                    ["cat", "/etc/redhat-release"], 
                    universal_newlines=True
                ).strip()
                os_info["rhel_version"] = rhel_version
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

        return os_info
    except Exception as e:
        logger.error(f"Failed to get system information: {str(e)}")
        return {}


def get_environment_info(tower_url: str, token: str, verify_ssl: bool = True) -> Dict:
    """Fetch environment information from AWX/Tower.

    Args:
        tower_url: The URL of the AWX/Tower instance
        token: The API token for authentication
        verify_ssl: Whether to verify SSL certificates

    Returns:
        Dict containing environment information
    """
    try:
        # Initialize AWX connection
        awx = api.Connection(
            tower_url,
            token=token,
            verify=verify_ssl
        )

        # Get base info
        base_info = awx.get()
        
        # Fetch various environment components
        info = {
            "system_info": get_system_info(),
            "version": base_info.version,
            "settings": base_info.settings,
            "me": base_info.me,
            "instances": base_info.instances,
            "config": base_info.config,
            "inventory_stats": {
                "inventories": len(awx.inventories.get().results),
                "hosts": len(awx.hosts.get().results)
            },
            "project_stats": {
                "projects": len(awx.projects.get().results)
            },
            "template_stats": {
                "job_templates": len(awx.job_templates.get().results),
                "workflow_job_templates": len(awx.workflow_job_templates.get().results)
            },
            "credential_stats": {
                "credentials": len(awx.credentials.get().results)
            },
            "database_info": {
                "type": base_info.settings.get("DATABASES", {}).get("default", {}).get("ENGINE", "unknown"),
                "name": base_info.settings.get("DATABASES", {}).get("default", {}).get("NAME", "unknown")
            },
            "authentication_info": {
                "auth_backends": base_info.settings.get("AUTHENTICATION_BACKENDS", []),
                "ldap_enabled": "django_auth_ldap.backend.LDAPBackend" in base_info.settings.get("AUTHENTICATION_BACKENDS", [])
            }
        }

        return info

    except Exception as e:
        logger.error(f"Failed to fetch environment information: {str(e)}")
        raise


@click.command()
@click.option(
    "--tower-url",
    envvar="TOWER_URL",
    required=True,
    help="AWX/Tower URL. Can also be set via TOWER_URL env var.",
)
@click.option(
    "--token",
    envvar="TOWER_TOKEN",
    required=True,
    help="API Token for authentication. Can also be set via TOWER_TOKEN env var.",
)
@click.option(
    "--output-file",
    type=click.Path(dir_okay=False, writable=True),
    help="File to save environment information (JSON format).",
)
@click.option(
    "--insecure",
    is_flag=True,
    default=False,
    help="Disable SSL certificate verification.",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable debug logging.",
)
def main(
    tower_url: str,
    token: str,
    output_file: Optional[str],
    insecure: bool,
    debug: bool,
) -> None:
    """Fetch and display AWX/Tower environment information."""
    # Setup logging
    setup_logging(debug)

    try:
        # Get environment information
        env_info = get_environment_info(tower_url, token, not insecure)

        # Output the information
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(env_info, f, indent=2)
            logger.info(f"Environment information saved to {output_file}")
        else:
            print(json.dumps(env_info, indent=2))

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        raise click.Abort()


if __name__ == "__main__":
    main() 