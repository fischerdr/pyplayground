#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ansible Structure Analyzer.

This script analyzes Ansible playbooks and roles to document:
- All included tasks and roles (include_tasks, import_tasks, include_role, import_role, roles:)
- All template files used (via template module and .j2 files in templates/)
- Hierarchical structure showing parent-child relationships
- File locations and paths

It supports analyzing either a single playbook file or a top-level directory
(non-recursive) containing playbook files.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import click
import yaml
from rich.console import Console

from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.password_finder import create_custom_yaml_loader
from pyplayground.utils.report_utils import save_summary_report

# Constants
MAX_RECURSION_DEPTH = 50
YAML_EXTENSIONS = [".yml", ".yaml"]
TEMPLATE_EXTENSIONS = [".j2"]
INCLUDE_TYPES = ["include_tasks", "import_tasks", "include_role", "import_role", "roles"]

logger = get_logger(__name__)


def _path_to_role_name(repo_root: Path, file_path: Path) -> Optional[str]:
    """Return the role name if file_path is under repo_root/roles/<name>/.

    Args:
        repo_root: Repository root directory
        file_path: Path to a file (task, template, etc.)

    Returns:
        Role name if path is under roles/<name>/, None otherwise
    """
    if not file_path:
        return None
    try:
        resolved_path = Path(file_path).resolve()
        resolved_repo = Path(repo_root).resolve()
        roles_dir = resolved_repo / "roles"
        try:
            resolved_path.relative_to(roles_dir)
        except ValueError:
            return None
        parts = resolved_path.relative_to(roles_dir).parts
        if parts:
            return parts[0]
    except (ValueError, OSError):
        pass
    return None


class FileDiscovery:
    """Handles discovery of Ansible playbook files from input."""

    def __init__(self):
        """Initialize the FileDiscovery."""
        logger.debug("FileDiscovery initialized")

    def discover_files(self, input_path: Path) -> List[Path]:
        """Discover playbook files from input path.

        Args:
            input_path: Single playbook file or top-level directory

        Returns:
            List of playbook file paths to analyze

        Raises:
            FileNotFoundError: If input path does not exist
            ValueError: If input path is invalid
        """
        logger.info(f"Discovering files from input: {input_path}")

        try:
            input_path = Path(input_path).resolve()

            if not input_path.exists():
                logger.error(f"Input path does not exist: {input_path}")
                raise FileNotFoundError(f"Input path does not exist: {input_path}")

            playbook_files = []

            if input_path.is_file():
                logger.debug(f"Input is a single file: {input_path}")
                if self.is_playbook_file(input_path):
                    playbook_files.append(input_path)
                    logger.info(f"Found playbook file: {input_path}")
                else:
                    logger.warning(f"File is not a YAML playbook: {input_path}")
            elif input_path.is_dir():
                logger.debug(f"Input is a directory: {input_path}")
                playbook_files = self._discover_from_directory(input_path)
                logger.info(f"Found {len(playbook_files)} playbook files in directory")
            else:
                logger.error(f"Input path is neither file nor directory: {input_path}")
                raise ValueError(f"Input path must be a file or directory: {input_path}")

            return playbook_files

        except Exception as e:
            logger.error(f"Error discovering files: {e}", exc_info=True)
            raise

    def _discover_from_directory(self, directory: Path) -> List[Path]:
        """Discover playbook files from a directory (non-recursive).

        Args:
            directory: Directory to search

        Returns:
            List of playbook file paths found in directory
        """
        logger.debug(f"Scanning directory (non-recursive): {directory}")
        playbook_files = []

        try:
            for item in directory.iterdir():
                if item.is_file() and self.is_playbook_file(item):
                    playbook_files.append(item)
                    logger.debug(f"Found playbook file: {item}")

            return playbook_files

        except Exception as e:
            logger.error(f"Error scanning directory {directory}: {e}", exc_info=True)
            raise

    def is_playbook_file(self, file_path: Path) -> bool:
        """Check if a file is a YAML playbook file.

        Args:
            file_path: Path to file to check

        Returns:
            True if file is a YAML playbook, False otherwise
        """
        if not file_path.is_file():
            return False

        if file_path.suffix not in YAML_EXTENSIONS:
            return False

        return True


