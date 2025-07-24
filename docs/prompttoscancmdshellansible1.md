# 🧩 Prompt: Ansible Playbook Shell Command Audit Script

## 🎯 Objective

Create a Python script that scans Ansible playbooks to extract and resolve shell or command calls. The goal is to detect all external applications (binaries) invoked via shell or command tasks, including those using variables, to support migration to Ansible Automation Platform (AAP) Execution Environments (EEs).

## 🔧 Functional Requirements

1. Playbook & Role Parsing

    Recursively search a given directory for .yml and .yaml files.

    Parse each file as YAML using ruamel.yaml, preserving structure, comments, and line numbers.

    Detect and handle standard playbook structures including:

        Playbooks

        Roles (tasks/, handlers/, defaults/, vars/)

        Group/host variables (group_vars/, host_vars/)

2. Task Filtering

    Identify tasks using any of the following module formats:

        ansible.builtin.shell

        ansible.builtin.command

        Unqualified shell

        Unqualified command

    For each task:

        Capture the task name (or fallback to a generated label from file name + line number).

        Capture the raw command string.

        Detect and mark Jinja2 templating expressions ({{ var_name }}).

3. Variable Resolution

    Collect and merge variable definitions from:

        Task-level vars

        Play-level vars

        defaults/ and vars/ in roles

        group_vars/ and host_vars/ directories

    Resolve variables statically where possible:

        Simple string substitutions should be resolved.

        If a variable is dynamic, undefined, or computed at runtime, mark it as "unresolved".

    Provide partial substitution if some variables resolve and others don’t.

4. Binary Detection and Normalization

    For each resolved command:

        Parse and extract the primary binary (first word or executable in the command).

        Normalize binary names:

            Strip full paths (/usr/bin/python3 → python3)

            Collapse versions to generic identifiers (python3.11 → python3)

            Detect aliases or symlinks when possible

    Mark detection confidence where ambiguity exists.

5. Output Format

Generate a structured JSON report in the following format:

    ```json
    {
    "playbook_file.yml": {
        "tasks": [
        {
            "name": "Install curl tool",
            "module": "shell",
            "raw_command": "curl -o tool.sh https://example.com",
            "resolved_command": "curl -o tool.sh https://example.com",
            "detected_binary": "curl",
            "resolved": true
        },
        {
            "name": "Run dynamic app",
            "module": "command",
            "raw_command": "{{ app_runner }} --check",
            "resolved_command": "unresolved",
            "detected_binary": "unresolved",
            "resolved": false
        }
        ]
    }
    }
    ```

Also output a binaries.txt file listing all unique detected binaries, one per line.

## 📦 Implementation Details

    Use argparse for CLI inputs:

        --source-dir (required): Directory of playbooks

        --output-json (required): Path to JSON report

        --binaries-file (optional): Path to flat binary summary

        --verbose (optional): Enable debug logging

    Use Python logging module for warnings and traceability.

    Modular structure:

        parser.py for file scanning and parsing

        resolver.py for variable resolution

        analyzer.py for binary detection

        main.py or __main__.py as entrypoint

    Gracefully handle YAML syntax errors or missing files.

## 🧪 Purpose

This tool enables a structured migration from legacy Ansible content to containerized automation by:

    Enumerating shell-based tooling dependencies

    Highlighting unresolved or dynamic command usage

    Supporting EE build planning by surfacing runtime binary requirements
