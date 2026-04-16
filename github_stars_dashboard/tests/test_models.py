"""Tests for database models."""

from datetime import datetime

import pytest
import sqlalchemy
from dateutil import tz
from sqlalchemy import text

from github_stars.database import (
    create_database_engine,
    get_db_session,
    init_database,
)
from github_stars.models import ActivityLog, Category, Repository, Star


@pytest.fixture
def test_db_url():
    """Create a test database URL."""
    return "sqlite:///./test_models.sqlite"


@pytest.fixture
def db_session(test_db_url):
    """Create a database session for testing."""
    import os

    engine = create_database_engine(test_db_url)
    init_database(engine)

    session = get_db_session(test_db_url)
    yield session

    session.rollback()
    session.close()

    db_path = (
        test_db_url.split("///")[-1]
        if "///" in test_db_url
        else test_db_url.replace("sqlite:///", "")
    )
    if db_path and os.path.exists(db_path):
        os.remove(db_path)


class TestCategory:
    """Tests for Category model."""

    def test_category_creation(self, db_session):
        """Test Category model creation."""
        category = Category(
            name="python-test",
            pattern="^python-.*",
            priority=1,
        )
        db_session.add(category)
        db_session.commit()

        assert category.id is not None
        assert category.name == "python-test"
        assert category.pattern == "^python-.*"
        assert category.priority == 1
        assert category.created_at is not None

    def test_category_to_dict(self, db_session):
        """Test Category to_dict method."""
        category = Category(
            name="javascript",
            pattern="^js-.*",
            priority=2,
        )
        db_session.add(category)
        db_session.commit()

        category_dict = category.to_dict()

        assert category_dict["name"] == "javascript"
        assert category_dict["pattern"] == "^js-.*"
        assert category_dict["priority"] == 2
        assert "id" in category_dict
        assert "created_at" in category_dict

    def test_category_uniqueness(self, db_session):
        """Test Category name uniqueness."""
        category1 = Category(name="python", pattern="^python-.*", priority=1)
        category2 = Category(name="python", pattern="^py-.*", priority=2)

        db_session.add(category1)
        db_session.commit()

        db_session.add(category2)
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            db_session.commit()


class TestRepository:
    """Tests for Repository model."""

    def test_repository_creation(self, db_session):
        """Test Repository model creation."""
        repository = Repository(
            full_name="test/repo",
            description="Test repository",
            html_url="https://github.com/test/repo",
            stars_count=100,
            forks_count=10,
            language="Python",
        )
        db_session.add(repository)
        db_session.commit()

        assert repository.id is not None
        assert repository.full_name == "test/repo"
        assert repository.stars_count == 100
        assert repository.is_active is True
        assert repository.created_at is not None
        assert repository.updated_at is not None

    def test_repository_to_dict(self, db_session):
        """Test Repository to_dict method."""
        repository = Repository(
            full_name="test/repo",
            description="Test repository",
            html_url="https://github.com/test/repo",
            stars_count=100,
        )
        db_session.add(repository)
        db_session.commit()

        repo_dict = repository.to_dict()

        assert repo_dict["full_name"] == "test/repo"
        assert repo_dict["stars_count"] == 100
        assert repo_dict["is_active"] is True
        assert "id" in repo_dict
        assert "created_at" in repo_dict

    def test_repository_full_name_uniqueness(self, db_session):
        """Test Repository full_name uniqueness."""
        repo1 = Repository(
            full_name="test/repo",
            html_url="https://github.com/test/repo",
        )
        repo2 = Repository(
            full_name="test/repo",
            html_url="https://github.com/test/repo2",
        )

        db_session.add(repo1)
        db_session.commit()

        db_session.add(repo2)
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            db_session.commit()


class TestStar:
    """Tests for Star model."""

    def test_star_creation(self, db_session):
        """Test Star model creation."""
        category = Category(name="python", pattern="^.*", priority=1)
        repository = Repository(
            full_name="test/repo",
            html_url="https://github.com/test/repo",
        )
        db_session.add_all([category, repository])
        db_session.commit()

        star = Star(
            repository_id=repository.id,
            starred_at=datetime.now(tz.UTC),
            is_new=True,
        )
        db_session.add(star)
        db_session.commit()

        assert star.id is not None
        assert star.repository_id == repository.id
        assert star.is_new is True

    def test_star_to_dict(self, db_session):
        """Test Star to_dict method."""
        category = Category(name="python", pattern="^.*", priority=1)
        repository = Repository(
            full_name="test/repo",
            html_url="https://github.com/test/repo",
        )
        db_session.add_all([category, repository])
        db_session.commit()

        star = Star(
            repository_id=repository.id,
            is_new=True,
        )
        db_session.add(star)
        db_session.commit()

        star_dict = star.to_dict()

        assert star_dict["repository_id"] == repository.id
        assert star_dict["is_new"] is True
        assert "id" in star_dict
        assert "starred_at" in star_dict

    def test_star_repository_relationship(self, db_session):
        """Test Star-Repository relationship."""
        category = Category(name="python-rel", pattern="^.*", priority=1)
        repository = Repository(
            full_name="test/repo-rel",
            html_url="https://github.com/test/repo",
        )
        db_session.add_all([category, repository])
        db_session.commit()

        star = Star(repository_id=repository.id, is_new=True)
        db_session.add(star)
        db_session.commit()

        repository = (
            db_session.query(Repository).filter_by(full_name="test/repo-rel").first()
        )
        assert repository.stars.count() == 1
        assert repository.stars.first().id == star.id


class TestActivityLog:
    """Tests for ActivityLog model."""

    def test_activity_log_creation(self, db_session):
        """Test ActivityLog model creation."""
        activity_log = ActivityLog(
            action="update",
            details='{"repository": "test/repo"}',
        )
        db_session.add(activity_log)
        db_session.commit()

        assert activity_log.id is not None
        assert activity_log.action == "update"
        assert activity_log.details == '{"repository": "test/repo"}'
        assert activity_log.created_at is not None

    def test_activity_log_to_dict(self, db_session):
        """Test ActivityLog to_dict method."""
        activity_log = ActivityLog(
            action="delete",
            details='{"repository": "test/repo"}',
        )
        db_session.add(activity_log)
        db_session.commit()

        log_dict = activity_log.to_dict()

        assert log_dict["action"] == "delete"
        assert log_dict["details"] == '{"repository": "test/repo"}'
        assert "id" in log_dict
        assert "created_at" in log_dict


class TestIndexes:
    """Tests for database indexes."""

    def test_indexes_created(self, test_db_url):
        """Test that indexes are created on tables."""
        engine = create_database_engine(test_db_url)
        init_database(engine)

        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index'")
            )
            indexes = [row[0] for row in result.fetchall()]

            assert any("ix_repositories_full_name" in idx for idx in indexes)
            assert any("ix_stars_repository_id" in idx for idx in indexes)
            assert any("ix_categories_name" in idx for idx in indexes)
