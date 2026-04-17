"""Command-line interface for GitHub Stars Dashboard.

This module provides CLI commands for managing GitHub repositories,
stars, categories, and synchronization operations using Click.
"""

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from sqlalchemy import func

# Add scripts directory to Python path
SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from github_stars.categorizer import Categorizer
from github_stars.config_loader import Config
from github_stars.database import init_database
from github_stars.fetcher import GitHubClient
from github_stars.scheduler import ScheduledSync
from github_stars.sync import RepoSyncer, SyncStats

try:
    from scripts.alert import AlertManager, AlertRule
    from scripts.monitor import MetricsCollector

    MONITORING_AVAILABLE = True
except ImportError:
    MONITORING_AVAILABLE = False

console = Console()
logger = logging.getLogger(__name__)


class Color:
    """ANSI color codes for rich output."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    BLUE = "blue"
    CYAN = "cyan"
    RESET = ""
    BOLD = "bold"


def setup_logging(level: str = "INFO") -> None:
    """Setup logging configuration.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@click.group()
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]),
    help="Set logging level",
)
@click.pass_context
def app(ctx: click.Context, log_level: str) -> None:
    """GitHub Stars Dashboard - Track and analyze GitHub repository stars."""
    setup_logging(log_level)
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level


@app.command()
def init() -> None:
    """Initialize the database and create tables."""
    console.print(f"[{Color.BLUE}]Initializing database...[/{Color.BLUE}]")
    init_database()
    console.print(f"[{Color.GREEN}]✓ Database initialized successfully[/{Color.GREEN}]")


@app.command()
@click.option("--user-login", help="GitHub username")
@click.option("--github-token", help="GitHub personal access token")
@click.option("--update-interval", default=60, help="Update interval in minutes")
@click.option("--max-repos", default=100, help="Maximum repositories to track")
@click.option("--log-level", default="INFO", help="Log level")
@click.option("--categories-config", help="Path to categories config file")
def config(
    user_login: str | None,
    github_token: str | None,
    update_interval: int,
    max_repos: int,
    log_level: str,
    categories_config: str | None,
) -> None:
    """Configure GitHub Stars Dashboard."""
    try:
        config_obj = Config.load()

        if user_login:
            config_obj.user_login = user_login
        if github_token:
            config_obj.github_token = github_token
        config_obj.update_interval_minutes = update_interval
        config_obj.max_repositories = max_repos
        config_obj.log_level = log_level
        if categories_config:
            config_obj.categories_config_path = categories_config

        config_obj.save()

        console.print(f"[{Color.GREEN}]✓ Configuration saved successfully[/{Color.GREEN}]")

        # Display current config
        console.print(f"\n[{Color.BOLD}]Current Configuration:[/{Color.BOLD}]")
        console.print(f"  User Login: {config_obj.user_login}")
        console.print(f"  Update Interval: {config_obj.update_interval_minutes} minutes")
        console.print(f"  Max Repositories: {config_obj.max_repositories}")
        console.print(f"  Log Level: {config_obj.log_level}")
        if config_obj.categories_config_path:
            console.print(f"  Categories Config: {config_obj.categories_config_path}")

    except Exception as e:
        console.print(f"[{Color.RED}]✗ Error: {e}[/{Color.RED}]")
        sys.exit(1)


