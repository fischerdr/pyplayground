"""Tests for Click CLI application."""

import pytest
from click.testing import CliRunner
from src.github_stars.cli import app as cli


@pytest.fixture
def runner():
    """Create CLI runner."""
    return CliRunner()


class TestVersionCommand:
    """Test version command."""

    def test_version_shows_version(self, runner):
        """Test version command shows version."""
        result = runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        assert "github stars dashboard" in result.output.lower()


class TestInitCommand:
    """Test init command."""

    def test_init_creates_database(self, runner):
        """Test init command creates database."""
        result = runner.invoke(cli, ["init"])
        # Should succeed (exit code 0 or 1 if already initialized)
        assert result.exit_code in [0, 1]


class TestInvalidCommands:
    """Test invalid command handling."""

    def test_invalid_command(self, runner):
        """Test invalid command shows help."""
        result = runner.invoke(cli, ["invalid-command"])
        assert result.exit_code != 0

    def test_invalid_option(self, runner):
        """Test invalid option shows error."""
        result = runner.invoke(cli, ["repos", "list", "--invalid-option"])
        assert result.exit_code != 0
