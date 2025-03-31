"""Utility functions for inventory operations."""

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

    try:
        logger.debug(f"Sending inventory search request to {endpoint}")
        response = requests.get(endpoint, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except RequestException as e:
        logger.error(f"Inventory search request failed: {str(e)}")
        raise
