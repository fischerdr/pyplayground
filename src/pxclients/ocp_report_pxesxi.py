#!/usr/bin/env python3
"""OpenShift and VMware ESXi Host Report Generator.

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
import logging
import os
import socket
import ssl
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import click
from kubernetes import client, config
from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim
from rich.console import Console
from rich.table import Table
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

# Import utility functions
from utils.config_utils import get_env_var, load_env_file
from utils.k8s_utils import get_custom_objects_api
from utils.logging_utils import get_logger, setup_logging

# SSL Certs location
# Consider making this configurable or removing if default context works for most cases
DEFAULT_FALLBACK_CERT_PATH = "/path/to/your/cert.pem"

# Set up logging
logger = get_logger(__name__)

# Initialize rich console for output
console = Console()


@dataclass
class VSphereConnectionParams:
    """Dataclass to hold vSphere connection parameters."""

    host: str
    user: str
    password: str
    disable_ssl: bool
    effective_cert_path: Optional[str]


def get_vmware_credentials_from_secret(
    namespace: str, secret_name: str
) -> Optional[Dict[str, str]]:
    """Retrieve VMware credentials from a Kubernetes Secrets.

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
        secret_obj = v1.read_namespaced_secret(secret_name, namespace)  # Renamed from configmap

        # Extract VMware credentials
        credentials = {}

        if "VSPHERE_USER" in secret_obj.data:
            credentials["username"] = (
                base64.b64decode(secret_obj.data["VSPHERE_USER"]).decode("utf-8").strip()
            )
        else:
            logger.error(f"VMware username not found in Secrets {secret_name}")
            return None

        if "VSPHERE_PASSWORD" in secret_obj.data:
            credentials["password"] = (
                base64.b64decode(secret_obj.data["VSPHERE_PASSWORD"]).decode("utf-8").strip()
            )
        else:
            logger.error(f"VMware password not found in Secrets {secret_name}")
            return None

        logger.info(f"Successfully retrieved VMware credentials from Secrets {secret_name}")
        return credentials

    except client.exceptions.ApiException as e:
        logger.error(f"Kubernetes API error when retrieving Secrets: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Error retrieving VMware credentials from Secrets: {str(e)}")
        return None


def _get_effective_vsphere_cert_path(vsphere_cert_path_cli: Optional[str]) -> Optional[str]:
    """Determines and logs the effective SSL certificate path for vSphere connection."""
    if vsphere_cert_path_cli:
        logger.info(f"Using vSphere SSL certificate path from CLI option: {vsphere_cert_path_cli}")
        # Path existence is checked by Click option type=click.Path(exists=True...)
        return vsphere_cert_path_cli

    env_cert_path = get_env_var("VSPHERE_SSL_CERT_PATH", required=False)
    if env_cert_path:
        logger.info(
            f"Using vSphere SSL certificate path from VSPHERE_SSL_CERT_PATH env var: {env_cert_path}"
        )
        return env_cert_path

    # Check if fallback exists and is a file. If not, treat as no specific path provided for custom cert loading.
    if os.path.isfile(DEFAULT_FALLBACK_CERT_PATH):
        logger.info(
            f"Using vSphere SSL certificate path from default fallback: {DEFAULT_FALLBACK_CERT_PATH}"
        )
        return DEFAULT_FALLBACK_CERT_PATH
    else:
        logger.info(
            f"Default fallback SSL certificate not found at: {DEFAULT_FALLBACK_CERT_PATH}. "
            "Will use system's default CAs if SSL is enabled and no other path is specified."
        )
        return None


def _create_ssl_context(disable_ssl: bool, effective_cert_path: Optional[str]) -> ssl.SSLContext:
    """Creates an SSL context for the vSphere connection based on provided path and disable_ssl flag."""
    if disable_ssl:
        logger.info("SSL verification disabled for vSphere connection.")
        return ssl._create_unverified_context()

    context = ssl.create_default_context()
    if effective_cert_path and os.path.isfile(effective_cert_path):
        try:
            context.load_verify_locations(effective_cert_path)
            logger.info(
                f"Loaded SSL certificate for vSphere connection from: {effective_cert_path}"
            )
        except Exception as cert_error:
            logger.warning(
                f"Failed to load SSL certificate from {effective_cert_path}: {cert_error}. "
                "Falling back to default SSL verification using system CAs."
            )
    elif effective_cert_path and not os.path.isfile(effective_cert_path):
        logger.warning(
            f"Specified SSL certificate file not found at {effective_cert_path}. "
            "Falling back to default SSL verification using system CAs."
        )
    else:
        logger.info(
            "No custom SSL certificate path provided or resolved path not found. "
            "Using default SSL verification with system CAs."
        )
    return context


def connect_to_vsphere(
    params: VSphereConnectionParams,
) -> Optional[Any]:  # TODO: Replace Any with specific pyVmomi ServiceInstance type
    """Establish connection to VMware vSphere.

    Args:
        params: VSphereConnectionParams object containing all connection details.

    Returns:
        Service instance object if connection is successful, None otherwise
    """
    try:
        # Use parameters from the dataclass
        context = _create_ssl_context(params.disable_ssl, params.effective_cert_path)

        si = SmartConnect(
            host=params.host, user=params.user, pwd=params.password, sslContext=context
        )
        if not si:
            logger.error(f"Failed to connect to vSphere host: {params.host}")
            return None
        logger.info(f"Successfully connected to vSphere host: {params.host}")
        return si
    except Exception as e:
        logger.error(f"Failed to connect to vSphere host {params.host}: {e}")
        return None


