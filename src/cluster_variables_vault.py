"""Cluster variables and Vault configuration utility.

This module handles cluster name validation, parsing, and Vault configuration
for Kubernetes clusters. It retrieves cluster information from inventory
and configures Vault access based on cluster environment.
"""

import os
import re
from typing import Any, Dict, Optional, Tuple

import click
import requests

from utils.logging_utils import get_logger, setup_logging

# Set up logging
logger = get_logger(__name__)
setup_logging()


class ClusterConfig:
    """Configuration class for cluster variables and Vault settings."""

    def __init__(
        self,
        cluster_name: Optional[str] = None,
        inventory_url: Optional[str] = None,
        validate_certs: bool = True,
        ca_cert_path: Optional[str] = None,
    ) -> None:
        """Initialize cluster configuration with environment variables.

        Args:
            cluster_name: Optional[str] = None
            inventory_url: Optional[str] = None
            validate_certs: bool = True
            ca_cert_path: Optional[str] = None
        """
        # Cluster variables
        self.cluster_name: Optional[str] = cluster_name or os.getenv("CLUSTER_NAME")
        self.inventory_url: Optional[str] = inventory_url or os.getenv(
            "INVENTORY_URL", "https://inventory.example.com"
        )
        self.validate_certs: bool = (
            validate_certs or os.getenv("VALIDATE_CERTS", "true").lower() == "false"
        )
        self.ca_cert_path: Optional[str] = ca_cert_path or os.getenv("CA_CERT_PATH", "")

        # Vault defaults
        self.vault_automation_prod_address: Optional[str] = os.getenv(
            "VAULT_AUTOMATION_PROD_ADDRESS", "https://vaultprod.example.com"
        )
        self.vault_automation_eng_address: Optional[str] = os.getenv(
            "VAULT_AUTOMATION_ENG_ADDRESS", "https://vaulteng.example.com"
        )
        self.vault_automation_stage_address: Optional[str] = os.getenv(
            "VAULT_AUTOMATION_STAGE_ADDRESS", "https://vaultstage.example.com"
        )
        self.vault_automation_dev_address: Optional[str] = os.getenv(
            "VAULT_AUTOMATION_DEV_ADDRESS", "https://vaultdev.example.com"
        )
        self.vault_automation_default_namespace: Optional[str] = os.getenv(
            "VAULT_AUTOMATION_DEFAULT_NAMESPACE", "automation"
        )
        self.vault_automation_config_mount_point: Optional[str] = os.getenv(
            "VAULT_AUTOMATION_CONFIG_MOUNT_POINT", "kv"
        )
        # Parsed cluster components (will be set after parsing)
        self.cluster_user: Optional[str] = None
        self.platform: Optional[str] = None
        self.cluster_env: Optional[str] = None
        self.region: Optional[str] = None
        self.zone: Optional[str] = None
        self.cluster_id: Optional[str] = None


def validate_cluster_name(cluster_name: Optional[str]) -> None:
    """Validate cluster name format.

    Args:
        cluster_name: The cluster name to validate

    Raises:
        ValueError: If cluster name is invalid or doesn't match expected format
    """
    if cluster_name is None:
        raise ValueError("Cluster name is not defined")

    if not isinstance(cluster_name, str):
        raise ValueError("Cluster name must be a string")

    if not cluster_name.strip():
        raise ValueError("Cluster name cannot be empty")

    pattern = r"^[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-zA-Z0-9]+[abc]-[0-9]+$"
    if not re.match(pattern, cluster_name):
        raise ValueError(
            "Invalid cluster name format. Expected format: <cluster_user>-<platform>-<env>-<region><zone>-<id>"
        )
    logger.info("Valid cluster name format")


def parse_cluster_name(cluster_name: str) -> Tuple[str, str, str, str, str, str]:
    """Parse cluster name into its component parts.

    Args:
        cluster_name: The cluster name to parse

    Returns:
        Tuple containing cluster user, platform, environment, region, zone, and cluster ID
    """
    parts = cluster_name.split("-")
    cluster_user = parts[0]
    platform = parts[1]
    cluster_env = parts[2].replace("p", "prod").replace("d", "dev").replace("t", "test")
    region_zone = parts[3]
    region = region_zone[:-1]
    zone = region_zone[-1:].replace("a", "zone-a").replace("b", "zone-b").replace("c", "zone-c")
    cluster_id = parts[4]

    logger.info(f"Cluster User: {cluster_user}")
    logger.info(f"Platform: {platform}")
    logger.info(f"Environment: {cluster_env}")
    logger.info(f"Region: {region}")
    logger.info(f"Zone: {zone}")
    logger.info(f"Cluster ID: {cluster_id}")

    return cluster_user, platform, cluster_env, region, zone, cluster_id


def get_inventory(config: ClusterConfig) -> Dict[str, Any]:
    """Retrieve inventory data for a cluster.

    Args:
        config: ClusterConfig object containing all necessary configuration

    Returns:
        Dictionary containing inventory data

    Raises:
        requests.exceptions.RequestException: If API request fails
    """
    if not config.inventory_url:
        raise ValueError("Inventory URL is not defined")
    if not config.cluster_name:
        raise ValueError("Cluster name is not defined")

    url = f"{config.inventory_url}/{config.cluster_name}"
    headers = {"Accept": "application/json"}
    response = requests.get(
        url, headers=headers, verify=config.validate_certs, cert=config.ca_cert_path
    )
    response.raise_for_status()
    return response.json()


