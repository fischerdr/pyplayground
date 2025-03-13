#!/usr/bin/env python3
"""
OpenShift VMware Cluster Report Generator.

This script interacts with OpenShift Kubernetes and VMware vSphere to generate
a report on the number of ESXi hosts per VMware cluster. It maps OpenShift
MachineSets to their respective ESXi host clusters.

Date: 2025-03-10
"""
import base64
import json
import os
import socket
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


def get_vmware_credentials_from_secret(
    namespace: str, secret_name: str
) -> Optional[Dict[str, str]]:
    """
    Retrieve VMware credentials from a Kubernetes Secrets.

    Args:
        namespace: Kubernetes namespace containing the Secrets
        secret_name: Name of the Secrets with VMware credentials

    Returns:
        Dictionary containing VMware host, username, and password if successful,
        None otherwise
    """
    try:
        # Initialize Kubernetes client
        v1 = client.CoreV1Api()

        # Retrieve the Secrets
        configmap = v1.read_namespaced_secret(secret_name, namespace)

        # Extract VMware credentials
        credentials = {}

        if "VSPHERE_USER" in configmap.data:
            credentials["username"] = (
                base64.b64decode(configmap.data["VSPHERE_USER"]).decode('utf-8').strip()
            )
        else:
            logger.error(f"VMware username not found in Secrets {secret_name}")
            return None

        if "VSPHERE_PASSWORD" in configmap.data:
            credentials["password"] = (
                base64.b64decode(configmap.data["VSPHERE_PASSWORD"]).decode('utf-8').strip()
            )
        else:
            logger.error(f"VMware password not found in Secrets {secret_name}")
            return None

        logger.info(f"Successfully retrieved VMware credentials from Secrets {secret_name}")
        logger.info(f"Secrets {credentials}")
        return credentials

    except client.exceptions.ApiException as e:
        logger.error(f"Kubernetes API error when retrieving Secrets: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Error retrieving VMware credentials from Secrets: {str(e)}")
        return None


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


