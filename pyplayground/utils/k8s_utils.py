"""Kubernetes utility functions.

This module provides utility functions for interacting with Kubernetes clusters,
including configuration loading, client creation, pod operations, node management,
and integration with HashiCorp Vault for kubeconfig retrieval.
"""

import base64
import binascii
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

import requests
import urllib3
import yaml
from hvac.exceptions import VaultError
from kubernetes import client, config, stream
from kubernetes.client import ApiClient, V1Pod
from kubernetes.client.rest import ApiException
from rich.console import Console

from pyplayground.utils.vault_utils import (
    create_vault_client,
    get_secret,
    normalize_vault_path,
)

logger = logging.getLogger(__name__)
console = Console()

# OpenShift Machine -> MachineSet association (label set by the machine controller).
_MACHINESET_LABEL_KEY = "machine.openshift.io/cluster-api-machineset"


def _machine_owned_by_machineset(machine: Dict[str, Any], machineset_name: str) -> bool:
    """Return True if a Machine belongs to the named MachineSet.

    Resolution order:
        1. Label ``machine.openshift.io/cluster-api-machineset`` when present (must match).
        2. ``ownerReferences`` with ``kind`` MachineSet and matching ``name``.
        3. Name pattern ``<machineset>-<suffix>`` where ``suffix`` contains no hyphens,
           so e.g. ``...-worker-storage-abc12`` matches ``...-worker-storage`` but
           ``...-worker-storage-ds02-abc12`` does not.

    Args:
        machine: Machine object from the Kubernetes API.
        machineset_name: MachineSet metadata.name.

    Returns:
        True if the Machine is owned by that MachineSet.
    """
    metadata = machine.get("metadata", {}) or {}
    labels = metadata.get("labels", {}) or {}
    if _MACHINESET_LABEL_KEY in labels:
        return labels.get(_MACHINESET_LABEL_KEY) == machineset_name
    for ref in metadata.get("ownerReferences", []) or []:
        if ref.get("kind") == "MachineSet" and ref.get("name") == machineset_name:
            return True
    machine_name = metadata.get("name", "")
    return bool(re.match(rf"^{re.escape(machineset_name)}-[^-]+$", machine_name))


def load_kube_config(config_file: Optional[str] = None, context: Optional[str] = None) -> None:
    """Load Kubernetes configuration from a kubeconfig file.

    Args:
        config_file: Optional path to kubeconfig file
        context: Optional context to use
    """
    try:
        if config_file:
            config.load_kube_config(config_file=config_file, context=context)
        else:
            config.load_kube_config(context=context)
    except config.config_exception.ConfigException as e:
        logger.error(f"Failed to load kubeconfig: {e}")
        raise


def load_kubeconfig_from_string(kubeconfig_str: str) -> None:
    """Safely load kubeconfig from a YAML string.

    Args:
        kubeconfig_str: String containing kubeconfig in YAML format

    Raises:
        yaml.YAMLError: If the YAML is invalid
        kubernetes.config.ConfigException: If the kubeconfig structure is invalid
    """
    try:
        # Safely parse the YAML string into a Python dictionary
        kubeconfig_dict = yaml.safe_load(kubeconfig_str)

        # Load the kubernetes config from the dictionary
        config.load_kube_config_from_dict(kubeconfig_dict)
    except yaml.YAMLError as e:
        # Handle YAML parsing errors
        raise ValueError(f"Invalid YAML format in kubeconfig: {e}")


def load_kube_config_auto(
    config_file: Optional[str] = None,
    context: Optional[str] = None,
    verify_ssl: bool = True,
    ssl_ca_cert: Optional[str] = None,
) -> bool:
    """Attempts to load Kubernetes config from default/specified file,falling back to in-cluster config.

    Args:
        config_file: Optional path to kubeconfig file.
        context: Optional context to use if loading from file.
        verify_ssl: Whether to verify SSL. Defaults to True.
        ssl_ca_cert: Path to CA cert file.

    Returns:
        True if configuration was loaded successfully, False otherwise.
    """
    loaded = False
    try:
        # Try loading from file first
        config.load_kube_config(config_file=config_file, context=context)
        logger.info(f"Loaded kubeconfig from file/context (file='{config_file}', context='{context}').")
        loaded = True
    except config.ConfigException:
        logger.debug("Could not load kubeconfig from file, attempting in-cluster config.")
        try:
            # Fallback to in-cluster config
            config.load_incluster_config()
            logger.info("Loaded in-cluster kubeconfig.")
            loaded = True
        except config.ConfigException:
            logger.error("Could not load Kubernetes configuration (neither from file/context nor in-cluster).")
            loaded = False
    except Exception as e:
        logger.error(f"An unexpected error occurred during kubeconfig loading: {e}")
        loaded = False

    if loaded:
        # After loading the config, let's modify the SSL settings if needed.
        # This will affect all subsequent client creations.
        configuration = client.Configuration.get_default_copy()

        configuration.verify_ssl = verify_ssl
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            logger.warning("SSL verification is disabled for Kubernetes client. " "This is not recommended for production.")

        if ssl_ca_cert:
            if not verify_ssl:
                logger.warning("`ssl_ca_cert` is provided but `verify_ssl` is False. The CA will not be used.")
            else:
                configuration.ssl_ca_cert = ssl_ca_cert
                logger.info(f"Using custom CA for Kubernetes client from: {ssl_ca_cert}")

        client.Configuration.set_default(configuration)

    return loaded


def get_k8s_client(api_version: str = "CoreV1Api") -> Any:
    """Get a Kubernetes API client.

    Args:
        api_version: The API version to use (e.g., "CoreV1Api", "CustomObjectsApi")

    Returns:
        Kubernetes API client
    """
    try:
        api_client = ApiClient()
        return getattr(client, api_version)(api_client)
    except AttributeError:
        logger.error(f"Invalid API version: {api_version}")
        raise


