"""Scheduler runner module for standalone scheduler execution.

This module provides a CLI entry point for running the scheduler
as a standalone service in Docker containers.
"""

import asyncio
import signal
import sys
import threading
from typing import Optional

from github_stars.config_loader import Config, load_config
from github_stars.scheduler import ScheduledSync
from github_stars.utils.logging_utils import get_logger

logger = get_logger(__name__)


class SchedulerRunner:
    """Runs the scheduled sync scheduler in a separate thread.

    Attributes:
        config: Application configuration instance.
        scheduler: ScheduledSync instance for managing jobs.
        thread: Background thread running the scheduler.
        stop_event: Event to signal shutdown.
    """

    def __init__(self, config: Config) -> None:
        """Initialize the scheduler runner.

        Args:
            config: Application configuration containing sync settings.
        """
        self.config = config
        self.scheduler: Optional[ScheduledSync] = None
        self.thread: Optional[threading.Thread] = None
        self.stop_event: Optional[asyncio.Event] = None

    def _run_scheduler_sync(self) -> None:
        """Run the scheduler synchronously in a background thread.

        This method is called by the background thread and blocks
        until the scheduler is stopped.
        """
        logger.info("Starting scheduler in background thread")

        try:
            self.scheduler = ScheduledSync(self.config)

            if not self.config.sync_enabled:
                logger.warning("Sync is disabled, scheduler will not start jobs")

            self.scheduler.start()
            logger.info("Scheduler running in background thread")

            while self.stop_event is None or not self.stop_event.is_set():
                asyncio.get_event_loop().run_until_complete(asyncio.sleep(1))

            if self.scheduler is not None and self.scheduler.is_running():
                self.scheduler.stop()

            logger.info("Scheduler stopped gracefully from background thread")

        except Exception as e:
            logger.error("Scheduler thread failed: %s", str(e), exc_info=True)

    async def run(self) -> int:
        """Run the scheduler asynchronously with signal handling.

        Returns:
            Exit code (0 for success, 1 for errors).
        """
        logger.info("Starting GitHub Stars scheduler service")

        try:
            config = load_config()

            runner = SchedulerRunner(config)
            self.stop_event = asyncio.Event()

            def handle_signal() -> None:
                logger.info("Received shutdown signal")
                if self.stop_event is not None:
                    self.stop_event.set()

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, handle_signal)

            self.thread = threading.Thread(
                target=runner._run_scheduler_sync,
                daemon=True,
            )
            self.thread.start()

            logger.info("Scheduler thread started, waiting for jobs...")
            await self.stop_event.wait()

            if self.thread.is_alive():
                self.thread.join(timeout=10)

            logger.info("Scheduler stopped gracefully")
            return 0

        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
            return 0
        except Exception as e:
            logger.error("Scheduler failed: %s", str(e), exc_info=True)
            return 1


async def run_scheduler() -> int:
    """Run the scheduled sync scheduler asynchronously.

    Returns:
        Exit code (0 for success, 1 for errors).
    """
    logger.info("Starting GitHub Stars scheduler service")

    try:
        config = load_config()

        if not config.sync_enabled:
            logger.warning("Sync is disabled, scheduler will not start jobs")

        scheduler = ScheduledSync(config)
        scheduler.start()
        logger.info("Scheduler running, waiting for jobs...")

        stop_event = asyncio.Event()

        def handle_signal() -> None:
            logger.info("Received shutdown signal")
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal)

        await stop_event.wait()

        if scheduler.is_running():
            scheduler.stop()

        logger.info("Scheduler stopped gracefully")
        return 0

    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
        return 0
    except Exception as e:
        logger.error("Scheduler failed: %s", str(e), exc_info=True)
        return 1


def main() -> int:
    """Run the scheduled sync scheduler.

    Returns:
        Exit code (0 for success, 1 for errors).
    """
    try:
        return asyncio.run(run_scheduler())
    except Exception as e:
        logger.error("Failed to run scheduler: %s", str(e), exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
