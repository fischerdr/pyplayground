#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared PX-Backup API Client and Authentication Utilities.

This module provides a common API client for PX-Backup modules and utilities
for generating authentication tokens.

"""

import base64
import json  # Import json for logging
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from kubernetes import client

from pyplayground.utils.k8s_utils import (
    exec_pod_command,
    find_running_pod_by_label,
    get_configmap_data,
    get_k8s_client,
    get_secret_data,
    get_service_account_jwt,
)

logger = logging.getLogger(__name__)

# --- Constants for PVC operations ---
VAULT_ADDR_SECRET_NAME = "px-vault"
PORTWORX_POD_LABEL_SELECTOR = "name=portworx,storage=true"
VAULT_SA_NAME = "portworx"
VAULT_SECRET_NAME_ANNOTATION = "px/secret-name"
VAULT_NAMESPACE_ANNOTATION = "px/vault-namespace"
DEFAULT_PX_NAMESPACE = "kube-system"


class PXBackupClient:
    """Common API client for PX-Backup modules."""

    def __init__(self, api_url: str, token: str, validate_certs: bool = True):
        """Initialize the PXBackupClient.

        Args:
            api_url: The base URL for the PX-Backup API.
            token: The authentication token.
            validate_certs: Whether to validate SSL certificates. Defaults to True.
        """
        # Add protocol if not present
        if not api_url.startswith(("http://", "https://")):
            # Defaulting to https based on playbook usage
            api_url = f"https://{api_url}"
            logger.info(f"Protocol not specified, assuming HTTPS: {api_url}")
        self.api_url = api_url.rstrip("/")
        # Prepare headers but log masked version
        self.raw_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
        masked_headers = self.raw_headers.copy()
        if token:
            masked_headers["Authorization"] = "Bearer ****"  # Mask token for logging
        self.headers_for_logging = masked_headers
        self.validate_certs = validate_certs
        logger.debug(f"API Client initialized for {self.api_url}")
        logger.debug(f"Client Headers (Token Masked): {self.headers_for_logging}")
        logger.debug(f"Certificate Validation Enabled: {self.validate_certs}")

    def _log_request_details(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]],
        data: Optional[Dict[str, Any]],
    ):
        """Logs the details of the outgoing request at DEBUG level."""
        log_data_presence = data is not None
        logger.debug(f"Making {method} request to URL: {url}")
        logger.debug(f"Params: {params}")
        logger.debug(f"Headers: {self.headers_for_logging}")  # Log masked headers
        if log_data_presence:
            try:
                data_str = json.dumps(data, indent=2)
                logger.debug(f"Request Body (Potential Sensitive Data):\n{data_str}")
            except TypeError as e:
                logger.debug(f"Could not serialize request body for logging: {e}. Data: {data}")
        else:
            logger.debug("Request Body: None")

    def _perform_request(
        self,
        method: str,
        url: str,
        data: Optional[Dict[str, Any]],
        params: Optional[Dict[str, Any]],
    ) -> requests.Response:
        """Executes the HTTP request and returns the raw response."""
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.raw_headers,  # Use actual headers here
                json=data,
                params=params,
                verify=self.validate_certs,
            )
            return response
        except requests.exceptions.RequestException as req_err:
            # Log and re-raise connection/timeout errors immediately
            logger.error(
                f"Request failed during connection/send: {req_err}",
                exc_info=logger.isEnabledFor(logging.DEBUG),
            )
            raise

    def _log_response_details(self, response: requests.Response):
        """Logs the status code and raw body of the response at DEBUG level."""
        logger.debug(f"Response Status Code: {response.status_code}")
        try:
            response_json = response.json()
            logger.debug(f"Raw Response Body (JSON):\n{json.dumps(response_json, indent=2)}")
        except json.JSONDecodeError:
            logger.debug(f"Raw Response Body (Non-JSON):\n{response.text}")

    def _handle_http_error(self, http_err: requests.exceptions.HTTPError) -> requests.exceptions.RequestException:
        """Formats and logs HTTPError, returning a RequestException."""
        error_msg = f"HTTP error occurred: {http_err}"
        try:
            error_detail = http_err.response.json()
            error_msg = f"{error_msg} - Detail: {error_detail}"
        except ValueError:
            error_msg = f"{error_msg} - Body: {http_err.response.text[:200]}..."  # Truncate
        logger.error(error_msg)  # Log formatted error
        # Return a new RequestException wrapping the original
        return requests.exceptions.RequestException(error_msg, response=http_err.response)

    def make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make HTTP request to PX-Backup API."""
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        self._log_request_details(method, url, params, data)

        try:
            response = self._perform_request(method, url, data, params)
            self._log_response_details(response)
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

            # Attempt to return JSON from successful response
            try:
                return response.json()
            except json.JSONDecodeError as json_err:
                logger.error(f"Successful status code ({response.status_code}) but failed to decode JSON response from {url}: {json_err}")
                raise ValueError(f"Invalid JSON received from API despite success status: {response.text}") from json_err

        except requests.exceptions.HTTPError as http_err:
            # Handle formatted HTTP error from helper
            raise self._handle_http_error(http_err) from http_err
        except requests.exceptions.RequestException as req_err:
            # Catch connection/timeout errors raised from _perform_request
            # Already logged in _perform_request, just re-raise
            raise req_err
        except Exception as e:
            # Catch any other unexpected errors during processing
            logger.exception(f"Unexpected error processing request for {url}: {e}")
            raise


