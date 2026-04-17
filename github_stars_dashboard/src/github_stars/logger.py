#!/usr/bin/env python3
"""Logging module for GitHub Stars Dashboard.

This module provides structured logging utilities for the application.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.

        Args:
            record: Log record to format.

        Returns:
            JSON string representation of log record.
        """
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        return json.dumps(log_data)


class StructuredLogger:
    """Structured logging wrapper for consistent logging across the application."""

    def __init__(
        self,
        name: str,
        level: int = logging.INFO,
        output_format: str = "console",
        log_file: Optional[str] = None,
    ):
        """Initialize structured logger.

        Args:
            name: Logger name (typically __name__).
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            output_format: Output format ('console' or 'json').
            log_file: Optional log file path.
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        # Remove existing handlers
        self.logger.handlers = []

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)

        if output_format == "json":
            console_handler.setFormatter(JSONFormatter())
        else:
            console_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )

        self.logger.addHandler(console_handler)

        # File handler (optional)
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(level)
            file_handler.setFormatter(JSONFormatter())
            self.logger.addHandler(file_handler)

    def log(
        self,
        level: int,
        message: str,
        **extra_data: Any,
    ) -> None:
        """Log a message with extra data.

        Args:
            level: Log level.
            message: Log message.
            **extra_data: Additional key-value pairs to include in log.
        """
        record = self.logger.makeRecord(
            self.logger.name,
            level,
            "",
            0,
            message,
            (),
            None,
        )
        record.extra_data = extra_data
        self.logger.handle(record)

    def debug(self, message: str, **extra_data: Any) -> None:
        """Log debug message.

        Args:
            message: Debug message.
            **extra_data: Additional key-value pairs.
        """
        self.log(logging.DEBUG, message, **extra_data)

    def info(self, message: str, **extra_data: Any) -> None:
        """Log info message.

        Args:
            message: Info message.
            **extra_data: Additional key-value pairs.
        """
        self.log(logging.INFO, message, **extra_data)

    def warning(self, message: str, **extra_data: Any) -> None:
        """Log warning message.

        Args:
            message: Warning message.
            **extra_data: Additional key-value pairs.
        """
        self.log(logging.WARNING, message, **extra_data)

    def error(self, message: str, **extra_data: Any) -> None:
        """Log error message.

        Args:
            message: Error message.
            **extra_data: Additional key-value pairs.
        """
        self.log(logging.ERROR, message, **extra_data)

    def critical(self, message: str, **extra_data: Any) -> None:
        """Log critical message.

        Args:
            message: Critical message.
            **extra_data: Additional key-value pairs.
        """
        self.log(logging.CRITICAL, message, **extra_data)

    def exception(self, message: str, **extra_data: Any) -> None:
        """Log exception message with traceback.

        Args:
            message: Exception message.
            **extra_data: Additional key-value pairs.
        """
        self.log(logging.ERROR, message, exc_info=True, **extra_data)


def setup_logging(
    level: str = "INFO",
    output_format: str = "console",
    log_file: Optional[str] = None,
    logger_name: Optional[str] = None,
) -> StructuredLogger:
    """Setup structured logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        output_format: Output format ('console' or 'json').
        log_file: Optional log file path.
        logger_name: Optional logger name.

    Returns:
        Configured StructuredLogger instance.
    """
    name = logger_name or __name__
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    return StructuredLogger(
        name=name,
        level=level_map.get(level.upper(), logging.INFO),
        output_format=output_format,
        log_file=log_file,
    )


# Default logger instance
default_logger: Optional[StructuredLogger] = None


def get_logger(
    name: Optional[str] = None,
    level: str = "INFO",
    output_format: str = "console",
    log_file: Optional[str] = None,
) -> StructuredLogger:
    """Get or create a logger instance.

    Args:
        name: Logger name.
        level: Log level.
        output_format: Output format.
        log_file: Optional log file path.

    Returns:
        StructuredLogger instance.
    """
    global default_logger

    if default_logger is None:
        default_logger = setup_logging(
            level=level,
            output_format=output_format,
            log_file=log_file,
        )

    return default_logger
