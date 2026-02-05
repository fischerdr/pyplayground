#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for ansible_structure_analyzer.py"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from pyplayground.ansible_structure_analyzer import (
    AnsibleStructureAnalyzer,
    ErrorCollector,
    FileDiscovery,
    IncludeResolver,
    OutputGenerator,
    StructureBuilder,
    TemplateFinder,
)


class TestFileDiscovery:
    """Tests for FileDiscovery class."""

    def test_discover_files_single_file(self, tmp_path):
        """Test discovering a single playbook file."""
        discovery = FileDiscovery()
        playbook_file = tmp_path / "playbook.yml"
        playbook_file.write_text("---\n- hosts: all\n  tasks: []\n")

        result = discovery.discover_files(playbook_file)

        assert len(result) == 1
        assert result[0] == playbook_file

    def test_discover_files_directory(self, tmp_path):
        """Test discovering files from a directory."""
        discovery = FileDiscovery()
        playbook1 = tmp_path / "playbook1.yml"
        playbook2 = tmp_path / "playbook2.yaml"
        other_file = tmp_path / "other.txt"

        playbook1.write_text("---\n- hosts: all\n")
        playbook2.write_text("---\n- hosts: all\n")
        other_file.write_text("not a playbook")

        result = discovery.discover_files(tmp_path)

        assert len(result) == 2
        assert playbook1 in result
        assert playbook2 in result
        assert other_file not in result

    def test_discover_files_nonexistent(self):
        """Test discovering files from non-existent path."""
        discovery = FileDiscovery()
        nonexistent = Path("/nonexistent/path")

        with pytest.raises(FileNotFoundError):
            discovery.discover_files(nonexistent)

    def test_is_playbook_file(self, tmp_path):
        """Test is_playbook_file validation."""
        discovery = FileDiscovery()

        yml_file = tmp_path / "test.yml"
        yaml_file = tmp_path / "test.yaml"
        txt_file = tmp_path / "test.txt"
        dir_path = tmp_path / "subdir"

        yml_file.write_text("test")
        yaml_file.write_text("test")
        txt_file.write_text("test")
        dir_path.mkdir()

        assert discovery.is_playbook_file(yml_file) is True
        assert discovery.is_playbook_file(yaml_file) is True
        assert discovery.is_playbook_file(txt_file) is False
        assert discovery.is_playbook_file(dir_path) is False


class TestErrorCollector:
    """Tests for ErrorCollector class."""

    def test_add_error(self):
        """Test adding errors to collector."""
        collector = ErrorCollector()

        collector.add_error("MISSING_FILE", "File not found", Path("/test.yml"))

        assert collector.has_errors() is True
        assert len(collector.get_errors()) == 1
        assert collector.get_errors()[0]["type"] == "MISSING_FILE"

    def test_no_errors_initially(self):
        """Test that collector starts with no errors."""
        collector = ErrorCollector()

        assert collector.has_errors() is False
        assert len(collector.get_errors()) == 0


class TestIncludeResolver:
    """Tests for IncludeResolver class."""

    def test_resolve_includes_max_depth(self, tmp_path):
        """Test that max depth is enforced."""
        repo_root = tmp_path
        error_collector = ErrorCollector()
        resolver = IncludeResolver(repo_root, error_collector, max_depth=2)

        # Create a simple playbook
        playbook = tmp_path / "playbook.yml"
        playbook.write_text("---\n- hosts: all\n  tasks: []\n")

        result = resolver.resolve_includes(playbook, depth=2)

        # Should not error at depth 2 (max_depth)
        assert "error" not in result or result.get("error") != "MAX_DEPTH_EXCEEDED"

    def test_resolve_includes_circular_dependency(self, tmp_path):
        """Test circular dependency detection."""
        repo_root = tmp_path
        error_collector = ErrorCollector()
        resolver = IncludeResolver(repo_root, error_collector)

        # Create a playbook that includes itself (circular)
        playbook = tmp_path / "playbook.yml"
        playbook.write_text("---\n- hosts: all\n  tasks:\n    - include_tasks: playbook.yml\n")

        visited = {playbook}
        result = resolver.resolve_includes(playbook, visited=visited, include_chain=[playbook])

        assert "error" in result or error_collector.has_errors()

    def test_find_role_path(self, tmp_path):
        """Test finding role paths."""
        repo_root = tmp_path
        error_collector = ErrorCollector()
        resolver = IncludeResolver(repo_root, error_collector)

        # Create role structure
        role_dir = tmp_path / "roles" / "test_role"
        role_dir.mkdir(parents=True)

        result = resolver._find_role_path("test_role")

        assert result == role_dir

    def test_find_role_path_not_found(self, tmp_path):
        """Test finding non-existent role."""
        repo_root = tmp_path
        error_collector = ErrorCollector()
        resolver = IncludeResolver(repo_root, error_collector)

        result = resolver._find_role_path("nonexistent_role")

        assert result is None
        assert error_collector.has_errors()