def get_ocp_cluster_name(kubeconfig: Optional[str] = None) -> Optional[str]:
    """Extract OpenShift cluster name from kubeconfig or MachineSets.

    This function attempts to derive the OpenShift cluster name using multiple strategies:
    1. Parse cluster name from kubeconfig `clusters[].name`
    2. Query MachineSets in openshift-machine-api namespace and extract cluster identifier
    3. Return cluster identifier from MachineSet name (e.g., `mycluster-worker-a` -> `mycluster`)

    Args:
        kubeconfig: Optional path to kubeconfig file. If not provided, uses default location.

    Returns:
        Optional[str]: Cluster name if found, None otherwise.
                       Returns the full cluster name from kubeconfig, or the base
                       cluster identifier extracted from MachineSet names.

    Example:
        >>> cluster_name = get_ocp_cluster_name()
        >>> print(cluster_name)
        mycluster
    """
    try:
        if kubeconfig:
            config.load_kube_config(config_file=kubeconfig)
        else:
            config.load_kube_config()

        contexts, active_context = config.list_kube_config_contexts()
        context_name = active_context.get("name", "unknown")
        logger.debug(f"Current kubeconfig context: {context_name}")

        kubeconfig_dict = config.get_kube_config().configuration
        if hasattr(kubeconfig_dict, "api_client") and kubeconfig_dict.api_client:
            pass

        if hasattr(config, "KubeConfigLoader"):
            pass

        logger.info("Successfully loaded kubeconfig, attempting to extract cluster name")

        try:
            config_dict = config.load_kube_config(return_config=True, config_file=kubeconfig)
            if hasattr(config_dict, "configuration") and hasattr(config_dict.configuration, "serialized_contents"):
                serialized = config_dict.configuration.serialized_contents
                parsed = yaml.safe_load(serialized)
                if parsed and "clusters" in parsed:
                    for cluster_entry in parsed["clusters"]:
                        if "cluster" in cluster_entry:
                            cluster_info = cluster_entry["cluster"]
                            if "name" in cluster_info:
                                cluster_name = cluster_info["name"]
                                logger.info(f"Extracted cluster name from kubeconfig: {cluster_name}")
                                return cluster_name
        except Exception as e:
            logger.debug(f"Could not extract cluster name from kubeconfig: {e}")

        try:
            machinesets = get_custom_objects_api().list_cluster_custom_object(group="machine.openshift.io", version="v1beta1", plural="machinesets")

            if machinesets and "items" in machinesets and len(machinesets["items"]) > 0:
                first_machineset = machinesets["items"][0]
                ms_name = first_machineset.get("metadata", {}).get("name", "")
                logger.debug(f"Found MachineSet: {ms_name}")

                if ms_name:
                    cluster_identifier = ms_name.split("-")[0]
                    logger.info(f"Extracted cluster identifier from MachineSet '{ms_name}': {cluster_identifier}")
                    return cluster_identifier

        except ApiException as e:
            logger.debug(f"Could not query MachineSets: {e}")
        except Exception as e:
            logger.debug(f"Unexpected error querying MachineSets: {e}")

        logger.warning("Could not determine cluster name from kubeconfig or MachineSets")
        return None

    except config.ConfigException as e:
        logger.error(f"Failed to load kubeconfig: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error extracting cluster name: {e}", exc_info=True)
        return None


def get_custom_objects_api() -> client.CustomObjectsApi:
    """Get a Kubernetes CustomObjectsApi client.

    This function provides access to the CustomObjectsApi for working with Custom Resource
    Definitions (CRDs) in Kubernetes.

    Returns:
        kubernetes.client.CustomObjectsApi: The CustomObjectsApi client instance

    Raises:
        kubernetes.client.rest.ApiException: If there are API connectivity issues
    """
    try:
        return client.CustomObjectsApi()
    except Exception as e:
        logger.error("Failed to create CustomObjectsApi client: %s", str(e))
        raise


def get_machine_for_node(node_name: str, crd_client: Optional[client.CustomObjectsApi] = None) -> Optional[Dict[str, Any]]:
    """Query Kubernetes for the Machine object associated with a Node.

    Args:
        node_name: Name of the node to find the associated Machine for
        crd_client: Optional CustomObjectsApi client. If not provided, creates a new one.

    Returns:
        Optional[Dict[str, Any]]: The Machine object if found, None otherwise
    """
    if not crd_client:
        crd_client = client.CustomObjectsApi()

    try:
        machines = crd_client.list_cluster_custom_object(group="machine.openshift.io", version="v1beta1", plural="machines")

        for machine in machines["items"]:
            # Type cast: machines["items"] is Any due to incomplete kubernetes type stubs
            machine_dict = cast(Dict[str, Any], machine)
            if machine_dict["status"]["nodeRef"]["name"] == node_name:
                logger.info(f"Found Machine {machine_dict['metadata']['name']} for Node {node_name}")
                return machine_dict
        logger.warning(f"No Machine found for Node {node_name}. This might be UPI.")
        return None
    except Exception as e:
        logger.error(f"Error fetching Machine for Node {node_name}: {e}")
        return None


def get_machineset_for_machine(machine: Dict[str, Any], crd_client: Optional[client.CustomObjectsApi] = None) -> Optional[Dict[str, Any]]:
    """Query Kubernetes for the MachineSet associated with a Machine.

    Args:
        machine: The Machine object to find the associated MachineSet for
        crd_client: Optional CustomObjectsApi client. If not provided, creates a new one.

    Returns:
        Optional[Dict[str, Any]]: The MachineSet object if found, None otherwise
    """
    if not crd_client:
        crd_client = client.CustomObjectsApi()

    try:
        machinesets = crd_client.list_cluster_custom_object(group="machine.openshift.io", version="v1beta1", plural="machinesets")

        machine_name = machine["metadata"]["name"]
        for ms in machinesets["items"]:
            # Type cast: machinesets["items"] is Any due to incomplete kubernetes type stubs
            ms_dict = cast(Dict[str, Any], ms)
            if ms_dict["metadata"]["name"] in machine_name:
                logger.info(f"Found MachineSet {ms_dict['metadata']['name']} for Machine {machine_name}")
                return ms_dict
        logger.warning(f"No MachineSet found for Machine {machine_name}.")
        return None
    except Exception as e:
        logger.error(f"Error fetching MachineSet for Machine {machine['metadata'].get('name', 'unknown')}: {e}")
        return None


def exec_pod_command(
    namespace: str,
    pod_name: str,
    command: List[str],
    container: Optional[str] = None,
    stdout: bool = True,
    stderr: bool = True,
    stdin: bool = False,
    tty: bool = False,
    v1_client: Optional[client.CoreV1Api] = None,
) -> Tuple[int, str, str]:
    """Execute a command in a pod and stream the output.

    Args:
        namespace: Pod namespace
        pod_name: Pod name
        command: Command to execute
        container: Optional container name. If not specified, will be determined.
        stdout: Capture stdout. Defaults to True.
        stderr: Capture stderr. Defaults to True.
        stdin: Enable stdin. Defaults to False.
        tty: Enable TTY. Defaults to False.
        v1_client: Optional CoreV1Api client. If not provided, creates a new one.

    Returns:
        A tuple containing the exit code (int), stdout (str), and stderr (str).

    Raises:
        ApiException: If the Kubernetes API call fails.
        ValueError: If container resolution fails.
    """
    if not v1_client:
        v1_client = client.CoreV1Api()

    try:
        pod = v1_client.read_namespaced_pod(name=pod_name, namespace=namespace)
        target_container = determine_target_container(pod, container)
    except ApiException as e:
        logger.error(f"Failed to read pod '{pod_name}' in namespace '{namespace}': {e}")
        raise

    exec_command = [str(cmd) for cmd in command]

    stdout_data = ""
    stderr_data = ""
    exit_code = -1
    resp = None

    try:
        resp = stream.stream(
            v1_client.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=namespace,
            container=target_container,
            command=exec_command,
            stdout=stdout,
            stderr=stderr,
            stdin=stdin,
            tty=tty,
            _preload_content=False,
        )

        while resp.is_open():
            resp.update(timeout=1)
            if resp.peek_stdout():
                stdout_data += resp.read_stdout()
            if resp.peek_stderr():
                stderr_data += resp.read_stderr()

    except ApiException as e:
        logger.error(f"API error executing command in pod '{pod_name}': {e.reason}")
        raise
    finally:
        if resp:
            resp.close()
            # Ensure returncode is an integer
            exit_code = resp.returncode if resp.returncode is not None else -1

    if exit_code != 0:
        logger.error(f"Command in pod '{pod_name}' failed with exit code {exit_code}. Stderr: {stderr_data.strip()}")

    return exit_code, stdout_data, stderr_data


