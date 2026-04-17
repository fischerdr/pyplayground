"""Tests for GitHubClient in fetcher.py."""

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from github import GithubException

from github_stars.fetcher import (
    GitHubAPIError,
    GitHubClient,
    GitHubRateLimitExceeded,
)


class TestGitHubClient:
    """Tests for GitHubClient class."""

    def test_init(self):
        """Test GitHubClient initialization."""
        client = GitHubClient(token="test_token", user_login="test_user")

        assert client.user_login == "test_user"
        assert client.rate_limit_remaining == 5000
        assert isinstance(client.rate_limit_reset, datetime)
        assert client._last_request_time == 0.0

    def test_init_default_user_login(self):
        """Test GitHubClient initialization without user_login."""
        client = GitHubClient(token="test_token")

        assert client.user_login is None

    def test_enforce_rate_limit(self):
        """Test rate limiting enforcement."""
        client = GitHubClient(token="test_token", user_login="test_user")
        client._request_delay = 0.1

        start_time = time.time()
        client._enforce_rate_limit()
        elapsed = time.time() - start_time

        assert elapsed >= 0.09  # Should have waited at least 90ms

    def test_enforce_rate_limit_no_delay(self):
        """Test rate limiting when no delay is needed."""
        client = GitHubClient(token="test_token", user_login="test_user")
        client._last_request_time = time.time() - 1.0  # 1 second ago

        start_time = time.time()
        client._enforce_rate_limit()
        elapsed = time.time() - start_time

        assert elapsed < 0.01  # Should be almost instant

    @patch("github_stars.fetcher.Github")
    def test_validate_connection_success(self, mock_github):
        """Test successful connection validation."""
        mock_user = MagicMock()
        mock_user.login = "test_user"
        mock_user.name = "Test User"
        mock_user.email = "test@example.com"
        mock_github.return_value.get_user.return_value = mock_user

        mock_rate_limit = MagicMock()
        mock_rate_limit.core.remaining = 4999
        mock_rate_limit.core.reset = int(
            (datetime.now(UTC) + timedelta(hours=1)).timestamp()
        )
        mock_github.return_value.get_rate_limit.return_value = mock_rate_limit

        client = GitHubClient(token="test_token", user_login="test_user")

        result = client.validate_connection()

        assert result["status"] == "success"
        assert result["user"] == "test_user"
        assert result["name"] == "Test User"
        assert result["email"] == "test@example.com"
        assert client.user_login == "test_user"

    @patch("github_stars.fetcher.Github")
    def test_validate_connection_github_exception(self, mock_github):
        """Test connection validation with GitHubException."""
        mock_github.return_value.get_user.side_effect = GithubException(
            401, "Unauthorized"
        )

        client = GitHubClient(token="test_token", user_login="test_user")

        with pytest.raises(GitHubAPIError) as exc_info:
            client.validate_connection()

        assert exc_info.value.status == 401

    @patch("github_stars.fetcher.Github")
    def test_fetch_starred_repos_success(self, mock_github):
        """Test successful fetching of starred repos."""
        mock_user = MagicMock()
        mock_repo1 = MagicMock()
        mock_repo1.full_name = "owner/repo1"
        mock_repo1.name = "repo1"
        mock_repo1.owner.login = "owner"
        mock_repo1.html_url = "https://github.com/owner/repo1"
        mock_repo1.description = "Test repo 1"
        mock_repo1.language = "Python"
        mock_repo1.stargazers_count = 100
        mock_repo1.forks_count = 10
        mock_repo1.updated_at = datetime.now(UTC)
        mock_repo1.created_at = datetime.now(UTC)

        mock_repo2 = MagicMock()
        mock_repo2.full_name = "owner/repo2"
        mock_repo2.name = "repo2"
        mock_repo2.owner.login = "owner"
        mock_repo2.html_url = "https://github.com/owner/repo2"
        mock_repo2.description = "Test repo 2"
        mock_repo2.language = "JavaScript"
        mock_repo2.stargazers_count = 50
        mock_repo2.forks_count = 5
        mock_repo2.updated_at = datetime.now(UTC)
        mock_repo2.created_at = datetime.now(UTC)

        mock_user.get_starred.return_value = [mock_repo1, mock_repo2]
        mock_github.return_value.get_user.return_value = mock_user

        client = GitHubClient(token="test_token", user_login="owner")

        result = client.fetch_starred_repos()

        assert len(result) == 2
        assert result[0]["full_name"] == "owner/repo1"
        assert result[1]["full_name"] == "owner/repo2"
        assert result[0]["stars"] == 100
        assert result[1]["stars"] == 50

    @patch("github_stars.fetcher.Github")
    def test_fetch_starred_repos_with_none_dates(self, mock_github):
        """Test fetching starred repos with None dates."""
        mock_user = MagicMock()
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.name = "repo"
        mock_repo.owner.login = "owner"
        mock_repo.html_url = "https://github.com/owner/repo"
        mock_repo.description = None
        mock_repo.language = None
        mock_repo.stargazers_count = 0
        mock_repo.forks_count = 0
        mock_repo.updated_at = None
        mock_repo.created_at = None

        mock_user.get_starred.return_value = [mock_repo]
        mock_github.return_value.get_user.return_value = mock_user

        client = GitHubClient(token="test_token", user_login="owner")

        result = client.fetch_starred_repos()

        assert len(result) == 1
        assert result[0]["description"] is None
        assert result[0]["updated_at"] is None

    @patch("github_stars.fetcher.Github")
    def test_fetch_repo_details_success(self, mock_github):
        """Test successful fetching of repo details."""
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.name = "repo"
        mock_repo.owner.login = "owner"
        mock_repo.html_url = "https://github.com/owner/repo"
        mock_repo.description = "Test repo"
        mock_repo.language = "Python"
        mock_repo.stargazers_count = 100
        mock_repo.forks_count = 10
        mock_repo.watchers_count = 20
        mock_repo.open_issues_count = 5
        mock_repo.default_branch = "main"
        mock_repo.created_at = datetime.now(UTC)
        mock_repo.updated_at = datetime.now(UTC)
        mock_repo.pushed_at = datetime.now(UTC)
        mock_repo.size = 1000
        mock_repo.archived = False
        mock_repo.disabled = False

        mock_github.return_value.get_repo.return_value = mock_repo

        client = GitHubClient(token="test_token", user_login="owner")

        result = client.fetch_repo_details("owner/repo")

        assert result["full_name"] == "owner/repo"
        assert result["stars_count"] == 100
        assert result["forks_count"] == 10
        assert result["archived"] is False

    @patch("github_stars.fetcher.Github")
    def test_fetch_recent_activity_success(self, mock_github):
        """Test successful fetching of recent activity."""
        mock_user = MagicMock()
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.name = "repo"
        mock_repo.owner.login = "owner"
        mock_repo.stargazers_count = 100
        mock_repo.description = "Test repo"
        mock_repo.language = "Python"
        mock_repo.created_at = datetime.now(UTC) - timedelta(days=5)

        mock_user.get_starred.return_value = [mock_repo]
        mock_github.return_value.get_user.return_value = mock_user

        client = GitHubClient(token="test_token", user_login="owner")

        result = client.fetch_recent_activity(days=30)

        assert len(result) == 1
        assert result[0]["repository_full_name"] == "owner/repo"
        assert result[0]["stars_count"] == 100

    @patch("github_stars.fetcher.Github")
    def test_fetch_recent_activity_no_recent_stars(self, mock_github):
        """Test fetching recent activity with no recent stars."""
        mock_user = MagicMock()
        mock_repo = MagicMock()
        mock_repo.full_name = "owner/repo"
        mock_repo.name = "repo"
        mock_repo.owner.login = "owner"
        mock_repo.created_at = datetime.now(UTC) - timedelta(days=60)

        mock_user.get_starred.return_value = [mock_repo]
        mock_github.return_value.get_user.return_value = mock_user

        client = GitHubClient(token="test_token", user_login="owner")

        result = client.fetch_recent_activity(days=30)

        assert len(result) == 0

    @patch("github_stars.fetcher.Github")
    def test_get_rate_limit_info_success(self, mock_github):
        """Test successful rate limit info retrieval."""
        mock_rate_limit = MagicMock()
        mock_rate_limit.core.remaining = 4999
        mock_rate_limit.core.limit = 5000
        mock_rate_limit.core.reset = int(
            (datetime.now(UTC) + timedelta(hours=1)).timestamp()
        )
        mock_rate_limit.search.remaining = 30
        mock_rate_limit.graphql.remaining = 5000
        mock_rate_limit.graphql.reset = int(
            (datetime.now(UTC) + timedelta(hours=1)).timestamp()
        )

        mock_github.return_value.get_rate_limit.return_value = mock_rate_limit

        client = GitHubClient(token="test_token", user_login="test_user")

        result = client.get_rate_limit_info()

        assert result["core_remaining"] == 4999
        assert result["core_limit"] == 5000
        assert "core_reset" in result
        assert result["search_remaining"] == 30
        assert result["graphql_remaining"] == 5000

    @patch("github_stars.fetcher.Github")
    def test_get_rate_limit_info_exception(self, mock_github):
        """Test rate limit info retrieval with exception."""
        mock_github.return_value.get_rate_limit.side_effect = GithubException(
            403, "Rate limit exceeded"
        )

        client = GitHubClient(token="test_token", user_login="test_user")

        result = client.get_rate_limit_info()

        assert "error" in result
        assert result["core_remaining"] == 5000  # Default value


class TestGitHubAPIError:
    """Tests for GitHubAPIError exception."""

    def test_init_with_status(self):
        """Test GitHubAPIError initialization with status."""
        error = GitHubAPIError("Test error", status=404)

        assert str(error) == "Test error"
        assert error.status == 404

    def test_init_without_status(self):
        """Test GitHubAPIError initialization without status."""
        error = GitHubAPIError("Test error")

        assert str(error) == "Test error"
        assert error.status is None


class TestGitHubRateLimitExceeded:
    """Tests for GitHubRateLimitExceeded exception."""

    def test_init(self):
        """Test GitHubRateLimitExceeded initialization."""
        error = GitHubRateLimitExceeded("Rate limit exceeded")

        assert str(error) == "Rate limit exceeded"
        assert isinstance(error, GitHubAPIError)
