"""Kubernetes utility functions."""

import logging
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
