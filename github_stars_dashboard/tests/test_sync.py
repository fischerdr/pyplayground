"""Tests for RepoSyncer in sync.py.

This module provides comprehensive tests for the data synchronization logic
that syncs starred repositories from GitHub to the local database.
"""

import json
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from github_stars.fetcher import GitHubAPIError, GitHubClient
from github_stars.models import ActivityLog, Repository, Star
from github_stars.sync import RepoSyncer, SyncStats, sync_starred_repos


class TestSyncStats:
    """Tests for SyncStats dataclass."""

    def test_init_default_values(self):
        """Test SyncStats initialization with default values."""
        stats = SyncStats()

        assert stats.total_starred == 0
        assert stats.new_repos == 0
        assert stats.updated_repos == 0
        assert stats.inactive_repos == 0
        assert stats.new_stars == 0
        assert stats.skipped_repos == 0
        assert stats.errors == 0
        assert stats.duration_seconds == 0.0

    def test_init_with_values(self):
        """Test SyncStats initialization with custom values."""
        stats = SyncStats(
            total_starred=10,
            new_repos=3,
            updated_repos=5,
            inactive_repos=2,
            new_stars=4,
            skipped_repos=1,
            errors=0,
            duration_seconds=1.5,
        )

        assert stats.total_starred == 10
        assert stats.new_repos == 3
        assert stats.updated_repos == 5
        assert stats.inactive_repos == 2
        assert stats.new_stars == 4
        assert stats.skipped_repos == 1
        assert stats.errors == 0
        assert stats.duration_seconds == 1.5

    def test_to_dict(self):
        """Test SyncStats to_dict method."""
        stats = SyncStats(
            total_starred=10,
            new_repos=3,
            updated_repos=5,
            inactive_repos=2,
            new_stars=4,
            skipped_repos=1,
            errors=0,
            duration_seconds=1.5,
        )

        result = stats.to_dict()

        assert isinstance(result, dict)
        assert result["total_starred"] == 10
        assert result["new_repos"] == 3
        assert result["updated_repos"] == 5
        assert result["inactive_repos"] == 2
        assert result["new_stars"] == 4
        assert result["skipped_repos"] == 1
        assert result["errors"] == 0
        assert result["duration_seconds"] == 1.5


class TestRepoSyncerInit:
    """Tests for RepoSyncer initialization."""

    def test_init(self):
        """Test RepoSyncer initialization."""
        mock_client = MagicMock(spec=GitHubClient)
        mock_session = MagicMock(spec=Session)

        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
            categories_config_path="/path/to/config.json",
        )

        assert syncer.github_client == mock_client
        assert syncer.session == mock_session
        assert syncer.categories_config_path == "/path/to/config.json"
        assert isinstance(syncer.stats, SyncStats)
        assert syncer._existing_repo_names == set()

    def test_init_without_categories_config(self):
        """Test RepoSyncer initialization without categories config."""
        mock_client = MagicMock(spec=GitHubClient)
        mock_session = MagicMock(spec=Session)

        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        assert syncer.categories_config_path is None