class TestTemplateFinder:
    """Tests for TemplateFinder class."""

    def test_find_templates_in_tasks(self, tmp_path):
        """Test finding templates in task list."""
        repo_root = tmp_path
        error_collector = ErrorCollector()
        finder = TemplateFinder(repo_root, error_collector)

        tasks = [
            {"name": "Template task", "template": {"src": "test.j2", "dest": "/tmp/test"}},
            {"name": "Other task", "command": "echo hello"},
        ]

        playbook_file = tmp_path / "playbook.yml"
        result = finder.find_templates(tasks, playbook_file)

        assert len(result) == 1
        assert result[0]["template"] == "test.j2"

    def test_scan_role_templates(self, tmp_path):
        """Test scanning role templates directory."""
        repo_root = tmp_path
        error_collector = ErrorCollector()
        finder = TemplateFinder(repo_root, error_collector)

        # Create role with templates
        role_dir = tmp_path / "roles" / "test_role"
        templates_dir = role_dir / "templates"
        templates_dir.mkdir(parents=True)

        template1 = templates_dir / "template1.j2"
        template2 = templates_dir / "template2.j2"
        template1.write_text("template content")
        template2.write_text("template content")

        result = finder.scan_role_templates(role_dir)

        assert len(result) == 2
        assert template1 in result
        assert template2 in result


class TestStructureBuilder:
    """Tests for StructureBuilder class."""

    def test_build_structure(self, tmp_path):
        """Test building structure from analysis results."""
        repo_root = tmp_path
        builder = StructureBuilder(repo_root)

        playbooks = [{"file": "playbook.yml", "includes": []}]
        roles = [{"name": "test_role", "path": "roles/test_role"}]
        templates = [{"template": "test.j2", "used_in": "playbook.yml"}]
        errors = []

        structure = builder.build_structure(playbooks, roles, templates, errors)

        assert "metadata" in structure
        assert "playbooks" in structure
        assert "roles" in structure
        assert "templates" in structure
        assert "statistics" in structure
        assert structure["statistics"]["total_playbooks"] == 1


class TestOutputGenerator:
    """Tests for OutputGenerator class."""

    def test_generate_json(self, tmp_path):
        """Test JSON output generation."""
        generator = OutputGenerator(tmp_path)

        structure = {
            "metadata": {"analyzed_at": "2026-01-01T00:00:00", "repo_root": "/test"},
            "playbooks": [],
            "roles": [],
            "templates": [],
            "errors": [],
            "statistics": {},
        }

        output_path = generator.generate_json(structure)

        assert output_path.exists()
        assert output_path.suffix == ".json"

    def test_generate_markdown(self, tmp_path):
        """Test Markdown output generation."""
        generator = OutputGenerator(tmp_path)

        structure = {
            "metadata": {"analyzed_at": "2026-01-01T00:00:00", "repo_root": "/test"},
            "playbooks": [{"file": "playbook.yml", "includes": []}],
            "roles": [{"name": "test_role", "path": "roles/test_role"}],
            "templates": [],
            "errors": [],
            "statistics": {"total_playbooks": 1, "total_roles": 1},
        }

        output_path = generator.generate_markdown(structure)

        assert output_path.exists()
        assert output_path.suffix == ".md"
        content = output_path.read_text()
        assert "Ansible Structure Analysis" in content
        assert "playbook.yml" in content


class TestAnsibleStructureAnalyzer:
    """Tests for AnsibleStructureAnalyzer orchestrator."""

    def test_analyze_single_playbook(self, tmp_path):
        """Test analyzing a single playbook."""
        repo_root = tmp_path
        analyzer = AnsibleStructureAnalyzer(repo_root)

        playbook = tmp_path / "playbook.yml"
        playbook.write_text("---\n- hosts: all\n  tasks:\n    - name: test\n      command: echo hello\n")

        result = analyzer.analyze(playbook)

        assert "playbooks" in result
        assert len(result["playbooks"]) == 1

    def test_analyze_directory(self, tmp_path):
        """Test analyzing a directory of playbooks."""
        repo_root = tmp_path
        analyzer = AnsibleStructureAnalyzer(repo_root)

        playbook1 = tmp_path / "playbook1.yml"
        playbook2 = tmp_path / "playbook2.yml"
        playbook1.write_text("---\n- hosts: all\n  tasks: []\n")
        playbook2.write_text("---\n- hosts: all\n  tasks: []\n")

        result = analyzer.analyze(tmp_path)

        assert "playbooks" in result
        assert len(result["playbooks"]) == 2

    def test_analyze_with_includes(self, tmp_path):
        """Test analyzing playbook with includes."""
        repo_root = tmp_path
        analyzer = AnsibleStructureAnalyzer(repo_root)

        # Create included task file
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        included = tasks_dir / "included.yml"
        included.write_text("---\n- name: included task\n  command: echo included\n")

        # Create playbook that includes it
        playbook = tmp_path / "playbook.yml"
        playbook.write_text("---\n- hosts: all\n  tasks:\n    - include_tasks: tasks/included.yml\n")

        result = analyzer.analyze(playbook)

        assert "playbooks" in result
        assert len(result["playbooks"]) == 1
        # Should have resolved the include
        assert len(result["playbooks"][0].get("includes", [])) > 0