@app.command()
@click.option("--sync-categories", is_flag=True, default=True, help="Sync categories")
@click.option("--reset-inactive", is_flag=True, default=False, help="Reset inactive flag")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def sync(sync_categories: bool, reset_inactive: bool, verbose: bool) -> None:
    """Sync starred repositories from GitHub."""
    try:
        config = Config.load()
        categorizer = Categorizer(config.categories_config_path)
        syncer = RepoSyncer(config, categorizer)

        console.print(f"[{Color.BLUE}]Starting sync...[/{Color.BLUE}]")

        if verbose:
            console.print(f"  Syncing categories: {sync_categories}")
            console.print(f"  Reset inactive: {reset_inactive}")

        stats = syncer.sync_starred_repos(
            sync_categories=sync_categories,
            reset_inactive=reset_inactive,
        )

        # Display results
        console.print(f"\n[{Color.BOLD}]Sync Results:[/{Color.BOLD}]")

        table = Table(title="Statistics")
        table.add_column("Metric", style=Color.CYAN)
        table.add_column("Value", style=Color.GREEN)

        table.add_row("Repositories Processed", str(stats.repositories_processed))
        table.add_row("Stars Created", str(stats.stars_created))
        table.add_row("Repositories Updated", str(stats.repositories_updated))

        if stats.errors:
            table.add_row("Errors", str(len(stats.errors)))
            if verbose:
                console.print(f"\n[{Color.YELLOW}]Errors:[/{Color.YELLOW}]")
                for error in stats.errors:
                    console.print(f"  - {error}")

        console.print(table)

        if stats.errors:
            console.print(f"\n[{Color.YELLOW}]⚠ Completed with {len(stats.errors)} error(s)[/{Color.YELLOW}]")
        else:
            console.print(f"\n[{Color.GREEN}]✓ Sync completed successfully[/{Color.GREEN}]")

    except Exception as e:
        console.print(f"[{Color.RED}]✗ Sync failed: {e}[/{Color.RED}]")
        logger.exception("Sync error")
        sys.exit(1)


@app.command()
@click.option(
    "--category",
    help="Filter by category",
)
@click.option(
    "--active",
    is_flag=True,
    default=None,
    help="Show only active repositories",
)
@click.option(
    "--limit",
    default=20,
    type=click.IntRange(min=1, max=1000),
    help="Maximum results to display",
)
@click.option(
    "--sort-by",
    default="stars",
    type=click.Choice(["stars", "name", "updated_at"]),
    help="Sort by field",
)
def repos(category: str | None, active: bool | None, limit: int, sort_by: str) -> None:
    """List all tracked repositories."""
    try:
        from github_stars.database import get_db_session
        from github_stars.models import Repository

        with get_db_session() as session:
            query = session.query(Repository)

            if category:
                query = query.filter(Repository.category == category)

            if active is not None:
                query = query.filter(Repository.is_active == active)

            # Sort
            if sort_by == "stars":
                query = query.order_by(Repository.stars.desc())
            elif sort_by == "name":
                query = query.order_by(Repository.full_name)
            elif sort_by == "updated_at":
                query = query.order_by(Repository.updated_at.desc())

            repositories = query.limit(limit).all()

            if not repositories:
                console.print(f"[{Color.YELLOW}]No repositories found[/{Color.YELLOW}]")
                return

            # Display table
            table = Table(title=f"Repositories (Showing {len(repositories)} of {query.count()})")
            table.add_column("ID", style=Color.CYAN, justify="right")
            table.add_column("Name", style=Color.GREEN)
            table.add_column("Language", style=Color.YELLOW)
            table.add_column("Stars", justify="right")
            table.add_column("Category", style=Color.BLUE)
            table.add_column("Active", justify="center")

            for repo in repositories:
                active_str = "[{Color.GREEN}]Yes[/{Color.GREEN}]" if repo.is_active else "[{Color.RED}]No[/{Color.RED}]"
                table.add_row(
                    str(repo.id),
                    repo.full_name,
                    repo.language or "-",
                    str(repo.stars),
                    repo.category or "-",
                    active_str.format(Color=Color),
                )

            console.print(table)

            # Summary
            total_stars = sum(repo.stars for repo in repositories)
            console.print(f"\n[{Color.BOLD}]Total Stars: {total_stars}[/{Color.BOLD}]")

    except Exception as e:
        console.print(f"[{Color.RED}]✗ Error: {e}[/{Color.RED}]")
        logger.exception("Error listing repositories")
        sys.exit(1)


