"""GitHub Stars Dashboard - Track and analyze GitHub repository stars."""

__version__ = "0.1.0"

from github_stars.categorizer import (
    CategoryConfig,
    CategorizationResult,
    CategoryConfigLoader,
    CategoryManager,
    Categorizer,
    categorize_repository,
    load_categories_from_config,
    update_repository_category,
)
from github_stars.fetcher import GitHubAPIError, GitHubClient
from github_stars.sync import RepoSyncer, SyncStats, sync_starred_repos

__all__ = [
    # Fetcher
    "GitHubClient",
    "GitHubAPIError",
    # Categorizer
    "CategoryManager",
    "CategoryConfigLoader",
    "Categorizer",
    "CategoryConfig",
    "CategorizationResult",
    "categorize_repository",
    "update_repository_category",
    "load_categories_from_config",
    # Sync
    "RepoSyncer",
    "SyncStats",
    "sync_starred_repos",
    # Models
    "Category",
    "Repository",
    "Star",
    "ActivityLog",
]

from github_stars.models import ActivityLog, Category, Repository, Star
