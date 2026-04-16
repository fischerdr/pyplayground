"""Database models for GitHub Stars Dashboard."""

import logging
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

logger = logging.getLogger(__name__)

Base = declarative_base()


class Category(Base):  # type: ignore[misc, valid-type]
    """Category model for organizing repositories.

    Attributes:
        id: Primary key.
        name: Category name.
        pattern: Regex pattern for matching repository names.
        priority: Category priority (lower = higher priority).
        created_at: Creation timestamp.
    """

    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    pattern = Column(String(255), nullable=False)
    priority = Column(Integer, default=100)
    created_at = Column(DateTime, default=datetime.utcnow)

    repositories = relationship(
        "Repository",
        back_populates="category",
        lazy="dynamic",
    )

    __table_args__ = (
        Index("ix_categories_name", "name"),
        Index("ix_categories_priority", "priority"),
    )

    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name='{self.name}', priority={self.priority})>"

    def to_dict(self) -> dict:
        """Convert model to dictionary.

        Returns:
            Dictionary representation of the model.
        """
        return {
            "id": self.id,
            "name": self.name,
            "pattern": self.pattern,
            "priority": self.priority,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Repository(Base):  # type: ignore[misc, valid-type]
    """Repository model for tracking GitHub repositories.

    Attributes:
        id: Primary key.
        full_name: Repository full name (owner/repo).
        description: Repository description.
        html_url: Repository URL.
        stars_count: Number of stars.
        forks_count: Number of forks.
        language: Primary programming language.
        category_id: Foreign key to Category.
        is_active: Whether repository is actively tracked.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    html_url = Column(String(500), nullable=False)
    stars_count = Column(Integer, default=0)
    forks_count = Column(Integer, default=0)
    language = Column(String(100), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("Category", back_populates="repositories")
    stars = relationship(
        "Star",
        back_populates="repository",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_repositories_full_name", "full_name"),
        Index("ix_repositories_stars_count", "stars_count"),
        Index("ix_repositories_is_active", "is_active"),
        Index("ix_repositories_category_id", "category_id"),
        Index("ix_repositories_language", "language"),
    )

    def __repr__(self) -> str:
        return f"<Repository(id={self.id}, full_name='{self.full_name}')>"

    def to_dict(self) -> dict:
        """Convert model to dictionary.

        Returns:
            Dictionary representation of the model.
        """
        return {
            "id": self.id,
            "full_name": self.full_name,
            "description": self.description,
            "html_url": self.html_url,
            "stars_count": self.stars_count,
            "forks_count": self.forks_count,
            "language": self.language,
            "category_id": self.category_id,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Star(Base):  # type: ignore[misc, valid-type]
    """Star model for tracking star events.

    Attributes:
        id: Primary key.
        repository_id: Foreign key to Repository.
        starred_at: When the star was recorded.
        is_new: Whether this is a new star event.
    """

    __tablename__ = "stars"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    starred_at = Column(DateTime, default=datetime.utcnow)
    is_new = Column(Boolean, default=True)

    repository = relationship("Repository", back_populates="stars")

    __table_args__ = (
        Index("ix_stars_repository_id", "repository_id"),
        Index("ix_stars_starred_at", "starred_at"),
        Index("ix_stars_is_new", "is_new"),
    )

    def __repr__(self) -> str:
        return f"<Star(id={self.id}, repository_id={self.repository_id}, starred_at={self.starred_at})>"

    def to_dict(self) -> dict:
        """Convert model to dictionary.

        Returns:
            Dictionary representation of the model.
        """
        return {
            "id": self.id,
            "repository_id": self.repository_id,
            "starred_at": self.starred_at.isoformat() if self.starred_at else None,
            "is_new": self.is_new,
        }


class ActivityLog(Base):  # type: ignore[misc, valid-type]
    """Activity log model for tracking operations.

    Attributes:
        id: Primary key.
        action: Action type (e.g., 'update', 'delete', 'create').
        details: Action details as JSON string.
        created_at: When the action occurred.
    """

    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_activity_logs_action", "action"),
        Index("ix_activity_logs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ActivityLog(id={self.id}, action='{self.action}', created_at={self.created_at})>"

    def to_dict(self) -> dict:
        """Convert model to dictionary.

        Returns:
            Dictionary representation of the model.
        """
        return {
            "id": self.id,
            "action": self.action,
            "details": self.details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
