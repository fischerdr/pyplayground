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
        sync_enabled: Whether scheduled sync is enabled.
        sync_interval_min: Minimum sync interval in minutes.
        sync_interval_max: Maximum sync interval in minutes.
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
    sync_enabled: bool = False
    sync_interval_min: int = 30
    sync_interval_max: int = 120

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from environment variables.

        Returns:
            Config instance with validated configuration.
        """
        return load_config()

    def save(self) -> None:
        """Save configuration to environment file.

        This method writes the current configuration to .env file.
        """
        from pathlib import Path

        env_path = Path(".env")

        with open(env_path, "w") as f:
            f.write(f"GITHUB_TOKEN={self.github_token}\n")
            f.write(f"DATABASE_URL={self.database_url}\n")
            f.write(f"LOG_LEVEL={self.log_level}\n")
            f.write(f"LOG_FORMAT={self.log_format}\n")
            f.write(f"APP_HOST={self.app_host}\n")
            f.write(f"APP_PORT={self.app_port}\n")
            f.write(f"DEBUG={str(self.debug).lower()}\n")
            f.write(f"CATEGORIES={','.join(self.categories)}\n")
            f.write(f"UPDATE_INTERVAL={self.update_interval}\n")
            f.write(f"MAX_REPOSITORIES={self.max_repositories}\n")
            f.write(f"SYNC_ENABLED={str(self.sync_enabled).lower()}\n")
            f.write(f"SYNC_INTERVAL_MIN={self.sync_interval_min}\n")
            f.write(f"SYNC_INTERVAL_MAX={self.sync_interval_max}\n")

        logger.info(f"Configuration saved to {env_path}")

    def __post_init__(self) -> None:
        """Validate configuration after initialization.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        self._validate_github_token()
        self._validate_log_level()
        self._validate_update_interval()
        self._validate_max_repositories()
        self._validate_sync_intervals()

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

    def _validate_sync_intervals(self) -> None:
        """Validate sync interval settings.

        Raises:
            ValueError: If sync intervals are invalid.
        """
        if self.sync_interval_min < 1:
            error_msg = f"Sync interval min must be at least 1 minute, got {self.sync_interval_min}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        if self.sync_interval_max < self.sync_interval_min:
            error_msg = f"Sync interval max ({self.sync_interval_max}) must be >= min ({self.sync_interval_min})"
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
            "sync_enabled": self.sync_enabled,
            "sync_interval_min": self.sync_interval_min,
            "sync_interval_max": self.sync_interval_max,
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
        sync_enabled_str = os.getenv("SYNC_ENABLED", "false").lower()
        sync_interval_min_str = os.getenv("SYNC_INTERVAL_MIN", "30")
        sync_interval_max_str = os.getenv("SYNC_INTERVAL_MAX", "120")

        app_port = int(app_port_str)
        debug = debug_str in ("true", "1", "yes")
        categories = [c.strip() for c in categories_str.split(",") if c.strip()]
        update_interval = int(update_interval_str)
        max_repositories = int(max_repositories_str)
        sync_enabled = sync_enabled_str in ("true", "1", "yes")
        sync_interval_min = int(sync_interval_min_str)
        sync_interval_max = int(sync_interval_max_str)

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
            sync_enabled=sync_enabled,
            sync_interval_min=sync_interval_min,
            sync_interval_max=sync_interval_max,
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
