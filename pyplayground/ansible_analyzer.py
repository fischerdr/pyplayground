#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ansible Playbook Analyzer.

This script analyzes Ansible playbooks from a given repository to identify
and extract shell, command, raw, and script module calls. It supports both
short module names (shell, command, raw, script) and fully qualified
collection names (ansible.builtin.shell, ansible.builtin.command, etc.).

It helps in planning migrations to Ansible Automation Platform (AAP)
Execution Environments by identifying external dependencies and commands.
"""

import csv
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import click
import yaml
from rich.console import Console
from rich.table import Table

from pyplayground.utils.logging_utils import get_logger, setup_logging
from pyplayground.utils.password_finder import create_custom_yaml_loader
from pyplayground.utils.report_utils import save_summary_report

# Constants
TARGET_MODULES = ["shell", "command", "raw", "script"]
TARGET_MODULES_FQCN = [
    "ansible.builtin.shell",
    "ansible.builtin.command",
    "ansible.builtin.raw",
    "ansible.builtin.script",
]
# Combined list for easier checking
ALL_TARGET_MODULES = TARGET_MODULES + TARGET_MODULES_FQCN
YAML_EXTENSIONS = [".yml", ".yaml"]
ROLE_VARS_DIRS = ["vars", "defaults"]
TOP_LEVEL_VARS_DIRS = ["group_vars", "host_vars"]

logger = get_logger(__name__)


class VariableManager:
    """Manages Ansible variables and their resolution."""

    def __init__(self, repo_path: Path):
        """Initialize the VariableManager."""
        self.repo_path = repo_path
        self.variables: Dict[str, Any] = {}
        self.unresolved_variables: Set[str] = set()
        logger.info(f"Initializing VariableManager for repository: {self.repo_path}")
        self.load_variables()

    def load_variables(self):  # noqa: C901
        """Load variables from common Ansible locations."""
        logger.info("Starting variable loading process")
        vars_loaded_count = 0

        # This is a simplified implementation. A real one would need inventory parsing
        # to understand groups and hosts to load files in the correct precedence.
        # For now, we load all vars files we find.
        for var_dir in TOP_LEVEL_VARS_DIRS:
            dir_path = self.repo_path / var_dir
            logger.debug(f"Checking for top-level vars directory: {dir_path}")
            if dir_path.is_dir():
                logger.info(f"Found top-level vars directory: {dir_path}")
                for var_file in dir_path.glob("**/*"):
                    if var_file.suffix in YAML_EXTENSIONS and var_file.is_file():
                        logger.debug(f"Found vars file: {var_file}")
                        self.load_vars_from_file(var_file)
                        vars_loaded_count += 1
            else:
                logger.debug(f"Top-level vars directory not found: {dir_path}")

        roles_path = self.repo_path / "roles"
        logger.debug(f"Checking for roles directory: {roles_path}")
        if roles_path.is_dir():
            logger.info(f"Found roles directory: {roles_path}")
            role_count = 0
            for role_dir in roles_path.iterdir():
                if role_dir.is_dir():
                    role_count += 1
                    logger.debug(f"Processing role directory: {role_dir}")
                    for var_dir_name in ROLE_VARS_DIRS:
                        var_dir = role_dir / var_dir_name
                        logger.debug(f"Checking role vars directory: {var_dir}")
                        if var_dir.is_dir():
                            logger.debug(f"Found role vars directory: {var_dir}")
                            for var_file in var_dir.glob("**/*"):
                                if var_file.suffix in YAML_EXTENSIONS and var_file.is_file():
                                    logger.debug(f"Found role vars file: {var_file}")
                                    self.load_vars_from_file(var_file)
                                    vars_loaded_count += 1
                        else:
                            logger.debug(f"Role vars directory not found: {var_dir}")
            logger.info(f"Processed {role_count} role directories")
        else:
            logger.debug(f"Roles directory not found: {roles_path}")

        logger.info(f"Variable loading complete. Loaded {vars_loaded_count} variable files")
        logger.info(f"Total variables loaded: {len(self.variables)}")
        logger.debug(f"Variable names: {list(self.variables.keys())}")

    def load_vars_from_file(self, file_path: Path):
        """Load variables from a YAML file."""
        logger.debug(f"Attempting to load variables from: {file_path}")
        try:
            with file_path.open("r", encoding="utf-8") as f:
                content = f.read()
                # Skip vault encrypted files
                if "ANSIBLE_VAULT" in content:
                    logger.warning(f"Skipping vaulted file: {file_path}")
                    return
                CustomLoader = create_custom_yaml_loader()
                data = yaml.load(content, Loader=CustomLoader)
                if isinstance(data, dict):
                    var_count_before = len(self.variables)
                    self.variables.update(data)
                    new_vars = len(self.variables) - var_count_before
                    logger.debug(f"Successfully loaded {new_vars} variables from: {file_path}")
                else:
                    logger.debug(f"No dictionary data found in: {file_path}")
        except Exception as e:
            logger.error(f"Error loading vars from {file_path}: {e}")

    def resolve_string(self, input_string: str) -> Tuple[str, bool]:
        """Attempt to resolve Jinja2 variables in a string."""
        if not isinstance(input_string, str):
            return str(input_string), False

        contains_vars = "{{" in input_string

        def replace_var(match):
            var_name = match.group(1).strip()
            if var_name in self.variables:
                logger.debug(f"Resolved variable {var_name} to: {self.variables[var_name]}")
                return str(self.variables[var_name])
            else:
                self.unresolved_variables.add(var_name)
                logger.debug(f"Could not resolve variable: {var_name}")
                return match.group(0)  # Return original if not found

        resolved_string = re.sub(r"{{\s*(.*?)\s*}}", replace_var, input_string)
        return resolved_string, contains_vars


class PlaybookParser:
    """Parses Ansible playbooks to find command/shell tasks."""

    def __init__(self, variable_manager: VariableManager):
        """Initialize the PlaybookParser."""
        self.variable_manager = variable_manager
        self.results: List[Dict[str, Any]] = []
        logger.debug("PlaybookParser initialized")

    def parse_playbook(self, file_path: Path):
        """Parse a single playbook file."""
        logger.info(f"Parsing playbook: {file_path}")
        try:
            with file_path.open("r", encoding="utf-8") as f:
                content = f.read()
                if "ANSIBLE_VAULT" in content:
                    logger.warning(f"Skipping vaulted playbook: {file_path}")
                    return
                CustomLoader = create_custom_yaml_loader()
                plays = yaml.load(content, Loader=CustomLoader)
                if plays:
                    if isinstance(plays, list):
                        logger.debug(f"Found {len(plays)} plays in: {file_path}")
                        for play_index, play in enumerate(plays):
                            if isinstance(play, dict):
                                logger.debug(f"Processing play {play_index + 1} in: {file_path}")
                                self._process_play(play, file_path)
                    else:
                        logger.debug(f"Single play found in: {file_path}")
                        if isinstance(plays, dict):
                            self._process_play(plays, file_path)
                else:
                    logger.debug(f"No plays found in: {file_path}")
        except Exception as e:
            logger.error(f"Failed to parse playbook {file_path}: {e}")

    def parse_role_tasks(self, file_path: Path):
        """Parse a role tasks file (direct list of tasks)."""
        logger.info(f"Parsing role tasks file: {file_path}")
        try:
            with file_path.open("r", encoding="utf-8") as f:
                content = f.read()
                if "ANSIBLE_VAULT" in content:
                    logger.warning(f"Skipping vaulted role tasks file: {file_path}")
                    return
                CustomLoader = create_custom_yaml_loader()
                tasks = yaml.load(content, Loader=CustomLoader)
                if tasks:
                    if isinstance(tasks, list):
                        logger.debug(f"Found {len(tasks)} tasks in role file: {file_path}")
                        self._process_tasks(tasks, file_path)
                    else:
                        logger.warning(f"Unexpected structure in role tasks file: {file_path}")
                else:
                    logger.debug(f"No tasks found in role file: {file_path}")
        except Exception as e:
            logger.error(f"Failed to parse role tasks file {file_path}: {e}")

    def _process_play(self, play: Dict[str, Any], file_path: Path):
        """Process a single play within a playbook."""
        play_name = play.get("name", "Unnamed Play")
        logger.debug(f"Processing play '{play_name}' in: {file_path}")

        # Process vars_files if present
        if "vars_files" in play:
            logger.debug(f"Found vars_files in play: {play['vars_files']}")
            self._process_vars_files(play["vars_files"], file_path)

        # Process inline vars
        if "vars" in play:
            var_count = len(play["vars"]) if isinstance(play["vars"], dict) else 0
            logger.debug(f"Found {var_count} inline vars in play")
            self.variable_manager.variables.update(play["vars"])

        task_sections_found = []
        for task_key in ["tasks", "pre_tasks", "post_tasks"]:
            if task_key in play:
                task_count = len(play[task_key]) if isinstance(play[task_key], list) else 0
                logger.debug(f"Found {task_count} {task_key} in play")
                task_sections_found.append(f"{task_count} {task_key}")
                self._process_tasks(play[task_key], file_path)

        if task_sections_found:
            logger.debug(f"Processed task sections: {', '.join(task_sections_found)}")

        if "roles" in play:
            logger.debug(f"Found roles in play: {play['roles']}")
            # Simplified role handling: assumes roles are in '<repo>/roles/'
            # A full implementation would need to respect roles_path config.
            pass  # Role task processing will happen when roles are parsed directly

    def _process_tasks(self, tasks: List[Dict[str, Any]], file_path: Path):  # noqa: C901
        """Recursively process a list of tasks."""
        if not tasks:
            return

        logger.debug(f"Processing {len(tasks)} tasks from: {file_path}")
        target_tasks_found = 0

        for task_index, task in enumerate(tasks):
            if not isinstance(task, dict):
                continue

            task_name = task.get("name", f"Task {task_index + 1}")
            logger.debug(f"Processing task: {task_name}")

            # Process task-level vars
            if "vars" in task:
                var_count = len(task["vars"]) if isinstance(task["vars"], dict) else 0
                logger.debug(f"Found {var_count} task-level vars in: {task_name}")
                self.variable_manager.variables.update(task["vars"])

            # Process set_fact tasks
            if "set_fact" in task:
                logger.debug(f"Found set_fact task: {task_name}")
                self._process_set_fact(task["set_fact"])

            # Process register variables (we can't resolve them, but we can track them)
            if "register" in task:
                register_var = task["register"]
                self.variable_manager.unresolved_variables.add(register_var)
                logger.debug(f"Found register variable: {register_var}")

            if "block" in task:
                logger.debug(f"Found block task: {task_name}")
                self._process_tasks(task["block"], file_path)
                if "rescue" in task:
                    logger.debug(f"Found rescue block in: {task_name}")
                    self._process_tasks(task["rescue"], file_path)
                if "always" in task:
                    logger.debug(f"Found always block in: {task_name}")
                    self._process_tasks(task["always"], file_path)
                continue

            for module in ALL_TARGET_MODULES:
                if module in task:
                    logger.debug(f"Found {module} module in task: {task_name}")
                    self._extract_command_info(task, module, file_path)
                    target_tasks_found += 1

        if target_tasks_found > 0:
            logger.info(f"Found {target_tasks_found} target module tasks in: {file_path}")

    def _extract_command_info(self, task: Dict[str, Any], module: str, file_path: Path):
        """Extract information from a command/shell task."""
        raw_command = task[module]
        logger.debug(f"Processing {module} task with raw command type: {type(raw_command)}")

        # Handle different command formats
        if isinstance(raw_command, dict):
            # Handle complex args like cmd: ... chdir: ...
            logger.debug(f"Complex command structure: {list(raw_command.keys())}")
            raw_command = raw_command.get("cmd", raw_command.get("_raw_params", str(raw_command)))

        # Convert to string and log original format
        raw_command = str(raw_command)
        logger.debug(f"Raw command (first 100 chars): {raw_command[:100]}")

        resolved_command, contains_vars = self.variable_manager.resolve_string(raw_command)
        primary_executable = self._get_primary_executable(resolved_command)

        # Normalize module name for display
        display_module = self._normalize_module_name(module)

        result = {
            "Playbook File Path": str(file_path.relative_to(self.variable_manager.repo_path)),
            "Task Name": task.get("name", "N/A"),
            "Module Type": display_module,
            "Full Command": resolved_command.replace("\n", " ").strip(),
            "Primary Executable": primary_executable,
            "Line Number": "N/A",
            "Contains Variables": "Y" if contains_vars else "N",
        }

        logger.debug(f"Extracted command info: '{primary_executable}' from {display_module} module")
        logger.debug(f"Task name: '{task.get('name', 'N/A')}'")
        self.results.append(result)

    def _normalize_module_name(self, module: str) -> str:
        """Normalize module name for consistent display."""
        # Keep FQCN for clarity, but could be simplified if needed
        return module

    def _get_primary_executable(self, command: str) -> str:
        """Extract the primary executable from a command string."""
        if not command or not isinstance(command, str):
            return "N/A"

        # Handle multi-line commands by processing line by line
        lines = command.strip().split("\n")
        logger.debug(f"Processing {len(lines)} command lines")

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                # Skip empty lines and comments
                continue

            # Skip common shell directives that aren't executables
            if line.startswith(("set ", "export ", "cd ", "mkdir -p", "echo ")):
                logger.debug(f"Line {line_num}: Skipping shell directive: {line[:50]}...")
                continue

            # Split by shell operators to find the main command
            command_parts = re.split(r"\s*&&\s*|\s*\|\|\s*|\s*;\s*|\s*\|\s*", line)

            for part in command_parts:
                part = part.strip()
                if part:
                    # Extract the first word as the executable
                    words = part.split()
                    if words:
                        executable = words[0]
                        # Remove common shell prefixes
                        executable = re.sub(r"^(sudo\s+|nohup\s+)", "", executable).strip()
                        if executable and not executable.startswith(("$", "{{", "[")):
                            logger.debug(f"Found primary executable: '{executable}' from line {line_num}: {line[:50]}...")
                            return executable

        # Fallback: try to extract from the first line
        first_line = lines[0].strip() if lines else ""
        if first_line:
            first_word = first_line.split()[0] if first_line.split() else "N/A"
            logger.debug(f"Fallback executable: '{first_word}' from: {command[:50]}...")
            return first_word

        logger.debug(f"Could not extract executable from command: {command[:50]}...")
        return "N/A"

    def _process_vars_files(self, vars_files: List[str], file_path: Path):
        """Process vars_files declarations in plays."""
        base_dir = file_path.parent
        logger.debug(f"Processing {len(vars_files)} vars_files from: {file_path}")

        for vars_file in vars_files:
            # Handle simple string vars_files (no variable resolution for now)
            if isinstance(vars_file, str) and not ("{{" in vars_file):
                vars_file_path = base_dir / vars_file
                logger.debug(f"Checking vars_file path: {vars_file_path}")
                if vars_file_path.exists():
                    self.variable_manager.load_vars_from_file(vars_file_path)
                    logger.debug(f"Loaded vars from vars_files: {vars_file_path}")
                else:
                    logger.warning(f"vars_files not found: {vars_file_path}")
            else:
                logger.debug(f"Skipping vars_file with variables: {vars_file}")

    def _process_set_fact(self, set_fact_data: Dict[str, Any]):
        """Process set_fact task data."""
        if isinstance(set_fact_data, dict):
            logger.debug(f"Processing set_fact with {len(set_fact_data)} variables")
            # Only process simple string values, skip complex expressions
            for key, value in set_fact_data.items():
                if isinstance(value, str) and not ("{{" in value):
                    self.variable_manager.variables[key] = value
                    logger.debug(f"Added set_fact variable: {key} = {value}")
                else:
                    self.variable_manager.unresolved_variables.add(key)
                    logger.debug(f"Found complex set_fact variable: {key}")


class AnsibleAnalyzer:
    """Orchestrates the analysis of an Ansible repository."""

    def __init__(self, repo_path: str):
        """Initialize the AnsibleAnalyzer."""
        self.repo_path = Path(repo_path).resolve()
        logger.info(f"Initializing AnsibleAnalyzer for path: {self.repo_path}")

        if not self.repo_path.is_dir():
            logger.error(f"Repository path not found: {self.repo_path}")
            raise NotADirectoryError(f"Repository path not found: {self.repo_path}")

        logger.info(f"Repository path validated: {self.repo_path}")
        self.variable_manager = VariableManager(self.repo_path)
        self.playbook_parser = PlaybookParser(self.variable_manager)

    def analyze(self):
        """Run the analysis across the repository."""
        logger.info(f"Starting analysis of repository: {self.repo_path}")

        # Log repository structure
        self._log_repository_structure()

        playbook_files = self._find_playbooks()
        logger.info(f"Found {len(playbook_files)} playbook files to analyze")

        if not playbook_files:
            logger.warning("No playbook files found in the repository")

        for pb_file in playbook_files:
            self.playbook_parser.parse_playbook(pb_file)

        # Also parse tasks inside roles directly
        roles_path = self.repo_path / "roles"
        role_task_files = []
        if roles_path.is_dir():
            logger.info(f"Scanning roles directory for task files: {roles_path}")
            for role_file in roles_path.glob("**/tasks/**/*.yml"):
                role_task_files.append(role_file)
            for role_file in roles_path.glob("**/tasks/**/*.yaml"):
                role_task_files.append(role_file)

            logger.info(f"Found {len(role_task_files)} role task files")
            for role_file in role_task_files:
                logger.debug(f"Parsing role task file: {role_file}")
                self.playbook_parser.parse_role_tasks(role_file)

        total_results = len(self.results)
        logger.info(f"Analysis complete. Found {total_results} command/shell tasks.")

        if total_results == 0:
            logger.warning("No target module tasks found. Check if the repository contains Ansible playbooks with shell/command/raw/script modules")

    def _log_repository_structure(self):
        """Log the basic structure of the repository to help with debugging."""
        logger.info("Repository structure analysis:")
        self._check_ansible_paths()
        self._list_yaml_files_in_root()

    def _check_ansible_paths(self):
        """Check for common Ansible directories and files."""
        common_ansible_paths = [
            "playbooks",
            "roles",
            "group_vars",
            "host_vars",
            "inventory",
            "ansible.cfg",
            "site.yml",
            "main.yml",
        ]

        found_paths = []
        for path_name in common_ansible_paths:
            path = self.repo_path / path_name
            if path.exists():
                found_path = self._process_ansible_path(path, path_name)
                found_paths.append(found_path)

        if found_paths:
            logger.info(f"Ansible-related paths found: {', '.join(found_paths)}")
        else:
            logger.warning("No common Ansible directories or files found in repository root")

    def _process_ansible_path(self, path: Path, path_name: str) -> str:
        """Process a single Ansible path and return its description."""
        if path.is_dir():
            try:
                file_count = sum(1 for _ in path.rglob("*") if _.is_file())
                logger.info(f"  Found directory: {path_name}/ with {file_count} files")
                return f"{path_name}/ ({file_count} files)"
            except Exception as e:
                logger.info(f"  Found directory: {path_name}/ (could not count files: {e})")
                return f"{path_name}/"
        else:
            logger.info(f"  Found file: {path_name}")
            return path_name

    def _list_yaml_files_in_root(self):
        """List all YAML files in the root directory."""
        yaml_files_root = []
        try:
            for ext in YAML_EXTENSIONS:
                yaml_files_root.extend([f.name for f in self.repo_path.glob(f"*{ext}") if f.is_file()])
            if yaml_files_root:
                logger.info(f"YAML files in root directory: {', '.join(yaml_files_root)}")
            else:
                logger.info("No YAML files found in root directory")
        except Exception as e:
            logger.error(f"Error scanning root directory for YAML files: {e}")

    def _find_playbooks(self) -> List[Path]:
        """Find all playbook files in the repository."""
        logger.info("Searching for playbook files...")
        playbooks = []

        # Search patterns and their descriptions
        search_patterns = [
            (self.repo_path, "*", "root directory"),
            (self.repo_path / "playbooks", "**/*", "playbooks directory"),
        ]

        for base_path, pattern, description in search_patterns:
            if base_path.exists():
                logger.debug(f"Searching in {description}: {base_path}")
                for ext in YAML_EXTENSIONS:
                    full_pattern = f"{pattern}{ext}"
                    found_files = list(base_path.glob(full_pattern))
                    file_playbooks = [p for p in found_files if p.is_file()]
                    if file_playbooks:
                        logger.info(f"Found {len(file_playbooks)} {ext} files in {description}")
                        for pb in file_playbooks:
                            logger.debug(f"  Found playbook: {pb}")
                    playbooks.extend(file_playbooks)
            else:
                logger.debug(f"Search path does not exist: {base_path}")

        # Remove duplicates while preserving order
        unique_playbooks = []
        seen = set()
        for pb in playbooks:
            if pb not in seen:
                unique_playbooks.append(pb)
                seen.add(pb)

        logger.info(f"Total unique playbook files found: {len(unique_playbooks)}")
        return unique_playbooks

    @property
    def results(self):
        """Get the results of the analysis."""
        return self.playbook_parser.results

    def get_unique_executables_summary(self) -> Dict[str, int]:
        """Get a summary of unique executables and their counts."""
        summary = {}
        for result in self.results:
            exe = result["Primary Executable"]
            summary[exe] = summary.get(exe, 0) + 1
        logger.debug(f"Generated summary for {len(summary)} unique executables")
        return summary

    def write_csv_report(self, output_path: str):
        """Write the analysis results to a CSV file."""
        if not self.results:
            logger.warning("No results to write to CSV.")
            return

        fieldnames = self.results[0].keys()
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.results)
        logger.info(f"CSV report saved to {output_path}")

    def write_json_report(self, output_path: str):
        """Write the analysis results to a JSON file."""
        if not self.results:
            logger.warning("No results to write to JSON.")
            return

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2)
        logger.info(f"JSON report saved to {output_path}")

    def apply_filters(self, include_executables: List[str], exclude_executables: List[str], pattern: str):  # noqa: C901
        """Apply filtering to the results based on executable names."""
        if not include_executables and not exclude_executables and not pattern:
            return

        original_count = len(self.playbook_parser.results)
        logger.info(f"Applying filters to {original_count} results")
        if include_executables:
            logger.info(f"Include executables: {include_executables}")
        if exclude_executables:
            logger.info(f"Exclude executables: {exclude_executables}")
        if pattern:
            logger.info(f"Pattern filter: {pattern}")

        filtered_results = []
        for result in self.playbook_parser.results:
            exe = result["Primary Executable"]
            include = True

            # Apply include filter
            if include_executables:
                if exe not in include_executables:
                    include = False

            # Apply exclude filter
            if exclude_executables:
                if exe in exclude_executables:
                    include = False

            # Apply pattern filter
            if pattern:
                try:
                    if not re.search(pattern, exe):
                        include = False
                except re.error as e:
                    logger.error(f"Invalid regex pattern '{pattern}': {e}")
                    return

            if include:
                filtered_results.append(result)

        # Update the results in the parser
        self.playbook_parser.results = filtered_results
        filtered_count = len(filtered_results)
        logger.info(f"Applied filters. Remaining results: {filtered_count} (filtered out: {original_count - filtered_count})")


@click.command()
@click.option(
    "--repo",
    "repo_path",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Path to the cloned git repository to analyze.",
)
@click.option(
    "--output",
    "output_file",
    required=True,
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    help="Path to the output report file (e.g., report.csv).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    show_default=True,
    help="Format of the output report.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
@click.option(
    "--filter-executable",
    "filter_executables",
    multiple=True,
    help="Filter results to only include specific executables (can be used multiple times).",
)
@click.option(
    "--exclude-executable",
    "exclude_executables",
    multiple=True,
    help="Exclude specific executables from results (can be used multiple times).",
)
@click.option(
    "--filter-pattern",
    help="Filter results using regex pattern matching against executables.",
)
def main(
    repo_path: Path,
    output_file: Path,
    output_format: str,
    verbose: bool,
    filter_executables: tuple,
    exclude_executables: tuple,
    filter_pattern: str,
):
    """Analyzes Ansible playbooks to find shell/command tasks for migration planning."""
    # Setup Logging
    log_level = logging.DEBUG if verbose else logging.INFO
    script_name = Path(__file__).stem
    setup_logging(level=log_level, script_name=script_name)

    console = Console()
    with console.status("[bold green]Analyzing Ansible repository..."):
        try:
            analyzer = AnsibleAnalyzer(str(repo_path))
            analyzer.analyze()
        except Exception as e:
            logger.error(f"An error occurred during analysis: {e}", exc_info=True)
            console.print(f"[bold red]Error: {e}[/bold red]")
            return

    # Apply filters if specified
    if filter_executables or exclude_executables or filter_pattern:
        analyzer.apply_filters(
            include_executables=list(filter_executables),
            exclude_executables=list(exclude_executables),
            pattern=filter_pattern,
        )

    # Display summary table
    summary = analyzer.get_unique_executables_summary()
    table = Table(title="Unique Executables Summary")
    table.add_column("Executable", justify="left", style="cyan")
    table.add_column("Count", justify="right", style="magenta")
    for exe, count in sorted(summary.items(), key=lambda item: item[1], reverse=True):
        table.add_row(exe, str(count))
    console.print(table)

    # Save summary report using utility
    script_base_name = os.path.basename(__file__).replace(".py", "")
    save_summary_report(
        summary_data=summary,
        report_title="Unique Executables Summary",
        script_name=script_base_name,
    )

    # Write detailed report
    if output_format == "csv":
        analyzer.write_csv_report(str(output_file))
    elif output_format == "json":
        analyzer.write_json_report(str(output_file))

    console.print(f"[bold green]Analysis complete. Report saved to {output_file}[/bold green]")


if __name__ == "__main__":
    main()