def set_vault_info_from_inventory(response: Dict[str, Any]) -> Optional[Tuple[str, str, str, str]]:
    """Extract Vault information from inventory response.

    Args:
        response: Inventory API response data

    Returns:
        Tuple containing vault address, namespace, mount point, and default path,
        or None if vault information is not found
    """
    vault_info = (
        response.get("kubernetes_platform", {})
        .get("secrets_management", {})
        .get("platform_vault", [{}])[0]
    )
    if vault_info:
        vault_address = vault_info.get("address")
        vault_namespace = vault_info.get("namespace")
        vault_default_path_full = vault_info.get("secrets_paths")
        vault_mount_point = vault_default_path_full.split("/")[0]
        vault_default_path = "/".join(vault_default_path_full.split("/")[1:])

        logger.info(f"Vault Address: {vault_address}")
        logger.info(f"Vault Namespace: {vault_namespace}")
        logger.info(f"Vault Default Path (Full): {vault_default_path_full}")
        logger.info(f"Vault Default Path (Clean): {vault_default_path}")
        logger.info(f"Vault Mount Point: {vault_mount_point}")
        return vault_address, vault_namespace, vault_mount_point, vault_default_path
    else:
        return None


def set_vault_info_from_defaults(config: ClusterConfig) -> Tuple[str, str, str, str]:
    """Set Vault information based on default values when inventory data is unavailable.

    Args:
        config: ClusterConfig object containing all necessary configuration

    Returns:
        Tuple containing vault address, namespace, mount point, and default path

    Raises:
        ValueError: If required default values are missing
    """
    if config.cluster_env == "prod":
        vault_address = config.vault_automation_prod_address
    elif config.cluster_user == "eng":
        vault_address = config.vault_automation_eng_address
    elif config.cluster_env == "stage":
        vault_address = config.vault_automation_stage_address
    else:
        vault_address = config.vault_automation_dev_address

    if not vault_address:
        raise ValueError(f"No vault address available for environment: {config.cluster_env}")

    vault_namespace = config.vault_automation_default_namespace
    vault_mount_point = config.vault_automation_config_mount_point
    vault_default_path = f"{config.cluster_user}/{config.cluster_name}"

    if not vault_namespace:
        raise ValueError("Default vault namespace is not defined")
    if not vault_mount_point:
        raise ValueError("Default vault mount point is not defined")

    logger.info(f"Vault Address: {vault_address}")
    logger.info(f"Vault Namespace: {vault_namespace}")
    logger.info(f"Vault Default Path (Clean): {vault_default_path}")
    logger.info(f"Vault Mount Point: {vault_mount_point}")

    return vault_address, vault_namespace, vault_mount_point, vault_default_path


def process_cluster_variables(cluster_name: Optional[str] = None) -> None:
    """Process cluster variables and set up Vault configuration.

    Args:
        cluster_name: Optional cluster name to override environment variable

    Raises:
        ValueError: If cluster name is invalid or required configuration is missing
    """
    config = ClusterConfig(cluster_name)

    try:
        validate_cluster_name(config.cluster_name)
        if not config.cluster_name:
            raise ValueError("Cluster name is not defined")

        # Parse cluster name and update config with the components
        (
            config.cluster_user,
            config.platform,
            config.cluster_env,
            config.region,
            config.zone,
            config.cluster_id,
        ) = parse_cluster_name(config.cluster_name)

        try:
            logger.info("Fetching inventory data...")
            inventory_response = get_inventory(config)
            vault_info = set_vault_info_from_inventory(inventory_response)
            if not vault_info:
                raise ValueError("No platform_vault information found in inventory")
        except Exception as e:
            logger.warning(f"{e} - Falling back to defaults")
            vault_info = set_vault_info_from_defaults(config)

        # Return the vault info for potential use by the caller
        return vault_info

    except Exception as e:
        logger.error(f"Failed to setup cluster variables: {e}")
        raise


@click.command()
@click.option(
    "--cluster-name",
    "-c",
    help="Cluster name in format <cluster_user>-<platform>-<env>-<region><zone>-<id>",
    envvar="CLUSTER_NAME",
)
@click.option(
    "--inventory-url",
    "-i",
    help="URL for inventory API",
    envvar="INVENTORY_URL",
)
@click.option(
    "--validate-certs",
    "-v",
    type=bool,
    default=True,
    help="Whether to validate SSL certificates",
    envvar="VALIDATE_CERTS",
)
@click.option(
    "--ca-cert-path",
    "-a",
    help="Path to CA certificate for SSL validation",
    envvar="CA_CERT_PATH",
)
def main(cluster_name: Optional[str] = None) -> None:
    """Process cluster variables and set up Vault configuration.

    This utility validates a cluster name, parses it into components, and configures
    Vault access information based on inventory data or default settings.

    The cluster name can be provided as a command-line argument or via the CLUSTER_NAME
    environment variable.
    """
    try:
        process_cluster_variables(cluster_name)
        logger.info("Successfully processed cluster variables")
    except Exception as e:
        logger.error(f"Error: {e}")
        raise click.ClickException(str(e))


if __name__ == "__main__":
    main()