class TestRepoSyncerLogActivity:
    """Tests for RepoSyncer._log_activity method."""

    def test_log_activity_with_repository(self, mock_session):
        """Test logging activity with repository."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_repository = MagicMock(spec=Repository)
        mock_repository.id = 123

        syncer._log_activity(
            action="create",
            details={"full_name": "owner/repo", "stars": 100},
            repository=mock_repository,
        )

        # Verify activity log was added to session
        assert mock_session.add.call_count == 1
        activity_log = mock_session.add.call_args[0][0]
        assert isinstance(activity_log, ActivityLog)
        assert activity_log.action == "create"
        details = json.loads(activity_log.details)
        assert details["full_name"] == "owner/repo"
        assert details["stars"] == 100
        assert details["repository_id"] == 123

    def test_log_activity_without_repository(self, mock_session):
        """Test logging activity without repository."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        syncer._log_activity(
            action="update",
            details={"stars_changed": 150},
        )

        # Verify activity log was added to session
        assert mock_session.add.call_count == 1
        activity_log = mock_session.add.call_args[0][0]
        assert isinstance(activity_log, ActivityLog)
        assert activity_log.action == "update"
        details = json.loads(activity_log.details)
        assert details["stars_changed"] == 150
        assert "repository_id" not in details

    def test_log_activity_exception(self, mock_session, caplog):
        """Test logging activity with exception."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        # Make session.add raise an exception
        mock_session.add.side_effect = Exception("Database error")

        syncer._log_activity(
            action="create",
            details={"full_name": "owner/repo"},
        )

        # Verify error was logged
        assert "Failed to log activity" in caplog.text


class TestRepoSyncerGetOrCreateRepository:
    """Tests for RepoSyncer._get_or_create_repository method."""

    def test_get_existing_repository(self, mock_session):
        """Test getting an existing repository."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_repository = MagicMock(spec=Repository)
        mock_repository.id = 123
        mock_repository.full_name = "owner/existing"

        mock_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_repository
        )

        repo_data = {
            "full_name": "owner/existing",
            "html_url": "https://github.com/owner/existing",
            "description": "Existing repo",
            "stars": 100,
            "language": "Python",
        }

        repository, is_new = syncer._get_or_create_repository(repo_data)

        assert repository == mock_repository
        assert is_new is False
        mock_session.query.assert_called_once()
        mock_session.add.assert_not_called()

    def test_create_new_repository(self, mock_session):
        """Test creating a new repository."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        repo_data = {
            "full_name": "owner/new",
            "html_url": "https://github.com/owner/new",
            "description": "New repo description",
            "stars": 50,
            "forks": 5,
            "language": "JavaScript",
        }

        repository, is_new = syncer._get_or_create_repository(repo_data)

        assert is_new is True
        assert repository.full_name == "owner/new"
        assert repository.description == "New repo description"
        assert repository.stars_count == 50
        assert repository.forks_count == 5
        assert repository.language == "JavaScript"
        assert repository.is_active is True
        mock_session.add.assert_called_once()
        assert "owner/new" in syncer._existing_repo_names

    def test_create_repository_with_alternative_field_names(self, mock_session):
        """Test creating repository with alternative field names."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        # Test with stars_count instead of stars
        repo_data = {
            "full_name": "owner/repo",
            "stars_count": 75,
            "forks_count": 10,
        }

        repository, is_new = syncer._get_or_create_repository(repo_data)

        assert repository.stars_count == 75
        assert repository.forks_count == 10

    def test_create_repository_without_html_url(self, mock_session):
        """Test creating repository without html_url."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        repo_data = {
            "full_name": "owner/repo",
        }

        repository, is_new = syncer._get_or_create_repository(repo_data)

        # Should use default URL format
        assert repository.html_url == "https://github.com/owner/repo"


class TestRepoSyncerCreateStarRecord:
    """Tests for RepoSyncer._create_star_record method."""

    def test_create_new_star_record(self, mock_session):
        """Test creating a new star record."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_repository = MagicMock(spec=Repository)
        mock_repository.id = 123
        mock_repository.full_name = "owner/repo"

        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        starred_at = datetime.now(UTC) - timedelta(days=5)

        star = syncer._create_star_record(
            repository=mock_repository,
            starred_at=starred_at,
            is_new=True,
        )

        assert star is not None
        assert star.repository_id == 123
        assert star.starred_at == starred_at
        assert star.is_new is True
        assert syncer.stats.new_stars == 1
        mock_session.add.assert_called_once()

    def test_create_star_record_duplicate(self, mock_session):
        """Test creating a star record that already exists."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_repository = MagicMock(spec=Repository)
        mock_repository.id = 123

        # Return existing star
        mock_existing_star = MagicMock(spec=Star)
        mock_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_existing_star
        )

        star = syncer._create_star_record(
            repository=mock_repository,
            is_new=True,
        )

        assert star is None
        assert syncer.stats.new_stars == 0
        mock_session.add.assert_not_called()

    def test_create_star_record_without_starred_at(self, mock_session):
        """Test creating star record without explicit starred_at."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_repository = MagicMock(spec=Repository)
        mock_repository.id = 123
        mock_repository.full_name = "owner/repo"

        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        star = syncer._create_star_record(
            repository=mock_repository,
            is_new=True,
        )

        assert star is not None
        # Should use current time with UTC
        assert star.starred_at.tzinfo == UTC


