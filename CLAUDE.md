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

### Testing Methodology

**Three-Tier Testing Strategy**:

**Tier 1: Automated Tests** (pytest or equivalent)

- **When**: After EVERY code change
- **Requirement**: Must remain passing (no tolerance for breaking tests)
- **Frequency**: Continuous
- **Command**: `pytest tests/` or equivalent

**Tier 2: Programmatic Validation**

- **When**: GUI/integration testing not available
- **Methods**:
  - Syntax validation (`python -m py_compile`)
  - Pattern verification (grep, static analysis)
  - Round-trip testing (load → process → save → compare)
  - API compliance checking
  - Comparison with reference implementations
- **Purpose**: Test what CAN be tested without full environment

**Tier 3: Manual Testing**

- **When**: Full environment available
- **Requirements**:
  - Structured checklist (not ad-hoc)
  - Document each step result
  - Capture logs for review
  - Verify with automated tools after
- **Purpose**: User experience validation, visual verification

**Testing Principles**:

1. **Test at highest available tier** - Don't skip testing because ideal environment unavailable
2. **Never skip Tier 1** - Automated tests always run
3. **Document test strategy** - Explain which tier used and why
4. **Validate with lower tiers** - Manual testing should still run automated tests

**Test Coverage Requirements**:

- Critical paths: 100% (must have tests)
- User-facing features: 90%+ (should have tests)
- Utility functions: 70%+ (nice to have tests)
- Legacy code: Test during modification (add as you touch)

**Test-Driven Bug Fixing**:

1. Write test that reproduces bug (if possible)
2. Verify test fails
3. Fix bug
4. Verify test passes
5. Keep test in suite (prevent regression)

For comprehensive testing methodology, see `docs/DEVELOPMENT_STANDARDS.md` Section 2.

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

### Core Coding Principles

**NO EXCEPTIONS to these rules**:

1. **Fix Bugs Immediately** - No "low priority" deferrals, regardless of fix time
2. **No Deprecated API** - Update immediately when found
3. **Consistent Patterns** - Copy proven code, don't reinvent
4. **Complete Error Handling** - All user-facing code must have try/except/finally
5. **Resource Cleanup** - Always use finally blocks for cleanup

### Code Pattern Template

Every user-facing function MUST follow this pattern:

```python
import logging
logger = logging.getLogger(__name__)

def userAction(self, event):
    """Clear docstring explaining purpose and behavior.
    
    Args:
        event: Description of parameter
        
    Returns:
        Description of return value (if any)
    """
    logger.info("User action started - describe what user did")
    
    try:
        # Setup phase
        logger.debug(f"Setup details: {variable}")
        
        # Main logic
        result = performOperation()
        
        # Handle result
        if result:
            logger.info(f"Operation succeeded: {result}")
            # Success path
        else:
            logger.debug("User cancelled operation")
            # Cancellation path
            
    except SpecificException as e:
        # Handle specific exceptions if possible
        logger.error(f"Specific error in operation: {e}", exc_info=True)
        showUserError(f"Specific error message: {e}")
    except Exception as e:
        # Catch-all for unexpected errors
        logger.error(f"Unexpected error in operation: {e}", exc_info=True)
        showUserError(f"An error occurred: {e}")
    finally:
        # Cleanup ALWAYS runs
        cleanup_resources()
        logger.debug("Cleanup completed")
```

**Mandatory Code Elements**:

Every function with user interaction MUST have:

- ✅ Logger initialization at module level
- ✅ Entry logging (info level) when user triggers action
- ✅ try/except/finally structure
- ✅ Error logging with `exc_info=True` for stack traces
- ✅ User feedback on errors
- ✅ Resource cleanup in finally block

Every module MUST have:

- ✅ `import logging` at top
- ✅ `logger = logging.getLogger(__name__)` after imports
- ✅ Docstrings on all functions/classes
- ✅ Type hints on new code (existing code optional)

### Forbidden Patterns

**Never use these in production/runtime code**:

- ❌ `print()` statements (except CLI tools and startup checks)
- ❌ Bare `except:` clauses without logging
- ❌ Resource allocation without cleanup
- ❌ Deprecated API calls
- ❌ Magic numbers without constants/comments
- ❌ Copy-paste code (extract to function)

For comprehensive coding standards, see `docs/DEVELOPMENT_STANDARDS.md` Section 1.

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

### Logging Standards (MANDATORY)

**Three-Level Hierarchy**:

**DEBUG Level** - Technical details for developers:

```python
logger.debug(f"Function called with args: {args}")
logger.debug(f"Current state: {state}")
logger.debug(f"Processing item {i} of {total}")
logger.debug("Internal operation completed")
```

**INFO Level** - User actions and major events:

```python
logger.info("Application started")
logger.info("User opened file dialog")
logger.info(f"User selected file: {path}")
logger.info(f"File saved successfully: {path}")
logger.info("Operation completed")
```

