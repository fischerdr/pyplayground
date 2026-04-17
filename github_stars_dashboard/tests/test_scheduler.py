"""Tests for ScheduledSync in scheduler.py.

This module provides comprehensive tests for the scheduled synchronization
functionality using APScheduler with random intervals.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from github_stars.config_loader import Config
from github_stars.scheduler import ScheduledSync


class TestScheduledSync:
    """Tests for ScheduledSync class."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration for testing."""
        config = MagicMock(spec=Config)
        config.sync_enabled = True
        config.sync_interval_min = 5
        config.sync_interval_max = 15
        return config

    @pytest.fixture
    def scheduled_sync(self, mock_config):
        """Create a ScheduledSync instance for testing."""
        return ScheduledSync(mock_config)

    def test_init(self, scheduled_sync, mock_config):
        """Test ScheduledSync initialization."""
        assert scheduled_sync.config == mock_config
        assert scheduled_sync.scheduler is None
        assert scheduled_sync.syncer is None
        assert scheduled_sync.job_id == "sync_starred_repos"

    def test_get_sync_interval(self, scheduled_sync, mock_config):
        """Test sync interval calculation."""
        interval = scheduled_sync._get_sync_interval()

        min_seconds = 5 * 60  # 5 minutes in seconds
        max_seconds = 15 * 60  # 15 minutes in seconds

        assert min_seconds <= interval <= max_seconds

    def test_get_sync_interval_custom_values(self, mock_config):
        """Test sync interval with custom configuration values."""
        mock_config.sync_interval_min = 10
        mock_config.sync_interval_max = 30

        scheduled_sync = ScheduledSync(mock_config)
        interval = scheduled_sync._get_sync_interval()

        min_seconds = 10 * 60
        max_seconds = 30 * 60

        assert min_seconds <= interval <= max_seconds

    def test_sync_job_success(self, scheduled_sync):
        """Test successful sync job execution."""
        mock_syncer = MagicMock()
        mock_syncer.sync_starred_repos.return_value = {
            "repositories_processed": 10,
            "new_stars": 5,
        }
        scheduled_sync.syncer = mock_syncer

        scheduled_sync._sync_job()

        mock_syncer.sync_starred_repos.assert_called_once()

    def test_sync_job_creates_syncer(self, scheduled_sync, mock_config):
        """Test that sync job creates RepoSyncer if not exists."""
        scheduled_sync.syncer = None

        with patch("github_stars.scheduler.RepoSyncer") as mock_syncer_class:
            mock_syncer_instance = MagicMock()
            mock_syncer_instance.sync_starred_repos.return_value = {
                "repositories_processed": 5,
                "new_stars": 2,
            }
            mock_syncer_class.return_value = mock_syncer_instance

            scheduled_sync._sync_job()

            mock_syncer_class.assert_called_once_with(mock_config)
            mock_syncer_instance.sync_starred_repos.assert_called_once()

    def test_sync_job_logs_error(self, scheduled_sync):
        """Test that sync job logs errors properly."""
        scheduled_sync.syncer = MagicMock()
        scheduled_sync.syncer.sync_starred_repos.side_effect = Exception("Sync failed")

        with patch("github_stars.scheduler.logger") as mock_logger:
            scheduled_sync._sync_job()

            mock_logger.error.assert_called()

    def test_start(self, scheduled_sync):
        """Test scheduler start."""
        with patch("github_stars.scheduler.AsyncIOScheduler") as mock_scheduler_class:
            mock_scheduler = MagicMock()
            mock_scheduler.running = True
            mock_scheduler_class.return_value = mock_scheduler

            scheduled_sync.start()

            mock_scheduler_class.assert_called_once()
            mock_scheduler.start.assert_called_once()
            assert scheduled_sync.scheduler == mock_scheduler
            assert scheduled_sync.scheduler.running is True

    def test_start_already_running(self, scheduled_sync):
        """Test starting scheduler that is already running."""
        mock_scheduler = MagicMock()
        mock_scheduler.running = True
        scheduled_sync.scheduler = mock_scheduler

        with patch("github_stars.scheduler.logger") as mock_logger:
            scheduled_sync.start()

            mock_logger.warning.assert_called()
            mock_scheduler.start.assert_not_called()

    def test_stop(self, scheduled_sync):
        """Test scheduler stop."""
        mock_scheduler = MagicMock()
        mock_scheduler.running = True
        scheduled_sync.scheduler = mock_scheduler

        scheduled_sync.stop()

        mock_scheduler.shutdown.assert_called_once()
        assert scheduled_sync.scheduler is None

    def test_stop_not_running(self, scheduled_sync):
        """Test stopping scheduler that is not running."""
        scheduled_sync.scheduler = None

        with patch("github_stars.scheduler.logger") as mock_logger:
            scheduled_sync.stop()

            mock_logger.info.assert_called()

    def test_is_running_true(self, scheduled_sync):
        """Test is_running returns True when scheduler is running."""
        mock_scheduler = MagicMock()
        mock_scheduler.running = True
        scheduled_sync.scheduler = mock_scheduler

        assert scheduled_sync.is_running() is True

    def test_is_running_false(self, scheduled_sync):
        """Test is_running returns False when scheduler is not running."""
        scheduled_sync.scheduler = None

        assert scheduled_sync.is_running() is False

    def test_is_running_scheduler_not_running(self, scheduled_sync):
        """Test is_running returns False when scheduler exists but not running."""
        mock_scheduler = MagicMock()
        mock_scheduler.running = False
        scheduled_sync.scheduler = mock_scheduler

        assert scheduled_sync.is_running() is False

    def test_get_next_run_with_scheduler(self, scheduled_sync):
        """Test get_next_run returns next run time."""
        mock_scheduler = MagicMock()
        mock_scheduler.running = True

        mock_job = MagicMock()
        mock_job.next_run_time = datetime.now() + timedelta(minutes=5)
        mock_scheduler.get_job.return_value = mock_job

        scheduled_sync.scheduler = mock_scheduler

        next_run = scheduled_sync.get_next_run()

        assert next_run is not None
        mock_scheduler.get_job.assert_called_once_with("sync_starred_repos")

    def test_get_next_run_no_scheduler(self, scheduled_sync):
        """Test get_next_run returns None when no scheduler."""
        scheduled_sync.scheduler = None

        next_run = scheduled_sync.get_next_run()

        assert next_run is None

    def test_get_next_run_no_job(self, scheduled_sync):
        """Test get_next_run returns None when job doesn't exist."""
        mock_scheduler = MagicMock()
        mock_scheduler.running = True
        mock_scheduler.get_job.return_value = None

        scheduled_sync.scheduler = mock_scheduler

        next_run = scheduled_sync.get_next_run()

        assert next_run is None
        mock_scheduler.get_job.assert_called_once_with("sync_starred_repos")
