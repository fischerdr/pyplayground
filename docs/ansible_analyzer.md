# Ansible Playbook Analyzer Documentation

## Overview

The Ansible Playbook Analyzer scans Ansible repositories to identify shell, command, raw, and script module calls. It supports both short module names and fully qualified collection names (FQCN), helping organizations plan migrations to Ansible Automation Platform (AAP) Execution Environments by cataloging external dependencies and commands.

## Prerequisites

- Python 3.9 or later
- Required dependencies: `click`, `pyyaml`, `rich`
- Access to cloned Ansible git repositories

## Architecture

The analyzer consists of three main components:

### VariableManager

Handles Ansible variable discovery and resolution across the repository structure.

**Responsibilities:**

- Loads variables from standard Ansible locations (`group_vars/`, `host_vars/`, role `vars/`, `defaults/`)
- Processes `vars_files`, `set_fact`, inline `vars`, and register variables  
- Attempts to resolve Jinja2 template variables in commands
- Tracks unresolved variables for manual review

**Limitations:**

- Simplified variable precedence (doesn't fully implement Ansible's complex precedence rules)
- No inventory parsing for group/host-specific variable loading
- Static resolution only (no runtime variable evaluation)

### PlaybookParser

Parses YAML files to identify target module usage and extract command information.

**Responsibilities:**

- Recursively processes playbook structures (`tasks`, `pre_tasks`, `post_tasks`, `blocks`)
- Identifies shell, command, raw, and script module usage (both short names and FQCN)
- Extracts task metadata (name, file path, command content)
- Handles nested task structures (blocks with `rescue`/`always`)
- Processes role task files directly

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
- Applies filtering based on executable names or patterns

## Detailed Description

### File Discovery Process

The analyzer searches for Ansible content in these locations:

1. Root-level YAML files (`*.yml`, `*.yaml`)
2. `playbooks/` directory (recursive)
3. `roles/*/tasks/` directories (recursive)

### Supported Module Types

The analyzer identifies these modules:

**Short names:**
- `shell`
- `command` 
- `raw`
- `script`

**Fully Qualified Collection Names (FQCN):**
- `ansible.builtin.shell`
- `ansible.builtin.command`
- `ansible.builtin.raw`
- `ansible.builtin.script`

### Variable Resolution Strategy

Variables are collected from:

- `group_vars/` directory (all files)
- `host_vars/` directory (all files)  
- `roles/*/vars/` directories
- `roles/*/defaults/` directories
- `vars_files` declarations in plays
- Inline `vars` in plays and tasks
- `set_fact` tasks (simple values only)
- `register` variables (tracked as unresolved)

**Resolution Process:**

1. Load all variable files into a consolidated dictionary
2. For each command string, use regex to find Jinja2 expressions (`{{ variable_name }}`)
3. Replace variables with known values or mark as unresolved
4. Track unresolved variables for reporting

### Command Parsing Logic

For each identified task:

1. Extract raw command string from module parameters
2. Handle both simple strings and complex argument dictionaries (`cmd`, `_raw_params`)
3. Attempt variable resolution using VariableManager
4. Parse primary executable using regex splitting on shell operators
5. Generate structured output record

**Primary Executable Detection:**

- Splits commands on shell operators (`&&`, `||`, `;`, `|`)
- Takes first word of the first command segment
- Removes common prefixes (`sudo`, `nohup`)
- Skips common shell directives (`set`, `export`, `cd`, `mkdir -p`, `echo`)
- Handles basic command structures but may miss complex shell constructs

## Code Examples

### Module Execution (Recommended)

```bash
# Basic analysis with module execution
python -m pyplayground.ansible_analyzer --repo /path/to/ansible/repo --output report.csv --verbose

# Generate JSON format report
python -m pyplayground.ansible_analyzer --repo /path/to/repo --output report.json --format json

# Filter to show only specific executables
python -m pyplayground.ansible_analyzer --repo /path/to/repo --output report.csv \
  --filter-executable curl --filter-executable wget

# Exclude certain executables from results  
python -m pyplayground.ansible_analyzer --repo /path/to/repo --output report.csv \
  --exclude-executable systemctl --exclude-executable echo

# Use regex pattern to filter executables
python -m pyplayground.ansible_analyzer --repo /path/to/repo --output report.csv \
  --filter-pattern "^(curl|wget|git)$"
```

