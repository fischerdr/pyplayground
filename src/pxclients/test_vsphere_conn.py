#!/usr/bin/env python3
"""Test vSphere Connection Script.

This script attempts to connect to vSphere using configuration retrieved
from Kubernetes secrets and CRDs, mirroring the logic in parse_clouddrive_map.py.
It helps isolate issues related to vSphere connectivity.
"""

import base64
import logging
import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Optional

import click
from kubernetes import client

# Assume utils are in the python path or adjust import accordingly
from utils.k8s_utils import (
    get_custom_objects_api,
    get_k8s_client,
    load_kube_config_auto,
)
from utils.logging_utils import get_logger, setup_logging
from utils.vmware_utils import connect  # Import the connect function to test

# Configure logging
logger = get_logger(__name__)


# --- Copied from parse_clouddrive_map.py ---
@dataclass
class VSphereConfig:
    """vSphere connection configuration."""

    host: str
    username: str
    password: str
    port: int = 443
    disable_ssl_verification: bool = True

    def to_args(self) -> object:
        """Convert config to args for vmware_utils.connect()."""
        args = SimpleNamespace()
        args.host = self.host
        args.user = self.username
        args.password = self.password
        args.port = self.port
        args.disable_ssl_verification = self.disable_ssl_verification
        return args


# TODO: Reduce complexity (currently McCabe complexity 15) - Consider refactoring K8s calls
def get_vsphere_config(namespace: str, verify_ssl: bool) -> Optional[VSphereConfig]:  # noqa: C901
    """Get vSphere configuration from Kubernetes secrets. (Copied from parse_clouddrive_map.py)."""
    logger.debug("Attempting to get vSphere config from namespace: %s", namespace)
    vcenter = None
    username = None
    password = None

    try:
        v1 = get_k8s_client()

        # Step 2.1: Get vSphere credentials from Secret
        try:
            secret_name = "px-vsphere-secret"
            logger.debug("Reading secret '%s'...", secret_name)
            secret = v1.read_namespaced_secret(secret_name, namespace)
            username = base64.b64decode(secret.data["VSPHERE_USER"]).decode().strip()
            password = base64.b64decode(secret.data["VSPHERE_PASSWORD"]).decode().strip()
            logger.debug("Successfully decoded and stripped vSphere username from secret.")
        except client.ApiException as e:
            logger.error("K8s API error reading secret '%s': %s", secret_name, str(e))
            return None
        except KeyError as e:
            logger.error("Secret '%s' is missing expected key: %s", secret_name, str(e))
            return None
        except Exception as e:
            logger.error("Failed processing secret '%s': %s", secret_name, str(e), exc_info=True)
            return None

        # Step 2.2: Get vCenter URL from StorageCluster CRD
        try:
            custom_api = get_custom_objects_api()
            storage_cluster_group = "core.libopenstorage.org"
            storage_cluster_version = "v1"
            storage_cluster_plural = "storageclusters"
            logger.debug(
                "Listing StorageClusters (group=%s, version=%s, plural=%s)...",
                storage_cluster_group,
                storage_cluster_version,
                storage_cluster_plural,
            )
            storage_clusters = custom_api.list_namespaced_custom_object(
                group=storage_cluster_group,
                version=storage_cluster_version,
                namespace=namespace,
                plural=storage_cluster_plural,
            )

            vcenter = None
            logger.debug("Searching for VSPHERE_VCENTER env var in StorageClusters...")
            for cluster in storage_clusters.get("items", []):
                cluster_name_debug = cluster.get("metadata", {}).get("name", "Unknown")
                logger.debug("Checking StorageCluster: %s", cluster_name_debug)
                env = cluster.get("spec", {}).get("env", [])
                for param in env:
                    if param.get("name") == "VSPHERE_VCENTER":
                        vcenter = param.get("value")
                        logger.debug(
                            "Found VSPHERE_VCENTER=%s in StorageCluster %s",
                            vcenter,
                            cluster_name_debug,
                        )
                        break
                if vcenter:
                    break

            if not vcenter:
                logger.error(
                    "Could not find VSPHERE_VCENTER in any StorageCluster in namespace '%s'",
                    namespace,
                )
                return None
        except client.ApiException as e:
            logger.error("K8s API error listing StorageClusters: %s", str(e))
            return None
        except Exception as e:
            logger.error("Failed processing StorageClusters: %s", str(e), exc_info=True)
            return None

        # Step 2.3: Create and return VSphereConfig object
        disable_verification = not verify_ssl
        logger.debug("vSphere SSL verification %s", "enabled" if verify_ssl else "disabled")

        config = VSphereConfig(
            host=vcenter,
            username=username,
            password=password,  # Note: Password will not be logged
            disable_ssl_verification=disable_verification,
        )
        logger.debug(
            "Created VSphereConfig: host=%s, user=%s, port=%d, disable_ssl=%s",
            config.host,
            config.username,
            config.port,
            config.disable_ssl_verification,
        )
        return config

    except Exception as e:  # General fallback catcher
        logger.error(
            "Unexpected outer error in get_vsphere_config for namespace '%s': %s",
            namespace,
            str(e),
            exc_info=True,
        )
        return None


