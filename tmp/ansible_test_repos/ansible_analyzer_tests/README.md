# Ansible Analyzer Test Suite

This directory contains comprehensive test files for the `ansible_analyzer.py` script. These tests cover various Ansible patterns and complexity levels.

## Test Files Overview

### 1. `basic_fqcn_test.yml`

Tests basic FQCN (Fully Qualified Collection Name) detection:

- `ansible.builtin.shell`
- `ansible.builtin.command`
- `ansible.builtin.raw`
- `ansible.builtin.script`
- Mixed with traditional short names (`shell`, `command`, etc.)
- Multi-line commands with `set -o pipefail`

### 2. `complex_parameters_test.yml`

Tests complex task parameters:

- `environment:` variables
- `register:` variables
- `failed_when:` conditions
- `changed_when:` conditions
- `ignore_errors:` flags
- Debug tasks (should be ignored)

### 3. `advanced_jinja_test.yml`

Tests advanced Jinja2 expressions and complex scenarios:

- HashiCorp Vault lookups: `{{ lookup('hashi_vault', ...) }}`
- Complex nested variable interpolation
- JSONPath expressions for Kubernetes
- Register variable references: `{{ cluster_display_name.stdout_lines[0] }}`
- Multi-level environment variables
- Unnamed tasks (no `name:` field)

### 4. `variable_resolution_test.yml`

Tests comprehensive variable resolution from multiple sources:

- `vars_files:` variables
- Inline `vars:` variables  
- `set_fact:` variables
- Task-level `vars:`
- `register:` variables (runtime, should remain unresolved)
- Mixed complexity levels

## Variable Sources

### `group_vars/all.yml`

Global variables available to all hosts:

- `app_name: "resolved_app"`
- `database_host: "db.example.com"`
- `log_level: "info"`

### `vars/main.yml`

Variables loaded via `vars_files`:

- `service_name: "nginx"`
- `port: 80`
- `config_path: "/etc/nginx/nginx.conf"`

### `roles/test_role/tasks/main.yml`

Role-specific tasks for testing role detection:

- Shell task with `grep` command
- Command task with `systemctl`
- Uses variables from group_vars

## Expected Results

When running `ansible_analyzer.py` on this test repository, you should expect:

### Unique Executables Found

- `/opt/tools/oc` - OpenShift CLI
- `kubectl` - Kubernetes CLI
- `curl` - HTTP client
- `grep` - Text search
- `systemctl` - System service control
- `chown` - File ownership
- `mysqldump` - Database export
- `echo` - Text output
- `uname` - System info
- `/usr/bin/docker` - Container runtime
- `ocm` - OpenShift Cluster Manager
- `/opt/tools/openshift-install` - OpenShift installer
- `ls` - Directory listing
- Various script paths

### Variable Resolution

- Simple variables should be resolved
- Complex lookups should remain as-is
- Register variables should remain unresolved
- Nested dictionary access should be partially resolved

## Usage

```bash
# Test individual files
python pyplayground/ansible_analyzer.py --repo tmp/ansible_analyzer_tests --output results.csv --verbose

# Test specific patterns
python pyplayground/ansible_analyzer.py --repo tmp/ansible_analyzer_tests --output results.csv --filter-executable "oc" --verbose

# Generate JSON output
python pyplayground/ansible_analyzer.py --repo tmp/ansible_analyzer_tests --output results.json --format json --verbose
```

## Notes

- These files are preserved for reusability
- Each test focuses on different aspects of Ansible complexity
- The role tasks test proper role file detection
- Variable resolution tests cover the full Ansible variable precedence hierarchy
