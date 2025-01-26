"""Kubernetes utility functions."""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml
from hvac.exceptions import VaultError
from kubernetes import client, config, stream
from kubernetes.client import ApiClient
from kubernetes.client.rest import ApiException

from utils.vault_utils import create_vault_client, get_secret

logger = logging.getLogger(__name__)


def load_kube_config(config_file: Optional[str] = None, context: Optional[str] = None) -> None:
    """
    Load Kubernetes configuration from a kubeconfig file.

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
    """
    Safely load kubeconfig from a YAML string.

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


def get_k8s_client(api_version: str = "CoreV1Api") -> Any:
    """
    Get a Kubernetes API client.

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


def get_custom_objects_api() -> client.CustomObjectsApi:
    """
    Get a Kubernetes CustomObjectsApi client.

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


def exec_pod_command(
    namespace: str,
    pod_name: str,
    command: List[str],
    container: Optional[str] = None,
    stdout: bool = True,
    stderr: bool = True,
    stdin: bool = False,
    tty: bool = False,
) -> Dict[str, str]:
    """
    Execute a command in a pod.

    Args:
        namespace: Pod namespace
        pod_name: Pod name
        command: Command to execute
        container: Optional container name
        stdout: Capture stdout
        stderr: Capture stderr
        stdin: Enable stdin
        tty: Enable TTY

    Returns:
        Dict containing stdout and stderr
    """
    try:
        core_v1 = client.CoreV1Api()
        resp = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)

        if not container and len(resp.spec.containers) > 1:
            container = resp.spec.containers[0].name
            logger.warning(f"Multiple containers found, using: {container}")

        exec_command = [str(cmd) for cmd in command]
        resp = stream(
            core_v1.connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            command=exec_command,
            container=container,
            stdout=stdout,
            stderr=stderr,
            stdin=stdin,
            tty=tty,
            _preload_content=False,
        )

        output = resp.read_all().decode("utf-8")
        error = None

        if resp.returncode != 0:
            error = f"Command failed with exit code {resp.returncode}"
            logger.error(error)

        return {"stdout": output, "stderr": error}

    except ApiException as e:
        logger.error(f"Failed to execute command in pod: {e}")
        raise


