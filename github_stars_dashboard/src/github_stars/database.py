"""Database configuration and initialization."""

import logging
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from github_stars.models import Base

logger = logging.getLogger(__name__)


def get_database_url() -> str:
    """Get database URL from environment or use default.

    Returns:
        Database URL string.
    """
    import os

    return os.getenv("DATABASE_URL", "sqlite:///./github_stars.db")


def create_database_engine(database_url: str | None = None) -> Engine:
    """Create SQLAlchemy engine instance.

    Args:
        database_url: Optional database URL. If not provided, uses environment variable.

    Returns:
        SQLAlchemy engine class.

    Raises:
        ValueError: If database URL is invalid.
    """
    try:
        if database_url is None:
            database_url = get_database_url()

        if database_url.startswith("sqlite"):
            engine = create_engine(
                database_url,
                connect_args={"check_same_thread": False},
                echo=False,
            )
        else:
            engine = create_engine(database_url, echo=False)

        logger.debug(f"Database engine created for: {database_url}")
        return engine
    except Exception as e:
        logger.error(f"Failed to create database engine: {e}")
        raise ValueError(f"Invalid database URL: {database_url}") from e


def create_engine_instance(database_url: str | None = None) -> Engine:
    """Alias for create_database_engine for backward compatibility."""
    return create_database_engine(database_url)


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create session factory from engine.

    Args:
        engine: SQLAlchemy engine instance.

    Returns:
        Session factory class.
    """
    try:
        session_factory = sessionmaker(
            bind=engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
        logger.debug("Session factory created successfully")
        return session_factory
    except Exception as e:
        logger.error(f"Failed to create session factory: {e}")
        raise


def init_database(engine: Engine) -> None:
    """Initialize database by creating all tables.

    Args:
        engine: SQLAlchemy engine instance.

    Raises:
        Exception: If database initialization fails.
    """
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


def get_session(engine: Engine) -> Generator[Session, None, None]:
    """Get database session generator.

    Args:
        engine: SQLAlchemy engine instance.

    Yields:
        Database session.
    """
    session_factory = get_session_factory(engine)
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_session(database_url: str | None = None) -> Session:
    """Get a database session.

    Args:
        database_url: Optional database URL.

    Returns:
        Database session.
    """
    engine = create_database_engine(database_url)
    session_factory = get_session_factory(engine)
    return session_factory()