@app.command()
@click.argument("repo_id", type=int)
def categorize(repo_id: int) -> None:
    """Re-categorize a specific repository."""
    try:
        from github_stars.database import get_db_session
        from github_stars.models import Repository

        with get_db_session() as session:
            repository = session.get(Repository, repo_id)

            if not repository:
                console.print(f"[{Color.RED}]✗ Repository with ID {repo_id} not found[/{Color.RED}]")
                sys.exit(1)

            config = Config.load()
            categorizer = Categorizer(config.categories_config_path)
            result = categorizer.categorize_repository(
                full_name=repository.full_name,
                description=repository.description or "",
                language=repository.language or "",
            )

            repository.category = result.category_name
            session.commit()

            console.print(f"\n[{Color.BOLD}]Categorization Result:[/{Color.BOLD}]")
            console.print(f"  Repository: {repository.full_name}")
            console.print(f"  Category: [{Color.GREEN}]{result.category_name}[/{Color.GREEN}]")
            console.print(f"  Confidence: {result.confidence:.2f}")
            console.print(f"  Matched Pattern: {result.matched_pattern}")

            console.print(f"\n[{Color.GREEN}]✓ Repository categorized successfully[/{Color.GREEN}]")

    except Exception as e:
        console.print(f"[{Color.RED}]✗ Error: {e}[/{Color.RED}]")
        logger.exception("Error categorizing repository")
        sys.exit(1)


@app.command()
def stats() -> None:
    """Display dashboard statistics."""
    try:
        from github_stars.database import get_db_session
        from github_stars.models import Category, Repository, Star

        with get_db_session() as session:
            total_repositories = session.query(Repository).count()
            total_stars = session.query(Star).count()
            active_count = session.query(Repository).filter(Repository.is_active == True).count()  # noqa: E712
            inactive_count = session.query(Repository).filter(Repository.is_active == False).count()  # noqa: E712
            categories_count = session.query(Category).count()

            # Calculate total stars
            total_star_count = session.query(Repository.stars).sum() or 0

            # Category breakdown
            category_stats = (
                session.query(
                    Repository.category,
                    func.count(Repository.id).label("count"),
                    func.sum(Repository.stars).label("total_stars"),
                )
                .group_by(Repository.category)
                .order_by(func.sum(Repository.stars).desc())
                .all()
            )

            # Display summary
            console.print(f"\n[{Color.BOLD}]Dashboard Statistics[/{Color.BOLD}]")
            console.print()

            table = Table(title="Summary")
            table.add_column("Metric", style=Color.CYAN)
            table.add_column("Value", style=Color.GREEN)

            table.add_row("Total Repositories", str(total_repositories))
            table.add_row("Total Stars", str(total_star_count))
            table.add_row("Active Repositories", str(active_count))
            table.add_row("Inactive Repositories", str(inactive_count))
            table.add_row("Categories", str(categories_count))

            console.print(table)

            if category_stats:
                console.print(f"\n[{Color.BOLD}]By Category:[/{Color.BOLD}]")

                cat_table = Table(show_header=True, header_style=Color.BOLD)
                cat_table.add_column("Category", style=Color.CYAN)
                cat_table.add_column("Repositories", justify="right", style=Color.YELLOW)
                cat_table.add_column("Total Stars", justify="right", style=Color.GREEN)

                for category, count, stars in category_stats:
                    cat_table.add_row(
                        category or "Uncategorized",
                        str(count),
                        str(stars),
                    )

                console.print(cat_table)

    except Exception as e:
        console.print(f"[{Color.RED}]✗ Error: {e}[/{Color.RED}]")
        logger.exception("Error getting stats")
        sys.exit(1)


