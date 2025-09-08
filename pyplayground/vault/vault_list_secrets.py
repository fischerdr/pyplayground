#!/usr/bin/env python3
"""Vault KV Secrets Listing Tool.

This script provides functionality to list keys in a Vault KV store using hvac.
It includes proper logging and type hints as per project guidelines.
"""

import logging
import os

# import sys
from typing import Any, Dict, List, Optional

import hvac
import typer
from hvac.exceptions import InvalidRequest, VaultError
from pick import pick
from rich.console import Console

from pyplayground.utils.config_utils import load_dotenv
from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.vault_utils import create_vault_client

# Load environment variables
load_dotenv()

# Instantiate Rich Console
console = Console()

# Get logger
logger = get_logger(__name__)

# Instantiate Typer app
app = typer.Typer(help="Vault KV Secrets Management Tool")


def get_vault_client(
    vault_addr: Optional[str] = None,
    vault_token: Optional[str] = None,
    namespace: Optional[str] = None,
) -> hvac.Client:
    """CLI wrapper for create_vault_client with Typer-specific error handling.

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


def _read_secret_data(client: hvac.Client, path: str, mount_point: str) -> Optional[Dict[str, Any]]:
    """Helper function to read secret data.

    Args:
        client: Authenticated Vault client.
        path: The path within the KV store to read data from.
        mount_point: The mount point of the KV store.

    Returns:
        Optional[Dict[str, Any]]: Secret data if found, else None.
    """
    try:
        secret = client.secrets.kv.v2.read_secret(path=path, mount_point=mount_point)
        return secret.get("data", {}).get("data")
    except hvac.exceptions.InvalidPath:
        return None
    except Exception as e:
        logger.warning(f"Could not read secret data at {mount_point}/{path}: {e}")
        return None


def _list_secret_keys(client: hvac.Client, path: str, mount_point: str) -> List[str]:
    """Helper function to list secret keys.

    Args:
        client: Authenticated Vault client.
        path: The path within the KV store to list keys from.
        mount_point: The mount point of the KV store.

    Returns:
        List[str]: List of keys if found, else an empty list.
    """
    try:
        response = client.secrets.kv.v2.list_secrets(path=path, mount_point=mount_point)
        return response.get("data", {}).get("keys", [])
    except hvac.exceptions.InvalidPath:
        return []  # Path might be a leaf node with data only, or non-existent
    except Exception as e:
        logger.warning(f"Could not list keys at {mount_point}/{path}: {e}")
        return []


def _check_keys_for_data(
    client: hvac.Client, keys: List[str], current_path: str, mount_point: str
) -> List[str]:
    """Helper function to check which keys contain data.

    Args:
        client: Authenticated Vault client.
        keys: List of keys to check.
        current_path: The current base path of the keys.
        mount_point: The mount point of the KV store.

    Returns:
        List[str]: List of keys that contain data.
    """
    data_keys = []
    for key in keys:
        if not key.endswith("/"):  # Only check non-folder paths
            full_path = f"{current_path}/{key}".lstrip("/")
            if _read_secret_data(client, path=full_path, mount_point=mount_point) is not None:
                data_keys.append(key)
    return data_keys


def list_kv_secrets(
    client: hvac.Client, mount_point: str = "static_secrets", path: str = ""
) -> Dict[str, Any]:
    """List keys and identify data nodes in the specified KV store path.

    Args:
        client: Authenticated Vault client
        mount_point: The mount point of the KV store (default: static_secrets)
        path: The path within the KV store to list (default: root path)

    Returns:
        Dict[str, Any]: Dictionary containing:
            - keys: list of path keys
            - is_data: boolean indicating if current path contains data
            - data: dictionary of secret data if present
            - data_keys: list of keys under the current path that contain secret data
    """
    result = {"keys": [], "is_data": False, "data": None, "data_keys": []}

    try:
        # Try to list keys first
        listed_keys = _list_secret_keys(client, path=path, mount_point=mount_point)
        result["keys"] = listed_keys

        # Try to read data at the current path
        current_path_data = _read_secret_data(client, path=path, mount_point=mount_point)
        if current_path_data is not None:
            result["is_data"] = True
            result["data"] = current_path_data
            # If the current path itself has data, and it's not the root,
            # its name should be considered a data key in the parent's context.
            # This specific logic might need adjustment based on how `data_keys` is used by the caller.
            if path:  # and path.split("/")[-1] not in result["data_keys"]:
                # This part of data_keys was intended for *children* of the current path.
                # If the current path *is* a data node, that's handled by is_data and data fields.
                pass

        # If we have keys, check each one to see if it contains data
        if listed_keys:
            result["data_keys"] = _check_keys_for_data(client, listed_keys, path, mount_point)

        # Special case: if the path itself has data, and no subkeys were listed,
        # but the path itself is a key (e.g. /secret/mydata, not /secret/)
        # This might be redundant with the `is_data` check above.
        if result["is_data"] and not listed_keys and path:
            # if path.split("/")[-1] not in result["data_keys"]:
            # result["data_keys"].append(path.split("/")[-1])
            pass  # Covered by is_data and data fields for the current path.

        return result
    except Exception as e:
        logger.error(f"Error accessing secrets at {mount_point}/{path}: {str(e)}")
        return result  # Return partially filled result or default


def format_data(data: Dict[str, Any], indent: int = 0, mask_values: bool = True) -> str:
    """Format secret data for display.

    Args:
        data: Dictionary containing secret data
        indent: Number of spaces to indent
        mask_values: If True, mask sensitive string values with asterisks

    Returns:
        str: Formatted string representation of the data
    """
    result_lines = []
    spaces = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            result_lines.append(f"{spaces}{key}:")
            result_lines.append(format_data(value, indent + 2, mask_values))
        else:
            # Mask sensitive values if requested
            display_value = "********" if mask_values and isinstance(value, str) else str(value)
            result_lines.append(f"{spaces}{key}: {display_value}")
    return "\n".join(result_lines)


def _display_secrets_results(
    result: Dict[str, Any],
    path: str,
    mount_point: str,
    show_data: bool,
    mask_values: bool,
) -> None:
    """Helper function to display the results of list_kv_secrets.

    Args:
        result: The result dictionary from list_kv_secrets.
        path: The current path being displayed.
        mount_point: The KV store mount point.
        show_data: Whether to display secret data.
        mask_values: Whether to mask sensitive values.
    """
    if not result["keys"] and not result["is_data"]:
        console.print(f"\n📂 No secrets found at path: {path or '/'}")
        return

    if result["keys"]:
        console.print(f"\n📂 Contents of {path or '/'} in {mount_point}:")
        for key in result["keys"]:
            if key in result.get("data_keys", []):
                console.print(f"  📄 {key}")  # File emoji for data
            else:
                console.print(f"  📁 {key}")  # Folder emoji for directories

    if result["is_data"]:
        if show_data:
            console.print("\n📋 Secret Data:")
            formatted_data = format_data(result["data"], 2, mask_values)
            console.print(formatted_data)
            if not mask_values:
                console.print(
                    "\n⚠️  [yellow]Warning: Displaying unmasked sensitive values![/yellow]"
                )
        else:
            console.print("\n📋 Secret data is available (use --show-data to view)")


def _handle_interactive_mode(
    result: Dict[str, Any],
    current_path: str,
    mount_point: str,
    vault_addr: Optional[str],
    vault_token: Optional[str],
    namespace: Optional[str],
    show_data: bool,
    mask_values: bool,
    interactive: bool,  # Pass through for recursive calls
) -> None:
    """Helper function to handle interactive mode.

    Args:
        result: The result dictionary from list_kv_secrets.
        current_path: The current path being explored.
        mount_point: KV store mount point.
        vault_addr: Vault server address.
        vault_token: Vault token.
        namespace: Vault namespace.
        show_data: Whether to display secret data.
        mask_values: Whether to mask sensitive values.
        interactive: Whether interactive mode is enabled.
    """
    if not interactive or not result["keys"]:
        return

    title = "🔍 Select a key to explore (use arrow keys, press Enter to select, Ctrl+C to exit):"
    options = result["keys"] + ["Exit"]
    try:
        selected, _ = pick(options, title)

        if selected != "Exit":
            new_path = f"{current_path}/{selected}" if current_path else selected
            # Call the main list_keys command for the new path
            list_keys(
                mount_point=mount_point,
                path=new_path,
                vault_addr=vault_addr,
                vault_token=vault_token,
                namespace=namespace,
                show_data=show_data,
                mask_values=mask_values,
                interactive=interactive,  # Continue in interactive mode
            )
    except KeyboardInterrupt:
        console.print("\n👋 Exiting interactive mode")
        raise typer.Exit()
    except Exception as e:  # Catch other pick-related or unexpected errors
        logger.error(f"Error during interactive selection: {e}")
        raise typer.Exit(1)


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
        None,
        "--namespace",
        "-n",
        help="Vault namespace (or use VAULT_NAMESPACE env var)",
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
        kv_result: Dict[str, Any]
        try:
            kv_result = list_kv_secrets(client, mount_point, path)
        except (VaultError, InvalidRequest) as e:
            logger.error(f"Failed to list secrets: {str(e)}")
            raise typer.Exit(1)

        _display_secrets_results(
            result=kv_result,
            path=path,
            mount_point=mount_point,
            show_data=show_data,
            mask_values=mask_values,
        )

        _handle_interactive_mode(
            result=kv_result,
            current_path=path,
            mount_point=mount_point,
            vault_addr=vault_addr,
            vault_token=vault_token,
            namespace=namespace,
            show_data=show_data,
            mask_values=mask_values,
            interactive=interactive,
        )

    except (
        typer.Exit
    ):  # Re-raise Typer Exit exceptions to prevent them from being caught by the generic one
        raise
    except Exception as e:
        logger.error(f"Unexpected error in list_keys: {str(e)}")
        raise typer.Exit(1)


if __name__ == "__main__":
    # Setup Logging
    script_base_name = os.path.basename(__file__).replace(".py", "")
    # Determine log level from a potential global debug flag or default to INFO
    # For now, defaulting to INFO, assuming no global debug flag is easily accessible here
    # You might want to pass a debug flag to main and then to setup_logging
    setup_logging(level=logging.INFO, script_name=script_base_name)
    app()
