"""Scheduled sync module for GitHub Stars Dashboard.

Provides automated sync functionality using APScheduler with random intervals.
"""

import random
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from github_stars.config_loader import Config
from github_stars.sync import RepoSyncer
from github_stars.utils.logging_utils import get_logger

logger = get_logger(__name__)


class ScheduledSync:
    """Manages scheduled synchronization of GitHub starred repositories.

    Uses APScheduler with random interval triggers to avoid rate limiting
    and distribute API calls evenly.

    Attributes:
        config: Application configuration instance.
        scheduler: APScheduler instance for managing jobs.
        syncer: RepoSyncer instance for executing sync operations.
        job_id: Unique identifier for the sync job.
    """

    def __init__(self, config: Config) -> None:
        """Initialize the scheduled sync manager.

        Args:
            config: Application configuration containing sync settings.
        """
        self.config = config
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.syncer: Optional[RepoSyncer] = None
        self.job_id: str = "sync_starred_repos"

        logger.info("ScheduledSync initialized with config: %s", config)

    def _get_sync_interval(self) -> int:
        """Calculate random sync interval from configuration.

        Returns:
            Random seconds value between min and max interval.
        """
        min_minutes = self.config.sync_interval_min
        max_minutes = self.config.sync_interval_max

        min_seconds = min_minutes * 60
        max_seconds = max_minutes * 60

        random_seconds = random.randint(min_seconds, max_seconds)

        logger.debug(
            "Sync interval: %d-%d minutes, selected: %d seconds",
            min_minutes,
            max_minutes,
            random_seconds,
        )

        return random_seconds

    def _sync_job(self) -> None:
        """Execute the scheduled sync job.

        This method is called by the scheduler at random intervals.
        Logs start/completion status and any errors encountered.
        """
        start_time = datetime.now()
        logger.info("Starting scheduled sync job")

        try:
            if self.syncer is None:
                self.syncer = RepoSyncer(self.config)

            result = self.syncer.sync_starred_repos()

            end_time = datetime.now()
            duration = end_time - start_time

            logger.info(
                "Scheduled sync completed: %d repos processed, %d new stars, "
                "duration: %s",
                result.get("repositories_processed", 0),
                result.get("new_stars", 0),
                duration,
            )

        except Exception as e:
            logger.error("Scheduled sync job failed: %s", str(e), exc_info=True)

    def start(self) -> None:
        """Start the scheduled sync scheduler.

        Initializes APScheduler with random interval trigger and
        starts the sync job. Logs startup confirmation.

        Raises:
            RuntimeError: If scheduler is already running.
        """
        if self.scheduler is not None:
            logger.warning("Scheduler already running")
            return

        logger.info("Starting scheduled sync scheduler")

        self.scheduler = AsyncIOScheduler()

        interval_seconds = self._get_sync_interval()

        trigger = IntervalTrigger(
            seconds=interval_seconds,
            timezone="UTC",
            jitter=random.randint(0, 60),
        )

        self.scheduler.add_job(
            self._sync_job,
            trigger,
            id=self.job_id,
            name="GitHub Stars Sync",
            replace_existing=True,
        )

        self.scheduler.start()

        logger.info(
            "Scheduled sync started with interval: %d seconds (jitter: 60s)",
            interval_seconds,
        )

    def stop(self) -> None:
        """Stop the scheduled sync scheduler.

        Shuts down the scheduler gracefully and logs shutdown confirmation.
        """
        if self.scheduler is not None:
            logger.info("Stopping scheduled sync scheduler")
            self.scheduler.shutdown()
            self.scheduler = None
            logger.info("Scheduled sync stopped")
        else:
            logger.info("Scheduled sync not running, nothing to stop")

    def is_running(self) -> bool:
        """Check if the scheduler is currently running.

        Returns:
            True if scheduler is running, False otherwise.
        """
        return self.scheduler is not None and self.scheduler.running

    def get_next_run(self) -> Optional[datetime]:
        """Get the next scheduled run time for the sync job.

        Returns:
            Next run datetime or None if scheduler is not running.
        """
        if self.scheduler is None:
            return None

        job = self.scheduler.get_job(self.job_id)
        if job is None:
            return None

        return job.next_run_time