class TestRepoSyncerUpdateRepositoryData:
    """Tests for RepoSyncer._update_repository_data method."""

    def test_update_repository_description_changed(self, mock_session):
        """Test updating repository when description changed."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        # Create a simple class to track attribute changes
        class MockRepository:
            def __init__(self):
                self.id = 123
                self.full_name = "owner/repo"
                self.description = "Old description"
                self.stars_count = 100
                self.forks_count = 10
                self.language = "Python"

        mock_repository = MockRepository()

        repo_data = {
            "description": "New description",
            "stars_count": 150,
            "forks_count": 15,
            "language": "JavaScript",
        }

        updated = syncer._update_repository_data(mock_repository, repo_data)

        assert updated is True
        # Verify attributes were updated
        assert mock_repository.description == "New description"
        assert mock_repository.stars_count == 150
        assert mock_repository.forks_count == 15
        assert mock_repository.language == "JavaScript"
        assert syncer.stats.updated_repos == 1

    def test_update_repository_no_changes(self, mock_session):
        """Test updating repository with no changes."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_repository = MagicMock(spec=Repository)
        mock_repository.id = 123
        mock_repository.full_name = "owner/repo"
        mock_repository.description = "Same description"
        mock_repository.stars_count = 100
        mock_repository.forks_count = 10
        mock_repository.language = "Python"

        repo_data = {
            "description": "Same description",
            "stars": 100,
            "forks": 10,
            "language": "Python",
        }

        updated = syncer._update_repository_data(mock_repository, repo_data)

        assert updated is False
        assert syncer.stats.updated_repos == 0

    def test_update_repository_with_none_values(self, mock_session):
        """Test updating repository with None values."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_repository = MagicMock(spec=Repository)
        mock_repository.id = 123
        mock_repository.full_name = "owner/repo"
        mock_repository.description = "Description"
        mock_repository.stars_count = 100
        mock_repository.forks_count = 10
        mock_repository.language = "Python"

        repo_data = {
            "description": None,
            "stars": None,
            "forks": None,
            "language": None,
        }

        updated = syncer._update_repository_data(mock_repository, repo_data)

        assert updated is False
        # Verify attributes were not changed
        assert mock_repository.description == "Description"
        assert mock_repository.stars_count == 100
        assert mock_repository.forks_count == 10
        assert mock_repository.language == "Python"


class TestRepoSyncerMarkInactiveRepos:
    """Tests for RepoSyncer._mark_inactive_repos method."""

    def test_mark_inactive_repos(self, mock_session):
        """Test marking repositories as inactive."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_repo1 = MagicMock(spec=Repository)
        mock_repo1.id = 123
        mock_repo1.full_name = "owner/active1"
        mock_repo1.is_active = True

        mock_repo2 = MagicMock(spec=Repository)
        mock_repo2.id = 456
        mock_repo2.full_name = "owner/active2"
        mock_repo2.is_active = True

        mock_session.query.return_value.filter.return_value.all.return_value = [
            mock_repo1,
            mock_repo2,
        ]

        starred_names = {"owner/active1", "owner/newrepo"}

        syncer._mark_inactive_repos(starred_names)

        assert mock_repo1.is_active is False
        assert mock_repo2.is_active is False
        assert syncer.stats.inactive_repos == 2
        # session.add is called for each inactive repo + activity logs
        assert mock_session.add.call_count >= 2
        # _log_activity is called twice (once per inactive repo)
        # We can verify this by checking the call count on the session.add
        # since each call to _log_activity adds an ActivityLog

    def test_mark_inactive_repos_no_inactive(self, mock_session):
        """Test marking inactive repos when all are in star list."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_session.query.return_value.filter.return_value.all.return_value = []

        starred_names = {"owner/repo1", "owner/repo2"}

        syncer._mark_inactive_repos(starred_names)

        assert syncer.stats.inactive_repos == 0
        mock_session.add.assert_not_called()


class TestRepoSyncerSyncStarredRepos:
    """Tests for RepoSyncer.sync_starred_repos method."""

    def test_sync_starred_repos_success(self, mock_session, caplog):
        """Test successful sync of starred repositories."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        # Mock GitHub client to return starred repos
        mock_repo_data = [
            {
                "full_name": "owner/repo1",
                "html_url": "https://github.com/owner/repo1",
                "description": "Repo 1",
                "stars": 100,
                "forks": 10,
                "language": "Python",
                "created_at": (datetime.now(UTC) - timedelta(days=10)).isoformat(),
            },
            {
                "full_name": "owner/repo2",
                "html_url": "https://github.com/owner/repo2",
                "description": "Repo 2",
                "stars": 50,
                "forks": 5,
                "language": "JavaScript",
                "created_at": (datetime.now(UTC) - timedelta(days=5)).isoformat(),
            },
        ]
        mock_client.fetch_starred_repos.return_value = mock_repo_data

        # Mock repository query to return None (new repos)
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("github_stars.sync.update_repository_category"):
            stats = syncer.sync_starred_repos()

        assert stats.total_starred == 2
        assert stats.new_repos == 2
        assert stats.updated_repos == 0
        assert stats.inactive_repos == 0
        assert stats.new_stars == 2  # Both created within 30 days
        assert stats.errors == 0
        assert stats.duration_seconds > 0
        mock_session.commit.assert_called_once()

    def test_sync_starred_repos_empty_list(self, mock_session, caplog):
        """Test sync with empty starred repos list."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_client.fetch_starred_repos.return_value = []

        stats = syncer.sync_starred_repos()

        assert stats.total_starred == 0
        assert stats.new_repos == 0
        assert stats.errors == 0

    def test_sync_starred_repos_github_api_error(self, mock_session, caplog):
        """Test sync with GitHub API error."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_client.fetch_starred_repos.side_effect = GitHubAPIError(
            "Rate limit exceeded", status=403
        )

        stats = syncer.sync_starred_repos()

        assert stats.errors == 1
        mock_session.rollback.assert_called_once()

    def test_sync_starred_repos_general_error(self, mock_session, caplog):
        """Test sync with general error."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_client.fetch_starred_repos.side_effect = Exception("Unexpected error")

        stats = syncer.sync_starred_repos()

        assert stats.errors == 1
        mock_session.rollback.assert_called_once()

    def test_sync_starred_repos_mixed_new_and_existing(self, mock_session, caplog):
        """Test sync with mix of new and existing repositories."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_repo_data = [
            {
                "full_name": "owner/newrepo",
                "html_url": "https://github.com/owner/newrepo",
                "description": "New repo",
                "stars": 100,
                "language": "Python",
                "created_at": (datetime.now(UTC) - timedelta(days=5)).isoformat(),
            },
            {
                "full_name": "owner/existing",
                "html_url": "https://github.com/owner/existing",
                "description": "Existing repo",
                "stars": 50,
                "language": "JavaScript",
                "created_at": (datetime.now(UTC) - timedelta(days=60)).isoformat(),
            },
        ]
        mock_client.fetch_starred_repos.return_value = mock_repo_data

        # Track calls to _get_or_create_repository
        call_count = [0]

        def get_or_create_side_effect(repo_data):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: new repo
                mock_new_repo = MagicMock(spec=Repository)
                mock_new_repo.id = 999
                mock_new_repo.full_name = "owner/newrepo"
                return mock_new_repo, True
            else:
                # Second call: existing repo
                mock_existing_repo = MagicMock(spec=Repository)
                mock_existing_repo.id = 123
                mock_existing_repo.full_name = "owner/existing"
                mock_existing_repo.description = "Old description"
                mock_existing_repo.stars_count = 40
                mock_existing_repo.language = "TypeScript"
                return mock_existing_repo, False

        with patch.object(
            syncer, "_get_or_create_repository", side_effect=get_or_create_side_effect
        ):
            with patch("github_stars.sync.update_repository_category"):
                stats = syncer.sync_starred_repos()

        assert stats.total_starred == 2
        assert stats.new_repos == 1
        assert stats.updated_repos == 1
        assert stats.new_stars == 1  # Only newrepo within 30 days

    def test_sync_starred_repos_error_during_processing(self, mock_session, caplog):
        """Test sync with error during processing of individual repos."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_repo_data = [
            {
                "full_name": "owner/repo1",
                "html_url": "https://github.com/owner/repo1",
                "description": "Repo 1",
                "stars": 100,
                "language": "Python",
            },
            {
                "full_name": "owner/repo2",
                # Missing required fields
                "html_url": "https://github.com/owner/repo2",
            },
            {
                "full_name": "owner/repo3",
                "html_url": "https://github.com/owner/repo3",
                "description": "Repo 3",
                "stars": 50,
                "language": "JavaScript",
            },
        ]
        mock_client.fetch_starred_repos.return_value = mock_repo_data

        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("github_stars.sync.update_repository_category"):
            stats = syncer.sync_starred_repos()

        assert stats.total_starred == 3
        # Errors will be counted for repos that fail processing

    def test_sync_starred_repos_invalid_date_format(self, mock_session, caplog):
        """Test sync with invalid date format."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_repo_data = [
            {
                "full_name": "owner/repo",
                "html_url": "https://github.com/owner/repo",
                "created_at": "invalid-date-format",
            },
        ]
        mock_client.fetch_starred_repos.return_value = mock_repo_data

        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("github_stars.sync.update_repository_category"):
            stats = syncer.sync_starred_repos()

        assert stats.total_starred == 1
        # Should handle invalid date gracefully

    def test_sync_starred_repos_mark_inactive(self, mock_session, caplog):
        """Test sync marks inactive repos correctly."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_repo_data = [
            {
                "full_name": "owner/newrepo",
                "html_url": "https://github.com/owner/newrepo",
                "stars": 100,
                "language": "Python",
                "created_at": (datetime.now(UTC) - timedelta(days=5)).isoformat(),
            },
        ]
        mock_client.fetch_starred_repos.return_value = mock_repo_data

        mock_existing_repo = MagicMock(spec=Repository)
        mock_existing_repo.id = 123
        mock_existing_repo.full_name = "owner/oldrepo"
        mock_existing_repo.is_active = True

        mock_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_existing_repo
        )

        mock_inactive_repos = [MagicMock(spec=Repository)]
        mock_inactive_repos[0].full_name = "owner/oldrepo"
        mock_inactive_repos[0].is_active = True
        mock_session.query.return_value.filter.return_value.all.return_value = (
            mock_inactive_repos
        )

        with patch("github_stars.sync.update_repository_category"):
            stats = syncer.sync_starred_repos()

        assert stats.inactive_repos == 1
        assert mock_session.commit.called

    def test_sync_starred_repos_category_update_failure(self, mock_session, caplog):
        """Test sync handles category update failure gracefully."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_repo_data = [
            {
                "full_name": "owner/repo",
                "html_url": "https://github.com/owner/repo",
                "stars": 100,
                "language": "Python",
                "created_at": (datetime.now(UTC) - timedelta(days=5)).isoformat(),
            },
        ]
        mock_client.fetch_starred_repos.return_value = mock_repo_data

        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        # Mock categorizer to raise exception
        with patch(
            "github_stars.sync.update_repository_category",
            side_effect=Exception("Category error"),
        ):
            stats = syncer.sync_starred_repos()

        # Should still complete with error logged
        assert stats.total_starred == 1


