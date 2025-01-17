import hvac
import os
import click
import logging
from typing import Optional, List, Dict, Any, Union
from pick import pick

# Configure logging with more detailed format
logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG level for more detailed information
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

# Create a specific logger for hvac client operations
hvac_logger = logging.getLogger('hvac.client')
hvac_logger.setLevel(logging.DEBUG)

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

@click.command()
@click.option('--url', default=None, help='Vault server URL')
@click.option('--token', default=None, help='Vault token or path to token file')
@click.option('--username', default=None, help='Username for Vault login')
@click.option('--path', default=None, help='Starting path for traversal')
@click.option('--mount-point', default="", help='KV store mount point')
@click.option('--namespace', default=None, help='Vault namespace')
@click.option('--cert', default=None, help='Path to SSL certificate (PEM) file for verification')
@click.option('--show-token-info', is_flag=True, help='Show detailed token information and permissions')
def main(url: Optional[str], token: Optional[str], username: Optional[str], 
         path: Optional[str], mount_point: str, namespace: Optional[str], 
         cert: Optional[str], show_token_info: bool = False) -> None:
    """
    Main entry point for Vault path traversal tool.
    
    Args:
        url: Vault server URL
        token: Vault token or path to token file
        username: Username for Vault login
        path: Starting path for traversal
        mount_point: KV store mount point
        namespace: Vault namespace
        cert: Path to SSL certificate (PEM) file for verification
        show_token_info: Flag to show detailed token information
    """
    # Setup Vault client
    client = setup_vault_client(url, token, username, namespace, cert)
    if not client:
        return

    # Show token information if requested
    if show_token_info:
        display_token_info(client)
        if not path:  # If no path specified, exit after showing token info
            return

    if path:
        if not validate_path_access(client, path, mount_point):
            click.echo(f"Unable to access path: {path}")
            click.echo("Please verify:")
            click.echo("1. The path exists and is a valid KV v2 secrets path")
            click.echo("2. Your token has the required permissions")
            click.echo("3. The namespace is correct (if using namespaces)")
            return
        vaults = [(mount_point, path.rstrip('/'))]
    else:
        try:
            mounts = client.sys.list_mounted_secrets_engines()['data']
            vaults = []
            for mount, details in mounts.items():
                if details['type'] == 'kv' and details.get('options', {}).get('version') == '2':
                    mount_path = mount.rstrip('/')
                    if validate_path_access(client, "", mount_path):
                        vaults.append((mount_path, ""))
                    else:
                        logger.info(f"Skipping inaccessible mount: {mount}")
            
            if not vaults:
                click.echo("No accessible KV v2 secret mounts found.")
                click.echo("Please verify your token has the required permissions.")
                return
                
        except Exception as e:
            if "permission denied" in str(e).lower():
                logger.error("Permission denied when listing secret engines. Please check your token permissions.")
            else:
                logger.error(f"Error listing secret engines: {str(e)}")
            return

    # Traverse each vault
    for mount_point, start_path in vaults:
        logger.info(f"Traversing mount point: {mount_point or 'default'}")
        traverse(client, start_path, mount_point)