def wait_for_pod_readiness(
    pod_name: str,
    namespace: str,
    timeout: int = 420,
    v1_client: Optional[client.CoreV1Api] = None,
) -> bool:
    """Wait for a pod to be ready (1/1) with a timeout.

    Args:
        pod_name: Name of the pod to check
        namespace: Namespace where the pod is located
        timeout: Maximum time to wait in seconds (default: 420 seconds / 7 minutes)
        v1_client: Optional CoreV1Api client. If not provided, creates a new one.

    Returns:
        bool: True if pod becomes ready within timeout, False otherwise
    """
    if not v1_client:
        v1_client = client.CoreV1Api()

    interval = 15  # Check every 15 seconds
    elapsed_time = 0

    while elapsed_time < timeout:
        try:
            pod = v1_client.read_namespaced_pod(name=pod_name, namespace=namespace)
            pod_status = pod.status.container_statuses[0].ready
            if pod_status:
                logger.info(f"Pod {pod_name} is ready (1/1).")
                return True
        except ApiException as e:
            logger.error(f"Error reading pod {pod_name} status: {e}")
            return False

        elapsed_time += interval
        logger.debug(f"Waiting for pod {pod_name} to be ready... ({elapsed_time}/{timeout} seconds elapsed)")
        time.sleep(interval)

    logger.warning(f"Timeout reached: Pod {pod_name} is not ready after {timeout} seconds.")
    return False


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


def _extract_node_info_from_machine(machine: Dict[str, Any], machineset_name: str, machineset_labels: Dict[str, str]) -> Optional[Tuple[str, Dict[str, str]]]:
    """Process a single machine object to extract node info if it matches the machineset.

    Helper function for get_nodes_from_machineset_specific that processes a Machine
    object to determine if it belongs to the specified MachineSet and extracts
    associated node information.

    Args:
        machine: Dictionary representing a Machine object from Kubernetes API.
        machineset_name: Name of the MachineSet to match against.
        machineset_labels: Dictionary of labels from the MachineSet.

    Returns:
        Optional[Tuple[str, Dict[str, str]]]: Tuple containing node name and
            machineset labels if the machine matches and has an associated node,
            None otherwise.
    """
    machine_metadata = machine.get("metadata", {})
    machine_name = machine_metadata.get("name", "")
    machine_status = machine.get("status")

    if _machine_owned_by_machineset(machine, machineset_name) and machine_status:
        node_name = machine_status.get("nodeRef", {}).get("name")
        if node_name:
            logger.info(f"Associated node {node_name} with MachineSet {machineset_name} via Machine {machine_name}")
            # Return node name and a copy of the machineset labels
            return node_name, machineset_labels.copy()
    return None


def get_kubeconfig_from_vault(  # noqa: C901
    cluster_name: str,
    inventory_url: str,
    vault_url: Optional[str] = None,
    vault_token: Optional[str] = None,
    kubeconfig_dir: str = "tmp/k8s",
) -> tuple[str, str]:
    """Retrieve kubeconfig from inventory and vault sources for a given cluster.

    This function fetches the kubeconfig for a specified cluster by:
    1. Getting cluster configuration from inventory
    2. Using that information to retrieve the kubeconfig from Vault
    3. Storing the kubeconfig in a local file under tmp/k8s directory

    Args:
        cluster_name: Name of the cluster to get kubeconfig for
        inventory_url: URL of the inventory service
        vault_url: Optional Vault server URL. If None, uses VAULT_ADDR environment variable
        vault_token: Optional Vault token. If None, uses VAULT_TOKEN environment variable
        kubeconfig_dir: Directory to store kubeconfig files (default: "tmp/k8s")

    Returns:
        tuple[str, str]: A tuple containing:
            - Path to the saved kubeconfig file
            - Kubeconfig data as a string that can be used directly with load_kube_config

    Raises:
        ValueError: If cluster_name contains invalid characters
        OSError: If kubeconfig directory is not writable
        VaultError: If Vault operations fail
        requests.RequestException: If inventory API request fails

    Example:
        cluster_name = "euse1c-4"
        inventory_url = "http://inventory.example.com"
        kubeconfig_dir = "tmp/k8s"
        vault_url = "http://vault.example.com"
        vault_token = "my-vault-token"

        kubeconfig_path, kubeconfig_data = get_kubeconfig_from_vault(
            cluster_name,
            inventory_url,
            vault_url,
            vault_token,
            kubeconfig_dir,
        )

        # Load kubeconfig data into KUBECONFIG
        load_kube_config(kubeconfig_data)
    """
    logger.info(f"Retrieving kubeconfig for cluster: {cluster_name}")

    # Get project root directory (where tmp/ should be located)
    project_root = Path(__file__).resolve().parents[1]
    kubeconfig_path = project_root / kubeconfig_dir

    # Validate cluster name
    if not re.match(r"^[a-zA-Z0-9_.-]+$", cluster_name):
        msg = f"Invalid cluster name: {cluster_name}. Must contain only alphanumeric characters, dots, dashes, and underscores."
        logger.error(msg)
        raise ValueError(msg)

    # Ensure kubeconfig directory exists and is writable
    kubeconfig_path.mkdir(parents=True, exist_ok=True)
    if not os.access(kubeconfig_path, os.W_OK):
        msg = f"Directory not writable: {kubeconfig_path}"
        logger.error(msg)
        raise OSError(msg)

    # Get inventory data
    logger.debug(f"Fetching inventory data from: {inventory_url}")
    try:
        response = requests.get(f"{inventory_url}/clusters/{cluster_name}")
        response.raise_for_status()
        inventory_data = response.json()
    except requests.RequestException as e:
        logger.error(f"Failed to get inventory data: {e}")
        raise

    # Extract Vault path from inventory data
    try:
        vault_config = inventory_data["kubernetes_platform"]["secrets_management"]["platform_vault"][0]
        vault_url = vault_config["address"]
        vault_namespace = vault_config["namespace"]
        raw_path = vault_config["default_path"]

        # Normalize the vault path
        vault_mount, vault_path = normalize_vault_path(raw_path)
        if not all([vault_url, vault_namespace, vault_path]):
            msg = "Missing required vault configuration in inventory"
            logger.error(msg)
            raise ValueError(msg)

    except (KeyError, IndexError) as e:
        msg = f"Invalid inventory data structure: {e}"
        logger.error(msg)
        raise ValueError(msg)

    # Create Vault client and get kubeconfig
    logger.debug("Creating Vault client")
    vault_client = create_vault_client(
        url=vault_url if vault_url else None,
        token=vault_token,
        namespace=vault_namespace,
    )
    try:
        secret = get_secret(vault_client, vault_path, mount_point=vault_mount)
        if not secret:
            msg = f"No secret found in Vault at path: {vault_path}"
            logger.error(msg)
            raise ValueError(msg)
        kubeconfig_data = secret.get("kubeconfig")
        if not kubeconfig_data:
            msg = f"No kubeconfig found in Vault at path: {vault_path}"
            logger.error(msg)
            raise ValueError(msg)
    except VaultError as e:
        logger.error(f"Failed to get kubeconfig from Vault: {e}")
        raise

    # Save kubeconfig to file
    kubeconfig_file = kubeconfig_path / f"{cluster_name}.kubeconfig"
    try:
        kubeconfig_file.write_text(kubeconfig_data)
        logger.info(f"Saved kubeconfig to: {kubeconfig_file}")
    except OSError as e:
        logger.error(f"Failed to write kubeconfig file: {e}")
        raise

    return str(kubeconfig_file), kubeconfig_data


