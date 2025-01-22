"""Logging utility functions."""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

# Get the project root directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG_DIR = os.path.join(PROJECT_ROOT, "logs")


def setup_logging(
    level: Union[str, int] = logging.INFO,
    log_dir: Optional[Union[str, Path]] = DEFAULT_LOG_DIR,
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    date_format: str = "%Y-%m-%d %H:%M:%S",
    handlers: Optional[List[logging.Handler]] = None,
) -> None:
    """
    Set up logging configuration with console and file output.

    Args:
        level: Logging level (default: INFO)
        log_dir: Directory for log files (default: PROJECT_ROOT/logs)
        log_format: Log message format
        date_format: Date format for log messages
        handlers: Optional list of custom handlers
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

    # Clear any existing handlers
    root_logger.handlers.clear()

    # Create logs directory if it doesn't exist
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Add console handlers for different levels
    console_error_handler = logging.StreamHandler(sys.stderr)
    console_error_handler.setLevel(logging.ERROR)
    console_error_handler.setFormatter(formatter)
    root_logger.addHandler(console_error_handler)

    console_debug_handler = logging.StreamHandler(sys.stdout)
    console_debug_handler.setLevel(logging.DEBUG)
    console_debug_handler.setFormatter(formatter)
    console_debug_handler.addFilter(lambda record: record.levelno < logging.ERROR)
    root_logger.addHandler(console_debug_handler)

    # Add file handlers for different levels
    current_date = datetime.now().strftime("%Y-%m-%d")

    # Debug and info log file
    debug_log_file = os.path.join(log_dir, f"{current_date}_debug.log")
    file_debug_handler = logging.FileHandler(debug_log_file)
    file_debug_handler.setLevel(logging.DEBUG)
    file_debug_handler.setFormatter(formatter)
    root_logger.addHandler(file_debug_handler)

    # Error log file (errors and above)
    error_log_file = os.path.join(log_dir, f"{current_date}_error.log")
    file_error_handler = logging.FileHandler(error_log_file)
    file_error_handler.setLevel(logging.ERROR)
    file_error_handler.setFormatter(formatter)
    root_logger.addHandler(file_error_handler)

    # Add custom handlers if provided
    if handlers:
        for handler in handlers:
            if not handler.formatter:
                handler.setFormatter(formatter)
            root_logger.addHandler(handler)

    # Prevent propagation to avoid duplicate logs
    root_logger.propagate = False

    logger = get_logger(__name__)
    logger.debug(f"Logging initialized. Debug log: {debug_log_file}, Error log: {error_log_file}")


def get_logger(name: str, level: Optional[Union[str, int]] = None) -> logging.Logger:
    """
    Get a logger instance with optional level setting.

    Args:
        name: Logger name
        level: Optional logging level

    Returns:
        logging.Logger instance
    """
    logger = logging.getLogger(name)

    if level is not None:
        if isinstance(level, str):
            level = getattr(logging, level.upper())
        logger.setLevel(level)

    return logger


def get_log_files() -> dict:
    """
    Get the paths to the current log files.

    Returns:
        Dictionary containing paths to debug and error log files
    """
    current_date = datetime.now().strftime("%Y-%m-%d")
    log_dir = DEFAULT_LOG_DIR

    return {
        "debug": os.path.join(log_dir, f"{current_date}_debug.log"),
        "error": os.path.join(log_dir, f"{current_date}_error.log"),
    }
