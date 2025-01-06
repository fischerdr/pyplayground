import json
import logging

import click
import requests

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Base URL for the API (can be configured)
BASE_URL = "https://px-backup-api-url"  # Replace with the correct API endpoint

@click.group()
def cli():
    """CLI tool for interacting with the px-backup API."""
    pass

def make_request(method, endpoint, params=None, data=None, headers=None):
    """Helper function to make API requests."""
    url = f"{BASE_URL}{endpoint}"
    try:
        response = requests.request(method, url, params=params, json=data, headers=headers)
        response.raise_for_status()
        logger.info(f"Request to {url} successful.")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error during request to {url}: {e}")
        click.echo(f"Error: {e}")
        return None

# Example command: Fetch resources
@cli.command()
@click.option('--resource', required=True, help="The API resource to fetch, e.g., '/clusters'.")
def get_resource(resource):
    """Fetch a resource from the API."""
    logger.info(f"Fetching resource: {resource}")
    result = make_request('GET', resource)
    if result:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo("Failed to fetch resource.")

# Example command: Create a resource
@cli.command()
@click.option('--resource', required=True, help="The API resource to create, e.g., '/clusters'.")
@click.option('--data', required=True, help="JSON data for the resource.")
def create_resource(resource, data):
    """Create a resource in the API."""
    logger.info(f"Creating resource: {resource}")
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON data provided.")
        click.echo("Error: Invalid JSON data.")
        return

    result = make_request('POST', resource, data=payload)
    if result:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo("Failed to create resource.")

# Example command: Delete a resource
@cli.command()
@click.option('--resource', required=True, help="The API resource to delete, e.g., '/clusters/{id}'.")
def delete_resource(resource):
    """Delete a resource in the API."""
    logger.info(f"Deleting resource: {resource}")
    result = make_request('DELETE', resource)
    if result:
        click.echo("Resource deleted successfully.")
    else:
        click.echo("Failed to delete resource.")

if __name__ == "__main__":
    cli()
