"""Vault utility functions."""

import logging
import os
from typing import Any, Dict, List, Optional

import hvac
from dotenv import load_dotenv
from hvac.exceptions import InvalidRequest, VaultError

logger = logging.getLogger(__name__)


def create_vault_client(
    url: Optional[str] = None,
    token: Optional[str] = None,
    namespace: Optional[str] = None,
    verify: Optional[str] = None,
    load_env: bool = True,
) -> hvac.Client:
    """
    Create and authenticate a Vault client.

    Args:
        url: Vault server URL (defaults to VAULT_ADDR env var)
        token: Vault token (defaults to VAULT_TOKEN env var)
        namespace: Vault namespace (defaults to VAULT_NAMESPACE env var)
        verify: Path to SSL certificate (PEM) file for verification
        load_env: Whether to load environment from .env file

    Returns:
        hvac.Client: Authenticated Vault client

    Raises:
        VaultError: If connection or authentication fails
        ValueError: If required parameters are missing
    """
    if load_env:
        load_dotenv()

    vault_url = url or os.environ.get("VAULT_ADDR")
    vault_token = token or os.environ.get("VAULT_TOKEN")
    vault_namespace = namespace or os.environ.get("VAULT_NAMESPACE")

    if not vault_url:
        raise ValueError("Vault URL not provided and VAULT_ADDR env var not set")
    if not vault_token:
        raise ValueError("Vault token not provided and VAULT_TOKEN env var not set")

    client = hvac.Client(url=vault_url, token=vault_token, namespace=vault_namespace, verify=verify)

    if not client.is_authenticated():
        raise VaultError("Failed to authenticate with Vault")

    return client


def list_secrets(client: hvac.Client, path: str, mount_point: str = "secret") -> Dict[str, Any]:
    """
    List secrets at a given path in Vault.

    Args:
        client: Authenticated Vault client
        path: Path to list secrets from
        mount_point: Secret engine mount point

    Returns:
        Dict containing list of secrets
    """
    try:
        result = client.secrets.kv.v2.list_secrets(path=path, mount_point=mount_point)
        return result

    except VaultError as e:
        logger.error(f"Failed to list secrets at path {path}: {e}")
        raise


def get_secret(
    client: hvac.Client, path: str, mount_point: str = "secret", version: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get a secret from Vault.

    Args:
        client: Authenticated Vault client
        path: Path to the secret
        mount_point: Secret engine mount point
        version: Optional version of the secret

    Returns:
        Dict containing secret data
    """
    try:
        result = client.secrets.kv.v2.read_secret_version(
            path=path, mount_point=mount_point, version=version
        )
        return result["data"]["data"]

    except VaultError as e:
        logger.error(f"Failed to get secret at path {path}: {e}")
        raise


def debug_token(token: str) -> str:
    """
    Safely debug token information without exposing the full token.

    Args:
        token: The token to debug

    Returns:
        str: A safe representation of the token for debugging
    """
    if not token:
        return "No token provided"
    # Show only first 4 and last 4 characters of the token
    if len(token) > 8:
        return f"{token[:4]}...{token[-4:]}"
    return "Token too short"


def validate_path_access(client: hvac.Client, path: str, mount_point: str = "secret") -> bool:
    """
    Validate if the client has access to the given path.

    Args:
        client: Authenticated Vault client
        path: Path to validate
        mount_point: The mount point of the KV store

    Returns:
        bool: True if path is accessible, False otherwise
    """
    try:
        if not path:
            # Try listing the mount point
            list_secrets(client, "", mount_point)
            return True

        # Try to list or get the path
        if path.endswith("/"):
            list_secrets(client, path, mount_point)
        else:
            get_secret(client, path, mount_point)
        return True
    except Exception as e:
        logging.debug(f"Path access validation failed: {str(e)}")
        return False


def get_token_info(client: hvac.Client) -> Dict[str, Any]:
    """
    Get detailed information about the current token.

    Args:
        client: Authenticated Vault client

    Returns:
        Dict containing token information including policies and metadata
    """
    try:
        token_info = client.auth.token.lookup_self()
        return token_info
    except Exception as e:
        logging.error(f"Failed to get token info: {str(e)}")
        return {}


def collect_secrets(
    client: hvac.Client, path: str, mount_point: str, secrets_list: List[str]
) -> None:
    """
    Recursively collect all secret paths in Vault.

    Args:
        client: Authenticated Vault client
        path: Current path to traverse
        mount_point: The mount point of the KV store
        secrets_list: List to store found secret paths
    """
    try:
        # List secrets at current path
        result = list_secrets(client, path, mount_point)

        if result and "keys" in result:
            for item in result["keys"]:
                full_path = f"{path}{item}" if path else item

                # If path ends with /, it's a directory
                if item.endswith("/"):
                    collect_secrets(client, full_path, mount_point, secrets_list)
                else:
                    secrets_list.append(full_path)
    except Exception as e:
        logging.error(f"Error collecting secrets at {path}: {str(e)}")
