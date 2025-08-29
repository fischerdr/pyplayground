#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Portworx node zone management utility for Kubernetes/OpenShift clusters.

This module provides functionality to manage Portworx node zones in a Kubernetes/OpenShift
cluster, including labeling nodes with zones, updating ConfigMaps, and managing node restarts.
It supports both storage and storageless Portworx nodes.
"""
import json
import logging
import time
from typing import Dict, List, Optional

import click
from kubernetes import client, config
from kubernetes.client import ApiException, V1Node, V1Pod

from pyplayground.utils.k8s_utils import (
    get_machine_for_node,
    get_machineset_for_machine,
    get_nodes_from_machineset_specific,
    get_nodes_from_machinesets,
    wait_for_pod_readiness,
)
from pyplayground.utils.logging_utils import get_logger, setup_logging

# Setup logger instance
logger = get_logger(__name__)

# Portworx-specific constants
PORTWORX_NAMESPACE = "portworx"
PORTWORX_ZONE_LABEL = "topology.portworx.io/zone"
PX_SERVICE_LABEL = "px/service"
PX_NODE_TYPE_LABEL = "portworx.io/node-type"
PX_POD_LABEL_SELECTOR = "name=portworx"

# OpenShift Machine API constants
MACHINE_API_GROUP = "machine.openshift.io"
MACHINE_API_VERSION = "v1beta1"
MACHINE_API_NAMESPACE = "openshift-machine-api"
MACHINE_API_PLURAL = "machines"

# Kubernetes constants
KUBE_SYSTEM_NAMESPACE = "kube-system"


class PortworxNodeManager:
    """Manages Portworx node operations in a Kubernetes cluster."""

    def __init__(
        self,
        fallback_zone: Optional[str] = None,
        dry_run: bool = True,
        debug_cm: bool = False,
        v1_client: Optional[client.CoreV1Api] = None,
        crd_client: Optional[client.CustomObjectsApi] = None,
    ) -> None:
        """Initialize the PortworxNodeManager."""
        self.v1 = v1_client
        self.crd = crd_client
        self.fallback_zone = fallback_zone
        self.dry_run = dry_run
        self.debug_cm = debug_cm

    def get_nodes_from_machineset_specific(self, machineset_name: str) -> Dict[str, str]:
        """Query Kubernetes for nodes associated with a specific MachineSet and their Portworx zone."""
        node_info = get_nodes_from_machineset_specific(
            machineset_name=machineset_name, label_key=PORTWORX_ZONE_LABEL, crd_client=self.crd
        )

        # Convert the node_info dict to just node->zone mapping
        return {
            node_name: info.get(PORTWORX_ZONE_LABEL, "unknown")
            for node_name, info in node_info.items()
        }

    def get_zone_for_node(self, node_name: str, unattended: bool = False) -> Optional[str]:
        """Fetch the zone for a node by checking its Machine and MachineSet."""
        machine = get_machine_for_node(node_name, self.crd)
        if machine:
            machineset = get_machineset_for_machine(machine, self.crd)
            if machineset:
                labels = machineset.get("metadata", {}).get("labels", None)
                if labels:
                    zone = labels.get(PORTWORX_ZONE_LABEL, None)
                    if zone:
                        logger.info(
                            f"Zone '{zone}' found in MachineSet '{machineset['metadata']['name']}'"
                        )
                        return zone
                else:
                    logger.warning(
                        f"No labels found in MachineSet '{machineset['metadata']['name']}'"
                    )

        if self.fallback_zone:
            logger.info(
                f"No zone found in MachineSet, using provided fallback zone: '{self.fallback_zone}'"
            )
            return self.fallback_zone

        if unattended:
            logger.error(f"Cannot determine zone for node '{node_name}' in unattended mode.")
            return None

        zone = input(f"No zone found for node {node_name}. Please provide the zone manually: ")
        return zone

    def label_node(self, node_name: str, labels: Dict[str, str]) -> None:
        """Apply labels to a Kubernetes node."""
        logger.info(f"Applying labels {labels} to node '{node_name}'...")
        if not self.dry_run:
            body = {"metadata": {"labels": labels}}
            self.v1.patch_node(node_name, body)
            logger.info(f"Node '{node_name}' labeled successfully.")
        else:
            logger.info(f"DRY-RUN: Would have labeled node '{node_name}' with {labels}.")

    def label_machine(self, machine_name: str, labels: Dict[str, str]) -> None:
        """Apply labels to an OpenShift Machine resource."""
        logger.info(f"Applying labels {labels} to machine '{machine_name}'...")
        if not self.dry_run:
            body = {"metadata": {"labels": labels}}
            self.crd.patch_namespaced_custom_object(
                group=MACHINE_API_GROUP,
                version=MACHINE_API_VERSION,
                namespace=MACHINE_API_NAMESPACE,
                plural=MACHINE_API_PLURAL,
                name=machine_name,
                body=body,
            )
            logger.info(f"Machine '{machine_name}' labeled successfully.")
        else:
            logger.info(f"DRY-RUN: Would have labeled machine '{machine_name}' with {labels}.")

    def update_cm(self, node_name: str, zone: str) -> None:
        """Update the Portworx ConfigMap with zone information for a specific node."""
        logger.info(f"Searching for ConfigMap to update for node '{node_name}'...")
        config_maps = self.v1.list_namespaced_config_map(namespace=KUBE_SYSTEM_NAMESPACE)
        for cm in config_maps.items:
            if cm.metadata.name.startswith("px-cloud-drive-"):
                data = json.loads(cm.data["cloud-drive"])
                configmap_modified = False

                for node_id, node_config in data.items():
                    if node_config["SchedulerNodeName"] == node_name:
                        logger.info(
                            f"Found SchedulerNodeName '{node_name}' in ConfigMap '{cm.metadata.name}'."
                        )
                        current_zone = node_config.get("Zone", "not set")
                        logger.info(f"Current zone for '{node_name}': {current_zone}")
                        if current_zone != zone:
                            logger.info(f"Updating zone to: '{zone}'")
                            node_config["Zone"] = zone
                            configmap_modified = True
                        else:
                            logger.info("Zone is already correctly set. No update needed.")

                if configmap_modified:
                    new_configmap = json.dumps(data, separators=(",", ":"))

                    if self.dry_run:
                        logger.info(f"DRY-RUN: Would have updated ConfigMap '{cm.metadata.name}'.")
                        if self.debug_cm:
                            logger.debug(
                                f"DRY-RUN: New ConfigMap content for '{cm.metadata.name}':\n{new_configmap}"
                            )
                    else:
                        backup_filename = f"cm_backup_{cm.metadata.name}.json"
                        with open(backup_filename, "w") as backup_file:
                            json.dump(data, backup_file, separators=(",", ":"))
                        logger.info(f"Backup of ConfigMap saved to '{backup_filename}'.")

                        body = {"data": {"cloud-drive": new_configmap}}
                        self.v1.patch_namespaced_config_map(
                            cm.metadata.name, KUBE_SYSTEM_NAMESPACE, body
                        )
                        logger.info(f"ConfigMap '{cm.metadata.name}' updated successfully.")
                else:
                    logger.debug(
                        f"No changes required for node '{node_name}' in ConfigMap '{cm.metadata.name}'."
                    )

    def get_px_nodes(self) -> List[V1Node]:
        """Get a list of all nodes that are running Portworx pods."""
        logger.info("Fetching all nodes where Portworx pods are running...")
        pods = self.v1.list_namespaced_pod(
            namespace=PORTWORX_NAMESPACE, label_selector=PX_POD_LABEL_SELECTOR
        )
        px_nodes = {pod.spec.node_name for pod in pods.items if pod.spec.node_name}
        logger.info(f"Found {len(px_nodes)} node(s) running Portworx pods.")
        return [self.v1.read_node(node_name) for node_name in px_nodes]

    def get_portworx_pod_for_node(self, node_name: str) -> Optional[V1Pod]:
        """Get the Portworx pod running on a specific node."""
        try:
            pods = self.v1.list_namespaced_pod(
                namespace=PORTWORX_NAMESPACE, label_selector=PX_POD_LABEL_SELECTOR
            )
            for pod in pods.items:
                if pod.spec.node_name == node_name:
                    return pod
            return None
        except ApiException as e:
            logger.error(f"Error fetching pod for node '{node_name}': {e}")
            return None

    def _handle_storage_node(self, node_name: str, zone: str, pod: V1Pod):
        """Handle the zone update and restart process for a storage node."""
        logger.info(f"'{node_name}' is a storage node. Stopping service before CM update...")
        self.label_node(node_name, {PX_SERVICE_LABEL: "stop"})

        if not self.dry_run:
            logger.info(
                f"Waiting for 1 minute after labeling '{node_name}' with px/service=stop..."
            )
            time.sleep(60)

        self.update_cm(node_name, zone)

        logger.info("Restarting PX on the storage node...")
        self.label_node(node_name, {PX_SERVICE_LABEL: "restart"})

    def _handle_storageless_node(self, node_name: str):
        """Handle the restart process for a storageless node."""
        logger.info(f"'{node_name}' is a storageless node. Restarting service...")
        self.label_node(node_name, {PX_SERVICE_LABEL: "restart"})

    def label_px_nodes(self, node_names: List[str], unattended: bool) -> None:
        """Label Portworx nodes with their corresponding zone information."""
        nodes = self.get_px_nodes()
        node_dict = {node.metadata.name: node for node in nodes}

        for node_name in node_names:
            node = node_dict.get(node_name)
            if not node:
                logger.warning(f"Node '{node_name}' not found with PX installed, skipping...")
                continue

            node_type = node.metadata.labels.get(PX_NODE_TYPE_LABEL)
            logger.info(f"\nProcessing node: '{node_name}', type: {node_type}")

            zone = self.get_zone_for_node(node_name, unattended)
            if not zone:
                continue  # Skip if zone could not be determined

            current_zone = node.metadata.labels.get(PORTWORX_ZONE_LABEL)
            if current_zone == zone:
                logger.info(
                    f"Node '{node_name}' is already in the correct zone ('{zone}'). Skipping."
                )
                continue

            logger.info(f"Updating zone for node '{node_name}': from '{current_zone}' to '{zone}'")

            machine = get_machine_for_node(node_name, self.crd)
            if machine:
                self.label_machine(machine["metadata"]["name"], {PORTWORX_ZONE_LABEL: zone})

            self.label_node(node_name, {PORTWORX_ZONE_LABEL: zone})

            pod = self.get_portworx_pod_for_node(node_name)
            if not pod:
                logger.warning(
                    f"No Portworx pod found for node '{node_name}'. Skipping readiness check."
                )
                continue

            if node_type == "storage":
                self._handle_storage_node(node_name, zone, pod)
            else:
                self._handle_storageless_node(node_name)

            if not self.dry_run:
                logger.info(
                    f"Waiting for Portworx pod '{pod.metadata.name}' on node '{node_name}' to be ready..."
                )
                pod_ready = wait_for_pod_readiness(
                    pod_name=pod.metadata.name, namespace=PORTWORX_NAMESPACE, v1_client=self.v1
                )
                if not pod_ready:
                    logger.error(
                        f"Pod '{pod.metadata.name}' did not become ready within the timeout."
                    )
                    raise RuntimeError(
                        f"Portworx pod on node '{node_name}' failed to become ready. Exiting."
                    )


def load_nodes_from_file(file_path: str) -> List[str]:
    """Load a list of node names from a file."""
    try:
        with open(file_path, "r") as f:
            nodes = [line.strip() for line in f.readlines() if line.strip()]
        logger.info(f"Loaded {len(nodes)} nodes from file '{file_path}'")
        return nodes
    except FileNotFoundError:
        logger.error(f"Error: The file '{file_path}' was not found.")
        return []


@click.command()
@click.option("--zone", help="Zone value to set for nodes (used as fallback).")
@click.option(
    "--real-run", is_flag=True, default=False, help="If set, run for real (not a dry-run)."
)
@click.option("--kubeconfig", help="Path to the kubeconfig file.", type=click.Path())
@click.option(
    "--node-file", help="Path to a file with node names, one per line.", type=click.Path()
)
@click.option("--debug-cm", is_flag=True, default=False, help="Enable debug Config Map.")
@click.option(
    "--fully-unattended",
    is_flag=True,
    default=False,
    help="Run unattended and iterate over all MachineSets.",
)
@click.option("--machine-set", help="Specify a MachineSet to load nodes from.")
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(
    zone: Optional[str],
    real_run: bool,
    kubeconfig: Optional[str],
    node_file: Optional[str],
    debug_cm: bool,
    fully_unattended: bool,
    machine_set: Optional[str],
    debug: bool,
):
    """Labels Portworx nodes with zone information and updates necessary ConfigMaps."""
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level)

    dry_run = not real_run
    logger.info(f"Starting Portworx Zone Updater. DRY-RUN mode: {dry_run}")

    # Load Kubernetes config
    config.load_kube_config(config_file=kubeconfig)

    v1_client = client.CoreV1Api()
    crd_client = client.CustomObjectsApi()

    manager = PortworxNodeManager(
        fallback_zone=zone,
        dry_run=dry_run,
        v1_client=v1_client,
        crd_client=crd_client,
        debug_cm=debug_cm,
    )

    node_names = []
    if fully_unattended:
        logger.info("Fully unattended mode: processing all nodes from all MachineSets.")
        node_map = get_nodes_from_machinesets(label_key=PORTWORX_ZONE_LABEL, crd_client=crd_client)
        node_names = list(node_map.keys())
    elif machine_set:
        logger.info(f"Processing nodes from specified MachineSet: '{machine_set}'")
        node_map = manager.get_nodes_from_machineset_specific(machine_set)
        node_names = list(node_map.keys())
    elif node_file:
        logger.info(f"Loading nodes from file: '{node_file}'")
        node_names = load_nodes_from_file(node_file)
    else:
        logger.error(
            "No node source specified. Use --fully-unattended, --machine-set, or --node-file."
        )
        return

    if node_names:
        manager.label_px_nodes([name.strip() for name in node_names], unattended=fully_unattended)
    else:
        logger.warning("No nodes found to process. Exiting.")


if __name__ == "__main__":
    main()
