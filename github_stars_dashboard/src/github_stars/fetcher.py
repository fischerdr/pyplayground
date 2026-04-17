"""GitHub API client for fetching repository data.

This module provides functionality to interact with the GitHub API,
including fetching starred repositories, repository details, and recent activity.
"""

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from github import Github, GithubException
from sqlalchemy.orm import Session

from github_stars.models import Repository

logger = logging.getLogger(__name__)


class GitHubAPIError(Exception):
    """Custom exception for GitHub API errors."""

    def __init__(self, message: str, status: int | None = None) -> None:
        """Initialize GitHubAPIError.

        Args:
            message: Error message.
            status: HTTP status code if available.
        """
        super().__init__(message)
        self.status = status


class GitHubRateLimitExceeded(GitHubAPIError):
    """Exception raised when GitHub rate limit is exceeded."""

    pass


class GitHubClient:
    """GitHub API client with rate limiting and retry support.

    Attributes:
        github: PyGithub Github instance.
        user_login: GitHub username for fetching starred repos.
        rate_limit_remaining: Remaining API requests.
        rate_limit_reset: Time when rate limit resets.
    """

    def __init__(self, token: str, user_login: str | None = None) -> None:
        """Initialize GitHub client.

        Args:
            token: GitHub API token.
            user_login: Optional GitHub username. If not provided,
                       token owner will be determined from API.
        """
        self.github = Github(login_or_token=token)
        self.user_login = user_login
        self.rate_limit_remaining = 5000
        self.rate_limit_reset = datetime.now(UTC) + timedelta(hours=1)
        self._last_request_time = 0.0
        self._request_delay = 0.0  # Rate limiting delay

        logger.info("GitHub client initialized for user: %s", user_login or "unknown")

    def _enforce_rate_limit(self) -> None:
        """Enforce GitHub API rate limiting.

        GitHub allows 5000 requests per hour for authenticated users.
        This method ensures we don't exceed the rate limit by adding
        delays between requests if necessary.
        """
        current_time = time.time()
        time_since_last_request = current_time - self._last_request_time

        if time_since_last_request < self._request_delay:
            sleep_time = self._request_delay - time_since_last_request
            logger.debug("Rate limiting: sleeping for %.2f seconds", sleep_time)
            time.sleep(sleep_time)

        self._last_request_time = time.time()

    def _handle_rate_limit(self, e: GithubException) -> None:
        """Handle rate limit errors from GitHub API.

        Args:
            e: GithubException that was raised.

        Raises:
            GitHubRateLimitExceeded: If rate limit is exceeded.
        """
        if e.status == 403:
            headers = e.headers or {}
            reset_time = headers.get("X-RateLimit-Reset")
            if reset_time:
                self.rate_limit_reset = datetime.fromtimestamp(int(reset_time), tz=UTC)
                remaining = int(headers.get("X-RateLimit-Remaining", 0))
                self.rate_limit_remaining = remaining

                logger.warning(
                    "Rate limit exceeded. Remaining: %d, Reset at: %s",
                    remaining,
                    self.rate_limit_reset.isoformat(),
                )

                if remaining == 0:
                    sleep_time = (
                        max(
                            0,
                            (self.rate_limit_reset - datetime.now(UTC)).total_seconds(),
                        )
                        + 5
                    )
                    logger.info("Waiting %.0f seconds for rate limit reset", sleep_time)
                    time.sleep(sleep_time)
                    self.rate_limit_remaining = 5000
        elif e.status == 404:
            logger.warning("Resource not found: %s", e.data.get("message", "Unknown"))

    def _make_request_with_retry(
        self,
        func: Any,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> Any:
        """Make API request with retry logic for transient failures.

        Args:
            func: Function to call for the API request.
            max_retries: Maximum number of retry attempts.
            retry_delay: Base delay between retries in seconds.

        Returns:
            Result of the function call.

        Raises:
            GitHubAPIError: If all retries fail.
        """
        last_exception: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                self._enforce_rate_limit()
                result = func()

                if attempt > 1:
                    logger.info("Request succeeded on attempt %d", attempt)

                return result

            except GithubException as e:
                last_exception = e

                if (
                    e.status == 403
                    and int((e.headers or {}).get("X-RateLimit-Remaining", 5000)) == 0
                ):
                    self._handle_rate_limit(e)
                    continue

                if e.status in (403, 404, 422):
                    logger.warning(
                        "API error (attempt %d/%d): %s",
                        attempt,
                        max_retries,
                        e.data.get("message", str(e)),
                    )
                    raise GitHubAPIError(e.data.get("message", str(e)), e.status) from e

                if attempt < max_retries:
                    wait_time = retry_delay * (2 ** (attempt - 1))
                    logger.debug(
                        "Transient error, retrying in %.1f seconds (attempt %d/%d)",
                        wait_time,
                        attempt,
                        max_retries,
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(
                        "All %d retries failed: %s",
                        max_retries,
                        e.data.get("message", str(e)),
                    )

        raise GitHubAPIError(
            f"Failed after {max_retries} retries: {last_exception}",
            getattr(last_exception, "status", None) if last_exception else None,
        ) from last_exception

    def validate_connection(self) -> dict[str, Any]:
        """Test GitHub token connection.

        Returns:
            Dictionary with connection status and user info.

        Raises:
            GitHubAPIError: If connection fails.
        """
        logger.info("Validating GitHub token connection")

        try:
            result = self._make_request_with_retry(self.github.get_user)
            user = result()

            if not user:
                raise GitHubAPIError("Failed to retrieve user information")

            self.user_login = user.login
            logger.info("Connected as GitHub user: %s", user.login)

            # Get rate limit info
            rate_limit = self.github.get_rate_limit()
            self.rate_limit_remaining = rate_limit.core.remaining  # type: ignore[attr-defined]
            self.rate_limit_reset = datetime.fromtimestamp(
                rate_limit.core.reset,  # type: ignore[attr-defined]
                tz=UTC,
            )

            return {
                "status": "success",
                "user": user.login,
                "name": user.name or "Unknown",
                "email": user.email or "Not provided",
                "rate_limit_remaining": self.rate_limit_remaining,
                "rate_limit_reset": self.rate_limit_reset.isoformat(),
            }

        except GithubException as e:
            error_msg = e.data.get("message", "Unknown error")
            logger.error("Connection validation failed: %s", error_msg)
            raise GitHubAPIError(error_msg, e.status) from e

    def fetch_starred_repos(self, per_page: int = 100) -> list[dict[str, Any]]:
        """Fetch all starred repositories for the authenticated user.

        Args:
            per_page: Number of repos per page (max 100).

        Returns:
            List of repository dictionaries with basic info.

        Raises:
            GitHubAPIError: If fetching fails.
        """
        logger.info("Fetching starred repositories")

        if not self.user_login:
            self.validate_connection()

        starred_repos = []

        try:
            user = self.github.get_user(self.user_login or "")
            starred = user.get_starred()

            total_repos = 0

            for repo in starred:
                starred_repos.append(
                    {
                        "full_name": repo.full_name,
                        "name": repo.name,
                        "owner": repo.owner.login,
                        "html_url": repo.html_url,
                        "description": repo.description,
                        "language": repo.language,
                        "stars": repo.stargazers_count,
                        "forks": repo.forks_count,
                        "updated_at": (
                            repo.updated_at.isoformat() if repo.updated_at else None
                        ),
                        "created_at": (
                            repo.created_at.isoformat() if repo.created_at else None
                        ),
                    }
                )
                total_repos += 1

                if total_repos % 50 == 0:
                    logger.debug("Fetched %d starred repositories", total_repos)

            logger.info("Successfully fetched %d starred repositories", total_repos)
            return starred_repos

        except GithubException as e:
            error_msg = e.data.get("message", "Failed to fetch starred repos")
            logger.error("Failed to fetch starred repositories: %s", error_msg)
            raise GitHubAPIError(error_msg, e.status) from e

    def fetch_repo_details(self, repo_full_name: str) -> dict[str, Any]:
        """Fetch full details for a specific repository.

        Args:
            repo_full_name: Repository full name (owner/repo).

        Returns:
            Dictionary with full repository details.

        Raises:
            GitHubAPIError: If fetching fails.
        """
        logger.debug("Fetching details for repository: %s", repo_full_name)

        try:
            result = self._make_request_with_retry(
                lambda: self.github.get_repo(repo_full_name)
            )
            repo = result()

            if not repo:
                raise GitHubAPIError(f"Repository not found: {repo_full_name}")

            return {
                "full_name": repo.full_name,
                "name": repo.name,
                "owner": repo.owner.login,
                "html_url": repo.html_url,
                "description": repo.description,
                "language": repo.language,
                "stars_count": repo.stargazers_count,
                "forks_count": repo.forks_count,
                "watchers_count": repo.watchers_count,
                "open_issues_count": repo.open_issues_count,
                "default_branch": repo.default_branch,
                "created_at": repo.created_at.isoformat() if repo.created_at else None,
                "updated_at": repo.updated_at.isoformat() if repo.updated_at else None,
                "pushed_at": repo.pushed_at.isoformat() if repo.pushed_at else None,
                "size": repo.size,
                "archived": repo.archived,
                "disabled": repo.disabled,
            }

        except GithubException as e:
            error_msg = e.data.get("message", "Failed to fetch repository details")
            logger.error("Failed to fetch repository details: %s", error_msg)
            raise GitHubAPIError(error_msg, e.status) from e

    def fetch_recent_activity(
        self, days: int = 30, per_page: int = 100
    ) -> list[dict[str, Any]]:
        """Fetch star events from the last N days.

        Args:
            days: Number of days to look back (default 30).
            per_page: Number of events per page (max 100).

        Returns:
            List of recent star event dictionaries.

        Raises:
            GitHubAPIError: If fetching fails.
        """
        logger.info("Fetching recent activity for last %d days", days)

        if not self.user_login:
            self.validate_connection()

        cutoff_date = datetime.now(UTC) - timedelta(days=days)
        recent_stars = []

        try:
            user = self.github.get_user(self.user_login or "")
            starred = user.get_starred()

            for repo in starred:
                created_at = repo.created_at
                if created_at and created_at >= cutoff_date:
                    recent_stars.append(
                        {
                            "repository_full_name": repo.full_name,
                            "repository_name": repo.name,
                            "owner": repo.owner.login,
                            "starred_at": created_at.isoformat(),
                            "stars_count": repo.stargazers_count,
                            "description": repo.description,
                            "language": repo.language,
                        }
                    )

            logger.info("Found %d stars from the last %d days", len(recent_stars), days)
            return recent_stars

        except GithubException as e:
            error_msg = e.data.get("message", "Failed to fetch recent activity")
            logger.error("Failed to fetch recent activity: %s", error_msg)
            raise GitHubAPIError(error_msg, e.status) from e

    def update_repo_from_github(
        self, repo: Repository, session: Session
    ) -> dict[str, Any]:
        """Update a repository record from GitHub API.

        Args:
            repo: Repository model instance to update.
            session: Database session.

        Returns:
            Dictionary with update results.
        """
        logger.debug("Updating repository from GitHub: %s", repo.full_name)

        try:
            details = self.fetch_repo_details(repo.full_name)  # type: ignore[arg-type]

            updated_fields = {}

            if repo.description != details["description"]:
                updated_fields["description"] = details["description"]
            if repo.stars_count != details["stars_count"]:
                updated_fields["stars_count"] = details["stars_count"]
            if repo.forks_count != details["forks_count"]:
                updated_fields["forks_count"] = details["forks_count"]
            if repo.language != details["language"]:
                updated_fields["language"] = details["language"]

            for field, new_value in updated_fields.items():
                setattr(repo, field, new_value)

            logger.info(
                "Updated repository %s: %s",
                repo.full_name,
                ", ".join(updated_fields.keys()),
            )

            session.add(repo)
            session.commit()

            return {
                "success": True,
                "repository_id": repo.id,
                "full_name": repo.full_name,
                "updated_fields": updated_fields,
            }

        except GitHubAPIError as e:
            logger.error("Failed to update repository %s: %s", repo.full_name, e)
            return {"success": False, "repository_id": repo.id, "error": str(e)}
        except Exception as e:
            logger.error(
                "Unexpected error updating repository %s: %s", repo.full_name, e
            )
            session.rollback()
            return {"success": False, "repository_id": repo.id, "error": str(e)}

    def get_rate_limit_info(self) -> dict[str, Any]:
        """Get current rate limit information.

        Returns:
            Dictionary with rate limit details.
        """
        try:
            rate_limit = self.github.get_rate_limit()
            self.rate_limit_remaining = rate_limit.core.remaining  # type: ignore[attr-defined]
            self.rate_limit_reset = datetime.fromtimestamp(
                rate_limit.core.reset,  # type: ignore[attr-defined]
                tz=UTC,
            )

            return {
                "core_remaining": self.rate_limit_remaining,
                "core_limit": rate_limit.core.limit,  # type: ignore[attr-defined]
                "core_reset": self.rate_limit_reset.isoformat(),
                "search_remaining": rate_limit.search.remaining,  # type: ignore[attr-defined]
                "graphql_remaining": rate_limit.graphql.remaining,  # type: ignore[attr-defined]
                "graphql_reset": datetime.fromtimestamp(
                    rate_limit.graphql.reset,  # type: ignore[attr-defined]
                    tz=UTC,
                ).isoformat(),
            }

        except GithubException as e:
            logger.error("Failed to get rate limit: %s", e.data.get("message"))
            return {
                "core_remaining": self.rate_limit_remaining,
                "core_reset": self.rate_limit_reset.isoformat(),
                "error": str(e),
            }