def setup_vault_client(url: Optional[str], token: Optional[str], 
                      username: Optional[str], namespace: Optional[str],
                      cert: Optional[str]) -> Optional[hvac.Client]:
    """
    Set up and authenticate the Vault client.
    
    Args:
        url: Vault server URL
        token: Vault token or path to token file
        username: Username for Vault login
        namespace: Vault namespace
        cert: Path to SSL certificate (PEM) file for verification
    
    Returns:
        hvac.Client: Authenticated Vault client or None if setup fails
    """
    if url is None:
        url = os.environ.get('VAULT_ADDR')
    if token is None:
        token = os.environ.get('VAULT_TOKEN')
    if namespace is None:
        namespace = os.environ.get('VAULT_NAMESPACE')
    if cert is None:
        cert = os.environ.get('VAULT_CACERT')
    
    # Debug logging for configuration
    logger.debug("Vault Configuration:")
    logger.debug(f"URL: {url}")
    logger.debug(f"Token Source: {'Environment' if token == os.environ.get('VAULT_TOKEN') else 'Command Line/File'}")
    logger.debug(f"Token: {debug_token(token) if token else 'None'}")
    logger.debug(f"Namespace: {namespace}")
    logger.debug(f"Certificate: {cert}")

    if not url:
        logger.error("Vault URL must be provided either as an argument or in the VAULT_ADDR environment variable.")
        return None

    try:
        verify: Union[bool, str] = True
        if cert:
            if not os.path.isfile(cert):
                logger.error(f"SSL certificate file not found: {cert}")
                return None
            verify = cert
            logger.info(f"Using SSL certificate for verification: {cert}")

        logger.debug("Creating Vault client with URL: %s, Namespace: %s", url, namespace)
        client = hvac.Client(url=url, namespace=namespace, verify=verify)

        if token:
            if os.path.isfile(token):
                logger.debug("Reading token from file: %s", token)
                with open(token, 'r') as f:
                    token = f.read().strip()
                logger.debug("Token read from file: %s", debug_token(token))
            client.token = token
            logger.debug("Token set in client: %s", debug_token(client.token))
        elif username:
            logger.debug("Attempting login with username: %s", username)
            # Prompt for password securely
            password = click.prompt("Enter your Vault password", hide_input=True)
            # Attempt to login and get a token
            try:
                login_response = client.auth.userpass.login(username, password)
                client.token = login_response['auth']['client_token']
                logger.debug("Successfully logged in with username, received token: %s", 
                           debug_token(client.token))
            except Exception as e:
                logger.error("Failed to login with username/password: %s", str(e))
                return None
        else:
            logger.error("Either a token or username must be provided.")
            return None

        # Verify authentication
        try:
            is_authenticated = client.is_authenticated()
            logger.debug("Authentication check result: %s", is_authenticated)
            if not is_authenticated:
                logger.error("Failed to authenticate with Vault - token validation failed")
                return None
            
            # Additional token validation
            try:
                token_info = client.auth.token.lookup_self()
                logger.debug("Token validation successful:")
                logger.debug("Token display name: %s", token_info.get('display_name'))
                logger.debug("Token policies: %s", token_info.get('policies', []))
                logger.debug("Token TTL: %s seconds", token_info.get('ttl'))
            except Exception as e:
                logger.error("Failed to lookup token details: %s", str(e))
                return None
                
        except Exception as e:
            logger.error("Error during authentication check: %s", str(e))
            return None
        
        return client
    except Exception as e:
        logger.error("Error connecting to Vault: %s", str(e))
        return None


def get_secret_data(client: hvac.Client, path: str, mount_point: str) -> Optional[Dict[str, Any]]:
    """
    Get secret data from a specific path in Vault.
    
    Args:
        client: Authenticated Vault client
        path: Full path to the secret
        mount_point: The mount point of the KV store
        
    Returns:
        Optional[Dict[str, Any]]: Secret data if successful, None otherwise
    """
    try:
        secret = client.secrets.kv.v2.read_secret_version(path=path, mount_point=mount_point)
        return secret['data']['data']
    except Exception as e:
        logger.error(f"Error reading secret at {path}: {str(e)}")
        return None


def collect_secrets(client: hvac.Client, path: str, mount_point: str, secrets_list: List[str]) -> None:
    """
    Recursively collect all secret paths in Vault.
    
    Args:
        client: Authenticated Vault client
        path: Current path to traverse
        mount_point: The mount point of the KV store
        secrets_list: List to store found secret paths
    """
    try:
        # Try to read data at current path
        try:
            data = client.secrets.kv.v2.read_secret(path=path, mount_point=mount_point)
            if data and path:  # Don't add root path as a secret
                secrets_list.append(path)
        except hvac.exceptions.InvalidPath:
            pass  # Path might be a directory only

        # List subdirectories and secrets
        try:
            response = client.secrets.kv.v2.list_secrets(path=path, mount_point=mount_point)
            items = response.get('data', {}).get('keys', [])
            for item in items:
                # Use proper path joining that works with URLs
                full_path = f"{path}/{item}".strip("/") if path else item
                if item.endswith('/'):
                    # Remove trailing slash for consistency
                    collect_secrets(client, full_path.rstrip('/'), mount_point, secrets_list)
                else:
                    # Check if this is a secret
                    try:
                        client.secrets.kv.v2.read_secret(path=full_path, mount_point=mount_point)
                        secrets_list.append(full_path)
                    except hvac.exceptions.InvalidPath:
                        pass
        except hvac.exceptions.InvalidPath:
            pass
    except Exception as e:
        logger.error(f"Error listing secrets at {path}: {str(e)}")


