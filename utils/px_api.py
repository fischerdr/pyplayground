#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared PX-Backup API Client and Authentication Utilities.

This module provides a common API client for PX-Backup modules and utilities
for generating authentication tokens.

"""

import json  # Import json for logging
import logging
from typing import Any, Dict, Optional

import requests
from kubernetes import client

from utils.k8s_utils import get_configmap_data

logger = logging.getLogger(__name__)


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

    def _handle_http_error(
        self, http_err: requests.exceptions.HTTPError
    ) -> requests.exceptions.RequestException:
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
                logger.error(
                    f"Successful status code ({response.status_code}) but failed to decode JSON response from {url}: {json_err}"
                )
                raise ValueError(
                    f"Invalid JSON received from API despite success status: {response.text}"
                ) from json_err

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


def _request_token_data(
    url: str, headers: Dict[str, str], data: Dict[str, str], validate_certs: bool
) -> Dict[str, Any]:
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
        raise requests.exceptions.RequestException(
            error_msg, response=http_err.response
        ) from http_err
    except requests.exceptions.RequestException as req_err:
        # Log connection/timeout errors
        logger.error(
            f"Token request failed: {req_err}", exc_info=logger.isEnabledFor(logging.DEBUG)
        )
        raise  # Re-raise original RequestException
    except json.JSONDecodeError as json_err:  # Catch error if successful status but invalid JSON
        logger.error(
            f"Failed to decode JSON response from token endpoint {url}: {json_err}", exc_info=True
        )
        # Raise ValueError as the structure is unexpected
        raise ValueError(
            f"Invalid JSON received from token endpoint: {response.text}"
        ) from json_err


def generate_token(
    auth_url: str, client_id: str, username: str, password: str, validate_certs: bool
) -> str:
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


def get_cloud_drive_config(
    namespace: str, configmap_name: str, v1_client: Optional[client.CoreV1Api] = None
) -> Dict[str, Any]:
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