@app.command()
@click.argument("repo_id", type=int)
def delete(repo_id: int) -> None:
    """Delete a repository and its associated stars."""
    try:
        from github_stars.database import get_db_session
        from github_stars.models import Repository, Star

        with get_db_session() as session:
            repository = session.get(Repository, repo_id)

            if not repository:
                console.print(f"[{Color.RED}]✗ Repository with ID {repo_id} not found[/{Color.RED}]")
                sys.exit(1)

            # Confirm deletion
            confirm = click.confirm(f"Are you sure you want to delete '{repository.full_name}'?")

            if not confirm:
                console.print("[{Color.YELLOW}]Cancelled[/{Color.YELLOW}]")
                return

            # Delete associated stars
            session.query(Star).filter(Star.repository_id == repo_id).delete()

            # Delete repository
            session.delete(repository)
            session.commit()

            console.print(f"[{Color.GREEN}]✓ Repository '{repository.full_name}' deleted successfully[/{Color.GREEN}]")

    except Exception as e:
        console.print(f"[{Color.RED}]✗ Error: {e}[/{Color.RED}]")
        logger.exception("Error deleting repository")
        sys.exit(1)


@app.command()
def version() -> None:
    """Show version information."""
    console.print(f"[{Color.BOLD}]GitHub Stars Dashboard v0.1.0[/{Color.BOLD}]")


@app.command()
def scheduler_start() -> None:
    """Start the scheduled sync scheduler."""
    try:
        config = Config.load()
        scheduler = ScheduledSync(config)

        console.print(f"[{Color.BLUE}]Starting scheduled sync...[/{Color.BLUE}]")
        scheduler.start()

        console.print(f"[{Color.GREEN}]✓ Scheduler started successfully[/{Color.GREEN}]")
        console.print(f"  Running: {scheduler.is_running()}")

        next_run = scheduler.get_next_run()
        if next_run:
            console.print(f"  Next run: {next_run}")

        # Keep running
        console.print(f"\n[{Color.YELLOW}]Scheduler running. Press Ctrl+C to stop.[/{Color.YELLOW}]")

        import time

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        console.print(f"\n[{Color.YELLOW}]Stopping scheduler...[/{Color.YELLOW}]")
        if "scheduler" in locals():
            scheduler.stop()
        console.print(f"[{Color.GREEN}]✓ Scheduler stopped[/{Color.GREEN}]")
    except Exception as e:
        console.print(f"[{Color.RED}]✗ Error: {e}[/{Color.RED}]")
        logger.exception("Scheduler error")
        sys.exit(1)


@app.command()
def scheduler_status() -> None:
    """Check scheduler status."""
    try:
        config = Config.load()
        scheduler = ScheduledSync(config)

        console.print(f"\n[{Color.BOLD}]Scheduler Status:[/{Color.BOLD}]")
        console.print(f"  Running: {scheduler.is_running()}")

        next_run = scheduler.get_next_run()
        if next_run:
            console.print(f"  Next run: {next_run}")
        else:
            console.print(f"  Next run: Not scheduled")

        if scheduler.is_running():
            console.print(f"\n[{Color.GREEN}]✓ Scheduler is running[/{Color.GREEN}]")
        else:
            console.print(f"\n[{Color.YELLOW}]⚠ Scheduler is not running[/{Color.YELLOW}]")

    except Exception as e:
        console.print(f"[{Color.RED}]✗ Error: {e}[/{Color.RED}]")
        logger.exception("Scheduler status error")
        sys.exit(1)


@app.command()
def scheduler_stop() -> None:
    """Stop the scheduled sync scheduler."""
    try:
        config = Config.load()
        scheduler = ScheduledSync(config)

        if scheduler.is_running():
            console.print(f"[{Color.BLUE}]Stopping scheduler...[/{Color.BLUE}]")
            scheduler.stop()
            console.print(f"[{Color.GREEN}]✓ Scheduler stopped successfully[/{Color.GREEN}]")
        else:
            console.print(f"[{Color.YELLOW}]⚠ Scheduler is not running[/{Color.YELLOW}]")

    except Exception as e:
        console.print(f"[{Color.RED}]✗ Error: {e}[/{Color.RED}]")
        logger.exception("Scheduler stop error")
        sys.exit(1)


