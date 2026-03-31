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

    # With custom kubeconfig (or KUBECONFIG environment variable)
    python openshift_zone_updater.py --kubeconfig /path/to/kubeconfig

    # Using KUBECONFIG environment variable
    KUBECONFIG=/path/to/kubeconfig python openshift_zone_updater.py
"""

import logging
import os
from typing import Any, Dict, Optional

import click
from rich.console import Console

from pyplayground.utils.k8s_utils import (
    get_all_machinesets,
    get_machines_for_machineset,
    get_machineset_resource_pool,
    get_nodes_for_machines,
    load_kube_config_auto,
    parse_resource_pool_path,
    update_zone_label,
)
from pyplayground.utils.logging_utils import get_logger, setup_logging

logger = get_logger(__name__)

console = Console()

# Constants
NAMESPACE = "openshift-machine-api"
ZONE_LABEL_KEY = "topology.portworx.io/zone"


def validate_machine_status(
    machine: Dict[str, Any],
    dry_run: bool = False,
) -> bool:
    """Validate that a Machine is ready for label propagation.

    Checks:
    - Machine has status section
    - Machine has nodeRef (node associated)
    - Machine phase is Running (not Provisioning)

    Args:
        machine: The Machine resource dictionary
        dry_run: If True, only log validation result

    Returns:
        True if Machine is valid, False otherwise
    """
    resource_name = machine["metadata"]["name"]
    machine_status = machine.get("status", {})

    if not machine_status:
        logger.warning(
            "Machine %s has no status section, skipping",
            resource_name,
        )
        return False

    node_ref = machine_status.get("nodeRef", {})
    if not node_ref or not node_ref.get("name"):
        logger.warning(
            "Machine %s has no nodeRef, skipping",
            resource_name,
        )
        return False

    phase = machine_status.get("phase", "Unknown")
    if phase != "Running":
        logger.warning(
            "Machine %s phase is %s (not Running), skipping",
            resource_name,
            phase,
        )
        return False

    logger.debug(
        "Machine %s passed status validation (phase=%s, node=%s)",
        resource_name,
        phase,
        node_ref.get("name"),
    )
    return True


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


def process_machineset(
    machineset: Dict[str, Any],
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
    if not machines:
        logger.warning(
            "No Machines found for MachineSet %s",
            resource_name,
        )
        if dry_run:
            logger.info(
                "DRY-RUN: Would report missing Machines for MachineSet %s",
                resource_name,
            )
    for machine in machines:
        # Validate Machine status before processing
        if not validate_machine_status(machine, dry_run=dry_run):
            logger.warning(
                "Machine %s failed status validation, skipping",
                machine["metadata"]["name"],
            )
            continue
        if not update_zone_label(
            machine,
            ZONE_LABEL_KEY,
            new_zone_value,
            dry_run=dry_run,
        ):
            return False

    # Step 3: Get and update Nodes for the Machines
    nodes = get_nodes_for_machines(machines)
    if dry_run and len(nodes) < len(machines):
        missing_count = len(machines) - len(nodes)
        logger.info(
            "DRY-RUN: Would report %d Machine(s) without associated Node(s)",
            missing_count,
        )
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
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the kubeconfig file. If not provided, uses default lookup.",
    envvar="KUBECONFIG",
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
def main(kubeconfig: Optional[str], dry_run: bool, live: bool, debug: bool) -> None:
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

        # With custom kubeconfig (or KUBECONFIG environment variable)
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
