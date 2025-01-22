#!/usr/bin/env python3
"""
Vault KV Secrets Listing Tool

This script provides functionality to list keys in a Vault KV store using hvac.
It includes proper logging and type hints as per project guidelines.
"""

import logging
import sys
from typing import Any, Dict, Optional

import hvac
import typer
from dotenv import load_dotenv
from hvac.exceptions import InvalidRequest, VaultError
from pick import pick

from utils.vault_utils import create_vault_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

app = typer.Typer(help="Vault KV Secrets Management Tool")


def get_vault_client(
    vault_addr: Optional[str] = None,
    vault_token: Optional[str] = None,
    namespace: Optional[str] = None,
) -> hvac.Client:
    """
    CLI wrapper for create_vault_client with Typer-specific error handling.

    Args:
        vault_addr: Optional Vault server address
        vault_token: Optional Vault token
        namespace: Optional Vault namespace

    Returns:
        hvac.Client: Authenticated Vault client

    Raises:
        typer.Exit: If authentication fails or required parameters are missing
    """
    try:
        return create_vault_client(
            url=vault_addr, token=vault_token, namespace=namespace, load_env=True
        )
    except (VaultError, InvalidRequest, ValueError) as e:
        logger.error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        logger.error(f"Error connecting to Vault: {str(e)}")
        raise typer.Exit(1)


def list_kv_secrets(
    client: hvac.Client, mount_point: str = "static_secrets", path: str = ""
) -> Dict[str, Any]:
    """
    List keys in the specified KV store path.

    Args:
        client: Authenticated Vault client
        mount_point: The mount point of the KV store (default: static_secrets)
        path: The path within the KV store to list (default: root path)

    Returns:
        Dict[str, Any]: Dictionary containing:
            - keys: list of path keys
            - is_data: boolean indicating if current path contains data
            - data: dictionary of secret data if present
            - data_keys: list of keys that contain secret data
    """
    result = {"keys": [], "is_data": False, "data": None, "data_keys": []}

    try:
        # Try to list keys first
        try:
            response = client.secrets.kv.v2.list_secrets(path=path, mount_point=mount_point)
            result["keys"] = response.get("data", {}).get("keys", [])
        except hvac.exceptions.InvalidPath:
            # Path might be a leaf node with data only
            pass

        # Try to read data at this path
        try:
            data = client.secrets.kv.v2.read_secret(path=path, mount_point=mount_point)
            result["is_data"] = True
            result["data"] = data["data"]["data"]
            # If we have both keys and data, mark this path as a data key
            if path:
                result["data_keys"].append(path.split("/")[-1])
        except hvac.exceptions.InvalidPath:
            pass

        # If we have keys, check each one to see if it contains data
        if result["keys"]:
            for key in result["keys"][:]:  # Create a copy to iterate over
                if not key.endswith("/"):  # Only check non-folder paths
                    try:
                        full_path = f"{path}/{key}".lstrip("/")
                        client.secrets.kv.v2.read_secret(path=full_path, mount_point=mount_point)
                        result["data_keys"].append(key)
                    except hvac.exceptions.InvalidPath:
                        pass

        return result
    except Exception as e:
        logger.error(f"Error accessing secrets: {str(e)}")
        return result


def format_data(data: Dict[str, Any], indent: int = 0, mask_values: bool = True) -> str:
    """
    Format secret data for display.

    Args:
        data: Dictionary containing secret data
        indent: Number of spaces to indent
        mask_values: If True, mask sensitive string values with asterisks

    Returns:
        str: Formatted string representation of the data
    """
    result = []
    spaces = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            result.append(f"{spaces}{key}:")
            result.append(format_data(value, indent + 2, mask_values))
        else:
            # Mask sensitive values if requested
            display_value = "********" if mask_values and isinstance(value, str) else str(value)
            result.append(f"{spaces}{key}: {display_value}")
    return "\n".join(result)


@app.command()
def list_keys(
    mount_point: str = typer.Option(
        "static_secrets", "--mount-point", "-m", help="KV store mount point"
    ),
    path: str = typer.Option("", "--path", "-p", help="Path within the KV store"),
    vault_addr: Optional[str] = typer.Option(
        None, "--vault-addr", help="Vault server address (or use VAULT_ADDR env var)"
    ),
    vault_token: Optional[str] = typer.Option(
        None, "--vault-token", help="Vault token (or use VAULT_TOKEN env var)"
    ),
    namespace: Optional[str] = typer.Option(
        None, "--namespace", "-n", help="Vault namespace (or use VAULT_NAMESPACE env var)"
    ),
    show_data: bool = typer.Option(
        True, "--show-data/--no-data", help="Show secret data when available"
    ),
    mask_values: bool = typer.Option(
        True, "--mask/--no-mask", help="Mask sensitive values in output"
    ),
    interactive: bool = typer.Option(
        True, "--interactive/--no-interactive", help="Enable/disable interactive mode"
    ),
) -> None:
    """List keys and optionally show data in a Vault KV store path."""
    try:
        # Get vault client with proper error handling
        client = get_vault_client(vault_addr, vault_token, namespace)
        logger.info(f"Accessing secrets at {mount_point}/{path}")

        # Get secrets with error handling
        try:
            result = list_kv_secrets(client, mount_point, path)
        except (VaultError, InvalidRequest) as e:
            logger.error(f"Failed to list secrets: {str(e)}")
            raise typer.Exit(1)

        if not result["keys"] and not result["is_data"]:
            typer.echo(f"\n📂 No secrets found at path: {path or '/'}")
            return

        # Display results
        if result["keys"]:
            typer.echo(f"\n📂 Contents of {path or '/'} in {mount_point}:")
            for key in result["keys"]:
                if key in result["data_keys"]:
                    typer.echo(f"  📄 {key}")  # File emoji for data
                else:
                    typer.echo(f"  📁 {key}")  # Folder emoji for directories

        if result["is_data"]:
            if show_data:
                typer.echo("\n📋 Secret Data:")
                formatted_data = format_data(result["data"], 2, mask_values)
                typer.echo(formatted_data)
                if not mask_values:
                    typer.secho("\n⚠️  Warning: Displaying unmasked sensitive values!", fg="yellow")
            else:
                typer.echo("\n📋 Secret data is available (use --show-data to view)")

        # Interactive mode
        if interactive and result["keys"]:
            title = (
                "🔍 Select a key to explore (use arrow keys, press Enter to select, Ctrl+C to exit):"
            )
            options = result["keys"] + ["Exit"]
            try:
                selected, _ = pick(options, title)

                if selected != "Exit":
                    new_path = f"{path}/{selected}" if path else selected
                    list_keys(
                        mount_point=mount_point,
                        path=new_path,
                        vault_addr=vault_addr,
                        vault_token=vault_token,
                        namespace=namespace,
                        show_data=show_data,
                        mask_values=mask_values,
                        interactive=interactive,
                    )
            except KeyboardInterrupt:
                typer.echo("\n👋 Exiting interactive mode")
                raise typer.Exit()

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