**WARNING Level** - Potential issues, recoverable problems:

```python
logger.warning("Deprecated API used, consider updating")
logger.warning(f"Retrying operation after failure: {retry_count}")
logger.warning("Configuration missing, using defaults")
```

**ERROR Level** - Exceptions and failures:

```python
logger.error(f"Failed to open file: {e}", exc_info=True)
logger.error(f"Operation failed: {e}", exc_info=True)
logger.error(f"Unexpected error: {e}", exc_info=True)
```

**Mandatory Logging Patterns**:

Every module:

```python
import logging
logger = logging.getLogger(__name__)  # REQUIRED at module level
```

Every user action:

```python
logger.info("User triggered [action name]")  # REQUIRED when action starts
```

Every exception:

```python
logger.error(f"Error in [operation]: {e}", exc_info=True)  # REQUIRED - note exc_info
```

Every resource operation:

```python
logger.debug("Opening resource: {resource}")
# ... operation ...
logger.debug("Closing resource: {resource}")
```

**Forbidden Logging Patterns**:

```python
# ❌ Using print() in runtime code
print("Debug info")  # Only acceptable in CLI tools and startup

# ❌ Logging without context
logger.info("Success")  # What succeeded?

# ❌ Exception without stack trace
logger.error(f"Error: {e}")  # Missing exc_info=True

# ❌ Using logging module directly
logging.info("Message")  # Use logger instance

# ❌ Excessive logging in loops
for item in huge_list:
    logger.debug(f"Processing {item}")  # Will flood logs

# ❌ Logging sensitive data
logger.info(f"Password: {password}")  # Security issue
```

For detailed logging standards and audit process, see `docs/DEVELOPMENT_STANDARDS.md` Section 5.

### Configuration Management

Configuration files live in `config/`, logs in `logs/`, and temporary files in `tmp/`. The `tmp/` directory contents should always be safe to delete.

### Documentation Standards

**IMPORTANT:** Follow these rules when working with documentation:

- **No emojis or icons** - Documentation must be professional and text-only
- **Ask before creating** - Always ask the user for approval before generating or modifying documentation files
- **No unsolicited documentation** - Never proactively create README files, markdown documentation, or similar without explicit user request
- Main docs in `docs/` directory covering setup, configuration, usage guides
- Keep README.md synchronized with project changes
- Update documentation when making code changes
- Document thought process and architecture decisions in `docs/`

This applies to all documentation including:

- README files
- Markdown documentation (*.md)
- Code comments and docstrings (emojis prohibited)
- Commit messages (emojis prohibited)

### Documentation Structure (When Authorized)

**Two Core Documents** (if maintained):

1. **`docs/progress.md`** - Timeline of what's been done
2. **`docs/debugging.md`** - Issues found and solutions

**progress.md Structure**:

- Track chronological progress through tasks
- Document changes made, tests run, logging added
- Update after EVERY task completion
- Include: Status, Date, Branch, Commit, Changes Made, Tests, Logging Added, Issues Found, Files Modified, Next Steps

**debugging.md Structure**:

- Document issues, root causes, and solutions
- Include: Symptom, Root Cause, Solution, Code Location, Verification, Logs, Prevention, Related Issues
- Cross-reference from progress.md

**Documentation Principles**:

1. **Update immediately** - Don't defer documentation
2. **Be specific** - "Fixed bug" is not sufficient
3. **Include code** - Show before/after when relevant
4. **Link between docs** - Cross-reference progress.md ↔ debugging.md
5. **No emojis in professional docs** - Text only (except status indicators)

For detailed documentation templates and examples, see `docs/DEVELOPMENT_STANDARDS.md` Section 6.

## Important Notes

- **MANDATORY: No code duplication**: ALL reusable code MUST be placed in `pyplayground/utils/`. If you find yourself writing the same function twice, STOP and refactor it into a utility module first.
- **pyproject.toml is the source of truth**: ALWAYS check `pyproject.toml` first for configuration. Add new tool configurations there when possible.
- **Template files**: Store in `templates/` with `.j2` extension for Jinja2 templates
- **External tools**: Place in `bin/tools/` organized by vendor (k8s/, hashicorp/, vmware/, openshift/)
- **No src/**: Code lives directly in `pyplayground/`, not in a `src/` directory
- **Focus on specific issues**: Make targeted changes rather than broad refactoring

## STOP Point Enforcement

**CRITICAL**: After completing each task, STOP and await approval before proceeding.

**Purpose**:

- Prevents rushing ahead without review
- Ensures quality of each task
- Catches issues early
- Maintains discipline
- Allows course correction

**STOP Point Template**:

```bash
echo "================================================"
echo "TASK X.Y COMPLETE"
echo "================================================"
echo ""

echo "Git Commit:"
git log -1 --oneline
echo ""

echo "Files Changed:"
git diff --stat HEAD~1 HEAD
echo ""

echo "Test Results:"
pytest --co -q | tail -1
# OR
echo "Manual tests: [results]"
echo ""

echo "Task-Specific Evidence:"
[Show relevant evidence for this specific task]
echo ""

echo "Documentation Updated:"
echo "- progress.md: [what was added]"
[ -f docs/debugging.md ] && echo "- debugging.md: [what was added]"
echo ""

echo "================================================"
echo "STOP HERE - Awaiting Approval"
echo "================================================"
```

**Never acceptable**:

- "Task looks good, proceeding to next" (without approval)
- "Skipping STOP since it's simple" (no exceptions)
- "Combining tasks to save time" (breaks discipline)
- "Will STOP at next task" (defeats purpose)

For detailed STOP point workflow and enforcement, see `docs/DEVELOPMENT_STANDARDS.md` Section 8.

## Reference Documentation

For comprehensive development standards, testing methodology, debugging practices, and detailed templates, see:

- **`docs/DEVELOPMENT_STANDARDS.md`** - Complete development standards and methodology (1147 lines)
- **`AGENT_RULES.md`** - Minimum required rules for all agents (highest precedence)
- **`AGENTS.md`** - Repository guidelines for contributors

## Module Purposes

- **k8s/**: Kubernetes API operations, node management, resource discovery, kubeconfig utilities
- **vault/**: HashiCorp Vault integration, namespace monitoring, K8s auth, secret management
- **pxclients/**: Portworx storage cluster operations, PX-Backup utilities, cloud drive management
- **awxtower/**: AWX/Ansible Tower API integration, resource management
- **dndfightsim/**: D&D character simulation and combat mechanics
- **pxsecretmigrate/**: Standalone secret migration tool for Portworx environments

## Markdown Code Block Language Specification

**Rule**: All fenced code blocks MUST have a language identifier specified to comply with MD040/fenced-code-language linting rules.

### Requirements

- Every code block using triple backticks (```) MUST include a language identifier
- If no specific language applies, use `text` as the default language identifier
- Never create code blocks with opening ``` without a language specifier

### Examples

**Correct**:

```python
print("Hello World")
```

```bash
echo "Hello World"
```

```text
This is plain text content
No specific language applies
```

**Incorrect**:

```
This violates MD040
```

### Common Language Identifiers

- Programming: `python`, `bash`, `javascript`, `java`, `yaml`, `json`, `xml`
- Output/Logs: `text`, `console`, `log`
- Documentation: `markdown`, `html`, `css`
- Configuration: `ini`, `toml`, `conf`
- When in doubt: `text`

This rule is clear, actionable, and includes examples of both correct and incorrect usage. It fits well with your existing Ansible documentation standards and will prevent MD040 violations in any markdown files Claude creates for you.

## Git Workflow

### Commit Message Format for Scripting Work

**IMPORTANT:** Do NOT add Claude Code attribution or co-authorship to commit messages.

**Scripting Work Format** (flexible, optional sections):

```text
[Short description - 50 chars max, imperative mood]

[Optional: What changed and WHY - be specific]
[Optional: Error handling added - pattern used]
[Optional: Uses shared utilities - which ones]

Modified:
- path/to/file.py (+X, -Y lines): [brief description]
- path/to/file2.py (+A, -B lines): [brief description]
```

**Commit Message Rules**:

1. First line: always required, 50 chars max, imperative mood
2. Body: optional, only include relevant sections
3. Modified section: always include file paths with line counts
4. Skip sections not applicable (Testing, Logging, Documentation)
5. No AI attribution (keep professional)

**Examples**:

Quick script:
```text
Add ansible inventory search utility

One-off script to search inventory for host patterns.
Uses config_utils for path handling.

Modified:
- scripts/inventory_search.py (+87 lines)
```

Bug fix:
```text
Fix vault token expiration handling

Root cause: Token not refreshed before expired.
Solution: Added retry with token refresh in loop.

Modified:
- vault/k8s_auth.py (+15, -3)
- Added retry logic with exponential backoff
```

Refactor:
```text
Refactor config loading to use shared utility

Moved hardcoded paths to config_utils.get_env_var().
Consistent with other scripts in repo.

Modified:
- k8s/node_manager.py (-12, +8)
- vault/secret_fetcher.py (-15, +10)
```

**Commit Frequency**:

- One commit per logical change
- After tests passing
- After code quality checks
- After STOP point approval received

**Pre-Commit Checklist**:

```bash
# 1. All tests passing
pytest tests/

# 2. Code quality checks
black pyplayground/
isort pyplayground/
flake8 pyplayground/
mypy pyplayground/

# 3. Review changes
git diff --staged

# 4. Commit with message
git commit -m "[message]"
```

Bad example (DO NOT USE):

```text
Add new feature

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

Good example:

```text
Add etcd defragmentation monitoring

Implements health check validation before and after defrag operations
to ensure cluster stability.
```

For detailed git workflow and branch strategy, see `docs/DEVELOPMENT_STANDARDS.md` Section 7.
