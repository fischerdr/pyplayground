#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Example script demonstrating the cache system in ansible_tower_utils."""

import logging
import sys

from pyplayground.utils.ansible_tower_utils import (
    cleanup_cache,
    clear_resource_cache,
    find_resource_by_name,
    get_awx_or_tower_client,
    get_cache_stats,
    invalidate_cache_by_endpoint,
    invalidate_cache_entry,
)

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_tower_config():
    """Get Tower client configuration."""
    try:
        client_config = get_awx_or_tower_client("AWX")
        return client_config["url"], client_config["headers"], client_config["verify"]
    except SystemExit:
        logger.error("Failed to get Tower client configuration. Please check your environment variables.")
        return None, None, None


def show_cache_stats(title: str) -> None:
    """Show cache statistics with a title."""
    logger.info(f"\n{title}:")
    stats = get_cache_stats()
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")


def demonstrate_lookups(tower_url: str, headers: dict, verify: bool) -> None:
    """Demonstrate resource lookups with caching."""
    # First lookup - should hit the API
    logger.info("\n1. First lookup for 'job_templates' endpoint:")
    result1 = find_resource_by_name(tower_url, headers, "job_templates", "example_template", verify)
    if result1:
        logger.info(f"Found {result1['count']} job templates")
    else:
        logger.info("No job templates found")

    # Second lookup - should hit the cache
    logger.info("\n2. Second lookup for 'job_templates' endpoint (should use cache):")
    result2 = find_resource_by_name(tower_url, headers, "job_templates", "example_template", verify)
    if result2:
        logger.info(f"Found {result2['count']} job templates (from cache)")
    else:
        logger.info("No job templates found (from cache)")


def demonstrate_cache_invalidation(tower_url: str, verify: bool) -> None:
    """Demonstrate cache invalidation methods."""
    # Demonstrate cache invalidation
    logger.info("\n3. Invalidating specific cache entry:")
    invalidated = invalidate_cache_entry(tower_url, "job_templates", "name", "example_template", verify)
    logger.info(f"Cache entry invalidated: {invalidated}")

    # Demonstrate endpoint cache invalidation
    logger.info("\n4. Invalidating all cache entries for 'job_templates' endpoint:")
    removed_count = invalidate_cache_by_endpoint(tower_url, "job_templates", verify)
    logger.info(f"Removed {removed_count} cache entries")


def demonstrate_cache_cleanup() -> None:
    """Demonstrate cache cleanup and clearing."""
    # Demonstrate cache cleanup
    logger.info("\n5. Running cache cleanup:")
    cleanup_stats = cleanup_cache()
    for key, value in cleanup_stats.items():
        logger.info(f"  {key}: {value}")

    # Demonstrate complete cache clearing
    logger.info("\n6. Clearing entire cache:")
    clear_resource_cache()


def demonstrate_cache_system() -> None:
    """Demonstrate the cache system functionality."""
    # Get Tower client configuration
    tower_url, headers, verify = get_tower_config()
    if not tower_url:
        return

    logger.info("=== Ansible Tower Cache System Demo ===")

    # Show initial cache stats
    show_cache_stats("Initial cache stats")

    # Demonstrate lookups
    demonstrate_lookups(tower_url, headers, verify)

    # Show cache stats after lookups
    show_cache_stats("Cache stats after lookups")

    # Demonstrate cache invalidation
    demonstrate_cache_invalidation(tower_url, verify)

    # Show cache stats after invalidation
    show_cache_stats("Cache stats after invalidation")

    # Demonstrate cache cleanup
    demonstrate_cache_cleanup()

    # Show final cache stats
    show_cache_stats("Final cache stats")

    # Show cache stats after clearing
    show_cache_stats("Cache stats after clearing")


def main() -> None:
    """Main function."""
    try:
        demonstrate_cache_system()
    except KeyboardInterrupt:
        logger.info("\nDemo interrupted by user.")
    except Exception as e:
        logger.error(f"Demo failed with error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