@app.command()
@click.option(
    "--output",
    "-o",
    default=None,
    help="Output file path (JSON format)",
)
@click.option(
    "--format",
    "-f",
    default="table",
    type=click.Choice(["table", "json"]),
    help="Output format",
)
def metrics(output: str | None, format: str) -> None:
    """Collect and display system metrics."""
    if not MONITORING_AVAILABLE:
        console.print(f"[{Color.RED}]✗ Monitoring scripts not available[/{Color.RED}]")
        console.print(f"[{Color.YELLOW}]Please ensure scripts/monitor.py exists[/{Color.YELLOW}]")
        sys.exit(1)

    try:
        console.print(f"[{Color.BLUE}]Collecting metrics...[/{Color.BLUE}]")

        collector = MetricsCollector()
        metrics_obj = collector.get_metrics()
        metrics_data = collector.metrics_to_dict(metrics_obj)

        if format == "json":
            import json

            if output:
                with open(output, "w") as f:
                    json.dump(metrics_data, f, indent=2, default=str)
                console.print(f"[{Color.GREEN}]✓ Metrics saved to {output}[/{Color.GREEN}]")
            else:
                console.print(json.dumps(metrics_data, indent=2, default=str))
        else:
            # Table format
            from rich.table import Table

            table = Table(title="System Metrics")
            table.add_column("Category", style=Color.CYAN)
            table.add_column("Metric", style=Color.YELLOW)
            table.add_column("Value", style=Color.GREEN)
            table.add_column("Status", justify="center")

            for metric_name, metric_value in metrics_data.items():
                status = f"[{Color.GREEN}]✓[/{Color.GREEN}]" if metric_value and metric_value != "error: no such table: repositories" else f"[{Color.YELLOW}]⚠[/{Color.YELLOW}]"
                table.add_row(
                    "general",
                    metric_name.replace("_", " ").title(),
                    str(metric_value),
                    status.format(Color=Color),
                )

            console.print(table)

        console.print(f"\n[{Color.GREEN}]✓ Metrics collected successfully[/{Color.GREEN}]")

    except Exception as e:
        console.print(f"[{Color.RED}]✗ Error collecting metrics: {e}[/{Color.RED}]")
        logger.exception("Metrics collection error")
        sys.exit(1)