class TestSyncStarredReposConvenienceFunction:
    """Tests for sync_starred_repos convenience function."""

    @patch("github_stars.database.get_db_session")
    @patch("github_stars.fetcher.GitHubClient")
    @patch("github_stars.sync.RepoSyncer")
    def test_sync_starred_repos_function_success(
        self, mock_syncer_class, mock_client_class, mock_get_session
    ):
        """Test sync_starred_repos function success."""
        mock_session = MagicMock(spec=Session)
        mock_get_session.return_value = mock_session

        mock_client = MagicMock(spec=GitHubClient)
        mock_client_class.return_value = mock_client

        mock_syncer = MagicMock(spec=RepoSyncer)
        mock_stats = SyncStats(total_starred=5, new_repos=3, errors=0)
        mock_syncer.sync_starred_repos.return_value = mock_stats
        mock_syncer_class.return_value = mock_syncer

        stats = sync_starred_repos(
            github_token="test_token",
            user_login="test_user",
            database_url="sqlite:///test.db",
            categories_config_path="/path/to/config.json",
        )

        assert stats.total_starred == 5
        assert stats.new_repos == 3
        assert stats.errors == 0
        mock_get_session.assert_called_once()
        mock_client_class.assert_called_once()
        mock_syncer_class.assert_called_once()
        mock_session.close.assert_called_once()

    @patch("github_stars.database.get_db_session")
    @patch("github_stars.fetcher.GitHubClient")
    @patch("github_stars.sync.RepoSyncer")
    def test_sync_starred_repos_function_with_optional_params(
        self, mock_syncer_class, mock_client_class, mock_get_session
    ):
        """Test sync_starred_repos function with optional parameters."""
        mock_session = MagicMock(spec=Session)
        mock_get_session.return_value = mock_session

        mock_client = MagicMock(spec=GitHubClient)
        mock_client_class.return_value = mock_client

        mock_syncer = MagicMock(spec=RepoSyncer)
        mock_syncer.sync_starred_repos.return_value = SyncStats()
        mock_syncer_class.return_value = mock_syncer

        stats = sync_starred_repos(github_token="test_token")

        assert stats is not None
        mock_client_class.assert_called_once_with(token="test_token", user_login=None)
        mock_syncer_class.assert_called_once()
        mock_session.close.assert_called_once()

    @patch("github_stars.database.get_db_session")
    @patch("github_stars.fetcher.GitHubClient")
    @patch("github_stars.sync.RepoSyncer")
    def test_sync_starred_repos_function_exception(
        self, mock_syncer_class, mock_client_class, mock_get_session
    ):
        """Test sync_starred_repos function handles exceptions."""
        mock_session = MagicMock(spec=Session)
        mock_get_session.return_value = mock_session

        mock_client = MagicMock(spec=GitHubClient)
        mock_client_class.return_value = mock_client

        mock_syncer = MagicMock(spec=RepoSyncer)
        mock_syncer.sync_starred_repos.side_effect = Exception("Sync failed")
        mock_syncer_class.return_value = mock_syncer

        with pytest.raises(Exception):
            sync_starred_repos(github_token="test_token")

        # Session should still be closed in finally block
        mock_session.close.assert_called_once()


