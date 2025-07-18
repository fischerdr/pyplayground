"""Vault utility functions for interacting with HashiCorp Vault.

This module provides a set of utility functions for interacting with HashiCorp Vault,
including client creation, secret management, and token operations.
"""

import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional

import hvac
import urllib3
from dotenv import load_dotenv
from hvac.exceptions import VaultError

# Disable SSL warnings - due to self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# mypy: disable-error-code="no-any-return"


def create_vault_client(
    url: Optional[str] = None,
    token: Optional[str] = None,
    namespace: Optional[str] = None,
    verify: bool = False,
    load_env: bool = True,
) -> hvac.Client:
    """Create and authenticate a HashiCorp Vault client.

    Creates a new Vault client instance and authenticates it using the provided credentials
    or environment variables. If load_env is True, it will attempt to load environment
    variables from a .env file.

    Args:
        url: Vault server URL. If None, uses VAULT_ADDR environment variable
        token: Vault authentication token. If None, uses VAULT_TOKEN environment variable
        namespace: Vault Enterprise namespace. If None, uses VAULT_NAMESPACE environment variable
        verify: Path to SSL certificate (PEM) for verification. If None, uses system CA certificates
        load_env: Whether to load environment variables from .env file. Defaults to True

    Returns:
        hvac.Client: An authenticated Vault client instance

    Raises:
        VaultError: If connection fails or authentication is unsuccessful
        ValueError: If required URL or token parameters are missing

    Example:
        >>> client = create_vault_client(url="http://vault:8200", token="hvs.example")
        >>> assert client.is_authenticated()
    """
    logger.debug(
        "create_vault_client called with: url=%s, token=%s, namespace=%s, verify=%s",
        url,
        debug_token(token) if token else "None",
        namespace,
        verify,
    )
    if load_env:
        load_dotenv()

    vault_url = url or os.environ.get("VAULT_ADDR")
    vault_token = token or os.environ.get("VAULT_TOKEN")
    vault_namespace = namespace or os.environ.get("VAULT_NAMESPACE")

    if not vault_url:
        raise ValueError("Vault URL not provided and VAULT_ADDR env var not set")
    if not vault_token:
        raise ValueError("Vault token not provided and VAULT_TOKEN env var not set")

    logger.debug(
        "Creating hvac.Client with resolved params: url=%s, token=%s, namespace=%s, verify=%s",
        vault_url,
        debug_token(vault_token),
        vault_namespace,
        verify,
    )

    client = hvac.Client(url=vault_url, token=vault_token, namespace=vault_namespace, verify=verify)
    logger.debug("hvac.Client created: %s", client)

    try:
        client.sys.is_sealed()
        logger.debug("Vault client authenticated successfully against the Vault API.")
    except VaultError as e:
        logger.error("Failed to create and authenticate Vault client.", exc_info=True)
        raise VaultError("Failed to authenticate with Vault") from e

    return client


def login_with_kubernetes(
    role: str,
    jwt: str,
    url: Optional[str] = None,
    mount_point: str = "kubernetes",
    namespace: Optional[str] = None,
    verify: bool = False,
    load_env: bool = True,
) -> hvac.Client:
    """Authenticates to Vault using the Kubernetes auth method.

    This is the recommended approach for services running inside Kubernetes.

    Args:
        role: The Vault role to authenticate against.
        jwt: The Kubernetes service account token (JWT).
        url: Vault server URL. If None, uses VAULT_ADDR environment variable.
        mount_point: The mount path of the Kubernetes auth method in Vault.
        namespace: Vault Enterprise namespace. If None, uses VAULT_NAMESPACE environment variable.
        verify: Whether to verify SSL certificates. Defaults to False.
        load_env: Whether to load environment variables from .env file. Defaults to True.

    Returns:
        hvac.Client: An authenticated Vault client instance.

    Raises:
        VaultError: If authentication fails.
        ValueError: If Vault URL is not provided or found in environment variables.
    """
    logger.debug(
        "login_with_kubernetes called with: role=%s, jwt=%s, url=%s, mount_point=%s, namespace=%s, verify=%s",
        role,
        debug_jwt(jwt),
        url,
        mount_point,
        namespace,
        verify,
    )
    if load_env:
        load_dotenv()

    vault_url = url or os.environ.get("VAULT_ADDR")
    vault_namespace = namespace or os.environ.get("VAULT_NAMESPACE")

    if not vault_url:
        raise ValueError("Vault URL not provided and VAULT_ADDR env var not set")

    logger.debug(
        "Creating initial hvac.Client for K8s auth: url=%s, namespace=%s",
        vault_url,
        vault_namespace,
    )

    client = hvac.Client(url=vault_url, namespace=vault_namespace, verify=verify)
    logger.debug("Initial (unauthenticated) hvac.Client created: %s", client)
    try:
        auth_response = hvac.api.auth_methods.Kubernetes(client.adapter).login(
            role=role,
            jwt=jwt,
            mount_point=mount_point,
        )
        logger.info(
            "Successfully authenticated to Vault with Kubernetes role '%s'. Token accessor: %s",
            role,
            auth_response["auth"]["accessor"],
        )
        logger.debug("hvac.Client is now authenticated. Client state: %s", client)
        logger.debug("Client token is now set: %s", debug_token(client.token))
        # The client token is automatically set by the hvac library upon successful login.

        # Log the full auth response and JWT payload for detailed debugging
        logger.debug("Full Vault auth response: %s", auth_response)
        log_jwt_payload(jwt)

        return client
    except VaultError as e:
        logger.error(
            "Failed to authenticate with Vault using Kubernetes auth method (role: %s): %s",
            role,
            e,
        )
        raise


