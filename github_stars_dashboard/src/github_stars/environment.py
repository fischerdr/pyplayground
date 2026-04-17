"""Environment validation utilities for GitHub Stars Dashboard.

This module provides utilities for validating and managing environment-specific
configuration for Podman containerized deployments.
"""

import os
from pathlib import Path
from typing import Optional


class EnvironmentValidator:
    """Validates environment configuration for Podman deployments."""

    REQUIRED_ENV_VARS = [
        "GITHUB_TOKEN",
        "DATABASE_URL",
        "LOG_LEVEL",
        "APP_HOST",
        "APP_PORT",
    ]

    VALID_ENVIRONMENTS = ["dev", "prod"]

    def __init__(self, env_file: Optional[str] = None):
        """Initialize environment validator.

        Args:
            env_file: Path to environment file. Defaults to .env in current directory.
        """
        self.env_file = env_file or ".env"
        self.environment = self._detect_environment()

    def _detect_environment(self) -> str:
        """Detect current environment from env file name.

        Returns:
            Environment name (dev, prod, or default).
        """
        if self.env_file in [".env.dev", "dev"]:
            return "dev"
        elif self.env_file in [".env.prod", "prod"]:
            return "prod"
        elif self.env_file == ".env":
            # Check if .env exists and has DEBUG=true
            if Path(self.env_file).exists():
                with open(self.env_file, "r") as f:
                    content = f.read()
                    if "DEBUG=true" in content:
                        return "dev"
            return "default"
        return "default"

    def validate(self) -> bool:
        """Validate all required environment variables are set.

        Returns:
            True if all required variables are present.

        Raises:
            ValueError: If required environment variables are missing.
        """
        missing = []
        for var in self.REQUIRED_ENV_VARS:
            value = os.getenv(var)
            if not value or value.strip() == "":
                missing.append(var)

        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                f"Please set these in your {self.env_file} file."
            )

        return True

    def validate_github_token(self) -> bool:
        """Validate GitHub token is properly configured.

        Returns:
            True if token is valid.

        Raises:
            ValueError: If GitHub token is missing or invalid.
        """
        token = os.getenv("GITHUB_TOKEN")

        if not token:
            raise ValueError(
                "GITHUB_TOKEN is not set. Please generate a token from "
                "https://github.com/settings/tokens and add it to your .env file."
            )

        if token in ["your_github_token_here", "your_token_here", ""]:
            raise ValueError(
                "GITHUB_TOKEN contains placeholder value. Please replace with "
                "your actual GitHub token in the .env file."
            )

        if not token.startswith("ghp_") and len(token) < 40:
            raise ValueError(
                "GITHUB_TOKEN appears to be invalid. GitHub personal access "
                "tokens should start with 'ghp_' and be at least 40 characters long."
            )

        return True

    def get_database_path(self) -> Path:
        """Get database path from environment configuration.

        Returns:
            Path object for database file.

        Raises:
            ValueError: If DATABASE_URL is not properly configured.
        """
        db_url = os.getenv("DATABASE_URL", "")

        if not db_url.startswith("sqlite:///"):
            raise ValueError(
                f"Invalid DATABASE_URL format: {db_url}. "
                "Expected format: sqlite:///./path/to/database.db"
            )

        # Extract path from sqlite:///./path format
        db_path = db_url.replace("sqlite:///./", "")
        return Path(db_path)

    def get_log_config(self) -> dict:
        """Get logging configuration from environment.

        Returns:
            Dictionary with LOG_LEVEL and LOG_FORMAT settings.
        """
        return {
            "level": os.getenv("LOG_LEVEL", "INFO"),
            "format": os.getenv("LOG_FORMAT", "json"),
        }

    def __str__(self) -> str:
        """Return string representation of environment status."""
        return f"EnvironmentValidator(environment={self.environment}, env_file={self.env_file})"

    def __repr__(self) -> str:
        """Return repr of environment status."""
        return self.__str__()


def validate_environment(env_file: Optional[str] = None) -> EnvironmentValidator:
    """Validate environment configuration.

    Convenience function that creates an EnvironmentValidator and runs validation.

    Args:
        env_file: Path to environment file.

    Returns:
        Validated EnvironmentValidator instance.

    Raises:
        ValueError: If validation fails.
    """
    validator = EnvironmentValidator(env_file)
    validator.validate()
    validator.validate_github_token()
    return validator


if __name__ == "__main__":
    import sys

    env_file = sys.argv[1] if len(sys.argv) > 1 else ".env"

    try:
        validator = validate_environment(env_file)
        print(f"Environment validation successful: {validator.environment}")
        print(f"Database path: {validator.get_database_path()}")
        print(f"Log config: {validator.get_log_config()}")
        sys.exit(0)
    except ValueError as e:
        print(f"Environment validation failed: {e}", file=sys.stderr)
        sys.exit(1)