def wait_for_pod_readiness(
    pod_name: str, namespace: str, timeout: int = 420, v1_client: Optional[client.CoreV1Api] = None
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
        logger.debug(
            f"Waiting for pod {pod_name} to be ready... ({elapsed_time}/{timeout} seconds elapsed)"
        )
        time.sleep(interval)

    logger.warning(f"Timeout reached: Pod {pod_name} is not ready after {timeout} seconds.")
    return False


def get_machine_for_node(
    node_name: str, crd_client: Optional[client.CustomObjectsApi] = None
) -> Optional[Dict[str, Any]]:
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
        machines = crd_client.list_cluster_custom_object(
            group="machine.openshift.io", version="v1beta1", plural="machines"
        )

        for machine in machines["items"]:
            if machine["status"]["nodeRef"]["name"] == node_name:
                logger.info(f"Found Machine {machine['metadata']['name']} for Node {node_name}")
                return machine
        logger.warning(f"No Machine found for Node {node_name}. This might be UPI.")
        return None
    except Exception as e:
        logger.error(f"Error fetching Machine for Node {node_name}: {e}")
        return None


def get_machineset_for_machine(
    machine: Dict[str, Any], crd_client: Optional[client.CustomObjectsApi] = None
) -> Optional[Dict[str, Any]]:
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
        machinesets = crd_client.list_cluster_custom_object(
            group="machine.openshift.io", version="v1beta1", plural="machinesets"
        )

        machine_name = machine["metadata"]["name"]
        for ms in machinesets["items"]:
            if ms["metadata"]["name"] in machine_name:
                logger.info(f"Found MachineSet {ms['metadata']['name']} for Machine {machine_name}")
                return ms
        logger.warning(f"No MachineSet found for Machine {machine_name}.")
        return None
    except Exception as e:
        logger.error(
            f"Error fetching MachineSet for Machine {machine['metadata'].get('name', 'unknown')}: {e}"
        )
        return None


def get_nodes_from_machineset_specific(
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
            (ms for ms in machinesets["items"] if ms["metadata"]["name"] == machineset_name), None
        )

        if not machineset:
            logger.error(f"MachineSet {machineset_name} not found.")
            return {}

        node_info: Dict[str, Dict[str, str]] = {}

        # Extract labels from the MachineSet
        ms_labels = machineset.get("metadata", {}).get("labels", {})
        if label_key and label_key in ms_labels:
            logger.info(
                f"Found label {label_key}={ms_labels[label_key]} in MachineSet {machineset_name}"
            )
        else:
            if label_key:
                logger.warning(f"Label {label_key} not found in MachineSet {machineset_name}")

        # Find associated machines for the MachineSet
        machines = crd_client.list_namespaced_custom_object(
            group="machine.openshift.io", version="v1beta1", namespace=namespace, plural="machines"
        )

        for machine in machines["items"]:
            # Check if the machine is part of the specified MachineSet
            if machineset_name in machine["metadata"]["name"] and "status" in machine:
                node_name = machine["status"].get("nodeRef", {}).get("name", None)
                if node_name:
                    # Store all labels and their values
                    node_info[node_name] = ms_labels.copy()
                    logger.info(f"Associated node {node_name} with MachineSet {machineset_name}")

        if node_info:
            logger.info(
                f"Found {len(node_info)} node(s) associated with MachineSet {machineset_name}."
            )
        else:
            logger.warning(f"No nodes found in MachineSet {machineset_name}.")

        return node_info

    except Exception as e:
        logger.error(f"Error retrieving nodes from MachineSet {machineset_name}: {e}")
        return {}


def get_nodes_from_machinesets(
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
        machinesets = crd_client.list_cluster_custom_object(
            group="machine.openshift.io", version="v1beta1", plural="machinesets"
        )

        node_info: Dict[str, Dict[str, str]] = {}

        for ms in machinesets["items"]:
            ms_name = ms["metadata"]["name"]
            logger.info(f"Processing MachineSet: {ms_name}")

            # Extract labels from the MachineSet
            ms_labels = ms.get("metadata", {}).get("labels", {})
            if label_key and label_key in ms_labels:
                logger.info(
                    f"Found label {label_key}={ms_labels[label_key]} in MachineSet {ms_name}"
                )
            else:
                if label_key:
                    logger.warning(f"Label {label_key} not found in MachineSet {ms_name}")

            # Find associated machines for the MachineSet
            machines = crd_client.list_cluster_custom_object(
                group="machine.openshift.io", version="v1beta1", plural="machines"
            )

            for machine in machines["items"]:
                # Check if the machine is part of the current MachineSet
                if ms_name in machine["metadata"]["name"] and "status" in machine:
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
    """
    Get data from a Kubernetes ConfigMap.

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
            if key not in configmap.data:
                raise KeyError(f"Key '{key}' not found in ConfigMap")
            return configmap.data[key]

        return configmap.data
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to get ConfigMap data: {str(e)}")
        raise


def update_configmap_data(
    namespace: str,
    configmap_name: str,
    data: Dict[str, str],
    v1_client: Optional[client.CoreV1Api] = None,
) -> None:
    """
    Update data in a Kubernetes ConfigMap.

    Args:
        namespace: Kubernetes namespace
        configmap_name: Name of the ConfigMap
        data: Dictionary of data to update in the ConfigMap
        v1_client: Optional CoreV1Api client. If not provided, creates a new one.
    """
    try:
        if not v1_client:
            v1_client = get_k8s_client("CoreV1Api")

        # Get the current ConfigMap
        configmap = v1_client.read_namespaced_config_map(configmap_name, namespace)

        # Update the data
        configmap.data.update(data)

        # Update the ConfigMap in Kubernetes
        v1_client.replace_namespaced_config_map(configmap_name, namespace, configmap)
        logger.info(f"Successfully updated ConfigMap {configmap_name} in namespace {namespace}")
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to update ConfigMap data: {str(e)}")
        raise


def get_cloud_drive_config(
    namespace: str, configmap_name: str, v1_client: Optional[client.CoreV1Api] = None
) -> Dict[str, Any]:
    """
    Get cloud-drive configuration from Kubernetes ConfigMap.

    Args:
        namespace: Kubernetes namespace
        configmap_name: Name of the ConfigMap
        v1_client: Optional CoreV1Api client. If not provided, creates a new one.

    Returns:
        Dictionary containing the cloud-drive configuration
    """
    try:
        data = get_configmap_data(namespace, configmap_name, "cloud-drive", v1_client)
        return json.loads(data)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse cloud-drive JSON: {str(e)}")
        raise


def update_cloud_drive_config(
    namespace: str,
    configmap_name: str,
    new_config: Dict[str, Any],
    v1_client: Optional[client.CoreV1Api] = None,
) -> None:
    """
    Update cloud-drive configuration in Kubernetes ConfigMap.

    Args:
        namespace: Kubernetes namespace
        configmap_name: Name of the ConfigMap
        new_config: New configuration to apply
        v1_client: Optional CoreV1Api client. If not provided, creates a new one.
    """
    try:
        data = {"cloud-drive": json.dumps(new_config)}
        update_configmap_data(namespace, configmap_name, data, v1_client)
    except Exception as e:
        logger.error(f"Failed to update cloud-drive config: {str(e)}")
        raise


def normalize_vault_path(path: str) -> tuple[str, str]:
    """Normalize vault path by removing mount prefix and returning mount point.

    Args:
        path: Raw vault path that may include mount prefix

    Returns:
        tuple[str, str]: A tuple containing:
            - mount_point: The vault mount point (e.g. 'static_secrets')
            - normalized_path: The path without mount prefix and leading/trailing slashes
    """
    # Remove leading and trailing slashes
    path = path.strip("/")

    # Split on first slash to separate mount point and path
    parts = path.split("/", 1)
    if len(parts) == 2:
        mount_point, path = parts
    else:
        mount_point = "secret"

    return mount_point, path


def get_kubeconfig_from_vault(
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
        vault_config = inventory_data["kubernetes_platform"]["secrets_management"][
            "platform_vault"
        ][0]
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
        url=vault_url if vault_url else None, token=vault_token, namespace=vault_namespace
    )
    try:
        secret = get_secret(vault_client, vault_path, mount_point=vault_mount)
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