def get_nodes_from_machineset_specific(  # noqa: C901
    machineset_name: str,
    label_key: Optional[str] = None,
    crd_client: Optional[client.CustomObjectsApi] = None,
    namespace: str = "openshift-machine-api",
) -> Dict[str, Dict[str, str]]:
    """Query Kubernetes for nodes associated with a specific MachineSet and their labels.

    Args:
        machineset_name: Name of the MachineSet to query
        label_key: Optional label key to extract from MachineSet (e.g., "topology.kubernetes.io/zone")
        crd_client: Optional CustomObjectsApi client. If not provided, creates a new one.
        namespace: Namespace where MachineSets reside (default: openshift-machine-api)

    Returns:
        Dict[str, Dict[str, str]]: A dictionary mapping node names to their labels and values.
        Example: {"node1": {"zone": "us-east-1a", "label2": "value2"}}
    """
    if not crd_client:
        crd_client = client.CustomObjectsApi()

    try:
        # Get all MachineSets (MachineSets are namespaced resources)
        machinesets = crd_client.list_namespaced_custom_object(
            group="machine.openshift.io",
            version="v1beta1",
            namespace=namespace,
            plural="machinesets",
        )

        # Find the specific MachineSet object by name
        machineset = next(
            (ms for ms in machinesets.get("items", []) if ms.get("metadata", {}).get("name") == machineset_name),
            None,
        )

        if not machineset:
            logger.error(f"MachineSet '{machineset_name}' not found in namespace '{namespace}'.")
            return {}

        node_info: Dict[str, Dict[str, str]] = {}

        # Extract labels from the MachineSet
        ms_labels = machineset.get("metadata", {}).get("labels", {})
        if label_key:
            if label_key in ms_labels:
                logger.info(f"Found label {label_key}={ms_labels[label_key]} in MachineSet {machineset_name}")
            else:
                logger.warning(f"Label '{label_key}' not found in MachineSet {machineset_name}")

        # Find associated machines for the MachineSet
        machines = crd_client.list_namespaced_custom_object(
            group="machine.openshift.io",
            version="v1beta1",
            namespace=namespace,
            plural="machines",
        )

        for machine in machines.get("items", []):
            # Use helper function to process each machine
            node_data = _extract_node_info_from_machine(machine, machineset_name, ms_labels)
            if node_data:
                node_name, labels = node_data
                node_info[node_name] = labels

        if node_info:
            logger.info(f"Found {len(node_info)} node(s) associated with MachineSet {machineset_name} in namespace {namespace}.")
        else:
            logger.warning(f"No nodes found associated with MachineSet {machineset_name} in namespace {namespace}.")

        return node_info

    except ApiException as e:
        logger.error(f"Kubernetes API error retrieving nodes for MachineSet '{machineset_name}': {e}")
        return {}
    except Exception as e:
        logger.error(
            f"Unexpected error retrieving nodes for MachineSet '{machineset_name}': {e}",
            exc_info=True,
        )
        return {}


def get_nodes_from_machinesets(  # noqa: C901
    label_key: Optional[str] = None,
    crd_client: Optional[client.CustomObjectsApi] = None,
    namespace: str = "openshift-machine-api",
) -> Dict[str, Dict[str, str]]:
    """Query Kubernetes for all nodes associated with MachineSets and their labels.

    Args:
        label_key: Optional label key to extract from MachineSets (e.g., "topology.kubernetes.io/zone")
        crd_client: Optional CustomObjectsApi client. If not provided, creates a new one.
        namespace: Namespace where MachineSets reside (default: openshift-machine-api)

    Returns:
        Dict[str, Dict[str, str]]: A dictionary mapping node names to their labels and values.
        Example: {"node1": {"zone": "us-east-1a", "label2": "value2"}}
    """
    if not crd_client:
        crd_client = client.CustomObjectsApi()

    try:
        machinesets = crd_client.list_cluster_custom_object(group="machine.openshift.io", version="v1beta1", plural="machinesets")

        node_info: Dict[str, Dict[str, str]] = {}

        for ms in machinesets["items"]:
            ms_name = ms["metadata"]["name"]
            logger.info(f"Processing MachineSet: {ms_name}")

            # Extract labels from the MachineSet
            ms_labels = ms.get("metadata", {}).get("labels", {})
            if label_key and label_key in ms_labels:
                logger.info(f"Found label {label_key}={ms_labels[label_key]} in MachineSet {ms_name}")
            else:
                if label_key:
                    logger.warning(f"Label {label_key} not found in MachineSet {ms_name}")

            # Find associated machines for the MachineSet
            machines = crd_client.list_cluster_custom_object(group="machine.openshift.io", version="v1beta1", plural="machines")

            pattern = re.compile(rf"^{re.escape(ms_name)}-.+")

            for machine in machines["items"]:
                # Check if the machine is part of the current MachineSet using exact match
                if pattern.match(machine["metadata"]["name"]) and "status" in machine:
                    node_name = machine["status"].get("nodeRef", {}).get("name", None)
                    if node_name:
                        # Store all labels and their values
                        node_info[node_name] = ms_labels.copy()
                        logger.info(f"Associated node {node_name} with MachineSet {ms_name}")

        if node_info:
            logger.info(f"Found {len(node_info)} node(s) associated with MachineSets.")
        else:
            logger.warning("No nodes found in MachineSets.")

        return node_info

    except Exception as e:
        logger.error(f"Error retrieving nodes from MachineSets: {e}")
        return {}


def get_configmap_data(
    namespace: str,
    configmap_name: str,
    key: Optional[str] = None,
    v1_client: Optional[client.CoreV1Api] = None,
) -> Dict[str, Any]:
    """Get data from a Kubernetes ConfigMap.

    Args:
        namespace: Kubernetes namespace
        configmap_name: Name of the ConfigMap
        key: Optional specific key to retrieve from ConfigMap data
        v1_client: Optional CoreV1Api client. If not provided, creates a new one.

    Returns:
        Dictionary containing the ConfigMap data or specific key value if key provided
    """
    try:
        if not v1_client:
            v1_client = get_k8s_client("CoreV1Api")

        # Get the ConfigMap
        configmap = v1_client.read_namespaced_config_map(configmap_name, namespace)

        if key:
            # Type cast: configmap.data is Any due to incomplete kubernetes type stubs
            configmap_data = cast(Dict[str, Any], configmap.data)
            if key not in configmap_data:
                raise KeyError(f"Key '{key}' not found in ConfigMap")
            return {key: configmap_data[key]}

        # Type cast: configmap.data is Any due to incomplete kubernetes type stubs
        return cast(Dict[str, Any], configmap.data)
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to get ConfigMap data: {str(e)}")
        raise