def _request_token_data(url: str, headers: Dict[str, str], data: Dict[str, str], validate_certs: bool) -> Dict[str, Any]:
    """Helper function to make the token request and handle immediate errors."""
    try:
        response = requests.post(url, headers=headers, data=data, verify=validate_certs)
        logger.debug(f"Token Response Status Code: {response.status_code}")
        try:
            response_json = response.json()
            logger.debug(f"Raw Token Response Body (JSON):\n{json.dumps(response_json, indent=2)}")
        except json.JSONDecodeError:
            logger.debug(f"Raw Token Response Body (Non-JSON):\n{response.text}")

        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        return response.json()  # Return parsed JSON
    except requests.exceptions.HTTPError as http_err:
        error_msg = f"Token request HTTP error: {http_err}"
        try:
            error_detail = http_err.response.json()
            error_msg = f"{error_msg} - Detail: {error_detail}"
        except ValueError:
            error_msg = f"{error_msg} - Body: {http_err.response.text[:200]}..."
        logger.error(error_msg)
        # Re-raise as RequestException for consistent handling by caller
        raise requests.exceptions.RequestException(error_msg, response=http_err.response) from http_err
    except requests.exceptions.RequestException as req_err:
        # Log connection/timeout errors
        logger.error(f"Token request failed: {req_err}", exc_info=logger.isEnabledFor(logging.DEBUG))
        raise  # Re-raise original RequestException
    except json.JSONDecodeError as json_err:  # Catch error if successful status but invalid JSON
        logger.error(f"Failed to decode JSON response from token endpoint {url}: {json_err}", exc_info=True)
        # Raise ValueError as the structure is unexpected
        raise ValueError(f"Invalid JSON received from token endpoint: {response.text}") from json_err


def generate_token(auth_url: str, client_id: str, username: str, password: str, validate_certs: bool) -> str:
    """Requests a bearer token from the authentication endpoint."""
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    if not auth_url.startswith(("http://", "https://")):
        auth_url = f"https://{auth_url}"
        logger.info(f"Auth URL protocol not specified, assuming HTTPS: {auth_url}")

    url = f"{auth_url.rstrip('/')}/auth/realms/master/protocol/openid-connect/token"
    data = {
        "grant_type": "password",
        "client_id": client_id,
        "username": username,
        "password": password,
    }
    # Log request details at debug level, masking password
    masked_data = data.copy()
    masked_data["password"] = "****"
    logger.debug(f"Requesting token from URL: {url}")
    logger.debug(f"Request Data (Password Masked): {masked_data}")
    logger.debug(f"Headers: {headers}")
    logger.debug(f"Certificate Validation Enabled: {validate_certs}")

    try:
        # Call helper to get response data
        token_response = _request_token_data(url, headers, data, validate_certs)

        # Process the successful response
        access_token = token_response.get("access_token")
        if not access_token:
            # This error condition remains here as it's about the *content* of the valid response
            logger.error("Access token key not found in authentication response JSON.")
            raise ValueError("Access token not found in authentication response.")

        logger.info("Successfully obtained access token.")
        return access_token

    except (requests.exceptions.RequestException, ValueError) as e:
        # Catch errors raised from _request_token_data or the access_token check
        logger.error(f"Failed to obtain token: {e}", exc_info=logger.isEnabledFor(logging.DEBUG))
        # Re-raise wrapped or original exception depending on needs, here re-raising
        raise e
    except Exception as e:  # Catch any other unexpected errors
        logger.exception(f"Unexpected error during token generation: {e}")
        raise


