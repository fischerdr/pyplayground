"""Tests for Categorizer in categorizer.py."""

from datetime import UTC, datetime

import pytest

from github_stars.categorizer import (
    CategorizationResult,
    CategoryConfig,
    Categorizer,
)


class TestCategoryConfig:
    """Tests for CategoryConfig class."""

    def test_init(self):
        """Test CategoryConfig initialization."""
        config = CategoryConfig(
            name="python",
            pattern=r".*python.*",
            priority=1,
        )

        assert config.name == "python"
        assert config.pattern == r".*python.*"
        assert config.priority == 1

    def test_to_dict(self):
        """Test CategoryConfig to_dict method."""
        config = CategoryConfig(
            name="python",
            pattern=r".*python.*",
            priority=1,
        )

        result = config.to_dict()

        assert result["name"] == "python"
        assert result["pattern"] == r".*python.*"
        assert result["priority"] == 1


class TestCategorizationResult:
    """Tests for CategorizationResult class."""

    def test_init(self):
        """Test CategorizationResult initialization."""
        result = CategorizationResult(
            category_name="python",
            confidence=0.9,
            matched_pattern=r".*python.*",
        )

        assert result.category_name == "python"
        assert result.confidence == 0.9
        assert result.matched_pattern == r".*python.*"

    def test_to_dict(self):
        """Test CategorizationResult to_dict method."""
        result = CategorizationResult(
            category_name="python",
            confidence=0.9,
            matched_pattern=r".*python.*",
        )

        dict_result = result.to_dict()

        assert dict_result["category_name"] == "python"
        assert dict_result["confidence"] == 0.9
        assert dict_result["matched_pattern"] == r".*python.*"


