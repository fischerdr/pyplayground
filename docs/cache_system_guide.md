# Ansible Tower Cache System Guide

This document describes the cache system implemented in the `ansible_tower_utils.py` module to speed up resource lookups and reduce API calls to Ansible Tower/Controller.

## Overview

The cache system provides automatic caching for the `find_resource_by_attribute_name()` function and its related helper functions (`find_resource_by_name()`, `find_resource_by_id()`). This significantly improves performance when making repeated lookups for the same resources.

## Features

- **Automatic Caching**: All resource lookups are automatically cached
- **Time-based Expiration**: Cache entries expire after 5 minutes (configurable)
- **Memory Management**: Automatic cleanup of expired entries and size limits
- **Manual Control**: Functions to manually invalidate or clear cache entries
- **Statistics**: Built-in cache statistics and monitoring

## Configuration

The cache system uses the following configuration constants (defined at the top of the module):

```python
_CACHE_TTL = 300  # 5 minutes in seconds
_CACHE_MAX_SIZE = 1000  # Maximum number of cached entries
```

## Cache Functions

### Core Functions

#### `find_resource_by_attribute_name()`

The main function that now includes caching. It automatically:

- Checks the cache before making API calls
- Stores successful API responses in the cache
- Returns cached data when available and valid

#### `find_resource_by_name()`

Helper function that searches by exact name (uses `find_resource_by_attribute_name()` internally)

#### `find_resource_by_id()`

Helper function that searches by exact ID (uses `find_resource_by_attribute_name()` internally)

### Cache Management Functions

#### `get_cache_stats()`

Returns statistics about the current cache state:

```python
{
    "total_entries": 10,
    "valid_entries": 8,
    "expired_entries": 2,
    "cache_size_limit": 1000,
    "ttl_seconds": 300
}
```

#### `clear_resource_cache()`

Clears the entire cache. Useful when you know data has changed on the server.

#### `cleanup_cache()`

Removes expired entries and manages cache size. Returns cleanup statistics:

```python
{
    "initial_entries": 10,
    "final_entries": 8,
    "removed_entries": 2
}
```

#### `invalidate_cache_entry(tower_url, endpoint, attribute_name, value, verify)`

Removes a specific cache entry. Returns `True` if the entry was found and removed.

#### `invalidate_cache_by_endpoint(tower_url, endpoint, verify)`

Removes all cache entries for a specific endpoint. Returns the number of entries removed.

## Usage Examples

### Basic Usage

The cache system works transparently - no changes needed to existing code:

```python
from pyplayground.utils.ansible_tower_utils import find_resource_by_name

# First call - hits the API
result1 = find_resource_by_name(tower_url, headers, "job_templates", "my_template", verify)

# Second call - uses cache (much faster)
result2 = find_resource_by_name(tower_url, headers, "job_templates", "my_template", verify)
```

### Cache Management

```python
from pyplayground.utils.ansible_tower_utils import (
    get_cache_stats,
    clear_resource_cache,
    invalidate_cache_entry
)

# Check cache status
stats = get_cache_stats()
print(f"Cache has {stats['valid_entries']} valid entries")

# Invalidate specific entry
invalidate_cache_entry(tower_url, "job_templates", "name", "my_template", verify)

# Clear entire cache
clear_resource_cache()
```

### Monitoring Cache Performance

```python
import logging

# Enable debug logging to see cache hits/misses
logging.getLogger('pyplayground.utils.ansible_tower_utils').setLevel(logging.DEBUG)

# Run your lookups
result = find_resource_by_name(tower_url, headers, "job_templates", "my_template", verify)

# Check cache statistics
stats = get_cache_stats()
print(f"Cache hit rate: {stats['valid_entries']}/{stats['total_entries']}")
```

## Performance Benefits

- **Reduced API Calls**: Repeated lookups for the same resource use cached data
- **Faster Response Times**: Cache hits are nearly instantaneous
- **Reduced Server Load**: Fewer requests to the Ansible Tower API
- **Better User Experience**: Faster script execution times

## Cache Key Structure

Cache keys are tuples containing:

1. `tower_url` - The base URL of the Tower instance
2. `endpoint` - API endpoint (e.g., 'job_templates', 'inventories')
3. `attribute_name` - Attribute being searched (e.g., 'name', 'id')
4. `value` - Value being searched for
5. `verify` - SSL verification setting (as string)

This ensures that different Tower instances, endpoints, and search criteria are cached separately.

## Best Practices

### When to Clear Cache

- After creating, updating, or deleting resources
- When you know data has changed on the server
- Before running critical operations that require fresh data

### Monitoring

- Use `get_cache_stats()` to monitor cache performance
- Enable debug logging to see cache behavior
- Consider cache hit rates when optimizing performance

### Memory Management

- The cache automatically manages memory usage
- Expired entries are cleaned up automatically
- Cache size is limited to prevent memory bloat

## Example Script

See `pyplayground/cache_example.py` for a complete demonstration of the cache system functionality.

## Troubleshooting

### Cache Not Working

- Check that you're using the same parameters (URL, endpoint, attribute, value, verify)
- Verify that the cache hasn't expired (5-minute TTL)
- Enable debug logging to see cache behavior

### Memory Issues

- The cache is limited to 1000 entries by default
- Expired entries are automatically removed
- Use `cleanup_cache()` to manually clean up if needed

### Stale Data

- Cache entries expire after 5 minutes
- Use `invalidate_cache_entry()` or `clear_resource_cache()` to force refresh
- Consider reducing TTL if data changes frequently
