#!/usr/bin/env python3
"""
OpenShift VMware Cluster Report Generator.

This script interacts with OpenShift Kubernetes and VMware vSphere to generate
a report on the number of ESXi hosts per VMware cluster. It maps OpenShift
MachineSets to their respective ESXi host clusters.

Author: Cascade
Date: 2025-03-10
"""

import json
import os
import ssl
import sys
from typing import Any, Dict, List, Optional

import click
from kubernetes import client, config
from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim
from rich.console import Console
from rich.table import Table

# Import utility functions
from utils.k8s_utils import get_custom_objects_api
from utils.logging_utils import get_logger, setup_logging

# Set up logging
logger = get_logger(__name__)
setup_logging()

# Initialize rich console for output
console = Console()


def connect_to_vsphere(
    host: str, username: str, password: str, disable_ssl: bool = False
) -> Optional[Any]:
    """
    Establish connection to VMware vSphere.

    Args:
        host: vSphere host address
        username: vSphere username
        password: vSphere password
        disable_ssl: Whether to disable SSL verification

    Returns:
        Service instance object if connection is successful, None otherwise
    """
    try:
        if disable_ssl:
            context = None
            logger.info("SSL verification disabled for vSphere connection")
        else:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        si = SmartConnect(host=host, user=username, pwd=password, sslContext=context)
        if not si:
            logger.error("Failed to connect to vSphere")
            return None
        logger.info(f"Successfully connected to vSphere host: {host}")
        return si
    except Exception as e:
        logger.error(f"Failed to connect to vSphere: {e}")
        return None


def get_machinesets(
    crd_client: Optional[client.CustomObjectsApi] = None,
    namespace: str = "openshift-machine-api",
) -> List[Dict[str, Any]]:
    """
    Retrieve all MachineSets from OpenShift.

    Args:
        crd_client: Optional CustomObjectsApi client
        namespace: Namespace where MachineSets reside

    Returns:
        List of MachineSet objects
    """
    if not crd_client:
        crd_client = get_custom_objects_api()

    try:
        machinesets = crd_client.list_namespaced_custom_object(
            group="machine.openshift.io",
            version="v1beta1",
            namespace=namespace,
            plural="machinesets",
        )
        logger.info(f"Retrieved {len(machinesets['items'])} MachineSets from OpenShift")
        return machinesets["items"]
    except client.rest.ApiException as e:
        logger.error(f"Failed to retrieve MachineSets: {e}")
        return []


def extract_vsphere_info_from_machinesets(
    machinesets: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Extract VMware vSphere information from MachineSets.

    Args:
        machinesets: List of MachineSet objects

    Returns:
        Dictionary mapping MachineSet names to their vSphere information
    """
    vsphere_info = {}
    for machineset in machinesets:
        try:
            name = machineset["metadata"]["name"]
            # Navigate through the nested structure to find provider spec
            provider_spec = machineset["spec"]["template"]["spec"]["providerSpec"]["value"]
            # Check if this is a vSphere provider
            if provider_spec.get("kind") == "VSphereMachineProviderSpec":
                vsphere_info[name] = {
                    "datacenter": provider_spec.get("workspace", {}).get("datacenter", ""),
                    "datastore": provider_spec.get("workspace", {}).get("datastore", ""),
                    "folder": provider_spec.get("workspace", {}).get("folder", ""),
                    "resourcePool": provider_spec.get("workspace", {}).get("resourcePool", ""),
                    "server": provider_spec.get("workspace", {}).get("server", ""),
                    "template": provider_spec.get("template", ""),
                    "diskGiB": provider_spec.get("diskGiB", 0),
                    "memoryMiB": provider_spec.get("memoryMiB", 0),
                    "numCPUs": provider_spec.get("numCPUs", 0),
                }
                # Extract network information if available
                if "network" in provider_spec and "devices" in provider_spec["network"]:
                    devices = provider_spec["network"]["devices"]
                    if devices and len(devices) > 0:
                        vsphere_info[name]["networkName"] = devices[0].get("networkName", "")
                logger.debug(f"Extracted vSphere info for MachineSet {name}")
        except (KeyError, IndexError, TypeError) as e:
            logger.warning(f"Failed to extract vSphere info from MachineSet {name}: {e}")
    logger.info(f"Extracted vSphere information from {len(vsphere_info)} MachineSets")
    return vsphere_info


def get_esxi_hosts_per_cluster(si: Any) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get all ESXi hosts per VMware cluster.

    Args:
        si: vSphere service instance

    Returns:
        Dictionary mapping cluster names to lists of ESXi hosts
    """
    clusters_hosts = {}
    try:
        content = si.RetrieveContent()
        container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.ClusterComputeResource], True
        )
        for cluster in container.view:
            cluster_name = cluster.name
            hosts = []
            for host in cluster.host:
                host_info = {
                    "name": host.name,
                    "connection_state": host.runtime.connectionState,
                    "power_state": host.runtime.powerState,
                    "maintenance_mode": host.runtime.inMaintenanceMode,
                    "cpu_cores": host.hardware.cpuInfo.numCpuCores,
                    "memory_size_gb": round(host.hardware.memorySize / (1024**3), 2),
                }
                hosts.append(host_info)
            clusters_hosts[cluster_name] = hosts
        container.Destroy()
        logger.info(f"Retrieved ESXi hosts from {len(clusters_hosts)} VMware clusters")
        return clusters_hosts
    except Exception as e:
        logger.error(f"Failed to retrieve ESXi hosts per cluster: {e}")
        return {}