class ErrorCollector:
    """Collects and categorizes errors during processing."""

    def __init__(self):
        """Initialize the ErrorCollector."""
        self.errors: List[Dict[str, Any]] = []
        logger.debug("ErrorCollector initialized")

    def add_error(
        self,
        error_type: str,
        message: str,
        file_path: Optional[Path] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add an error to the collection.

        Args:
            error_type: Type of error (MISSING_FILE, PARSE_ERROR, etc.)
            message: Error message
            file_path: Optional file path where error occurred
            context: Optional additional context information
        """
        error = {
            "type": error_type,
            "message": message,
            "file": str(file_path) if file_path else None,
            "context": context or {},
            "timestamp": datetime.now().isoformat(),
        }
        self.errors.append(error)
        logger.warning(f"Error collected: {error_type} - {message}")

    def get_errors(self) -> List[Dict[str, Any]]:
        """Get all collected errors.

        Returns:
            List of error dictionaries
        """
        return self.errors

    def has_errors(self) -> bool:
        """Check if any errors were collected.

        Returns:
            True if errors exist, False otherwise
        """
        return len(self.errors) > 0


class IncludeResolver:
    """Resolves Ansible includes and roles with path resolution."""

    def __init__(
        self, repo_root: Path, error_collector: ErrorCollector, max_depth: int = MAX_RECURSION_DEPTH
    ):
        """Initialize the IncludeResolver.

        Args:
            repo_root: Repository root directory for path resolution
            error_collector: ErrorCollector instance for error reporting
            max_depth: Maximum recursion depth for includes
        """
        self.repo_root = repo_root
        self.error_collector = error_collector
        self.max_depth = max_depth
        logger.debug(
            f"IncludeResolver initialized with repo_root: {repo_root}, max_depth: {max_depth}"
        )

    def _get_include_key(self, task: Dict[str, Any], short_name: str) -> Optional[str]:
        """Get include key from task, checking both short and FQCN forms.

        Args:
            task: Task dictionary
            short_name: Short module name (e.g., 'include_tasks')

        Returns:
            Key name if found (short or FQCN), None otherwise
        """
        # Check short form first
        if short_name in task:
            return short_name

        # Check FQCN form
        fqcn_name = f"ansible.builtin.{short_name}"
        if fqcn_name in task:
            return fqcn_name

        # Check other common FQCN forms
        for collection in ["ansible.legacy", "ansible.posix"]:
            fqcn_alt = f"{collection}.{short_name}"
            if fqcn_alt in task:
                return fqcn_alt

        return None

    def _has_loop(self, task: Dict[str, Any]) -> Optional[str]:
        """Check if task has a loop construct.

        Args:
            task: Task dictionary

        Returns:
            Loop type string or None
        """
        if "with_sequence" in task:
            return "with_sequence"
        if "with_items" in task:
            return "with_items"
        if "loop" in task:
            return "loop"
        # Note: loop_control alone doesn't indicate a loop, only when used with loop
        return None

    def resolve_includes(  # noqa: C901
        self,
        file_path: Path,
        visited: Optional[Set[Path]] = None,
        depth: int = 0,
        include_chain: Optional[List[Path]] = None,
        loop_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Recursively resolve includes from a playbook or task file.

        Args:
            file_path: Path to file to analyze
            visited: Set of already visited files (for circular dependency detection)
            depth: Current recursion depth
            include_chain: Chain of includes leading to this file
            loop_context: Loop context if this file is included from a loop (with_sequence, with_items, loop)

        Returns:
            Dictionary containing resolved includes information
        """
        if visited is None:
            visited = set()
        if include_chain is None:
            include_chain = []

        logger.debug(
            f"resolve_includes: starting resolution from {file_path} (depth: {depth}/{self.max_depth})"
        )
        if loop_context:
            logger.debug(f"resolve_includes: Processing {file_path.name} [loop: {loop_context}]")
        if include_chain:
            chain_str = " -> ".join(str(p.name) for p in include_chain[-3:])
            logger.debug(f"resolve_includes: include chain (last 3): ... -> {chain_str}")

        try:
            # Check recursion depth
            if depth >= self.max_depth:
                logger.warning(
                    f"resolve_includes: MAX DEPTH EXCEEDED at depth {depth} for {file_path}"
                )
                self.error_collector.add_error(
                    "MAX_DEPTH_EXCEEDED",
                    f"Maximum recursion depth ({self.max_depth}) exceeded",
                    file_path,
                    {"depth": depth, "include_chain": [str(p) for p in include_chain]},
                )
                return {"file": str(file_path), "includes": [], "error": "MAX_DEPTH_EXCEEDED"}

            # Check for circular dependency - only flag if file is in current execution path
            # This prevents false positives when same file is included from different branches
            if file_path in include_chain:
                # True circular dependency - file appears twice in same execution path
                circular_chain = include_chain + [file_path]
                # Find where in the chain this file was first visited
                first_visit_index = None
                for idx, chain_file in enumerate(include_chain):
                    if chain_file == file_path:
                        first_visit_index = idx
                        break

                logger.warning(
                    f"resolve_includes: CIRCULAR DEPENDENCY detected: {' -> '.join(str(p) for p in circular_chain)}"
                )
                if first_visit_index is not None:
                    logger.debug(
                        f"resolve_includes: File {file_path.name} was first visited at chain index {first_visit_index}"
                    )
                    logger.debug(
                        f"resolve_includes: Circular loop: {' -> '.join(str(p.name) for p in circular_chain[first_visit_index:])}"
                    )

                # Try to parse the file to see what it includes (for debugging)
                try:
                    content = self._parse_yaml_file(file_path)
                    if content is not None:
                        # Quick check for includes without full recursion
                        temp_includes = []
                        if isinstance(content, dict):
                            if "tasks" in content:
                                for task in content["tasks"]:
                                    if isinstance(task, dict):
                                        include_key = self._get_include_key(task, "include_tasks")
                                        if include_key:
                                            temp_includes.append(
                                                f"include_tasks: {task[include_key]}"
                                            )
                        elif isinstance(content, list):
                            for item in content[:3]:  # Check first 3 items
                                if isinstance(item, dict):
                                    include_key = self._get_include_key(item, "include_tasks")
                                    if include_key:
                                        temp_includes.append(f"include_tasks: {item[include_key]}")
                        if temp_includes:
                            logger.debug(
                                f"resolve_includes: File {file_path.name} includes: {', '.join(temp_includes[:5])}"
                            )
                except Exception:
                    pass  # Ignore errors during debug logging

                self.error_collector.add_error(
                    "CIRCULAR_DEPENDENCY",
                    "Circular dependency detected",
                    file_path,
                    {"include_chain": [str(p) for p in circular_chain]},
                )
                return {"file": str(file_path), "includes": [], "error": "CIRCULAR_DEPENDENCY"}
            elif file_path in visited:
                # File was visited from different branch - skip processing but don't flag as circular
                logger.debug(
                    f"resolve_includes: File {file_path.name} already visited from different branch, skipping"
                )
                return {
                    "file": str(file_path),
                    "includes": [],
                    "skipped": True,
                    "reason": "already_visited",
                }

            # Mark as visited
            visited.add(file_path)
            current_chain = include_chain + [file_path]
            logger.debug(
                f"resolve_includes: marked {file_path} as visited (total visited: {len(visited)})"
            )

            # Parse file
            content = self._parse_yaml_file(file_path)
            if content is None:
                logger.debug(
                    f"resolve_includes: content is None for {file_path}, returning empty includes"
                )
                return {"file": str(file_path), "includes": []}

            # Find includes
            includes = self._parse_includes(
                content, file_path, visited, depth, current_chain, loop_context
            )
            logger.debug(
                f"resolve_includes: found {len(includes)} includes in {file_path} at depth {depth}"
            )

            result = {"file": str(file_path), "includes": includes}
            if loop_context:
                result["loop_context"] = loop_context
            return result

        except Exception as e:
            logger.error(f"Error resolving includes from {file_path}: {e}", exc_info=True)
            self.error_collector.add_error("PARSE_ERROR", str(e), file_path)
            return {"file": str(file_path), "includes": [], "error": str(e)}

    def _parse_yaml_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Parse a YAML file.

        Args:
            file_path: Path to YAML file

        Returns:
            Parsed YAML content or None if parsing fails
        """
        logger.debug(f"Parsing YAML file: {file_path}")

        try:
            with file_path.open("r", encoding="utf-8") as f:
                content = f.read()

            # Skip vault encrypted files
            if "ANSIBLE_VAULT" in content:
                logger.warning(f"Skipping vaulted file: {file_path}")
                return None

            custom_loader = create_custom_yaml_loader()
            data = yaml.load(content, Loader=custom_loader)

            return data

        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error in {file_path}: {e}", exc_info=True)
            self.error_collector.add_error("PARSE_ERROR", f"YAML parsing failed: {e}", file_path)
            return None
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}", exc_info=True)
            self.error_collector.add_error("PARSE_ERROR", f"File read error: {e}", file_path)
            return None

    def _parse_includes(  # noqa: C901
        self,
        content: Any,
        current_file: Path,
        visited: Set[Path],
        depth: int,
        include_chain: List[Path],
        loop_context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Parse includes from YAML content.

        Args:
            content: Parsed YAML content
            current_file: Current file being processed
            visited: Set of visited files
            depth: Current recursion depth
            include_chain: Chain of includes
            loop_context: Loop context if this file is included from a loop

        Returns:
            List of resolved includes
        """
        includes = []

        # Debug: Log content type and structure
        content_type = type(content).__name__
        logger.debug(
            f"_parse_includes: content type={content_type}, file={current_file}, depth={depth}"
        )

        if isinstance(content, dict):
            content_keys = list(content.keys())[:10]  # First 10 keys for debugging
            logger.debug(f"_parse_includes: dict content keys (first 10): {content_keys}")
            # Check for include statements in tasks
            if "tasks" in content:
                includes.extend(
                    self._parse_task_includes(
                        content["tasks"], current_file, visited, depth, include_chain, loop_context
                    )
                )
            if "pre_tasks" in content:
                includes.extend(
                    self._parse_task_includes(
                        content["pre_tasks"],
                        current_file,
                        visited,
                        depth,
                        include_chain,
                        loop_context,
                    )
                )
            if "post_tasks" in content:
                includes.extend(
                    self._parse_task_includes(
                        content["post_tasks"],
                        current_file,
                        visited,
                        depth,
                        include_chain,
                        loop_context,
                    )
                )
            if "roles" in content:
                includes.extend(
                    self._parse_role_includes(
                        content["roles"], current_file, visited, depth, include_chain
                    )
                )

            # Check for include_tasks at play level (short or FQCN)
            include_tasks_key = self._get_include_key(content, "include_tasks")
            if include_tasks_key:
                includes.append(
                    self._resolve_include_task(
                        content[include_tasks_key],
                        current_file,
                        visited,
                        depth,
                        include_chain,
                        loop_context,
                    )
                )

            # Check for import_tasks at play level (short or FQCN)
            import_tasks_key = self._get_include_key(content, "import_tasks")
            if import_tasks_key:
                includes.append(
                    self._resolve_import_task(
                        content[import_tasks_key],
                        current_file,
                        visited,
                        depth,
                        include_chain,
                        loop_context,
                    )
                )

            # Check for include_role at play level (short or FQCN)
            include_role_key = self._get_include_key(content, "include_role")
            if include_role_key:
                includes.append(
                    self._resolve_include_role(
                        content[include_role_key],
                        current_file,
                        visited,
                        depth,
                        include_chain,
                        loop_context,
                    )
                )

            # Check for import_role at play level (short or FQCN)
            import_role_key = self._get_include_key(content, "import_role")
            if import_role_key:
                includes.append(
                    self._resolve_import_role(
                        content[import_role_key],
                        current_file,
                        visited,
                        depth,
                        include_chain,
                        loop_context,
                    )
                )

        elif isinstance(content, list):
            logger.debug(f"_parse_includes: list content length={len(content)}")
            # Check if list contains plays vs tasks
            # Plays MUST have "hosts" OR have "tasks"/"pre_tasks" keys
            # Tasks are dictionaries with module keys (ansible.builtin.*) or just "name"
            # If file is in tasks/ directory, it's almost certainly a task list
            if content and isinstance(content[0], dict):
                first_item = content[0]
                first_item_keys = list(first_item.keys())[:10]  # First 10 keys
                logger.debug(f"_parse_includes: first list item keys (first 10): {first_item_keys}")

                # Check if we're in a tasks directory - if so, almost certainly a task list
                is_in_tasks_dir = current_file.parent.name == "tasks"
                logger.debug(f"_parse_includes: file is in tasks directory: {is_in_tasks_dir}")

                # Plays MUST have "hosts" OR have "tasks"/"pre_tasks" keys
                # Tasks NEVER have "hosts" - that's a play-level key
                # Tasks can be unnamed, but they have module keys (ansible.builtin.*) or include keys
                has_hosts = "hosts" in first_item
                has_tasks_key = "tasks" in first_item or "pre_tasks" in first_item

                # Check for task indicators: module keys or include keys
                # Tasks have module keys like ansible.builtin.shell, template, copy, etc.
                # Or include keys like include_tasks, include_role, import_tasks, import_role
                has_module_key = any(
                    key.startswith("ansible.builtin.")
                    or key.startswith("ansible.")
                    or key.startswith("kubernetes.")
                    or key
                    in [
                        "shell",
                        "command",
                        "template",
                        "copy",
                        "file",
                        "debug",
                        "set_fact",
                        "pause",
                        "fail",
                        "uri",
                        "get_url",
                        "tempfile",
                        "meta",
                    ]
                    for key in first_item.keys()
                )
                has_include_key = any(
                    key in ["include_tasks", "import_tasks", "include_role", "import_role"]
                    or key.startswith("ansible.builtin.include_")
                    or key.startswith("ansible.builtin.import_")
                    for key in first_item.keys()
                )
                # Task-specific keys that plays don't typically have
                has_task_indicators = any(
                    key
                    in [
                        "block",
                        "when",
                        "register",
                        "loop",
                        "with_items",
                        "until",
                        "retries",
                        "changed_when",
                        "failed_when",
                    ]
                    for key in first_item.keys()
                )

                # If file is in tasks/ directory, treat as task list (very reliable indicator)
                # Exception: if it has "hosts", it might be a play (unusual but possible)
                # Otherwise, if it has "hosts" or "tasks"/"pre_tasks", it's a play
                # If it has module/include keys or task indicators, it's a task
                if is_in_tasks_dir and not has_hosts:
                    is_play = False
                    logger.debug(
                        "_parse_includes: file in tasks/ directory without hosts → treating as task list"
                    )
                elif has_hosts or has_tasks_key:
                    is_play = True
                    logger.debug(
                        f"_parse_includes: item has hosts={has_hosts} or tasks_key={has_tasks_key} → treating as play"
                    )
                elif has_module_key or has_include_key or has_task_indicators:
                    is_play = False
                    logger.debug(
                        f"_parse_includes: item has module_key={has_module_key}, include_key={has_include_key}, task_indicators={has_task_indicators} → treating as task"
                    )
                else:
                    # Default to task list if uncertain (safer for includes)
                    is_play = False
                    logger.debug(
                        "_parse_includes: no clear play indicators → treating as task list"
                    )

                logger.debug(
                    f"_parse_includes: play detection - has_hosts={has_hosts}, has_tasks_key={has_tasks_key}, "
                    f"has_module_key={has_module_key}, has_include_key={has_include_key}, "
                    f"has_task_indicators={has_task_indicators}, is_in_tasks_dir={is_in_tasks_dir}, is_play={is_play}"
                )

                if is_play:
                    # Process as list of plays
                    logger.debug(
                        f"_parse_includes: treating list as playbook with {len(content)} plays"
                    )
                    for play_index, play in enumerate(content):
                        if isinstance(play, dict):
                            logger.debug(f"_parse_includes: processing play {play_index + 1}")
                            # Recursively process each play dict
                            play_includes = self._parse_includes(
                                play, current_file, visited, depth, include_chain, loop_context
                            )
                            includes.extend(play_includes)
                else:
                    # Process as list of tasks
                    logger.debug(
                        f"_parse_includes: treating list as task list, length={len(content)}"
                    )
                    includes.extend(
                        self._parse_task_includes(
                            content, current_file, visited, depth, include_chain, loop_context
                        )
                    )
            else:
                # Empty list or non-dict items - treat as task list
                logger.debug(
                    f"_parse_includes: treating list as task list (empty or non-dict items={len(content)})"
                )
                includes.extend(
                    self._parse_task_includes(
                        content, current_file, visited, depth, include_chain, loop_context
                    )
                )

        logger.debug(f"_parse_includes: returning {len(includes)} total includes")
        return includes

    def _parse_task_includes(
        self,
        tasks: List[Dict[str, Any]],
        current_file: Path,
        visited: Set[Path],
        depth: int,
        include_chain: List[Path],
        loop_context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Parse includes from a list of tasks.

        Args:
            tasks: List of task dictionaries
            current_file: Current file being processed
            visited: Set of visited files
            depth: Current recursion depth
            include_chain: Chain of includes
            loop_context: Loop context if this file is included from a loop

        Returns:
            List of resolved includes
        """
        includes = []
        logger.debug(f"_parse_task_includes: processing {len(tasks)} tasks from {current_file}")

        for task_index, task in enumerate(tasks):
            if not isinstance(task, dict):
                logger.debug(f"_parse_task_includes: task {task_index} is not a dict, skipping")
                continue

            task_keys = list(task.keys())[:10]  # First 10 keys for debugging
            logger.debug(
                f"_parse_task_includes: task {task_index} keys (first 10): {task_keys}, name={task.get('name', 'N/A')}"
            )

            # Detect loop in this task
            task_loop_context = self._has_loop(task)
            # Use task's loop context if present, otherwise inherit from parent
            current_loop_context = task_loop_context if task_loop_context else loop_context

            # Check for include_tasks (short or FQCN)
            include_tasks_key = self._get_include_key(task, "include_tasks")
            if include_tasks_key:
                logger.debug(
                    f"_parse_task_includes: found include_tasks key={include_tasks_key} in task {task_index}"
                )
                includes.append(
                    self._resolve_include_task(
                        task[include_tasks_key],
                        current_file,
                        visited,
                        depth,
                        include_chain,
                        current_loop_context,
                    )
                )

            # Check for import_tasks (short or FQCN)
            import_tasks_key = self._get_include_key(task, "import_tasks")
            if import_tasks_key:
                includes.append(
                    self._resolve_import_task(
                        task[import_tasks_key],
                        current_file,
                        visited,
                        depth,
                        include_chain,
                        current_loop_context,
                    )
                )

            # Check for include_role (short or FQCN)
            include_role_key = self._get_include_key(task, "include_role")
            if include_role_key:
                logger.debug(
                    f"_parse_task_includes: found include_role key={include_role_key} in task {task_index}"
                )
                includes.append(
                    self._resolve_include_role(
                        task[include_role_key],
                        current_file,
                        visited,
                        depth,
                        include_chain,
                        current_loop_context,
                    )
                )

            # Check for import_role (short or FQCN)
            import_role_key = self._get_include_key(task, "import_role")
            if import_role_key:
                includes.append(
                    self._resolve_import_role(
                        task[import_role_key],
                        current_file,
                        visited,
                        depth,
                        include_chain,
                        current_loop_context,
                    )
                )

            # Check blocks
            if "block" in task:
                includes.extend(
                    self._parse_task_includes(
                        task["block"],
                        current_file,
                        visited,
                        depth,
                        include_chain,
                        current_loop_context,
                    )
                )

        logger.debug(
            f"_parse_task_includes: found {len(includes)} total includes from {len(tasks)} tasks"
        )
        return includes

    def _parse_role_includes(
        self,
        roles: Any,
        current_file: Path,
        visited: Set[Path],
        depth: int,
        include_chain: List[Path],
    ) -> List[Dict[str, Any]]:
        """Parse role includes from roles list.

        Args:
            roles: Roles list (can be list of strings or list of dicts)
            current_file: Current file being processed
            visited: Set of visited files
            depth: Current recursion depth
            include_chain: Chain of includes

        Returns:
            List of resolved role includes
        """
        includes = []

        if isinstance(roles, list):
            for role in roles:
                if isinstance(role, str):
                    includes.append(
                        self._resolve_role(role, current_file, visited, depth, include_chain)
                    )
                elif isinstance(role, dict):
                    role_name = role.get("role", role.get("name"))
                    if role_name:
                        includes.append(
                            self._resolve_role(
                                role_name, current_file, visited, depth, include_chain
                            )
                        )

        return includes

    def _resolve_include_task(
        self,
        include_ref: Any,
        current_file: Path,
        visited: Set[Path],
        depth: int,
        include_chain: List[Path],
        loop_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve an include_tasks reference.

        Args:
            include_ref: Include reference (string or dict)
            current_file: Current file being processed
            visited: Set of visited files
            depth: Current recursion depth
            include_chain: Chain of includes
            loop_context: Loop context if this include is from a loop

        Returns:
            Dictionary with resolved include information
        """
        logger.debug(
            f"_resolve_include_task: resolving include_ref={include_ref}, from={current_file}, depth={depth}"
        )
        if loop_context:
            logger.debug(f"_resolve_include_task: loop context: {loop_context}")

        if isinstance(include_ref, dict):
            include_ref = include_ref.get("file", include_ref.get("name"))

        if not isinstance(include_ref, str):
            logger.debug(f"_resolve_include_task: invalid reference type: {type(include_ref)}")
            return {
                "type": "include_tasks",
                "ref": str(include_ref),
                "resolved": False,
                "error": "Invalid reference",
            }

        logger.debug(f"_resolve_include_task: finding path for include_ref={include_ref}")
        resolved_path = self._find_include_path(include_ref, current_file)
        result = {
            "type": "include_tasks",
            "ref": include_ref,
            "resolved": resolved_path is not None,
        }
        if loop_context:
            result["loop_context"] = loop_context

        if resolved_path:
            result["path"] = str(resolved_path)
            logger.debug(
                f"_resolve_include_task: resolved path={resolved_path}, recursing with depth={depth + 1}"
            )
            # Recursively resolve includes from this file
            nested = self.resolve_includes(
                resolved_path, visited, depth + 1, include_chain, loop_context
            )
            nested_includes = nested.get("includes", [])
            result["includes"] = nested_includes
            logger.debug(
                f"_resolve_include_task: found {len(nested_includes)} nested includes in {resolved_path}"
            )
        else:
            logger.warning(
                f"_resolve_include_task: could not resolve path for include_ref={include_ref} from {current_file}"
            )

        # Cross-role detection: task in role A including task file from role B
        caller_role = _path_to_role_name(self.repo_root, current_file)
        target_role = _path_to_role_name(self.repo_root, resolved_path) if resolved_path else None
        if caller_role and target_role and caller_role != target_role:
            result["cross_role"] = True
            result["caller_role"] = caller_role
            result["target_role"] = target_role
        else:
            result["cross_role"] = False

        return result

    def _resolve_import_task(
        self,
        import_ref: Any,
        current_file: Path,
        visited: Set[Path],
        depth: int,
        include_chain: List[Path],
        loop_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve an import_tasks reference.

        Args:
            import_ref: Import reference (string or dict)
            current_file: Current file being processed
            visited: Set of visited files
            depth: Current recursion depth
            include_chain: Chain of includes
            loop_context: Loop context if this import is from a loop

        Returns:
            Dictionary with resolved import information
        """
        if isinstance(import_ref, dict):
            import_ref = import_ref.get("file", import_ref.get("name"))

        if not isinstance(import_ref, str):
            return {
                "type": "import_tasks",
                "ref": str(import_ref),
                "resolved": False,
                "error": "Invalid reference",
            }

        resolved_path = self._find_include_path(import_ref, current_file)
        result = {"type": "import_tasks", "ref": import_ref, "resolved": resolved_path is not None}
        if loop_context:
            result["loop_context"] = loop_context

        if resolved_path:
            result["path"] = str(resolved_path)
            # Recursively resolve includes from this file
            nested = self.resolve_includes(
                resolved_path, visited, depth + 1, include_chain, loop_context
            )
            result["includes"] = nested.get("includes", [])

        # Cross-role detection for import_tasks
        caller_role = _path_to_role_name(self.repo_root, current_file)
        target_role = _path_to_role_name(self.repo_root, resolved_path) if resolved_path else None
        if caller_role and target_role and caller_role != target_role:
            result["cross_role"] = True
            result["caller_role"] = caller_role
            result["target_role"] = target_role
        else:
            result["cross_role"] = False

        return result

    def _resolve_include_role(
        self,
        include_ref: Any,
        current_file: Path,
        visited: Set[Path],
        depth: int,
        include_chain: List[Path],
        loop_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve an include_role reference.

        Args:
            include_ref: Include reference (string or dict)
            current_file: Current file being processed
            visited: Set of visited files
            depth: Current recursion depth
            include_chain: Chain of includes
            loop_context: Loop context if this include is from a loop

        Returns:
            Dictionary with resolved role include information
        """
        if isinstance(include_ref, dict):
            include_ref = include_ref.get("name", include_ref.get("role"))

        if not isinstance(include_ref, str):
            return {
                "type": "include_role",
                "ref": str(include_ref),
                "resolved": False,
                "error": "Invalid reference",
            }

        return self._resolve_role(
            include_ref, current_file, visited, depth, include_chain, loop_context
        )

    def _resolve_import_role(
        self,
        import_ref: Any,
        current_file: Path,
        visited: Set[Path],
        depth: int,
        include_chain: List[Path],
        loop_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve an import_role reference.

        Args:
            import_ref: Import reference (string or dict)
            current_file: Current file being processed
            visited: Set of visited files
            depth: Current recursion depth
            include_chain: Chain of includes
            loop_context: Loop context if this import is from a loop

        Returns:
            Dictionary with resolved role import information
        """
        if isinstance(import_ref, dict):
            import_ref = import_ref.get("name", import_ref.get("role"))

        if not isinstance(import_ref, str):
            return {
                "type": "import_role",
                "ref": str(import_ref),
                "resolved": False,
                "error": "Invalid reference",
            }

        return self._resolve_role(
            import_ref, current_file, visited, depth, include_chain, loop_context
        )

    def _resolve_role(
        self,
        role_name: str,
        current_file: Path,
        visited: Set[Path],
        depth: int,
        include_chain: List[Path],
        loop_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve a role reference.

        Args:
            role_name: Name of the role
            current_file: Current file being processed
            visited: Set of visited files
            depth: Current recursion depth
            include_chain: Chain of includes
            loop_context: Loop context if this role is included from a loop

        Returns:
            Dictionary with resolved role information
        """
        logger.debug(
            f"_resolve_role: resolving role={role_name}, from={current_file}, depth={depth}"
        )
        if loop_context:
            logger.debug(f"_resolve_role: loop context: {loop_context}")

        # Find role directory
        role_path = self._find_role_path(role_name)
        result = {"type": "role", "name": role_name, "resolved": role_path is not None}
        if loop_context:
            result["loop_context"] = loop_context

        caller_role = _path_to_role_name(self.repo_root, current_file)
        if caller_role is not None and caller_role != role_name:
            result["cross_role"] = True
            result["caller_role"] = caller_role
            result["target_role"] = role_name
        else:
            result["cross_role"] = False

        if role_path:
            result["path"] = str(role_path)
            logger.debug(f"_resolve_role: found role path: {role_path}")
            # Find main tasks file
            main_tasks = role_path / "tasks" / "main.yml"
            if not main_tasks.exists():
                main_tasks = role_path / "tasks" / "main.yaml"

            if main_tasks.exists():
                result["main_tasks"] = str(main_tasks)
                logger.debug(
                    f"_resolve_role: found main tasks file: {main_tasks}, recursing with depth={depth + 1}"
                )
                # Recursively resolve includes from role tasks
                nested = self.resolve_includes(
                    main_tasks, visited, depth + 1, include_chain, loop_context
                )
                nested_includes = nested.get("includes", [])
                result["includes"] = nested_includes
                logger.debug(
                    f"_resolve_role: found {len(nested_includes)} nested includes in role {role_name}"
                )
            else:
                logger.debug(f"_resolve_role: no main tasks file found for role {role_name}")

        return result

    def _find_include_path(self, include_ref: str, current_file: Path) -> Optional[Path]:
        """Find the path for an include reference.

        Tries multiple resolution strategies:
        1. Relative to current file
        2. From repo root (roles/, tasks/, etc.)
        3. Standard Ansible paths

        Args:
            include_ref: Include reference string
            current_file: Current file being processed

        Returns:
            Resolved path or None if not found
        """
        logger.debug(f"Finding include path for: {include_ref} (from {current_file})")
        attempted_paths = []

        # Try 1: Relative to current file
        path1 = current_file.parent / include_ref
        attempted_paths.append(str(path1))
        logger.debug(f"_find_include_path: trying path1 (relative to file): {path1}")
        if path1.exists() and path1.is_file():
            logger.debug(f"Found include path (relative to file): {path1}")
            return path1
        else:
            logger.debug("_find_include_path: path1 does not exist or is not a file")

        # Try 2: From repo root
        path2 = self.repo_root / include_ref
        attempted_paths.append(str(path2))
        logger.debug(f"_find_include_path: trying path2 (from repo root): {path2}")
        if path2.exists() and path2.is_file():
            logger.debug(f"Found include path (from repo root): {path2}")
            return path2
        else:
            logger.debug("_find_include_path: path2 does not exist or is not a file")

        # Try 3: Standard Ansible paths
        # Try tasks/ directory relative to current file
        if current_file.parent.name == "tasks":
            path3 = current_file.parent / include_ref
            attempted_paths.append(str(path3))
            logger.debug(f"_find_include_path: trying path3 (tasks directory): {path3}")
            if path3.exists() and path3.is_file():
                logger.debug(f"Found include path (tasks directory): {path3}")
                return path3
            else:
                logger.debug("_find_include_path: path3 does not exist or is not a file")

        # Try roles/*/tasks/ directory
        roles_dir = self.repo_root / "roles"
        if roles_dir.exists():
            logger.debug(f"_find_include_path: searching in roles directory: {roles_dir}")
            for role_dir in roles_dir.iterdir():
                if role_dir.is_dir():
                    tasks_dir = role_dir / "tasks"
                    if tasks_dir.exists():
                        path4 = tasks_dir / include_ref
                        attempted_paths.append(str(path4))
                        logger.debug(f"_find_include_path: trying path4 (role tasks): {path4}")
                        if path4.exists() and path4.is_file():
                            logger.debug(f"Found include path (role tasks): {path4}")
                            return path4

        # Not found
        logger.warning(
            f"Could not resolve include path: {include_ref} (attempted {len(attempted_paths)} paths)"
        )
        logger.debug(f"_find_include_path: attempted paths: {attempted_paths}")
        self.error_collector.add_error(
            "MISSING_FILE",
            f"Include file not found: {include_ref}",
            current_file,
            {"include_ref": include_ref, "attempted_paths": attempted_paths},
        )
        return None

    def _find_role_path(self, role_name: str) -> Optional[Path]:
        """Find the path for a role.

        Args:
            role_name: Name of the role

        Returns:
            Resolved role directory path or None if not found
        """
        logger.debug(f"Finding role path for: {role_name}")

        # Try standard roles/ directory
        role_path = self.repo_root / "roles" / role_name
        if role_path.exists() and role_path.is_dir():
            logger.debug(f"Found role path: {role_path}")
            return role_path

        # Not found
        logger.warning(f"Could not resolve role path: {role_name}")
        self.error_collector.add_error(
            "MISSING_FILE", f"Role not found: {role_name}", None, {"role_name": role_name}
        )
        return None


class TemplateFinder:
    """Finds template files used in Ansible playbooks and roles."""

    def __init__(self, repo_root: Path, error_collector: ErrorCollector):
        """Initialize the TemplateFinder.

        Args:
            repo_root: Repository root directory
            error_collector: ErrorCollector instance for error reporting
        """
        self.repo_root = repo_root
        self.error_collector = error_collector
        logger.debug(f"TemplateFinder initialized with repo_root: {repo_root}")

    def _get_template_key(self, task: Dict[str, Any]) -> Optional[str]:
        """Get template key from task, checking both short and FQCN forms.

        Args:
            task: Task dictionary

        Returns:
            Key name if found (short or FQCN), None otherwise
        """
        # Check short form first
        if "template" in task:
            return "template"

        # Check FQCN form
        fqcn_name = "ansible.builtin.template"
        if fqcn_name in task:
            return fqcn_name

        # Check other common FQCN forms
        for collection in ["ansible.legacy", "ansible.posix"]:
            fqcn_alt = f"{collection}.template"
            if fqcn_alt in task:
                return fqcn_alt

        return None

    def find_templates(self, tasks: List[Dict[str, Any]], file_path: Path) -> List[Dict[str, Any]]:
        """Find template files used in tasks.

        Templates can be unnamed and may have with_items or loop_control.
        This method detects templates using both short and FQCN module names.

        Args:
            tasks: List of task dictionaries
            file_path: File path where tasks are defined

        Returns:
            List of template usage information
        """
        logger.debug(f"Finding templates in tasks from: {file_path}")
        templates = []

        for task in tasks:
            if not isinstance(task, dict):
                continue

            # Check for template module usage (short or FQCN)
            # Templates can be unnamed and may have with_items/loop_control
            template_key = self._get_template_key(task)
            if template_key:
                logger.debug(f"Found template task with key: {template_key}")
                template_info = self._extract_template_usage(task[template_key], file_path)
                if template_info:
                    templates.append(template_info)
                    logger.debug(f"Extracted template: {template_info.get('template', 'N/A')}")

            # Check blocks
            if "block" in task:
                templates.extend(self.find_templates(task["block"], file_path))

        logger.debug(f"Found {len(templates)} templates in tasks from: {file_path}")
        return templates

    def _extract_template_usage(
        self, template_data: Any, file_path: Path
    ) -> Optional[Dict[str, Any]]:
        """Extract template usage information from a template task.

        Args:
            template_data: Template task data (string or dict)
            file_path: File path where template is used

        Returns:
            Dictionary with template usage information or None
        """
        template_path = None

        if isinstance(template_data, str):
            template_path = template_data
        elif isinstance(template_data, dict):
            template_path = template_data.get("src", template_data.get("dest"))

        if not template_path:
            return None

        # Resolve template path
        resolved_path = self._find_template_path(template_path, file_path)

        result = {
            "template": template_path,
            "resolved_path": str(resolved_path) if resolved_path else None,
            "used_in": str(file_path),
            "found": resolved_path is not None,
        }
        caller_role = _path_to_role_name(self.repo_root, file_path)
        if resolved_path is not None:
            template_role = _path_to_role_name(self.repo_root, resolved_path)
            if (
                caller_role is not None
                and template_role is not None
                and caller_role != template_role
            ):
                result["cross_role"] = True
                result["caller_role"] = caller_role
                result["template_role"] = template_role
            else:
                result["cross_role"] = False
        else:
            result["cross_role"] = False
        return result

    def _find_template_path(  # noqa: C901
        self, template_ref: str, current_file: Path
    ) -> Optional[Path]:
        """Find the path for a template reference.

        Args:
            template_ref: Template reference string
            current_file: Current file being processed

        Returns:
            Resolved template path or None if not found
        """
        logger.debug(f"Finding template path for: {template_ref}")

        # Try relative to current file's templates directory
        if current_file.parent.name == "tasks":
            # If we're in tasks/, look for templates/ in the same role/directory
            templates_dir = current_file.parent.parent / "templates"
            if templates_dir.exists():
                template_path = templates_dir / template_ref
                if template_path.exists():
                    logger.debug(f"Found template path (role templates): {template_path}")
                    return template_path

        # Try relative to repo root templates/
        templates_dir = self.repo_root / "templates"
        if templates_dir.exists():
            template_path = templates_dir / template_ref
            if template_path.exists():
                logger.debug(f"Found template path (repo templates): {template_path}")
                return template_path

        # Try in roles/*/templates/
        roles_dir = self.repo_root / "roles"
        if roles_dir.exists():
            for role_dir in roles_dir.iterdir():
                if role_dir.is_dir():
                    templates_dir = role_dir / "templates"
                    if templates_dir.exists():
                        template_path = templates_dir / template_ref
                        if template_path.exists():
                            logger.debug(f"Found template path (role templates): {template_path}")
                            return template_path

        # Not found
        logger.warning(f"Could not resolve template path: {template_ref}")
        return None

    def scan_role_templates(self, role_path: Path) -> List[Path]:
        """Scan a role's templates directory for .j2 files.

        Args:
            role_path: Path to role directory

        Returns:
            List of template file paths found
        """
        logger.debug(f"Scanning role templates: {role_path}")
        templates = []

        templates_dir = role_path / "templates"
        if templates_dir.exists() and templates_dir.is_dir():
            for template_file in templates_dir.rglob("*"):
                if template_file.is_file() and template_file.suffix in TEMPLATE_EXTENSIONS:
                    templates.append(template_file)
                    logger.debug(f"Found template file: {template_file}")

        return templates

    def find_templates_in_role_tasks(  # noqa: C901
        self, role_path: Path, include_resolver: "IncludeResolver"
    ) -> List[Dict[str, Any]]:
        """Find templates used in role task files.

        Scans all task files in a role and finds template module usage.

        Args:
            role_path: Path to role directory
            include_resolver: IncludeResolver instance for parsing YAML files

        Returns:
            List of template usage information
        """
        logger.debug(f"Finding templates in role tasks: {role_path}")
        templates = []

        tasks_dir = role_path / "tasks"
        if not tasks_dir.exists() or not tasks_dir.is_dir():
            logger.debug(f"No tasks directory found in role: {role_path}")
            return templates

        # Scan all YAML files in tasks directory
        for task_file in tasks_dir.rglob("*"):
            if task_file.is_file() and task_file.suffix in YAML_EXTENSIONS:
                logger.debug(f"Scanning task file for templates: {task_file}")
                try:
                    # Parse task file
                    content = include_resolver._parse_yaml_file(task_file)
                    if content is None:
                        continue

                    # Extract tasks from content
                    tasks = []
                    if isinstance(content, list):
                        # List of tasks
                        tasks = content
                    elif isinstance(content, dict):
                        # Could be a single task or a play
                        if "tasks" in content:
                            tasks = content["tasks"]
                        elif any(key in content for key in ["name", "hosts"]):
                            # It's a play, extract tasks
                            tasks = content.get("tasks", [])
                        else:
                            # Single task dict
                            tasks = [content]

                    # Find templates in tasks
                    file_templates = self.find_templates(tasks, task_file)
                    templates.extend(file_templates)
                    logger.debug(f"Found {len(file_templates)} templates in task file: {task_file}")

                except Exception as e:
                    logger.warning(
                        f"Error scanning task file {task_file} for templates: {e}", exc_info=True
                    )

        logger.debug(f"Found {len(templates)} total templates in role tasks: {role_path}")
        return templates


class StructureBuilder:
    """Builds hierarchical structure from analyzed playbooks and roles."""

    def __init__(self, repo_root: Path):
        """Initialize the StructureBuilder.

        Args:
            repo_root: Repository root directory
        """
        self.repo_root = repo_root
        logger.debug(f"StructureBuilder initialized with repo_root: {repo_root}")

    def build_structure(
        self,
        playbooks: List[Dict[str, Any]],
        roles: List[Dict[str, Any]],
        templates: List[Dict[str, Any]],
        errors: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build hierarchical structure from analysis results.

        Args:
            playbooks: List of playbook analysis results
            roles: List of role analysis results
            templates: List of template usage information
            errors: List of errors collected

        Returns:
            Dictionary containing complete structure
        """
        logger.info("Building hierarchical structure")

        structure = {
            "metadata": {
                "analyzed_at": datetime.now().isoformat(),
                "repo_root": str(self.repo_root),
            },
            "playbooks": playbooks,
            "roles": roles,
            "templates": templates,
            "errors": errors,
            "statistics": self._calculate_statistics(playbooks, roles, templates, errors),
        }

        logger.debug(
            f"Structure built with {len(playbooks)} playbooks, {len(roles)} roles, {len(templates)} templates"
        )
        return structure

    def _calculate_statistics(
        self,
        playbooks: List[Dict[str, Any]],
        roles: List[Dict[str, Any]],
        templates: List[Dict[str, Any]],
        errors: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Calculate statistics from analysis results.

        Args:
            playbooks: List of playbook analysis results
            roles: List of role analysis results
            templates: List of template usage information
            errors: List of errors collected

        Returns:
            Dictionary with statistics
        """
        total_includes = sum(len(pb.get("includes", [])) for pb in playbooks)
        total_roles = len(roles)
        total_templates = len(set(t.get("template") for t in templates if t.get("template")))

        return {
            "total_playbooks": len(playbooks),
            "total_roles": total_roles,
            "total_includes": total_includes,
            "total_templates": total_templates,
            "total_errors": len(errors),
        }


class OutputGenerator:
    """Generates JSON and Markdown output reports."""

    def __init__(self, output_dir: Path):
        """Initialize the OutputGenerator.

        Args:
            output_dir: Directory for output files
        """
        self.output_dir = output_dir
        logger.debug(f"OutputGenerator initialized with output_dir: {output_dir}")

    def generate_json(
        self, structure: Dict[str, Any], filename: str = "ansible_structure.json"
    ) -> Path:
        """Generate JSON output file.

        Args:
            structure: Structure dictionary to output
            filename: Output filename

        Returns:
            Path to generated file

        Raises:
            IOError: If file cannot be written
        """
        logger.info(f"Generating JSON output: {filename}")

        try:
            output_path = self.output_dir / filename

            with output_path.open("w", encoding="utf-8") as f:
                json.dump(structure, f, indent=2, ensure_ascii=False)

            logger.info(f"JSON output saved to: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Error generating JSON output: {e}", exc_info=True)
            raise

    def generate_markdown(  # noqa: C901
        self, structure: Dict[str, Any], filename: str = "ansible_structure.md"
    ) -> Path:
        """Generate Markdown output file.

        Args:
            structure: Structure dictionary to output
            filename: Output filename

        Returns:
            Path to generated file

        Raises:
            IOError: If file cannot be written
        """
        logger.info(f"Generating Markdown output: {filename}")

        try:
            output_path = self.output_dir / filename

            with output_path.open("w", encoding="utf-8") as f:
                f.write("# Ansible Structure Analysis\n\n")
                f.write(f"**Generated**: {structure['metadata']['analyzed_at']}\n")
                f.write(f"**Repository Root**: {structure['metadata']['repo_root']}\n\n")

                # Statistics
                stats = structure.get("statistics", {})
                f.write("## Statistics\n\n")
                f.write(f"- Total Playbooks: {stats.get('total_playbooks', 0)}\n")
                f.write(f"- Total Roles: {stats.get('total_roles', 0)}\n")
                f.write(f"- Total Includes: {stats.get('total_includes', 0)}\n")
                f.write(f"- Total Templates: {stats.get('total_templates', 0)}\n")
                f.write(f"- Total Errors: {stats.get('total_errors', 0)}\n\n")

                # Playbooks
                f.write("## Playbooks\n\n")
                for pb in structure.get("playbooks", []):
                    f.write(f"### {pb.get('file', 'Unknown')}\n\n")
                    includes = pb.get("includes", [])
                    if includes:
                        f.write(f"#### Includes ({len(includes)} items)\n\n")
                        self._write_includes_markdown(f, includes, indent=0)
                    f.write("\n")

                # Roles
                f.write("## Roles\n\n")
                for role in structure.get("roles", []):
                    f.write(f"### {role.get('name', 'Unknown')}\n\n")
                    f.write(f"- Path: {role.get('path', 'N/A')}\n")
                    role_includes = role.get("includes", [])
                    if role_includes:
                        f.write(f"#### Includes ({len(role_includes)} items)\n\n")
                        self._write_includes_markdown(f, role_includes, indent=0)
                    f.write("\n")

                # Templates
                f.write("## Templates\n\n")
                f.write("| Template File | Used In | Cross-role |\n")
                f.write("|--------------|----------|------------|\n")
                for template in structure.get("templates", []):
                    template_file = template.get("template", "N/A")
                    used_in = template.get("used_in", "N/A")
                    cross_role = ""
                    if (
                        template.get("cross_role")
                        and template.get("caller_role")
                        and template.get("template_role")
                    ):
                        cross_role = f"{template['caller_role']} -> {template['template_role']}"
                    else:
                        cross_role = "-"
                    f.write(f"| {template_file} | {used_in} | {cross_role} |\n")
                f.write("\n")

                # Errors
                errors = structure.get("errors", [])
                if errors:
                    f.write("## Errors\n\n")
                    for error in errors:
                        f.write(f"### {error.get('type', 'Unknown')}\n\n")
                        f.write(f"- **Message**: {error.get('message', 'N/A')}\n")
                        if error.get("file"):
                            f.write(f"- **File**: {error.get('file')}\n")
                        f.write("\n")

                # Cross-role summary
                task_includes, role_includes, template_usage = self._collect_cross_role_summary(
                    structure
                )
                if task_includes or role_includes or template_usage:
                    f.write("## Cross-role summary\n\n")
                    if task_includes:
                        f.write("### Cross-role task includes\n\n")
                        for caller, target, ref in task_includes:
                            f.write(f"- {caller} -> {target}: `{ref}`\n")
                        f.write("\n")
                    if role_includes:
                        f.write("### Cross-role role includes\n\n")
                        for caller, target in role_includes:
                            f.write(f"- {caller} -> {target}\n")
                        f.write("\n")
                    if template_usage:
                        f.write("### Cross-role template usage\n\n")
                        for caller, t_role, t_path, used_in in template_usage:
                            f.write(
                                f"- {caller} -> {t_role}: template `{t_path}` (used in {used_in})\n"
                            )
                        f.write("\n")

            logger.info(f"Markdown output saved to: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Error generating Markdown output: {e}", exc_info=True)
            raise

    def _collect_cross_role_summary(self, structure: Dict[str, Any]) -> tuple:  # noqa: C901
        """Collect cross-role task includes, role includes, and template usage from structure.

        Args:
            structure: Full structure dict from analyzer.

        Returns:
            Tuple of (task_includes, role_includes, template_usage).
            task_includes: List of (caller_role, target_role, ref).
            role_includes: List of (caller_role, target_role).
            template_usage: List of (caller_role, template_role, template_path, used_in).
        """
        task_includes: List[tuple] = []
        role_includes: List[tuple] = []

        def walk(includes: List[Dict[str, Any]]) -> None:
            for inc in includes:
                if inc.get("cross_role") and inc.get("caller_role") and inc.get("target_role"):
                    if inc.get("type") in ("include_tasks", "import_tasks"):
                        ref = inc.get("ref") or inc.get("path") or "?"
                        task_includes.append((inc["caller_role"], inc["target_role"], ref))
                    elif inc.get("type") in ("include_role", "import_role", "role"):
                        role_includes.append((inc["caller_role"], inc["target_role"]))
                for nested in inc.get("includes") or []:
                    walk([nested])

        for pb in structure.get("playbooks", []):
            walk(pb.get("includes") or [])
        for role in structure.get("roles", []):
            walk(role.get("includes") or [])

        template_usage: List[tuple] = []
        for t in structure.get("templates", []):
            if t.get("cross_role") and t.get("caller_role") and t.get("template_role"):
                template_usage.append(
                    (
                        t["caller_role"],
                        t["template_role"],
                        t.get("template", "N/A"),
                        t.get("used_in", "N/A"),
                    )
                )

        return task_includes, role_includes, template_usage

    def _write_includes_markdown(self, f, includes: List[Dict[str, Any]], indent: int = 0) -> None:
        """Write includes to markdown file recursively.

        Args:
            f: File handle to write to
            includes: List of include dictionaries
            indent: Indentation level for nested includes
        """
        indent_prefix = "  " * indent
        for include in includes:
            include_type = include.get("type", "unknown")
            loop_context = include.get("loop_context")
            loop_suffix = f" [{loop_context}]" if loop_context else ""
            cross_note = ""
            if include.get("cross_role") and include.get("target_role"):
                cross_note = f" (cross-role: {include['target_role']})"

            if include_type == "role":
                role_name = include.get("name", "N/A")
                resolved = include.get("resolved", False)
                status = "✓" if resolved else "✗"
                f.write(
                    f"{indent_prefix}- {status} **Role**: `{role_name}`{loop_suffix}{cross_note}\n"
                )
                if include.get("path"):
                    f.write(f"{indent_prefix}  - Path: `{include.get('path')}`\n")
            elif include_type in ["include_tasks", "import_tasks"]:
                ref = include.get("ref", "N/A")
                resolved = include.get("resolved", False)
                status = "✓" if resolved else "✗"
                f.write(
                    f"{indent_prefix}- {status} **{include_type}**: `{ref}`{loop_suffix}{cross_note}\n"
                )
                if include.get("path"):
                    f.write(f"{indent_prefix}  - Path: `{include.get('path')}`\n")
            elif include_type in ["include_role", "import_role"]:
                ref = include.get("ref", include.get("name", "N/A"))
                resolved = include.get("resolved", False)
                status = "✓" if resolved else "✗"
                f.write(
                    f"{indent_prefix}- {status} **{include_type}**: `{ref}`{loop_suffix}{cross_note}\n"
                )
                if include.get("path"):
                    f.write(f"{indent_prefix}  - Path: `{include.get('path')}`\n")
            else:
                ref = include.get("ref", str(include))
                resolved = include.get("resolved", False)
                status = "✓" if resolved else "✗"
                f.write(
                    f"{indent_prefix}- {status} **{include_type}**: `{ref}`{loop_suffix}{cross_note}\n"
                )

            # Write nested includes
            nested_includes = include.get("includes", [])
            if nested_includes:
                self._write_includes_markdown(f, nested_includes, indent + 1)


class AnsibleStructureAnalyzer:
    """Orchestrates the analysis of Ansible playbooks and roles."""

    def __init__(self, repo_root: Path, max_depth: int = MAX_RECURSION_DEPTH):
        """Initialize the AnsibleStructureAnalyzer.

        Args:
            repo_root: Repository root directory
            max_depth: Maximum recursion depth for includes
        """
        self.repo_root = Path(repo_root).resolve()
        self.max_depth = max_depth
        logger.info(f"Initializing AnsibleStructureAnalyzer for repo_root: {self.repo_root}")

        if not self.repo_root.is_dir():
            logger.error(f"Repository root not found: {self.repo_root}")
            raise NotADirectoryError(f"Repository root not found: {self.repo_root}")

        self.file_discovery = FileDiscovery()
        self.error_collector = ErrorCollector()
        self.include_resolver = IncludeResolver(self.repo_root, self.error_collector, max_depth)
        self.template_finder = TemplateFinder(self.repo_root, self.error_collector)
        self.structure_builder = StructureBuilder(self.repo_root)

    def analyze(self, input_path: Path) -> Dict[str, Any]:
        """Run the analysis on input playbook(s).

        Args:
            input_path: Single playbook file or directory containing playbooks

        Returns:
            Dictionary containing complete structure analysis
        """
        logger.info(f"Starting analysis of: {input_path}")

        try:
            # Discover files
            playbook_files = self.file_discovery.discover_files(input_path)
            logger.info(f"Found {len(playbook_files)} playbook file(s) to analyze")

            if not playbook_files:
                logger.warning("No playbook files found")
                return self.structure_builder.build_structure(
                    [], [], [], self.error_collector.get_errors()
                )

            # Analyze each playbook
            playbooks = []
            all_roles = {}
            all_templates = []

            for pb_file in playbook_files:
                logger.info(f"Analyzing playbook: {pb_file}")
                playbook_result = self._analyze_playbook(pb_file)
                playbooks.append(playbook_result)

                # Collect roles and templates
                self._collect_roles_and_templates(playbook_result, all_roles, all_templates)

            # Build structure
            structure = self.structure_builder.build_structure(
                playbooks,
                list(all_roles.values()),
                all_templates,
                self.error_collector.get_errors(),
            )

            logger.info("Analysis complete")
            return structure

        except Exception as e:
            logger.error(f"Error during analysis: {e}", exc_info=True)
            raise

    def _analyze_playbook(self, playbook_path: Path) -> Dict[str, Any]:
        """Analyze a single playbook file.

        Args:
            playbook_path: Path to playbook file

        Returns:
            Dictionary with playbook analysis results
        """
        logger.debug(f"Analyzing playbook: {playbook_path}")

        # Resolve includes
        include_result = self.include_resolver.resolve_includes(playbook_path)

        # Parse playbook to find tasks
        content = self.include_resolver._parse_yaml_file(playbook_path)
        tasks = []
        if isinstance(content, list):
            for play in content:
                if isinstance(play, dict):
                    tasks.extend(play.get("tasks", []))
                    tasks.extend(play.get("pre_tasks", []))
                    tasks.extend(play.get("post_tasks", []))
        elif isinstance(content, dict):
            tasks.extend(content.get("tasks", []))
            tasks.extend(content.get("pre_tasks", []))
            tasks.extend(content.get("post_tasks", []))

        # Find templates
        templates = self.template_finder.find_templates(tasks, playbook_path)

        return {
            "file": str(playbook_path.relative_to(self.repo_root)),
            "includes": include_result.get("includes", []),
            "templates": templates,
        }

    def _collect_roles_and_templates(
        self,
        playbook_result: Dict[str, Any],
        all_roles: Dict[str, Dict[str, Any]],
        all_templates: List[Dict[str, Any]],
    ) -> None:
        """Collect roles and templates from playbook results.

        Args:
            playbook_result: Playbook analysis result
            all_roles: Dictionary to collect roles in
            all_templates: List to collect templates in
        """

        def process_includes(includes: List[Dict[str, Any]]) -> None:
            for include in includes:
                if include.get("type") == "role":
                    role_name = include.get("name")
                    if role_name and role_name not in all_roles:
                        role_path = self.include_resolver._find_role_path(role_name)
                        if role_path:
                            # Scan role templates directory for .j2 files
                            role_template_files = self.template_finder.scan_role_templates(
                                role_path
                            )
                            # Find templates used in role task files
                            role_task_templates = self.template_finder.find_templates_in_role_tasks(
                                role_path, self.include_resolver
                            )
                            # Collect templates from role tasks
                            all_templates.extend(role_task_templates)
                            logger.debug(
                                f"Found {len(role_task_templates)} templates in role {role_name} tasks"
                            )
                            all_roles[role_name] = {
                                "name": role_name,
                                "path": str(role_path.relative_to(self.repo_root)),
                                "templates": [
                                    str(t.relative_to(self.repo_root)) for t in role_template_files
                                ],
                                "includes": include.get("includes", []),
                            }
                            # Process nested includes
                            process_includes(include.get("includes", []))

                # Process nested includes
                if "includes" in include:
                    process_includes(include.get("includes", []))

        # Process playbook includes
        process_includes(playbook_result.get("includes", []))

        # Collect templates from playbook
        all_templates.extend(playbook_result.get("templates", []))


@click.command()
@click.option(
    "--input",
    "input_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Single playbook file or top-level directory containing playbooks (can be relative to repo-root).",
)
@click.option(
    "--repo-root",
    "repo_root",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Repository root directory for resolving relative paths.",
)
@click.option(
    "--output-dir",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory for output files (default: tmp/ in current directory).",
)
@click.option(
    "--max-depth",
    type=int,
    default=MAX_RECURSION_DEPTH,
    show_default=True,
    help="Maximum recursion depth for includes.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "markdown", "both"], case_sensitive=False),
    default="both",
    show_default=True,
    help="Output format: json, markdown, or both.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
@click.option("--debug", "-d", is_flag=True, help="Enable debug logging (same as --verbose).")
def main(  # noqa: C901
    input_path: Path,
    repo_root: Path,
    output_dir: Path,
    max_depth: int,
    output_format: str,
    verbose: bool,
    debug: bool,
):
    """Analyzes Ansible playbooks and roles to document structure, includes, and templates."""
    # Setup logging early
    log_level = logging.DEBUG if (verbose or debug) else logging.INFO
    script_name = Path(__file__).stem
    setup_logging(level=log_level, script_name=script_name)
    logger.info("Ansible Structure Analyzer started")

    # Log file location info
    from pyplayground.utils.logging_utils import DEFAULT_LOG_DIR

    console = Console()

    log_dir = Path(DEFAULT_LOG_DIR)
    if log_dir.exists():
        log_files = sorted(
            log_dir.glob(f"{script_name}_*.log"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        if log_files:
            console.print(f"[dim]Log file: {log_files[0]}[/dim]")

    # Resolve input path - try relative to current directory first, then relative to repo-root
    resolved_input_path = None

    # Try 1: Absolute path or relative to current directory
    if input_path.is_absolute():
        resolved_input_path = input_path
    else:
        resolved_input_path = Path.cwd() / input_path

    # Try 2: Relative to repo-root if not found
    if not resolved_input_path.exists():
        repo_root_path = Path(repo_root).resolve()
        resolved_input_path = repo_root_path / input_path
        logger.debug(f"Trying input path relative to repo-root: {resolved_input_path}")

    # Validate resolved path
    if not resolved_input_path.exists():
        logger.error(
            f"Input path not found: {input_path} (tried: {Path.cwd() / input_path}, {Path(repo_root) / input_path})"
        )
        raise FileNotFoundError(
            f"Input path '{input_path}' not found. Tried relative to current directory and repo-root."
        )

    logger.info(f"Resolved input path: {resolved_input_path}")
    input_path = resolved_input_path

    # Set default output directory to tmp/ if not specified
    if output_dir is None:
        output_dir = Path.cwd() / "tmp"
        logger.debug(f"Using default output directory: {output_dir}")

    # Ensure output directory exists
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Output directory: {output_dir}")

    # Generate base filename from input path
    if input_path.is_file():
        base_name = input_path.stem
    else:
        # For directories, use directory name
        base_name = input_path.name if input_path.name else "ansible_structure"
    logger.debug(f"Generated base filename: {base_name}")

    try:
        with console.status("[bold green]Analyzing Ansible structure..."):
            analyzer = AnsibleStructureAnalyzer(repo_root, max_depth)
            structure = analyzer.analyze(input_path)

            # Generate output with base filename
            output_gen = OutputGenerator(output_dir)

            if output_format in ["json", "both"]:
                json_filename = f"{base_name}_structure.json"
                json_path = output_gen.generate_json(structure, filename=json_filename)
                console.print(f"[bold green]JSON output saved to: {json_path}[/bold green]")

            if output_format in ["markdown", "both"]:
                md_filename = f"{base_name}_structure.md"
                md_path = output_gen.generate_markdown(structure, filename=md_filename)
                console.print(f"[bold green]Markdown output saved to: {md_path}[/bold green]")

            # Generate summary report
            stats = structure.get("statistics", {})
            save_summary_report(
                summary_data=stats,
                report_title="Ansible Structure Analysis Summary",
                script_name="ansible_structure_analyzer",
            )

            # Display summary
            console.print("\n[bold]Analysis Summary:[/bold]")
            console.print(f"  Playbooks: {stats.get('total_playbooks', 0)}")
            console.print(f"  Roles: {stats.get('total_roles', 0)}")
            console.print(f"  Includes: {stats.get('total_includes', 0)}")
            console.print(f"  Templates: {stats.get('total_templates', 0)}")
            console.print(f"  Errors: {stats.get('total_errors', 0)}")

    except Exception as e:
        logger.error(f"An error occurred during analysis: {e}", exc_info=True)
        console.print(f"[bold red]Error: {e}[/bold red]")
        raise


if __name__ == "__main__":
    main()