def parse_storage_string(storage_str: str) -> Optional[int]:
    """Parse Kubernetes storage strings into bytes.

    Converts Kubernetes storage quantity strings (e.g., "10Gi", "500Mi", "1T")
    into their byte equivalents. Supports both decimal (K, M, G, T, P, E) and
    binary (Ki, Mi, Gi, Ti, Pi, Ei) units.

    Args:
        storage_str: Storage string in Kubernetes format (e.g., "10Gi", "500Mi").

    Returns:
        Optional[int]: Number of bytes if parsing succeeds, None if parsing fails.
            Returns 0 for empty or invalid input types.

    Examples:
        >>> parse_storage_string("10Gi")
        10737418240
        >>> parse_storage_string("500Mi")
        524288000
    """
    if not storage_str:
        return 0
    multipliers = {
        "K": 1000,
        "M": 1000**2,
        "G": 1000**3,
        "T": 1000**4,
        "P": 1000**5,
        "E": 1000**6,
        "Ki": 1024,
        "Mi": 1024**2,
        "Gi": 1024**3,
        "Ti": 1024**4,
        "Pi": 1024**5,
        "Ei": 1024**6,
    }
    match = re.match(r"^(\d+)([KMGTPE]i?|)$", storage_str)
    if match:
        value, unit = match.groups()
        value = int(value)
        if unit in multipliers:
            return value * multipliers[unit]
        elif unit == "":  # Assume bytes if no unit
            return value
        else:
            logger.warning(f"Unknown storage unit '{unit}' in string '{storage_str}'")
            return None  # Indicate parsing failure
    else:
        # Handle cases like "1.5Gi" or other formats if necessary, for now just log warning
        logger.warning(f"Could not parse storage string: '{storage_str}'")
        return None  # Indicate parsing failure


def list_all_namespaces(api_client: Optional[ApiClient] = None) -> Optional[List[str]]:
    """Retrieve a list of all namespace names in the cluster.

    Args:
        api_client: Optional initialized Kubernetes ApiClient. If not provided,
            creates a new CoreV1Api client.

    Returns:
        Optional[List[str]]: List of namespace names if successful, None if an
            error occurs.

    Raises:
        ApiException: If the Kubernetes API call fails.
        Exception: For other unexpected errors during namespace listing.
    """
    try:
        v1 = client.CoreV1Api(api_client)
        namespaces_list = v1.list_namespace()
        return [ns.metadata.name for ns in namespaces_list.items]
    except ApiException as e:
        logger.error(f"Error listing namespaces: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error listing namespaces: {e}")
        return None


def namespace_exists(namespace_name: str, api_client: Optional[ApiClient] = None) -> bool:
    """Checks if a specific namespace exists in the cluster.

    Args:
        namespace_name: The name of the namespace to check.
        api_client: Optional initialized Kubernetes ApiClient.

    Returns:
        True if the namespace exists, False otherwise.
    """
    if not namespace_name:
        return False
    try:
        v1 = client.CoreV1Api(api_client)
        v1.read_namespace(name=namespace_name)
        return True
    except ApiException as e:
        if e.status == 404:
            logger.debug(f"Namespace '{namespace_name}' not found (404).")
        else:
            logger.error(f"Error checking namespace {namespace_name}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error checking namespace {namespace_name}: {e}")
        return False


def format_duration(seconds: float) -> str:
    """Format a duration in seconds into a human-readable string.

    Converts a duration in seconds into a human-readable format showing days,
    hours, minutes, and seconds as appropriate.

    Args:
        seconds: Duration in seconds (can be a float for sub-second precision).

    Returns:
        str: Human-readable duration string (e.g., "2 days, 3 hours, 15 minutes, 30 seconds").
            Returns "Invalid duration" if seconds is negative, "0 seconds" if zero.

    Examples:
        >>> format_duration(90061)
        "1 day, 1 hour, 1 minute, 1 second"
        >>> format_duration(45.5)
        "45.50 seconds"
    """
    if seconds < 0:
        return "Invalid duration"
    if seconds == 0:
        return "0 seconds"

    # Calculate components
    total_seconds = int(seconds)
    days, remainder = divmod(total_seconds, 86400)  # 60 * 60 * 24
    hours, remainder = divmod(remainder, 3600)  # 60 * 60
    minutes, secs = divmod(remainder, 60)

    # Build the string
    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    # Always show seconds if > 0 or if it's the only unit
    if secs > 0 or not parts:
        # Add fractional part if original input was float and < 60s
        if seconds < 60 and seconds != float(total_seconds):
            sec_str = f"{seconds:.2f}"
        else:
            sec_str = str(secs)
        parts.append(f"{sec_str} second{'s' if secs != 1 or (seconds < 60 and seconds != 1.0) else ''}")

    return ", ".join(parts)


def determine_target_container(pod: V1Pod, specified_container_name: Optional[str]) -> str:
    """Determine the container to execute the command in, handling errors.

    Determines which container in a pod should be used for command execution.
    If the pod has only one container, that container is used (and any specified
    name is validated). If multiple containers exist, a container name must be
    specified.

    Args:
        pod: The V1Pod object containing container specifications.
        specified_container_name: Optional container name provided by the user.
            If None and pod has multiple containers, raises ValueError.

    Returns:
        str: The validated name of the target container.

    Raises:
        ValueError: If container resolution fails (e.g., container not found,
            multiple containers but none specified, or specified container doesn't exist).
    """
    containers = pod.spec.containers
    container_names = [c.name for c in containers]
    pod_name = pod.metadata.name
    logger_local = logging.getLogger(__name__)  # Use local logger

    if len(containers) == 1:
        # Type cast: containers[0].name is Any due to incomplete kubernetes type stubs
        actual_container_name = cast(str, containers[0].name)
        if specified_container_name and specified_container_name != actual_container_name:
            logger_local.warning(f"Specified container '{specified_container_name}' ignored; pod '{pod_name}' has only one container: '{actual_container_name}'.")
        logger_local.debug(f"Pod '{pod_name}' has one container: '{actual_container_name}'. Using it.")
        return actual_container_name
    elif specified_container_name:
        if specified_container_name in container_names:
            logger_local.debug(f"Using specified container: '{specified_container_name}' for pod '{pod_name}'.")
            return specified_container_name
        else:
            error_msg = f"Specified container '{specified_container_name}' not found in pod '{pod_name}'. " f"Available containers: {', '.join(container_names)}"
            logger_local.error(error_msg)
            raise ValueError(error_msg)
    else:
        # Multiple containers, but none specified
        error_msg = f"Pod '{pod_name}' has multiple containers ({', '.join(container_names)}). " f"Please specify the target container."
        logger_local.error(error_msg)
        raise ValueError(error_msg)


def find_running_pod_by_label(
    namespace: str,
    label_selector: str,
    v1_client: Optional[client.CoreV1Api] = None,
) -> Optional[V1Pod]:
    """Find the first running pod based on a label selector.

    Searches for pods in the specified namespace matching the label selector
    and returns the first pod that is in the "Running" phase.

    Args:
        namespace: The namespace to search in.
        label_selector: The label selector string to filter pods (e.g., "app=myapp").
        v1_client: Optional CoreV1Api client. If not provided, creates a new one.

    Returns:
        Optional[V1Pod]: The V1Pod object if a running pod is found, None if
            no pods match the selector or no running pods are found.

    Raises:
        ApiException: If the Kubernetes API call fails.
    """
    if not v1_client:
        v1_client = client.CoreV1Api()

    logger.debug(f"Searching for running pod with labels '{label_selector}' in namespace '{namespace}'...")
    try:
        pods = v1_client.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
        if not pods.items:
            logger.warning(f"No pods found with labels '{label_selector}' in namespace '{namespace}'.")
            return None

        for pod in pods.items:
            if pod.status.phase == "Running":
                logger.info(f"Found running pod: '{pod.metadata.name}'")
                return pod

        logger.warning(f"No *running* pods found with labels '{label_selector}' in '{namespace}'.")
        return None
    except ApiException as e:
        logger.error(
            f"API error finding pod in namespace '{namespace}': {e.status} - {e.reason}",
            exc_info=True,
        )
        return None
    except Exception as e:
        logger.exception(f"Unexpected error finding pod: {e}")
        return None


