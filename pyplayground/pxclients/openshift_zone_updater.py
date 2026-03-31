#!/usr/bin/env python3
"""OpenShift Portworx Zone Label Updater.

This script updates the topology.portworx.io/zone label across OpenShift resources
(MachineSets, Machines, and Nodes) based on the ESXi host cluster name extracted
from the MachineSet's resourcePool configuration.

Label Propagation Order:
1. MachineSet (spec.template.spec.metadata.labels)
2. Machine (spec.metadata.labels)
3. Node (metadata.labels)

Usage:
    # Default behavior (live mode)
    python openshift_zone_updater.py

    # Dry-run mode
    python openshift_zone_updater.py --dry-run

    # With custom kubeconfig
    python openshift_zone_updater.py --kubeconfig /path/to/kubeconfig
"""

import logging
import os

import click
from rich.console import Console

from pyplayground.utils import get_logger, setup_logging
from pyplayground.utils.k8s_utils import (
    get_all_machinesets,
    get_machines_for_machineset,
    get_machineset_resource_pool,
    get_nodes_for_machines,
    load_kube_config_auto,
    parse_resource_pool_path,
    update_zone_label,
)

logger = get_logger(__name__)

console = Console()

# Constants
NAMESPACE = "openshift-machine-api"
ZONE_LABEL_KEY = "topology.portworx.io/zone"


def confirm_update(
    resource_type: str,
    resource_name: str,
    existing_value: str,
    new_value: str,
) -> bool:
    """Ask user for confirmation to proceed with label update.

    Args:
        resource_type: Type of resource (MachineSet, Machine, Node)
        resource_name: Name of the resource
        existing_value: Current label value
        new_value: New label value to apply

    Returns:
        True if user confirms, False otherwise

    Examples:
        >>> # User types 'y'
        >>> confirm_update('MachineSet', 'test-ms', 'old', 'new')
        True
        >>> # User types 'n'
        >>> confirm_update('MachineSet', 'test-ms', 'old', 'new')
        False
    """
    console.print("\n[yellow]WARNING: Label mismatch detected[/yellow]")
    console.print(f"   Resource: {resource_type} '{resource_name}'")
    console.print(f"   Current value: {existing_value}")
    console.print(f"   New value: {new_value}")
    response = input("Continue with update? (y/N): ")
    return response.lower() == "y"


def get_kubeconfig_path(kubeconfig: str | None) -> str | None:
    """Get the kubeconfig path to use for cluster connection.

    Args:
        kubeconfig: Optional custom kubeconfig path

    Returns:
        Path to the kubeconfig file, or None if not found
    """
    if kubeconfig:
        logger.info("Using custom kubeconfig at %s", kubeconfig)
        return kubeconfig

    logger.info("Using default kubeconfig location")
    return None


def connect_to_cluster(kubeconfig: str | None) -> bool:
    """Connect to the OpenShift cluster using the provided kubeconfig.

    Args:
        kubeconfig: Path to the kubeconfig file

    Returns:
        True if connection succeeded, False otherwise
    """
    try:
        if not load_kube_config_auto(config_file=kubeconfig):
            logger.error("Failed to load Kubernetes configuration")
            return False
        logger.info("Successfully connected to OpenShift cluster")
        return True
    except Exception as e:
        logger.error("Failed to load Kubernetes config: %s", e)
        return False


def process_machineset(
    machineset: dict,
    dry_run: bool,
) -> bool:
    """Process a single MachineSet: update labels and propagate to Machines and Nodes.

    Args:
        machineset: The MachineSet resource dictionary
        dry_run: If True, only show what would be changed

    Returns:
        True if processing succeeded, False otherwise
    """
    resource_name = machineset["metadata"]["name"]

    # Extract ESXi host cluster name from resourcePool
    resource_pool = get_machineset_resource_pool(machineset)

    if not resource_pool:
        logger.error(
            "MachineSet %s has no resourcePool configured",
            resource_name,
        )
        return False

    new_zone_value = parse_resource_pool_path(resource_pool)
    logger.info(
        "Processing MachineSet %s: ESXi host cluster = %s",
        resource_name,
        new_zone_value,
    )

    # Step 1: Update MachineSet labels
    if not update_zone_label(
        machineset,
        ZONE_LABEL_KEY,
        new_zone_value,
        dry_run=dry_run,
    ):
        return False

    # Step 2: Get and update Machines in the MachineSet
    machines = get_machines_for_machineset(resource_name)
    for machine in machines:
        if not update_zone_label(
            machine,
            ZONE_LABEL_KEY,
            new_zone_value,
            dry_run=dry_run,
        ):
            return False

    # Step 3: Get and update Nodes for the Machines
    nodes = get_nodes_for_machines(machines)
    for node in nodes:
        if not update_zone_label(
            node,
            ZONE_LABEL_KEY,
            new_zone_value,
            dry_run=dry_run,
        ):
            return False

    return True


@click.command()
@click.option(
    "--kubeconfig",
    default=None,
    help="Path to the kubeconfig file.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be changed without applying.",
)
@click.option(
    "--live",
    is_flag=True,
    default=True,
    help="Apply changes (default behavior).",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging.",
)
def main(kubeconfig: str | None, dry_run: bool, live: bool, debug: bool) -> None:
    r"""Update Portworx zone labels across OpenShift resources.

    This script updates the topology.portworx.io/zone label on MachineSets,
    Machines, and Nodes based on the ESXi host cluster name extracted from
    the MachineSet's resourcePool configuration.

    \b
    Label Propagation Order:
    1. MachineSet (spec.template.spec.metadata.labels)
    2. Machine (spec.metadata.labels)
    3. Node (metadata.labels)


    \b
    Examples:
        # Default behavior (live mode)
        python openshift_zone_updater.py

        # Dry-run mode
        python openshift_zone_updater.py --dry-run

        # With custom kubeconfig
        python openshift_zone_updater.py --kubeconfig /path/to/kubeconfig
    """
    # Handle flag logic
    if dry_run:
        live = False

    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)

    logger.info("Starting Portworx Zone Label Updater")
    logger.info("Mode: %s", "DRY-RUN" if dry_run else "LIVE")

    try:
        # Connect to cluster using auto-loading with in-cluster fallback
        if not load_kube_config_auto(config_file=kubeconfig):
            logger.error("Failed to load Kubernetes configuration.")
            click.echo("ERROR: Failed to load Kubernetes configuration.", err=True)
            raise click.Abort()

        # Get all MachineSets (client created internally by utility function)
        machinesets = get_all_machinesets()

        if not machinesets:
            logger.warning("No MachineSets found in namespace %s", NAMESPACE)
            return

        # Process each MachineSet
        success_count = 0
        failure_count = 0

        for machineset in machinesets:
            try:
                if process_machineset(machineset, dry_run):
                    success_count += 1
                else:
                    failure_count += 1
            except Exception as e:
                logger.error(
                    "Failed to process MachineSet %s: %s",
                    machineset["metadata"]["name"],
                    e,
                )
                failure_count += 1
                raise

        # Summary
        logger.info("Completed: %d successful, %d failed", success_count, failure_count)

        if failure_count > 0:
            raise click.Abort()

    except click.Abort:
        raise
    except Exception as e:
        logger.error("Error: %s", e)
        raise click.Abort() from e


if __name__ == "__main__":
    main()
