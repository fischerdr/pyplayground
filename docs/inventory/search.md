# Inventory Search Tool

## Overview

The Inventory Search Tool provides a flexible command-line interface for searching and filtering inventory clusters. It allows users to search for clusters based on various criteria such as environment, region, zone, status, and more.

## Installation

The tool is part of the pyplayground project. To use it, ensure you have all the required dependencies installed:

```bash
pip install -r requirements.txt
```

## Usage

The inventory search script can be run from the command line with various options:

```bash
./bin/inventory_search.py --base-url https://api.example.com [OPTIONS]
```

### Environment Variables

The tool supports the following environment variables:

- `INVENTORY_API_URL`: Base URL for the inventory API (can be overridden with `--base-url`)
- `INVENTORY_API_KEY`: API key for authentication (can be overridden with `--api-key`)

You can set these in a `.env` file in the project root or export them in your shell.

### Command Line Options

| Option | Description |
|--------|-------------|
| `--base-url` | Base URL for the inventory API (required) |
| `--api-key` | API key for authentication |
| `--offset` | Pagination offset (default: 0) |
| `--limit` | Maximum number of results to return (default: 100) |
| `--env` | Filter by environment (e.g., 'prod', 'dev', 'test') |
| `--install-type` | Filter by installation type (e.g., 'upi') |
| `--network` | Filter by network type (e.g., 'internet') |
| `--region` | Filter by region (e.g., 'euswest1') |
| `--zone` | Filter by zone (e.g., 'a', 'b', 'c') |
| `--tenancy` | Filter by tenancy type (e.g., 'single-tenancy') |
| `--tier` | Filter by tier |
| `--status` | Filter by status (e.g., 'provisioned') |
| `--is-under-maintenance` | Filter by maintenance status (flag) |
| `--car-id` | Filter by CAR ID (can be specified multiple times) |
| `--feature` | Filter by feature (can be specified multiple times) |
| `--tag` | Filter by tag (can be specified multiple times) |
| `--workload` | Filter by workload (can be specified multiple times) |
| `--timeout` | Request timeout in seconds (default: 30) |
| `--output` | Output format: 'table' or 'json' (default: 'table') |
| `--debug` | Enable debug logging (flag) |

### Examples

#### Basic Search

Search for production clusters:

```bash
./bin/inventory_search.py --base-url https://api.example.com --env prod
```

#### Filtering by Multiple Criteria

Search for clusters in a specific region and zone:

```bash
./bin/inventory_search.py --base-url https://api.example.com --region euswest1 --zone c
```

#### Using Multiple Values for List Filters

Search for clusters with specific features and tags:

```bash
./bin/inventory_search.py --base-url https://api.example.com --feature feature1 --feature feature2 --tag tag1
```

#### JSON Output

Get results in JSON format:

```bash
./bin/inventory_search.py --base-url https://api.example.com --output json
```

## API Integration

The tool uses the inventory API endpoint:

```text
{base_url}/v1/inventory/clusters
```

### Response Format

The API response is expected to be a JSON object with the following structure:

```json
{
  "clusters": [
    {
      "id": "cluster-id",
      "name": "cluster-name",
      "env": "prod",
      "region": "euswest1",
      "zone": "c",
      "status": "provisioned",
      ...
    },
    ...
  ],
  "total": 42
}
```

## Utility Function

The script uses a reusable utility function from the `utils.inventory` module:

```python
from utils.inventory import search_inventory

results = search_inventory(
    base_url="https://api.example.com",
    env="prod",
    region="euswest1"
)
```

This function can be imported and used in other scripts that need to search inventory.

## Troubleshooting

### Debug Mode

Enable debug mode to see more detailed logging:

```bash
./bin/inventory_search.py --base-url https://api.example.com --debug
```

### Common Issues

1. **API Connection Errors**: Ensure the base URL is correct and the API is accessible.
2. **Authentication Errors**: Check that your API key is valid and properly formatted.
3. **No Results**: Verify your search criteria; you might be filtering too strictly.

## Security Considerations

- The API key is sensitive information and should be kept secure.
- Use environment variables or a `.env` file to store API keys rather than passing them on the command line.
- The script uses HTTPS for secure communication with the API.
