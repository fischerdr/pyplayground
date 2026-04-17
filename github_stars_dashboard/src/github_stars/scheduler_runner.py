"""Scheduler runner module for standalone scheduler execution.

This module provides a CLI entry point for running the scheduler
as a standalone service in Docker containers.
"""

import signal
import sys
from contextlib import contextmanager

from github_stars.config_loader import load_config
from github_stars.scheduler import ScheduledSync
from github_stars.utils.logging_utils import get_logger

logger = get_logger(__name__)


@contextmanager
def signal_handler(scheduler: ScheduledSync):
    """Handle shutdown signals gracefully.

    Args:
        scheduler: ScheduledSync instance to stop on shutdown.

    Yields:
        None
    """
    stop_event = False

    def handle_signal(signum, frame):
        nonlocal stop_event
        logger.info("Received signal %d, initiating shutdown", signum)
        stop_event = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        yield
    finally:
        if scheduler.is_running():
            scheduler.stop()


def main() -> int:
    """Run the scheduled sync scheduler.

    Returns:
        Exit code (0 for success, 1 for errors).
    """
    logger.info("Starting GitHub Stars scheduler service")

    try:
        config = load_config()

        if not config.sync_enabled:
            logger.warning("Sync is disabled, scheduler will not start jobs")

        scheduler = ScheduledSync(config)

        with signal_handler(scheduler):
            scheduler.start()
            logger.info("Scheduler running, waiting for jobs...")

            while True:
                import time

                time.sleep(1)

                if not scheduler.is_running():
                    logger.error("Scheduler stopped unexpectedly")
                    return 1

    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
        return 0
    except Exception as e:
        logger.error("Scheduler failed: %s", str(e), exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
