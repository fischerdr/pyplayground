# Prompt for Ansible Playbook Shell/Command Analysis Script

Create a Python script that analyzes Ansible playbooks from cloned git repositories to identify and extract shell and command module calls for AAP Execution Environment migration planning. The script should:

## Core Requirements

1. **Git Repository and File Scanning:**
   - Recursively scan cloned git repositories for Ansible content
   - Parse YAML playbook files (.yml, .yaml)
   - Scan Ansible directory structures (playbooks/, roles/, group_vars/, host_vars/)
   - Handle both single playbooks and complex role structures
   - Identify and process Ansible inventory files

2. **Identify Target Modules:**
   - `shell` module calls
   - `command` module calls  
   - `raw` module calls
   - `script` module calls (if running shell scripts)

3. **Variable Resolution and Analysis:**
   - Parse and extract variables from:
     - group_vars/ directories (all.yml, specific groups)
     - host_vars/ directories
     - vars/ directories in roles
     - defaults/ directories in roles
     - Inline vars: sections in playbooks
     - vars_files: includes
     - set_fact: tasks
     - register: variable assignments
   - Attempt to resolve variable values in commands where possible
   - Track unresolved variables for manual review
   - Handle Jinja2 templating syntax and filters
   - The actual command/executable being called
   - Full command with arguments
   - Associated task name/description
   - File path where found
   - Line number in file

4. **Command Parsing Logic:**
   - Extract the primary executable/binary name from commands
   - Handle complex commands with pipes, redirects, and multiple commands
   - Parse commands that use variables ({{ variable_name }})
   - Identify system binaries vs custom scripts/applications

5. **Output Format:**
   - Generate a comprehensive CSV report with columns:
     - Playbook File Path
     - Task Name
     - Module Type (shell/command/raw)
     - Full Command
     - Primary Executable
     - Line Number
     - Contains Variables (Y/N)
   - Create a summary report of unique executables found
   - Optionally generate a JSON output for further processing

6. **Additional Features:**
   - Command-line argument support for input directory/file specification
   - Verbose logging option
   - Ability to filter by specific executables or patterns
   - Handle encrypted Ansible Vault files gracefully (skip with warning)
   - Support for both inline commands and multi-line commands

7. **Error Handling:**
   - Graceful handling of malformed YAML
   - Continue processing if individual files fail
   - Provide meaningful error messages and warnings

## Example Usage

```bash
# Scan single git repository
python ansible_analyzer.py --repo /path/to/cloned/repo --output analysis_report.csv --verbose

# Scan multiple repositories
python ansible_analyzer.py --repos /path/to/repo1 /path/to/repo2 /path/to/repo3 --output migration_analysis.csv

# Include variable resolution details
python ansible_analyzer.py --repo /path/to/repo --output report.csv --resolve-vars --export-vars vars_export.json
```

The script should help identify all external dependencies and commands across multiple git repositories that need to be available in the new AAP Execution Environment container image. It should provide comprehensive variable analysis to ensure accurate command resolution and complete dependency mapping for the migration.
