"""Auto-categorization engine for GitHub repositories.

This module provides functionality to automatically categorize repositories
based on pattern matching against category configurations.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from github_stars.models import Category, Repository

logger = logging.getLogger(__name__)


@dataclass
class CategoryConfig:
    """Configuration for a category.

    Attributes:
        name: Category name.
        pattern: Regex pattern to match repositories.
        priority: Priority order for matching (lower = higher priority).
    """

    name: str
    pattern: str
    priority: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "name": self.name,
            "pattern": self.pattern,
            "priority": self.priority,
        }


@dataclass
class CategorizationResult:
    """Result of categorizing a repository.

    Attributes:
        category_name: Name of the matched category.
        confidence: Confidence score (0-1).
        matched_pattern: The regex pattern that matched.
    """

    category_name: str | None
    confidence: float
    matched_pattern: str | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "category_name": self.category_name,
            "confidence": self.confidence,
            "matched_pattern": self.matched_pattern,
        }


class Categorizer:
    """Auto-categorizer for GitHub repositories.

    Attributes:
        categories: List of CategoryConfig objects.
    """

    def __init__(self, config_file: str | None = None) -> None:
        """Initialize Categorizer.

        Args:
            config_file: Optional path to categories JSON file.
                        Defaults to config/categories.json in project root.
        """
        if config_file is None:
            config_file = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "config",
                "categories.json",
            )

        self.categories: list[CategoryConfig] = []
        self._load_default_categories(config_file)
        logger.debug("Categorizer initialized with %d categories", len(self.categories))

    def _load_default_categories(self, config_file: str) -> None:
        """Load default categories from config file.

        Args:
            config_file: Path to categories JSON file.
        """
        path = Path(config_file)
        if not path.exists():
            logger.warning("Category config file not found: %s", config_file)
            self._create_builtin_categories()
            return

        try:
            with open(path, encoding="utf-8") as f:
                config = json.load(f)

            # Handle both list format and dict with "categories" key
            if isinstance(config, list):
                categories_data = config
            else:
                categories_data = config.get("categories", [])

            for cat_data in categories_data:
                name = cat_data.get("name", "")
                # Support both 'patterns' (list) and 'pattern' (single string)
                patterns = cat_data.get("patterns", [])
                pattern = cat_data.get("pattern", None)

                # If pattern is a string, convert to list
                if pattern and isinstance(pattern, str):
                    patterns = [pattern]

                priority = cat_data.get("priority", 100)

                # For catch-all categories (priority >= 100), use a default pattern
                if not patterns:
                    if priority >= 100:
                        patterns = [".*"]  # Catch-all pattern
                    else:
                        continue  # Skip categories without patterns

                # Use first pattern as the main pattern
                main_pattern = patterns[0]
                self.categories.append(
                    CategoryConfig(name=name, pattern=main_pattern, priority=priority)
                )

            # Sort by priority
            self.categories.sort(key=lambda x: x.priority)
            logger.info(
                "Loaded %d categories from %s", len(self.categories), config_file
            )

        except (json.JSONDecodeError, IOError) as e:
            logger.error("Failed to load categories: %s", e)
            self._create_builtin_categories()

    def _create_builtin_categories(self) -> None:
        """Create builtin categories if config file is not found."""
        builtin = [
            CategoryConfig(name="python", pattern=r".*python.*", priority=1),
            CategoryConfig(name="javascript", pattern=r".*javascript.*", priority=2),
            CategoryConfig(name="web", pattern=r".*web.*", priority=3),
            CategoryConfig(name="api", pattern=r".*api.*", priority=4),
            CategoryConfig(name="database", pattern=r".*database.*", priority=5),
            CategoryConfig(name="ml-ai", pattern=r".*ml.*", priority=6),
            CategoryConfig(name="devops", pattern=r".*devops.*", priority=7),
            CategoryConfig(name="infra", pattern=r".*infra.*", priority=8),
            CategoryConfig(name="tools", pattern=r".*tool.*", priority=9),
            CategoryConfig(name="framework", pattern=r".*framework.*", priority=10),
            CategoryConfig(name="library", pattern=r".*lib.*", priority=11),
            CategoryConfig(name="application", pattern=r".*app.*", priority=12),
            CategoryConfig(name="utility", pattern=r".*util.*", priority=13),
            CategoryConfig(name="other", pattern=r".*", priority=100),
        ]
        self.categories = builtin
        logger.info("Created %d builtin categories", len(self.categories))

    def categorize_repository(
        self,
        full_name: str,
        description: str,
        language: str,
    ) -> CategorizationResult:
        """Categorize a repository based on name, description, and language.

        Args:
            full_name: Repository full name (e.g., 'facebook/react').
            description: Repository description.
            language: Repository programming language.

        Returns:
            CategorizationResult with matched category and confidence.
        """
        # Combine all text for matching
        text_to_search = f"{full_name} {description} {language}".lower()

        best_match: CategorizationResult | None = None
        best_priority = float("inf")

        for category in self.categories:
            try:
                if self._validate_pattern(category.pattern):
                    compiled = re.compile(category.pattern, re.IGNORECASE)
                    if compiled.search(text_to_search):
                        # Calculate confidence based on where match occurs
                        confidence = 0.3  # Base confidence

                        # Higher confidence for full_name match
                        if compiled.search(full_name.lower()):
                            confidence = 0.9
                        # Medium confidence for description match
                        elif compiled.search(description.lower()):
                            confidence = 0.7
                        # Lower confidence for language match
                        elif compiled.search(language.lower()):
                            confidence = 0.5

                        # Higher confidence for higher priority categories
                        confidence = min(confidence, 1.0 - (category.priority * 0.01))

                        if category.priority < best_priority:
                            best_priority = category.priority
                            best_match = CategorizationResult(
                                category_name=category.name,
                                confidence=confidence,
                                matched_pattern=category.pattern,
                            )

            except re.error as e:
                logger.warning("Invalid pattern for category %s: %s", category.name, e)
                continue

        # If no match found, check if we have a catch-all category (priority 100)
        if best_match is None:
            for category in self.categories:
                if category.priority == 100:
                    best_match = CategorizationResult(
                        category_name=category.name,
                        confidence=0.1,
                        matched_pattern=category.pattern,
                    )
                    break

        if best_match:
            logger.debug(
                "Categorized '%s' as '%s' (confidence: %.2f, pattern: %s)",
                full_name,
                best_match.category_name,
                best_match.confidence,
                best_match.matched_pattern,
            )
        else:
            # Return no match result
            best_match = CategorizationResult(
                category_name=None,
                confidence=0.0,
                matched_pattern=None,
            )
            logger.debug("No category matched for '%s'", full_name)

        return best_match

    def get_category_patterns(self) -> list[dict[str, Any]]:
        """Get all category patterns.

        Returns:
            List of dicts with name, pattern, and priority.
        """
        return [
            {"name": cat.name, "pattern": cat.pattern, "priority": cat.priority}
            for cat in self.categories
        ]

    def get_stats(self) -> dict[str, Any]:
        """Get categorization statistics.

        Returns:
            Dict with total_categories, high_priority_count,
            medium_priority_count, low_priority_count.
        """
        high_priority = sum(1 for cat in self.categories if cat.priority <= 5)
        medium_priority = sum(1 for cat in self.categories if 5 < cat.priority <= 10)
        low_priority = sum(1 for cat in self.categories if cat.priority > 10)

        return {
            "total_categories": len(self.categories),
            "high_priority_count": high_priority,
            "medium_priority_count": medium_priority,
            "low_priority_count": low_priority,
        }

    def _validate_pattern(self, pattern: str) -> bool:
        """Validate a regex pattern.

        Args:
            pattern: Regex pattern string.

        Returns:
            True if valid, False otherwise.
        """
        try:
            re.compile(pattern)
            return True
        except re.error:
            return False

    def add_category(self, name: str, pattern: str, priority: int = 100) -> None:
        """Add a new category.

        Args:
            name: Category name.
            pattern: Regex pattern.
            priority: Category priority (lower = higher priority).
        """
        if self._validate_pattern(pattern):
            self.categories.append(
                CategoryConfig(name=name, pattern=pattern, priority=priority)
            )
            self.categories.sort(key=lambda x: x.priority)
            logger.info("Added category: %s (priority: %d)", name, priority)
        else:
            logger.error("Invalid pattern for category: %s", name)

    def to_dict(self) -> dict[str, Any]:
        """Convert categorizer to dictionary.

        Returns:
            Dictionary with categories and patterns.
        """
        return {
            "categories": [cat.to_dict() for cat in self.categories],
            "patterns": self.get_category_patterns(),
            "stats": self.get_stats(),
        }


class CategoryManager:
    """Manager for Category model CRUD operations.

    Attributes:
        session: Database session.
    """

    def __init__(self, session: Session) -> None:
        """Initialize CategoryManager.

        Args:
            session: Database session.
        """
        self.session = session
        logger.debug("CategoryManager initialized")

    def create_category(self, name: str, pattern: str, priority: int = 100) -> Category:
        """Create a new category.

        Args:
            name: Category name.
            pattern: Regex pattern for matching.
            priority: Category priority (lower = higher priority).

        Returns:
            Created Category instance.

        Raises:
            ValueError: If category already exists.
        """
        logger.info("Creating category: %s (priority: %d)", name, priority)

        existing = self.get_category_by_name(name)
        if existing:
            error_msg = f"Category already exists: {name}"
            logger.warning(error_msg)
            raise ValueError(error_msg)

        category = Category(
            name=name,
            pattern=pattern,
            priority=priority,
        )

        self.session.add(category)
        self.session.commit()

        logger.info("Created category: %s with id %d", name, category.id)
        return category

    def get_category_by_id(self, category_id: int) -> Category | None:
        """Get category by ID.

        Args:
            category_id: Category ID.

        Returns:
            Category instance or None.
        """
        return self.session.query(Category).filter_by(id=category_id).first()

    def get_category_by_name(self, name: str) -> Category | None:
        """Get category by name.

        Args:
            name: Category name.

        Returns:
            Category instance or None.
        """
        return self.session.query(Category).filter_by(name=name).first()

    def update_category(self, category_id: int, **kwargs: Any) -> Category | None:
        """Update category fields.

        Args:
            category_id: Category ID.
            **kwargs: Fields to update.

        Returns:
            Updated Category instance or None.
        """
        category = self.get_category_by_id(category_id)
        if not category:
            logger.warning("Category not found for update: %d", category_id)
            return None

        logger.info("Updating category: %d", category_id)

        for field, value in kwargs.items():
            if hasattr(category, field):
                setattr(category, field, value)
                logger.debug("Updated %s to: %s", field, value)

        self.session.commit()
        return category

    def delete_category(self, category_id: int) -> bool:
        """Delete a category.

        Args:
            category_id: Category ID.

        Returns:
            True if deleted, False if not found.
        """
        category = self.get_category_by_id(category_id)
        if not category:
            logger.warning("Category not found for deletion: %d", category_id)
            return False

        logger.info("Deleting category: %d (%s)", category_id, category.name)

        self.session.delete(category)
        self.session.commit()
        return True

    def list_categories(self) -> list[Category]:
        """List all categories ordered by priority.

        Returns:
            List of Category instances.
        """
        categories = (
            self.session.query(Category)
            .order_by(Category.priority, Category.name)
            .all()
        )
        logger.debug("Found %d categories", len(categories))
        return categories

    def get_or_create_category(
        self, name: str, pattern: str, priority: int = 100
    ) -> Category:
        """Get existing category or create new one.

        Args:
            name: Category name.
            pattern: Regex pattern.
            priority: Category priority.

        Returns:
            Category instance (existing or newly created).
        """
        existing = self.get_category_by_name(name)
        if existing:
            logger.debug("Category already exists: %s", name)
            return existing

        logger.info("Creating new category: %s", name)
        return self.create_category(name, pattern, priority)

    def get_category_for_repository(self, repository: Repository) -> Category | None:
        """Get or set category for a repository.

        Args:
            repository: Repository instance.

        Returns:
            Category instance or None.
        """
        if repository.category_id:
            return self.get_category_by_id(int(repository.category_id))

        result = categorize_repository(repository, self)
        if result.matched_category:
            category = self.get_or_create_category(
                result.matched_category, result.pattern_matched or ".*", result.priority
            )
            repository.category_id = category.id
            self.session.commit()
            return category

        return None


class CategoryConfigLoader:
    """Load category configurations from JSON files.

    Attributes:
        config_path: Path to categories configuration file.
    """

    def __init__(self, config_path: str | None = None) -> None:
        """Initialize CategoryConfigLoader.

        Args:
            config_path: Path to categories JSON file.
                        Defaults to config/categories.json in project root.
        """
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "config",
                "categories.json",
            )

        self.config_path = config_path
        self.categories: list[dict[str, Any]] = []
        logger.debug("CategoryConfigLoader initialized with path: %s", config_path)

    def load(self) -> list[dict[str, Any]]:
        """Load categories from configuration file.

        Returns:
            List of category configurations.

        Raises:
            FileNotFoundError: If config file doesn't exist.
            json.JSONDecodeError: If config file is invalid JSON.
        """
        logger.info("Loading categories from: %s", self.config_path)

        path = Path(self.config_path)
        if not path.exists():
            error_msg = f"Category config file not found: {self.config_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        with open(path, encoding="utf-8") as f:
            config = json.load(f)

        self.categories = config.get("categories", [])
        logger.info("Loaded %d categories from configuration", len(self.categories))

        for category in self.categories:
            logger.debug(
                "Category: %s (priority: %d, patterns: %d)",
                category["name"],
                category.get("priority", 100),
                len(category.get("patterns", [])),
            )

        return self.categories

    def get_categories_by_priority(self) -> list[dict[str, Any]]:
        """Get categories sorted by priority.

        Returns:
            List of category configurations sorted by priority.
        """
        if not self.categories:
            self.load()

        return sorted(self.categories, key=lambda x: x.get("priority", 100))


def categorize_repository(
    repository: Repository,
    category_manager: CategoryManager | None = None,
    config_loader: CategoryConfigLoader | None = None,
    manual_override: str | None = None,
) -> CategorizationResult:
    """Categorize a repository based on pattern matching.

    Args:
        repository: Repository instance to categorize.
        category_manager: Optional CategoryManager for database operations.
        config_loader: Optional CategoryConfigLoader for loading patterns.
        manual_override: Optional manual category name override.

    Returns:
        CategorizationResult with matched category info.
    """
    repo_name = repository.full_name.lower()
    repo_description = (repository.description or "").lower()
    search_text = f"{repo_name} {repo_description}"

    logger.debug(
        "Categorizing repository: %s (text: %s)",
        repository.full_name,
        search_text[:100],
    )

    if manual_override:
        logger.info(
            "Using manual override for repository %s: %s",
            repository.full_name,
            manual_override,
        )
        return CategorizationResult(
            category_name=manual_override,
            confidence=1.0,
            matched_pattern="manual",
        )

    categories = []

    if category_manager:
        categories = category_manager.list_categories()
        logger.debug("Found %d categories in database", len(categories))

    if not categories and config_loader and category_manager:
        config_categories = config_loader.get_categories_by_priority()
        for cat in config_categories:
            category = category_manager.get_or_create_category(
                cat["name"],
                cat["patterns"][0] if cat["patterns"] else ".*",
                cat.get("priority", 100),
            )
            categories.append(category)

    if not categories:
        logger.warning("No categories found for repository: %s", repository.full_name)
        return CategorizationResult(
            category_name=None,
            confidence=0.0,
            matched_pattern=None,
        )

    best_match: CategorizationResult | None = None

    for category in categories:
        try:
            pattern = str(category.pattern)
            compiled_pattern = re.compile(pattern, re.IGNORECASE)

            if compiled_pattern.search(search_text):
                logger.debug(
                    "Matched category '%s' (priority: %d) for repo '%s' with pattern '%s'",
                    category.name,
                    category.priority,
                    repository.full_name,
                    pattern,
                )

                match_result = CategorizationResult(
                    category_name=str(category.name),
                    confidence=0.8,
                    matched_pattern=pattern,
                )

                if not best_match or match_result.priority < best_match.priority:
                    best_match = match_result

        except re.error as e:
            logger.error(
                "Invalid regex pattern in category '%s': %s",
                category.name,
                e,
            )
            continue

    if best_match:
        logger.info(
            "Selected best match for repository %s: %s (priority: %d, confidence: %.1f)",
            repository.full_name,
            best_match.category_name,
            best_match.priority,
            best_match.confidence,
        )
    else:
        logger.debug("No category matched for repository: %s", repository.full_name)

    return best_match or CategorizationResult(
        category_name=None,
        confidence=0.0,
        matched_pattern=None,
    )


def update_repository_category(
    repository: Repository,
    session: Session,
    manual_override: str | None = None,
) -> CategorizationResult:
    """Update a repository's category based on current patterns.

    Args:
        repository: Repository instance to update.
        session: Database session.
        manual_override: Optional manual category override.

    Returns:
        CategorizationResult with the new category.
    """
    logger.info("Updating category for repository: %s", repository.full_name)

    category_manager = CategoryManager(session)
    result = categorize_repository(repository, category_manager, None, manual_override)

    if result.category_name:
        category = category_manager.get_or_create_category(
            result.category_name, result.matched_pattern or ".*", result.priority
        )
        repository.category_id = category.id
        session.commit()

        logger.info(
            "Updated repository %s category to: %s",
            repository.full_name,
            category.name,
        )
    else:
        repository.category_id = None  # type: ignore[assignment]
        session.commit()
        logger.info("Removed category from repository: %s", repository.full_name)

    return result


def load_categories_from_config(
    session: Session, config_path: str | None = None
) -> int:
    """Load categories from config file into database.

    Args:
        session: Database session.
        config_path: Optional path to config file.

    Returns:
        Number of categories created/updated.
    """
    logger.info("Loading categories from config into database")

    category_manager = CategoryManager(session)
    config_loader = CategoryConfigLoader(config_path)

    try:
        config_categories = config_loader.load()
    except FileNotFoundError:
        logger.warning("No config file found, using empty categories")
        return 0

    created_count = 0
    updated_count = 0

    for cat_config in config_categories:
        try:
            name = cat_config["name"]
            patterns = cat_config.get("patterns", [])
            priority = cat_config.get("priority", 100)

            if not patterns:
                logger.warning("Category '%s' has no patterns, skipping", name)
                continue

            # Use first pattern as primary
            primary_pattern = patterns[0]

            existing = category_manager.get_category_by_name(name)
            if existing:
                category_manager.update_category(
                    int(existing.id),
                    pattern=primary_pattern,
                    priority=priority,
                )
                updated_count += 1
                logger.debug("Updated category: %s", name)
            else:
                category_manager.create_category(name, primary_pattern, priority)
                created_count += 1
                logger.debug("Created category: %s", name)

        except KeyError as e:
            logger.error("Invalid category config: %s", e)
            continue
        except ValueError as e:
            logger.warning("Could not create category: %s", e)
            continue

    logger.info(
        "Loaded %d categories: %d created, %d updated",
        created_count + updated_count,
        created_count,
        updated_count,
    )

    return created_count + updated_count
