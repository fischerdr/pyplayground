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


def _read_vault_token_file() -> Optional[str]:
    """Read Vault token from the default CLI token file location.

    The Vault CLI stores tokens in ~/.vault-token after successful login.
    This function attempts to read from that file as a fallback when
    VAULT_TOKEN environment variable is not set.

    Returns:
        The token string if file exists and is readable, None otherwise
    """
    try:
        vault_token_file = os.path.expanduser("~/.vault-token")
        if os.path.exists(vault_token_file) and os.path.isfile(vault_token_file):
            with open(vault_token_file, "r") as f:
                token = f.read().strip()
                if token:
                    logger.debug("Successfully read token from ~/.vault-token")
                    return token
                else:
                    logger.debug("~/.vault-token file exists but is empty")
        else:
            logger.debug("~/.vault-token file does not exist")
    except (IOError, OSError) as e:
        logger.debug(f"Could not read ~/.vault-token file: {e}")
    except Exception as e:
        logger.debug(f"Unexpected error reading ~/.vault-token file: {e}")

    return None


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
        token: Vault authentication token. If None, tries VAULT_TOKEN env var, then ~/.vault-token file
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
    vault_token = token or os.environ.get("VAULT_TOKEN") or _read_vault_token_file()
    vault_namespace = namespace or os.environ.get("VAULT_NAMESPACE")

    if not vault_url:
        raise ValueError("Vault URL not provided and VAULT_ADDR env var not set")
    if not vault_token:
        raise ValueError(
            "Vault token not provided. Set VAULT_TOKEN env var, create ~/.vault-token file, "
            "or use 'vault login' command"
        )

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
        # Test basic connectivity and authentication
        logger.debug("Testing Vault connectivity and authentication...")
        seal_status = client.sys.is_sealed()
        logger.debug(f"Vault seal status: {seal_status}")

        # Test authentication by checking if we can read our own token info
        logger.debug("Verifying token authentication...")
        try:
            token_lookup = client.lookup_token()
            if token_lookup and "data" in token_lookup:
                token_data = token_lookup["data"]
                logger.debug("Authentication verification successful:")
                logger.debug(f"  - Token accessor: {token_data.get('accessor', 'N/A')}")
                logger.debug(f"  - Token policies: {token_data.get('policies', [])}")
                logger.debug(f"  - Token entity_id: {token_data.get('entity_id', 'N/A')}")
                logger.debug(f"  - Token renewable: {token_data.get('renewable', 'N/A')}")
                logger.debug(f"  - Token TTL: {token_data.get('ttl', 'N/A')}")
            else:
                logger.debug("Token lookup returned empty response")
        except Exception as token_e:
            logger.debug(f"Could not verify token details (this may be normal): {token_e}")

        logger.debug("Vault client authenticated successfully against the Vault API.")
    except VaultError as e:
        logger.error("Failed to create and authenticate Vault client.", exc_info=True)
        logger.debug(f"VaultError details: {type(e).__name__}: {str(e)}")
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
        logger.debug("Attempting Kubernetes authentication...")
        auth_response = hvac.api.auth_methods.Kubernetes(client.adapter).login(
            role=role,
            jwt=jwt,
            mount_point=mount_point,
        )

        # Enhanced authentication success logging
        auth_data = auth_response.get("auth", {})
        logger.info(
            "Successfully authenticated to Vault with Kubernetes role '%s'. Token accessor: %s",
            role,
            auth_data.get("accessor", "N/A"),
        )

        # Detailed debug logging for authentication response
        logger.debug("Kubernetes authentication successful - detailed response:")
        logger.debug(f"  - Token accessor: {auth_data.get('accessor', 'N/A')}")
        logger.debug(f"  - Token policies: {auth_data.get('policies', [])}")
        logger.debug(f"  - Token metadata: {auth_data.get('metadata', {})}")
        logger.debug(f"  - Token lease duration: {auth_data.get('lease_duration', 'N/A')}")
        logger.debug(f"  - Token renewable: {auth_data.get('renewable', 'N/A')}")
        logger.debug(f"  - Token entity_id: {auth_data.get('entity_id', 'N/A')}")
        logger.debug(f"  - Token client_token: {debug_token(auth_data.get('client_token', ''))}")

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
        result = client.secrets.kv.v2.list_secrets(path=path, mount_point=mount_point)
        if not result or "data" not in result:
            return {"keys": []}
        return {"keys": result["data"]["keys"]}

    except VaultError as e:
        logger.error(f"Failed to list secrets at path {path}: {e}")
        raise


