"""Tests for database configuration."""

import os
from unittest.mock import patch

import pytest
from sqlalchemy import text

from github_stars.database import (
    create_engine_instance,
    get_database_url,
    get_db_session,
    init_database,
)


@pytest.fixture
def test_db_url():
    """Create a test database URL."""
    return "sqlite:///./test_db.sqlite"


class TestDatabaseURL:
    """Tests for get_database_url function."""

    def test_get_database_url_default(self):
        """Test get_database_url returns default URL."""
        with patch.dict(os.environ, {}, clear=True):
            url = get_database_url()
            assert url == "sqlite:///./github_stars.db"

    def test_get_database_url_from_env(self):
        """Test get_database_url uses environment variable."""
        test_url = "sqlite:///./custom.db"
        with patch.dict(os.environ, {"DATABASE_URL": test_url}):
            url = get_database_url()
            assert url == test_url


class TestCreateEngineInstance:
    """Tests for create_engine_instance function."""

    def test_create_engine_default(self, test_db_url):
        """Test create_engine_instance with default URL."""
        engine = create_engine_instance()
        assert engine is not None

    def test_create_engine_custom_url(self, test_db_url):
        """Test create_engine_instance with custom URL."""
        engine = create_engine_instance(test_db_url)
        assert engine is not None

    def test_create_engine_invalid_url(self):
        """Test create_engine_instance with invalid URL."""
        with pytest.raises(ValueError, match="Invalid database URL"):
            create_engine_instance("invalid://url")


class TestInitDatabase:
    """Tests for init_database function."""

    def test_init_database_creates_tables(self, test_db_url):
        """Test init_database creates all tables."""
        engine = create_engine_instance(test_db_url)

        try:
            init_database(engine)

            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
                tables = [row[0] for row in result.fetchall()]

                assert "repositories" in tables
                assert "stars" in tables
                assert "categories" in tables
                assert "activity_logs" in tables
        finally:
            db_path = (
                test_db_url.split("///")[-1]
                if "///" in test_db_url
                else test_db_url.replace("sqlite:///", "")
            )
            if db_path and os.path.exists(db_path):
                os.remove(db_path)

    def test_init_database_idempotent(self, test_db_url):
        """Test init_database can be called multiple times."""
        engine = create_engine_instance(test_db_url)

        try:
            init_database(engine)
            init_database(engine)

            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
                tables = [row[0] for row in result.fetchall()]

                assert len(tables) == 4
        finally:
            db_path = (
                test_db_url.split("///")[-1]
                if "///" in test_db_url
                else test_db_url.replace("sqlite:///", "")
            )
            if db_path and os.path.exists(db_path):
                os.remove(db_path)


class TestGetDBSession:
    """Tests for get_db_session function."""

    def test_get_db_session_returns_session(self, test_db_url):
        """Test get_db_session returns a valid session."""
        session = get_db_session(test_db_url)
        assert session is not None

    def test_get_db_session_can_query(self, test_db_url):
        """Test get_db_session can perform queries."""
        engine = create_engine_instance(test_db_url)
        init_database(engine)

        try:
            session = get_db_session(test_db_url)
            result = session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            assert result is not None
        finally:
            db_path = (
                test_db_url.split("///")[-1]
                if "///" in test_db_url
                else test_db_url.replace("sqlite:///", "")
            )
            if db_path and os.path.exists(db_path):
                os.remove(db_path)