def list_secrets(
    client: hvac.Client, path: str, mount_point: str = "secret"
) -> Dict[str, List[str]]:
    """List secrets at a specified path in Vault.

    Lists all secrets and subdirectories at the given path in the Vault KV2 secrets engine.

    Args:
        client: An authenticated Vault client instance
        path: Path in Vault to list secrets from (e.g., "myapp/")
        mount_point: The mount point of the KV secrets engine. Defaults to "secret"

    Returns:
        Dict[str, List[str]]: Dictionary containing 'keys' with list of secret names and subdirectories

    Raises:
        VaultError: If listing secrets fails due to permissions or connectivity issues

    Example:
        >>> secrets = list_secrets(client, "myapp/")
        >>> print(secrets["keys"])
        ['config', 'credentials/', 'certificates/']
    """
    try:
        result = client.kv.v2.list_secrets(path=path, mount_point=mount_point)
        if not result or "data" not in result:
            return {"keys": []}
        return {"keys": result["data"]["keys"]}

    except VaultError as e:
        logger.error(f"Failed to list secrets at path {path}: {e}")
        raise


def get_secret(
    client: hvac.Client, path: str, mount_point: str = "secret", version: Optional[int] = None
) -> Dict[str, Any]:
    """Retrieve a secret from Vault.

    Gets the secret data at the specified path from the Vault KV2 secrets engine.
    Optionally retrieves a specific version of the secret.

    Args:
        client: An authenticated Vault client instance
        path: Full path to the secret in Vault (e.g., "myapp/config")
        mount_point: The mount point of the KV secrets engine. Defaults to "secret"
        version: Specific version of the secret to retrieve. If None, gets latest version

    Returns:
        Dict[str, Any]: Dictionary containing the secret data

    Raises:
        VaultError: If secret retrieval fails due to permissions or connectivity issues

    Example:
        >>> secret = get_secret(client, "myapp/config")
        >>> print(secret["api_key"])
        'abc123'
    """
    try:
        result = client.kv.v2.read_secret_version(
            path=path, mount_point=mount_point, version=version
        )
        if not result or "data" not in result or "data" not in result["data"]:
            return {}
        return result["data"]["data"]

    except VaultError as e:
        logger.error(f"Failed to get secret at path {path}: {e}")
        raise


def debug_token(token: str) -> str:
    """Create a safe debug representation of a Vault token.

    Creates a partially redacted version of a Vault token suitable for logging
    or debugging, showing only the first and last 4 characters.

    Args:
        token: The Vault token to create a debug representation for

    Returns:
        str: A redacted representation of the token (e.g., "hvs.....abc1")

    Example:
        >>> print(debug_token("hvs.6F8q9x2mK4"))
        'hvs.....2mK4'
    """
    if not token:
        return "No token provided"
    # Show only first 4 and last 4 characters of the token
    if len(token) > 8:
        return f"{token[:4]}...{token[-4:]}"
    return "Token too short"