def get_secret_data(
    namespace: str,
    secret_name: str,
    v1_client: Optional[client.CoreV1Api] = None,
) -> Optional[Dict[str, str]]:
    """Retrieve and decode all data from a Kubernetes secret.

    Reads a Kubernetes secret and decodes all base64-encoded values into UTF-8 strings.

    Args:
        namespace: The namespace containing the secret.
        secret_name: The name of the secret to retrieve.
        v1_client: Optional CoreV1Api client. If not provided, creates a new one.

    Returns:
        Optional[Dict[str, str]]: Dictionary with decoded secret data (key-value pairs),
            empty dictionary if secret exists but has no data, None if secret is not
            found or an error occurs during decoding.

    Raises:
        ApiException: If the Kubernetes API call fails (e.g., secret not found).
        base64.binascii.Error: If base64 decoding fails.
        UnicodeDecodeError: If UTF-8 decoding fails.
    """
    if not v1_client:
        v1_client = client.CoreV1Api()

    logger.debug(f"Attempting to read secret '{secret_name}' in namespace '{namespace}'.")
    try:
        secret = v1_client.read_namespaced_secret(secret_name, namespace)
        if not secret.data:
            logger.warning(f"Secret '{secret_name}' in namespace '{namespace}' contains no data.")
            return {}

        # Decode all values from base64
        decoded_data = {key: base64.b64decode(value).decode("utf-8") for key, value in secret.data.items() if value}
        return decoded_data
    except ApiException as e:
        if e.status == 404:
            logger.error(f"Secret '{secret_name}' not found in namespace '{namespace}'.")
        else:
            logger.error(f"API error reading secret '{secret_name}': {e.reason}", exc_info=True)
        return None
    except (binascii.Error, UnicodeDecodeError) as e:
        logger.error(f"Failed to decode secret data from '{secret_name}': {e}", exc_info=True)
        return None


def get_service_account_jwt(
    namespace: str,
    service_account_name: str,
    v1_client: Optional[client.CoreV1Api] = None,
) -> Optional[str]:
    """Retrieve an existing Kubernetes service account token (JWT) from a secret.

    Searches for a secret associated with the service account that contains
    '-token' in its name and extracts the JWT token from the 'token' key.

    Args:
        namespace: The namespace containing the service account.
        service_account_name: The name of the service account.
        v1_client: Optional CoreV1Api client. If not provided, creates a new one.

    Returns:
        Optional[str]: The JWT token string if found, None if no token secret is
            found or an error occurs.

    Raises:
        ApiException: If the Kubernetes API call fails.
        Exception: For other unexpected errors during token retrieval.
    """
    if not v1_client:
        v1_client = client.CoreV1Api()

    logger.info(f"Searching for an existing token secret for SA '{service_account_name}' in namespace '{namespace}'.")
    try:
        secrets = v1_client.list_namespaced_secret(namespace)
        for secret in secrets.items:
            secret_name = secret.metadata.name
            annotations = secret.metadata.annotations
            if (
                secret.type == "kubernetes.io/service-account-token"
                and annotations
                and annotations.get("kubernetes.io/service-account.name") == service_account_name
                and f"{service_account_name}-token" in secret_name
            ):
                if "token" in secret.data and secret.data["token"]:
                    token_b64 = secret.data["token"]
                    token = base64.b64decode(token_b64).decode("utf-8").strip()
                    logger.info(f"Found and decoded service account JWT from secret '{secret_name}'.")
                    return token
                else:
                    logger.warning(f"Secret '{secret_name}' is a SA token but missing 'token' data.")

    except ApiException as e:
        logger.error(
            f"API error listing secrets in namespace '{namespace}': {e.reason}",
            exc_info=True,
        )

    logger.error(f"Could not retrieve a token for ServiceAccount '{service_account_name}'.")
    return None


def get_cluster_name_from_config() -> str:
    """Derive a cluster name from the current kubeconfig context's server URL.

    Extracts and sanitizes a cluster name from the Kubernetes API server URL
    in the current kubeconfig. Removes common prefixes like 'api.' and sanitizes
    the hostname to create a valid cluster identifier.

    Returns:
        str: A sanitized cluster name derived from the API server hostname,
            or 'unknown_cluster' if the hostname cannot be determined or parsed.

    Examples:
        >>> # For API URL: https://api.my-cluster.dev.example.com:6443
        >>> # Returns: "my-cluster"
    """
    try:
        # Load the configuration to get the host
        config = client.Configuration.get_default_copy()
        if not config or not config.host:
            logger.warning("Could not determine Kubernetes API host from config.")
            return "unknown_cluster"

        # The host is a full URL, e.g., https://api.my-cluster.dev.example.com:6443
        from urllib.parse import urlparse

        hostname = urlparse(config.host).hostname
        if not hostname:
            return "unknown_cluster"

        # Sanitize the hostname
        # Remove common prefixes like 'api.'
        if hostname.startswith("api."):
            hostname = hostname[4:]

        # Take the first part of the hostname as the cluster name
        cluster_name = hostname.split(".")[0]

        # Final sanitization for file names
        sanitized_name = re.sub(r"[^a-zA-Z0-9_-]", "", cluster_name)
        logger.debug(f"Derived cluster name '{sanitized_name}' from host '{config.host}'")
        return sanitized_name

    except Exception as e:
        logger.error(f"Failed to get cluster name from kubeconfig: {e}", exc_info=True)
        return "unknown_cluster"


def get_machineset_resource_pool(
    machineset: Dict[str, Any],
) -> Optional[str]:
    """Extract the resourcePool path from a MachineSet.

    Args:
        machineset: The MachineSet resource dictionary

    Returns:
        The resourcePool path string, or None if not found

    Example:
        >>> machineset = get_machineset("my-machineset")
        >>> resource_pool = get_machineset_resource_pool(machineset)
        >>> print(resource_pool)
        /vcenterdc/host/hostclustername/Resources
    """
    resource_pool: Optional[str] = cast(
        Optional[str],
        machineset.get("spec", {}).get("template", {}).get("spec", {}).get("providerSpec", {}).get("value", {}).get("workspace", {}).get("resourcePool"),
    )
    return resource_pool


def parse_resource_pool_path(resource_pool: str) -> str:
    """Extract the ESXi host cluster name from the resourcePool path.

    The resourcePool path follows the format:
    /datacenter/host/cluster_name/Resources

    Args:
        resource_pool: The resourcePool path (e.g.,
            '/vcenterdc/host/hostclustername/Resources')

    Returns:
        The extracted host cluster name (e.g., 'hostclustername')

    Examples:
        >>> parse_resource_pool_path('/vcenterdc/host/hostclustername/Resources')
        'hostclustername'
        >>> parse_resource_pool_path('/DC1/host/CLUSTER/Resources')
        'CLUSTER'
    """
    logger.debug("Parsing resourcePool path: %s", resource_pool)

    # Parse the path: /datacenter/host/cluster_name/Resources
    # Extract the cluster name (third component)
    parts = resource_pool.strip("/").split("/")

    if len(parts) >= 3:
        cluster_name = parts[2]
        logger.debug("Extracted cluster name: %s", cluster_name)
        return cluster_name

    logger.warning(
        "Could not parse cluster name from resourcePool path: %s, using original",
        resource_pool,
    )
    return resource_pool


