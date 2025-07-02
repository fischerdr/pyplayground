#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""This module provides functionality to fetch and display AWX/Tower environment information."""

import json
import logging
import platform
import subprocess
from typing import Dict, Optional

import click
import requests
import urllib3

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
            "processor": platform.processor(),
        }

        # Get RHEL specific information if available
        if os_info["system"] == "Linux":
            try:
                rhel_version = subprocess.check_output(
                    ["cat", "/etc/redhat-release"], universal_newlines=True
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
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}

        # Get base info
        base_url = f"{tower_url}/api/v2/"
        response = requests.get(base_url, headers=headers, verify=verify_ssl, timeout=30)
        response.raise_for_status()
        base_info = response.json()

        # Get version info
        version_url = f"{tower_url}/api/v2/config/"
        response = requests.get(version_url, headers=headers, verify=verify_ssl, timeout=30)
        response.raise_for_status()
        config_info = response.json()

        # Get user info
        me_url = f"{tower_url}/api/v2/me/"
        response = requests.get(me_url, headers=headers, verify=verify_ssl, timeout=30)
        response.raise_for_status()
        me_info = response.json()

        # Get inventory stats
        inventories_url = f"{tower_url}/api/v2/inventories/"
        response = requests.get(inventories_url, headers=headers, verify=verify_ssl, timeout=30)
        response.raise_for_status()
        inventories_data = response.json()

        # Get hosts stats
        hosts_url = f"{tower_url}/api/v2/hosts/"
        response = requests.get(hosts_url, headers=headers, verify=verify_ssl, timeout=30)
        response.raise_for_status()
        hosts_data = response.json()

        # Get project stats
        projects_url = f"{tower_url}/api/v2/projects/"
        response = requests.get(projects_url, headers=headers, verify=verify_ssl, timeout=30)
        response.raise_for_status()
        projects_data = response.json()

        # Get job template stats
        job_templates_url = f"{tower_url}/api/v2/job_templates/"
        response = requests.get(job_templates_url, headers=headers, verify=verify_ssl, timeout=30)
        response.raise_for_status()
        job_templates_data = response.json()

        # Get workflow job template stats
        workflow_job_templates_url = f"{tower_url}/api/v2/workflow_job_templates/"
        response = requests.get(
            workflow_job_templates_url, headers=headers, verify=verify_ssl, timeout=30
        )
        response.raise_for_status()
        workflow_job_templates_data = response.json()

        # Get credential stats
        credentials_url = f"{tower_url}/api/v2/credentials/"
        response = requests.get(credentials_url, headers=headers, verify=verify_ssl, timeout=30)
        response.raise_for_status()
        credentials_data = response.json()

        # Get settings
        settings_url = f"{tower_url}/api/v2/settings/"
        response = requests.get(settings_url, headers=headers, verify=verify_ssl, timeout=30)
        response.raise_for_status()
        settings_data = response.json()

        # Compile information
        info = {
            "system_info": get_system_info(),
            "version": config_info.get("version", "unknown"),
            "settings": settings_data,
            "me": me_info,
            "config": config_info,
            "inventory_stats": {
                "inventories": inventories_data.get("count", 0),
                "hosts": hosts_data.get("count", 0),
            },
            "project_stats": {"projects": projects_data.get("count", 0)},
            "template_stats": {
                "job_templates": job_templates_data.get("count", 0),
                "workflow_job_templates": workflow_job_templates_data.get("count", 0),
            },
            "credential_stats": {"credentials": credentials_data.get("count", 0)},
            "database_info": {
                "type": settings_data.get("DATABASES", {})
                .get("default", {})
                .get("ENGINE", "unknown"),
                "name": settings_data.get("DATABASES", {})
                .get("default", {})
                .get("NAME", "unknown"),
            },
            "authentication_info": {
                "auth_backends": settings_data.get("AUTHENTICATION_BACKENDS", []),
                "ldap_enabled": "django_auth_ldap.backend.LDAPBackend"
                in settings_data.get("AUTHENTICATION_BACKENDS", []),
            },
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