def generate_cluster_summary(mapping: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    """
    Generate a summary of clusters and their ESXi host counts.

    Args:
        mapping: Mapping between MachineSets and VMware clusters

    Returns:
        Dictionary mapping cluster names to their ESXi host counts
    """
    cluster_summary = {}
    for machineset_info in mapping.values():
        cluster_name = machineset_info["cluster_name"]
        # Only count each cluster once
        if cluster_name not in cluster_summary:
            cluster_summary[cluster_name] = machineset_info["host_count"]

    logger.info(f"Generated summary for {len(cluster_summary)} VMware clusters")
    return cluster_summary


def count_portworx_pods(namespace: str = "portworx") -> int:
    """
    Count the number of pods with label name=portworx in the specified namespace.

    Args:
        namespace: Namespace to search for Portworx pods (default: "portworx")

    Returns:
        Number of Portworx pods found
    """
    try:
        v1 = client.CoreV1Api()
        pods = v1.list_namespaced_pod(namespace=namespace, label_selector="name=portworx")
        pod_count = len(pods.items)
        logger.info(f"Found {pod_count} Portworx pods in namespace '{namespace}'")
        return pod_count
    except client.exceptions.ApiException as e:
        logger.error(f"Error fetching Portworx pods in namespace '{namespace}': {e}")
        return 0


def generate_report(
    mapping: Dict[str, Dict[str, Any]],
    output_format: str = "table",
    brief: bool = False,
    px_namespace: str = "portworx",
) -> None:
    """
    Generate and display a report of MachineSets and their ESXi clusters.

    Args:
        mapping: Mapping between MachineSets and VMware clusters
        output_format: Output format (table or json)
        brief: Whether to generate a brief report showing only clusters and host counts
        px_namespace: Namespace to search for Portworx pods (default: "portworx")
    """
    # Get Portworx pod count
    px_pod_count = count_portworx_pods(px_namespace)

    if brief:
        # Generate a summary of clusters and their ESXi host counts
        cluster_summary = generate_cluster_summary(mapping)

        if output_format.lower() == "json":
            # Add Portworx pod count to the JSON output
            output_data = {"portworx_pods": px_pod_count, "clusters": cluster_summary}
            console.print(json.dumps(output_data, indent=2))
        else:  # Default to table format
            # First show Portworx pod count
            console.print(
                f"[bold]Portworx pods in namespace '{px_namespace}':[/bold] {px_pod_count}"
            )

            # Then show cluster table
            table = Table(title="VMware Clusters and ESXi Host Counts")
            table.add_column("Cluster Name", style="green")
            table.add_column("ESXi Host Count", justify="right", style="yellow")

            for cluster_name, host_count in cluster_summary.items():
                table.add_row(cluster_name, str(host_count))

            console.print(table)
        return

    if output_format.lower() == "json":
        # Create a simplified version for JSON output
        report_data = {"portworx_pods": px_pod_count, "machinesets": {}}
        for machineset_name, cluster_info in mapping.items():
            report_data["machinesets"][machineset_name] = {
                "cluster_name": cluster_info["cluster_name"],
                "host_count": cluster_info["host_count"],
                "hosts": [host["name"] for host in cluster_info["hosts"]],
                "datacenter": cluster_info.get("datacenter", ""),
                "datastore": cluster_info.get("datastore", ""),
            }
        console.print(json.dumps(report_data, indent=2))
    else:  # Default to table format
        # First show Portworx pod count
        console.print(f"[bold]Portworx pods in namespace '{px_namespace}':[/bold] {px_pod_count}")

        # Then show the main table
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
@click.option(
    "--kubeconfig", default=None, help="Path to the kubeconfig file for OpenShift", required=True
)
@click.option("--vsphere-host", help="VMware vSphere host address")
@click.option("--vsphere-user", help="VMware vSphere username")
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
@click.option(
    "--brief",
    is_flag=True,
    help="Generate a brief report showing only cluster names and ESXi host counts",
)
@click.option(
    "--credentials-secret",
    help="Name of the Secret containing VMware credentials",
    default="px-vsphere-secret",
)
@click.option(
    "--credentials-namespace",
    default="portworx",
    help="Namespace containing the VMware credentials Secret",
)
@click.option("--timeout", default=30, type=int, help="Timeout in seconds for API calls")
@click.option(
    "--px-namespace", default="portworx", help="Namespace where Portworx pods are running"
)
def main(
    kubeconfig: Optional[str],
    vsphere_host: Optional[str],
    vsphere_user: Optional[str],
    vsphere_password: Optional[str],
    namespace: str,
    output_format: str,
    disable_ssl: bool,
    brief: bool,
    credentials_secret: Optional[str],
    credentials_namespace: str,
    timeout: int,
    px_namespace: str,
) -> None:
    """
    Generate a report on ESXi hosts per VMware cluster for OpenShift MachineSets.

    This script connects to both OpenShift and VMware vSphere to map OpenShift
    MachineSets to their respective ESXi host clusters and count the number of
    ESXi hosts in each cluster.
    """
    # Set timeout for API calls
    socket.setdefaulttimeout(timeout)

    # Load Kubernetes configuration
    try:
        if kubeconfig:
            if not os.path.isfile(kubeconfig):
                logger.error(f"Kubeconfig file not found: {kubeconfig}")
                sys.exit(1)
            config.load_kube_config(config_file=kubeconfig)
            logger.info(f"Using custom kubeconfig: {kubeconfig}")
        else:
            try:
                config.load_kube_config()
                logger.info("Using default kubeconfig")
            except config.config_exception.ConfigException:
                try:
                    config.load_incluster_config()
                    logger.info("Using in-cluster configuration")
                except config.config_exception.ConfigException:
                    logger.error("Failed to load any Kubernetes configuration")
                    sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to load Kubernetes configuration: {str(e)}")
        sys.exit(1)

    try:
        # Get MachineSets from OpenShift
        logger.info(f"Retrieving MachineSets from namespace '{namespace}'")
        try:
            custom_api = get_custom_objects_api()
            machinesets = get_machinesets(custom_api, namespace)
            if not machinesets:
                logger.error(f"No MachineSets found in namespace '{namespace}'")
                sys.exit(1)
            logger.info(f"Found {len(machinesets)} MachineSets")
        except Exception as e:
            logger.error(f"Error retrieving MachineSets: {str(e)}")
            sys.exit(1)

        # Extract vSphere information from MachineSets
        try:
            logger.info("Extracting vSphere information from MachineSets")
            vsphere_info = extract_vsphere_info_from_machinesets(machinesets)
            if not vsphere_info:
                logger.error("No vSphere information found in MachineSets")
                sys.exit(1)
            logger.info(f"Extracted vSphere information from {len(vsphere_info)} MachineSets")
        except Exception as e:
            logger.error(f"Error extracting vSphere information: {str(e)}")
            sys.exit(1)

        # Get VMware credentials from Secret if specified
        if credentials_secret:
            try:
                logger.info(
                    f"Retrieving VMware credentials from Secret '{credentials_secret}' in namespace '{credentials_namespace}'"
                )
                credentials = get_vmware_credentials_from_secret(
                    credentials_namespace, credentials_secret
                )
                if not credentials:
                    logger.error("Secret exists but doesn't contain required VMware credentials")
                    sys.exit(1)
                first_key = list(vsphere_info.keys())[0]
                vsphere_host = vsphere_info[first_key]['server']
                vsphere_user = credentials["username"]
                vsphere_password = credentials["password"]
                logger.info("Successfully retrieved VMware credentials from Secret")

            except Exception as e:
                logger.error(f"Error retrieving credentials from Secret: {str(e)}")
                sys.exit(1)
        else:
            # Get vSphere password from environment variable if not provided
            if not vsphere_password:
                vsphere_password = os.environ.get("VSPHERE_PASSWORD")
                if vsphere_password:
                    logger.info("Using vSphere password from VSPHERE_PASSWORD environment variable")

        # Validate required VMware credentials
        missing_credentials = []
        if not vsphere_host:
            missing_credentials.append("vSphere host")
        if not vsphere_user:
            missing_credentials.append("vSphere username")
        if not vsphere_password:
            missing_credentials.append("vSphere password")

        if missing_credentials:
            logger.error(f"Missing required VMware credentials: {', '.join(missing_credentials)}")
            logger.error("Provide them via command line options, environment variables, or Secrets")
            sys.exit(1)

        # Connect to vSphere
        logger.info(f"Connecting to vSphere host: {vsphere_host}")
        si = None
        try:
            si = connect_to_vsphere(vsphere_host, vsphere_user, vsphere_password, disable_ssl)
            if not si:
                logger.error("Failed to establish connection to vSphere")
                sys.exit(1)
            logger.info("Successfully connected to vSphere")
        except Exception as e:
            logger.error(f"Error connecting to vSphere: {str(e)}")
            sys.exit(1)

        # Get ESXi hosts per VMware cluster
        try:
            logger.info("Retrieving ESXi hosts information from vSphere")
            hosts_per_cluster = get_esxi_hosts_per_cluster(si)
            if not hosts_per_cluster:
                logger.error("No VMware clusters found or error retrieving ESXi hosts")
                sys.exit(1)
            logger.info(
                f"Found {len(hosts_per_cluster)} VMware clusters with {sum(len(hosts) for hosts in hosts_per_cluster.values())} ESXi hosts"
            )
        except Exception as e:
            logger.error(f"Error retrieving ESXi hosts information: {str(e)}")
            sys.exit(1)

        # Map MachineSets to VMware clusters
        try:
            logger.info("Mapping OpenShift MachineSets to VMware clusters")
            mapping = map_machinesets_to_clusters(vsphere_info, hosts_per_cluster)
            if not mapping:
                logger.warning("Could not map any MachineSets to VMware clusters")
            else:
                logger.info(f"Successfully mapped {len(mapping)} MachineSets to VMware clusters")
        except Exception as e:
            logger.error(f"Error mapping MachineSets to VMware clusters: {str(e)}")
            sys.exit(1)

        # Generate report
        try:
            logger.info("Generating report")
            generate_report(mapping, output_format, brief, px_namespace)
        except Exception as e:
            logger.error(f"Error generating report: {str(e)}")
            sys.exit(1)

    finally:
        if not si:
            # Disconnect from vSphere
            logger.info("Disconnecting from vSphere")
            Disconnect(si)


if __name__ == "__main__":
    main()
