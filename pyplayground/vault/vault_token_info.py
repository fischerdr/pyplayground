#!/usr/bin/env python3
"""Vault Token Information Script.

This script retrieves and displays information about a Vault token.
It provides detailed token metadata and capabilities.
"""

import sys
from datetime import datetime
from typing import Any, Dict, Optional

import click
import hvac
from rich.console import Console
from rich.table import Table

from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.vault_utils import create_vault_client

# Configure logging
setup_logging(level="INFO")

# Get module logger
logger = get_logger(__name__)
console = Console()


class VaultTokenInfo:
    """Class to handle Vault token information retrieval and display."""

    def __init__(self, vault_addr: str, token: str, verify_pem: Optional[str] = None):
        """Initialize VaultTokenInfo with Vault address and token.

        Args:
            vault_addr: The Vault server address
            token: The Vault token to inspect
            verify_pem: Path to PEM file for SSL verification
        """
        self.vault_addr = vault_addr
        self.token = token
        self.verify_pem = verify_pem
        self.client = self._create_client()

    def _create_client(self) -> hvac.Client:
        """Create and return an authenticated Vault client.

        Returns:
            hvac.Client: Authenticated Vault client

        Raises:
            hvac.exceptions.InvalidRequest: If token is invalid
            hvac.exceptions.VaultError: If connection fails
            FileNotFoundError: If verify_pem file doesn't exist
        """
        try:
            return create_vault_client(self.vault_addr, self.token, self.verify_pem)
        except Exception as e:
            logger.error(f"Failed to create Vault client: {str(e)}")
            raise

    def get_token_info(self) -> Dict[str, Any]:
        """Retrieve token information from Vault.

        Returns:
            Dict containing token metadata and capabilities

        Raises:
            hvac.exceptions.VaultError: If token lookup fails
        """
        try:
            token_info = self.client.auth.token.lookup_self()
            logger.info("Successfully retrieved token information")
            return token_info
        except Exception as e:
            logger.error(f"Failed to retrieve token information: {str(e)}")
            raise

    def display_token_info(self, token_info: Dict[str, Any]) -> None:
        """Display token information in a formatted table.

        Args:
            token_info: Dictionary containing token metadata
        """
        table = Table(title="Vault Token Information")
        table.add_column("Attribute", style="cyan")
        table.add_column("Value", style="green")

        # Add relevant token information to table
        important_fields = [
            "accessor",
            "creation_time",
            "creation_ttl",
            "display_name",
            "expire_time",
            "explicit_max_ttl",
            "id",
            "meta",
            "num_uses",
            "orphan",
            "path",
            "policies",
            "ttl",
        ]

        for field in important_fields:
            if field in token_info:
                value = str(token_info[field])
                if field == "creation_time":
                    # Convert Unix timestamp to readable format
                    try:
                        value = datetime.fromtimestamp(float(token_info[field])).strftime("%Y-%m-%d %H:%M:%S")
                    except (ValueError, TypeError):
                        pass
                table.add_row(field, value)

        console.print(table)


@click.command()
@click.option(
    "--vault-addr",
    required=True,
    help="Vault server address (e.g., http://localhost:8200)",
)
@click.option("--token", required=True, help="Vault token to inspect")
@click.option(
    "--verify-pem",
    required=False,
    help="Path to PEM file for SSL verification",
    type=click.Path(exists=True, dir_okay=False, path_type=str),
)
def main(vault_addr: str, token: str, verify_pem: Optional[str] = None) -> None:
    """Display information about a Vault token.

    This command connects to a Vault server and displays detailed information
    about the provided token, including its metadata and capabilities.
    """
    try:
        token_info = VaultTokenInfo(vault_addr, token, verify_pem)
        info = token_info.get_token_info()
        token_info.display_token_info(info)
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
