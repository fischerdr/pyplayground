"""Logging utility functions.

This module provides logging setup and configuration utilities.
It includes robust project root detection that works correctly when
scripts are executed as modules (e.g., python -m pyplayground.awxtower.script).
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union


def get_project_root() -> str:
    """Find the project root directory by looking for project markers.

    This function looks for common project files to identify the root directory,
    starting from the current file's location and walking up the directory tree.

    This works correctly when scripts are executed as modules using
    python -m pyplayground.awxtower.<script> syntax.

    The function prioritizes .git directory as the most definitive marker,
    then looks for directories with multiple project markers to avoid
    stopping at package subdirectories.

    Returns:
        str: Path to the project root directory
    """
    # Start from the current file's directory
    current_path = Path(__file__).resolve().parent

    # Primary markers - .git is the most definitive
    primary_markers = {".git"}

    # Secondary markers - used in combination
    secondary_markers = {"pyproject.toml", "README.md", "requirements.txt", "setup.py"}

    # Walk up the directory tree looking for project markers
    for parent in [current_path] + list(current_path.parents):
        # First check for .git directory (most definitive)
        if (parent / ".git").exists():
            return str(parent)

        # Check for multiple secondary markers (at least 2)
        found_markers = sum(1 for marker in secondary_markers if (parent / marker).exists())
        if found_markers >= 2:
            return str(parent)

    # Fallback 1: If we can't find definitive markers, try the current working directory
    cwd = Path.cwd()
    if (cwd / ".git").exists():
        return str(cwd)

    found_markers_cwd = sum(1 for marker in secondary_markers if (cwd / marker).exists())
    if found_markers_cwd >= 2:
        return str(cwd)

    # Fallback 2: Use the original method as last resort
    original_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return original_root


def _find_project_root() -> str:
    """Deprecated: Use get_project_root() instead."""
    return get_project_root()


# Get the project root directory using the robust method
PROJECT_ROOT = get_project_root()
# Check for environment variable first, fall back to default
DEFAULT_LOG_DIR = os.getenv("DEFAULT_LOG_DIR", os.path.join(PROJECT_ROOT, "logs"))


def setup_logging(  # noqa: C901
    level: Union[str, int] = logging.INFO,
    log_dir: Optional[Union[str, Path]] = DEFAULT_LOG_DIR,
    script_name: str = "app_log",
    # Use specific formats similar to k8s script
    log_format_file: str = "%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s] - %(message)s",
    log_format_console: str = "%(levelname)s: %(message)s",
    date_format: str = "%Y-%m-%d %H:%M:%S",
    handlers: Optional[List[logging.Handler]] = None,
) -> None:
    """Set up logging configuration with console (errors only) and a single file output.

    Args:
        level: Logging level for the file handler (default: INFO). Console is fixed at WARNING.
        log_dir: Directory for log files (default: PROJECT_ROOT/logs).
        script_name: Name of the script, used for the log filename (default: app_log).
        log_format_file: Log message format for the file handler.
        log_format_console: Log message format for the console handler.
        date_format: Date format for log messages.
        handlers: Optional list of custom handlers to add.
    """
    # Store the level name before potentially converting
    if isinstance(level, str):
        level_name = level.upper()
        level_int = getattr(logging, level_name, logging.INFO)
    else:  # Assumed int
        level_int = level
        level_name = logging.getLevelName(level_int)  # Getting name from int is okay here for init msg
        # Alternatively, handle only expected int levels:
        # level_name = 'DEBUG' if level_int == logging.DEBUG else 'INFO' # etc.

    root_logger = logging.getLogger()
    # Set root logger level to the most verbose level needed (DEBUG if file is DEBUG)
    root_logger.setLevel(min(level_int, logging.WARNING))  # Ensure root captures everything needed

    file_formatter = logging.Formatter(fmt=log_format_file, datefmt=date_format)
    console_formatter = logging.Formatter(fmt=log_format_console)

    # Clear any existing handlers
    root_logger.handlers.clear()

    # Create logs directory if it doesn't exist
    if log_dir and not os.path.exists(str(log_dir)):
        try:
            os.makedirs(str(log_dir))
        except OSError as e:
            # Fallback gracefully if dir creation fails (e.g., permissions)
            print(
                f"Warning: Could not create log directory '{log_dir}': {e}. File logging disabled.",
                file=sys.stderr,
            )
            log_dir = None  # Disable file logging

    # Add Console Handler (WARNING level and above)
    console_handler = logging.StreamHandler(sys.stderr)  # Explicitly use stderr for warnings/errors
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Add File Handler (INFO or DEBUG based on level) if log_dir is valid
    log_file_path = None
    if log_dir:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Generate a base filename, perhaps based on the main script?
        # For now, using a generic name. Consider passing script name if needed.
        log_file_path = os.path.join(log_dir, f"{script_name}_{timestamp}.log")
        try:
            file_handler = logging.FileHandler(log_file_path)
            file_handler.setLevel(level_int)  # Use the integer level here
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
        except IOError as e:
            print(
                f"Warning: Could not open log file '{log_file_path}': {e}. File logging disabled.",
                file=sys.stderr,
            )
            log_file_path = None  # Indicate file logging failed

    # Add custom handlers if provided
    if handlers:
        for handler in handlers:
            if not handler.formatter:
                # Try to apply a sensible default formatter if none is set
                if isinstance(handler, logging.FileHandler):
                    handler.setFormatter(file_formatter)
                else:
                    handler.setFormatter(console_formatter)
            root_logger.addHandler(handler)

    # Prevent propagation to avoid duplicate logs if other loggers are configured
    root_logger.propagate = False

    # Log initialization message (will go to file if level allows, and console if WARNING+)
    init_msg = f"Logging initialized. Level: {level_name}."  # Use the stored level name
    if log_file_path:
        init_msg += f" Log file: {log_file_path}"
    else:
        init_msg += " File logging disabled."
    # Use a logger instance to emit the message
    get_logger(__name__).info(init_msg)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Logger name

    Returns:
        logging.Logger instance
    """
    # Removed optional level setting to rely on root config
    logger = logging.getLogger(name)
    return logger