def get_secret(
    client: hvac.Client, path: str, mount_point: str = "secret", version: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """Retrieve a secret from Vault.

    Gets the secret data at the specified path from the Vault KV2 secrets engine.
    Optionally retrieves a specific version of the secret. Returns None if the
    secret is not found, access is forbidden, or an error occurs.

    Args:
        client: An authenticated Vault client instance
        path: Full path to the secret in Vault (e.g., "myapp/config")
        mount_point: The mount point of the KV secrets engine. Defaults to "secret"
        version: Specific version of the secret to retrieve. If None, gets latest version

    Returns:
        A dictionary containing the secret data, or None.

    Raises:
        VaultError: If secret retrieval fails for reasons other than not found/forbidden.

    Example:
        >>> secret = get_secret(client, "myapp/config")
        >>> if secret:
        ...     print(secret["api_key"])
        'abc123'
    """
    try:
        result = client.secrets.kv.v2.read_secret_version(
            path=path, mount_point=mount_point, version=version
        )
        if not result or "data" not in result or "data" not in result["data"]:
            logger.warning(f"Secret at path '{path}' contains no data.")
            return {}  # Return empty dict for existing but empty secret
        return result["data"]["data"]
    except hvac.exceptions.InvalidPath:
        logger.warning(f"Invalid Vault path for secret '{path}' in mount '{mount_point}'.")
        return None
    except hvac.exceptions.Forbidden:
        logger.warning(f"Vault access forbidden for secret path '{path}' in mount '{mount_point}'.")
        return None
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


def get_token_info(client: hvac.Client) -> Dict[str, Any]:  # noqa: C901
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
    logger.debug("Starting token information retrieval...")
    logger.debug(
        f"Current token (redacted): {debug_token(client.token) if client.token else 'None'}"
    )

    try:
        logger.debug("Calling client.lookup_token() to get self token info...")
        token_info = client.lookup_token()
        logger.debug(f"Raw token info response: {token_info}")

        if not token_info or "data" not in token_info:
            logger.debug("Token info response was empty or malformed")
            return {}

        token_data = token_info["data"]

        # Enhanced debug logging for token analysis
        logger.debug("Token information details:")
        logger.debug(f"  - Accessor: {token_data.get('accessor', 'N/A')}")
        logger.debug(f"  - Creation time: {token_data.get('creation_time', 'N/A')}")
        logger.debug(f"  - Creation TTL: {token_data.get('creation_ttl', 'N/A')}")
        logger.debug(f"  - Display name: {token_data.get('display_name', 'N/A')}")
        logger.debug(f"  - Entity ID: {token_data.get('entity_id', 'N/A')}")
        logger.debug(f"  - Expire time: {token_data.get('expire_time', 'N/A')}")
        logger.debug(f"  - Explicit max TTL: {token_data.get('explicit_max_ttl', 'N/A')}")
        logger.debug(
            f"  - ID: {debug_token(token_data.get('id', '')) if token_data.get('id') else 'N/A'}"
        )
        logger.debug(f"  - Issue time: {token_data.get('issue_time', 'N/A')}")
        logger.debug(f"  - Num uses: {token_data.get('num_uses', 'N/A')}")
        logger.debug(f"  - Orphan: {token_data.get('orphan', 'N/A')}")
        logger.debug(f"  - Path: {token_data.get('path', 'N/A')}")
        logger.debug(f"  - Policies: {token_data.get('policies', [])}")
        logger.debug(f"  - Renewable: {token_data.get('renewable', 'N/A')}")
        logger.debug(f"  - TTL: {token_data.get('ttl', 'N/A')}")
        logger.debug(f"  - Type: {token_data.get('type', 'N/A')}")

        # Log metadata if present
        meta = token_data.get("meta", {})
        if meta:
            logger.debug(f"  - Metadata: {meta}")
        else:
            logger.debug("  - No metadata associated with token")

        # Security analysis
        policies = token_data.get("policies", [])
        if "root" in policies:
            logger.debug("    * WARNING: Token has ROOT policy - highest privileges")
        if not policies:
            logger.debug("    * WARNING: Token has no policies assigned")
        elif len(policies) > 10:
            logger.debug(f"    * NOTICE: Token has many policies assigned ({len(policies)})")

        # Check token type and characteristics
        token_type = token_data.get("type", "unknown")
        if token_type == "service":
            logger.debug("    * Service token - long-lived, suitable for applications")
        elif token_type == "batch":
            logger.debug("    * Batch token - lightweight, limited capabilities")
        elif token_type == "default":
            logger.debug("    * Default token type")

        # Check TTL settings
        ttl = token_data.get("ttl", 0)
        if ttl == 0:
            logger.debug("    * Token has unlimited TTL (never expires)")
        elif ttl < 3600:  # Less than 1 hour
            logger.debug(f"    * Token expires soon (TTL: {ttl} seconds)")

        logger.debug("Token information retrieval completed successfully")
        return token_data

    except Exception as e:
        logger.error(f"Failed to get token info: {str(e)}")
        logger.debug(f"Exception details for token info: {type(e).__name__}: {str(e)}")
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


def get_token_for_namespace(
    vault_namespace: str,
    vault_tokens_cache: Dict[str, Optional[str]],
    vault_conn_info: Dict[str, str],
    sa_jwt: str,
) -> Optional[str]:
    """Retrieves a Vault token for a given namespace, using a cache.

    Args:
        vault_namespace: The Vault namespace to authenticate against.
        vault_tokens_cache: A dictionary to cache tokens.
        vault_conn_info: A dictionary with Vault connection details.
        sa_jwt: The Kubernetes service account JWT.

    Returns:
        The Vault token string if successful, otherwise None.
    """
    if vault_namespace in vault_tokens_cache:
        return vault_tokens_cache[vault_namespace]

    try:
        logger.info(f"Authenticating to Vault for namespace: '{vault_namespace}'")
        vault_client = login_with_kubernetes(
            role=vault_conn_info["auth_role"],
            jwt=sa_jwt,
            url=vault_conn_info["addr"],
            mount_point=vault_conn_info["auth_mount_path"],
            namespace=vault_namespace,
        )
        token = vault_client.token
        if not token:
            raise ValueError("Authentication successful but client token is empty.")
        logger.info(f"Successfully authenticated for Vault namespace '{vault_namespace}'.")
        vault_tokens_cache[vault_namespace] = token
        return token
    except VaultError as e:
        logger.error(
            f"Vault API error during authentication for namespace '{vault_namespace}': {e}",
            exc_info=True,
        )
        vault_tokens_cache[vault_namespace] = None
        return None
    except Exception as e:
        logger.error(
            f"Failed to authenticate with Vault for namespace '{vault_namespace}': {e}",
            exc_info=True,
        )
        vault_tokens_cache[vault_namespace] = None  # Cache failure
        return None


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


def get_policies(client: hvac.Client) -> Dict[str, Any]:  # noqa: C901
    """Retrieve all policies in the current namespace.

    Args:
        client: The Vault client instance

    Returns:
        Dict containing policy information
    """
    policies_data = {"policies": [], "errors": []}

    logger.debug("Starting policy retrieval process...")
    logger.debug(f"Vault client namespace: {getattr(client, 'namespace', 'None')}")
    logger.debug(f"Vault client URL: {getattr(client, 'url', 'None')}")

    try:
        # List all policies
        logger.debug("Calling client.sys.list_policies()...")
        policies_response = client.sys.list_policies()
        logger.debug(f"Raw policies response: {policies_response}")

        if not policies_response or "data" not in policies_response:
            logger.warning("No policies found or unable to list policies")
            logger.debug("Policies response structure invalid or empty")
            return policies_data

        policies = policies_response["data"]["policies"]
        logger.info(f"Found {len(policies)} policies")
        logger.debug(f"Policy names: {policies}")

        # Get details for each policy
        for i, policy_name in enumerate(policies, 1):
            logger.debug(f"Retrieving policy {i}/{len(policies)}: '{policy_name}'")
            try:
                policy_response = client.sys.read_policy(name=policy_name)
                logger.debug(f"Raw policy response for '{policy_name}': {policy_response}")

                if policy_response and "data" in policy_response:
                    rules = policy_response["data"]["rules"]
                    policy_type = policy_response["data"].get("type", "unknown")

                    policy_info = {
                        "name": policy_name,
                        "rules": rules,
                        "type": policy_type,
                    }

                    # Enhanced debug logging for policy analysis
                    logger.debug(f"Policy '{policy_name}' details:")
                    logger.debug(f"  - Type: {policy_type}")
                    logger.debug(f"  - Rules length: {len(rules)} characters")
                    logger.debug(f"  - Rules content preview: {rules[:200]}...")

                    # Analyze policy rules for common patterns
                    if rules:
                        rules_lower = rules.lower()
                        capabilities_count = rules_lower.count("capabilities")
                        path_count = rules_lower.count("path")
                        secret_refs = rules_lower.count("secret")
                        deny_refs = rules_lower.count("deny")

                        logger.debug(f"  - Policy analysis for '{policy_name}':")
                        logger.debug(f"    * Capabilities statements: {capabilities_count}")
                        logger.debug(f"    * Path statements: {path_count}")
                        logger.debug(f"    * Secret path references: {secret_refs}")
                        logger.debug(f"    * Deny statements: {deny_refs}")

                        # Log specific security-relevant patterns
                        if deny_refs > 0:
                            logger.debug(
                                f"    * WARNING: Policy '{policy_name}' contains DENY rules"
                            )
                        if "admin" in rules_lower or "sudo" in rules_lower:
                            logger.debug(
                                f"    * NOTICE: Policy '{policy_name}' may have admin privileges"
                            )
                        if "*" in rules:
                            logger.debug(
                                f"    * NOTICE: Policy '{policy_name}' contains wildcard permissions"
                            )

                    policies_data["policies"].append(policy_info)
                    logger.debug(f"Successfully processed policy '{policy_name}'")
                else:
                    logger.warning(f"Could not retrieve details for policy: {policy_name}")
                    logger.debug(f"Policy response for '{policy_name}' was empty or malformed")
                    policies_data["errors"].append(f"Failed to retrieve policy: {policy_name}")
            except Exception as e:
                logger.error(f"Error retrieving policy '{policy_name}': {e}")
                logger.debug(
                    f"Exception details for policy '{policy_name}': {type(e).__name__}: {str(e)}"
                )
                policies_data["errors"].append(f"Error retrieving policy '{policy_name}': {str(e)}")

    except Exception as e:
        logger.error(f"Error listing policies: {e}")
        logger.debug(f"Exception details for listing policies: {type(e).__name__}: {str(e)}")
        policies_data["errors"].append(f"Error listing policies: {str(e)}")

    logger.debug(
        f"Policy retrieval completed. Total policies: {len(policies_data['policies'])}, Errors: {len(policies_data['errors'])}"
    )
    return policies_data


def get_groups(client: hvac.Client) -> Dict[str, Any]:  # noqa: C901
    """Retrieve all identity groups in the current namespace.

    Args:
        client: The Vault client instance

    Returns:
        Dict containing group information
    """
    groups_data = {"groups": [], "errors": []}

    logger.debug("Starting identity groups retrieval process...")
    logger.debug(f"Vault client namespace: {getattr(client, 'namespace', 'None')}")
    logger.debug(f"Vault client URL: {getattr(client, 'url', 'None')}")

    try:
        # Check if identity secrets engine is available
        if not hasattr(client.secrets, "identity"):
            logger.warning("Identity secrets engine not available on this Vault client")
            groups_data["errors"].append("Identity secrets engine not available")
            return groups_data

        # List all groups
        logger.debug("Calling client.secrets.identity.list_groups()...")
        groups_response = client.secrets.identity.list_groups()
        logger.debug(f"Raw groups response: {groups_response}")

        if not groups_response or "data" not in groups_response:
            logger.warning("No groups found or unable to list groups")
            logger.debug("Groups response structure invalid or empty")
            return groups_data

        groups = groups_response["data"]["keys"]
        logger.info(f"Found {len(groups)} groups")
        logger.debug(f"Group IDs: {groups}")

        # Get details for each group
        for i, group_id in enumerate(groups, 1):
            logger.debug(f"Retrieving group {i}/{len(groups)}: '{group_id}'")
            try:
                group_response = client.secrets.identity.read_group(group_id=group_id)
                logger.debug(f"Raw group response for '{group_id}': {group_response}")

                if group_response and "data" in group_response:
                    group_data = group_response["data"]
                    group_name = group_data.get("name", "Unknown")
                    group_type = group_data.get("type", "unknown")
                    member_entities = group_data.get("member_entity_ids", [])
                    member_groups = group_data.get("member_group_ids", [])
                    policies = group_data.get("policies", [])
                    metadata = group_data.get("metadata", {})

                    group_info = {
                        "id": group_id,
                        "name": group_name,
                        "type": group_type,
                        "member_entity_ids": member_entities,
                        "member_group_ids": member_groups,
                        "policies": policies,
                        "metadata": metadata,
                    }

                    # Enhanced debug logging for group analysis
                    logger.debug(f"Group '{group_name}' (ID: {group_id}) details:")
                    logger.debug(f"  - Type: {group_type}")
                    logger.debug(f"  - Member entities: {len(member_entities)} ({member_entities})")
                    logger.debug(f"  - Member groups: {len(member_groups)} ({member_groups})")
                    logger.debug(f"  - Assigned policies: {len(policies)} ({policies})")
                    logger.debug(f"  - Metadata keys: {list(metadata.keys())}")

                    # Log detailed metadata if present
                    if metadata:
                        logger.debug(f"  - Metadata content: {metadata}")

                    # Security analysis
                    if not policies:
                        logger.debug(f"    * NOTICE: Group '{group_name}' has no policies assigned")
                    elif len(policies) > 5:
                        logger.debug(
                            f"    * NOTICE: Group '{group_name}' has many policies ({len(policies)})"
                        )

                    # Check for nested group relationships
                    if member_groups:
                        logger.debug(
                            f"    * NOTICE: Group '{group_name}' contains nested groups: {member_groups}"
                        )

                    groups_data["groups"].append(group_info)
                    logger.debug(f"Successfully processed group '{group_name}' (ID: {group_id})")
                else:
                    logger.warning(f"Could not retrieve details for group: {group_id}")
                    logger.debug(f"Group response for '{group_id}' was empty or malformed")
                    groups_data["errors"].append(f"Failed to retrieve group: {group_id}")
            except Exception as e:
                logger.error(f"Error retrieving group '{group_id}': {e}")
                logger.debug(
                    f"Exception details for group '{group_id}': {type(e).__name__}: {str(e)}"
                )
                groups_data["errors"].append(f"Error retrieving group '{group_id}': {str(e)}")

    except Exception as e:
        error_msg = str(e)
        if "permission denied" in error_msg.lower():
            logger.warning(f"Permission denied listing identity groups: {e}")
            logger.info("This may be normal if your token doesn't have identity group permissions")
            groups_data["errors"].append(f"Permission denied listing groups: {str(e)}")
        else:
            logger.error(f"Error listing groups: {e}")
            logger.debug(f"Exception details for listing groups: {type(e).__name__}: {str(e)}")
            groups_data["errors"].append(f"Error listing groups: {str(e)}")

    logger.debug(
        f"Groups retrieval completed. Total groups: {len(groups_data['groups'])}, Errors: {len(groups_data['errors'])}"
    )
    return groups_data


def get_auth_methods(client: hvac.Client) -> Dict[str, Any]:  # noqa: C901
    """Retrieve all enabled authentication methods in the current namespace.

    Args:
        client: The Vault client instance

    Returns:
        Dict containing auth method information
    """
    auth_methods_data = {"auth_methods": [], "errors": []}

    logger.debug("Starting authentication methods retrieval process...")
    logger.debug(f"Vault client namespace: {getattr(client, 'namespace', 'None')}")
    logger.debug(f"Vault client URL: {getattr(client, 'url', 'None')}")

    try:
        # List all auth methods
        logger.debug("Calling client.sys.list_auth_methods()...")
        auth_methods_response = client.sys.list_auth_methods()
        logger.debug(f"Raw auth methods response: {auth_methods_response}")

        if not auth_methods_response or "data" not in auth_methods_response:
            logger.warning("No auth methods found or unable to list auth methods")
            logger.debug("Auth methods response structure invalid or empty")
            return auth_methods_data

        auth_methods = auth_methods_response["data"]
        logger.info(f"Found {len(auth_methods)} auth methods")
        logger.debug(f"Auth method paths: {list(auth_methods.keys())}")

        # Get details for each auth method
        for i, (path, auth_info) in enumerate(auth_methods.items(), 1):
            logger.debug(f"Processing auth method {i}/{len(auth_methods)}: '{path}'")
            try:
                auth_type = auth_info.get("type", "unknown")
                description = auth_info.get("description", "")
                accessor = auth_info.get("accessor", "")
                config = auth_info.get("config", {})

                auth_method_info = {
                    "path": path,
                    "type": auth_type,
                    "description": description,
                    "accessor": accessor,
                    "config": config,
                }

                # Enhanced debug logging for auth method analysis
                logger.debug(f"Auth method '{path}' details:")
                logger.debug(f"  - Type: {auth_type}")
                logger.debug(f"  - Description: {description}")
                logger.debug(f"  - Accessor: {accessor}")
                logger.debug(f"  - Config keys: {list(config.keys())}")

                # Log detailed configuration if present
                if config:
                    logger.debug("  - Configuration details:")
                    for config_key, config_value in config.items():
                        # Mask sensitive configuration values
                        if any(
                            sensitive in config_key.lower()
                            for sensitive in ["password", "secret", "key", "token"]
                        ):
                            logger.debug(f"    * {config_key}: [REDACTED]")
                        else:
                            logger.debug(f"    * {config_key}: {config_value}")

                # Security and operational analysis
                logger.debug(f"  - Auth method analysis for '{path}':")
                if auth_type == "token":
                    logger.debug("    * Token auth method - check for proper token policies")
                elif auth_type == "kubernetes":
                    logger.debug("    * Kubernetes auth method - verify service account bindings")
                elif auth_type == "ldap":
                    logger.debug("    * LDAP auth method - verify group mappings and security")
                elif auth_type == "userpass":
                    logger.debug("    * Userpass auth method - ensure strong password policies")
                elif auth_type == "aws":
                    logger.debug("    * AWS auth method - verify IAM role bindings")
                elif auth_type == "azure":
                    logger.debug("    * Azure auth method - verify managed identity configuration")
                elif auth_type == "oidc" or auth_type == "jwt":
                    logger.debug(
                        "    * OIDC/JWT auth method - verify issuer and audience configuration"
                    )
                else:
                    logger.debug(
                        f"    * Unknown auth type '{auth_type}' - manual review recommended"
                    )

                # Check for default mount paths that might indicate security concerns
                if path in ["token/", "userpass/", "ldap/"]:
                    logger.debug(f"    * NOTICE: Auth method '{path}' uses default mount path")

                auth_methods_data["auth_methods"].append(auth_method_info)
                logger.debug(f"Successfully processed auth method '{path}' (Type: {auth_type})")
            except Exception as e:
                logger.error(f"Error processing auth method '{path}': {e}")
                logger.debug(
                    f"Exception details for auth method '{path}': {type(e).__name__}: {str(e)}"
                )
                auth_methods_data["errors"].append(
                    f"Error processing auth method '{path}': {str(e)}"
                )

    except Exception as e:
        logger.error(f"Error listing auth methods: {e}")
        logger.debug(f"Exception details for listing auth methods: {type(e).__name__}: {str(e)}")
        auth_methods_data["errors"].append(f"Error listing auth methods: {str(e)}")

    logger.debug(
        f"Auth methods retrieval completed. Total auth methods: {len(auth_methods_data['auth_methods'])}, Errors: {len(auth_methods_data['errors'])}"
    )
    return auth_methods_data


def get_auth_role_bindings(  # noqa: C901
    client: hvac.Client, auth_methods: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Retrieve role bindings for all authentication methods.

    Args:
        client: The Vault client instance
        auth_methods: List of auth methods from get_auth_methods()

    Returns:
        Dict containing role binding information for each auth method
    """
    role_bindings_data = {"role_bindings": [], "errors": []}

    logger.debug("Starting authentication role bindings retrieval process...")
    logger.debug(f"Processing {len(auth_methods)} auth methods for role bindings")

    for auth_method in auth_methods:
        auth_path = auth_method.get("path", "")
        auth_type = auth_method.get("type", "unknown")

        logger.debug(f"Retrieving role bindings for auth method: '{auth_path}' (type: {auth_type})")

        try:
            roles_data = {
                "auth_method": auth_path,
                "auth_type": auth_type,
                "roles": [],
                "errors": [],
            }

            # Handle different auth method types
            if auth_type == "kubernetes":
                roles_data.update(_get_kubernetes_role_bindings(client, auth_path))
            elif auth_type == "ldap":
                roles_data.update(_get_ldap_role_bindings(client, auth_path))
            elif auth_type == "userpass":
                roles_data.update(_get_userpass_role_bindings(client, auth_path))
            elif auth_type == "aws":
                roles_data.update(_get_aws_role_bindings(client, auth_path))
            elif auth_type == "azure":
                roles_data.update(_get_azure_role_bindings(client, auth_path))
            elif auth_type == "oidc" or auth_type == "jwt":
                roles_data.update(_get_oidc_jwt_role_bindings(client, auth_path))
            elif auth_type == "approle":
                roles_data.update(_get_approle_role_bindings(client, auth_path))
            elif auth_type == "token":
                logger.debug(
                    f"Token auth method '{auth_path}' - roles managed through policies, not role bindings"
                )
                roles_data["roles"] = []  # Token auth doesn't have traditional roles
            elif auth_type == "ns_token":
                logger.debug(
                    f"Namespace token auth method '{auth_path}' - roles managed through policies, not role bindings"
                )
                roles_data["roles"] = []  # NS token auth doesn't have traditional roles
            else:
                logger.debug(
                    f"Unknown auth method type '{auth_type}' - skipping role binding retrieval"
                )
                roles_data["roles"] = []
                roles_data["errors"].append(f"Unknown auth method type: {auth_type}")

            role_bindings_data["role_bindings"].append(roles_data)
            logger.debug(
                f"Role binding retrieval completed for auth method '{auth_path}': {len(roles_data.get('roles', []))} roles found"
            )

        except Exception as e:
            logger.error(f"Error retrieving role bindings for auth method '{auth_path}': {e}")
            logger.debug(
                f"Exception details for auth method '{auth_path}': {type(e).__name__}: {str(e)}"
            )
            role_bindings_data["errors"].append(
                f"Error retrieving role bindings for '{auth_path}': {str(e)}"
            )

    total_roles = sum(len(rb.get("roles", [])) for rb in role_bindings_data["role_bindings"])
    logger.debug(
        f"Role bindings retrieval completed. Total roles across all auth methods: {total_roles}, Errors: {len(role_bindings_data['errors'])}"
    )
    return role_bindings_data


def _get_kubernetes_role_bindings(  # noqa: C901
    client: hvac.Client, auth_path: str
) -> Dict[str, Any]:
    """Retrieve Kubernetes auth method role bindings."""
    roles_data = {"roles": [], "errors": []}

    logger.debug(f"Retrieving Kubernetes roles for auth path: {auth_path}")

    try:
        # List roles for Kubernetes auth method using the correct LIST operation
        roles_list_path = f"auth/{auth_path.rstrip('/')}/role"
        logger.debug(f"Listing Kubernetes roles at path: {roles_list_path}")
        roles_response = client.list(roles_list_path)
        logger.debug(f"Raw Kubernetes roles list response: {roles_response}")

        if roles_response and "data" in roles_response and "keys" in roles_response["data"]:
            role_names = roles_response["data"]["keys"]
            logger.debug(f"Found {len(role_names)} Kubernetes roles: {role_names}")

            for role_name in role_names:
                try:
                    role_response = client.read(f"auth/{auth_path.rstrip('/')}/role/{role_name}")
                    logger.debug(f"Raw Kubernetes role response for '{role_name}': {role_response}")

                    if role_response and "data" in role_response:
                        role_data = role_response["data"]

                        role_info = {
                            "name": role_name,
                            "bound_service_account_names": role_data.get(
                                "bound_service_account_names", []
                            ),
                            "bound_service_account_namespaces": role_data.get(
                                "bound_service_account_namespaces", []
                            ),
                            "token_policies": role_data.get("token_policies", []),
                            "token_ttl": role_data.get("token_ttl", 0),
                            "token_max_ttl": role_data.get("token_max_ttl", 0),
                            "audience": role_data.get("audience", ""),
                        }

                        # Enhanced debug logging for Kubernetes role
                        logger.debug(f"Kubernetes role '{role_name}' details:")
                        logger.debug(
                            f"  - Bound service accounts: {role_info['bound_service_account_names']}"
                        )
                        logger.debug(
                            f"  - Bound namespaces: {role_info['bound_service_account_namespaces']}"
                        )
                        logger.debug(f"  - Token policies: {role_info['token_policies']}")
                        logger.debug(f"  - Token TTL: {role_info['token_ttl']}")
                        logger.debug(f"  - Token Max TTL: {role_info['token_max_ttl']}")
                        logger.debug(f"  - Audience: {role_info['audience']}")

                        # Security analysis
                        if "*" in role_info["bound_service_account_names"]:
                            logger.debug(
                                f"    * WARNING: Role '{role_name}' allows any service account"
                            )
                        if "*" in role_info["bound_service_account_namespaces"]:
                            logger.debug(f"    * WARNING: Role '{role_name}' allows any namespace")
                        if not role_info["token_policies"]:
                            logger.debug(f"    * WARNING: Role '{role_name}' has no token policies")

                        roles_data["roles"].append(role_info)

                except Exception as e:
                    logger.error(f"Error retrieving Kubernetes role '{role_name}': {e}")
                    roles_data["errors"].append(
                        f"Error retrieving Kubernetes role '{role_name}': {str(e)}"
                    )
        else:
            logger.debug("No Kubernetes roles found or unable to list roles")

    except Exception as e:
        error_msg = str(e)
        if "unsupported operation" in error_msg.lower():
            logger.warning(
                f"Kubernetes auth method at '{auth_path}' doesn't support role listing: {e}"
            )
            logger.info("This may be normal for certain Kubernetes auth configurations")
            roles_data["errors"].append(f"Role listing not supported for {auth_path}: {str(e)}")
        elif "permission denied" in error_msg.lower():
            logger.warning(f"Permission denied listing Kubernetes roles at '{auth_path}': {e}")
            logger.info("This may be normal if your token doesn't have auth method permissions")
            roles_data["errors"].append(
                f"Permission denied listing roles for {auth_path}: {str(e)}"
            )
        else:
            logger.error(f"Error listing Kubernetes roles: {e}")
            roles_data["errors"].append(f"Error listing Kubernetes roles: {str(e)}")

    return roles_data


def _get_ldap_role_bindings(client: hvac.Client, auth_path: str) -> Dict[str, Any]:  # noqa: C901
    """Retrieve LDAP auth method role bindings."""
    roles_data = {"roles": [], "errors": []}

    logger.debug(f"Retrieving LDAP groups/users for auth path: {auth_path}")

    try:
        # LDAP uses groups and users, not traditional roles
        # Try to get LDAP groups using LIST operation
        groups_list_path = f"auth/{auth_path.rstrip('/')}/groups"
        logger.debug(f"Listing LDAP groups at path: {groups_list_path}")
        groups_response = client.list(groups_list_path)
        logger.debug(f"Raw LDAP groups list response: {groups_response}")

        if groups_response and "data" in groups_response and "keys" in groups_response["data"]:
            group_names = groups_response["data"]["keys"]
            logger.debug(f"Found {len(group_names)} LDAP groups: {group_names}")

            for group_name in group_names:
                try:
                    group_response = client.read(
                        f"auth/{auth_path.rstrip('/')}/groups/{group_name}"
                    )
                    if group_response and "data" in group_response:
                        group_data = group_response["data"]

                        role_info = {
                            "name": group_name,
                            "type": "ldap_group",
                            "policies": group_data.get("policies", []),
                        }

                        logger.debug(f"LDAP group '{group_name}' details:")
                        logger.debug(f"  - Policies: {role_info['policies']}")

                        roles_data["roles"].append(role_info)

                except Exception as e:
                    logger.error(f"Error retrieving LDAP group '{group_name}': {e}")
                    roles_data["errors"].append(
                        f"Error retrieving LDAP group '{group_name}': {str(e)}"
                    )

        # Try to get LDAP users using LIST operation
        users_list_path = f"auth/{auth_path.rstrip('/')}/users"
        logger.debug(f"Listing LDAP users at path: {users_list_path}")
        users_response = client.list(users_list_path)
        logger.debug(f"Raw LDAP users list response: {users_response}")

        if users_response and "data" in users_response and "keys" in users_response["data"]:
            user_names = users_response["data"]["keys"]
            logger.debug(f"Found {len(user_names)} LDAP users: {user_names}")

            for user_name in user_names:
                try:
                    user_response = client.read(f"auth/{auth_path.rstrip('/')}/users/{user_name}")
                    if user_response and "data" in user_response:
                        user_data = user_response["data"]

                        role_info = {
                            "name": user_name,
                            "type": "ldap_user",
                            "policies": user_data.get("policies", []),
                            "groups": user_data.get("groups", []),
                        }

                        logger.debug(f"LDAP user '{user_name}' details:")
                        logger.debug(f"  - Policies: {role_info['policies']}")
                        logger.debug(f"  - Groups: {role_info['groups']}")

                        roles_data["roles"].append(role_info)

                except Exception as e:
                    logger.error(f"Error retrieving LDAP user '{user_name}': {e}")
                    roles_data["errors"].append(
                        f"Error retrieving LDAP user '{user_name}': {str(e)}"
                    )

    except Exception as e:
        error_msg = str(e)
        if "unsupported operation" in error_msg.lower():
            logger.warning(
                f"LDAP auth method at '{auth_path}' doesn't support groups/users listing: {e}"
            )
            logger.info("This may be normal for certain LDAP auth configurations or permissions")
            roles_data["errors"].append(
                f"Groups/users listing not supported for {auth_path}: {str(e)}"
            )
        elif "permission denied" in error_msg.lower():
            logger.warning(f"Permission denied listing LDAP groups/users at '{auth_path}': {e}")
            logger.info(
                "This may be normal if your token doesn't have LDAP auth method permissions"
            )
            roles_data["errors"].append(
                f"Permission denied listing LDAP groups/users for {auth_path}: {str(e)}"
            )
        else:
            logger.error(f"Error listing LDAP groups/users: {e}")
            roles_data["errors"].append(f"Error listing LDAP groups/users: {str(e)}")

    return roles_data


def _get_userpass_role_bindings(client: hvac.Client, auth_path: str) -> Dict[str, Any]:
    """Retrieve userpass auth method role bindings."""
    roles_data = {"roles": [], "errors": []}

    logger.debug(f"Retrieving userpass users for auth path: {auth_path}")

    try:
        # List users for userpass auth method
        users_response = client.read(f"auth/{auth_path.rstrip('/')}/users")
        logger.debug(f"Raw userpass users list response: {users_response}")

        if users_response and "data" in users_response and "keys" in users_response["data"]:
            user_names = users_response["data"]["keys"]
            logger.debug(f"Found {len(user_names)} userpass users: {user_names}")

            for user_name in user_names:
                try:
                    user_response = client.read(f"auth/{auth_path.rstrip('/')}/users/{user_name}")
                    if user_response and "data" in user_response:
                        user_data = user_response["data"]

                        role_info = {
                            "name": user_name,
                            "type": "userpass_user",
                            "policies": user_data.get("policies", []),
                            "token_ttl": user_data.get("token_ttl", 0),
                            "token_max_ttl": user_data.get("token_max_ttl", 0),
                        }

                        logger.debug(f"Userpass user '{user_name}' details:")
                        logger.debug(f"  - Policies: {role_info['policies']}")
                        logger.debug(f"  - Token TTL: {role_info['token_ttl']}")
                        logger.debug(f"  - Token Max TTL: {role_info['token_max_ttl']}")

                        if not role_info["policies"]:
                            logger.debug(
                                f"    * WARNING: User '{user_name}' has no policies assigned"
                            )

                        roles_data["roles"].append(role_info)

                except Exception as e:
                    logger.error(f"Error retrieving userpass user '{user_name}': {e}")
                    roles_data["errors"].append(
                        f"Error retrieving userpass user '{user_name}': {str(e)}"
                    )
        else:
            logger.debug("No userpass users found or unable to list users")

    except Exception as e:
        logger.error(f"Error listing userpass users: {e}")
        roles_data["errors"].append(f"Error listing userpass users: {str(e)}")

    return roles_data


def _get_aws_role_bindings(client: hvac.Client, auth_path: str) -> Dict[str, Any]:
    """Retrieve AWS auth method role bindings."""
    roles_data = {"roles": [], "errors": []}

    logger.debug(f"Retrieving AWS roles for auth path: {auth_path}")

    try:
        # List roles for AWS auth method
        roles_response = client.read(f"auth/{auth_path.rstrip('/')}/roles")
        logger.debug(f"Raw AWS roles list response: {roles_response}")

        if roles_response and "data" in roles_response and "keys" in roles_response["data"]:
            role_names = roles_response["data"]["keys"]
            logger.debug(f"Found {len(role_names)} AWS roles: {role_names}")

            for role_name in role_names:
                try:
                    role_response = client.read(f"auth/{auth_path.rstrip('/')}/role/{role_name}")
                    if role_response and "data" in role_response:
                        role_data = role_response["data"]

                        role_info = {
                            "name": role_name,
                            "type": "aws_role",
                            "auth_type": role_data.get("auth_type", ""),
                            "bound_account_id": role_data.get("bound_account_id", []),
                            "bound_arn": role_data.get("bound_arn", []),
                            "bound_iam_instance_profile_arn": role_data.get(
                                "bound_iam_instance_profile_arn", []
                            ),
                            "bound_iam_role_arn": role_data.get("bound_iam_role_arn", []),
                            "bound_vpc_id": role_data.get("bound_vpc_id", []),
                            "token_policies": role_data.get("token_policies", []),
                            "token_ttl": role_data.get("token_ttl", 0),
                            "token_max_ttl": role_data.get("token_max_ttl", 0),
                        }

                        logger.debug(f"AWS role '{role_name}' details:")
                        logger.debug(f"  - Auth type: {role_info['auth_type']}")
                        logger.debug(f"  - Bound account IDs: {role_info['bound_account_id']}")
                        logger.debug(f"  - Bound ARNs: {role_info['bound_arn']}")
                        logger.debug(f"  - Token policies: {role_info['token_policies']}")
                        logger.debug(f"  - Token TTL: {role_info['token_ttl']}")

                        # Security analysis
                        if "*" in str(role_info["bound_account_id"]):
                            logger.debug(
                                f"    * WARNING: Role '{role_name}' allows any AWS account"
                            )
                        if not role_info["token_policies"]:
                            logger.debug(f"    * WARNING: Role '{role_name}' has no token policies")

                        roles_data["roles"].append(role_info)

                except Exception as e:
                    logger.error(f"Error retrieving AWS role '{role_name}': {e}")
                    roles_data["errors"].append(
                        f"Error retrieving AWS role '{role_name}': {str(e)}"
                    )
        else:
            logger.debug("No AWS roles found or unable to list roles")

    except Exception as e:
        logger.error(f"Error listing AWS roles: {e}")
        roles_data["errors"].append(f"Error listing AWS roles: {str(e)}")

    return roles_data


def _get_azure_role_bindings(client: hvac.Client, auth_path: str) -> Dict[str, Any]:
    """Retrieve Azure auth method role bindings."""
    roles_data = {"roles": [], "errors": []}

    logger.debug(f"Retrieving Azure roles for auth path: {auth_path}")

    try:
        # List roles for Azure auth method
        roles_response = client.read(f"auth/{auth_path.rstrip('/')}/roles")
        logger.debug(f"Raw Azure roles list response: {roles_response}")

        if roles_response and "data" in roles_response and "keys" in roles_response["data"]:
            role_names = roles_response["data"]["keys"]
            logger.debug(f"Found {len(role_names)} Azure roles: {role_names}")

            for role_name in role_names:
                try:
                    role_response = client.read(f"auth/{auth_path.rstrip('/')}/role/{role_name}")
                    if role_response and "data" in role_response:
                        role_data = role_response["data"]

                        role_info = {
                            "name": role_name,
                            "type": "azure_role",
                            "bound_subscription_id": role_data.get("bound_subscription_id", []),
                            "bound_resource_groups": role_data.get("bound_resource_groups", []),
                            "bound_locations": role_data.get("bound_locations", []),
                            "token_policies": role_data.get("token_policies", []),
                            "token_ttl": role_data.get("token_ttl", 0),
                            "token_max_ttl": role_data.get("token_max_ttl", 0),
                        }

                        logger.debug(f"Azure role '{role_name}' details:")
                        logger.debug(
                            f"  - Bound subscriptions: {role_info['bound_subscription_id']}"
                        )
                        logger.debug(
                            f"  - Bound resource groups: {role_info['bound_resource_groups']}"
                        )
                        logger.debug(f"  - Bound locations: {role_info['bound_locations']}")
                        logger.debug(f"  - Token policies: {role_info['token_policies']}")

                        roles_data["roles"].append(role_info)

                except Exception as e:
                    logger.error(f"Error retrieving Azure role '{role_name}': {e}")
                    roles_data["errors"].append(
                        f"Error retrieving Azure role '{role_name}': {str(e)}"
                    )
        else:
            logger.debug("No Azure roles found or unable to list roles")

    except Exception as e:
        logger.error(f"Error listing Azure roles: {e}")
        roles_data["errors"].append(f"Error listing Azure roles: {str(e)}")

    return roles_data


def _get_oidc_jwt_role_bindings(client: hvac.Client, auth_path: str) -> Dict[str, Any]:
    """Retrieve OIDC/JWT auth method role bindings."""
    roles_data = {"roles": [], "errors": []}

    logger.debug(f"Retrieving OIDC/JWT roles for auth path: {auth_path}")

    try:
        # List roles for OIDC/JWT auth method
        roles_list_path = f"auth/{auth_path.rstrip('/')}/role"
        logger.debug(f"Listing OIDC/JWT roles at path: {roles_list_path}")
        roles_response = client.list(roles_list_path)
        logger.debug(f"Raw OIDC/JWT roles list response: {roles_response}")

        if roles_response and "data" in roles_response and "keys" in roles_response["data"]:
            role_names = roles_response["data"]["keys"]
            logger.debug(f"Found {len(role_names)} OIDC/JWT roles: {role_names}")

            for role_name in role_names:
                try:
                    role_response = client.read(f"auth/{auth_path.rstrip('/')}/role/{role_name}")
                    if role_response and "data" in role_response:
                        role_data = role_response["data"]

                        role_info = {
                            "name": role_name,
                            "type": "oidc_jwt_role",
                            "bound_audiences": role_data.get("bound_audiences", []),
                            "bound_subject": role_data.get("bound_subject", ""),
                            "bound_claims": role_data.get("bound_claims", {}),
                            "user_claim": role_data.get("user_claim", ""),
                            "groups_claim": role_data.get("groups_claim", ""),
                            "token_policies": role_data.get("token_policies", []),
                            "token_ttl": role_data.get("token_ttl", 0),
                            "token_max_ttl": role_data.get("token_max_ttl", 0),
                        }

                        logger.debug(f"OIDC/JWT role '{role_name}' details:")
                        logger.debug(f"  - Bound audiences: {role_info['bound_audiences']}")
                        logger.debug(f"  - Bound subject: {role_info['bound_subject']}")
                        logger.debug(f"  - Bound claims: {role_info['bound_claims']}")
                        logger.debug(f"  - User claim: {role_info['user_claim']}")
                        logger.debug(f"  - Groups claim: {role_info['groups_claim']}")
                        logger.debug(f"  - Token policies: {role_info['token_policies']}")

                        roles_data["roles"].append(role_info)

                except Exception as e:
                    logger.error(f"Error retrieving OIDC/JWT role '{role_name}': {e}")
                    roles_data["errors"].append(
                        f"Error retrieving OIDC/JWT role '{role_name}': {str(e)}"
                    )
        else:
            logger.debug("No OIDC/JWT roles found or unable to list roles")

    except Exception as e:
        logger.error(f"Error listing OIDC/JWT roles: {e}")
        roles_data["errors"].append(f"Error listing OIDC/JWT roles: {str(e)}")

    return roles_data


def _get_approle_role_bindings(client: hvac.Client, auth_path: str) -> Dict[str, Any]:
    """Retrieve AppRole auth method role bindings."""
    roles_data = {"roles": [], "errors": []}

    logger.debug(f"Retrieving AppRole roles for auth path: {auth_path}")

    try:
        # List roles for AppRole auth method
        roles_list_path = f"auth/{auth_path.rstrip('/')}/role"
        logger.debug(f"Listing AppRole roles at path: {roles_list_path}")
        roles_response = client.list(roles_list_path)
        logger.debug(f"Raw AppRole roles list response: {roles_response}")

        if roles_response and "data" in roles_response and "keys" in roles_response["data"]:
            role_names = roles_response["data"]["keys"]
            logger.debug(f"Found {len(role_names)} AppRole roles: {role_names}")

            for role_name in role_names:
                try:
                    role_response = client.read(f"auth/{auth_path.rstrip('/')}/role/{role_name}")
                    if role_response and "data" in role_response:
                        role_data = role_response["data"]

                        role_info = {
                            "name": role_name,
                            "type": "approle",
                            "bind_secret_id": role_data.get("bind_secret_id", True),
                            "bound_cidr_list": role_data.get("bound_cidr_list", []),
                            "token_policies": role_data.get("token_policies", []),
                            "token_ttl": role_data.get("token_ttl", 0),
                            "token_max_ttl": role_data.get("token_max_ttl", 0),
                            "secret_id_ttl": role_data.get("secret_id_ttl", 0),
                        }

                        logger.debug(f"AppRole role '{role_name}' details:")
                        logger.debug(f"  - Bind secret ID: {role_info['bind_secret_id']}")
                        logger.debug(f"  - Bound CIDR list: {role_info['bound_cidr_list']}")
                        logger.debug(f"  - Token policies: {role_info['token_policies']}")
                        logger.debug(f"  - Secret ID TTL: {role_info['secret_id_ttl']}")

                        # Security analysis
                        if not role_info["bind_secret_id"]:
                            logger.debug(
                                f"    * WARNING: Role '{role_name}' does not require secret ID"
                            )
                        if not role_info["bound_cidr_list"]:
                            logger.debug(
                                f"    * NOTICE: Role '{role_name}' has no CIDR restrictions"
                            )

                        roles_data["roles"].append(role_info)

                except Exception as e:
                    logger.error(f"Error retrieving AppRole role '{role_name}': {e}")
                    roles_data["errors"].append(
                        f"Error retrieving AppRole role '{role_name}': {str(e)}"
                    )
        else:
            logger.debug("No AppRole roles found or unable to list roles")

    except Exception as e:
        logger.error(f"Error listing AppRole roles: {e}")
        roles_data["errors"].append(f"Error listing AppRole roles: {str(e)}")

    return roles_data


def get_namespace_info(client: hvac.Client, namespace: str) -> Dict[str, Any]:
    """Get basic information about the namespace.

    Args:
        client: The Vault client instance
        namespace: The namespace name

    Returns:
        Dict containing namespace information
    """
    namespace_info = {"name": namespace, "timestamp": None, "errors": []}

    try:
        # Get current time for timestamp
        from datetime import datetime

        namespace_info["timestamp"] = datetime.now().isoformat()

        # Try to get namespace metadata if available
        try:
            # This might not be available in all Vault versions
            namespace_response = client.sys.read_namespace(namespace=namespace)
            if namespace_response and "data" in namespace_response:
                namespace_info["metadata"] = namespace_response["data"]
        except Exception as e:
            logger.debug(f"Could not retrieve namespace metadata: {e}")
            # This is not critical, so we don't add to errors

    except Exception as e:
        logger.error(f"Error getting namespace info: {e}")
        namespace_info["errors"].append(f"Error getting namespace info: {str(e)}")

    return namespace_info


def perform_namespace_review(namespace: str, debug: bool = False) -> Dict[str, Any]:
    """Perform a comprehensive review of the specified Vault namespace.

    Args:
        namespace: The namespace to review
        debug: Whether to enable debug logging

    Returns:
        Dict containing the complete review results
    """
    logger.info(f"Starting Vault namespace review for: {namespace}")
    logger.debug(f"Debug mode enabled: {debug}")

    review_results = {
        "namespace_info": {},
        "policies": {},
        "groups": {},
        "auth_methods": {},
        "role_bindings": {},
        "summary": {
            "total_policies": 0,
            "total_groups": 0,
            "total_auth_methods": 0,
            "total_roles": 0,
            "errors": [],
        },
    }

    try:
        # Create and authenticate client using vault_utils
        logger.debug(f"Creating Vault client for namespace: {namespace}")
        client = create_vault_client(namespace=namespace, verify=False)
        logger.debug("Vault client created and authenticated successfully")

        # Get current token information for debugging
        logger.debug("Retrieving current token information...")
        token_info = get_token_info(client)
        if token_info:
            logger.debug("Token information retrieved successfully")
        else:
            logger.debug("Warning: Could not retrieve token information")

        # Get namespace information
        logger.debug("Retrieving namespace information...")
        review_results["namespace_info"] = get_namespace_info(client, namespace)
        logger.debug("Namespace information retrieval completed")

        # Get policies
        logger.info("Retrieving policies...")
        logger.debug("=== STARTING POLICY RETRIEVAL PHASE ===")
        policies_data = get_policies(client)
        review_results["policies"] = policies_data
        review_results["summary"]["total_policies"] = len(policies_data.get("policies", []))
        logger.debug(
            f"=== POLICY RETRIEVAL PHASE COMPLETED: {review_results['summary']['total_policies']} policies found ==="
        )

        # Get groups
        logger.info("Retrieving groups...")
        logger.debug("=== STARTING GROUPS RETRIEVAL PHASE ===")
        groups_data = get_groups(client)
        review_results["groups"] = groups_data
        review_results["summary"]["total_groups"] = len(groups_data.get("groups", []))
        logger.debug(
            f"=== GROUPS RETRIEVAL PHASE COMPLETED: {review_results['summary']['total_groups']} groups found ==="
        )

        # Get auth methods
        logger.info("Retrieving authentication methods...")
        logger.debug("=== STARTING AUTH METHODS RETRIEVAL PHASE ===")
        auth_methods_data = get_auth_methods(client)
        review_results["auth_methods"] = auth_methods_data
        review_results["summary"]["total_auth_methods"] = len(
            auth_methods_data.get("auth_methods", [])
        )
        logger.debug(
            f"=== AUTH METHODS RETRIEVAL PHASE COMPLETED: {review_results['summary']['total_auth_methods']} auth methods found ==="
        )

        # Get role bindings for auth methods
        logger.info("Retrieving authentication role bindings...")
        logger.debug("=== STARTING ROLE BINDINGS RETRIEVAL PHASE ===")
        role_bindings_data = get_auth_role_bindings(
            client, auth_methods_data.get("auth_methods", [])
        )
        review_results["role_bindings"] = role_bindings_data

        # Calculate total roles across all auth methods
        total_roles = sum(
            len(rb.get("roles", [])) for rb in role_bindings_data.get("role_bindings", [])
        )
        review_results["summary"]["total_roles"] = total_roles
        logger.debug(
            f"=== ROLE BINDINGS RETRIEVAL PHASE COMPLETED: {total_roles} roles found across all auth methods ==="
        )

        # Collect all errors
        all_errors = []
        all_errors.extend(policies_data.get("errors", []))
        all_errors.extend(groups_data.get("errors", []))
        all_errors.extend(auth_methods_data.get("errors", []))
        all_errors.extend(role_bindings_data.get("errors", []))
        # Also collect errors from individual role binding sections
        for rb in role_bindings_data.get("role_bindings", []):
            all_errors.extend(rb.get("errors", []))
        review_results["summary"]["errors"] = all_errors

        # Enhanced summary logging
        logger.info(
            f"Namespace review completed. Found {review_results['summary']['total_policies']} policies, "
            f"{review_results['summary']['total_groups']} groups, "
            f"{review_results['summary']['total_auth_methods']} auth methods, "
            f"{review_results['summary']['total_roles']} role bindings"
        )

        logger.debug("=== NAMESPACE REVIEW SUMMARY ===")
        logger.debug(f"Namespace: {namespace}")
        logger.debug(f"Total policies: {review_results['summary']['total_policies']}")
        logger.debug(f"Total groups: {review_results['summary']['total_groups']}")
        logger.debug(f"Total auth methods: {review_results['summary']['total_auth_methods']}")
        logger.debug(f"Total role bindings: {review_results['summary']['total_roles']}")
        logger.debug(f"Total errors: {len(all_errors)}")

        if all_errors:
            logger.warning(f"Completed with {len(all_errors)} errors")
            logger.debug("Error details:")
            for i, error in enumerate(all_errors, 1):
                logger.debug(f"  {i}. {error}")
        else:
            logger.debug("No errors encountered during review")

    except Exception as e:
        logger.error(f"Fatal error during namespace review: {e}")
        logger.debug(f"Fatal exception details: {type(e).__name__}: {str(e)}", exc_info=True)
        review_results["summary"]["errors"].append(f"Fatal error: {str(e)}")

    logger.debug("=== NAMESPACE REVIEW PROCESS COMPLETED ===")
    return review_results
