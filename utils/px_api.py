#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Shared PX-Backup API Client and Authentication Utilities.
"""

import logging
from typing import Dict, Optional, Any
import requests

logger = logging.getLogger(__name__)


class PXBackupClient:
    """Common API client for PX-Backup modules"""

    def __init__(self, api_url: str, token: str, validate_certs: bool = True):
        """
        Initialize the PXBackupClient.

        Args:
            api_url: The base URL for the PX-Backup API.
            token: The authentication token.
            validate_certs: Whether to validate SSL certificates. Defaults to True.
        """
        # Add protocol if not present
        if not api_url.startswith(('http://', 'https://')):
            # Defaulting to https based on playbook usage
            api_url = f"https://{api_url}"
            logger.info(f"Protocol not specified, assuming HTTPS: {api_url}")
        self.api_url = api_url.rstrip('/')
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {token}"
        }
        self.validate_certs = validate_certs
        logger.debug(f"API Client initialized for {self.api_url}")

    def make_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Make HTTP request to PX-Backup API.

        Args:
            method: HTTP method (e.g., 'GET', 'POST', 'PUT', 'DELETE').
            endpoint: API endpoint path (e.g., '/v1/cluster').
            data: Request body data for POST/PUT requests. Defaults to None.
            params: URL query parameters. Defaults to None.

        Returns:
            The JSON response from the API as a dictionary.

        Raises:
            requests.exceptions.RequestException: If the request fails.
            ValueError: If the response is not valid JSON.
        """
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        logger.debug(f"Making {method} request to {url} with params: {params}, data: {data is not None}")

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                params=params,
                verify=self.validate_certs
            )
            logger.debug(f"Response status code: {response.status_code}")
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            return response.json()
        except requests.exceptions.HTTPError as http_err:
            error_msg = f"HTTP error occurred: {http_err}"
            try:
                # Attempt to get more detail from the JSON response
                error_detail = http_err.response.json()
                error_msg = f"{error_msg} - Response: {error_detail}"
            except ValueError:
                # Fallback to raw text if response is not JSON
                error_msg = f"{error_msg} - Response: {http_err.response.text}"
            logger.error(error_msg)
            # Re-raise as RequestException attaching the original response
            raise requests.exceptions.RequestException(error_msg, response=http_err.response) from http_err
        except requests.exceptions.RequestException as req_err:
            # Handle other request errors (connection, timeout, etc.)
            logger.error(f"Request failed: {req_err}")
            raise
        except ValueError as json_err:  # Includes JSONDecodeError
            # Handle errors decoding the JSON response
            logger.error(f"Failed to decode JSON response from {url}: {json_err}")
            raise ValueError(f"Invalid JSON received from API: {response.text}") from json_err


def generate_token(auth_url: str, client_id: str, username: str, password: str, validate_certs: bool) -> str:
    """
    Requests a bearer token from the authentication endpoint.

    Args:
        auth_url: The base URL for the authentication server.
        client_id: Client identifier for authentication.
        username: Username for authentication.
        password: Password for authentication.
        validate_certs: Whether to validate SSL certificates.

    Returns:
        The access token string.

    Raises:
        requests.exceptions.RequestException: If the token request fails.
        ValueError: If the access token is not found in the response.
    """
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    # Add protocol if not present (defaulting to https)
    if not auth_url.startswith(('http://', 'https://')):
        auth_url = f"https://{auth_url}"
        logger.info(f"Auth URL protocol not specified, assuming HTTPS: {auth_url}")

    # Endpoint confirmed from auth.py
    url = f"{auth_url.rstrip('/')}/auth/realms/master/protocol/openid-connect/token"
    data = {
        'grant_type': 'password',  # Hardcoded based on auth.py
        'client_id': client_id,
        'username': username,
        'password': password,
        # 'token-duration' is not included here, using server default
    }
    logger.info(f"Requesting token from {url} for user {username}")
    try:
        response = requests.post(url, headers=headers, data=data, verify=validate_certs)
        logger.debug(f"Token response status code: {response.status_code}")
        response.raise_for_status()
        token_response = response.json()
        access_token = token_response.get('access_token')
        if not access_token:
            raise ValueError("Access token not found in authentication response.")
        logger.info("Successfully obtained access token.")
        return access_token
    except requests.exceptions.HTTPError as http_err:
        error_msg = f"Token request HTTP error: {http_err}"
        try:
            error_detail = http_err.response.json()
            error_msg = f"{error_msg} - Response: {error_detail}"
        except ValueError:
            error_msg = f"{error_msg} - Response: {http_err.response.text}"
        logger.error(error_msg)
        raise requests.exceptions.RequestException(error_msg, response=http_err.response) from http_err
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Token request failed: {req_err}")
        raise
    except ValueError as val_err:
        logger.error(f"Error processing token response: {val_err}")
        raise
