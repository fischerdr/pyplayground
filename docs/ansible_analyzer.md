# Ansible Playbook Analyzer Documentation

## Overview

The Ansible Playbook Analyzer is a Python script that scans Ansible repositories to identify and extract shell, command, raw, and script module calls. It helps organizations plan migrations to Ansible Automation Platform (AAP) Execution Environments by cataloging external dependencies and commands used across playbooks and roles.

## Prerequisites

- Python 3.9 or later
- Required dependencies: `click`, `yaml`, `rich`
- Access to cloned Ansible git repositories

## Architecture

The analyzer consists of three main components:

### VariableManager

Handles Ansible variable discovery and resolution across the repository structure.

**Responsibilities:**

- Loads variables from standard Ansible locations (group_vars/, host_vars/, role vars/, defaults/)
- Attempts to resolve Jinja2 template variables in commands
- Tracks unresolved variables for manual review

**Limitations:**

- Simplified variable precedence (doesn't fully implement Ansible's complex precedence rules)
- No inventory parsing for group/host-specific variable loading
- Static resolution only (no runtime variable evaluation)

### PlaybookParser

Parses YAML files to identify target module usage and extract command information.

**Responsibilities:**

- Recursively processes playbook structures (tasks, pre_tasks, post_tasks, blocks)
- Identifies shell, command, raw, and script module usage
- Extracts task metadata (name, file path, command content)
- Handles nested task structures (blocks with rescue/always)

**Current Implementation:**

- Uses PyYAML with custom loader (borrowed from password_finder utility)
- Gracefully handles Ansible Vault encrypted files (skips with warning)
- Limited line number tracking due to PyYAML limitations

### AnsibleAnalyzer

Orchestrates the analysis process and manages output generation.

**Responsibilities:**

- Coordinates file discovery across repository structure
- Manages the analysis workflow
- Generates summary statistics and detailed reports
- Provides multiple output formats (CSV, JSON)

## Detailed Description

### File Discovery Process

The analyzer searches for Ansible content in these locations:

1. Root-level YAML files (*.yml,*.yaml)
2. `playbooks/` directory (recursive)
3. `roles/*/tasks/` directories (recursive)

### Variable Resolution Strategy

Variables are collected from:

- `group_vars/` directory (all files)
- `host_vars/` directory (all files)  
- `roles/*/vars/` directories
- `roles/*/defaults/` directories

**Resolution Process:**

1. Load all variable files into a consolidated dictionary
2. For each command string, use regex to find Jinja2 expressions (`{{ variable_name }}`)
3. Replace variables with known values or mark as unresolved
4. Track unresolved variables for reporting

### Command Parsing Logic

For each identified task:

1. Extract raw command string from module parameters
2. Handle both simple strings and complex argument dictionaries
3. Attempt variable resolution using VariableManager
4. Parse primary executable using regex splitting on shell operators
5. Generate structured output record

**Primary Executable Detection:**

- Splits commands on shell operators (`&&`, `||`, `;`, `|`)
- Takes first word of the first command segment
- Handles basic command structures but may miss complex shell constructs

## Code Examples

### Basic Usage

```bash
# Analyze repository and generate CSV report
python ansible_analyzer.py --repo /path/to/ansible/repo --output report.csv --verbose

# Generate JSON format report
python ansible_analyzer.py --repo /path/to/repo --output report.json --format json

# Filter to show only specific executables
python ansible_analyzer.py --repo /path/to/repo --output report.csv --filter-executable curl --filter-executable wget

# Exclude certain executables from results
python ansible_analyzer.py --repo /path/to/repo --output report.csv --exclude-executable systemctl --exclude-executable echo

# Use regex pattern to filter executables
python ansible_analyzer.py --repo /path/to/repo --output report.csv --filter-pattern "^(curl|wget|git)$"
```

### Programmatic Usage

```python
from pyplayground.ansible_analyzer import AnsibleAnalyzer

# Initialize analyzer
analyzer = AnsibleAnalyzer("/path/to/ansible/repo")

# Run analysis
analyzer.analyze()

# Get results
results = analyzer.results
summary = analyzer.get_unique_executables_summary()

# Generate reports
analyzer.write_csv_report("output.csv")
analyzer.write_json_report("output.json")
```