class TestCategorizer:
    """Tests for Categorizer class."""

    def test_init(self):
        """Test Categorizer initialization."""
        categorizer = Categorizer()

        assert categorizer.categories is not None
        assert len(categorizer.categories) > 0

    def test_categorize_repository_matching_pattern(self):
        """Test categorizing a repository that matches a pattern."""
        categorizer = Categorizer()

        result = categorizer.categorize_repository(
            full_name="facebook/react",
            description="A declarative, efficient, and flexible JavaScript library for building user interfaces",
            language="JavaScript",
        )

        assert result.category_name is not None
        assert result.confidence > 0

    def test_categorize_repository_no_match(self):
        """Test categorizing a repository that doesn't match any pattern."""
        categorizer = Categorizer()

        # Create a categorizer with no matching categories
        from github_stars.categorizer import CategoryConfig

        categorizer.categories = [
            CategoryConfig(name="special", pattern=r"^special.*", priority=1)
        ]

        result = categorizer.categorize_repository(
            full_name="random/repo",
            description="Random repository",
            language="Python",
        )

        assert result.category_name is None
        assert result.confidence == 0.0

    def test_categorize_by_full_name(self):
        """Test categorization based on full name pattern."""
        categorizer = Categorizer()

        result = categorizer.categorize_repository(
            full_name="pydantic/pydantic",
            description="",
            language="Python",
        )

        # Should match python framework pattern
        assert result.category_name is not None
        assert result.confidence > 0

    def test_categorize_by_description(self):
        """Test categorization based on description pattern."""
        categorizer = Categorizer()

        result = categorizer.categorize_repository(
            full_name="test/repo",
            description="This is a machine learning project using TensorFlow",
            language="Python",
        )

        # Should match ML/AI pattern
        assert result.category_name is not None
        assert result.confidence > 0

    def test_categorize_by_language(self):
        """Test categorization based on language."""
        categorizer = Categorizer()

        result = categorizer.categorize_repository(
            full_name="test/repo",
            description="",
            language="Go",
        )

        # Should match go pattern
        assert result.category_name is not None
        assert result.confidence > 0

    def test_categorize_priority_ordering(self):
        """Test that higher priority categories are checked first."""
        categorizer = Categorizer()

        # All categories should be sorted by priority
        priorities = [cat.priority for cat in categorizer.categories]
        assert priorities == sorted(priorities)

    def test_get_category_patterns(self):
        """Test getting category patterns."""
        categorizer = Categorizer()

        patterns = categorizer.get_category_patterns()

        assert isinstance(patterns, list)
        assert len(patterns) > 0

        for pattern_info in patterns:
            assert "name" in pattern_info
            assert "pattern" in pattern_info
            assert "priority" in pattern_info

    def test_get_stats(self):
        """Test getting categorization statistics."""
        categorizer = Categorizer()

        stats = categorizer.get_stats()

        assert "total_categories" in stats
        assert "high_priority_count" in stats
        assert "medium_priority_count" in stats
        assert "low_priority_count" in stats

        assert stats["total_categories"] == len(categorizer.categories)

    def test_validate_pattern(self):
        """Test pattern validation."""
        categorizer = Categorizer()

        # Valid pattern
        assert categorizer._validate_pattern(r".*test.*") is True

        # Invalid pattern (unclosed bracket)
        assert categorizer._validate_pattern(r"[test") is False

    def test_load_categories_from_file(self, tmp_path):
        """Test loading categories from a JSON file."""
        import json

        categories_data = [
            {
                "name": "test_category",
                "pattern": r".*test.*",
                "priority": 1,
            }
        ]

        config_file = tmp_path / "test_categories.json"
        config_file.write_text(json.dumps(categories_data))

        categorizer = Categorizer(config_file=str(config_file))

        assert len(categorizer.categories) == 1
        assert categorizer.categories[0].name == "test_category"

    def test_load_categories_default(self):
        """Test loading default categories."""
        categorizer = Categorizer()

        assert len(categorizer.categories) > 0

        # Check for expected default categories
        category_names = [cat.name for cat in categorizer.categories]
        expected_categories = [
            "python",
            "javascript",
            "web",
            "api",
            "database",
            "ml-ai",
            "devops",
            "infra",
            "tools",
            "framework",
            "library",
            "application",
            "utility",
            "other",
        ]

        for expected in expected_categories:
            assert expected in category_names

    def test_categorize_empty_inputs(self):
        """Test categorizing with empty inputs."""
        categorizer = Categorizer()

        result = categorizer.categorize_repository(
            full_name="",
            description="",
            language="",
        )

        # Should still return a result, possibly with low confidence
        assert result.category_name is not None or result.confidence >= 0

    def test_categorize_case_insensitive(self):
        """Test that categorization is case insensitive."""
        categorizer = Categorizer()

        result1 = categorizer.categorize_repository(
            full_name="TEST/REPO",
            description="Test Description",
            language="PYTHON",
        )

        result2 = categorizer.categorize_repository(
            full_name="test/repo",
            description="test description",
            language="python",
        )

        # Results should be similar
        assert result1.category_name == result2.category_name
        assert abs(result1.confidence - result2.confidence) < 0.01

    def test_categorize_special_characters(self):
        """Test categorizing with special characters."""
        categorizer = Categorizer()

        result = categorizer.categorize_repository(
            full_name="test/repo-with_special.chars",
            description="Test with special chars: @#$%",
            language="Python",
        )

        assert result.category_name is not None
        assert result.confidence >= 0

    def test_categorize_long_description(self):
        """Test categorizing with a very long description."""
        categorizer = Categorizer()

        long_description = "This is a " * 1000
        result = categorizer.categorize_repository(
            full_name="test/repo",
            description=long_description,
            language="Python",
        )

        assert result.category_name is not None
        assert result.confidence >= 0

    def test_categorize_unicode(self):
        """Test categorizing with unicode characters."""
        categorizer = Categorizer()

        result = categorizer.categorize_repository(
            full_name="测试/仓库",
            description="测试描述",
            language="中文",
        )

        assert result.category_name is not None
        assert result.confidence >= 0
