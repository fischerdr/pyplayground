#!/usr/bin/env python3
"""Secret Scanner Tool.

This script searches for potential sensitive information exposures in various file types
including JSON, YAML, Python, and Markdown files. It can detect:
- Passwords
- API Keys
- AWS Keys
- Private Keys
- Tokens
- Environment Variables with sensitive values
"""

import logging
from pathlib import Path
from typing import List

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.text import Text

from pyplayground.utils.password_finder import FileResult, process_file

# Initialize typer app and rich console
app = typer.Typer(help="Search for exposed secrets in code and config files")
console = Console()


def setup_logging(log_level: str = "INFO") -> None:
    """Set up logging configuration.

    Args:
        log_level: Desired logging level (default: INFO)
    """
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )


def scan_directory(
    directory: Path,
    ignore_tests: bool = True,
    file_patterns: List[str] = ["*.json", "*.yaml", "*.yml", "*.py", "*.md", "*.env", "*.conf"],
) -> List[FileResult]:
    """Scan directory for files containing potential secret exposures.

    Args:
        directory: Directory path to scan
        ignore_tests: Whether to ignore test files and directories
        file_patterns: List of file patterns to match

    Returns:
        List of FileResult containing found secrets
    """
    logger = logging.getLogger(__name__)
    results: List[FileResult] = []

    try:
        for pattern in file_patterns:
            for file_path in directory.rglob(pattern):
                if result := process_file(file_path, ignore_tests):
                    results.append(result)
    except Exception as e:
        logger.error(f"Error scanning directory {directory}: {str(e)}")

    return results


def get_secret_style(secret_type: str) -> str:
    """Get the appropriate color style based on secret type."""
    return {
        "API Key": "yellow",
        "AWS Key": "red",
        "Password": "bright_red",
        "Private Key": "red",
        "Token": "yellow",
        "Environment Variable": "blue",
        "Secret": "magenta",
    }.get(secret_type, "white")


def display_results(results: List[FileResult], base_dir: Path) -> None:
    """Display scan results in a formatted table.

    Args:
        results: List of FileResult to display
        base_dir: Base directory to make paths relative to
    """
    if not results:
        console.print("[yellow]No secrets found.[/yellow]")
        return

    table = Table(
        show_header=True,
        header_style="bold magenta",
        title="[bold red]Potential Secrets Found[/bold red]",
        caption="[yellow]Note: Review these findings carefully for false positives[/yellow]",
    )

    table.add_column("File", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Line #")
    table.add_column("Secret")
    table.add_column("Context")

    total_secrets = 0
    for result in results:
        # Convert absolute path to relative path
        try:
            rel_path = Path(result["file"]).relative_to(base_dir)
        except ValueError:
            # Fallback to filename if path is not relative to base_dir
            rel_path = Path(result["file"]).name

        for secret_info in result["passwords"]:
            secret_style = get_secret_style(secret_info["type"])
            secret_value = Text(secret_info["password"], style=secret_style)

            table.add_row(
                str(rel_path),
                secret_info["type"],
                str(secret_info["line"]) if secret_info["line"] else "N/A",
                secret_value,
                secret_info["text"] if secret_info["text"] else "N/A",
            )
            total_secrets += 1

    console.print(table)
    console.print(f"\n[bold]Total secrets found: {total_secrets}[/bold]")


@app.command()
def main(
    directory: Path = typer.Argument(
        ...,
        help="Directory to scan for secrets",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    log_level: str = typer.Option(
        "INFO", "--log-level", "-l", help="Logging level (DEBUG, INFO, WARNING, ERROR)"
    ),
    ignore_tests: bool = typer.Option(
        True,
        "--ignore-tests/--include-tests",
        "-i/-I",
        help="Whether to ignore test files and directories",
    ),
) -> None:
    """Scan directory for potential secret exposures in code and config files.

    Args:
        directory: Directory to scan for secrets
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        ignore_tests: Whether to ignore test files and directories

    Returns:
        None

    Raises:
        typer.BadParameter: If the directory does not exist
        typer.BadParameter: If the directory is not a directory
    """
    setup_logging(log_level)
    logger = logging.getLogger(__name__)

    # Resolve the absolute path of the directory
    abs_directory = directory.resolve()
    logger.info(f"Scanning directory: {abs_directory}")
    logger.info(f"Test files will be {'ignored' if ignore_tests else 'included'}")

    results = scan_directory(abs_directory, ignore_tests)
    display_results(results, abs_directory)


if __name__ == "__main__":
    app()
