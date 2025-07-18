#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script to check Vault secrets referenced by Portworx PVC annotations.

This script connects to a Kubernetes cluster, finds Portworx PVCs with specific
annotations (`px/vault-namespace`, `px/secret-name`), and verifies if the
corresponding secrets exist in HashiCorp Vault. It retrieves Vault connection
details from Kubernetes secrets associated with Portworx.

Example usage:
    python pyplayground/k8s/k8s_px_pvc_vault_secret_checker.py --kubeconfig ~/.kube/config
"""

import base64
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

import click
import hvac
from kubernetes import client, stream
from kubernetes.client.rest import ApiException
from rich.console import Console
from rich.table import Table

# Add project root to path for utils
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from pyplayground.utils.k8s_utils import get_k8s_client, load_kube_config_auto
from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.vault_utils import create_vault_client, login_with_kubernetes

# --- Constants ---
PORTWORX_PROVISIONER = "pxd.portworx.com"
VAULT_SECRET_NAME_ANNOTATION = "px/secret-name"
VAULT_NAMESPACE_ANNOTATION = "px/vault-namespace"
DEFAULT_PX_NAMESPACE = "kube-system"
PORTWORX_POD_LABEL_SELECTOR = "name=portworx,storage=true"
VAULT_ADDR_SECRET_NAME = "px-vault"
VAULT_ADDR_SECRET_KEY = "VAULT_ADDR"
VAULT_BACKEND_PATH_KEY = "VAULT_BACKEND_PATH"
VAULT_AUTH_ROLE_KEY = "VAULT_AUTH_KUBERNETES_ROLE"
VAULT_AUTH_MOUNT_PATH_KEY = "VAULT_AUTH_MOUNT_PATH"
VAULT_AUTH_NAMESPACE_KEY = "VAULT_NAMESPACE"  # For the auth call
VAULT_SA_NAME = "portworx"
# VAULT_TOKEN_SECRET_PREFIX is no longer needed with the improved SA secret search logic.

# --- Globals ---
console = Console()
logger = get_logger(__name__)


# --- Kubernetes Helper Functions ---


def get_portworx_storage_classes(storage_v1_client: client.StorageV1Api) -> List[str]:
    """Gets the names of StorageClasses provisioned by Portworx."""
    logger.debug("Fetching StorageClasses...")
    portworx_sc_names = []
    try:
        storage_classes = storage_v1_client.list_storage_class()
        for sc in storage_classes.items:
            if sc.provisioner == PORTWORX_PROVISIONER:
                portworx_sc_names.append(sc.metadata.name)
        logger.info(
            f"Found {len(portworx_sc_names)} Portworx StorageClasses: {', '.join(portworx_sc_names)}"
        )
        return portworx_sc_names
    except ApiException as e:
        logger.error(f"API error listing StorageClasses: {e.status} - {e.reason}", exc_info=True)
        return []


def get_annotated_portworx_pvcs(
    core_v1_client: client.CoreV1Api, portworx_sc_names: List[str]
) -> List[client.V1PersistentVolumeClaim]:
    """Fetches all PVCs using Portworx SCs and having Vault annotations."""
    logger.debug("Fetching all PVCs across all namespaces...")
    annotated_pvcs = []
    try:
        all_pvcs = core_v1_client.list_persistent_volume_claim_for_all_namespaces()
        for pvc in all_pvcs.items:
            sc_name = pvc.spec.storage_class_name
            if sc_name in portworx_sc_names:
                annotations = pvc.metadata.annotations
                if (
                    annotations
                    and VAULT_SECRET_NAME_ANNOTATION in annotations
                    and VAULT_NAMESPACE_ANNOTATION in annotations
                ):
                    annotated_pvcs.append(pvc)
        logger.info(f"Found {len(annotated_pvcs)} Portworx PVCs with Vault annotations.")
        return annotated_pvcs
    except ApiException as e:
        logger.error(f"API error listing PVCs: {e.status} - {e.reason}", exc_info=True)
        return []


def get_vault_connection_info(
    core_v1_client: client.CoreV1Api, namespace: str
) -> Optional[Dict[str, str]]:
    """Retrieves Vault connection and auth info from the 'px-vault' secret."""
    logger.debug(
        f"Attempting to read secret '{VAULT_ADDR_SECRET_NAME}' in namespace '{namespace}'."
    )
    try:
        secret = core_v1_client.read_namespaced_secret(VAULT_ADDR_SECRET_NAME, namespace)
        secret_data = secret.data

        required_keys = {
            "addr": VAULT_ADDR_SECRET_KEY,
            "backend_path": VAULT_BACKEND_PATH_KEY,
            "auth_role": VAULT_AUTH_ROLE_KEY,
            "auth_mount_path": VAULT_AUTH_MOUNT_PATH_KEY,
        }

        conn_info = {}
        for key, secret_key in required_keys.items():
            value_b64 = secret_data.get(secret_key)
            if not value_b64:
                logger.error(
                    f"Secret '{VAULT_ADDR_SECRET_NAME}' is missing the key '{secret_key}'."
                )
                return None
            conn_info[key] = base64.b64decode(value_b64).decode("utf-8").strip()

        logger.info("Successfully retrieved Vault connection and auth info.")
        return conn_info

    except ApiException as e:
        if e.status == 404:
            logger.error(f"Secret '{VAULT_ADDR_SECRET_NAME}' not found in namespace '{namespace}'.")
        else:
            logger.error(f"API error reading Vault connection secret: {e.reason}", exc_info=True)
        return None


def get_service_account_jwt(core_v1_client: client.CoreV1Api, namespace: str) -> Optional[str]:
    """Retrieves an existing K8s service account token (JWT) from a secret."""
    logger.info(
        f"Searching for an existing secret for SA '{VAULT_SA_NAME}' containing '{VAULT_SA_NAME}-token' in its name."
    )
    try:
        secrets = core_v1_client.list_namespaced_secret(namespace)
        for secret in secrets.items:
            secret_name = secret.metadata.name
            annotations = secret.metadata.annotations
            if (
                secret.type == "kubernetes.io/service-account-token"
                and annotations
                and annotations.get("kubernetes.io/service-account.name") == VAULT_SA_NAME
                and f"{VAULT_SA_NAME}-token" in secret_name
            ):
                if "token" in secret.data:
                    token_b64 = secret.data["token"]
                    token = base64.b64decode(token_b64).decode("utf-8").strip()
                    logger.info(
                        f"Found and decoded service account JWT from secret '{secret_name}'."
                    )
                    return token
                else:
                    logger.warning(
                        f"Secret '{secret_name}' is a SA token but missing 'token' data."
                    )

    except ApiException as e:
        logger.error(
            f"API error listing secrets in namespace '{namespace}': {e.reason}", exc_info=True
        )

    logger.error(f"Could not retrieve token for ServiceAccount '{VAULT_SA_NAME}'.")
    return None


def find_portworx_pod(v1_client: client.CoreV1Api, namespace: str) -> Optional[tuple[str, str]]:
    """Finds the first running Portworx pod based on labels in the specified namespace."""
    logger.info(
        f"Searching for Portworx pod with labels '{PORTWORX_POD_LABEL_SELECTOR}' in namespace '{namespace}'..."
    )
    try:
        pods = v1_client.list_namespaced_pod(
            namespace=namespace, label_selector=PORTWORX_POD_LABEL_SELECTOR
        )
        if not pods.items:
            logger.warning(
                f"No pods found with labels '{PORTWORX_POD_LABEL_SELECTOR}' in namespace '{namespace}'."
            )
            return None

        for pod in pods.items:
            pod_name = pod.metadata.name
            if pod.status.phase == "Running":
                if pod.spec.containers:
                    container_name = pod.spec.containers[0].name
                    logger.info(
                        f"Found running Portworx pod: '{pod_name}', container: '{container_name}'"
                    )
                    return pod_name, container_name
                else:
                    logger.warning(
                        f"Portworx pod '{pod_name}' found but has no containers defined."
                    )

        logger.warning(f"No *running* Portworx pods found in namespace '{namespace}'.")
        return None
    except ApiException as e:
        logger.error(
            f"API error finding Portworx pod in namespace '{namespace}': {e.status} - {e.reason}",
            exc_info=True,
        )
        return None
    except Exception as e:
        logger.exception(f"Unexpected error finding Portworx pod: {e}")
        return None


def get_pxctl_auth_env(core_v1: client.CoreV1Api, px_namespace: str) -> Optional[str]:
    """Return PXCTL_AUTH_TOKEN env var if Portworx security is enabled in StorageCluster."""
    logger = get_logger(__name__)
    try:
        co_api = get_k8s_client("CustomObjectsApi")
        stc = co_api.list_namespaced_custom_object(
            group="core.libopenstorage.org",
            version="v1",
            namespace=px_namespace,
            plural="storageclusters",
        )
        if stc["items"]:
            sec_enabled = stc["items"][0].get("spec", {}).get("security", {}).get("enabled", False)
            if sec_enabled:
                secret = core_v1.read_namespaced_secret("px-admin-token", px_namespace)
                token_b64 = secret.data.get("auth-token")
                if token_b64:
                    token = base64.b64decode(token_b64).decode("utf-8")
                    logger.info(
                        "Portworx security enabled; using PXCTL_AUTH_TOKEN from px-admin-token secret."
                    )
                    return f"PXCTL_AUTH_TOKEN={token}"
                else:
                    logger.warning("px-admin-token secret found but 'auth-token' key missing.")
            else:
                logger.info("Portworx security is not enabled in StorageCluster.")
        else:
            logger.warning(f"No StorageCluster found in namespace '{px_namespace}'.")
    except Exception:
        logger.warning("Could not determine PXCTL_AUTH_TOKEN.", exc_info=True)
    return None


def _prepare_execution_command(
    env_var_list: List[str], base_command: str
) -> tuple[str, Dict[str, str]]:
    """Parses environment variables and constructs the full command string."""
    env_vars = {}
    for var in env_var_list:
        if "=" not in var:
            error_msg = f"Invalid environment variable format: '{var}'. Use VAR=VALUE."
            logger.error(error_msg)
            raise ValueError(error_msg)
        key, value = var.split("=", 1)
        env_vars[key] = value

    if env_vars:
        env_exports = " && ".join([f'export {key}="{value}"' for key, value in env_vars.items()])
        full_command_str = f"{env_exports} && {base_command}"
    else:
        full_command_str = base_command

    logger.debug(f"Prepared full command (env vars included): {full_command_str}")
    return full_command_str, env_vars


def _run_command_in_pod(
    v1_client: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    container_name: str,
    command: List[str],
) -> tuple[int, str, str]:
    """Executes a command in a pod container and returns exit code, stdout, stderr."""
    stdout_data = ""
    stderr_data = ""
    exit_code = -1
    resp = None
    try:
        resp = stream.stream(
            v1_client.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=namespace,
            container=container_name,
            command=command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _preload_content=False,
        )

        while resp.is_open():
            resp.update(timeout=1)
            if resp.peek_stdout():
                stdout_data += resp.read_stdout()
            if resp.peek_stderr():
                stderr_data += resp.read_stderr()

    finally:
        if resp:
            resp.close()
            exit_code = resp.returncode if resp.returncode is not None else -1

    return exit_code, stdout_data, stderr_data


def _parse_pxctl_output(
    stdout_data: str, stderr_data: str, volume_name: str
) -> tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """Parses the JSON output from a successful pxctl command."""
    if not stdout_data:
        return None, None, stderr_data

    try:
        parsed_json = json.loads(stdout_data)
        if isinstance(parsed_json, list) and parsed_json:
            return parsed_json[0], None, None
        if isinstance(parsed_json, dict):
            return parsed_json, None, None

        logger.warning(
            f"pxctl output for '{volume_name}' was valid JSON but not a dict or non-empty list."
        )
        return None, stdout_data, stderr_data
    except json.JSONDecodeError:
        logger.error(f"Failed to parse pxctl JSON for volume '{volume_name}'.")
        return None, stdout_data, stderr_data


def execute_pxctl_inspect(
    v1_client: client.CoreV1Api,
    px_namespace: str,
    px_pod_name: str,
    px_container_name: str,
    volume_name: str,
    env_vars: List[str],
) -> tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """Executes 'pxctl volume inspect -j <volume_name>' in the Portworx pod."""
    base_command = f"pxctl volume inspect {volume_name} -j"
    try:
        full_command_str, _ = _prepare_execution_command(env_vars, base_command)
    except ValueError as e:
        return None, None, f"Invalid Environment Variable: {e}"

    command_to_run = ["/bin/sh", "-c", full_command_str]
    logger.debug(
        f"Executing in pod '{px_pod_name}/{px_container_name}': {' '.join(command_to_run)}"
    )

    try:
        exit_code, stdout_data, stderr_data = _run_command_in_pod(
            v1_client, px_namespace, px_pod_name, px_container_name, command_to_run
        )

        if exit_code == 0:
            return _parse_pxctl_output(stdout_data, stderr_data, volume_name)
        else:
            return None, stdout_data, stderr_data
    except ApiException as e:
        logger.error(f"API error for volume '{volume_name}': {e.reason}", exc_info=True)
        return None, None, f"Kubernetes API Error: {e.reason}"
    except Exception as e:
        logger.exception(f"Unexpected error for volume '{volume_name}': {e}")
        return None, None, f"Unexpected Error: {e}"


# --- Vault Helper Functions ---


def format_data_for_table(data: Optional[Dict[str, Any]], mask_values: bool = True) -> str:
    """Formats secret data for compact display in a Rich table."""
    if not data:
        return ""

    lines = []
    for key, value in data.items():
        display_value = "********" if mask_values and isinstance(value, str) else str(value)
        lines.append(f"{key}: {display_value}")
    return "\n".join(lines)


def format_labels_for_table(labels: Optional[Dict[str, str]]) -> str:
    """Formats volume labels for display in a Rich table, filtering for specific prefixes."""
    if not labels:
        return ""

    filtered_labels = {
        key: value
        for key, value in labels.items()
        if key.startswith("SECRET_") or key.startswith("px/")
    }

    if not filtered_labels:
        return "[dim]No relevant labels found[/dim]"

    return json.dumps(filtered_labels, indent=2)


def check_vault_secret(
    vault_addr: str,
    vault_token: str,
    secret_path: str,
    mount_point: str,
    vault_namespace: Optional[str] = None,
) -> tuple[str, Optional[Dict[str, Any]]]:
    """Checks for a secret in Vault and returns its status and data."""
    logger.debug(
        f"Checking Vault for secret at path '{secret_path}' in mount '{mount_point}' (namespace: {vault_namespace or 'root'})."
    )

    status = "Unknown"
    data = None
    try:
        # Create a temporary, namespaced client for each check for maximum compatibility.
        vault_client = create_vault_client(
            url=vault_addr, token=vault_token, namespace=vault_namespace
        )

        response = vault_client.secrets.kv.v2.read_secret_version(
            path=secret_path, mount_point=mount_point
        )

        if response and "data" in response and "data" in response["data"]:
            status = "[green]Found[/green]"
            data = response["data"]["data"]
        else:
            status = "[yellow]Found (No Data)[/yellow]"
    except hvac.exceptions.InvalidPath as e:
        logger.warning(
            f"Invalid Vault path for secret '{secret_path}' in mount '{mount_point}'. Reason: {e}",
            exc_info=True,
        )
        status = "[red]Not Found[/red]"
    except hvac.exceptions.Forbidden as e:
        logger.warning(
            f"Vault access forbidden for secret path '{secret_path}' in mount '{mount_point}'. Reason: {e}",
            exc_info=True,
        )
        status = "[red]Forbidden[/red]"
    except Exception as e:
        logger.error(f"Error reading Vault secret '{secret_path}': {e}", exc_info=True)
        status = f"[red]Error: {type(e).__name__}[/red]"

    return status, data


def _initialize_check_environment(core_v1_client, px_namespace):
    """Gets Vault/PX connection info and returns it, or None if setup fails."""
    vault_conn_info = get_vault_connection_info(core_v1_client, px_namespace)
    if not vault_conn_info:
        console.print("[bold red]Failed to retrieve Vault connection info.[/bold red]")
        return None, None, None, None

    sa_jwt = get_service_account_jwt(core_v1_client, px_namespace)
    if not sa_jwt:
        console.print("[bold red]Failed to retrieve Service Account JWT for Vault auth.[/bold red]")
        return None, None, None, None

    px_pod_info = find_portworx_pod(core_v1_client, px_namespace)
    if not px_pod_info:
        console.print(
            f"[bold red]Could not find a running Portworx pod in '{px_namespace}'.[/bold red]"
        )
        return None, None, None, None

    pxctl_auth_env = get_pxctl_auth_env(core_v1_client, px_namespace)
    effective_env_vars = [pxctl_auth_env] if pxctl_auth_env else []

    return vault_conn_info, sa_jwt, px_pod_info, effective_env_vars


def _process_single_pvc(
    pvc,
    core_v1,
    px_namespace,
    px_pod_info,
    effective_env_vars,
    vault_conn_info,
    sa_jwt,
    vault_tokens,
):
    """Processes a single PVC, performing Vault and pxctl checks."""
    px_pod_name, px_container_name = px_pod_info
    pvc_info = {
        "pvc_namespace": pvc.metadata.namespace,
        "pvc_name": pvc.metadata.name,
        "secret_path": pvc.metadata.annotations.get(VAULT_SECRET_NAME_ANNOTATION),
        "vault_namespace": pvc.metadata.annotations.get(VAULT_NAMESPACE_ANNOTATION, ""),
        "status": "[red]Unknown[/red]",
        "secret_data": None,
        "volume_labels": None,
    }

    # Vault Secret Check
    if not pvc_info["vault_namespace"]:
        pvc_info["status"] = "[red]No Vault Namespace Annotation[/red]"
    else:
        vault_token = get_vault_token_for_namespace(
            pvc_info["vault_namespace"], vault_tokens, vault_conn_info, sa_jwt
        )
        if vault_token:
            pvc_info["status"], pvc_info["secret_data"] = check_vault_secret(
                vault_conn_info["addr"],
                vault_token,
                pvc_info["secret_path"],
                mount_point=vault_conn_info["backend_path"],
                vault_namespace=pvc_info["vault_namespace"],
            )
        else:
            pvc_info["status"] = "[red]Auth Failed[/red]"

    # Get Volume Labels from pxctl
    pv_name = pvc.spec.volume_name
    if pv_name:
        pxctl_json, _, _ = execute_pxctl_inspect(
            core_v1, px_namespace, px_pod_name, px_container_name, pv_name, effective_env_vars
        )
        if pxctl_json:
            pvc_info["volume_labels"] = pxctl_json.get("spec", {}).get("volume_labels")

    return pvc_info


def get_vault_token_for_namespace(
    vault_namespace: str,
    vault_tokens_cache: Dict[str, Optional[str]],
    vault_conn_info: Dict[str, str],
    sa_jwt: str,
) -> Optional[str]:
    """Retrieves a Vault token for a given namespace, using a cache."""
    if vault_namespace in vault_tokens_cache:
        return vault_tokens_cache[vault_namespace]

    try:
        logger.info(f"Authenticating to Vault for namespace: '{vault_namespace}'")
        vault_client = login_with_kubernetes(
            role=vault_conn_info["auth_role"],
            jwt=sa_jwt,
            url=vault_conn_info["addr"],
            mount_point=vault_conn_info["auth_mount_path"],
            namespace=vault_namespace,
        )
        token = vault_client.token
        if not token:
            raise ValueError("Authentication successful but client token is empty.")
        logger.info(f"Successfully authenticated for Vault namespace '{vault_namespace}'.")
        vault_tokens_cache[vault_namespace] = token
        return token
    except hvac.exceptions.VaultError as e:
        logger.error(
            f"Vault API error during authentication for namespace '{vault_namespace}': {e}",
            exc_info=True,
        )
        vault_tokens_cache[vault_namespace] = None
        return None
    except Exception as e:
        logger.error(
            f"Failed to authenticate with Vault for namespace '{vault_namespace}': {e}",
            exc_info=True,
        )
        vault_tokens_cache[vault_namespace] = None  # Cache failure
        return None


def process_pvc_vault_checks(core_v1, storage_v1, px_namespace):
    """Gathers PVCs, checks vault secrets, fetches labels, and returns results."""
    # 1. Initialize environment: Vault, K8s, and Portworx info
    (
        vault_conn_info,
        sa_jwt,
        px_pod_info,
        effective_env_vars,
    ) = _initialize_check_environment(core_v1, px_namespace)
    if not vault_conn_info:
        sys.exit(1)  # Errors are printed inside the helper

    # 2. Get Portworx PVCs with Vault annotations
    px_scs = get_portworx_storage_classes(storage_v1)
    if not px_scs:
        console.print(
            "[yellow]No Portworx StorageClasses found. Cannot identify any Portworx PVCs.[/yellow]"
        )
        return []

    annotated_pvcs = get_annotated_portworx_pvcs(core_v1, px_scs)
    if not annotated_pvcs:
        console.print("[yellow]No Portworx PVCs with required Vault annotations found.[/yellow]")
        return []

    # 3. Process each PVC
    results = []
    vault_tokens: Dict[str, Optional[str]] = {}
    for pvc in annotated_pvcs:
        pvc_result = _process_single_pvc(
            pvc,
            core_v1,
            px_namespace,
            px_pod_info,
            effective_env_vars,
            vault_conn_info,
            sa_jwt,
            vault_tokens,
        )
        results.append(pvc_result)

    return results


def display_results(results: List[Dict[str, Any]], mask_values: bool):
    """Displays the results in a Rich table."""
    if not results:
        return

    table = Table(title="Portworx PVC Vault Secret Check Results")
    table.add_column("PVC Namespace", style="cyan")
    table.add_column("PVC Name", style="magenta")
    table.add_column("Vault Path", style="green")
    table.add_column("Vault Namespace", style="blue")
    table.add_column("Status", style="bold")
    table.add_column("Secret Data", style="yellow")
    table.add_column("Volume Labels", style="white")

    for item in results:
        secret_data_str = ""
        if item["secret_data"]:
            if mask_values:
                secret_data_str = ", ".join(item["secret_data"].keys()) + " (values masked)"
            else:
                secret_data_str = json.dumps(item["secret_data"], indent=2)

        table.add_row(
            item["pvc_namespace"],
            item["pvc_name"],
            item["secret_path"],
            item["vault_namespace"] or "[dim]N/A[/dim]",
            item["status"],
            secret_data_str,
            format_labels_for_table(item["volume_labels"]),
        )
    console.print(table)


# --- Main Command ---


@click.command()
@click.option(
    "--kubeconfig",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the kubeconfig file. If not provided, uses default lookup.",
    envvar="KUBECONFIG",
)
@click.option(
    "--px-namespace",
    default=DEFAULT_PX_NAMESPACE,
    show_default=True,
    help="Namespace for Portworx and where to look for Vault credential secrets.",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
@click.option(
    "--mask/--no-mask",
    "mask_values",
    default=True,
    help="Mask/unmask sensitive values in the output.",
    show_default=True,
)
def main(kubeconfig: Optional[str], px_namespace: str, debug: bool, mask_values: bool):
    """Checks Vault secrets referenced by Portworx PVCs."""
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=os.path.basename(__file__).replace(".py", ""))

    logger.info("Script started.")

    if not load_kube_config_auto(config_file=kubeconfig):
        console.print("[bold red]Error: Failed to load Kubernetes configuration.[/bold red]")
        sys.exit(1)

    try:
        core_v1 = get_k8s_client("CoreV1Api")
        storage_v1 = get_k8s_client("StorageV1Api")
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes API clients: {e}", exc_info=True)
        console.print(f"[bold red]Error initializing Kubernetes clients: {e}[/bold red]")
        sys.exit(1)

    results = process_pvc_vault_checks(core_v1, storage_v1, px_namespace)
    display_results(results, mask_values)

    logger.info("Script finished.")


if __name__ == "__main__":
    main()
