#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Portworx node zone management utility.

This module provides functionality to manage Portworx node zones, including
labeling nodes and updating ConfigMaps for zone assignments.
"""

import argparse
import json
import time

from kubernetes import client, config


class PortworxNodeManager:
    """Manager for Portworx node zone operations."""

    def __init__(self, zone, dry_run=True, debug_cm=False, v1_client=None):
        """Initialize the PortworxNodeManager.

        Args:
            zone (str): Target zone for node assignment.
            dry_run (bool): Whether to perform dry run (no actual changes).
            debug_cm (bool): Whether to enable ConfigMap debugging.
            v1_client: Kubernetes API client instance.
        """
        self.v1 = v1_client
        self.zone = zone
        self.dry_run = dry_run
        self.debug_cm = debug_cm

    def get_px_nodes(self):
        """Get all Portworx-eligible nodes (excluding masters and disabled nodes).

        Returns:
            List: List of node objects that can run Portworx.
        """
        print("Fetching all nodes except master nodes and nodes with px/enabled=false...")
        nodes = self.v1.list_node()

        filtered_nodes = []
        for node in nodes.items:
            labels = node.metadata.labels
            if (
                "node-role.kubernetes.io/master" not in labels
                and labels.get("px/enabled") != "false"
            ):
                filtered_nodes.append(node)

        print(
            f"Found {len(filtered_nodes)} node(s) that are not master nodes and do not have px/enabled=false."
        )
        return filtered_nodes

    def label_node(self, node_name, labels):
        """Apply labels to a Kubernetes node.

        Args:
            node_name (str): Name of the node to label.
            labels (dict): Dictionary of labels to apply.
        """
        print(f"Dry-run: {self.dry_run} - Adding labels {labels} to node {node_name}...")
        if not self.dry_run:
            body = {"metadata": {"labels": labels}}
            self.v1.patch_node(node_name, body)
            print(f"Node {node_name} labeled successfully with {labels}.")

    def update_cm(self, node_name):
        """Update ConfigMap with node zone information.

        Args:
            node_name (str): Name of the node to update in ConfigMap.
        """
        print(f"Fetching ConfigMap for node {node_name}...")
        config_maps = self.v1.list_namespaced_config_map(namespace="kube-system")
        for cm in config_maps.items:
            if cm.metadata.name.startswith("px-cloud-drive-"):
                data = json.loads(cm.data["cloud-drive"])
                configmap_modified = False

                for node_id, node_config in data.items():
                    if node_config["SchedulerNodeName"] == node_name:
                        print(
                            f"Found SchedulerNodeName {node_name} in ConfigMap {cm.metadata.name}."
                        )
                        print(f"Current zone for {node_name}: {node_config.get('Zone', 'not set')}")
                        print(f"Updating zone to: {self.zone}")

                        node_config["Zone"] = self.zone
                        configmap_modified = True

                if configmap_modified:
                    new_configmap = json.dumps(data, separators=(",", ":"))

                    if self.dry_run:
                        if self.debug_cm:
                            print(
                                f"\nDry-run: New intended ConfigMap content for {cm.metadata.name}:\n{new_configmap}\n"
                            )
                        print(
                            f"Dry-run: Would save a backup of the current ConfigMap to cm_backup_{cm.metadata.name}.json"
                        )
                    else:
                        backup_filename = f"cm_backup_{cm.metadata.name}.json"
                        with open(backup_filename, "w") as backup_file:
                            json.dump(data, backup_file, separators=(",", ":"))
                        print(f"Backup of ConfigMap saved as {backup_filename}.")

                        body = {"data": {"cloud-drive": new_configmap}}
                        self.v1.patch_namespaced_config_map(cm.metadata.name, "kube-system", body)
                        print(
                            f"ConfigMap {cm.metadata.name} updated successfully with changes for {node_name}."
                        )
                else:
                    print(f"No changes made to ConfigMap {cm.metadata.name} for {node_name}.")

    def label_px_nodes(self, node_names):
        """Label multiple Portworx nodes with zone information.

        Args:
            node_names (List[str]): List of node names to label.
        """
        nodes = self.get_px_nodes()
        node_dict = {node.metadata.name: node for node in nodes}

        for node_name in node_names:
            node = node_dict.get(node_name)
            if not node:
                print(f"Node {node_name} not found with PX installed, skipping...")
                continue

            node_type = node.metadata.labels.get("portworx.io/node-type")
            print(f"\nProcessing node: {node_name}, type: {node_type}")

            print(f"Labeled {node_name} with topology.portworx.io/zone={self.zone}")
            self.label_node(node_name, {"topology.portworx.io/zone": self.zone})

            if node_type == "storage":
                print(f"{node_name} is a storage node. Proceeding with special handling...")
                self.label_node(node_name, {"px/service": "stop"})

                if not self.dry_run:
                    print(
                        f"Waiting for 1 minute after labeling {node_name} with px/service=stop..."
                    )
                    time.sleep(60)

                self.update_cm(node_name)

                if not self.dry_run:
                    print("Restarting PX on the storage node...")
                    self.label_node(node_name, {"px/service": "restart"})

                    print(f"Waiting for 3 minutes after labeling {node_name} to let it start...")
                    time.sleep(180)

            else:
                print(f"{node_name} is a storageless node. Proceeding to restart...")
                if not self.dry_run:
                    print(f"Labeled {node_name} with px/service=restart")
                    self.label_node(node_name, {"px/service": "restart"})

                    print(f"Waiting for 3 minutes after labeling {node_name} to let it start...")
                    time.sleep(180)


def load_nodes_from_file(file_path):
    """Load node names from a text file.

    Args:
        file_path (str): Path to file containing node names (one per line).

    Returns:
        List[str]: List of node names loaded from the file.
    """
    try:
        with open(file_path, "r") as f:
            nodes = [line.strip() for line in f.readlines() if line.strip()]
        print(f"Loaded {len(nodes)} nodes from file {file_path}")
        return nodes
    except FileNotFoundError:
        print(f"Error: The file {file_path} was not found.")
        return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Label Portworx nodes and update ConfigMaps")
    parser.add_argument("--zone", required=True, help="Zone value to set for nodes")
    parser.add_argument(
        "--real-run", action="store_true", help="If set, run for real (not a dry-run)"
    )
    parser.add_argument("--kubeconfig", help="Path to the kubeconfig file")
    parser.add_argument("--node-file", help="Path to a file with node names, one per line")
    parser.add_argument("--debug-cm", action="store_true", help="Enable debug Config Map")

    args = parser.parse_args()
    dry_run = not args.real_run
    debug_cm = args.debug_cm

    # Load kubeconfig outside of class to avoid multiple loads
    if args.kubeconfig:
        config.load_kube_config(config_file=args.kubeconfig)
    else:
        config.load_kube_config()

    v1_client = client.CoreV1Api()

    manager = PortworxNodeManager(
        zone=args.zone, dry_run=dry_run, v1_client=v1_client, debug_cm=debug_cm
    )

    if args.node_file:
        node_names = load_nodes_from_file(args.node_file)
    else:
        node_names = input("Enter the comma-separated list of node names: ").split(",")

    if node_names:
        manager.label_px_nodes([node.strip() for node in node_names])
    else:
        print("No nodes provided. Exiting.")
