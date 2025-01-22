import logging
import os
from typing import Any, Dict, List, Optional, Union

import click
import hvac
from pick import pick

from utils.vault_utils import (
    collect_secrets,
    create_vault_client,
    get_token_info,
    validate_path_access,
)

# Configure logging with more detailed format
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",  # Set to DEBUG level for more detailed information
)
logger = logging.getLogger(__name__)

# Create a specific logger for hvac client operations
hvac_logger = logging.getLogger("hvac.client")
hvac_logger.setLevel(logging.DEBUG)


@click.command()
@click.option("--url", default=None, help="Vault server URL")
@click.option("--token", default=None, help="Vault token or path to token file")
@click.option("--username", default=None, help="Username for Vault login")
@click.option("--path", default=None, help="Starting path for traversal")
@click.option("--mount-point", default="", help="KV store mount point")
@click.option("--namespace", default=None, help="Vault namespace")
@click.option("--cert", default=None, help="Path to SSL certificate (PEM) file for verification")
@click.option(
    "--show-token-info", is_flag=True, help="Show detailed token information and permissions"
)
def main(
    url: Optional[str],
    token: Optional[str],
    username: Optional[str],
    path: Optional[str],
    mount_point: str,
    namespace: Optional[str],
    cert: Optional[str],
    show_token_info: bool = False,
) -> None:
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
    try:
        # Create Vault client
        client = create_vault_client(url=url, token=token, namespace=namespace, verify=cert)

        # Show token information if requested
        if show_token_info:
            token_info = get_token_info(client)
            if token_info:
                click.echo("\nToken Information:")
                click.echo("-" * 20)
                for key, value in token_info.items():
                    click.echo(f"{key}: {value}")
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
            vaults = [(mount_point, path.rstrip("/"))]
        else:
            try:
                mounts = client.sys.list_mounted_secrets_engines()["data"]
                vaults = []
                for mount, details in mounts.items():
                    if details["type"] == "kv" and details.get("options", {}).get("version") == "2":
                        mount_path = mount.rstrip("/")
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
                    logger.error(
                        "Permission denied when listing secret engines. Please check your token permissions."
                    )
                else:
                    logger.error(f"Error listing secret engines: {str(e)}")
                return

        # Traverse each vault mount point
        for mount_point, base_path in vaults:
            secrets_list: List[str] = []
            collect_secrets(client, base_path, mount_point, secrets_list)

            if secrets_list:
                click.echo(f"\nSecrets found in {mount_point}:")
                for secret_path in secrets_list:
                    click.echo(f"  {secret_path}")
            else:
                click.echo(f"\nNo secrets found in {mount_point}")

    except Exception as e:
        logger.error(f"Error during vault traversal: {str(e)}")
        return


if __name__ == "__main__":
    main()
