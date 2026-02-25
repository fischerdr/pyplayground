#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""NFS checker and node management utility.

This module provides functionality to check NFS mounts on Kubernetes nodes
and perform cordon-drain-reboot operations for nodes with stale entries.
"""

import argparse
import json
import subprocess
import time

SSH_KEY = "id_rsa"
SSH_USER = "core"
KUBE_CLI = "oc --kubeconfig=~/.kube/config"
DRAIN_TIMEOUT = 300  # Timeout for draining the node in seconds


def run_command(command):
    """Run a shell command and return output or raise exception on failure.

    Args:
        command (str): Shell command to execute.

    Returns:
        str: Command output stripped of whitespace.

    Raises:
        Exception: If command returns non-zero exit code.
    """
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(result.stderr)
    return result.stdout.strip()


def run_command_with_timeout(command, timeout):
    """Run a shell command with timeout and return output.

    Args:
        command (str): Shell command to execute.
        timeout (int): Timeout in seconds.

    Returns:
        str: Command output stripped of whitespace.

    Raises:
        Exception: If command returns non-zero exit code or times out.
    """
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise Exception(result.stderr)
    return result.stdout.strip()


def get_nodes():
    """Get list of Kubernetes nodes with their IP addresses.

    Returns:
        List[Tuple[str, str]]: List of (node_name, node_ip) tuples.
    """
    try:
        nodes_output = run_command(f"{KUBE_CLI} get nodes -o wide")
        nodes = []
        for line in nodes_output.split("\n")[1:]:
            if line:
                parts = line.split()
                node_name = parts[0]
                node_ip = parts[5]
                nodes.append((node_name, node_ip))
        return nodes
    except Exception as e:
        print(f"Error fetching nodes: {e}")
        return []


def get_nodes_from_file(file_path):
    """Load node information from a JSON file.

    Args:
        file_path (str): Path to JSON file containing node data.

    Returns:
        List[Tuple[str, str]]: List of (node_name, node_ip) tuples.
    """
    try:
        with open(file_path, "r") as file:
            nodes = [tuple(line.strip().split(",")) for line in file.readlines()]
        return nodes
    except Exception as e:
        print(f"Error reading nodes from file: {e}")
        return []


def get_node_ip(node_name):
    """Get IP address for a specific node.

    Args:
        node_name (str): Name of the Kubernetes node.

    Returns:
        str: IP address of the node.
    """
    node_info = run_command(f"{KUBE_CLI} get node {node_name} -o json")
    node_data = json.loads(node_info)
    for address in node_data["status"]["addresses"]:
        if address["type"] == "InternalIP":
            return address["address"]
    raise Exception(f"Could not find IP address for node {node_name}")


def get_nfs_mounts(node_ip):
    """Get NFS mounts from a specific node.

    Args:
        node_ip (str): IP address of the node to check.

    Returns:
        str: Output from mount command showing NFS mounts.
    """
    try:
        mount_output = run_command(f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {SSH_USER}@{node_ip} 'sudo mount | grep nfs | grep px'")
        nfs_mounts = [line.split()[2] for line in mount_output.strip().split("\n") if line]
        return nfs_mounts
    except Exception as e:
        print(f"Error fetching PX Sharedv4 mounts on node {node_ip}: {e}")
        return []


def check_nfs_on_node(node_ip):
    """Check if node has stale NFS entries.

    Args:
        node_ip (str): IP address of the node to check.

    Returns:
        bool: True if node has stale NFS entries, False otherwise.
    """
    nfs_mounts = get_nfs_mounts(node_ip)
    if not nfs_mounts:
        print(f"No PX Sharedv4 mounts found on node {node_ip}.\n")
        return None  # No need to reboot if there are no NFS mounts

    for mount_point in nfs_mounts:
        print(f"Checking PX Sharedv4 mount point: {mount_point} on node {node_ip}.")
        try:
            # Use stat command with a timeout within the SSH command
            result = subprocess.run(
                f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {SSH_USER}@{node_ip} 'sudo timeout 30 stat {mount_point}'",
                shell=True,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"Error: stat command failed for {mount_point} on node {node_ip}.\n")
                print(f"stdout: {result.stdout}")
                print(f"stderr: {result.stderr}")
                return False
            else:
                print(f"Stat command succeeded for mount point {mount_point} on node {node_ip}.\n")

        except subprocess.CalledProcessError as e:
            print(f"Error: Unable to stat {mount_point} on node {node_ip} (timeout after 30s or stat command failed)")
            print(f"stdout: {e.stdout}")
            print(f"stderr: {e.stderr}")
            return False

    return True


def cordon_drain_reboot_node(node, perform_reboot):
    """Cordon, drain, and optionally reboot a Kubernetes node.

    Args:
        node (str): Name of the node to process.
        perform_reboot (bool): Whether to actually perform the reboot.

    Returns:
        bool: True if operation was successful, False otherwise.
    """
    print(f"Performing Cordon-Drain-Reboot operation on node {node}.")
    print(f"Cordoning node {node}")
    try:
        run_command(f"{KUBE_CLI} adm cordon {node}")
    except Exception as e:
        print(f"Error cordoning node {node}: {e}")
        return False

    print(f"Draining node {node}")
    print(f"Waiting up to {DRAIN_TIMEOUT} seconds for pods to be evicted...")
    try:
        run_command_with_timeout(
            f"{KUBE_CLI} adm drain {node} --ignore-daemonsets --delete-emptydir-data --force",
            DRAIN_TIMEOUT,
        )
    except Exception as e:
        print(f"Error draining node {node}: {e}")
        return False

    node_ip = get_node_ip(node)
    print(f"Rebooting node {node} with IP {node_ip} using SSH")

    if perform_reboot:
        try:
            run_command(f"ssh -t -i {SSH_KEY} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {SSH_USER}@{node_ip} 'sudo systemctl reboot'")
            print(f"Node {node} rebooted successfully.")
        except Exception as e:
            print(f"Error rebooting node {node}: {e}")
            return False
    else:
        print(f"DRY RUN: Would reboot node {node} with IP {node_ip}")

    return wait_for_node_ready_and_uncordon(node)


def wait_for_node_ready_and_uncordon(node):
    """Wait for a node to come back online and uncordon it.

    Args:
        node (str): Name of the node to wait for.

    Returns:
        bool: True if node became ready and was uncordoned, False otherwise.
    """
    print(f"Waiting for node {node} to come back online")
    print("Sleeping 90 seconds before checking node status...")
    time.sleep(90)
    start_time = time.time()
    max_wait_time = 1800  # 30 minutes
    while time.time() - start_time < max_wait_time:
        try:
            print(f"Checking status for node {node}...")
            node_status = run_command(f"{KUBE_CLI} get node {node} -o jsonpath='{{.status.conditions[?(@.type==\"Ready\")].status}}'")
            if node_status == "True":
                print(f"Node {node} is ready")
                run_command(f"{KUBE_CLI} adm uncordon {node}")
                return True
            time.sleep(20)
        except Exception as e:
            print(f"Error checking status for node {node}: {e}")

    print(f"Node {node} did not become ready within the maximum wait time.")
    return False


def main(perform_reboot, nodes_file):
    """Main function to check NFS mounts and manage nodes.

    Args:
        perform_reboot (bool): Whether to perform actual reboot operations.
        nodes_file (str): Optional path to file containing node information.
    """
    if nodes_file:
        nodes = get_nodes_from_file(nodes_file)
    else:
        nodes = get_nodes()

    stale_nodes = []
    successful_nodes = []

    for node_name, node_ip in nodes:
        status = check_nfs_on_node(node_ip)
        if status is None:
            continue
        elif status:
            successful_nodes.append((node_name, node_ip))
        else:
            stale_nodes.append((node_name, node_ip))

    if perform_reboot:
        print("\nPerforming Cordon-Drain-Reboot operation on nodes with stale PX Sharedv4 entries...\n")
        for node_name, node_ip in stale_nodes:
            cordon_drain_reboot_node(node_name, perform_reboot)

    print("\nSummary:")
    print("Nodes with PX Sharedv4 entries that went fine:")
    for node_name, node_ip in successful_nodes:
        print(f"- {node_name} ({node_ip})")

    print("\nNodes with stale PX Sharedv4 entries that were rebooted:")
    if stale_nodes:
        for node_name, node_ip in stale_nodes:
            print(f"- {node_name} ({node_ip})")
    else:
        print("None")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check and manage PX Sharedv4 mounts on nodes.")
    parser.add_argument(
        "--perform-reboot",
        action="store_true",
        help="Actually perform reboots, otherwise dry-run is default.",
    )
    parser.add_argument(
        "--nodes-file",
        type=str,
        help="Path to a file containing a list of nodes to check. Format: node-name,ip per line.",
    )
    args = parser.parse_args()
    main(args.perform_reboot, args.nodes_file)
