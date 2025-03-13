#!/usr/bin/env python3
"""
OpenShift and VMware ESXi Host Report Generator

This script generates a report of OpenShift MachineSets and their corresponding VMware ESXi hosts.
It can process a single OpenShift cluster using the --kubeconfig option or multiple clusters
using the --clusterlist option (a file with one kubeconfig path per line).

The script connects to the OpenShift API to retrieve MachineSets and their corresponding vSphere
information, then connects to vSphere to retrieve the ESXi hosts where the VMs are running.

The report can be generated in either table or JSON format.

Example usage:
    # Process a single cluster
    python ocp_report_pxesxi.py --kubeconfig /path/to/kubeconfig --output-format json

    # Process multiple clusters from a list file
    python ocp_report_pxesxi.py --clusterlist /path/to/clusterlist.txt --output-format json

    # The clusterlist.txt file should contain one kubeconfig path per line, for example:
    # /path/to/kubeconfig1
    # /path/to/kubeconfig2
    # /path/to/kubeconfig3
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
        # Initialize the Kubernetes API client
        config.load_kube_config()
        v1 = client.CoreV1Api()

        # Get pods with the label name=portworx in the specified namespace
        pods = v1.list_namespaced_pod(namespace=namespace, label_selector="name=portworx")
        pod_count = len(pods.items)
        logger.info(f"Found {pod_count} Portworx pods in namespace '{namespace}'")
        return pod_count
    except client.exceptions.ApiException as e:
        logger.error(f"Error fetching Portworx pods in namespace '{namespace}': {e}")
        return 0


def extract_cluster_name_from_api_url(api_url: str) -> str:
    """
    Extract the cluster name from the Kubernetes API URL.
    
    Args:
        api_url: The Kubernetes API URL (e.g., https://api.hostname.fqdn)
        
    Returns:
        The extracted hostname (e.g., hostname)
    """
    try:
        # Remove the protocol part (https://)
        if "://" in api_url:
            api_url = api_url.split("://")[1]
        
        # Remove the 'api.' prefix if present
        if api_url.startswith("api."):
            api_url = api_url[4:]
        
        # Extract the hostname part (remove domain/fqdn)
        hostname = api_url.split(".")[0]
        
        logger.info(f"Extracted cluster name '{hostname}' from API URL '{api_url}'")
        return hostname
    except Exception as e:
        logger.warning(f"Failed to extract cluster name from API URL '{api_url}': {e}")
        return "unknown-cluster"


@click.command()
@click.option(
    "--kubeconfig", 
    help="Path to a kubeconfig file for a single OpenShift cluster"
)
@click.option(
    "--clusterlist",
    help="Path to a file containing a list of kubeconfig files (one per line)"
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
    kubeconfig: str,
    clusterlist: str,
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

    # Initialize data structure to store results from all clusters
    all_clusters_data = {}
    total_px_pods = 0
    total_esxi_hosts = set()

    # Process each kubeconfig file
    if clusterlist:
        try:
            with open(clusterlist, 'r') as f:
                kubeconfigs = [line.strip() for line in f.readlines()]
        except FileNotFoundError:
            logger.error(f"Cluster list file not found: {clusterlist}")
            sys.exit(1)
    elif kubeconfig:
        kubeconfigs = [kubeconfig]
    else:
        logger.error("Either --kubeconfig or --clusterlist must be provided")
        sys.exit(1)

    for config_file in kubeconfigs:
        try:
            # Load Kubernetes configuration
            if not os.path.isfile(config_file):
                logger.error(f"Kubeconfig file not found: {config_file}")
                continue

            # Load the specific kubeconfig
            config.load_kube_config(config_file=config_file)
            logger.info(f"Using kubeconfig: {config_file}")

            # Get the API host to extract cluster name
            api_host = client.Configuration._default.host
            cluster_name = extract_cluster_name_from_api_url(api_host)
            logger.info(f"Processing cluster: {cluster_name}")

            # Get MachineSets from OpenShift
            logger.info(f"Retrieving MachineSets from namespace '{namespace}'")
            try:
                custom_api = get_custom_objects_api()
                machinesets = get_machinesets(custom_api, namespace)
                if not machinesets:
                    logger.warning(f"No MachineSets found in namespace '{namespace}' for cluster {cluster_name}")
                    continue
                logger.info(f"Found {len(machinesets)} MachineSets in cluster {cluster_name}")
            except Exception as e:
                logger.error(f"Error retrieving MachineSets from cluster {cluster_name}: {str(e)}")
                continue

            # Extract vSphere information from MachineSets
            try:
                logger.info(f"Extracting vSphere information from MachineSets in cluster {cluster_name}")
                vsphere_info = extract_vsphere_info_from_machinesets(machinesets)
                if not vsphere_info:
                    logger.warning(f"No vSphere information found in MachineSets for cluster {cluster_name}")
                    continue
                logger.info(f"Extracted vSphere information from {len(vsphere_info)} MachineSets in cluster {cluster_name}")
            except Exception as e:
                logger.error(f"Error extracting vSphere information from cluster {cluster_name}: {str(e)}")
                continue

            # Get VMware credentials from Secret if specified
            cluster_vsphere_host = vsphere_host
            cluster_vsphere_user = vsphere_user
            cluster_vsphere_password = vsphere_password

            if credentials_secret:
                try:
                    logger.info(
                        f"Retrieving VMware credentials from Secret '{credentials_secret}' in namespace '{credentials_namespace}'"
                    )
                    credentials = get_vmware_credentials_from_secret(
                        credentials_namespace, credentials_secret
                    )
                    if not credentials:
                        logger.error(f"Secret exists but doesn't contain required VMware credentials for cluster {cluster_name}")
                        continue
                    first_key = list(vsphere_info.keys())[0]
                    cluster_vsphere_host = vsphere_info[first_key]['server']
                    cluster_vsphere_user = credentials["username"]
                    cluster_vsphere_password = credentials["password"]
                    logger.info(f"Successfully retrieved VMware credentials from Secret for cluster {cluster_name}")

                except Exception as e:
                    logger.error(f"Error retrieving credentials from Secret for cluster {cluster_name}: {str(e)}")
                    continue
            else:
                # Get vSphere password from environment variable if not provided
                if not cluster_vsphere_password:
                    cluster_vsphere_password = os.environ.get("VSPHERE_PASSWORD")
                    if cluster_vsphere_password:
                        logger.info("Using vSphere password from VSPHERE_PASSWORD environment variable")

            # Validate required VMware credentials
            missing_credentials = []
            if not cluster_vsphere_host:
                missing_credentials.append("vSphere host")
            if not cluster_vsphere_user:
                missing_credentials.append("vSphere username")
            if not cluster_vsphere_password:
                missing_credentials.append("vSphere password")

            if missing_credentials:
                logger.error(f"Missing required VMware credentials for cluster {cluster_name}: {', '.join(missing_credentials)}")
                logger.error("Provide them via command line options, environment variables, or Secrets")
                continue

            # Connect to vSphere
            logger.info(f"Connecting to vSphere host: {cluster_vsphere_host} for cluster {cluster_name}")
            si = None
            try:
                si = connect_to_vsphere(cluster_vsphere_host, cluster_vsphere_user, cluster_vsphere_password, disable_ssl)
                if not si:
                    logger.error(f"Failed to establish connection to vSphere for cluster {cluster_name}")
                    continue
                logger.info(f"Successfully connected to vSphere for cluster {cluster_name}")
            except Exception as e:
                logger.error(f"Error connecting to vSphere for cluster {cluster_name}: {str(e)}")
                continue

            try:
                # Get ESXi hosts per VMware cluster
                logger.info(f"Retrieving ESXi hosts information from vSphere for cluster {cluster_name}")
                hosts_per_cluster = get_esxi_hosts_per_cluster(si)
                if not hosts_per_cluster:
                    logger.error(f"No VMware clusters found or error retrieving ESXi hosts for cluster {cluster_name}")
                    continue
                logger.info(
                    f"Found {len(hosts_per_cluster)} VMware clusters with {sum(len(hosts) for hosts in hosts_per_cluster.values())} ESXi hosts for cluster {cluster_name}"
                )

                # Map MachineSets to VMware clusters
                logger.info(f"Mapping OpenShift MachineSets to VMware clusters for cluster {cluster_name}")
                mapping = map_machinesets_to_clusters(vsphere_info, hosts_per_cluster)
                if not mapping:
                    logger.warning(f"Could not map any MachineSets to VMware clusters for cluster {cluster_name}")
                    continue
                logger.info(f"Successfully mapped {len(mapping)} MachineSets to VMware clusters for cluster {cluster_name}")

                # Count Portworx pods
                px_pod_count = count_portworx_pods(px_namespace)
                total_px_pods += px_pod_count
                logger.info(f"Found {px_pod_count} Portworx pods in namespace '{px_namespace}' for cluster {cluster_name}")

                # Store the results for this cluster
                all_clusters_data[cluster_name] = {
                    "mapping": mapping,
                    "portworx_pods_count": px_pod_count
                }

                # Track all unique ESXi hosts
                for cluster_info in mapping.values():
                    for host in cluster_info["hosts"]:
                        total_esxi_hosts.add(host["name"])

            finally:
                # Disconnect from vSphere
                if si:
                    logger.info(f"Disconnecting from vSphere for cluster {cluster_name}")
                    Disconnect(si)

        except Exception as e:
            logger.error(f"Error processing kubeconfig {config_file}: {str(e)}")
            continue

    # If no clusters were successfully processed
    if not all_clusters_data:
        logger.error("No clusters were successfully processed")
        sys.exit(1)

    # Generate combined report
    try:
        logger.info("Generating combined report for all clusters")
        
        # Handle brief output format
        if brief:
            # Generate a summary of clusters and their ESXi host counts
            all_clusters_summary = {}
            total_px_pods = 0
            total_esxi_hosts = 0
            
            # Collect summary data from all clusters
            for cluster_name, cluster_data in all_clusters_data.items():
                mapping = cluster_data["mapping"]
                px_pod_count = cluster_data["portworx_pods_count"]
                total_px_pods += px_pod_count
                
                # Generate cluster summary (cluster name -> host count)
                cluster_summary = generate_cluster_summary(mapping)
                
                # Add to all clusters summary
                for vmware_cluster, host_count in cluster_summary.items():
                    key = f"{cluster_name}/{vmware_cluster}"
                    all_clusters_summary[key] = host_count
                    total_esxi_hosts += host_count
            
            if output_format.lower() == "json":
                # Create brief JSON output
                output_data = {
                    "portworx_pods_count": total_px_pods,
                    "total_esxi_hosts": total_esxi_hosts,
                    "clusters": {}
                }
                
                # Group by OpenShift cluster
                for full_cluster_name, host_count in all_clusters_summary.items():
                    ocp_cluster, vmware_cluster = full_cluster_name.split("/", 1)
                    
                    if ocp_cluster not in output_data["clusters"]:
                        output_data["clusters"][ocp_cluster] = {
                            "vmware_clusters": {}
                        }
                    
                    output_data["clusters"][ocp_cluster]["vmware_clusters"][vmware_cluster] = {
                        "hosts_count": host_count
                    }
                
                console.print(json.dumps(output_data, indent=2))
            else:  # Default to table format
                # Show summary information
                console.print(f"[bold]Total Portworx pods across all clusters:[/bold] {total_px_pods}")
                console.print(f"[bold]Total ESXi hosts across all clusters:[/bold] {total_esxi_hosts}")
                console.print("")
                
                # Create a table with all clusters
                table = Table(title="OpenShift and VMware Clusters Summary")
                table.add_column("OpenShift Cluster", style="cyan")
                table.add_column("VMware Cluster", style="green")
                table.add_column("ESXi Host Count", justify="right", style="yellow")
                
                # Sort by OpenShift cluster and then by VMware cluster
                for full_cluster_name in sorted(all_clusters_summary.keys()):
                    ocp_cluster, vmware_cluster = full_cluster_name.split("/", 1)
                    host_count = all_clusters_summary[full_cluster_name]
                    table.add_row(ocp_cluster, vmware_cluster, str(host_count))
                
                console.print(table)
            
            return
        
        # Handle detailed output formats (non-brief)
        if output_format.lower() == "json":
            # Create a new JSON structure organized by cluster, datacenter, and VMware cluster
            report_data = {}
            
            # Process each OpenShift cluster
            for cluster_name, cluster_data in all_clusters_data.items():
                mapping = cluster_data["mapping"]
                px_pod_count = cluster_data["portworx_pods_count"]
                
                # Track unique hosts for this cluster
                cluster_hosts = set()
                
                # First pass: collect all datacenter, cluster, and host information for this cluster
                datacenter_clusters = {}
                for machineset_name, cluster_info in mapping.items():
                    datacenter = cluster_info.get("datacenter", "Unknown")
                    vmware_cluster_name = cluster_info["cluster_name"]
                    
                    # Initialize datacenter if not seen before
                    if datacenter not in datacenter_clusters:
                        datacenter_clusters[datacenter] = {}
                    
                    # Initialize VMware cluster if not seen before
                    if vmware_cluster_name not in datacenter_clusters[datacenter]:
                        datacenter_clusters[datacenter][vmware_cluster_name] = {
                            "hosts": set(),
                            "hosts_count": 0
                        }
                    
                    # Add unique hosts to this VMware cluster
                    for host in cluster_info["hosts"]:
                        host_name = host["name"]
                        datacenter_clusters[datacenter][vmware_cluster_name]["hosts"].add(host_name)
                        cluster_hosts.add(host_name)
                
                # Add this OpenShift cluster's data to the report
                report_data[cluster_name] = {
                    "portworx_pods_count": px_pod_count,
                    "total_esxi_hosts": len(cluster_hosts)
                }
                
                # Add datacenter and VMware cluster information
                for datacenter, vmware_clusters in datacenter_clusters.items():
                    if "datacenters" not in report_data[cluster_name]:
                        report_data[cluster_name]["datacenters"] = {}
                    
                    report_data[cluster_name]["datacenters"][datacenter] = {}
                    for vmware_cluster_name, vmware_cluster_data in vmware_clusters.items():
                        # Convert set to sorted list for JSON serialization
                        host_list = sorted(list(vmware_cluster_data["hosts"]))
                        hosts_count = len(host_list)
                        
                        report_data[cluster_name]["datacenters"][datacenter][vmware_cluster_name] = {
                            "hosts": host_list,
                            "hosts_count": hosts_count
                        }
            
            # Output the JSON
            console.print(json.dumps(report_data, indent=2))
        else:  # Default to table format
            # Create a table for each cluster
            for cluster_name, cluster_data in all_clusters_data.items():
                mapping = cluster_data["mapping"]
                px_pod_count = cluster_data["portworx_pods_count"]
                
                # Get unique hosts for this cluster
                cluster_hosts = set()
                for machineset_name, cluster_info in mapping.items():
                    for host in cluster_info["hosts"]:
                        cluster_hosts.add(host["name"])
                
                console.print(f"[bold]Cluster: {cluster_name}[/bold]")
                console.print(f"[bold]Portworx pods in namespace '{px_namespace}':[/bold] {px_pod_count}")
                console.print(f"[bold]Total unique ESXi hosts in this cluster:[/bold] {len(cluster_hosts)}")
                console.print("")
                
                # Show the main table for this cluster
                table = Table(title=f"OpenShift MachineSets to VMware ESXi Clusters Mapping for {cluster_name}")
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
                
                # If there are hosts, print a detailed hosts table for this cluster
                if any(info["host_count"] > 0 for info in mapping.values()):
                    hosts_table = Table(title=f"ESXi Hosts Details for {cluster_name}")
                    hosts_table.add_column("Cluster", style="green")
                    hosts_table.add_column("Host", style="cyan")
                    hosts_table.add_column("CPU Cores", justify="right", style="yellow")
                    hosts_table.add_column("Memory (GB)", justify="right", style="yellow")
                    hosts_table.add_column("State", style="magenta")
                    
                    # Track unique hosts using a set of (cluster_name, host_name) tuples
                    seen_hosts = set()
                    
                    # Collect all unique hosts across all clusters
                    unique_hosts = []
                    for machineset_name, cluster_info in mapping.items():
                        if cluster_info["host_count"] > 0:
                            for host in cluster_info["hosts"]:
                                # Create a unique identifier for each host
                                host_key = (cluster_info["cluster_name"], host["name"])
                                if host_key not in seen_hosts:
                                    seen_hosts.add(host_key)
                                    unique_hosts.append({
                                        "cluster_name": cluster_info["cluster_name"],
                                        "host": host
                                    })
                    
                    # Sort unique hosts by cluster name and then by host name
                    unique_hosts.sort(key=lambda x: (x["cluster_name"], x["host"]["name"]))
                    
                    # Add rows for unique hosts
                    for host_info in unique_hosts:
                        host = host_info["host"]
                        hosts_table.add_row(
                            host_info["cluster_name"],
                            host["name"],
                            str(host.get("cpu_cores", "N/A")),
                            str(host.get("memory_size_gb", "N/A")),
                            host.get("power_state", "N/A"),
                        )
                    console.print(hosts_table)
                
                console.print("")  # Add a blank line between clusters
                
    except Exception as e:
        logger.error(f"Error generating combined report: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
