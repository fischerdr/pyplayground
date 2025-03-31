"""Utility functions for inventory operations."""

import json
import logging
from typing import Dict, List, Optional, Union

import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)


def search_inventory(
    base_url: str,
    api_key: Optional[str] = None,
    offset: int = 0,
    limit: int = 100,
    env: Optional[str] = None,
    install_type: Optional[str] = None,
    network: Optional[str] = None,
    region: Optional[str] = None,
    zone: Optional[str] = None,
    tenancy: Optional[str] = None,
    tier: Optional[Union[str, int, float]] = None,
    status: Optional[str] = None,
    is_under_maintenance: Optional[bool] = None,
    car_ids: Optional[List[str]] = None,
    features: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    workloads: Optional[List[str]] = None,
    timeout: int = 30,
    verify_ssl: bool = True,
    cert_path: Optional[str] = None,
    debug_request: bool = False,
) -> Dict:
    """
    Search for inventory clusters with flexible filtering options.

    Args:
        base_url: Base URL for the inventory API
        api_key: Optional API key for authentication
        offset: Pagination offset
        limit: Maximum number of results to return
        env: Filter by environment (e.g., 'prod', 'dev', 'test')
        install_type: Filter by installation type (e.g., 'upi')
        network: Filter by network type (e.g., 'internet')
        region: Filter by region (e.g., 'euswest1')
        zone: Filter by zone (e.g., 'a', 'b', 'c')
        tenancy: Filter by tenancy type (e.g., 'single-tenancy')
        tier: Filter by tier
        status: Filter by status (e.g., 'provisioned')
        is_under_maintenance: Filter by maintenance status
        car_ids: Filter by CAR IDs
        features: Filter by features
        tags: Filter by tags
        workloads: Filter by workloads
        timeout: Request timeout in seconds
        verify_ssl: Whether to verify SSL certificates
        cert_path: Path to a custom certificate file to use for verification
        debug_request: Whether to enable detailed request debugging

    Returns:
        Dict containing the inventory search results

    Raises:
        RequestException: If the request fails
    """
    # Construct the endpoint URL
    endpoint = f"{base_url.rstrip('/')}/v1/inventory/clusters"

    # Build query parameters
    params = {}
    if offset is not None:
        params["offset"] = offset
    if limit is not None:
        params["limit"] = limit
    if env:
        params["env"] = env
    if install_type:
        params["install_type"] = install_type
    if network:
        params["network"] = network
    if region:
        params["region"] = region
    if zone:
        params["zone"] = zone
    if tenancy:
        params["tenancy"] = tenancy
    if tier is not None:
        params["tier"] = tier
    if status:
        params["status"] = status
    if is_under_maintenance is not None:
        params["is_under_maintenance"] = str(is_under_maintenance).lower()

    # Add list parameters
    for name, values in [
        ("car_ids", car_ids),
        ("features", features),
        ("tags", tags),
        ("workloads", workloads),
    ]:
        if values:
            for value in values:
                if name in params:
                    params[name].append(value)
                else:
                    params[name] = [value]

    # Set up headers
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Enable request debugging if needed
    if debug_request:
        # Set up a session with debugging
        session = requests.Session()

        # Create a request object for logging purposes
        req = requests.Request("GET", endpoint, headers=headers, params=params)
        prepared_req = session.prepare_request(req)

        # Log the request details
        logger.debug("=" * 80)
        logger.debug("REQUEST DETAILS:")
        logger.debug("-" * 80)
        logger.debug(f"Method: {prepared_req.method}")
        logger.debug(f"URL: {prepared_req.url}")
        logger.debug("Headers:")
        for name, value in prepared_req.headers.items():
            # Mask sensitive headers
            if name.lower() in ["authorization", "x-api-key"]:
                logger.debug(f"  {name}: ****REDACTED****")
            else:
                logger.debug(f"  {name}: {value}")
        logger.debug(f"SSL Verification: {verify_ssl if cert_path is None else cert_path}")
        logger.debug("-" * 80)

    try:
        logger.debug(f"Sending inventory search request to {endpoint}")
        # Use the verify parameter with either a boolean or path to cert
        verify = cert_path if cert_path else verify_ssl

        # Make the request
        response = requests.get(
            endpoint, headers=headers, params=params, timeout=timeout, verify=verify
        )

        # Log response details if debug is enabled
        if debug_request:
            logger.debug("=" * 80)
            logger.debug("RESPONSE DETAILS:")
            logger.debug("-" * 80)
            logger.debug(f"Status Code: {response.status_code}")
            logger.debug(f"Reason: {response.reason}")
            logger.debug("Headers:")
            for name, value in response.headers.items():
                logger.debug(f"  {name}: {value}")
            logger.debug("-" * 80)

            # Log response content preview (truncated if too large)
            content_preview = (
                response.text[:1000] + "..." if len(response.text) > 1000 else response.text
            )
            logger.debug("Response Content Preview:")
            logger.debug(content_preview)
            logger.debug("=" * 80)

        response.raise_for_status()
        return response.json()
    except RequestException as e:
        logger.error(f"Inventory search request failed: {str(e)}")
        # Add more detailed error information in debug mode
        if debug_request and hasattr(e, "response") and e.response is not None:
            logger.debug("=" * 80)
            logger.debug("ERROR RESPONSE DETAILS:")
            logger.debug("-" * 80)
            logger.debug(f"Status Code: {e.response.status_code}")
            logger.debug(f"Reason: {e.response.reason}")
            logger.debug("Headers:")
            for name, value in e.response.headers.items():
                logger.debug(f"  {name}: {value}")

            # Log error response content
            try:
                error_content = e.response.text
                logger.debug("Error Response Content:")
                logger.debug(error_content)
            except Exception:
                logger.debug("Could not retrieve error response content")
            logger.debug("=" * 80)
        raise
