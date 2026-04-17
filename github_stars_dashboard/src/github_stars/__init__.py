"""GitHub Stars Dashboard - Track and analyze GitHub repository stars."""

__version__ = "0.1.0"

from github_stars.categorizer import (
    CategorizationResult,
    Categorizer,
    CategoryConfig,
    CategoryConfigLoader,
    CategoryManager,
    categorize_repository,
    load_categories_from_config,
    update_repository_category,
)
from github_stars.fetcher import GitHubAPIError, GitHubClient
from github_stars.logger import JSONFormatter, StructuredLogger
from github_stars.scheduler import ScheduledSync
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
    # Scheduler
    "ScheduledSync",
    # Models
    "Category",
    "Repository",
    "Star",
    "ActivityLog",
    # API
    "app",
    # CLI
    "app as cli_app",
    # Logging
    "StructuredLogger",
    "JSONFormatter",
]

from github_stars.api import app
from github_stars.cli import app as cli_app
from github_stars.models import ActivityLog, Category, Repository, Star
