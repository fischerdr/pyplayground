"""Kubernetes utility functions."""

import logging
import time
from typing import Optional, Dict, Any, List
from kubernetes import client, config
from kubernetes.client import ApiClient
from kubernetes.client.rest import ApiException

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

def exec_pod_command(
    namespace: str,
    pod_name: str,
    command: List[str],
    container: Optional[str] = None,
    stdout: bool = True,
    stderr: bool = True,
    stdin: bool = False,
    tty: bool = False
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
            _preload_content=False
        )
        
        output = resp.read_all().decode('utf-8')
        error = None
        
        if resp.returncode != 0:
            error = f"Command failed with exit code {resp.returncode}"
            logger.error(error)
        
        return {"stdout": output, "stderr": error}
        
    except ApiException as e:
        logger.error(f"Failed to execute command in pod: {e}")
        raise

def wait_for_pod_readiness(
    pod_name: str,
    namespace: str,
    timeout: int = 420,
    v1_client: Optional[client.CoreV1Api] = None
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

def get_machine_for_node(
    node_name: str,
    crd_client: Optional[client.CustomObjectsApi] = None
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
            group="machine.openshift.io",
            version="v1beta1",
            plural="machines"
        )

        for machine in machines['items']:
            if machine['status']['nodeRef']['name'] == node_name:
                logger.info(f"Found Machine {machine['metadata']['name']} for Node {node_name}")
                return machine
        logger.warning(f"No Machine found for Node {node_name}. This might be UPI.")
        return None
    except Exception as e:
        logger.error(f"Error fetching Machine for Node {node_name}: {e}")
        return None

def get_machineset_for_machine(
    machine: Dict[str, Any],
    crd_client: Optional[client.CustomObjectsApi] = None
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
            group="machine.openshift.io",
            version="v1beta1",
            plural="machinesets"
        )

        machine_name = machine['metadata']['name']
        for ms in machinesets['items']:
            if ms['metadata']['name'] in machine_name:
                logger.info(f"Found MachineSet {ms['metadata']['name']} for Machine {machine_name}")
                return ms
        logger.warning(f"No MachineSet found for Machine {machine_name}.")
        return None
    except Exception as e:
        logger.error(f"Error fetching MachineSet for Machine {machine['metadata'].get('name', 'unknown')}: {e}")
        return None

def get_nodes_from_machineset_specific(
    machineset_name: str,
    label_key: Optional[str] = None,
    crd_client: Optional[client.CustomObjectsApi] = None,
    namespace: str = "openshift-machine-api"
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
            plural="machinesets"
        )

        # Find the specific MachineSet object by name
        machineset = next((ms for ms in machinesets['items'] if ms['metadata']['name'] == machineset_name), None)

        if not machineset:
            logger.error(f"MachineSet {machineset_name} not found.")
            return {}

        node_info: Dict[str, Dict[str, str]] = {}

        # Extract labels from the MachineSet
        ms_labels = machineset.get('metadata', {}).get('labels', {})
        if label_key and label_key in ms_labels:
            logger.info(f"Found label {label_key}={ms_labels[label_key]} in MachineSet {machineset_name}")
        else:
            if label_key:
                logger.warning(f"Label {label_key} not found in MachineSet {machineset_name}")

        # Find associated machines for the MachineSet
        machines = crd_client.list_namespaced_custom_object(
            group="machine.openshift.io",
            version="v1beta1",
            namespace=namespace,
            plural="machines"
        )

        for machine in machines['items']:
            # Check if the machine is part of the specified MachineSet
            if machineset_name in machine['metadata']['name'] and 'status' in machine:
                node_name = machine['status'].get('nodeRef', {}).get('name', None)
                if node_name:
                    # Store all labels and their values
                    node_info[node_name] = ms_labels.copy()
                    logger.info(f"Associated node {node_name} with MachineSet {machineset_name}")

        if node_info:
            logger.info(f"Found {len(node_info)} node(s) associated with MachineSet {machineset_name}.")
        else:
            logger.warning(f"No nodes found in MachineSet {machineset_name}.")

        return node_info

    except Exception as e:
        logger.error(f"Error retrieving nodes from MachineSet {machineset_name}: {e}")
        return {}

def get_nodes_from_machinesets(
    label_key: Optional[str] = None,
    crd_client: Optional[client.CustomObjectsApi] = None,
    namespace: str = "openshift-machine-api"
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
            group="machine.openshift.io",
            version="v1beta1",
            plural="machinesets"
        )

        node_info: Dict[str, Dict[str, str]] = {}

        for ms in machinesets['items']:
            ms_name = ms['metadata']['name']
            logger.info(f"Processing MachineSet: {ms_name}")
            
            # Extract labels from the MachineSet
            ms_labels = ms.get('metadata', {}).get('labels', {})
            if label_key and label_key in ms_labels:
                logger.info(f"Found label {label_key}={ms_labels[label_key]} in MachineSet {ms_name}")
            else:
                if label_key:
                    logger.warning(f"Label {label_key} not found in MachineSet {ms_name}")

            # Find associated machines for the MachineSet
            machines = crd_client.list_cluster_custom_object(
                group="machine.openshift.io",
                version="v1beta1",
                plural="machines"
            )

            for machine in machines['items']:
                # Check if the machine is part of the current MachineSet
                if ms_name in machine['metadata']['name'] and 'status' in machine:
                    node_name = machine['status'].get('nodeRef', {}).get('name', None)
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