def map_machinesets_to_clusters(
    machinesets_vsphere_info: Dict[str, Dict[str, Any]],
    clusters_hosts: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    """
    Map OpenShift MachineSets to VMware clusters and their ESXi hosts.

    Args:
        machinesets_vsphere_info: Dictionary of MachineSet vSphere information
        clusters_hosts: Dictionary of VMware clusters and their ESXi hosts

    Returns:
        Mapping between MachineSets and VMware clusters with host counts
    """
    mapping = {}
    for machineset_name, vsphere_info in machinesets_vsphere_info.items():
        resource_pool = vsphere_info.get("resourcePool", "")
        # Extract cluster name from resource pool path
        # Format is typically: /DATACENTER/host/CLUSTER/Resources/optional_resource_pool
        cluster_name = None
        if resource_pool:
            parts = resource_pool.split("/")
            # Find the part after 'host' which should be the cluster name
            for i, part in enumerate(parts):
                if part == "host" and i + 1 < len(parts):
                    cluster_name = parts[i + 1]
                    break
        # If cluster name not found in resource pool, try other methods
        if not cluster_name:
            # Try to match based on server information
            server = vsphere_info.get("server", "")
            for cluster in clusters_hosts:
                if server and server in cluster:
                    cluster_name = cluster
                    break
        if cluster_name and cluster_name in clusters_hosts:
            hosts = clusters_hosts[cluster_name]
            mapping[machineset_name] = {
                "cluster_name": cluster_name,
                "host_count": len(hosts),
                "hosts": hosts,
                "datacenter": vsphere_info.get("datacenter", ""),
                "datastore": vsphere_info.get("datastore", ""),
            }
        else:
            # If we couldn't find a direct match, look for partial matches in cluster names
            matched_cluster = None
            if cluster_name:
                for c_name in clusters_hosts:
                    if cluster_name in c_name:
                        matched_cluster = c_name
                        break
            if matched_cluster:
                hosts = clusters_hosts[matched_cluster]
                mapping[machineset_name] = {
                    "cluster_name": matched_cluster,
                    "host_count": len(hosts),
                    "hosts": hosts,
                    "datacenter": vsphere_info.get("datacenter", ""),
                    "datastore": vsphere_info.get("datastore", ""),
                }
            else:
                mapping[machineset_name] = {
                    "cluster_name": "Unknown",
                    "host_count": 0,
                    "hosts": [],
                    "datacenter": vsphere_info.get("datacenter", ""),
                    "datastore": vsphere_info.get("datastore", ""),
                }
    logger.info(f"Mapped {len(mapping)} MachineSets to VMware clusters")
    return mapping


def generate_report(mapping: Dict[str, Dict[str, Any]], output_format: str = "table") -> None:
    """
    Generate and display a report of MachineSets and their ESXi clusters.

    Args:
        mapping: Mapping between MachineSets and VMware clusters
        output_format: Output format (table or json)
    """
    if output_format.lower() == "json":
        # Create a simplified version for JSON output
        report_data = {}
        for machineset_name, cluster_info in mapping.items():
            report_data[machineset_name] = {
                "cluster_name": cluster_info["cluster_name"],
                "host_count": cluster_info["host_count"],
                "hosts": [host["name"] for host in cluster_info["hosts"]],
                "datacenter": cluster_info.get("datacenter", ""),
                "datastore": cluster_info.get("datastore", ""),
            }
        console.print(json.dumps(report_data, indent=2))
    else:  # Default to table format
        table = Table(title="OpenShift MachineSets to VMware ESXi Clusters Mapping")
        table.add_column("MachineSet", style="cyan")
        table.add_column("VMware Cluster", style="green")
        table.add_column("ESXi Host Count", justify="right", style="yellow")
        table.add_column("Datacenter", style="magenta")
        table.add_column("Datastore", style="blue")
        for machineset_name, cluster_info in mapping.items():
            table.add_row(
                machineset_name,
                cluster_info["cluster_name"],
                str(cluster_info["host_count"]),
                cluster_info.get("datacenter", ""),
                cluster_info.get("datastore", ""),
            )
        console.print(table)
        # If there are hosts, print a detailed hosts table
        if any(info["host_count"] > 0 for info in mapping.values()):
            hosts_table = Table(title="ESXi Hosts Details")
            hosts_table.add_column("Cluster", style="green")
            hosts_table.add_column("Host", style="cyan")
            hosts_table.add_column("CPU Cores", justify="right", style="yellow")
            hosts_table.add_column("Memory (GB)", justify="right", style="yellow")
            hosts_table.add_column("State", style="magenta")
            for machineset_name, cluster_info in mapping.items():
                if cluster_info["host_count"] > 0:
                    for host in cluster_info["hosts"]:
                        hosts_table.add_row(
                            cluster_info["cluster_name"],
                            host["name"],
                            str(host.get("cpu_cores", "N/A")),
                            str(host.get("memory_size_gb", "N/A")),
                            host.get("power_state", "N/A"),
                        )
            console.print(hosts_table)


@click.command()
@click.option("--kubeconfig", default=None, help="Path to the kubeconfig file for OpenShift")
@click.option("--vsphere-host", required=True, help="VMware vSphere host address")
@click.option("--vsphere-user", required=True, help="VMware vSphere username")
@click.option(
    "--vsphere-password",
    help="VMware vSphere password (if not provided, will use environment variable VSPHERE_PASSWORD)",
)
@click.option(
    "--namespace", default="openshift-machine-api", help="Namespace where MachineSets reside"
)
@click.option(
    "--output-format",
    default="table",
    type=click.Choice(["table", "json"]),
    help="Output format (table or json)",
)
@click.option("--disable-ssl", is_flag=True, help="Disable SSL verification for vSphere connection")
def main(
    kubeconfig: Optional[str],
    vsphere_host: str,
    vsphere_user: str,
    vsphere_password: Optional[str],
    namespace: str,
    output_format: str,
    disable_ssl: bool,
) -> None:
    """
    Generate a report on ESXi hosts per VMware cluster for OpenShift MachineSets.

    This script connects to both OpenShift and VMware vSphere to map OpenShift
    MachineSets to their respective ESXi host clusters and count the number of
    ESXi hosts in each cluster.
    """
    # Get vSphere password from environment variable if not provided
    if not vsphere_password:
        vsphere_password = os.environ.get("VSPHERE_PASSWORD")
        if not vsphere_password:
            logger.error(
                "vSphere password not provided and VSPHERE_PASSWORD environment variable not set"
            )
            sys.exit(1)
    # Load Kubernetes configuration
    try:
        if kubeconfig:
            config.load_kube_config(config_file=kubeconfig)
            logger.info(f"Using custom kubeconfig at {kubeconfig}")
        else:
            config.load_kube_config()
            logger.info("Using default kubeconfig")
    except Exception as e:
        logger.error(f"Failed to load Kubernetes config: {e}")
        sys.exit(1)
    # Connect to vSphere
    si = connect_to_vsphere(vsphere_host, vsphere_user, vsphere_password, disable_ssl)
    if not si:
        logger.error("Failed to connect to vSphere")
        sys.exit(1)
    try:
        # Get MachineSets from OpenShift
        crd_client = get_custom_objects_api()
        machinesets = get_machinesets(crd_client, namespace)
        if not machinesets:
            logger.error("No MachineSets found in OpenShift")
            sys.exit(1)
        # Extract vSphere information from MachineSets
        machinesets_vsphere_info = extract_vsphere_info_from_machinesets(machinesets)
        # Get ESXi hosts per VMware cluster
        clusters_hosts = get_esxi_hosts_per_cluster(si)
        # Map MachineSets to VMware clusters
        mapping = map_machinesets_to_clusters(machinesets_vsphere_info, clusters_hosts)
        # Generate and display the report
        generate_report(mapping, output_format)
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        sys.exit(1)
    finally:
        # Disconnect from vSphere
        Disconnect(si)
        logger.info("Disconnected from vSphere")


if __name__ == "__main__":
    main()
