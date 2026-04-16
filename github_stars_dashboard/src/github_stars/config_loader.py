"""Configuration loader for GitHub Stars Dashboard."""

import logging
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class Config:
    """Configuration class for GitHub Stars Dashboard.

    Attributes:
        github_token: GitHub API token.
        database_url: Database connection URL.
        log_level: Logging level.
        log_format: Log format (json or text).
        app_host: Application host address.
        app_port: Application port.
        debug: Debug mode flag.
        categories: Comma-separated list of default categories.
        update_interval: Update interval in seconds.
        max_repositories: Maximum number of repositories to track.
    """

    github_token: str
    database_url: str = "sqlite:///./github_stars.db"
    log_level: str = "INFO"
    log_format: str = "json"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False
    categories: list[str] = field(
        default_factory=lambda: ["python", "javascript", "go", "rust", "java"]
    )
    update_interval: int = 3600
    max_repositories: int = 100

    def __post_init__(self) -> None:
        """Validate configuration after initialization.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        self._validate_github_token()
        self._validate_log_level()
        self._validate_update_interval()
        self._validate_max_repositories()

    def _validate_github_token(self) -> None:
        """Validate GitHub token is provided.

        Raises:
            ValueError: If GitHub token is empty.
        """
        if not self.github_token or not self.github_token.strip():
            error_msg = "GITHUB_TOKEN is required"
            logger.error(error_msg)
            raise ValueError(error_msg)

        if len(self.github_token) < 10:
            warning_msg = "GitHub token appears to be too short"
            logger.warning(warning_msg)

    def _validate_log_level(self) -> None:
        """Validate log level is valid.

        Raises:
            ValueError: If log level is invalid.
        """
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_levels:
            error_msg = (
                f"Invalid log level: {self.log_level}. Must be one of {valid_levels}"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

    def _validate_update_interval(self) -> None:
        """Validate update interval is positive.

        Raises:
            ValueError: If update interval is not positive.
        """
        if self.update_interval < 60:
            error_msg = f"Update interval must be at least 60 seconds, got {self.update_interval}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    def _validate_max_repositories(self) -> None:
        """Validate max repositories is positive.

        Raises:
            ValueError: If max repositories is not positive.
        """
        if self.max_repositories < 1:
            error_msg = (
                f"Max repositories must be at least 1, got {self.max_repositories}"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

    def to_dict(self) -> dict:
        """Convert configuration to dictionary.

        Returns:
            Dictionary representation of the configuration.
        """
        return {
            "github_token": self.github_token,
            "database_url": self.database_url,
            "log_level": self.log_level,
            "log_format": self.log_format,
            "app_host": self.app_host,
            "app_port": self.app_port,
            "debug": self.debug,
            "categories": self.categories,
            "update_interval": self.update_interval,
            "max_repositories": self.max_repositories,
        }


def load_config() -> Config:
    """Load configuration from environment variables.

    This function loads environment variables from .env file and
    creates a Config instance with validation.

    Returns:
        Config instance with validated configuration.

    Raises:
        ValueError: If required configuration is missing or invalid.
    """
    logger.info("Loading configuration from environment variables")

    try:
        load_dotenv()

        github_token = os.getenv("GITHUB_TOKEN", "")
        database_url = os.getenv("DATABASE_URL", "sqlite:///./github_stars.db")
        log_level = os.getenv("LOG_LEVEL", "INFO")
        log_format = os.getenv("LOG_FORMAT", "json")
        app_host = os.getenv("APP_HOST", "0.0.0.0")
        app_port_str = os.getenv("APP_PORT", "8000")
        debug_str = os.getenv("DEBUG", "false").lower()
        categories_str = os.getenv("CATEGORIES", "python,javascript,go,rust,java")
        update_interval_str = os.getenv("UPDATE_INTERVAL", "3600")
        max_repositories_str = os.getenv("MAX_REPOSITORIES", "100")

        app_port = int(app_port_str)
        debug = debug_str in ("true", "1", "yes")
        categories = [c.strip() for c in categories_str.split(",") if c.strip()]
        update_interval = int(update_interval_str)
        max_repositories = int(max_repositories_str)

        config = Config(
            github_token=github_token,
            database_url=database_url,
            log_level=log_level,
            log_format=log_format,
            app_host=app_host,
            app_port=app_port,
            debug=debug,
            categories=categories,
            update_interval=update_interval,
            max_repositories=max_repositories,
        )

        logger.info(
            f"Configuration loaded successfully. "
            f"Database: {config.database_url}, "
            f"Log level: {config.log_level}, "
            f"Port: {config.app_port}"
        )

        return config

    except ValueError as e:
        logger.error(f"Configuration validation failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        raise


def get_config() -> Config:
    """Get configuration instance.

    This function provides a simple interface to get the configuration.
    It caches the configuration instance to avoid reloading.

    Returns:
        Config instance.
    """
    try:
        return load_config()
    except Exception as e:
        logger.error(f"Failed to get configuration: {e}")
        raise
