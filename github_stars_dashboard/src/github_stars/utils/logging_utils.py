"""Logging utilities for GitHub Stars Dashboard."""

import json
import logging
import sys
from datetime import datetime
from typing import Any

from dateutil import tz


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.

        Args:
            record: Log record to format.

        Returns:
            JSON string representation of the log record.
        """
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(tz.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            log_entry["exc_info"] = self.formatException(record.exc_info)

        if hasattr(record, "extra_data"):
            log_entry.update(record.extra_data)

        return json.dumps(log_entry)


class TextFormatter(logging.Formatter):
    """Text formatter for human-readable logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as text.

        Args:
            record: Log record to format.

        Returns:
            Formatted text string.
        """
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        return formatter.format(record)


def setup_logger(
    name: str,
    level: str = "INFO",
    format_type: str = "json",
) -> logging.Logger:
    """Setup and return a logger instance.

    Args:
        name: Logger name (typically __name__).
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        format_type: Log format type ('json' or 'text').

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, level.upper()))

        if format_type == "json":
            handler.setFormatter(JSONFormatter())
        else:
            handler.setFormatter(TextFormatter())

        logger.addHandler(handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get or create a logger instance.

    This is a convenience function to get a logger with the standard pattern.

    Args:
        name: Logger name (typically __name__).

    Returns:
        Logger instance.
    """
    return setup_logger(name)
