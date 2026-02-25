#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for ansible_structure_analyzer.py."""

from pathlib import Path

import pytest

from pyplayground.ansible_structure_analyzer import (
    AnsibleStructureAnalyzer,
    ErrorCollector,
    FileDiscovery,
    IncludeResolver,
    OutputGenerator,
    StructureBuilder,
    TemplateFinder,
    _path_to_role_name,
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

    def test_generate_markdown_no_diagrams(self, tmp_path):
        """Test that include_diagrams=False produces no mermaid blocks."""
        generator = OutputGenerator(tmp_path)
        structure = {
            "metadata": {"analyzed_at": "2026-01-01T00:00:00", "repo_root": "/test"},
            "playbooks": [{"file": "pb.yml", "includes": [{"type": "role", "name": "r1"}]}],
            "roles": [],
            "templates": [],
            "errors": [],
            "statistics": {},
            "dependency_graph": {"nodes": ["r1"], "edges": []},
        }
        path = generator.generate_markdown(structure, include_diagrams=False)
        content = path.read_text()
        assert "```mermaid" not in content

    def test_generate_markdown_diagram_scope_per_playbook(self, tmp_path):
        """Test diagram_scope per_playbook: per-playbook diagram only, no global section."""
        generator = OutputGenerator(tmp_path)
        structure = {
            "metadata": {"analyzed_at": "2026-01-01T00:00:00", "repo_root": "/test"},
            "playbooks": [
                {
                    "file": "pb.yml",
                    "includes": [{"type": "role", "name": "my_role", "includes": []}],
                }
            ],
            "roles": [],
            "templates": [],
            "errors": [],
            "statistics": {},
            "dependency_graph": {"nodes": ["my_role"], "edges": []},
        }
        path = generator.generate_markdown(structure, include_diagrams=True, diagram_scope="per_playbook")
        content = path.read_text()
        assert "```mermaid" in content
        assert "Execution flow" in content
        assert "Role Dependency Graph" not in content

    def test_generate_markdown_diagram_scope_global(self, tmp_path):
        """Test diagram_scope global: only Role Dependency Graph, no per-playbook Execution flow."""
        generator = OutputGenerator(tmp_path)
        structure = {
            "metadata": {"analyzed_at": "2026-01-01T00:00:00", "repo_root": "/test"},
            "playbooks": [
                {
                    "file": "pb.yml",
                    "includes": [{"type": "role", "name": "my_role", "includes": []}],
                }
            ],
            "roles": [],
            "templates": [],
            "errors": [],
            "statistics": {},
            "dependency_graph": {"nodes": ["my_role"], "edges": []},
        }
        path = generator.generate_markdown(structure, include_diagrams=True, diagram_scope="global")
        content = path.read_text()
        assert "Role Dependency Graph" in content
        assert "Execution flow" not in content

    def test_generate_playbook_mermaid_diagram_empty(self, tmp_path):
        """Test generate_playbook_mermaid_diagram returns empty string when no includes."""
        generator = OutputGenerator(tmp_path)
        playbook = {"file": "pb.yml", "includes": []}
        result = generator.generate_playbook_mermaid_diagram(playbook)
        assert result == ""

    def test_generate_playbook_mermaid_diagram_with_includes(self, tmp_path):
        """Test generate_playbook_mermaid_diagram returns valid mermaid for playbook with includes."""
        generator = OutputGenerator(tmp_path)
        playbook = {
            "file": "upgrade.yml",
            "includes": [
                {"type": "role", "name": "upgrade_cluster", "includes": []},
                {"type": "include_tasks", "ref": "node_status.yml", "includes": []},
            ],
        }
        result = generator.generate_playbook_mermaid_diagram(playbook)
        assert result
        assert "graph TD" in result or "graph LR" in result
        assert "upgrade_cluster" in result
        assert "node_status" in result or "node_status.yml" in result


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


@pytest.fixture
def fixture_dir():
    """Get path to test fixtures directory."""
    return Path(__file__).parent / "fixtures" / "ansible_structure"


@pytest.fixture
def fixture_repo_root(fixture_dir):
    """Get repo root for fixture directory."""
    return fixture_dir


class TestLoopHandling:
    """Tests for loop handling in includes and breadcrumbs."""

    def test_has_loop_with_sequence(self):
        """Test _has_loop() detects with_sequence."""
        repo_root = Path("/tmp")
        error_collector = ErrorCollector()
        resolver = IncludeResolver(repo_root, error_collector)

        task = {"name": "test", "include_tasks": "file.yml", "with_sequence": "start=1 end=5"}
        result = resolver._has_loop(task)

        assert result == "with_sequence"

    def test_has_loop_with_items(self):
        """Test _has_loop() detects with_items."""
        repo_root = Path("/tmp")
        error_collector = ErrorCollector()
        resolver = IncludeResolver(repo_root, error_collector)

        task = {"name": "test", "include_tasks": "file.yml", "with_items": ["item1", "item2"]}
        result = resolver._has_loop(task)

        assert result == "with_items"

    def test_has_loop_loop(self):
        """Test _has_loop() detects loop."""
        repo_root = Path("/tmp")
        error_collector = ErrorCollector()
        resolver = IncludeResolver(repo_root, error_collector)

        task = {"name": "test", "include_tasks": "file.yml", "loop": ["item1", "item2"]}
        result = resolver._has_loop(task)

        assert result == "loop"

    def test_has_loop_no_loop(self):
        """Test _has_loop() returns None for tasks without loops."""
        repo_root = Path("/tmp")
        error_collector = ErrorCollector()
        resolver = IncludeResolver(repo_root, error_collector)

        task = {"name": "test", "include_tasks": "file.yml"}
        result = resolver._has_loop(task)

        assert result is None

    def test_include_with_sequence(self, fixture_dir, fixture_repo_root):
        """Test includes with with_sequence are detected and loop context preserved."""
        if not fixture_dir.exists():
            pytest.skip("Test fixtures not found")

        analyzer = AnsibleStructureAnalyzer(fixture_repo_root)
        playbook = fixture_dir / "playbooks" / "with_loops.yml"

        if not playbook.exists():
            pytest.skip("with_loops.yml fixture not found")

        result = analyzer.analyze(playbook)

        # Find includes with with_sequence
        includes = result["playbooks"][0].get("includes", [])
        with_sequence_found = False
        for include in includes:
            if include.get("loop_context") == "with_sequence":
                with_sequence_found = True
                break

        assert with_sequence_found, "Should find include with with_sequence loop context"

    def test_include_with_items(self, fixture_dir, fixture_repo_root):
        """Test includes with with_items are detected and loop context preserved."""
        if not fixture_dir.exists():
            pytest.skip("Test fixtures not found")

        analyzer = AnsibleStructureAnalyzer(fixture_repo_root)
        playbook = fixture_dir / "playbooks" / "with_loops.yml"

        if not playbook.exists():
            pytest.skip("with_loops.yml fixture not found")

        result = analyzer.analyze(playbook)

        # Find includes with with_items
        includes = result["playbooks"][0].get("includes", [])
        with_items_found = False
        for include in includes:
            if include.get("loop_context") == "with_items":
                with_items_found = True
                break

        assert with_items_found, "Should find include with with_items loop context"

    def test_include_with_loop(self, fixture_dir, fixture_repo_root):
        """Test includes with loop are detected and loop context preserved."""
        if not fixture_dir.exists():
            pytest.skip("Test fixtures not found")

        analyzer = AnsibleStructureAnalyzer(fixture_repo_root)
        playbook = fixture_dir / "playbooks" / "with_loops.yml"

        if not playbook.exists():
            pytest.skip("with_loops.yml fixture not found")

        result = analyzer.analyze(playbook)

        # Find includes with loop
        includes = result["playbooks"][0].get("includes", [])
        loop_found = False
        for include in includes:
            if include.get("loop_context") == "loop":
                loop_found = True
                break

        assert loop_found, "Should find include with loop context"

    def test_role_with_loops(self, fixture_dir, fixture_repo_root):
        """Test role task files with loops are processed correctly."""
        if not fixture_dir.exists():
            pytest.skip("Test fixtures not found")

        analyzer = AnsibleStructureAnalyzer(fixture_repo_root)
        # Use a playbook that includes the role_with_loops role
        playbook = fixture_dir / "playbooks" / "with_loops.yml"

        if not playbook.exists():
            pytest.skip("with_loops.yml fixture not found")

        result = analyzer.analyze(playbook)

        # Find role_with_loops role
        roles = result.get("roles", [])
        role_found = False
        scale_nodes_found = False
        post_provision_found = False

        for role in roles:
            if role.get("name") == "role_with_loops":
                role_found = True
                # Check includes in role
                role_includes = role.get("includes", [])
                for include in role_includes:
                    if "scale_nodes.yml" in include.get("ref", ""):
                        scale_nodes_found = True
                        # Check nested includes
                        nested = include.get("includes", [])
                        for nested_include in nested:
                            if "post_provision.yml" in nested_include.get("ref", ""):
                                post_provision_found = True
                                break
                    if scale_nodes_found and post_provision_found:
                        break
                break

        assert role_found, "Should find role_with_loops role"
        assert scale_nodes_found, "Should find scale_nodes.yml include"
        assert post_provision_found, "Should find post_provision.yml nested include"

    def test_circular_dependency_with_loops_no_false_positive(self, fixture_dir, fixture_repo_root):
        """Test that scale_nodes.yml including post_provision.yml with with_sequence does NOT create false positive."""
        if not fixture_dir.exists():
            pytest.skip("Test fixtures not found")

        analyzer = AnsibleStructureAnalyzer(fixture_repo_root)
        playbook = fixture_dir / "playbooks" / "with_loops.yml"

        if not playbook.exists():
            pytest.skip("with_loops.yml fixture not found")

        result = analyzer.analyze(playbook)

        # Check for false positive circular dependencies
        errors = result.get("errors", [])
        false_positives = [
            e for e in errors if e.get("type") == "CIRCULAR_DEPENDENCY" and "scale_nodes.yml" in str(e.get("file", "")) and "post_provision.yml" in str(e.get("file", ""))
        ]

        assert len(false_positives) == 0, "Should not have false positive circular dependency for scale_nodes -> post_provision"

    def test_true_circular_dependency_still_detected(self, fixture_dir, fixture_repo_root):
        """Test true circular dependency (A -> B -> C -> A) is still detected."""
        if not fixture_dir.exists():
            pytest.skip("Test fixtures not found")

        analyzer = AnsibleStructureAnalyzer(fixture_repo_root)
        playbook = fixture_dir / "playbooks" / "circular_dependency.yml"

        if not playbook.exists():
            pytest.skip("circular_dependency.yml fixture not found")

        result = analyzer.analyze(playbook)

        # Should detect circular dependency
        errors = result.get("errors", [])
        circular_errors = [e for e in errors if e.get("type") == "CIRCULAR_DEPENDENCY"]

        assert len(circular_errors) > 0, "Should detect true circular dependency"

    def test_loop_context_in_output_json(self, fixture_dir, fixture_repo_root, tmp_path):
        """Test loop context appears in JSON output."""
        if not fixture_dir.exists():
            pytest.skip("Test fixtures not found")

        analyzer = AnsibleStructureAnalyzer(fixture_repo_root)
        playbook = fixture_dir / "playbooks" / "with_loops.yml"

        if not playbook.exists():
            pytest.skip("with_loops.yml fixture not found")

        result = analyzer.analyze(playbook)

        # Check JSON structure has loop_context
        includes = result["playbooks"][0].get("includes", [])
        has_loop_context = False
        for include in includes:
            if "loop_context" in include:
                has_loop_context = True
                break

        assert has_loop_context, "JSON output should include loop_context field"

    def test_loop_context_in_output_markdown(self, fixture_dir, fixture_repo_root, tmp_path):
        """Test loop context appears in Markdown output."""
        if not fixture_dir.exists():
            pytest.skip("Test fixtures not found")

        analyzer = AnsibleStructureAnalyzer(fixture_repo_root)
        playbook = fixture_dir / "playbooks" / "with_loops.yml"

        if not playbook.exists():
            pytest.skip("with_loops.yml fixture not found")

        result = analyzer.analyze(playbook)

        # Generate markdown
        output_gen = OutputGenerator(tmp_path)
        md_path = output_gen.generate_markdown(result)

        # Check markdown content
        content = md_path.read_text()
        assert "[with_sequence]" in content or "[with_items]" in content or "[loop]" in content, "Markdown should show loop context"

    def test_breadcrumbs_with_loop_context(self, fixture_dir, fixture_repo_root):
        """Test include chain shows loop context in debug logs."""
        if not fixture_dir.exists():
            pytest.skip("Test fixtures not found")

        repo_root = fixture_repo_root
        error_collector = ErrorCollector()
        resolver = IncludeResolver(repo_root, error_collector)

        # Test with a role that has loops
        role_path = fixture_dir / "roles" / "role_with_loops"
        if not role_path.exists():
            pytest.skip("role_with_loops fixture not found")

        main_tasks = role_path / "tasks" / "main.yml"
        if not main_tasks.exists():
            pytest.skip("role_with_loops/tasks/main.yml not found")

        # This should process includes and preserve loop context
        result = resolver.resolve_includes(main_tasks)

        # Check that includes are found
        assert "includes" in result
        includes = result.get("includes", [])
        assert len(includes) > 0, "Should find includes in role_with_loops"


class TestCrossRole:
    """Tests for cross-role detection and reporting."""

    def test_path_to_role_name_under_role_tasks(self, tmp_path):
        """_path_to_role_name returns role name for path under roles/foo/tasks/."""
        repo = tmp_path
        (repo / "roles" / "configure_cluster" / "tasks").mkdir(parents=True)
        path = repo / "roles" / "configure_cluster" / "tasks" / "setup_machinesets.yml"
        path.touch()
        assert _path_to_role_name(repo, path) == "configure_cluster"

    def test_path_to_role_name_under_role_templates(self, tmp_path):
        """_path_to_role_name returns role name for path under roles/foo/templates/."""
        repo = tmp_path
        (repo / "roles" / "create_machineset" / "templates").mkdir(parents=True)
        path = repo / "roles" / "create_machineset" / "templates" / "machineset.yaml.j2"
        path.touch()
        assert _path_to_role_name(repo, path) == "create_machineset"

    def test_path_to_role_name_playbook_returns_none(self, tmp_path):
        """_path_to_role_name returns None for playbooks/ path."""
        repo = tmp_path
        (repo / "playbooks").mkdir(parents=True)
        path = repo / "playbooks" / "configure_cluster.yml"
        path.touch()
        assert _path_to_role_name(repo, path) is None

    def test_path_to_role_name_root_tasks_returns_none(self, tmp_path):
        """_path_to_role_name returns None for repo root tasks/."""
        repo = tmp_path
        (repo / "tasks").mkdir(parents=True)
        path = repo / "tasks" / "setup.yml"
        path.touch()
        assert _path_to_role_name(repo, path) is None

    def test_path_to_role_name_outside_roles_returns_none(self, tmp_path):
        """_path_to_role_name returns None for path outside repo roles/."""
        repo = tmp_path
        (repo / "roles" / "foo").mkdir(parents=True)
        path = Path("/other/repo/roles/bar/tasks/main.yml")
        assert _path_to_role_name(repo, path) is None

    def test_cross_role_task_include_detected(self, tmp_path):
        """Role A including role B task file is reported as cross-role."""
        repo = tmp_path
        # role_a/tasks/main.yml includes ../../role_b/tasks/extra.yml
        (repo / "roles" / "role_a" / "tasks").mkdir(parents=True)
        (repo / "roles" / "role_b" / "tasks").mkdir(parents=True)
        (repo / "playbooks").mkdir(parents=True)

        main_a = repo / "roles" / "role_a" / "tasks" / "main.yml"
        main_a.write_text("- include_tasks: ../../role_b/tasks/extra.yml\n")
        (repo / "roles" / "role_b" / "tasks" / "extra.yml").write_text("- debug: msg=ok\n")

        playbook = repo / "playbooks" / "pb.yml"
        playbook.write_text("---\n- hosts: all\n  roles:\n    - role_a\n")

        analyzer = AnsibleStructureAnalyzer(repo)
        result = analyzer.analyze(playbook)

        def find_cross_role_includes(includes):
            for inc in includes:
                if inc.get("cross_role") and inc.get("type") in ("include_tasks", "import_tasks"):
                    return inc
                found = find_cross_role_includes(inc.get("includes") or [])
                if found:
                    return found
            return None

        role_a = next((r for r in result.get("roles", []) if r.get("name") == "role_a"), None)
        assert role_a is not None, "role_a should be in result"
        cross = find_cross_role_includes(role_a.get("includes") or [])
        assert cross is not None, "Should find cross-role task include"
        assert cross.get("caller_role") == "role_a"
        assert cross.get("target_role") == "role_b"

    def test_cross_role_template_detected(self, tmp_path):
        """Role A using a template from role B is reported as cross-role."""
        repo = tmp_path
        (repo / "roles" / "role_a" / "tasks").mkdir(parents=True)
        (repo / "roles" / "role_b" / "templates").mkdir(parents=True)
        (repo / "playbooks").mkdir(parents=True)

        main_a = repo / "roles" / "role_a" / "tasks" / "main.yml"
        main_a.write_text("- template:\n    src: other_config.j2\n    dest: /tmp/other.conf\n")
        (repo / "roles" / "role_b" / "templates" / "other_config.j2").write_text("config\n")

        playbook = repo / "playbooks" / "pb.yml"
        playbook.write_text("---\n- hosts: all\n  roles:\n    - role_a\n")

        analyzer = AnsibleStructureAnalyzer(repo)
        result = analyzer.analyze(playbook)

        templates = result.get("templates", [])
        cross_templates = [t for t in templates if t.get("cross_role") and t.get("template_role") == "role_b"]
        assert len(cross_templates) >= 1, "Should find cross-role template usage"
        assert cross_templates[0].get("caller_role") == "role_a"
        assert cross_templates[0].get("template_role") == "role_b"

    def test_cross_role_in_json_and_markdown(self, tmp_path):
        """Cross-role flags appear in JSON and Cross-role summary in Markdown."""
        repo = tmp_path
        (repo / "roles" / "role_a" / "tasks").mkdir(parents=True)
        (repo / "roles" / "role_b" / "tasks").mkdir(parents=True)
        (repo / "playbooks").mkdir(parents=True)

        (repo / "roles" / "role_a" / "tasks" / "main.yml").write_text("- include_tasks: ../../role_b/tasks/extra.yml\n")
        (repo / "roles" / "role_b" / "tasks" / "extra.yml").write_text("- debug: msg=ok\n")

        playbook = repo / "playbooks" / "pb.yml"
        playbook.write_text("---\n- hosts: all\n  roles:\n    - role_a\n")

        analyzer = AnsibleStructureAnalyzer(repo)
        result = analyzer.analyze(playbook)

        # JSON: at least one include has cross_role true
        def has_cross_role_in_includes(includes):
            for inc in includes:
                if inc.get("cross_role") is True:
                    return True
                if has_cross_role_in_includes(inc.get("includes") or []):
                    return True
            return False

        assert has_cross_role_in_includes(result.get("playbooks", [{}])[0].get("includes") or []), "Playbook includes tree should contain cross_role include"
        roles_includes = []
        for r in result.get("roles", []):
            roles_includes.extend(r.get("includes") or [])
        assert has_cross_role_in_includes(roles_includes), "Roles includes should contain cross_role"

        # Markdown: Cross-role summary section present
        output_gen = OutputGenerator(tmp_path)
        md_path = output_gen.generate_markdown(result)
        content = md_path.read_text()
        assert "## Cross-role summary" in content, "Markdown should have Cross-role summary section"
        assert "Cross-role task includes" in content or "role_a" in content, "Markdown should list cross-role task includes"
