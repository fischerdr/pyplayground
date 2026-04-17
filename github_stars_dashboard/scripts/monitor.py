#!/usr/bin/env python3
"""Monitoring module for GitHub Stars Dashboard.

This module provides metrics collection and monitoring utilities.
"""

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


@dataclass
class Metrics:
    """Collection of system metrics."""

    timestamp: float = field(default_factory=time.time)
    datetime_str: str = field(default_factory=lambda: datetime.now().isoformat())

    # Database metrics
    total_repositories: int = 0
    total_stars: int = 0
    total_categories: int = 0
    total_activity_logs: int = 0

    # Sync metrics
    last_sync_time: Optional[float] = None
    last_sync_duration: Optional[float] = None
    sync_errors: int = 0

    # API metrics
    api_uptime: float = 0.0
    api_requests_total: int = 0
    api_requests_failed: int = 0

    # Health metrics
    database_connected: bool = True
    database_health: str = "healthy"
    scheduler_running: bool = False


class MetricsCollector:
    """Collects metrics from various system components."""

    def __init__(self, database_url: str = "sqlite:///./github_stars.db"):
        """Initialize metrics collector.

        Args:
            database_url: Database connection URL.
        """
        self.database_url = database_url
        self.metrics_file = Path("/tmp/github_stars_metrics.json")
        self.start_time = time.time()

    def collect_database_metrics(self) -> Metrics:
        """Collect metrics from the database.

        Returns:
            Metrics object with database statistics.
        """
        metrics = Metrics()
        metrics.api_uptime = time.time() - self.start_time

        try:
            db_path = self.database_url.replace("sqlite:///", "")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Count repositories
            cursor.execute("SELECT COUNT(*) FROM repositories")
            metrics.total_repositories = cursor.fetchone()[0]

            # Count stars
            cursor.execute("SELECT COUNT(*) FROM stars")
            metrics.total_stars = cursor.fetchone()[0]

            # Count categories
            cursor.execute("SELECT COUNT(*) FROM categories")
            metrics.total_categories = cursor.fetchone()[0]

            # Count activity logs
            cursor.execute("SELECT COUNT(*) FROM activity_logs")
            metrics.total_activity_logs = cursor.fetchone()[0]

            # Check last sync time from activity logs
            cursor.execute(
                """
                SELECT timestamp FROM activity_logs
                WHERE action = 'sync_completed'
                ORDER BY timestamp DESC
                LIMIT 1
                """
            )
            last_sync = cursor.fetchone()
            if last_sync:
                metrics.last_sync_time = time.mktime(
                    datetime.strptime(last_sync[0], "%Y-%m-%d %H:%M:%S").timetuple()
                )

            cursor.close()
            conn.close()

        except sqlite3.Error as e:
            metrics.database_connected = False
            metrics.database_health = f"error: {str(e)}"

        return metrics

    def collect_sync_metrics(self, sync_errors: int = 0) -> Metrics:
        """Collect sync-specific metrics.

        Args:
            sync_errors: Number of sync errors encountered.

        Returns:
            Metrics object with sync statistics.
        """
        metrics = self.collect_database_metrics()
        metrics.sync_errors = sync_errors
        return metrics

    def collect_api_metrics(
        self, requests_total: int = 0, requests_failed: int = 0
    ) -> Metrics:
        """Collect API-specific metrics.

        Args:
            requests_total: Total number of API requests.
            requests_failed: Number of failed API requests.

        Returns:
            Metrics object with API statistics.
        """
        metrics = self.collect_database_metrics()
        metrics.api_requests_total = requests_total
        metrics.api_requests_failed = requests_failed
        return metrics

    def get_metrics(self) -> Metrics:
        """Get current metrics from all sources.

        Returns:
            Complete Metrics object.
        """
        return self.collect_database_metrics()

    def metrics_to_dict(self, metrics: Metrics) -> dict:
        """Convert Metrics object to dictionary.

        Args:
            metrics: Metrics object to convert.

        Returns:
            Dictionary representation of metrics.
        """
        import dataclasses

        return dataclasses.asdict(metrics)

    def save_metrics(self, metrics: Optional[Metrics] = None) -> bool:
        """Save metrics to file.

        Args:
            metrics: Metrics to save. If None, collects current metrics.

        Returns:
            True if save successful.
        """
        import json

        if metrics is None:
            metrics = self.get_metrics()

        try:
            metrics_dict = {
                "timestamp": metrics.timestamp,
                "datetime": metrics.datetime_str,
                "total_repositories": metrics.total_repositories,
                "total_stars": metrics.total_stars,
                "total_categories": metrics.total_categories,
                "total_activity_logs": metrics.total_activity_logs,
                "last_sync_time": metrics.last_sync_time,
                "last_sync_duration": metrics.last_sync_duration,
                "sync_errors": metrics.sync_errors,
                "api_uptime": metrics.api_uptime,
                "api_requests_total": metrics.api_requests_total,
                "api_requests_failed": metrics.api_requests_failed,
                "database_connected": metrics.database_connected,
                "database_health": metrics.database_health,
                "scheduler_running": metrics.scheduler_running,
            }

            with open(self.metrics_file, "w") as f:
                json.dump(metrics_dict, f, indent=2)

            return True

        except (IOError, OSError) as e:
            print(f"Failed to save metrics: {e}")
            return False

    def load_metrics(self) -> Optional[Metrics]:
        """Load metrics from file.

        Returns:
            Metrics object if file exists, None otherwise.
        """
        import json

        if not self.metrics_file.exists():
            return None

        try:
            with open(self.metrics_file, "r") as f:
                data = json.load(f)

            return Metrics(
                timestamp=data.get("timestamp", time.time()),
                datetime_str=data.get("datetime_str", ""),
                total_repositories=data.get("total_repositories", 0),
                total_stars=data.get("total_stars", 0),
                total_categories=data.get("total_categories", 0),
                total_activity_logs=data.get("total_activity_logs", 0),
                last_sync_time=data.get("last_sync_time"),
                last_sync_duration=data.get("last_sync_duration"),
                sync_errors=data.get("sync_errors", 0),
                api_uptime=data.get("api_uptime", 0.0),
                api_requests_total=data.get("api_requests_total", 0),
                api_requests_failed=data.get("api_requests_failed", 0),
                database_connected=data.get("database_connected", True),
                database_health=data.get("database_health", "healthy"),
                scheduler_running=data.get("scheduler_running", False),
            )

        except (IOError, OSError, json.JSONDecodeError) as e:
            print(f"Failed to load metrics: {e}")
            return None

    def get_metrics_summary(self) -> str:
        """Get formatted metrics summary.

        Returns:
            Formatted string with metrics summary.
        """
        metrics = self.get_metrics()

        summary = [
            "\n" + "=" * 60,
            "GitHub Stars Dashboard - Metrics Summary",
            "=" * 60,
            f"\nTimestamp: {metrics.datetime_str}",
            f"API Uptime: {metrics.api_uptime:.0f} seconds",
            "",
            "Database Metrics:",
            f"  - Repositories: {metrics.total_repositories}",
            f"  - Stars: {metrics.total_stars}",
            f"  - Categories: {metrics.total_categories}",
            f"  - Activity Logs: {metrics.total_activity_logs}",
            f"  - Database Health: {metrics.database_health}",
            "",
            "Sync Metrics:",
            f"  - Last Sync: {metrics.last_sync_time}",
            f"  - Sync Errors: {metrics.sync_errors}",
            "",
            "API Metrics:",
            f"  - Total Requests: {metrics.api_requests_total}",
            f"  - Failed Requests: {metrics.api_requests_failed}",
            "",
            "=" * 60,
        ]

        return "\n".join(summary)


def main() -> None:
    """Main entry point for metrics collection script."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Collect and display metrics for GitHub Stars Dashboard"
    )
    parser.add_argument(
        "-d", "--database", default="sqlite:///./github_stars.db", help="Database URL"
    )
    parser.add_argument("--save", action="store_true", help="Save metrics to file")
    parser.add_argument("--load", action="store_true", help="Load metrics from file")

    args = parser.parse_args()

    collector = MetricsCollector(database_url=args.database)

    if args.load:
        metrics = collector.load_metrics()
        if metrics:
            print(collector.get_metrics_summary())
        else:
            print("No metrics file found")
    elif args.save:
        metrics = collector.get_metrics()
        if collector.save_metrics(metrics):
            print("Metrics saved successfully")
            print(collector.get_metrics_summary())
        else:
            print("Failed to save metrics")
    else:
        print(collector.get_metrics_summary())


if __name__ == "__main__":
    main()