class TestRepoSyncerEdgeCases:
    """Tests for edge cases in RepoSyncer."""

    def test_get_or_create_repository_special_characters(self, mock_session):
        """Test repository creation with special characters in name."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        repo_data = {
            "full_name": "owner/repo-with_special.chars",
            "html_url": "https://github.com/owner/repo",
        }

        repository, is_new = syncer._get_or_create_repository(repo_data)

        assert is_new is True
        assert repository.full_name == "owner/repo-with_special.chars"

    def test_get_or_create_repository_unicode_name(self, mock_session):
        """Test repository creation with unicode characters."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        repo_data = {
            "full_name": "测试/仓库",
            "html_url": "https://github.com/测试/仓库",
        }

        repository, is_new = syncer._get_or_create_repository(repo_data)

        assert is_new is True
        assert repository.full_name == "测试/仓库"

    def test_sync_with_very_long_description(self, mock_session, caplog):
        """Test sync with very long repository description."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        long_description = "This is a " * 1000

        mock_repo_data = [
            {
                "full_name": "owner/repo",
                "html_url": "https://github.com/owner/repo",
                "description": long_description,
                "stars": 100,
                "language": "Python",
                "created_at": (datetime.now(UTC) - timedelta(days=5)).isoformat(),
            },
        ]
        mock_client.fetch_starred_repos.return_value = mock_repo_data
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("github_stars.sync.update_repository_category"):
            stats = syncer.sync_starred_repos()

        assert stats.total_starred == 1
        assert stats.new_repos == 1

    def test_star_record_not_created_for_old_repos(self, mock_session, caplog):
        """Test that star records are not created for repos older than 30 days."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        # Repo created 60 days ago
        mock_repo_data = [
            {
                "full_name": "owner/oldrepo",
                "html_url": "https://github.com/owner/oldrepo",
                "stars": 100,
                "language": "Python",
                "created_at": (datetime.now(UTC) - timedelta(days=60)).isoformat(),
            },
        ]
        mock_client.fetch_starred_repos.return_value = mock_repo_data
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("github_stars.sync.update_repository_category"):
            stats = syncer.sync_starred_repos()

        assert stats.total_starred == 1
        assert stats.new_repos == 1
        assert stats.new_stars == 0  # No star record for old repo

    def test_sync_resets_stats_at_start(self, mock_session):
        """Test that sync resets stats at the beginning."""
        mock_client = MagicMock(spec=GitHubClient)
        syncer = RepoSyncer(
            github_client=mock_client,
            session=mock_session,
        )

        # Set some initial stats
        syncer.stats = SyncStats(total_starred=10, errors=5)

        mock_client.fetch_starred_repos.return_value = []

        stats = syncer.sync_starred_repos()

        # Stats should be reset
        assert stats.total_starred == 0
        assert stats.errors == 0


# Fixtures
@pytest.fixture
def mock_session():
    """Create a mocked database session."""
    session = MagicMock(spec=Session)
    session.query.return_value.filter_by.return_value.first.return_value = None
    session.query.return_value.filter.return_value.all.return_value = []
    return session