def traverse(client: hvac.Client, path: str, mount_point: str) -> None:
    """
    Recursively traverse Vault paths and list secrets.
    
    Args:
        client: Authenticated Vault client
        path: Path to traverse in Vault
        mount_point: The mount point of the KV store
    """
    try:
        # Try to read data at current path
        try:
            data = client.secrets.kv.v2.read_secret(path=path, mount_point=mount_point)
            if data:
                logger.info(f"Found secret at: {path}")
        except hvac.exceptions.InvalidPath:
            pass

        # List subdirectories and secrets
        try:
            response = client.secrets.kv.v2.list_secrets(path=path, mount_point=mount_point)
            secrets = response.get('data', {}).get('keys', [])
            
            for secret in secrets:
                # Use proper path joining that works with URLs
                full_path = f"{path}/{secret}".strip("/") if path else secret
                if secret.endswith('/'):
                    traverse(client, full_path.rstrip('/'), mount_point)
                else:
                    try:
                        client.secrets.kv.v2.read_secret(path=full_path, mount_point=mount_point)
                        logger.info(f"Found secret at: {full_path}")
                    except hvac.exceptions.InvalidPath:
                        pass
        except hvac.exceptions.InvalidPath:
            pass
    except Exception as e:
        logger.error(f"Error listing secrets at {path}: {str(e)}")


def validate_path_access(client: hvac.Client, path: str, mount_point: str = "") -> bool:
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
        # Try to list the path first
        try:
            client.secrets.kv.v2.list_secrets(path=path, mount_point=mount_point)
            return True
        except hvac.exceptions.InvalidPath:
            # If listing fails, try to read data
            try:
                client.secrets.kv.v2.read_secret(path=path, mount_point=mount_point)
                return True
            except hvac.exceptions.InvalidPath:
                logger.warning(f"Path does not exist or is not a valid KV v2 path: {path}")
                return False
    except Exception as e:
        if "permission denied" in str(e).lower():
            logger.warning(f"Permission denied for path: {path}")
        else:
            logger.error(f"Error accessing path {path}: {str(e)}")
        return False


def display_token_info(client: hvac.Client) -> None:
    """
    Display information about the current token including its policies and metadata.
    
    Args:
        client: Authenticated Vault client
    """
    try:
        # Get token information
        token_info = client.auth.token.lookup_self()
        
        click.echo("\nToken Information:")
        click.echo("-" * 50)
        
        # Display basic token info
        click.echo(f"Display Name: {token_info.get('display_name', 'N/A')}")
        click.echo(f"Token Type: {token_info.get('type', 'N/A')}")
        click.echo(f"Token TTL: {token_info.get('ttl', 'N/A')} seconds")
        
        # Display policies
        policies = token_info.get('policies', [])
        click.echo("\nPolicies:")
        if policies:
            for policy in policies:
                click.echo(f"  - {policy}")
                try:
                    # Try to get policy details
                    policy_info = client.sys.read_policy(policy)
                    if policy_info and 'rules' in policy_info:
                        click.echo("    Permissions:")
                        rules = policy_info['rules'].split('\n')
                        for rule in rules:
                            if rule.strip():
                                click.echo(f"      {rule.strip()}")
                except Exception:
                    # Skip policy details if we can't read them
                    continue
        else:
            click.echo("  No policies attached")
        
        # Display metadata if any
        metadata = token_info.get('metadata', {})
        if metadata:
            click.echo("\nMetadata:")
            for key, value in metadata.items():
                click.echo(f"  {key}: {value}")
        
        # Display token capabilities for current path
        try:
            capabilities = client.auth.token.lookup_self()['data']['capabilities']
            click.echo("\nToken Capabilities:")
            for cap in capabilities:
                click.echo(f"  - {cap}")
        except Exception:
            click.echo("\nUnable to retrieve token capabilities")
            
    except Exception as e:
        logger.error(f"Error retrieving token information: {str(e)}")
        click.echo("Unable to retrieve token information. Please check your permissions.")


if __name__ == "__main__":
    main()