def get_zone_label(
    resource: Dict[str, Any],
    label_key: str = "topology.portworx.io/zone",
) -> Optional[str]:
    """Get the zone label value from any Kubernetes resource.

    Args:
        resource: The Kubernetes resource dictionary (MachineSet, Machine, or Node)
        label_key: The label key to look for (default: topology.portworx.io/zone)

    Returns:
        The label value if found, None otherwise

    Examples:
        >>> machineset = get_machineset("my-machineset")
        >>> zone = get_zone_label(machineset)
        >>> print(zone)
        hostclustername
    """
    # Try different label paths based on resource type
    # MachineSet: spec.template.spec.metadata.labels
    # Machine: spec.metadata.labels
    # Node: metadata.labels

    # Try MachineSet path first
    labels = resource.get("spec", {}).get("template", {}).get("spec", {}).get("metadata", {}).get("labels")

    # Try Machine path if not found
    if not labels:
        labels = resource.get("spec", {}).get("metadata", {}).get("labels")

    # Try Node path if not found
    if not labels:
        labels = resource.get("metadata", {}).get("labels")

    if labels:
        label_value: Optional[str] = cast(Optional[str], labels.get(label_key))
        return label_value

    return None


def update_zone_label(
    resource: Dict[str, Any],
    label_key: str,
    new_value: str,
    dry_run: bool = False,
    crd_client: Optional[client.CustomObjectsApi] = None,
    v1_client: Optional[client.CoreV1Api] = None,
    max_retries: int = 3,
    base_retry_delay: float = 1.0,
) -> Tuple[bool, Optional[str]]:
    """Update the zone label on a Kubernetes resource.

    Args:
        resource: The Kubernetes resource dictionary (MachineSet, Machine, or Node)
        label_key: The label key to update
        new_value: The new label value
        dry_run: If True, only show what would be changed
        crd_client: Optional CustomObjectsApi client for MachineSet/Machine updates
        v1_client: Optional CoreV1Api client for Node updates
        max_retries: Maximum number of retry attempts for conflict errors (default: 3)
        base_retry_delay: Base delay in seconds for exponential backoff (default: 1.0)

    Returns:
        Tuple of (success, old_value).
        success: True if update succeeded or skipped, False if user declined
        old_value: The existing label value (or None if not set)

    Examples:
        >>> machineset = get_machineset("my-machineset")
        >>> success, old = update_zone_label(machineset, "topology.portworx.io/zone", "new-zone")
    """
    resource_name = resource.get("metadata", {}).get("name", "unknown")
    existing_value = get_zone_label(resource, label_key)
    resource_version = resource.get("metadata", {}).get("resourceVersion", "")

    # Idempotency check: skip if label already matches
    if existing_value and existing_value == new_value:
        logger.debug(
            "Label %s already set to %s on %s %s (resourceVersion=%s), skipping",
            label_key,
            new_value,
            resource.get("kind", "Resource"),
            resource_name,
            resource_version if resource_version else "none",
        )
        return (True, existing_value)

    # Existing label differs from target (e.g. old cluster id vs ESXi cluster from resourcePool)
    if existing_value and existing_value != new_value:
        if dry_run:
            console.print(f"[yellow]DRY-RUN:[/yellow] {resource.get('kind', 'Resource')} {resource_name} would set {label_key}: {existing_value} -> {new_value}")
        else:
            logger.warning(
                "Label mismatch for %s %s (resourceVersion=%s): existing=%s, new=%s",
                resource.get("kind", "Resource"),
                resource_name,
                resource_version if resource_version else "none",
                existing_value,
                new_value,
            )
        # Note: This function doesn't handle user confirmation - that's up to the caller

    # Determine resource type and patch path
    kind = resource.get("kind", "")

    if not dry_run:
        retry_count = 0
        last_error: Optional[Exception] = None

        while retry_count < max_retries:
            try:
                if kind == "Node":
                    # Node is a CoreV1 resource
                    if not v1_client:
                        v1_client = client.CoreV1Api()
                    patch_data: Dict[str, Any] = {"metadata": {"labels": {label_key: new_value}}}
                    v1_client.patch_node(name=resource_name, body=patch_data)
                else:
                    # MachineSet and Machine are Custom Resources
                    if not crd_client:
                        crd_client = client.CustomObjectsApi()

                    if kind == "MachineSet":
                        patch_data = {"spec": {"template": {"spec": {"metadata": {"labels": {label_key: new_value}}}}}}
                        crd_client.patch_namespaced_custom_object(
                            group="machine.openshift.io",
                            version="v1beta1",
                            namespace="openshift-machine-api",
                            plural="machinesets",
                            name=resource_name,
                            body=patch_data,
                        )
                    elif kind == "Machine":
                        patch_data = {"spec": {"metadata": {"labels": {label_key: new_value}}}}
                        crd_client.patch_cluster_custom_object(
                            group="machine.openshift.io",
                            version="v1beta1",
                            plural="machines",
                            name=resource_name,
                            body=patch_data,
                        )
                    else:
                        logger.warning("Unknown resource kind: %s", kind)
                        return (False, existing_value)

                logger.info(
                    "Updated %s %s with label %s: %s",
                    kind,
                    resource_name,
                    label_key,
                    new_value,
                )
                return (True, existing_value)

            except ApiException as e:
                last_error = e
                error_reason = getattr(e, "reason", str(e))
                error_status = getattr(e, "status", None)

                # Check for conflict (409) - resource version mismatch
                if error_status == 409 and retry_count < max_retries - 1:
                    retry_count += 1
                    delay = base_retry_delay * (2 ** (retry_count - 1))
                    logger.warning(
                        "Conflict updating %s %s (attempt %d/%d, retrying in %.1fs): %s",
                        kind,
                        resource_name,
                        retry_count,
                        max_retries,
                        delay,
                        error_reason,
                    )
                    time.sleep(delay)
                    continue

                # For other errors or after max retries, log and fail
                logger.error(
                    "Failed to update %s %s after %d attempts: %s",
                    kind,
                    resource_name,
                    retry_count + 1,
                    error_reason,
                )
                return (False, existing_value)
            except Exception as e:
                logger.error(
                    "Unexpected error updating %s %s (attempt %d/%d): %s",
                    kind,
                    resource_name,
                    retry_count + 1,
                    max_retries,
                    e,
                    exc_info=True,
                )
                return (False, existing_value)

        # Max retries exceeded
        logger.error(
            "Failed to update %s %s after %d retries: %s",
            kind,
            resource_name,
            max_retries,
            getattr(last_error, "reason", None) if last_error else "unknown error",
        )
        return (False, existing_value)
    else:
        console.print(f"[yellow]DRY-RUN:[/yellow] Would update {kind} {resource_name} with label {label_key}: {new_value}")
        return (True, existing_value)


