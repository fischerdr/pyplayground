"""FastAPI application for GitHub Stars Dashboard.

This module provides REST API endpoints for managing GitHub repositories,
stars, categories, and synchronization operations.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func

from github_stars.categorizer import Categorizer, categorize_repository
from github_stars.config_loader import Config
from github_stars.database import get_db_session, init_database
from github_stars.environment import validate_environment
from github_stars.fetcher import GitHubClient
from github_stars.scheduler import ScheduledSync
from github_stars.sync import RepoSyncer, sync_starred_repos

logger = logging.getLogger(__name__)


# Pydantic models for request/response
class RepositoryResponse(BaseModel):
    """Repository response model."""

    id: int
    full_name: str
    description: str | None
    html_url: str
    language: str | None
    stars: int
    forks: int
    category: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CategoryResponse(BaseModel):
    """Category response model."""

    id: int
    name: str
    pattern: str
    priority: int


class StarResponse(BaseModel):
    """Star response model."""

    id: int
    repository_id: int
    repository_name: str
    starred_at: datetime


class SyncStatsResponse(BaseModel):
    """Sync statistics response model."""

    total_repositories: int
    total_stars: int
    active_repositories: int
    inactive_repositories: int
    categories_count: int


class SyncRequest(BaseModel):
    """Sync request model."""

    sync_categories: bool = Field(
        default=True, description="Whether to sync categories"
    )
    reset_inactive: bool = Field(
        default=False, description="Whether to reset inactive flag"
    )


class ConfigResponse(BaseModel):
    """Configuration response model."""

    github_token: str | None
    user_login: str
    update_interval_minutes: int
    max_repositories: int
    log_level: str
    categories_config_path: str | None


# Create FastAPI app
app = FastAPI(
    title="GitHub Stars Dashboard API",
    description="REST API for tracking and analyzing GitHub repository stars",
    version="0.1.0",
)

# Mount static files - look in project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
STATIC_DIR = PROJECT_ROOT / "static"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# Only mount static files if directory exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Template directory
TEMPLATE_DIR = TEMPLATES_DIR

# Global scheduler instance
scheduler_manager: ScheduledSync | None = None


# Event handlers
@app.on_event("startup")
async def startup_event():
    """Initialize database and scheduler on startup."""
    from github_stars.connection_retry import retry_on_connection
    from github_stars.database import create_database_engine

    validate_environment()
    logger.info(f"Environment validated: {os.getenv('LOG_LEVEL', 'INFO')}")

    @retry_on_connection(max_retries=10, delay=5, backoff=2)
    def initialize_database():
        engine = create_database_engine()
        init_database(engine)
        logger.info("Database initialized successfully")

    try:
        initialize_database()
    except Exception as e:
        logger.error(f"Failed to initialize database after retries: {e}")
        raise

    config = Config.load()
    global scheduler_manager
    scheduler_manager = ScheduledSync(config)

    if config.sync_enabled:
        try:
            scheduler_manager.start()
            logger.info("Scheduler started successfully")
        except Exception as e:
            logger.warning(f"Failed to start scheduler: {e}")

    logger.info("GitHub Stars Dashboard API started")


@app.on_event("shutdown")
async def shutdown_event():
    """Stop scheduler on shutdown."""
    global scheduler_manager
    if scheduler_manager:
        scheduler_manager.stop()
    logger.info("GitHub Stars Dashboard API stopped")


# Middleware for logging
@app.middleware("http")
async def log_requests(request, call_next):
    """Log all HTTP requests."""
    logger.debug("Request: %s %s", request.method, request.url.path)
    response = await call_next(request)
    logger.debug("Response status: %s", response.status_code)
    return response


# Routes
@app.get("/", response_class=JSONResponse)
async def root(request: Request):
    """Serve the main dashboard page or API info based on Accept header."""
    # Check if client wants HTML or JSON
    accept = request.headers.get("accept", "")

    if "text/html" in accept:
        # Serve HTML for browser
        return FileResponse(str(TEMPLATE_DIR / "index.html"))

    # Return JSON for API clients (including tests)
    return {
        "name": "GitHub Stars Dashboard API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", response_model=dict)
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/config", response_model=dict)
async def get_config():
    """Get current configuration."""
    config = Config.load()
    return {
        "github_token": config.github_token,
        "user_login": config.user_login,
        "update_interval_minutes": config.update_interval_minutes,
        "max_repositories": config.max_repositories,
        "log_level": config.log_level,
        "categories_config_path": config.categories_config_path,
        "sync_enabled": config.sync_enabled,
        "sync_interval_min": config.sync_interval_min,
        "sync_interval_max": config.sync_interval_max,
    }


@app.get("/scheduler/status")
async def get_scheduler_status():
    """Get scheduler status."""
    global scheduler_manager

    if scheduler_manager is None:
        return {"running": False, "error": "Scheduler not initialized"}

    return {
        "running": scheduler_manager.is_running(),
        "next_run": (
            scheduler_manager.get_next_run().isoformat()
            if scheduler_manager.get_next_run()
            else None
        ),
    }


@app.post("/scheduler/start")
async def start_scheduler():
    """Start the scheduler."""
    global scheduler_manager

    if scheduler_manager is None:
        config = Config.load()
        scheduler_manager = ScheduledSync(config)

    scheduler_manager.start()

    return {
        "status": "success",
        "message": "Scheduler started",
        "running": scheduler_manager.is_running(),
    }


@app.post("/scheduler/stop")
async def stop_scheduler():
    """Stop the scheduler."""
    global scheduler_manager

    if scheduler_manager is None:
        return {"status": "success", "message": "Scheduler was not running"}

    scheduler_manager.stop()

    return {
        "status": "success",
        "message": "Scheduler stopped",
        "running": False,
    }


@app.post("/scheduler/restart")
async def restart_scheduler():
    """Restart the scheduler."""
    global scheduler_manager

    if scheduler_manager:
        scheduler_manager.stop()

    config = Config.load()
    scheduler_manager = ScheduledSync(config)
    scheduler_manager.start()

    return {
        "status": "success",
        "message": "Scheduler restarted",
        "running": scheduler_manager.is_running(),
    }


@app.get("/repositories", response_model=list[RepositoryResponse])
async def list_repositories(
    category: str | None = Query(None, description="Filter by category"),
    active: bool | None = Query(None, description="Filter by active status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List all repositories with optional filtering."""
    from github_stars.models import Repository

    try:
        with get_db_session() as session:
            query = session.query(Repository)

            if category:
                query = query.filter(Repository.category == category)

            if active is not None:
                query = query.filter(Repository.is_active == active)

            repositories = (
                query.order_by(Repository.stars.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )

            return [RepositoryResponse.model_validate(repo) for repo in repositories]

    except Exception as e:
        logger.error("Error listing repositories: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.get("/repositories/{repo_id}", response_model=RepositoryResponse)
async def get_repository(repo_id: int):
    """Get a specific repository by ID."""
    from github_stars.models import Repository

    try:
        with get_db_session() as session:
            repository = session.get(Repository, repo_id)

            if not repository:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Repository with ID {repo_id} not found",
                )

            return RepositoryResponse.model_validate(repository)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting repository %d: %s", repo_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.get("/categories", response_model=list[CategoryResponse])
async def list_categories():
    """List all categories."""
    from github_stars.models import Category

    try:
        with get_db_session() as session:
            categories = session.query(Category).order_by(Category.priority).all()

            return [CategoryResponse.model_validate(cat) for cat in categories]

    except Exception as e:
        logger.error("Error listing categories: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.get("/stars", response_model=list[StarResponse])
async def list_stars(
    repository_id: int | None = Query(None, description="Filter by repository ID"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List all stars with optional filtering."""
    from github_stars.models import Star

    try:
        with get_db_session() as session:
            query = session.query(Star)

            if repository_id:
                query = query.filter(Star.repository_id == repository_id)

            stars = (
                query.order_by(Star.starred_at.desc()).offset(offset).limit(limit).all()
            )

            result = []
            for star in stars:
                result.append(
                    StarResponse(
                        id=star.id,
                        repository_id=star.repository_id,
                        repository_name=(
                            star.repository.full_name if star.repository else "Unknown"
                        ),
                        starred_at=star.starred_at,
                    )
                )

            return result

    except Exception as e:
        logger.error("Error listing stars: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.get("/stats", response_model=dict)
async def get_stats():
    """Get dashboard statistics."""
    from github_stars.models import Category, Repository, Star

    try:
        with get_db_session() as session:
            total_repositories = session.query(Repository).count()
            total_stars = session.query(Star).count()

            active_count = (
                session.query(Repository)
                .filter(Repository.is_active == True)  # noqa: E712
                .count()
            )

            inactive_count = (
                session.query(Repository)
                .filter(Repository.is_active == False)  # noqa: E712
                .count()
            )

            categories_count = session.query(Category).count()

            # Get category breakdown
            categories = []
            category_results = (
                session.query(
                    Repository.category,
                    Repository.count(),
                    func.sum(Repository.stars).label("total_stars"),
                )
                .group_by(Repository.category)
                .filter(Repository.category.isnot(None))
                .all()
            )

            for category_name, count, stars in category_results:
                categories.append(
                    {"name": category_name, "count": count, "total_stars": stars or 0}
                )

            return {
                "total_repositories": total_repositories,
                "total_stars": total_stars,
                "active_repositories": active_count,
                "inactive_repositories": inactive_count,
                "categories_count": categories_count,
                "categories": categories,
            }

    except Exception as e:
        logger.error("Error getting stats: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.post("/sync", response_model=dict)
async def trigger_sync(request: SyncRequest = None):
    """Trigger a sync operation."""
    try:
        config = Config.load()
        categorizer = Categorizer(config.categories_config_path)

        syncer = RepoSyncer(config, categorizer)
        stats = syncer.sync_starred_repos(
            sync_categories=request.sync_categories if request else True,
            reset_inactive=request.reset_inactive if request else False,
        )

        return {
            "status": "success",
            "message": "Sync completed successfully",
            "stats": {
                "repositories_processed": stats.repositories_processed,
                "stars_created": stats.stars_created,
                "repositories_updated": stats.repositories_updated,
                "errors": stats.errors,
            },
        }

    except Exception as e:
        logger.error("Sync failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.post("/repositories/{repo_id}/categorize", response_model=dict)
async def categorize_repository_endpoint(repo_id: int):
    """Re-categorize a specific repository."""
    from github_stars.models import Repository

    try:
        with get_db_session() as session:
            repository = session.get(Repository, repo_id)

            if not repository:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Repository with ID {repo_id} not found",
                )

            config = Config.load()
            categorizer = Categorizer(config.categories_config_path)
            result = categorizer.categorize_repository(
                full_name=repository.full_name,
                description=repository.description or "",
                language=repository.language or "",
            )

            repository.category = result.category_name
            session.commit()

            logger.info(
                "Re-categorized repository %s to %s (confidence: %.2f)",
                repository.full_name,
                result.category_name,
                result.confidence,
            )

            return {
                "status": "success",
                "category": result.category_name,
                "confidence": result.confidence,
                "matched_pattern": result.matched_pattern,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error categorizing repository %d: %s", repo_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.post("/repositories", response_model=RepositoryResponse)
async def create_repository(request: dict):
    """Create a new repository entry."""
    from github_stars.models import Repository

    try:
        owner = request.get("owner")
        name = request.get("name")

        if not owner or not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Owner and name are required",
            )

        full_name = f"{owner}/{name}"

        with get_db_session() as session:
            # Check if repository already exists
            existing = (
                session.query(Repository)
                .filter(Repository.full_name == full_name)
                .first()
            )

            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Repository already exists",
                )

            # Fetch repository info from GitHub
            config = Config.load()
            github_client = GitHubClient(config.github_token)
            repo_data = github_client.get_repository(owner, name)

            # Create new repository
            new_repo = Repository(
                full_name=full_name,
                description=repo_data.get("description"),
                html_url=repo_data.get("html_url"),
                language=repo_data.get("language"),
                stars=repo_data.get("stargazers_count", 0),
                forks=repo_data.get("forks_count", 0),
                is_active=True,
            )

            # Categorize the repository
            categorizer = Categorizer(config.categories_config_path)
            category_result = categorizer.categorize_repository(
                full_name=full_name,
                description=repo_data.get("description") or "",
                language=repo_data.get("language") or "",
            )
            new_repo.category = category_result.category_name

            session.add(new_repo)
            session.commit()
            session.refresh(new_repo)

            logger.info("Created repository: %s", full_name)

            return RepositoryResponse.model_validate(new_repo)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creating repository: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.put("/repositories/{repo_id}", response_model=RepositoryResponse)
async def update_repository(repo_id: int, request: dict):
    """Update a repository."""
    from github_stars.models import Repository

    try:
        owner = request.get("owner")
        name = request.get("name")
        category = request.get("category")

        with get_db_session() as session:
            repository = session.get(Repository, repo_id)

            if not repository:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Repository with ID {repo_id} not found",
                )

            # Update fields if provided
            if owner and name:
                old_full_name = repository.full_name
                new_full_name = f"{owner}/{name}"

                repository.full_name = new_full_name

                # Re-fetch from GitHub to update stats
                config = Config.load()
                github_client = GitHubClient(config.github_token)
                repo_data = github_client.get_repository(owner, name)

                repository.description = repo_data.get("description")
                repository.html_url = repo_data.get("html_url")
                repository.language = repo_data.get("language")
                repository.stars = repo_data.get("stargazers_count", 0)
                repository.forks = repo_data.get("forks_count", 0)

                # Update category if provided
                if category:
                    repository.category = category
                elif category is not None:
                    # Recategorize
                    categorizer = Categorizer(config.categories_config_path)
                    result = categorizer.categorize_repository(
                        full_name=new_full_name,
                        description=repository.description or "",
                        language=repository.language or "",
                    )
                    repository.category = result.category_name

            session.commit()
            session.refresh(repository)

            logger.info("Updated repository: %s", repository.full_name)

            return RepositoryResponse.model_validate(repository)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating repository %d: %s", repo_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.delete("/repositories/{repo_id}", response_model=dict)
async def delete_repository(repo_id: int):
    """Delete a repository and its associated stars."""
    from github_stars.models import Repository, Star

    try:
        with get_db_session() as session:
            repository = session.get(Repository, repo_id)

            if not repository:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Repository with ID {repo_id} not found",
                )

            # Delete associated stars
            session.query(Star).filter(Star.repository_id == repo_id).delete()

            # Delete repository
            session.delete(repository)
            session.commit()

            logger.info("Deleted repository: %s", repository.full_name)

            return {
                "status": "success",
                "message": f"Repository {repository.full_name} deleted",
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting repository %d: %s", repo_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.get("/activity/recent", response_model=list[dict])
async def get_recent_activity(
    days: int = Query(7, ge=1, le=365, description="Number of days"),
    limit: int = Query(50, ge=1, le=500, description="Maximum results"),
):
    """Get recent activity (new stars)."""
    from github_stars.models import Star

    try:
        with get_db_session() as session:
            from datetime import timedelta

            cutoff_date = datetime.utcnow() - timedelta(days=days)

            stars = (
                session.query(Star)
                .filter(Star.starred_at >= cutoff_date)
                .order_by(Star.starred_at.desc())
                .limit(limit)
                .all()
            )

            result = []
            for star in stars:
                result.append(
                    {
                        "id": star.id,
                        "type": "star",
                        "message": f"New star on {star.repository.full_name if star.repository else 'Unknown'}",
                        "timestamp": star.starred_at.isoformat(),
                    }
                )

            return result

    except Exception as e:
        logger.error("Error getting recent activity: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )
