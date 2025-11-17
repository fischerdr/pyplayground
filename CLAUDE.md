# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PyPlayground is a Python-based mock and testing environment for infrastructure components including Kubernetes, VMware, HashiCorp Vault APIs, Portworx storage, PX-Backup, and a D&D simulator. It serves as a development playground for simulating and testing these systems.

## Project Configuration

**CRITICAL**: This project uses `pyproject.toml` as the single source of truth for all configuration:

- **Dependencies**: Defined in `[project.dependencies]` and `[project.optional-dependencies].dev`
- **Tool configurations**: Black, isort, pytest, mypy, flake8 settings all in `pyproject.toml`
- **Package metadata**: Version, authors, description, Python version requirements
- **DO NOT** manually edit `requirements.txt` or `requirements-dev.txt` - these are generated from `pyproject.toml`
- **ALWAYS** check `pyproject.toml` for configuration before adding new config files

## Key Architecture

### Code Organization

The project uses a **flat package structure** with the main code in `pyplayground/` (NOT `src/`):

- `pyplayground/` - Main package containing all Python modules and scripts
  - `utils/` - Centralized utility functions (config, k8s, vault, logging, migration, ansible)
  - `k8s/` - Kubernetes-related utilities and scripts
  - `vault/` - HashiCorp Vault integration scripts
  - `pxclients/` - Portworx client utilities and PX-Backup tools
  - `awxtower/` - AWX/Ansible Tower integration
  - `dndfightsim/` - D&D combat simulator (fun project)
  - `pxsecretmigrate/` - Standalone secret migration tool
  - Standalone scripts at root level (e.g., `ansible_analyzer.py`, `cert_viewer.py`, `inventory_search.py`)

### Shared Utilities (CRITICAL)

**MANDATORY CODE REUSE POLICY**: All reusable code MUST be placed in utility libraries. NEVER duplicate code across scripts.

The `pyplayground/utils/` module provides common functionality used across the codebase:

- **Config utilities** (`config_utils.py`): Environment variables, JSON config loading
- **Kubernetes utilities** (`k8s_utils.py`): K8s client, kubeconfig from Vault, node/machine operations
- **Vault utilities** (`vault_utils.py`): Vault client, secret collection, path validation
- **Logging utilities** (`logging_utils.py`): Structured logging setup
- **Migration utilities** (`migration_utils.py`): Secret name normalization, PVC validation
- **Ansible Tower utilities** (`ansible_tower_utils.py`): AWX/Tower client operations

**When writing code:**

1. **BEFORE writing any function**: Check if similar functionality exists in `pyplayground/utils/`
2. **IF functionality is used in 2+ places**: Extract it to the appropriate utils module
3. **IF creating new utility**: Add it to the correct utils module based on its purpose
4. **ALWAYS import from utils**: Use `from pyplayground.utils import function_name`
5. **NEVER copy-paste code**: Refactor to use shared utilities instead

**Example workflow:**

```python
# BAD - Duplicating code in multiple scripts
# script1.py
def create_k8s_client():
    # ... k8s client code ...

# script2.py
def create_k8s_client():
    # ... same k8s client code ...

# GOOD - Using shared utility
# script1.py and script2.py
from pyplayground.utils import get_k8s_client

client = get_k8s_client()
```

## Development Commands

**IMPORTANT**: All Python commands must be run with the virtual environment activated or using `.venv/bin/` prefix.

### Environment Setup

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install development dependencies (includes production deps)
.venv/bin/pip install -r requirements-dev.txt

# Or use pip-sync for exact dependency matching
.venv/bin/pip install pip-tools
.venv/bin/pip-sync requirements-dev.txt
```

### Testing

```bash
# Ensure virtual environment is activated
source .venv/bin/activate

# Run all tests with coverage
.venv/bin/pytest

# Run specific test file
.venv/bin/pytest tests/test_specific.py

# Run with verbose output
.venv/bin/pytest -v

# Run with coverage report
.venv/bin/pytest --cov=pyplayground --cov-report=html
```

### Code Quality

**NOTE**: All tool configurations (black, isort, pytest, mypy) are defined in `pyproject.toml`. Check there for settings like line length, target Python version, etc.

```bash
# Ensure virtual environment is activated
source .venv/bin/activate

# Format code with black (settings in pyproject.toml: line-length=180)
.venv/bin/black pyplayground/

# Sort imports with isort (settings in pyproject.toml)
.venv/bin/isort pyplayground/

# Lint with flake8 (settings in .flake8 - consider migrating to pyproject.toml)
.venv/bin/flake8 pyplayground/

# Type checking with mypy (settings in mypy.ini - consider migrating to pyproject.toml)
.venv/bin/mypy pyplayground/

# Run pre-commit hooks manually (settings in .pre-commit-config.yaml)
.venv/bin/pre-commit run --all-files
```

### Dependency Management

**CRITICAL**: `pyproject.toml` is the ONLY place to define dependencies. The `requirements.txt` and `requirements-dev.txt` files are **auto-generated** - NEVER edit them manually.

```bash
# Ensure virtual environment is activated
source .venv/bin/activate

# 1. ALWAYS edit pyproject.toml to add/remove/update dependencies
#    - Production deps: [project.dependencies]
#    - Development deps: [project.optional-dependencies].dev

# 2. Regenerate requirements files after editing pyproject.toml
.venv/bin/pip-compile --resolver=backtracking -o requirements.txt pyproject.toml
.venv/bin/pip-compile --resolver=backtracking --extra dev -o requirements-dev.txt pyproject.toml

# 3. ALWAYS commit all three files together:
#    - pyproject.toml (source of truth)
#    - requirements.txt (generated)
#    - requirements-dev.txt (generated)
```

## Code Quality Requirements (CRITICAL)

**ALL code must pass linting before being committed:**

### Python Code Standards

- **Python version**: 3.9-3.14
- **Line length**: 180 characters maximum
- **CLI frameworks**: Click or Typer for command-line interfaces
- **Type hints**: Required for all functions and classes
- **Docstrings**: Required for all modules, classes, and functions (Google style)
- **Logging**: Use `pyplayground/utils/logging_utils.py` for structured logging

**Required to pass:**

- **black**: Code formatting (enforced via pre-commit)
- **isort**: Import sorting (enforced via pre-commit)
- **flake8**: Linting with docstring checks
- **mypy**: Type checking (strict mode enabled)

All Python code MUST pass black, isort, and flake8 checks before committing.

### Ansible Standards

**Required to pass:**

- **ansible-lint**: All Ansible playbooks and roles must pass ansible-lint

```bash
# Run ansible-lint on playbooks
ansible-lint ansible/

# Run on specific playbook
ansible-lint ansible/playbooks/example.yml
```

### Shell Script Standards

When working with shell scripts in `bin/scripts/`:

- Use double quotes for variable expansion
- Define functions at the top of the file before usage
- Define variables before use
- Follow proper error handling with `set -e` and cleanup traps

**Required to pass:**

- **shellcheck**: All shell scripts must pass shellcheck

```bash
# Run shellcheck on shell scripts
shellcheck bin/scripts/*.sh

# Run on specific script
shellcheck bin/scripts/example.sh
```

## Container Standards

When creating Dockerfiles, limit base images to:

- CentOS/CentOS Stream
- Fedora/Fedora Stream
- Alpine

## Common Patterns

### Code Reuse (MANDATORY)

**BEFORE writing any new function, CHECK if it already exists in utils:**

```python
# Step 1: Check existing utilities
from pyplayground.utils import (
    # Config
    get_env_var, load_env_file, load_json_config, save_json_config,
    # K8s
    get_k8s_client, get_kubeconfig_from_vault, get_configmap_data,
    # Vault
    create_vault_client, get_secret, collect_secrets,
    # Logging
    get_logger, setup_logging,
    # Migration
    normalize_secret_name, parse_export_data,
    # Ansible
    get_awx_or_tower_client, get_resource, update_resource,
)

# Step 2: If functionality doesn't exist and is reusable, add it to utils
# Step 3: NEVER duplicate code across scripts
```

### Importing Utilities

```python
# ALWAYS import from centralized utils
from pyplayground.utils import (
    get_logger,
    get_k8s_client,
    create_vault_client,
    get_env_var,
)
```

### Logging Setup

```python
from pyplayground.utils import get_logger, setup_logging

# Initialize logging
setup_logging()
logger = get_logger(__name__)

# Use structured logging
logger.info("Operation started", extra={"operation": "example", "count": 5})
```

### Configuration Management

Configuration files live in `config/`, logs in `logs/`, and temporary files in `tmp/`. The `tmp/` directory contents should always be safe to delete.

## Documentation

- Main docs in `docs/` directory covering setup, configuration, usage guides
- Keep README.md synchronized with project changes
- Update documentation when making code changes
- Document thought process and architecture decisions in `docs/`

## Important Notes

- **MANDATORY: No code duplication**: ALL reusable code MUST be placed in `pyplayground/utils/`. If you find yourself writing the same function twice, STOP and refactor it into a utility module first.
- **pyproject.toml is the source of truth**: ALWAYS check `pyproject.toml` first for configuration. Add new tool configurations there when possible.
- **Template files**: Store in `templates/` with `.j2` extension for Jinja2 templates
- **External tools**: Place in `bin/tools/` organized by vendor (k8s/, hashicorp/, vmware/, openshift/)
- **No src/**: Code lives directly in `pyplayground/`, not in a `src/` directory
- **Focus on specific issues**: Make targeted changes rather than broad refactoring

## Module Purposes

- **k8s/**: Kubernetes API operations, node management, resource discovery, kubeconfig utilities
- **vault/**: HashiCorp Vault integration, namespace monitoring, K8s auth, secret management
- **pxclients/**: Portworx storage cluster operations, PX-Backup utilities, cloud drive management
- **awxtower/**: AWX/Ansible Tower API integration, resource management
- **dndfightsim/**: D&D character simulation and combat mechanics
- **pxsecretmigrate/**: Standalone secret migration tool for Portworx environments
