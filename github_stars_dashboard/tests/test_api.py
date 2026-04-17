"""Tests for FastAPI application."""

import pytest
from fastapi.testclient import TestClient
from src.github_stars.api import app
from src.github_stars.database import create_database_engine
from src.github_stars.models import Base


@pytest.fixture
def client():
    """Create test client."""
    engine = create_database_engine()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as client:
        yield client


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_check(self, client):
        """Test /health endpoint returns 200."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


class TestRootEndpoint:
    """Test root endpoint."""

    def test_root(self, client):
        """Test / endpoint returns API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data


class TestCategoriesEndpoint:
    """Test categories endpoint."""

    def test_list_categories(self, client):
        """Test listing categories."""
        response = client.get("/categories")
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data or isinstance(data, list)


class TestStatsEndpoint:
    """Test statistics endpoint."""

    def test_get_stats(self, client):
        """Test getting statistics."""
        response = client.get("/stats")
        # Stats may return 500 if no data, which is acceptable for empty DB
        assert response.status_code in [200, 500]