### Direct Script Execution

```bash
# Alternative execution method
python pyplayground/ansible_analyzer.py --repo /path/to/ansible/repo --output report.csv --verbose
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

# Apply filtering
analyzer.apply_filters(
    include_executables=["curl", "wget"],
    exclude_executables=["echo"],
    pattern=r"^(git|ssh).*"
)

# Generate reports
analyzer.write_csv_report("output.csv")
analyzer.write_json_report("output.json")
```

### Output Structure

**CSV Report Columns:**

- **Playbook File Path**: Relative path from repository root
- **Task Name**: Ansible task name or "N/A"
- **Module Type**: shell, command, raw, script, or FQCN equivalent
- **Full Command**: Resolved command string (variables substituted where possible)
- **Primary Executable**: Extracted binary/executable name
- **Line Number**: "N/A" (limitation of current YAML parser)
- **Contains Variables**: "Y" if original command had Jinja2 templates

**Summary Report:**

- Unique executable counts sorted by frequency
- Displayed as Rich table in terminal
- Saved using project's report_utils for consistent formatting

## Alignment with Requirements

### ✅ Implemented Features

**Core Functionality:**

- ✅ Recursive YAML file discovery
- ✅ Standard playbook structure handling
- ✅ Target module identification (shell, command, raw, script + FQCN)
- ✅ Task name capture with fallback
- ✅ Jinja2 template detection and resolution
- ✅ Variable collection from standard locations
- ✅ Binary detection and extraction
- ✅ Structured output generation (CSV, JSON)
- ✅ CLI interface with Click framework
- ✅ Error handling for YAML syntax issues
- ✅ Modular code structure

**Advanced Features:**

- ✅ **Module Execution Support**: Can be run as `python -m pyplayground.ansible_analyzer`
- ✅ **Advanced Variable Sources**: Parse `vars_files`, `set_fact`, register, and inline task vars
- ✅ **Filtering Options**: Filter by specific executables, exclude executables, or use regex patterns
- ✅ **FQCN Support**: Handles both short and fully qualified module names
- ✅ **Vault File Handling**: Gracefully skips encrypted files with warnings
- ✅ **Rich Terminal Output**: Uses Rich library for enhanced console display
- ✅ **Comprehensive Logging**: Detailed logging with configurable levels

### ⚠️ Partial Implementation

- ⚠️ **Line Numbers**: PyYAML doesn't preserve line numbers well (marked as "N/A")
- ⚠️ **Complex Variable Resolution**: Simplified precedence rules vs full Ansible logic
- ⚠️ **Binary Normalization**: Basic executable extraction vs advanced path/version normalization

### ❌ Missing Features

- ❌ **ruamel.yaml**: Uses PyYAML instead (affects line number preservation)
- ❌ **Advanced Binary Normalization**: No path stripping or version collapsing
- ❌ **Confidence Scoring**: No ambiguity detection for binary identification
- ❌ **Multiple Repository Support**: Single repo only
- ❌ **Inventory File Processing**: No inventory parsing

## Common Issues

### YAML Parsing Errors

The script continues processing when individual files fail, logging errors for manual review.

### Vault File Handling

Encrypted files are automatically detected and skipped with appropriate warnings.

### Variable Resolution Limitations

Complex Ansible variable precedence and runtime evaluation are not fully supported. The script provides partial resolution where possible.

### Performance Considerations

Large repositories with many files may take significant time to process. The script processes files sequentially without optimization for parallel processing.

### Module Execution Path Issues

**Fixed**: Recent updates to the logging utilities ensure that logs are created in the correct project-level `logs/` directory when running as a module (`python -m pyplayground.ansible_analyzer`).

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
8. **Confidence Scoring**: Add ambiguity detection for executable identification