@app.command()
@click.option(
    "--list-rules",
    is_flag=True,
    default=False,
    help="List all alert rules",
)
@click.option(
    "--add",
    is_flag=True,
    default=False,
    help="Add a new alert rule",
)
@click.option("--name", default=None, help="Rule name")
@click.option("--metric", default=None, help="Metric name")
@click.option("--condition", default=None, help="Condition (e.g., '>100', '<5')")
@click.option("--threshold", default=None, help="Threshold value")
@click.option("--severity", default="warning", help="Alert severity")
@click.option("--message", default=None, help="Alert message")
@click.option(
    "--format",
    "-f",
    default="table",
    type=click.Choice(["table", "json"]),
    help="Output format",
)
def alerts(
    list_rules: bool,
    add: bool,
    name: str | None,
    metric: str | None,
    condition: str | None,
    threshold: str | None,
    severity: str,
    message: str | None,
    format: str,
) -> None:
    """Manage alert rules and check alerts."""
    if not MONITORING_AVAILABLE:
        console.print(f"[{Color.RED}]✗ Monitoring scripts not available[/{Color.RED}]")
        console.print(f"[{Color.YELLOW}]Please ensure scripts/alert.py exists[/{Color.YELLOW}]")
        sys.exit(1)

    try:
        alert_manager = AlertManager()

        if list_rules:
            alerts = alert_manager.get_alerts()
            rules = [
                {
                    "id": i + 1,
                    "name": alert.title,
                    "metric": alert.metric_name,
                    "condition": "",
                    "severity": alert.severity,
                    "enabled": not alert.acknowledged,
                }
                for i, alert in enumerate(alerts)
            ]

            if format == "json":
                import json

                console.print(json.dumps(rules, indent=2))
            else:
                from rich.table import Table

                table = Table(title="Alert Rules")
                table.add_column("ID", style=Color.CYAN, justify="right")
                table.add_column("Name", style=Color.GREEN)
                table.add_column("Metric", style=Color.YELLOW)
                table.add_column("Condition", style=Color.BLUE)
                table.add_column("Severity", justify="center")
                table.add_column("Status", justify="center")

                for rule in rules:
                    status = "[{Color.GREEN}]Active[/{Color.GREEN}]" if rule.get("enabled", True) else "[{Color.RED}]Inactive[/{Color.RED}]"
                    table.add_row(
                        str(rule.get("id", "")),
                        rule.get("name", ""),
                        rule.get("metric", ""),
                        rule.get("condition", ""),
                        rule.get("severity", ""),
                        status.format(Color=Color),
                    )

                console.print(table)

        elif add:
            if not all([name, metric, condition, threshold]):
                console.print(f"[{Color.RED}]✗ Missing required parameters for adding rule[/{Color.RED}]")
                console.print(f"[{Color.YELLOW}]Required: --name, --metric, --condition, --threshold[/{Color.YELLOW}]")
                sys.exit(1)

            rule = AlertRule(
                name=name,
                metric_name=metric,
                condition=condition,
                threshold=float(threshold),
                severity=severity,
                message_template=message or f"Alert: {name} threshold exceeded",
            )

            alert_manager.add_rule(rule=rule)

            console.print(f"[{Color.GREEN}]✓ Alert rule '{name}' added successfully[/{Color.GREEN}]")
            console.print(f"  Metric: {metric}")
            console.print(f"  Condition: {condition}")
            console.print(f"  Threshold: {threshold}")
            console.print(f"  Severity: {severity}")

        else:
            # Check current alerts
            console.print(f"[{Color.BLUE}]Checking alerts...[/{Color.BLUE}]")

            collector = MetricsCollector()
            metrics_obj = collector.get_metrics()
            metrics_data = collector.metrics_to_dict(metrics_obj)

            # Flatten metrics
            flat_metrics: dict[str, float] = {}
            for metric_name, metric_value in metrics_data.items():
                if isinstance(metric_value, (int, float)):
                    flat_metrics[metric_name] = float(metric_value)

            alerts = alert_manager.check_rules(metrics=flat_metrics)
            alerts_list = [
                {
                    "rule_name": alert.title,
                    "metric": alert.metric_name,
                    "value": alert.metric_value,
                    "threshold": alert.threshold,
                    "severity": alert.severity,
                }
                for alert in alerts
            ]

            if format == "json":
                import json

                console.print(json.dumps(alerts_list, indent=2, default=str))
            else:
                from rich.table import Table

                if alerts_list:
                    table = Table(title="Active Alerts")
                    table.add_column("Rule", style=Color.CYAN)
                    table.add_column("Metric", style=Color.YELLOW)
                    table.add_column("Value", style=Color.GREEN)
                    table.add_column("Threshold", style=Color.BLUE)
                    table.add_column("Severity", justify="center")

                    for alert in alerts_list:
                        severity_style = "red" if alert.get("severity") == "critical" else "yellow"
                        table.add_row(
                            alert.get("rule_name", ""),
                            alert.get("metric", ""),
                            str(alert.get("value", "")),
                            str(alert.get("threshold", "")),
                            f"[{severity_style}]{alert.get('severity', '')}[/{severity_style}]",
                        )

                    console.print(table)
                    console.print(f"\n[{Color.RED}]⚠ {len(alerts_list)} alert(s) active[/{Color.RED}]")

                else:
                    console.print(f"[{Color.GREEN}]✓ No active alerts[/{Color.GREEN}]")

        console.print(f"\n[{Color.GREEN}]✓ Alert check completed[/{Color.GREEN}]")

    except Exception as e:
        console.print(f"[{Color.RED}]✗ Error: {e}[/{Color.RED}]")
        logger.exception("Alert management error")
        sys.exit(1)


# Main entry point
if __name__ == "__main__":
    app()