def log_jwt_payload(jwt: str):
    """Safely decodes and logs the payload of a JWT for debugging.

    Args:
        jwt: The JWT string to decode.
    """
    if not jwt:
        logger.debug("No JWT provided to decode.")
        return
    try:
        # A JWT is three parts separated by dots: header.payload.signature
        parts = jwt.split(".")
        if len(parts) != 3:
            logger.warning("Malformed JWT: does not contain 3 parts.")
            return

        payload_b64 = parts[1]
        # The payload might have incorrect padding, so we add it if needed
        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)

        # Decode from Base64 and then from UTF-8
        payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
        payload_dict = json.loads(payload_json)

        logger.debug("Decoded JWT Payload Claims: %s", payload_dict)

    except (IndexError, TypeError, base64.binascii.Error, json.JSONDecodeError) as e:
        logger.warning("Could not decode JWT payload for debugging: %s", e, exc_info=True)


def debug_jwt(jwt: str) -> str:
    """Create a safe debug representation of a JWT.

    Creates a partially redacted version of a JWT suitable for logging,
    showing only the first 8 and last 8 characters.

    Args:
        jwt: The JWT string to create a debug representation for.

    Returns:
        str: A redacted representation of the JWT.
    """
    if not jwt:
        return "No JWT provided"
    if len(jwt) > 16:
        return f"{jwt[:8]}...{jwt[-8:]}"
    return "JWT too short to redact"


def validate_path_access(client: hvac.Client, path: str, mount_point: str = "secret") -> bool:
    """Validate if the client has access to a Vault path.

    Checks if the authenticated client has permission to access the specified path
    by attempting to list or read from it.

    Args:
        client: An authenticated Vault client instance
        path: Path in Vault to validate access to
        mount_point: The mount point of the KV secrets engine. Defaults to "secret"

    Returns:
        bool: True if path is accessible, False if path is inaccessible or doesn't exist

    Example:
        >>> has_access = validate_path_access(client, "myapp/config")
        >>> if has_access:
        ...     secret = get_secret(client, "myapp/config")
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
    """Retrieve detailed information about the current authentication token.

    Gets metadata about the token being used by the client, including creation time,
    policies, and any metadata associated with the token.

    Args:
        client: An authenticated Vault client instance

    Returns:
        Dict[str, Any]: Dictionary containing token metadata including:
            - creation_time: Token creation timestamp
            - policies: List of policies attached to the token
            - meta: Dictionary of token metadata
            - num_uses: Number of times token has been used

    Example:
        >>> info = get_token_info(client)
        >>> print(info["policies"])
        ['default', 'app-policy']
    """
    try:
        token_info = client.token.lookup_self()
        if not token_info or "data" not in token_info:
            return {}
        return token_info["data"]
    except Exception as e:
        logging.error(f"Failed to get token info: {str(e)}")
        return {}


def collect_secrets(
    client: hvac.Client, path: str, mount_point: str, secrets_list: List[str]
) -> None:
    """Recursively collect all secret paths under a given path in Vault.

    Traverses the Vault path hierarchy starting at the specified path and collects
    all secret paths into the provided list. This is useful for creating an inventory
    of secrets or validating secret organization.

    Args:
        client: An authenticated Vault client instance
        path: Starting path to begin collection from
        mount_point: The mount point of the KV secrets engine
        secrets_list: List to store collected secret paths (modified in-place)

    Raises:
        VaultError: If secret collection fails due to permissions or connectivity issues

    Example:
        >>> secrets = []
        >>> collect_secrets(client, "myapp/", "secret", secrets)
        >>> print(secrets)
        ['myapp/config', 'myapp/credentials/db', 'myapp/certificates/tls']
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


def normalize_vault_path(path: str) -> tuple[str, str]:
    """Normalize vault path by removing mount prefix and returning mount point.

    Args:
        path: Raw vault path that may include mount prefix

    Returns:
        tuple[str, str]: A tuple containing:
            - mount_point: The vault mount point (e.g. 'static_secrets')
            - normalized_path: The path without mount prefix and leading/trailing slashes
    """
    # Remove leading and trailing slashes
    path = path.strip("/")

    # Split on first slash to separate mount point and path
    parts = path.split("/", 1)
    if len(parts) == 2:
        mount_point, path = parts
    else:
        mount_point = "secret"

    return mount_point, path