def get_cloud_drive_config(namespace: str, configmap_name: str, v1_client: Optional[client.CoreV1Api] = None) -> Dict[str, Any]:
    """Get cloud-drive configuration from Kubernetes ConfigMap.

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


def get_pxctl_auth_env(px_namespace: str, v1_client: Optional[client.CoreV1Api] = None) -> Optional[str]:
    """Return PXCTL_AUTH_TOKEN env var if Portworx security is enabled in StorageCluster."""
    if not v1_client:
        v1_client = client.CoreV1Api()
    try:
        co_api = client.CustomObjectsApi()
        stc_list = co_api.list_namespaced_custom_object(
            group="core.libopenstorage.org",
            version="v1",
            namespace=px_namespace,
            plural="storageclusters",
        )
        if stc_list and stc_list.get("items"):
            stc = stc_list["items"][0]
            sec_enabled = stc.get("spec", {}).get("security", {}).get("enabled", False)
            if sec_enabled:
                secret = v1_client.read_namespaced_secret("px-admin-token", px_namespace)
                token_b64 = secret.data.get("auth-token")
                if token_b64:
                    token = base64.b64decode(token_b64).decode("utf-8")
                    logger.info("Portworx security enabled; using PXCTL_AUTH_TOKEN from px-admin-token secret.")
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


def _parse_pxctl_output(stdout_data: str, stderr_data: str, volume_name: str) -> tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """Parses the JSON output from a successful pxctl command."""
    if not stdout_data:
        return None, None, stderr_data

    try:
        parsed_json = json.loads(stdout_data)
        if isinstance(parsed_json, list) and parsed_json:
            return parsed_json[0], None, None
        if isinstance(parsed_json, dict):
            return parsed_json, None, None

        logger.warning(f"pxctl output for '{volume_name}' was valid JSON but not a dict or non-empty list.")
        return None, stdout_data, stderr_data
    except json.JSONDecodeError:
        logger.error(f"Failed to parse pxctl JSON for volume '{volume_name}'.")
        return None, stdout_data, stderr_data


def execute_pxctl_command(
    px_namespace: str,
    px_pod_name: str,
    px_container_name: str,
    command: str,
    env_vars: Optional[List[str]] = None,
    v1_client: Optional[client.CoreV1Api] = None,
    expect_json: bool = True,
) -> tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """Executes a pxctl command in the Portworx pod and returns parsed JSON.

    Args:
        px_namespace: Namespace of the Portworx pod.
        px_pod_name: Name of the Portworx pod.
        px_container_name: Name of the container inside the pod.
        command: The base pxctl command to run (e.g., "volume inspect my-volume -j").
        env_vars: A list of environment variables to set (e.g., ["VAR=VALUE"]).
        v1_client: Optional CoreV1Api client.
        expect_json: If True, attempts to parse stdout as JSON.

    Returns:
        A tuple containing:
        - Parsed JSON output from pxctl if successful and expect_json is True.
        - Raw stdout if parsing fails or is not expected.
        - Raw stderr if the command fails.
    """
    if not v1_client:
        v1_client = get_k8s_client("CoreV1Api")
    if env_vars is None:
        env_vars = []

    # Prepare command with environment variables
    env_exports = " && ".join([f'export {key}="{value}"' for var in env_vars for key, value in [var.split("=", 1)]])
    full_command_str = f"{env_exports} && {command}" if env_vars else command
    command_to_run = ["/bin/sh", "-c", full_command_str]

    logger.debug(f"Executing in pod '{px_pod_name}/{px_container_name}': {' '.join(command_to_run)}")

    try:
        exit_code, stdout_data, stderr_data = exec_pod_command(
            namespace=px_namespace,
            pod_name=px_pod_name,
            container=px_container_name,
            command=command_to_run,
            v1_client=v1_client,
        )

        # Always log the raw output at debug level for traceability
        if stdout_data:
            logger.debug(f"pxctl stdout for '{command}':\n{stdout_data}")
        if stderr_data:
            logger.debug(f"pxctl stderr for '{command}':\n{stderr_data}")

        volume_name_match = re.search(r"volume inspect (\S+)", command)
        volume_name = volume_name_match.group(1) if volume_name_match else "unknown_volume"

        if exit_code == 0:
            if expect_json:
                return _parse_pxctl_output(stdout_data, stderr_data, volume_name)
            else:
                # Command succeeded, but no JSON expected; return raw stdout
                return None, stdout_data, stderr_data
        else:
            return None, stdout_data, stderr_data
    except Exception as e:
        logger.exception(f"Unexpected error executing pxctl command: {e}")
        return None, None, f"Unexpected Error: {e}"


def get_portworx_storage_classes(
    storage_v1_client: Optional[client.StorageV1Api] = None,
) -> List[str]:
    """Gets the names of StorageClasses provisioned by Portworx.

    Args:
        storage_v1_client: Optional StorageV1Api client.

    Returns:
        A list of Portworx StorageClass names.
    """
    if not storage_v1_client:
        storage_v1_client = client.StorageV1Api()

    logger.debug("Fetching StorageClasses...")
    portworx_sc_names = []
    try:
        storage_classes = storage_v1_client.list_storage_class()
        for sc in storage_classes.items:
            if sc.provisioner == "pxd.portworx.com":
                portworx_sc_names.append(sc.metadata.name)
        logger.info(f"Found {len(portworx_sc_names)} Portworx StorageClasses: {', '.join(portworx_sc_names)}")
        return portworx_sc_names
    except Exception as e:
        logger.error(f"API error listing StorageClasses: {e}", exc_info=True)
        return []


def get_annotated_portworx_pvcs(
    core_v1_client: Optional[client.CoreV1Api] = None,
    storage_v1_client: Optional[client.StorageV1Api] = None,
) -> List[client.V1PersistentVolumeClaim]:
    """Fetches all PVCs using Portworx SCs and having Vault annotations.

    Args:
        core_v1_client: Optional CoreV1Api client.
        storage_v1_client: Optional StorageV1Api client.

    Returns:
        A list of V1PersistentVolumeClaim objects with Vault annotations.
    """
    if not core_v1_client:
        core_v1_client = client.CoreV1Api()
    if not storage_v1_client:
        storage_v1_client = client.StorageV1Api()

    portworx_sc_names = get_portworx_storage_classes(storage_v1_client)
    if not portworx_sc_names:
        logger.warning("No Portworx storage classes found, so no PVCs can be matched.")
        return []

    logger.debug("Fetching all PVCs across all namespaces...")
    annotated_pvcs = []
    try:
        all_pvcs = core_v1_client.list_persistent_volume_claim_for_all_namespaces()
        for pvc in all_pvcs.items:
            sc_name = pvc.spec.storage_class_name
            if sc_name in portworx_sc_names:
                annotations = pvc.metadata.annotations
                if annotations and "px/secret-name" in annotations and "px/vault-namespace" in annotations:
                    annotated_pvcs.append(pvc)
        logger.info(f"Found {len(annotated_pvcs)} Portworx PVCs with Vault annotations.")
        return annotated_pvcs
    except Exception as e:
        logger.error(f"API error listing PVCs: {e}", exc_info=True)
        return []


def filter_volume_labels(labels: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Filters volume labels for keys starting with Portworx-specific prefixes.

    Args:
        labels: Dictionary of volume labels from pxctl volume inspect.

    Returns:
        Dictionary containing only labels with SECRET_ or px/ prefixes.
    """
    if not labels:
        return {}

    return {key: value for key, value in labels.items() if key.startswith("SECRET_") or key.startswith("px/")}


