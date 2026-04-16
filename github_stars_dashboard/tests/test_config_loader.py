"""Tests for configuration loader."""

import os
from unittest.mock import patch

import pytest

from github_stars.config_loader import Config, load_config


@pytest.fixture
def mock_env_vars():
    """Create mock environment variables for testing."""
    env_vars = {
        "GITHUB_TOKEN": "test_token_12345",
        "DATABASE_URL": "sqlite:///./test.db",
        "LOG_LEVEL": "DEBUG",
        "APP_PORT": "8080",
    }
    return env_vars


@pytest.fixture
def clean_env():
    """Clean environment variables before and after test."""
    original_env = dict(os.environ)
    os.environ.clear()
    os.environ["GITHUB_TOKEN"] = "test_token"
    yield
    os.environ.clear()
    os.environ.update(original_env)


class TestConfig:
    """Tests for Config class."""

    def test_config_creation(self):
        """Test Config object creation with required fields."""
        config = Config(github_token="test_token")

        assert config.github_token == "test_token"
        assert config.database_url == "sqlite:///./github_stars.db"
        assert config.log_level == "INFO"
        assert config.app_port == 8000
        assert config.debug is False

    def test_config_with_custom_values(self):
        """Test Config object with custom values."""
        config = Config(
            github_token="test_token",
            database_url="sqlite:///./custom.db",
            log_level="DEBUG",
            app_port=9000,
        )

        assert config.database_url == "sqlite:///./custom.db"
        assert config.log_level == "DEBUG"
        assert config.app_port == 9000

    def test_config_validation_missing_token(self):
        """Test Config validation fails without token."""
        with pytest.raises(ValueError, match="GITHUB_TOKEN is required"):
            Config(github_token="")

    def test_config_validation_empty_token(self):
        """Test Config validation fails with empty token."""
        with pytest.raises(ValueError, match="GITHUB_TOKEN is required"):
            Config(github_token="   ")

    def test_config_validation_invalid_log_level(self):
        """Test Config validation fails with invalid log level."""
        with pytest.raises(ValueError, match="Invalid log level"):
            Config(github_token="test_token", log_level="INVALID")

    def test_config_validation_invalid_update_interval(self):
        """Test Config validation fails with invalid update interval."""
        with pytest.raises(ValueError, match="Update interval must be at least"):
            Config(github_token="test_token", update_interval=30)

    def test_config_validation_invalid_max_repositories(self):
        """Test Config validation fails with invalid max repositories."""
        with pytest.raises(ValueError, match="Max repositories must be at least"):
            Config(github_token="test_token", max_repositories=0)

    def test_config_to_dict(self):
        """Test Config to_dict method."""
        config = Config(github_token="test_token", log_level="DEBUG")

        config_dict = config.to_dict()

        assert config_dict["github_token"] == "test_token"
        assert config_dict["log_level"] == "DEBUG"
        assert "database_url" in config_dict
        assert "app_port" in config_dict


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_with_env_vars(self, clean_env):
        """Test load_config with environment variables."""
        os.environ["GITHUB_TOKEN"] = "test_token"
        os.environ["DATABASE_URL"] = "sqlite:///./test.db"
        os.environ["LOG_LEVEL"] = "DEBUG"

        config = load_config()

        assert config.github_token == "test_token"
        assert config.database_url == "sqlite:///./test.db"
        assert config.log_level == "DEBUG"

    def test_load_config_defaults(self, clean_env):
        """Test load_config uses defaults for missing variables."""
        os.environ["GITHUB_TOKEN"] = "test_token"

        config = load_config()

        assert config.database_url == "sqlite:///./github_stars.db"
        assert config.log_level == "INFO"
        assert config.app_port == 8000

    def test_load_config_categories(self, clean_env):
        """Test load_config parses categories correctly."""
        os.environ["GITHUB_TOKEN"] = "test_token"
        os.environ["CATEGORIES"] = "python,javascript,go"

        config = load_config()

        assert config.categories == ["python", "javascript", "go"]

    def test_load_config_missing_token(self, clean_env):
        """Test load_config fails without token."""
        os.environ.pop("GITHUB_TOKEN", None)

        with pytest.raises(ValueError, match="GITHUB_TOKEN is required"):
            load_config()

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"})
    def test_load_config_with_dotenv(self, mock_env_vars):
        """Test load_config with dotenv loading."""
        config = load_config()
        assert config.github_token == "test_token"