def get_machines_for_machineset(
    machineset_name: str,
    crd_client: Optional[client.CustomObjectsApi] = None,
    namespace: str = "openshift-machine-api",
) -> List[Dict[str, Any]]:
    """Query Kubernetes for Machines associated with a specific MachineSet.

    Args:
        machineset_name: Name of the MachineSet to query
        crd_client: Optional CustomObjectsApi client. If not provided, creates a new one.
        namespace: Namespace where MachineSets reside (default: openshift-machine-api)

    Returns:
        List[Dict[str, Any]]: A list of Machine objects associated with the MachineSet.
    """
    if not crd_client:
        crd_client = client.CustomObjectsApi()

    try:
        # Get all Machines in the namespace
        machines = crd_client.list_namespaced_custom_object(
            group="machine.openshift.io",
            version="v1beta1",
            namespace=namespace,
            plural="machines",
        )

        matching_machines = []
        unlabeled_match_count = 0
        for machine in machines.get("items", []):
            if not _machine_owned_by_machineset(machine, machineset_name):
                continue
            matching_machines.append(machine)
            labels = machine.get("metadata", {}).get("labels", {}) or {}
            if _MACHINESET_LABEL_KEY not in labels:
                unlabeled_match_count += 1

        if unlabeled_match_count:
            logger.warning(
                "MachineSet %s: %d Machine(s) matched without label %s (used ownerReferences/name pattern)",
                machineset_name,
                unlabeled_match_count,
                _MACHINESET_LABEL_KEY,
            )

        logger.info(
            "Found %d Machine(s) for MachineSet %s",
            len(matching_machines),
            machineset_name,
        )
        return matching_machines

    except ApiException as e:
        logger.error(
            "Kubernetes API error retrieving Machines for MachineSet '%s': %s",
            machineset_name,
            e,
        )
        return []
    except Exception as e:
        logger.error(
            "Unexpected error retrieving Machines for MachineSet '%s': %s",
            machineset_name,
            e,
            exc_info=True,
        )
        return []


def get_all_machinesets(
    crd_client: Optional[client.CustomObjectsApi] = None,
    namespace: str = "openshift-machine-api",
) -> List[Dict[str, Any]]:
    """Get all MachineSets in the cluster.

    Args:
        crd_client: Optional CustomObjectsApi client. If not provided, creates a new one.
        namespace: Namespace where MachineSets reside (default: openshift-machine-api)

    Returns:
        List[Dict[str, Any]]: A list of all MachineSet objects in the cluster.

    Example:
        >>> machinesets = get_all_machinesets()
        >>> for ms in machinesets:
        ...     print(ms["metadata"]["name"])
    """
    if not crd_client:
        crd_client = client.CustomObjectsApi()

    try:
        # Get all MachineSets in the namespace
        machinesets = crd_client.list_namespaced_custom_object(
            group="machine.openshift.io",
            version="v1beta1",
            namespace=namespace,
            plural="machinesets",
        )

        ms_list: List[Dict[str, Any]] = cast(List[Dict[str, Any]], machinesets.get("items", []))
        logger.info("Found %d MachineSet(s) in namespace %s", len(ms_list), namespace)
        return ms_list

    except ApiException as e:
        logger.error(
            "Kubernetes API error retrieving MachineSets: %s",
            e,
        )
        return []
    except Exception as e:
        logger.error(
            "Unexpected error retrieving MachineSets: %s",
            e,
            exc_info=True,
        )
        return []


def get_nodes_for_machines(
    machines: List[Dict[str, Any]],
    v1_client: Optional[client.CoreV1Api] = None,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Get all Nodes associated with the given Machines.

    Args:
        machines: List of Machine resources (dictionaries)
        v1_client: Optional CoreV1Api client. If not provided, creates a new one.
        dry_run: If True, print summary to console instead of logging

    Returns:
        List[Dict[str, Any]]: List of Node resources (dictionaries)
    """
    if not v1_client:
        v1_client = get_k8s_client("CoreV1Api")

    try:
        nodes = v1_client.list_node()
        node_names = set()

        for machine in machines:
            node_ref = machine.get("status", {}).get("nodeRef", {})
            if node_ref and node_ref.get("name"):
                node_names.add(node_ref["name"])

        # Convert V1Node objects to dictionaries for consistency
        matching_nodes = []
        for node in nodes.items:
            if node.metadata.name in node_names:
                # Convert V1Node to dict for consistency with Machine objects
                node_dict = {
                    "metadata": {
                        "name": node.metadata.name,
                        "labels": dict(node.metadata.labels) if node.metadata.labels else {},
                    },
                    "spec": {},
                    "status": {},
                }
                matching_nodes.append(node_dict)

        if dry_run:
            console.print(f"Found {len(matching_nodes)} Node(s) for {len(machines)} Machine(s)")
        else:
            logger.info(
                "Found %d Node(s) for %d Machine(s)",
                len(matching_nodes),
                len(machines),
            )
        return matching_nodes

    except ApiException as e:
        logger.error("Kubernetes API error retrieving Nodes: %s", e)
        return []
    except Exception as e:
        logger.error("Error retrieving Nodes: %s", e, exc_info=True)
        return []


def get_existing_zone_label(
    machineset: Dict[str, Any],
    label_key: str = "topology.portworx.io/zone",
) -> Optional[str]:
    """Extract the existing zone label from a MachineSet.

    Args:
        machineset: The MachineSet resource dictionary
        label_key: The label key to extract (default: topology.portworx.io/zone)

    Returns:
        The existing label value, or None if not found
    """
    labels = cast(
        Dict[str, str],
        machineset.get("spec", {}).get("template", {}).get("spec", {}).get("metadata", {}).get("labels", {}),
    )
    return labels.get(label_key)


def get_nodes_from_machinesets_with_labels(
    label_key: str = "topology.portworx.io/zone",
    crd_client: Optional[client.CustomObjectsApi] = None,
    namespace: str = "openshift-machine-api",
) -> Dict[str, Dict[str, str]]:
    """Query Kubernetes for all nodes associated with MachineSets and their labels.

    This is a convenience wrapper around get_nodes_from_machinesets that specifically
    retrieves the zone label.

    Args:
        label_key: The label key to extract (default: topology.portworx.io/zone)
        crd_client: Optional CustomObjectsApi client. If not provided, creates a new one.
        namespace: Namespace where MachineSets reside (default: openshift-machine-api)

    Returns:
        Dict[str, Dict[str, str]]: A dictionary mapping node names to their labels and values.
    """
    return get_nodes_from_machinesets(label_key=label_key, crd_client=crd_client, namespace=namespace)


def get_nodes_from_machineset_specific_with_labels(
    machineset_name: str,
    label_key: str = "topology.portworx.io/zone",
    crd_client: Optional[client.CustomObjectsApi] = None,
    namespace: str = "openshift-machine-api",
) -> Dict[str, Dict[str, str]]:
    """Query Kubernetes for nodes associated with a specific MachineSet and their labels.

    This is a convenience wrapper around get_nodes_from_machineset_specific that specifically
    retrieves the zone label.

    Args:
        machineset_name: Name of the MachineSet to query
        label_key: The label key to extract (default: topology.portworx.io/zone)
        crd_client: Optional CustomObjectsApi client. If not provided, creates a new one.
        namespace: Namespace where MachineSets reside (default: openshift-machine-api)

    Returns:
        Dict[str, Dict[str, str]]: A dictionary mapping node names to their labels and values.
    """
    return get_nodes_from_machineset_specific(
        machineset_name=machineset_name,
        label_key=label_key,
        crd_client=crd_client,
        namespace=namespace,
    )
