"""Command-line interface for GitHub Stars Dashboard.

This module provides CLI commands for managing GitHub repositories,
stars, categories, and synchronization operations using Click.
"""

import logging
import sys
from datetime import datetime, timedelta

import click
from rich.console import Console
from rich.table import Table
from sqlalchemy import func

from github_stars.categorizer import Categorizer
from github_stars.config_loader import Config
from github_stars.database import init_database
from github_stars.fetcher import GitHubClient
from github_stars.sync import RepoSyncer, SyncStats

console = Console()
logger = logging.getLogger(__name__)


class Color:
    """ANSI color codes for rich output."""

    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


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

        console.print(
            f"[{Color.GREEN}]✓ Configuration saved successfully[/{Color.GREEN}]"
        )

        # Display current config
        console.print(f"\n[{Color.BOLD}]Current Configuration:[/{Color.BOLD}]")
        console.print(f"  User Login: {config_obj.user_login}")
        console.print(
            f"  Update Interval: {config_obj.update_interval_minutes} minutes"
        )
        console.print(f"  Max Repositories: {config_obj.max_repositories}")
        console.print(f"  Log Level: {config_obj.log_level}")
        if config_obj.categories_config_path:
            console.print(f"  Categories Config: {config_obj.categories_config_path}")

    except Exception as e:
        console.print(f"[{Color.RED}]✗ Error: {e}[/{Color.RED}]")
        sys.exit(1)


@app.command()
@click.option("--sync-categories", is_flag=True, default=True, help="Sync categories")
@click.option(
    "--reset-inactive", is_flag=True, default=False, help="Reset inactive flag"
)
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
            console.print(
                f"\n[{Color.YELLOW}]⚠ Completed with {len(stats.errors)} error(s)[/{Color.YELLOW}]"
            )
        else:
            console.print(
                f"\n[{Color.GREEN}]✓ Sync completed successfully[/{Color.GREEN}]"
            )

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
            table = Table(
                title=f"Repositories (Showing {len(repositories)} of {query.count()})"
            )
            table.add_column("ID", style=Color.CYAN, justify="right")
            table.add_column("Name", style=Color.GREEN)
            table.add_column("Language", style=Color.YELLOW)
            table.add_column("Stars", justify="right")
            table.add_column("Category", style=Color.BLUE)
            table.add_column("Active", justify="center")

            for repo in repositories:
                active_str = (
                    "[{Color.GREEN}]Yes[/{Color.GREEN}]"
                    if repo.is_active
                    else "[{Color.RED}]No[/{Color.RED}]"
                )
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
                console.print(
                    f"[{Color.RED}]✗ Repository with ID {repo_id} not found[/{Color.RED}]"
                )
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
            console.print(
                f"  Category: [{Color.GREEN}]{result.category_name}[/{Color.GREEN}]"
            )
            console.print(f"  Confidence: {result.confidence:.2f}")
            console.print(f"  Matched Pattern: {result.matched_pattern}")

            console.print(
                f"\n[{Color.GREEN}]✓ Repository categorized successfully[/{Color.GREEN}]"
            )

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
            active_count = (
                session.query(Repository).filter(Repository.is_active == True).count()
            )  # noqa: E712
            inactive_count = (
                session.query(Repository).filter(Repository.is_active == False).count()
            )  # noqa: E712
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
                cat_table.add_column(
                    "Repositories", justify="right", style=Color.YELLOW
                )
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
                console.print(
                    f"[{Color.RED}]✗ Repository with ID {repo_id} not found[/{Color.RED}]"
                )
                sys.exit(1)

            # Confirm deletion
            confirm = click.confirm(
                f"Are you sure you want to delete '{repository.full_name}'?"
            )

            if not confirm:
                console.print("[{Color.YELLOW}]Cancelled[/{Color.YELLOW}]")
                return

            # Delete associated stars
            session.query(Star).filter(Star.repository_id == repo_id).delete()

            # Delete repository
            session.delete(repository)
            session.commit()

            console.print(
                f"[{Color.GREEN}]✓ Repository '{repository.full_name}' deleted successfully[/{Color.GREEN}]"
            )

    except Exception as e:
        console.print(f"[{Color.RED}]✗ Error: {e}[/{Color.RED}]")
        logger.exception("Error deleting repository")
        sys.exit(1)


@app.command()
def version() -> None:
    """Show version information."""
    console.print(f"[{Color.BOLD}]GitHub Stars Dashboard v0.1.0[/{Color.BOLD}]")


# Main entry point
if __name__ == "__main__":
    app()
