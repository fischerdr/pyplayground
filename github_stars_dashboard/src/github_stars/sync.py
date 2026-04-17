"""Data synchronization logic for GitHub Stars Dashboard.

This module provides functionality to sync starred repositories from GitHub
to the local database, including creating/updating repositories and stars.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from github_stars.categorizer import (
    update_repository_category,
)
from github_stars.fetcher import GitHubAPIError, GitHubClient
from github_stars.models import ActivityLog, Repository, Star

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    """Statistics for a sync operation.

    Attributes:
        total_starred: Total number of starred repos from GitHub.
        new_repos: Number of new repositories created.
        updated_repos: Number of existing repositories updated.
        inactive_repos: Number of repos marked inactive.
        new_stars: Number of new star events recorded.
        skipped_repos: Number of repos skipped (already up to date).
        errors: Number of errors encountered.
        duration_seconds: Sync duration in seconds.
    """

    total_starred: int = 0
    new_repos: int = 0
    updated_repos: int = 0
    inactive_repos: int = 0
    new_stars: int = 0
    skipped_repos: int = 0
    errors: int = 0
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "total_starred": self.total_starred,
            "new_repos": self.new_repos,
            "updated_repos": self.updated_repos,
            "inactive_repos": self.inactive_repos,
            "new_stars": self.new_stars,
            "skipped_repos": self.skipped_repos,
            "errors": self.errors,
            "duration_seconds": self.duration_seconds,
        }


class RepoSyncer:
    """Synchronize starred repositories from GitHub to database.

    Attributes:
        github_client: GitHub API client.
        session: Database session.
        stats: Sync statistics.
    """

    def __init__(
        self,
        github_client: GitHubClient,
        session: Session,
        categories_config_path: str | None = None,
    ) -> None:
        """Initialize RepoSyncer.

        Args:
            github_client: GitHub API client.
            session: Database session.
            categories_config_path: Optional path to categories config.
        """
        self.github_client = github_client
        self.session = session
        self.categories_config_path = categories_config_path
        self.stats = SyncStats()
        self._existing_repo_names: set[str] = set()

        logger.debug("RepoSyncer initialized")

    def _log_activity(
        self, action: str, details: dict[str, Any], repository: Repository | None = None
    ) -> None:
        """Log an activity to the database.

        Args:
            action: Action type (create, update, delete, etc.).
            details: Action details as dictionary.
            repository: Optional repository instance.
        """
        try:
            import json

            activity_log = ActivityLog(
                action=action,
                details=json.dumps(details),
            )

            if repository:
                activity_log.details = json.dumps(  # type: ignore[assignment]
                    {**details, "repository_id": repository.id}
                )

            self.session.add(activity_log)
            logger.debug("Logged activity: %s - %s", action, details)

        except Exception as e:
            logger.error("Failed to log activity: %s", e)

    def _get_or_create_repository(
        self, repo_data: dict[str, Any]
    ) -> tuple[Repository, bool]:
        """Get existing repository or create new one.

        Args:
            repo_data: Repository data from GitHub.

        Returns:
            Tuple of (Repository, is_new).
        """
        full_name = repo_data["full_name"]

        repository = (
            self.session.query(Repository).filter_by(full_name=full_name).first()
        )

        if repository:
            logger.debug("Found existing repository: %s", full_name)
            return repository, False

        logger.info("Creating new repository: %s", full_name)

        repository = Repository(
            full_name=full_name,
            html_url=repo_data.get("html_url", f"https://github.com/{full_name}"),
            description=repo_data.get("description"),
            stars_count=repo_data.get("stars", repo_data.get("stars_count", 0)),
            forks_count=repo_data.get("forks", repo_data.get("forks_count", 0)),
            language=repo_data.get("language"),
            is_active=True,
        )

        self.session.add(repository)
        self._existing_repo_names.add(full_name)
        return repository, True

    def _create_star_record(
        self,
        repository: Repository,
        starred_at: datetime | None = None,
        is_new: bool = True,
    ) -> Star | None:
        """Create a star record for a repository.

        Args:
            repository: Repository instance.
            starred_at: When the star occurred.
            is_new: Whether this is a new star event.

        Returns:
            Created Star instance or None.
        """
        # Check for duplicate star
        existing_star = (
            self.session.query(Star)
            .filter_by(repository_id=repository.id, is_new=is_new)
            .first()
        )

        if existing_star:
            logger.debug(
                "Duplicate star record found for repo %s", repository.full_name
            )
            return None

        star = Star(
            repository_id=repository.id,
            starred_at=starred_at or datetime.now(UTC),
            is_new=is_new,
        )

        self.session.add(star)
        self.stats.new_stars += 1
        logger.debug("Created star record for repository: %s", repository.full_name)
        return star

    def _update_repository_data(
        self, repository: Repository, repo_data: dict[str, Any]
    ) -> bool:
        """Update repository data if changed.

        Args:
            repository: Repository instance.
            repo_data: New data from GitHub.

        Returns:
            True if repository was updated.
        """
        updated = False

        fields_to_check = [
            "description",
            "stars_count",
            "forks_count",
            "language",
        ]

        for field in fields_to_check:
            github_value = repo_data.get(field)
            if github_value is not None:
                current_value = getattr(repository, field)
                if current_value != github_value:
                    setattr(repository, field, github_value)
                    updated = True
                    logger.debug(
                        "Updated %s for repository %s: %s -> %s",
                        field,
                        repository.full_name,
                        current_value,
                        github_value,
                    )

        if updated:
            repository.updated_at = datetime.now(UTC)  # type: ignore[assignment]
            self.stats.updated_repos += 1

            return updated

        return False

    def _mark_inactive_repos(self, starred_names: set[str]) -> None:
        """Mark repositories not in star list as inactive.

        Args:
            starred_names: Set of currently starred repository names.
        """
        inactive_repos = (
            self.session.query(Repository)
            .filter(
                Repository.full_name.notin_(starred_names),
                Repository.is_active,
            )
            .all()
        )

        for repo in inactive_repos:
            repo.is_active = False  # type: ignore[assignment]
            self.session.add(repo)
            self.stats.inactive_repos += 1
            logger.info("Marked repository as inactive: %s", repo.full_name)
            self._log_activity(
                "deactivate",
                {"reason": "no longer starred"},
                repo,
            )

    def sync_starred_repos(self) -> SyncStats:
        """Sync all starred repositories from GitHub.

        This method:
        1. Fetches all starred repos from GitHub
        2. Updates existing repos or creates new ones
        3. Creates star records for recent activity
        4. Marks inactive repos
        5. Logs all changes

        Returns:
            SyncStats with operation statistics.
        """
        import time

        start_time = time.time()
        self.stats = SyncStats()

        logger.info("Starting starred repos sync")

        try:
            # Fetch starred repos from GitHub
            starred_repos = self.github_client.fetch_starred_repos()
            self.stats.total_starred = len(starred_repos)
            logger.info(
                "Fetched %d starred repositories from GitHub", self.stats.total_starred
            )

            if not starred_repos:
                logger.warning("No starred repositories found")
                self.stats.duration_seconds = time.time() - start_time
                return self.stats

            starred_names = set()

            for repo_data in starred_repos:
                try:
                    full_name = repo_data["full_name"]
                    starred_names.add(full_name)

                    repository, is_new = self._get_or_create_repository(repo_data)

                    if is_new:
                        self.stats.new_repos += 1
                        self._log_activity(
                            "create",
                            {
                                "full_name": full_name,
                                "stars": repo_data.get("stars"),
                                "language": repo_data.get("language"),
                            },
                            repository,
                        )
                    else:
                        if self._update_repository_data(repository, repo_data):
                            self._log_activity(
                                "update",
                                {
                                    "stars_changed": repository.stars_count,
                                    "description_changed": repository.description
                                    is not None,
                                },
                                repository,
                            )
                        else:
                            self.stats.skipped_repos += 1

                    # Update category
                    try:
                        update_repository_category(repository, self.session)
                        logger.debug("Updated category for repository: %s", full_name)
                    except Exception as e:
                        logger.warning(
                            "Failed to update category for %s: %s", full_name, e
                        )

                    # Create star record for recent activity
                    created_at_str = repo_data.get("created_at")
                    if created_at_str:
                        try:
                            created_at = datetime.fromisoformat(
                                created_at_str.replace("Z", "+00:00")
                            )
                            now = datetime.now(UTC)
                            days_since_created = (now - created_at).days

                            # Only create star record if created in last 30 days
                            if days_since_created <= 30:
                                self._create_star_record(
                                    repository,
                                    starred_at=created_at,
                                    is_new=True,
                                )
                        except (ValueError, TypeError) as e:
                            logger.warning(
                                "Failed to parse created_at for %s: %s",
                                full_name,
                                e,
                            )

                except Exception as e:
                    self.stats.errors += 1
                    logger.error(
                        "Error processing repository %s: %s",
                        repo_data.get("full_name"),
                        e,
                    )

            # Mark inactive repositories
            self._mark_inactive_repos(starred_names)

            # Commit all changes
            self.session.commit()
            logger.info("Successfully committed all changes")

        except GitHubAPIError as e:
            self.session.rollback()
            logger.error("GitHub API error during sync: %s", e)
            self.stats.errors += 1
        except Exception as e:
            self.session.rollback()
            logger.error("Error during sync: %s", e)
            self.stats.errors += 1
        finally:
            self.stats.duration_seconds = time.time() - start_time
            logger.info(
                "Sync completed in %.2f seconds: %d new, %d updated, %d inactive, %d stars, %d errors",
                self.stats.duration_seconds,
                self.stats.new_repos,
                self.stats.updated_repos,
                self.stats.inactive_repos,
                self.stats.new_stars,
                self.stats.errors,
            )

        return self.stats


def sync_starred_repos(
    github_token: str,
    user_login: str | None = None,
    database_url: str | None = None,
    categories_config_path: str | None = None,
) -> SyncStats:
    """Sync starred repositories from GitHub to database.

    This is a convenience function that creates all necessary components
    and performs the sync operation.

    Args:
        github_token: GitHub API token.
        user_login: Optional GitHub username.
        database_url: Optional database URL.
        categories_config_path: Optional path to categories config.

    Returns:
        SyncStats with operation statistics.
    """
    from github_stars.database import get_db_session
    from github_stars.fetcher import GitHubClient

    logger.info("Starting starred repos sync operation")

    session = get_db_session(database_url)

    try:
        github_client = GitHubClient(token=github_token, user_login=user_login)
        syncer = RepoSyncer(
            github_client=github_client,
            session=session,
            categories_config_path=categories_config_path,
        )

        stats = syncer.sync_starred_repos()
        return stats

    finally:
        session.close()