def get_machinesets(
    crd_client: Optional[client.CustomObjectsApi] = None,
    namespace: str = "openshift-machine-api",
) -> List[Dict[str, Any]]:
    """Retrieve all MachineSets from OpenShift.

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
    """Extract VMware vSphere information from MachineSets.

    Args:
        machinesets: List of MachineSet objects

    Returns:
        Dictionary mapping MachineSet names to their vSphere information
    """
    vsphere_info_map = {}  # Renamed from vsphere_info to avoid confusion
    for machineset in machinesets:
        try:
            name = machineset["metadata"]["name"]
            # Navigate through the nested structure to find provider spec
            provider_spec = machineset["spec"]["template"]["spec"]["providerSpec"]["value"]
            # Check if this is a vSphere provider
            if provider_spec.get("kind") == "VSphereMachineProviderSpec":
                vsphere_info_map[name] = {
                    "datacenter": provider_spec.get("workspace", {}).get("datacenter", ""),
                    "datastore": provider_spec.get("workspace", {}).get("datastore", ""),
                    "folder": provider_spec.get("workspace", {}).get("folder", ""),
                    "resourcePool": provider_spec.get("workspace", {}).get("resourcePool", ""),
                    "server": provider_spec.get("workspace", {}).get("server", ""),
                    "template": provider_spec.get("template", ""),
                    "diskGiB": provider_spec.get("diskGiB", 0),
                    "memoryMiB": provider_spec.get("memoryMiB", 0),
                    "numCPUs": provider_spec.get("numCPUs", 0),
                    "networkName": "",  # Initialize networkName
                }
                # Extract network information if available
                if "network" in provider_spec and "devices" in provider_spec["network"]:
                    devices = provider_spec["network"]["devices"]
                    if devices and len(devices) > 0:
                        vsphere_info_map[name]["networkName"] = devices[0].get("networkName", "")
                logger.debug(f"Extracted vSphere info for MachineSet {name}")
        except (KeyError, IndexError, TypeError) as e:
            logger.warning(f"Failed to extract vSphere info from MachineSet {name}: {e}")
    logger.info(f"Extracted vSphere information from {len(vsphere_info_map)} MachineSets")
    return vsphere_info_map


def extract_vmware_clusters_from_machinesets(
    machinesets_vsphere_info: Dict[str, Dict[str, Any]],
) -> List[str]:
    """Extract unique VMware cluster names from MachineSets vSphere information.

    Args:
        machinesets_vsphere_info: Dictionary of MachineSet vSphere information

    Returns:
        List of unique VMware cluster names
    """
    cluster_names = set()
    for _, vsphere_info_item in machinesets_vsphere_info.items():  # Renamed vsphere_info
        resource_pool = vsphere_info_item.get("resourcePool", "")
        # Extract cluster name from resource pool path
        # Format is typically: /DATACENTER/host/CLUSTER/Resources/optional_resource_pool
        if resource_pool:
            parts = resource_pool.split("/")
            # Find the part after 'host' which should be the cluster name
            for i, part in enumerate(parts):
                if part == "host" and i + 1 < len(parts):
                    cluster_name = parts[i + 1]
                    cluster_names.add(cluster_name)
                    break

    logger.info(f"Extracted {len(cluster_names)} unique VMware cluster names from MachineSets")
    return list(cluster_names)


def get_filtered_clusters(si: Any, cluster_names: List[str]) -> List[Any]:  # TODO: Specific types
    """Get filtered VMware clusters by name using PropertyCollector for efficiency.

    Args:
        si: vSphere service instance
        cluster_names: List of cluster names to filter

    Returns:
        List of filtered cluster objects
    """
    try:
        content = si.RetrieveContent()

        # Create a view of the inventory
        container_view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.ClusterComputeResource], True
        )

        # Create property specification to specify which properties to retrieve
        property_spec = vim.PropertySpec(type=vim.ClusterComputeResource, pathSet=["name"])

        # Create filter specification to define the filter conditions
        filter_spec = vim.PropertyFilterSpec(
            objectSet=[
                vim.ObjectSpec(
                    obj=container_view,
                    skip=False,
                    selectSet=[
                        vim.TraversalSpec(
                            name="traverseEntities", type=vim.ContainerView, path="view", skip=False
                        )
                    ],
                )
            ],
            propSet=[property_spec],
            reportMissingObjectsInResults=False,
        )

        # Perform the query using PropertyCollector
        collector = content.propertyCollector
        query_result = collector.RetrievePropertiesEx(
            specSet=[filter_spec], options=vim.RetrieveOptions()
        )

        cluster_list = []
        if query_result:  # Check if query_result is not None
            for result in query_result.objects:
                cluster = result.obj
                if cluster.name in cluster_names:
                    cluster_list.append(cluster)

        # Destroy the container view
        container_view.Destroy()

        logger.info(
            f"Found {len(cluster_list)} VMware clusters matching the filter criteria (out of {len(cluster_names)} requested)"
        )
        return cluster_list
    except Exception as e:
        logger.error(f"Failed to retrieve filtered clusters: {e}")
        return []


# Retry both connection and data retrieval
@retry(
    stop=stop_after_attempt(3),  # Retry up to 3 times
    wait=wait_fixed(5),  # Wait 5 seconds between attempts
    retry=retry_if_exception_type(Exception),  # Retry on any exception
)
def get_esxi_hosts_per_cluster(
    si: Any, cluster_names: List[str]  # TODO: Specific types
) -> Dict[str, List[Dict[str, Any]]]:
    """Get all ESXi hosts per VMware cluster.

    Args:
        si: vSphere service instance
        cluster_names: List of cluster names to filter the query

    Returns:
        Dictionary mapping cluster names to lists of ESXi hosts
    """
    clusters_hosts = {}
    try:
        # Use the efficient PropertyCollector-based filtering
        filtered_clusters = get_filtered_clusters(si, cluster_names)
        for cluster in filtered_clusters:
            cluster_name = cluster.name
            hosts = []
            for host_system in cluster.host:  # Renamed host to host_system
                host_info = {
                    "name": host_system.name,
                    "connection_state": host_system.runtime.connectionState,
                    "power_state": host_system.runtime.powerState,
                    "maintenance_mode": host_system.runtime.inMaintenanceMode,
                    "cpu_cores": host_system.hardware.cpuInfo.numCpuCores,
                    "memory_size_gb": round(host_system.hardware.memorySize / (1024**3), 2),
                }
                hosts.append(host_info)
            clusters_hosts[cluster_name] = hosts

        logger.info(
            f"Retrieved ESXi hosts from {len(clusters_hosts)} VMware clusters (filtered from {len(cluster_names)} requested clusters)"
        )
        return clusters_hosts
    except Exception as e:
        logger.error(f"Failed to retrieve ESXi hosts per cluster: {e}")
        return {}


def _get_cluster_name_from_resource_pool(resource_pool: str) -> Optional[str]:
    """Extract the cluster name from a vSphere resource pool path.

    Expected format: /DATACENTER/host/CLUSTER/Resources/optional_sub_pool

    Args:
        resource_pool: The full path of the resource pool.

    Returns:
        The extracted cluster name, or None if parsing fails.
    """
    if not resource_pool:
        return None
    try:
        parts = resource_pool.split("/")
        # Find the index of 'host'
        host_index = parts.index("host")
        # The cluster name should be the part immediately after 'host'
        if host_index + 1 < len(parts):
            cluster_name = parts[host_index + 1]
            logger.debug(
                f"Parsed cluster name '{cluster_name}' from resource pool '{resource_pool}'"
            )
            return cluster_name
    except (ValueError, IndexError):
        # Handle cases where 'host' is not found or the structure is unexpected
        logger.debug(f"Could not parse cluster name from resource pool path: {resource_pool}")
    return None


def _find_cluster_match(
    candidate_name: Optional[str], server_name: str, known_clusters: List[str]
) -> Optional[str]:
    """Find the best matching known cluster name based on candidate and server names.

    Tries direct match on candidate, then server, then partial match on candidate.

    Args:
        candidate_name: Cluster name potentially derived from resource pool.
        server_name: Server name (vCenter FQDN/IP) from the machineset.
        known_clusters: List of actual VMware cluster names from vSphere.

    Returns:
        The matched cluster name, or None if no suitable match found.
    """
    # 1. Direct match on candidate name from resource pool
    if candidate_name and candidate_name in known_clusters:
        logger.debug(f"Direct match found for candidate '{candidate_name}'")
        return candidate_name

    # 2. Direct match on server name (less common but possible)
    if server_name and server_name in known_clusters:
        logger.debug(f"Direct match found for server name '{server_name}'")
        return server_name

    # 3. Partial match based on candidate name
    if candidate_name:
        for known_cluster in known_clusters:
            if candidate_name in known_cluster:
                logger.debug(
                    f"Partial match found for candidate '{candidate_name}' -> '{known_cluster}'"
                )
                return known_cluster
    logger.debug(
        f"No match found for candidate='{candidate_name}', server='{server_name}' in known clusters."
    )
    return None


def map_machinesets_to_clusters(
    machinesets_vsphere_info: Dict[str, Dict[str, Any]],
    clusters_hosts: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    """Map OpenShift MachineSets to VMware clusters and their ESXi hosts.

    Args:
        machinesets_vsphere_info: Dictionary of MachineSet vSphere information
        clusters_hosts: Dictionary of VMware clusters and their ESXi hosts

    Returns:
        Mapping between MachineSets and VMware clusters with host counts
    """
    mapping = {}
    known_cluster_names = list(clusters_hosts.keys())

    for (
        machineset_name,
        vsphere_info_item,
    ) in machinesets_vsphere_info.items():  # Renamed vsphere_info
        resource_pool = vsphere_info_item.get("resourcePool", "")
        server_name = vsphere_info_item.get("server", "")

        # Attempt to find the cluster name
        candidate_name = _get_cluster_name_from_resource_pool(resource_pool)
        matched_cluster_name = _find_cluster_match(candidate_name, server_name, known_cluster_names)

        # Populate the mapping based on the match result
        if (
            matched_cluster_name and matched_cluster_name in clusters_hosts
        ):  # Check if matched_cluster_name is valid key
            hosts = clusters_hosts[matched_cluster_name]
            mapping[machineset_name] = {
                "cluster_name": matched_cluster_name,
                "host_count": len(hosts),
                "hosts": hosts,
                "datacenter": vsphere_info_item.get("datacenter", ""),
                "datastore": vsphere_info_item.get("datastore", ""),
            }
        else:
            # Handle cases where no match was found or matched_cluster_name is not in clusters_hosts
            logger.warning(
                f"No valid VMware cluster match for MachineSet {machineset_name}. "
                f"Candidate: {candidate_name}, Server: {server_name}, Matched: {matched_cluster_name}"
            )
            mapping[machineset_name] = {
                "cluster_name": (
                    "Unknown" if not matched_cluster_name else matched_cluster_name
                ),  # Keep matched name if it exists but not in hosts
                "host_count": 0,
                "hosts": [],
                "datacenter": vsphere_info_item.get("datacenter", ""),
                "datastore": vsphere_info_item.get("datastore", ""),
            }

    logger.info(f"Mapped {len(mapping)} MachineSets to VMware clusters")
    return mapping


def generate_cluster_summary(mapping: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    """Generate a summary of clusters and their ESXi host counts.

    Args:
        mapping: Mapping between MachineSets and VMware clusters

    Returns:
        Dictionary mapping cluster names to their ESXi host counts
    """
    cluster_summary = {}
    for machineset_info_item in mapping.values():  # Renamed machineset_info
        cluster_name = machineset_info_item["cluster_name"]
        # Only count each cluster once, ensure it's not "Unknown"
        if cluster_name != "Unknown" and cluster_name not in cluster_summary:
            cluster_summary[cluster_name] = machineset_info_item["host_count"]

    logger.info(f"Generated summary for {len(cluster_summary)} VMware clusters")
    return cluster_summary


def count_portworx_pods(px_namespace: str = "portworx") -> int:  # Renamed namespace to px_namespace
    """Count the number of pods with label name=portworx in the specified namespace.

    Args:
        px_namespace: Namespace to search for Portworx pods (default: "portworx")

    Returns:
        Number of Portworx pods found
    """
    try:
        # Initialize the Kubernetes API client
        v1 = client.CoreV1Api()

        # Get pods with the label name=portworx in the specified namespace
        pods = v1.list_namespaced_pod(namespace=px_namespace, label_selector="name=portworx")
        pod_count = len(pods.items)
        logger.info(f"Found {pod_count} Portworx pods in namespace '{px_namespace}'")
        return pod_count
    except client.exceptions.ApiException as e:
        logger.error(f"Error fetching Portworx pods in namespace '{px_namespace}': {e}")
        return 0


def extract_cluster_name_from_api_url(api_url: str) -> str:
    """Extract the cluster name from the Kubernetes API URL.

    Args:
        api_url: The Kubernetes API URL (e.g., https://api.hostname.fqdn)

    Returns:
        The extracted hostname (e.g., hostname)
    """
    try:
        # Remove the protocol part (https://)
        hostname_part = api_url  # Renamed from api_url to avoid confusion
        if "://" in hostname_part:
            hostname_part = hostname_part.split("://")[1]

        # Remove the 'api.' prefix if present
        if hostname_part.startswith("api."):
            hostname_part = hostname_part[4:]

        # Extract the hostname part (remove domain/fqdn)
        hostname = hostname_part.split(".")[0]

        logger.info(f"Extracted cluster name '{hostname}' from API URL '{api_url}'")
        return hostname
    except Exception as e:
        logger.warning(f"Failed to extract cluster name from API URL '{api_url}': {e}")
        return "unknown-cluster"


def _generate_brief_json_data(all_clusters_data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:  # noqa: C901
    """Generate the data structure for the brief JSON report.

    Args:
        all_clusters_data: Dictionary containing the processed data for all clusters.

    Returns:
        Dictionary representing the brief JSON report data.
    """
    # Generate a summary of clusters and their ESXi host counts
    all_clusters_summary = {}
    total_px_pods_count = 0  # Renamed from total_px_pods
    total_esxi_hosts_count = 0  # Renamed from total_esxi_hosts

    # Collect summary data from all clusters
    for cluster_name, cluster_data in all_clusters_data.items():
        mapping = cluster_data["mapping"]
        px_pod_count = cluster_data["portworx_pods_count"]
        total_px_pods_count += px_pod_count

        # Generate cluster summary (cluster name -> host count)
        cluster_summary = generate_cluster_summary(mapping)

        # Add to all clusters summary
        for vmware_cluster, host_count in cluster_summary.items():
            if vmware_cluster == "Unknown":  # Skip unknown clusters for summary
                continue
            key = f"{cluster_name}/{vmware_cluster}"
            all_clusters_summary[key] = {
                "host_count": host_count,
                "px_pod_count": px_pod_count,  # Store px_pod_count per OCP cluster
            }
            # Sum unique hosts based on their actual count in the mapping
            # This logic for total_esxi_hosts_count needs to be careful not to double count
            # across different OCP clusters if they share VMware clusters.
            # The most straightforward way is to sum host_count from the cluster_summary.
            total_esxi_hosts_count += host_count

    # Recalculate total_esxi_hosts for truly unique ESXi hosts across all OCP clusters
    # This requires iterating through the original mapping data to get unique host names.
    globally_unique_esxi_hosts = set()
    for ocp_cluster_data in all_clusters_data.values():
        for ms_info in ocp_cluster_data["mapping"].values():
            if ms_info["cluster_name"] != "Unknown":
                for host in ms_info["hosts"]:
                    globally_unique_esxi_hosts.add(host["name"])

    # Create brief JSON output
    output_data = {
        "portworx_pods_count": total_px_pods_count,
        "total_esxi_hosts": len(
            globally_unique_esxi_hosts
        ),  # Use the count of globally unique hosts
        "clusters": {},
    }

    # Group by OpenShift cluster
    # Store OCP cluster specific PX pod count only once.
    ocp_px_counts_recorded = set()

    for full_cluster_name_key, data in all_clusters_summary.items():  # Renamed full_cluster_name
        ocp_cluster, vmware_cluster = full_cluster_name_key.split("/", 1)

        if ocp_cluster not in output_data["clusters"]:
            output_data["clusters"][ocp_cluster] = {
                # Store px_pod_count only once per OCP cluster
                "px_pod_count": data["px_pod_count"],
                "vmware_clusters": {},
            }
            ocp_px_counts_recorded.add(ocp_cluster)
        # If OCP cluster already exists, but px_pod_count wasn't set (e.g. older logic)
        elif (
            "px_pod_count" not in output_data["clusters"][ocp_cluster]
            and ocp_cluster not in ocp_px_counts_recorded
        ):
            output_data["clusters"][ocp_cluster]["px_pod_count"] = data["px_pod_count"]
            ocp_px_counts_recorded.add(ocp_cluster)

        output_data["clusters"][ocp_cluster]["vmware_clusters"][vmware_cluster] = {
            "hosts_count": data["host_count"]
        }
    return output_data


def _generate_detailed_json_data(all_clusters_data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Generate the data structure for the detailed JSON report.

    Args:
        all_clusters_data: Dictionary containing the processed data for all clusters.

    Returns:
        Dictionary representing the detailed JSON report data.
    """
    # Create a new JSON structure organized by cluster, datacenter, and VMware cluster
    report_data = {}

    # Process each OpenShift cluster
    for cluster_name, cluster_data_item in all_clusters_data.items():  # Renamed cluster_data
        mapping = cluster_data_item["mapping"]
        px_pod_count = cluster_data_item["portworx_pods_count"]

        # Track unique hosts for this cluster
        cluster_hosts = set()

        # First pass: collect all datacenter, cluster, and host information for this cluster
        datacenter_clusters = {}
        for _machineset_name, cluster_info in mapping.items():  # Renamed machineset_name
            datacenter = cluster_info.get("datacenter", "Unknown")
            vmware_cluster_name = cluster_info["cluster_name"]

            if vmware_cluster_name == "Unknown":  # Skip if cluster is unknown
                continue

            # Initialize datacenter if not seen before
            if datacenter not in datacenter_clusters:
                datacenter_clusters[datacenter] = {}

            # Initialize VMware cluster if not seen before
            if vmware_cluster_name not in datacenter_clusters[datacenter]:
                datacenter_clusters[datacenter][vmware_cluster_name] = {
                    "hosts": set(),
                    "hosts_count": 0,
                }

            # Add unique hosts to this VMware cluster
            for host_item in cluster_info["hosts"]:  # Renamed host
                host_name = host_item["name"]
                datacenter_clusters[datacenter][vmware_cluster_name]["hosts"].add(host_name)
                cluster_hosts.add(host_name)

        # Add this OpenShift cluster's data to the report
        report_data[cluster_name] = {
            "portworx_pods_count": px_pod_count,
            "total_esxi_hosts": len(cluster_hosts),
        }

        # Add datacenter and VMware cluster information
        for datacenter_name, vmware_clusters in datacenter_clusters.items():  # Renamed datacenter
            if "datacenters" not in report_data[cluster_name]:
                report_data[cluster_name]["datacenters"] = {}

            report_data[cluster_name]["datacenters"][datacenter_name] = {}
            for (
                vmware_cluster_name_item,
                vmware_cluster_data,
            ) in vmware_clusters.items():  # Renamed vmware_cluster_name
                # Convert set to sorted list for JSON serialization
                host_list = sorted(list(vmware_cluster_data["hosts"]))
                hosts_count = len(host_list)

                report_data[cluster_name]["datacenters"][datacenter_name][
                    vmware_cluster_name_item
                ] = {
                    "hosts": host_list,
                    "hosts_count": hosts_count,
                }

    return report_data


def generate_json_report(all_clusters_data: Dict[str, Dict[str, Any]], brief: bool) -> None:
    """Generate the report in JSON format.

    Args:
        all_clusters_data: Dictionary containing the processed data for all clusters.
        brief: Whether to generate a brief summary report.
    """
    if brief:
        report_output = _generate_brief_json_data(all_clusters_data)
    else:
        report_output = _generate_detailed_json_data(all_clusters_data)

    # Output the JSON
    console.print(json.dumps(report_output, indent=2))


# --- New Helper Functions for Refactoring ---


def _derive_vsphere_host_from_machinesets(
    machineset_vsphere_info: Dict[str, Dict[str, Any]],
    ocp_cluster_name: str,
) -> Optional[str]:
    """Derives vSphere host from the first MachineSet's providerSpec if available."""
    if not machineset_vsphere_info:
        logger.debug(
            f"Cannot derive vSphere host: machineset_vsphere_info is empty for {ocp_cluster_name}."
        )
        return None
    first_machineset_key = next(iter(machineset_vsphere_info), None)
    if first_machineset_key:
        derived_host = machineset_vsphere_info[first_machineset_key].get("server")
        if derived_host:
            logger.info(
                f"Derived vSphere host '{derived_host}' from MachineSet providerSpec for OCP cluster {ocp_cluster_name}."
            )
            return derived_host
        else:
            logger.debug(
                f"No 'server' field in first machineset for {ocp_cluster_name} to derive host."
            )
    else:
        logger.debug(f"No machinesets available to derive host for {ocp_cluster_name}.")
    return None


def _determine_host_parameter(
    cli_vsphere_host: Optional[str],
    use_secret_workflow: bool,  # True if credentials_secret_name is set
    machineset_vsphere_info: Dict[str, Dict[str, Any]],
    ocp_cluster_name: str,
) -> Optional[str]:
    """Determines the final vSphere host parameter."""
    if cli_vsphere_host:
        logger.info(
            f"Using vSphere host from CLI option: {cli_vsphere_host} for {ocp_cluster_name}."
        )
        return cli_vsphere_host
    if use_secret_workflow:
        # Attempt to derive host if CLI didn't provide it and secret workflow is active
        return _derive_vsphere_host_from_machinesets(machineset_vsphere_info, ocp_cluster_name)
    return None


def _determine_user_parameter(
    cli_vsphere_user: Optional[str],
    secret_credentials: Optional[Dict[str, str]],  # Result of get_vmware_credentials_from_secret
    ocp_cluster_name: str,
) -> Optional[str]:
    """Determines the final vSphere user parameter."""
    if cli_vsphere_user:
        logger.info(f"Using vSphere user from CLI option for {ocp_cluster_name}.")
        return cli_vsphere_user
    if secret_credentials:
        user_from_secret = secret_credentials.get("username")
        if user_from_secret:
            logger.info(f"Using vSphere user from Kubernetes Secret for {ocp_cluster_name}.")
            return user_from_secret
    return None


def _determine_password_parameter(
    cli_vsphere_password: Optional[str],
    secret_credentials: Optional[Dict[str, str]],
    ocp_cluster_name: str,
) -> Optional[str]:
    """Determines the final vSphere password parameter."""
    if cli_vsphere_password:
        logger.info(f"Using vSphere password from CLI option for {ocp_cluster_name}.")
        return cli_vsphere_password
    if secret_credentials:
        password_from_secret = secret_credentials.get("password")
        if password_from_secret:
            logger.info(f"Using vSphere password from Kubernetes Secret for {ocp_cluster_name}.")
            return password_from_secret
    # Fallback to env var if CLI and secret didn't provide it
    env_password = get_env_var("VSPHERE_PASSWORD", required=False)
    if env_password:
        logger.info(
            "Using vSphere password from VSPHERE_PASSWORD environment variable "
            f"for OCP cluster {ocp_cluster_name}."
        )
        return env_password
    return None


def _get_vsphere_connection_details(
    cli_vsphere_host: Optional[str],
    cli_vsphere_user: Optional[str],
    cli_vsphere_password: Optional[str],
    machineset_vsphere_info: Dict[str, Dict[str, Any]],
    credentials_secret_name: Optional[str],
    credentials_secret_namespace: str,
    ocp_cluster_name: str,
    disable_ssl_vsphere: bool,
    vsphere_cert_path_cli: Optional[str],
) -> Optional[VSphereConnectionParams]:
    """Determines vSphere connection details from various sources and returns a VSphereConnectionParams object."""
    secret_creds_retrieved = None
    if credentials_secret_name:
        logger.info(
            f"Attempting to retrieve VMware credentials from Secret "
            f"'{credentials_secret_name}' in namespace '{credentials_secret_namespace}' "
            f"for OCP cluster {ocp_cluster_name}."
        )
        # get_vmware_credentials_from_secret already logs success/failure of retrieval
        secret_creds_retrieved = get_vmware_credentials_from_secret(
            credentials_secret_namespace, credentials_secret_name
        )

    final_host = _determine_host_parameter(
        cli_vsphere_host,
        bool(credentials_secret_name),  # Pass intent to use secret for derivation
        machineset_vsphere_info,
        ocp_cluster_name,
    )
    final_user = _determine_user_parameter(
        cli_vsphere_user, secret_creds_retrieved, ocp_cluster_name
    )
    final_password = _determine_password_parameter(
        cli_vsphere_password, secret_creds_retrieved, ocp_cluster_name
    )

    # Validate required VMware credentials
    missing_creds = []
    if not final_host:
        missing_creds.append("vSphere host")
    if not final_user:
        missing_creds.append("vSphere username")
    if not final_password:
        missing_creds.append("vSphere password")

    if missing_creds:
        logger.error(
            f"Missing required VMware credentials for OCP cluster {ocp_cluster_name}: "
            f"{', '.join(missing_creds)}. Provide them via CLI options, "
            "environment variables, or a Kubernetes Secret."
        )
        return None

    # Determine effective cert path
    effective_cert_path = _get_effective_vsphere_cert_path(vsphere_cert_path_cli)

    return VSphereConnectionParams(
        host=final_host,
        user=final_user,
        password=final_password,
        disable_ssl=disable_ssl_vsphere,
        effective_cert_path=effective_cert_path,
    )


def _initialize_ocp_connection_and_get_machinesets(
    kubeconfig_file_path: str, machineset_namespace: str
) -> tuple[Optional[str], Optional[List[Dict[str, Any]]]]:
    """Initialize OCP connection and retrieve MachineSets."""
    try:
        if not os.path.isfile(kubeconfig_file_path):
            logger.error(f"Kubeconfig file not found: {kubeconfig_file_path}")
            return None, None

        logger.info(f"Loading kubeconfig: {kubeconfig_file_path}")
        config.load_kube_config(config_file=kubeconfig_file_path)

        api_host = client.Configuration._default.host
        ocp_cluster_name = extract_cluster_name_from_api_url(api_host)
        logger.info(f"Processing OpenShift cluster: {ocp_cluster_name}")

        logger.info(f"Retrieving MachineSets from namespace '{machineset_namespace}'")
        custom_api = get_custom_objects_api()
        machinesets = get_machinesets(custom_api, machineset_namespace)
        if not machinesets:
            logger.warning(
                f"No MachineSets found in namespace '{machineset_namespace}' for OCP cluster {ocp_cluster_name}"
            )
            # Return cluster name even if no machinesets, as PX pods can still be counted
            return ocp_cluster_name, []

        return ocp_cluster_name, machinesets
    except Exception as e:
        logger.error(
            f"Error during OCP initialization or MachineSet retrieval for {kubeconfig_file_path}: {str(e)}"
        )
        return None, None


def _extract_vsphere_info_and_params(
    ocp_cluster_name: str,  # Added ocp_cluster_name for logging and context
    machinesets: List[Dict[str, Any]],
    cli_vsphere_host: Optional[str],
    cli_vsphere_user: Optional[str],
    cli_vsphere_password: Optional[str],
    credentials_secret_name: Optional[str],
    credentials_secret_namespace: str,
    disable_ssl_vsphere: bool,
    vsphere_cert_path_cli: Optional[str],
) -> tuple[Optional[Dict[str, Dict[str, Any]]], Optional[VSphereConnectionParams]]:
    """Extract vSphere info from MachineSets and get connection parameters."""
    logger.info(
        f"Extracting vSphere information from MachineSets in OCP cluster {ocp_cluster_name}"
    )
    machineset_vsphere_data = extract_vsphere_info_from_machinesets(machinesets)
    if (
        not machineset_vsphere_data and machinesets
    ):  # Only warn if machinesets existed but no vsphere info
        logger.warning(
            f"No vSphere provider information found in the retrieved MachineSets for OCP cluster {ocp_cluster_name}"
        )
        # Allow proceeding if machinesets is empty (no warning needed then, already logged by caller)

    vsphere_conn_params = _get_vsphere_connection_details(
        cli_vsphere_host,
        cli_vsphere_user,
        cli_vsphere_password,
        machineset_vsphere_data,  # Pass even if empty, for potential host derivation logic
        credentials_secret_name,
        credentials_secret_namespace,
        ocp_cluster_name,
        disable_ssl_vsphere,
        vsphere_cert_path_cli,
    )
    if (
        not vsphere_conn_params and machineset_vsphere_data
    ):  # Only fail hard if we had vsphere data but couldn't get params
        logger.error(
            f"Could not determine vSphere connection parameters for {ocp_cluster_name} despite having MachineSet vSphere data."
        )
        return machineset_vsphere_data, None  # Return data for partial reporting

    # If vsphere_conn_params is None but machineset_vsphere_data is also empty/None, it's fine, means no vSphere work to do.
    return machineset_vsphere_data, vsphere_conn_params


def _connect_and_gather_vsphere_mapping(
    ocp_cluster_name: str,  # Added for logging
    vsphere_conn_params: Optional[VSphereConnectionParams],
    machineset_vsphere_data: Optional[Dict[str, Dict[str, Any]]],
) -> tuple[Optional[Dict[str, Dict[str, Any]]], Optional[Any]]:
    """Connect to vSphere, gather ESXi info, and map to MachineSets. Returns mapping and service instance."""
    si = None
    if not vsphere_conn_params or not machineset_vsphere_data:
        logger.info(
            f"Skipping vSphere connection and mapping for {ocp_cluster_name} due to missing "
            "connection parameters or vSphere data from MachineSets."
        )
        # Return an empty mapping if there's no data, so PX count can still be added
        return {}, None  # No mapping, no service instance

    try:
        logger.info(
            f"Connecting to vSphere host: {vsphere_conn_params.host} for OCP cluster {ocp_cluster_name}"
        )
        si = connect_to_vsphere(vsphere_conn_params)
        if not si:
            logger.error(
                f"Failed to establish connection to vSphere: {vsphere_conn_params.host} "
                f"for OCP cluster {ocp_cluster_name}"
            )
            # Return an empty mapping but no service instance, error already logged.
            return {}, None

        logger.info(
            f"Retrieving ESXi hosts information from vSphere for OCP cluster {ocp_cluster_name}"
        )
        vmware_cluster_names = extract_vmware_clusters_from_machinesets(machineset_vsphere_data)
        esxi_hosts_per_vmware_cluster = get_esxi_hosts_per_cluster(si, vmware_cluster_names)
        if not esxi_hosts_per_vmware_cluster:
            logger.warning(
                f"No VMware clusters found or error retrieving ESXi hosts for OCP cluster {ocp_cluster_name}"
            )
            # Fallthrough to map_machinesets_to_clusters which can handle empty hosts

        logger.info(
            f"Mapping OpenShift MachineSets to VMware clusters for OCP cluster {ocp_cluster_name}"
        )
        machineset_to_vmware_map = map_machinesets_to_clusters(
            machineset_vsphere_data, esxi_hosts_per_vmware_cluster
        )
        if not machineset_to_vmware_map:
            logger.warning(
                f"Could not map any MachineSets to VMware clusters for OCP cluster {ocp_cluster_name}"
            )
            # Return empty mapping if no maps could be made
            return {}, si

        return machineset_to_vmware_map, si
    except Exception as e:
        logger.error(
            f"Error during vSphere connection or data gathering for {ocp_cluster_name}: {str(e)}"
        )
        # Return empty mapping and service instance (if it exists) for cleanup
        return {}, si


def _process_single_kubeconfig(
    kubeconfig_file_path: str,
    cli_vsphere_host: Optional[str],
    cli_vsphere_user: Optional[str],
    cli_vsphere_password: Optional[str],
    machineset_namespace: str,
    disable_ssl_vsphere: bool,
    vsphere_cert_path_cli: Optional[str],
    credentials_secret_name: Optional[str],
    credentials_secret_namespace: str,
    portworx_namespace: str,
) -> Optional[Dict[str, Any]]:
    """Processes a single OpenShift cluster to gather vSphere and Portworx data."""
    ocp_cluster_name, machinesets = _initialize_ocp_connection_and_get_machinesets(
        kubeconfig_file_path, machineset_namespace
    )

    if ocp_cluster_name is None:  # Indicates a fatal error during init
        return None
    # If machinesets is None but ocp_cluster_name is present, it means init was ok but no MS.
    # If machinesets is an empty list, also proceed.

    # Ensure machinesets is a list for the next step, even if None was returned (though logic above makes it [] if ocp_cluster_name is not None)
    current_machinesets = machinesets if machinesets is not None else []

    machineset_vsphere_data, vsphere_conn_params = _extract_vsphere_info_and_params(
        ocp_cluster_name,
        current_machinesets,  # Pass the list of machinesets
        cli_vsphere_host,
        cli_vsphere_user,
        cli_vsphere_password,
        credentials_secret_name,
        credentials_secret_namespace,
        disable_ssl_vsphere,
        vsphere_cert_path_cli,
    )

    # If vsphere_conn_params is None and machineset_vsphere_data has content,
    # it's an issue with vSphere creds/params for an expected vSphere setup.
    # However, if machineset_vsphere_data is empty, not having vSphere params is fine.
    if vsphere_conn_params is None and machineset_vsphere_data:
        logger.warning(
            f"Proceeding with partial data for {ocp_cluster_name} due to missing vSphere connection parameters."
        )
        # We can still count PX pods. The mapping will be empty.
        machineset_to_vmware_map = {}
        si = None
    elif not machineset_vsphere_data:  # No vsphere data from machinesets implies no vsphere work.
        logger.info(
            f"No vSphere MachineSets found or no vSphere provider info for {ocp_cluster_name}. Skipping vSphere specific steps."
        )
        machineset_to_vmware_map = {}
        si = None
    else:  # We have vsphere_conn_params and potentially machineset_vsphere_data
        machineset_to_vmware_map, si = _connect_and_gather_vsphere_mapping(
            ocp_cluster_name, vsphere_conn_params, machineset_vsphere_data
        )
        # If machineset_to_vmware_map is None from this call, it means a vSphere connection/processing error.
        # The helper function already logs this. Set to {} for consistent return type if None.
        if machineset_to_vmware_map is None:
            machineset_to_vmware_map = {}

    try:
        # Portworx pod count is independent of vSphere processing
        px_pod_count = count_portworx_pods(portworx_namespace)
        logger.info(
            f"Found {px_pod_count} Portworx pods in namespace '{portworx_namespace}' for OCP cluster {ocp_cluster_name}"
        )

        return {
            "ocp_cluster_name": ocp_cluster_name,
            "mapping": machineset_to_vmware_map,
            "portworx_pods_count": px_pod_count,
        }
    finally:
        if si:
            logger.info(f"Disconnecting from vSphere for OCP cluster {ocp_cluster_name}")
            Disconnect(si)
    # The original top-level try-except for any other unhandled errors is removed
    # as sub-functions should handle their specific errors.
    # If any sub-function returned None indicating a fatal issue for *that stage*,
    # _process_single_kubeconfig will effectively propagate that by returning None
    # or a partial result.


# --- Refactored Report Generation ---
def _generate_brief_table_report(
    all_clusters_data: Dict[str, Dict[str, Any]],
    console_instance: Console,  # Renamed from console
    # px_namespace: str # Not directly needed here, but kept for consistency if extended
) -> None:
    """Generates and prints the brief table report."""
    all_clusters_summary = {}
    total_px_pods_count = 0
    # Use a set to count globally unique ESXi hosts for the top-level summary
    globally_unique_esxi_hosts_set = set()

    for ocp_cluster_name, cluster_data in all_clusters_data.items():
        mapping = cluster_data["mapping"]
        px_pod_count = cluster_data["portworx_pods_count"]
        total_px_pods_count += px_pod_count

        cluster_summary = generate_cluster_summary(mapping)

        for vmware_cluster, host_count in cluster_summary.items():
            if vmware_cluster == "Unknown":
                continue
            key = f"{ocp_cluster_name}/{vmware_cluster}"
            all_clusters_summary[key] = {
                "ocp_cluster": ocp_cluster_name,
                "vmware_cluster": vmware_cluster,
                "host_count": host_count,
                "px_pod_count": px_pod_count,  # Store with each entry for sorting/display logic
            }
            # Collect unique host names for the global total
            for ms_info in mapping.values():
                if ms_info["cluster_name"] == vmware_cluster:
                    for host in ms_info["hosts"]:
                        globally_unique_esxi_hosts_set.add(host["name"])

    console_instance.print(
        f"[bold]Total Portworx pods across all clusters:[/bold] {total_px_pods_count}"
    )
    console_instance.print(
        f"[bold]Total unique ESXi hosts across all clusters:[/bold] {len(globally_unique_esxi_hosts_set)}"
    )
    console_instance.print("")

    table = Table(title="OpenShift and VMware Clusters Summary")
    table.add_column("OpenShift Cluster", style="cyan")
    table.add_column("VMware Cluster", style="green")
    table.add_column("ESXi Host Count", justify="right", style="yellow")
    table.add_column("Portworx Pod Count", justify="right", style="magenta")

    # Sort by OpenShift cluster, then VMware cluster
    # Keep track of OCP clusters for which PX count has been displayed
    displayed_px_for_ocp = set()
    sorted_summary_keys = sorted(all_clusters_summary.keys())

    for key in sorted_summary_keys:
        summary_item = all_clusters_summary[key]
        ocp_name = summary_item["ocp_cluster"]
        vmware_name = summary_item["vmware_cluster"]
        hosts = str(summary_item["host_count"])
        px_pods_for_row = ""

        if ocp_name not in displayed_px_for_ocp:
            px_pods_for_row = str(summary_item["px_pod_count"])
            displayed_px_for_ocp.add(ocp_name)
        table.add_row(ocp_name, vmware_name, hosts, px_pods_for_row)

    console_instance.print(table)


def _generate_detailed_table_report_for_cluster(  # noqa: C901
    ocp_cluster_name: str,
    cluster_data: Dict[str, Any],
    console_instance: Console,  # Renamed
    px_namespace: str,
) -> None:
    """Generates and prints the detailed table report for a single OCP cluster."""
    mapping = cluster_data["mapping"]
    px_pod_count = cluster_data["portworx_pods_count"]

    cluster_unique_hosts = set()
    for _ms_name, ms_info in mapping.items():
        if ms_info["cluster_name"] != "Unknown":
            for host in ms_info["hosts"]:
                cluster_unique_hosts.add(host["name"])

    console_instance.print(f"[bold]Cluster: {ocp_cluster_name}[/bold]")
    console_instance.print(
        f"[bold]Portworx pods in namespace '{px_namespace}':[/bold] {px_pod_count}"
    )
    console_instance.print(
        f"[bold]Total unique ESXi hosts in this cluster:[/bold] {len(cluster_unique_hosts)}"
    )
    console_instance.print("")

    ms_table = Table(
        title=f"OpenShift MachineSets to VMware ESXi Clusters Mapping for {ocp_cluster_name}"
    )
    ms_table.add_column("MachineSet", style="cyan")
    ms_table.add_column("Datacenter", style="magenta")
    ms_table.add_column("VMware Cluster", style="green")
    ms_table.add_column("Datastore", style="blue")

    sorted_machineset_names = sorted(mapping.keys())
    for machineset_name in sorted_machineset_names:
        cluster_info = mapping[machineset_name]
        ms_table.add_row(
            machineset_name,
            cluster_info.get("datacenter", "N/A"),
            cluster_info["cluster_name"],
            cluster_info.get("datastore", "N/A"),
        )
    console_instance.print(ms_table)

    # Collect all unique hosts for the detailed host table for this OCP cluster
    # Format: (vmware_cluster_name, host_detail_dict)
    detailed_hosts_info_list = []
    seen_host_in_ocp_cluster_scope = set()  # (vmware_cluster_name, esxi_host_name)

    for ms_info in mapping.values():
        vmware_cluster_for_ms = ms_info["cluster_name"]
        if vmware_cluster_for_ms != "Unknown":
            for host_detail in ms_info["hosts"]:
                host_key = (vmware_cluster_for_ms, host_detail["name"])
                if host_key not in seen_host_in_ocp_cluster_scope:
                    detailed_hosts_info_list.append(
                        {"vmware_cluster": vmware_cluster_for_ms, "host": host_detail}
                    )
                    seen_host_in_ocp_cluster_scope.add(host_key)

    if detailed_hosts_info_list:
        hosts_table = Table(title=f"ESXi Hosts Details for {ocp_cluster_name}")
        hosts_table.add_column("VMware Cluster", style="green")
        hosts_table.add_column("Host", style="cyan")
        hosts_table.add_column("CPU Cores", justify="right", style="yellow")
        hosts_table.add_column("Memory (GB)", justify="right", style="yellow")
        hosts_table.add_column("State", style="magenta")

        detailed_hosts_info_list.sort(key=lambda x: (x["vmware_cluster"], x["host"]["name"]))

        for item in detailed_hosts_info_list:
            host = item["host"]
            hosts_table.add_row(
                item["vmware_cluster"],
                host["name"],
                str(host.get("cpu_cores", "N/A")),
                str(host.get("memory_size_gb", "N/A")),
                host.get("power_state", "N/A"),
            )
        console_instance.print(hosts_table)
    console_instance.print("")


def _generate_detailed_table_report(
    all_clusters_data: Dict[str, Dict[str, Any]],
    console_instance: Console,  # Renamed
    px_namespace: str,
) -> None:
    """Generates and prints the detailed table report for all clusters."""
    sorted_ocp_cluster_names = sorted(all_clusters_data.keys())
    for ocp_cluster_name in sorted_ocp_cluster_names:
        cluster_data = all_clusters_data[ocp_cluster_name]
        _generate_detailed_table_report_for_cluster(
            ocp_cluster_name, cluster_data, console_instance, px_namespace
        )


# --- Main Click Command ---
@click.command()
@click.option("--kubeconfig", help="Path to a kubeconfig file for a single OpenShift cluster")
@click.option(
    "--clusterlist", help="Path to a file containing a list of kubeconfig files (one per line)"
)
@click.option(
    "--vsphere-host",
    help="VMware vSphere host address (optional if using secret or derived from MachineSet)",
)
@click.option("--vsphere-user", help="VMware vSphere username (optional if using secret)")
@click.option(
    "--vsphere-password",
    help="VMware vSphere password (if not provided, "
    "will use environment variable VSPHERE_PASSWORD or secret)",
)
@click.option(
    "--namespace",
    default="openshift-machine-api",
    show_default=True,
    help="Namespace where MachineSets reside",
)
@click.option(
    "--output-format",
    default="table",
    type=click.Choice(["table", "json"]),
    show_default=True,
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
    default="px-vsphere-secret",  # Default from docs/script
    show_default=True,
    help="Name of the Secret containing VMware credentials",
)
@click.option(
    "--credentials-namespace",
    default="portworx",  # Default from docs/script
    show_default=True,
    help="Namespace containing the VMware credentials Secret",
)
@click.option(
    "--timeout", default=30, type=int, show_default=True, help="Timeout in seconds for API calls"
)
@click.option(
    "--px-namespace",
    default="portworx",
    show_default=True,
    help="Namespace where Portworx pods are running",
)
@click.option(
    "--vsphere-cert-path",
    help="Path to a custom SSL certificate file for vSphere connection. Overrides VSPHERE_SSL_CERT_PATH env var and default fallback.",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    required=False,
)
@click.option("--debug", is_flag=True, help="Enable debug logging")
def main(  # noqa: C901
    kubeconfig: Optional[str],  # Made options optional to allow None check
    clusterlist: Optional[str],
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
    vsphere_cert_path: Optional[str],  # Added for Click option
    debug: bool,
) -> None:
    """Generate a report on ESXi hosts per VMware cluster for OpenShift MachineSets.

    This script connects to both OpenShift and VMware vSphere to map OpenShift
    MachineSets to their respective ESXi host clusters and count the number of
    ESXi hosts in each cluster.
    """
    # --- Setup Logging --- #
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)
    logger.debug("Logging setup complete.")

    # Load .env file if it exists, for environment variable overrides
    load_env_file()  # From utils.config_utils

    # Set timeout for API calls
    socket.setdefaulttimeout(timeout)

    # Determine list of kubeconfig files
    kubeconfig_files_to_process: List[str] = []  # Renamed from kubeconfigs
    if clusterlist:
        try:
            with open(clusterlist, "r") as f:
                kubeconfig_files_to_process = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            logger.error(f"Cluster list file not found: {clusterlist}")
            sys.exit(1)
    elif kubeconfig:
        kubeconfig_files_to_process = [kubeconfig]
    else:
        logger.error("Either --kubeconfig or --clusterlist must be provided.")
        sys.exit(1)

    if not kubeconfig_files_to_process:
        logger.error("No kubeconfig files specified for processing.")
        sys.exit(1)

    # Process each kubeconfig and store results
    all_ocp_clusters_data: Dict[str, Dict[str, Any]] = {}  # Renamed from all_clusters_data

    for kc_file_path in kubeconfig_files_to_process:
        processed_data = _process_single_kubeconfig(
            kc_file_path,
            vsphere_host,  # Pass CLI args directly
            vsphere_user,
            vsphere_password,
            namespace,  # machineset_namespace
            disable_ssl,  # disable_ssl_vsphere
            vsphere_cert_path,  # Pass CLI option for cert path
            credentials_secret,  # credentials_secret_name
            credentials_namespace,
            px_namespace,  # portworx_namespace
        )
        if processed_data:
            # Use the ocp_cluster_name returned by the processing function as the key
            all_ocp_clusters_data[processed_data["ocp_cluster_name"]] = processed_data

    if not all_ocp_clusters_data:
        logger.error("No OpenShift clusters were successfully processed.")
        sys.exit(1)

    # Generate combined report
    logger.info("Generating combined report for all processed OpenShift clusters.")
    try:
        if output_format.lower() == "json":
            generate_json_report(all_ocp_clusters_data, brief)
        else:  # Default to table format
            if brief:
                _generate_brief_table_report(all_ocp_clusters_data, console)
            else:
                _generate_detailed_table_report(all_ocp_clusters_data, console, px_namespace)
    except Exception as e:
        logger.error(f"Error generating combined report: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