### Output Structure

**CSV Report Columns:**

- Playbook File Path: Relative path from repository root
- Task Name: Ansible task name or "N/A"
- Module Type: shell, command, raw, or script
- Full Command: Resolved command string (variables substituted where possible)
- Primary Executable: Extracted binary/executable name
- Line Number: "N/A" (limitation of current YAML parser)
- Contains Variables: "Y" if original command had Jinja2 templates

**Summary Report:**

- Unique executable counts sorted by frequency
- Displayed as Rich table in terminal
- Saved using project's report_utils for consistent formatting

## Alignment with Requirements

### ✅ Implemented Features

**From prompttoscancmdshellansible1.md:**

- ✅ Recursive YAML file discovery
- ✅ Standard playbook structure handling
- ✅ Target module identification (shell, command, raw, script)
- ✅ Task name capture with fallback
- ✅ Jinja2 template detection
- ✅ Variable collection from standard locations
- ✅ Static variable resolution
- ✅ Binary detection and extraction
- ✅ Structured output generation
- ✅ CLI interface with argparse-like functionality (Click)
- ✅ Error handling for YAML syntax issues
- ✅ Modular code structure

**From prompttoscancmdshellansible2.md:**

- ✅ Git repository scanning
- ✅ Comprehensive directory structure support
- ✅ Variable resolution from multiple sources
- ✅ Command parsing with variable handling
- ✅ CSV report generation
- ✅ Summary statistics
- ✅ Verbose logging
- ✅ Vault file handling
- ✅ Graceful error handling
- ✅ **Advanced Variable Sources**: Parse vars_files, set_fact, register, and inline task vars
- ✅ **Filtering Options**: Filter by specific executables, exclude executables, or use regex patterns

### ⚠️ Partial Implementation

- ⚠️ **Line Numbers**: PyYAML doesn't preserve line numbers well (marked as "N/A")
- ⚠️ **Complex Variable Resolution**: Simplified precedence rules vs full Ansible logic
- ⚠️ **Binary Normalization**: Basic executable extraction vs advanced path/version normalization

### ❌ Missing Features

**From prompttoscancmdshellansible1.md:**

- ❌ **ruamel.yaml**: Uses PyYAML instead (affects line number preservation)
- ❌ **Advanced Binary Normalization**: No path stripping or version collapsing
- ❌ **Confidence Scoring**: No ambiguity detection for binary identification
- ❌ **binaries.txt Output**: Only generates JSON/CSV, not flat text file

**From prompttoscancmdshellansible2.md:**

- ❌ **Multiple Repository Support**: Single repo only
- ❌ **Inventory File Processing**: No inventory parsing
- ❌ **Variable Export**: No separate variable export functionality

## Common Issues

### YAML Parsing Errors

The script continues processing when individual files fail, logging errors for manual review.

### Vault File Handling

Encrypted files are automatically detected and skipped with appropriate warnings.

### Variable Resolution Limitations

Complex Ansible variable precedence and runtime evaluation are not fully supported. The script provides partial resolution where possible.

### Performance Considerations

Large repositories with many files may take significant time to process. The script processes files sequentially without optimization for parallel processing.

## Related Documentation

- [Project Organization Guide](project_organization.md) - Understanding the project structure
- [Password Finder Utility](../pyplayground/utils/password_finder.py) - Custom YAML loader implementation
- [Report Utils](../pyplayground/utils/report_utils.py) - Report generation utilities
- [Logging Utils](../pyplayground/utils/logging_utils.py) - Logging configuration

## Future Enhancements

1. **Enhanced Line Number Support**: Implement ruamel.yaml for better position tracking
2. **Advanced Variable Resolution**: Full Ansible precedence rule implementation
3. **Binary Normalization**: Path stripping and version collapsing
4. **Multi-Repository Support**: Batch processing of multiple repositories
5. **Performance Optimization**: Parallel file processing
6. **Extended Output Formats**: Additional report formats and filtering options
7. **Inventory Integration**: Parse inventory files for complete variable context