# --- End of copied code ---


@click.command()
@click.option(
    "--namespace",
    "-n",
    default="kube-system",
    help="Kubernetes namespace containing the StorageCluster.",
    show_default=True,
)
@click.option(
    "--portworx-namespace",
    "-p",
    default="portworx",
    help="Kubernetes namespace containing the vSphere secret (px-vsphere-secret).",
    show_default=True,
)
@click.option(
    "--kubeconfig",
    "-k",
    default=None,
    help="Path to the kubeconfig file to use.",
    type=click.Path(exists=True, dir_okay=False, readable=True),
)
@click.option(
    "--vsphere-ssl-verify",
    is_flag=True,
    default=False,  # Default is NOT to verify (disable_ssl_verification=True)
    help="Enable SSL verification for vSphere connection.",
)
@click.option(
    "--debug",
    "-d",
    is_flag=True,
    default=False,
    help="Enable debug logging (DEBUG level).",
)
def test_connection(
    namespace: str,
    portworx_namespace: str,
    kubeconfig: Optional[str],
    vsphere_ssl_verify: bool,
    debug: bool,
):
    """Test connection to vSphere using K8s-derived credentials."""
    # Setup Logging
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    # Note: If run standalone, logs might go to a different dir/file than main script
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Starting vSphere connection test.")

    # Load Kubeconfig
    logger.info("Loading Kubernetes configuration...")
    if not load_kube_config_auto(config_file=kubeconfig):
        logger.error("Failed to load Kubernetes configuration.")
        click.echo("ERROR: Failed to load Kubernetes configuration.", err=True)
        raise click.Abort()
    logger.info("Kubernetes configuration loaded successfully.")

    # Get vSphere Config from K8s
    logger.info(f"Retrieving vSphere connection details from namespace '{portworx_namespace}'...")
    vsphere_config = get_vsphere_config(portworx_namespace, vsphere_ssl_verify)

    if not vsphere_config:
        logger.error("Failed to retrieve vSphere configuration from Kubernetes.")
        click.echo("ERROR: Failed to retrieve vSphere configuration from Kubernetes.", err=True)
        raise click.Abort()
    logger.info(f"Successfully retrieved vSphere config details for host: {vsphere_config.host}")
    click.echo(f"Retrieved config for vSphere host: {vsphere_config.host}")

    # Prepare args for connect()
    connect_args = vsphere_config.to_args()
    logger.debug(
        "Attempting vSphere connection with args: host=%s, user=%s, port=%d, disable_ssl=%s",
        connect_args.host,
        connect_args.user,  # Username logged here
        connect_args.port,
        connect_args.disable_ssl_verification,
    )
    click.echo(f"Attempting connection to {connect_args.host}...")

    # --- Perform Connection Test ---
    si = None
    try:
        si = connect(connect_args)  # Call the function from vmware_utils

        if si:
            # Connection successful
            success_msg = f"Successfully connected to vSphere: {vsphere_config.host}"
            logger.info(success_msg)
            click.echo(click.style(f"SUCCESS: {success_msg}", fg="green"))

            # Optional: Further test with CurrentTime
            try:
                server_time = si.CurrentTime()
                time_msg = f"vSphere server time: {server_time}"
                logger.info(time_msg)
                click.echo(f"  -> Server time check successful: {server_time}")
            except Exception as time_e:
                warn_msg = f"Connected, but failed to get server time: {time_e}"
                logger.warning(warn_msg)
                click.echo(click.style(f"  -> WARNING: {warn_msg}", fg="yellow"))

        else:
            # connect() returned None, indicating failure
            fail_msg = (
                f"Failed to connect to vSphere: {vsphere_config.host}. Check logs for details."
            )
            logger.error(fail_msg)
            click.echo(click.style(f"FAILED: {fail_msg}", fg="red"), err=True)

    except Exception as conn_e:
        # Catch any unexpected errors during the connect call itself
        fail_msg = f"An unexpected error occurred during the connect attempt: {conn_e}"
        logger.error(fail_msg, exc_info=True)
        click.echo(click.style(f"FAILED: {fail_msg}", fg="red"), err=True)


if __name__ == "__main__":
    test_connection()