def initialize_pvc_vault_environment(core_v1_client: client.CoreV1Api, px_namespace: str) -> Optional[Tuple[Dict[str, str], str, client.V1Pod, List[str]]]:
    """Initialize environment for PVC vault operations.

    This function consolidates the common initialization logic used by both
    the PVC data exporter and vault secret checker scripts.

    Args:
        core_v1_client: Kubernetes CoreV1Api client
        px_namespace: Namespace where Portworx and vault secrets are located

    Returns:
        Tuple containing:
        - Vault connection info dict
        - Service account JWT string
        - Running Portworx pod
        - List of effective environment variables for pxctl

        Returns None if initialization fails.
    """
    # Get Vault connection info from K8s secret
    vault_conn_info = get_secret_data(px_namespace, VAULT_ADDR_SECRET_NAME, core_v1_client)
    if not vault_conn_info:
        logger.error(f"Failed to retrieve Vault connection info from secret '{VAULT_ADDR_SECRET_NAME}'.")
        return None

    # Map secret keys to expected keys used by the application
    key_mapping = {
        "VAULT_ADDR": "addr",
        "VAULT_BACKEND_PATH": "backend_path",
        "VAULT_AUTH_KUBERNETES_ROLE": "auth_role",
        "VAULT_AUTH_MOUNT_PATH": "auth_mount_path",
        "VAULT_NAMESPACE": "namespace",
    }

    mapped_vault_info = {}
    for secret_key, app_key in key_mapping.items():
        if secret_key in vault_conn_info:
            mapped_vault_info[app_key] = vault_conn_info[secret_key]
        else:
            logger.warning(f"Missing expected key '{secret_key}' in px-vault secret")

    vault_conn_info = mapped_vault_info

    # Get service account JWT
    sa_jwt = get_service_account_jwt(px_namespace, VAULT_SA_NAME, core_v1_client)
    if not sa_jwt:
        logger.error(f"Failed to retrieve Service Account JWT for '{VAULT_SA_NAME}'.")
        return None

    # Find running Portworx pod
    px_pod = find_running_pod_by_label(px_namespace, PORTWORX_POD_LABEL_SELECTOR, core_v1_client)
    if not px_pod:
        logger.error(f"Could not find a running Portworx pod in '{px_namespace}'.")
        return None

    # Get pxctl auth environment
    pxctl_auth_env = get_pxctl_auth_env(px_namespace, core_v1_client)
    effective_env_vars = [pxctl_auth_env] if pxctl_auth_env else []

    return vault_conn_info, sa_jwt, px_pod, effective_env_vars
