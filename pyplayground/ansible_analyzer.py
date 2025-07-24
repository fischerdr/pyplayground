#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ansible Playbook Analyzer.

This script analyzes Ansible playbooks from a given repository to identify
and extract shell, command, raw, and script module calls. It helps in
planning migrations to Ansible Automation Platform (AAP) Execution Environments
by identifying external dependencies and commands.
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
        self.load_variables()

    def load_variables(self):  # noqa: C901
        """Load variables from common Ansible locations."""
        # This is a simplified implementation. A real one would need inventory parsing
        # to understand groups and hosts to load files in the correct precedence.
        # For now, we load all vars files we find.
        for var_dir in TOP_LEVEL_VARS_DIRS:
            dir_path = self.repo_path / var_dir
            if dir_path.is_dir():
                for var_file in dir_path.glob("**/*"):
                    if var_file.suffix in YAML_EXTENSIONS and var_file.is_file():
                        self.load_vars_from_file(var_file)

        roles_path = self.repo_path / "roles"
        if roles_path.is_dir():
            for role_dir in roles_path.iterdir():
                if role_dir.is_dir():
                    for var_dir_name in ROLE_VARS_DIRS:
                        var_dir = role_dir / var_dir_name
                        if var_dir.is_dir():
                            for var_file in var_dir.glob("**/*"):
                                if var_file.suffix in YAML_EXTENSIONS and var_file.is_file():
                                    self.load_vars_from_file(var_file)

    def load_vars_from_file(self, file_path: Path):
        """Load variables from a YAML file."""
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
                    self.variables.update(data)
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
                return str(self.variables[var_name])
            else:
                self.unresolved_variables.add(var_name)
                return match.group(0)  # Return original if not found

        resolved_string = re.sub(r"{{\s*(.*?)\s*}}", replace_var, input_string)
        return resolved_string, contains_vars


class PlaybookParser:
    """Parses Ansible playbooks to find command/shell tasks."""

    def __init__(self, variable_manager: VariableManager):
        """Initialize the PlaybookParser."""
        self.variable_manager = variable_manager
        self.results: List[Dict[str, Any]] = []

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
                    for play in plays:
                        if isinstance(play, dict):
                            self._process_play(play, file_path)
        except Exception as e:
            logger.error(f"Failed to parse playbook {file_path}: {e}")

    def _process_play(self, play: Dict[str, Any], file_path: Path):
        """Process a single play within a playbook."""
        # Process vars_files if present
        if "vars_files" in play:
            self._process_vars_files(play["vars_files"], file_path)

        # Process inline vars
        if "vars" in play:
            self.variable_manager.variables.update(play["vars"])

        for task_key in ["tasks", "pre_tasks", "post_tasks"]:
            if task_key in play:
                self._process_tasks(play[task_key], file_path)

        if "roles" in play:
            # Simplified role handling: assumes roles are in '<repo>/roles/'
            # A full implementation would need to respect roles_path config.
            pass  # Role task processing will happen when roles are parsed directly

    def _process_tasks(self, tasks: List[Dict[str, Any]], file_path: Path):  # noqa: C901
        """Recursively process a list of tasks."""
        if not tasks:
            return
        for task in tasks:
            if not isinstance(task, dict):
                continue

            # Process task-level vars
            if "vars" in task:
                self.variable_manager.variables.update(task["vars"])

            # Process set_fact tasks
            if "set_fact" in task:
                self._process_set_fact(task["set_fact"])

            # Process register variables (we can't resolve them, but we can track them)
            if "register" in task:
                register_var = task["register"]
                self.variable_manager.unresolved_variables.add(register_var)
                logger.debug(f"Found register variable: {register_var}")

            if "block" in task:
                self._process_tasks(task["block"], file_path)
                if "rescue" in task:
                    self._process_tasks(task["rescue"], file_path)
                if "always" in task:
                    self._process_tasks(task["always"], file_path)
                continue

            for module in TARGET_MODULES:
                if module in task:
                    self._extract_command_info(task, module, file_path)

    def _extract_command_info(self, task: Dict[str, Any], module: str, file_path: Path):
        """Extract information from a command/shell task."""
        raw_command = task[module]
        if isinstance(raw_command, dict):
            # Handle complex args like cmd: ... chdir: ...
            raw_command = raw_command.get("cmd", raw_command)

        resolved_command, contains_vars = self.variable_manager.resolve_string(raw_command)
        primary_executable = self._get_primary_executable(resolved_command)

        # PyYAML doesn't preserve line numbers well. This is a limitation.
        # We can only provide the file path.
        self.results.append(
            {
                "Playbook File Path": str(file_path.relative_to(self.variable_manager.repo_path)),
                "Task Name": task.get("name", "N/A"),
                "Module Type": module,
                "Full Command": resolved_command.replace("\n", " "),
                "Primary Executable": primary_executable,
                "Line Number": "N/A",
                "Contains Variables": "Y" if contains_vars else "N",
            }
        )

    def _get_primary_executable(self, command: str) -> str:
        """Extract the primary executable from a command string."""
        if not command or not isinstance(command, str):
            return "N/A"
        # Simplistic parser: split by pipe/semicolon/etc. and take first word of first part.
        command_parts = re.split(r"\s*&&\s*|\s*\|\|\s*|\s*;\s*|\s*\|\s*", command)
        first_command = command_parts[0].strip()
        return first_command.split()[0]

    def _process_vars_files(self, vars_files: List[str], file_path: Path):
        """Process vars_files declarations in plays."""
        base_dir = file_path.parent
        for vars_file in vars_files:
            # Handle simple string vars_files (no variable resolution for now)
            if isinstance(vars_file, str) and not ("{{" in vars_file):
                vars_file_path = base_dir / vars_file
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
        if not self.repo_path.is_dir():
            raise NotADirectoryError(f"Repository path not found: {self.repo_path}")

        self.variable_manager = VariableManager(self.repo_path)
        self.playbook_parser = PlaybookParser(self.variable_manager)

    def analyze(self):
        """Run the analysis across the repository."""
        logger.info(f"Starting analysis of repository: {self.repo_path}")
        playbook_files = self._find_playbooks()
        for pb_file in playbook_files:
            self.playbook_parser.parse_playbook(pb_file)

        # Also parse tasks inside roles directly
        roles_path = self.repo_path / "roles"
        if roles_path.is_dir():
            for role_file in roles_path.glob("**/tasks/**/*.yml"):
                self.playbook_parser.parse_playbook(role_file)
            for role_file in roles_path.glob("**/tasks/**/*.yaml"):
                self.playbook_parser.parse_playbook(role_file)

        logger.info(f"Analysis complete. Found {len(self.results)} command/shell tasks.")

    def _find_playbooks(self) -> List[Path]:
        """Find all playbook files in the repository."""
        playbooks = []
        for ext in YAML_EXTENSIONS:
            # Look in root and a 'playbooks' directory
            playbooks.extend(self.repo_path.glob(f"*{ext}"))
            playbooks.extend((self.repo_path / "playbooks").glob(f"**/*{ext}"))
        return [p for p in playbooks if p.is_file()]

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

    def apply_filters(  # noqa: C901
        self, include_executables: List[str], exclude_executables: List[str], pattern: str
    ):
        """Apply filtering to the results based on executable names."""
        if not include_executables and not exclude_executables and not pattern:
            return

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
        logger.info(f"Applied filters. Remaining results: {len(filtered_results)}")


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
