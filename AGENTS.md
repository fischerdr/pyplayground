# Repository Guidelines

This document provides a quick reference for contributors working on the **pyplayground**
project. It covers folder layout, build and test commands, coding style, testing,
and pull‑request expectations.

## Project Structure & Module Organization

- `pyplayground/` – Python source tree (modules, utils, vault helpers).
- `tests/` – unit / integration tests using **pytest**.
- `ansible/` – Ansible playbooks and roles used to provision Vault clusters.
- `docs/`, `examples/`, `templates/` – documentation, example playbooks and
  Jinja templates.
- `scripts/` – helper shell utilities for CI or local dev.

All Python packages expose a public API via `__init__.py`. The root contains
`pyproject.toml` and the runtime dependencies (`requirements.txt`).

## Build, Test, and Development Commands

Before running any Python command, activate the local virtual environment:

```bash
source .venv/bin/activate  # macOS/Linux
# or on Windows: .\venv\Scripts\activate
```

After activation you can use the following commands:

- **Install locally** – `pip install -e .`
- **Run tests** – `pytest` (covers 80% by default). Add flags such as `-v` for verbose.
- **Lint & format** – `flake8`, `black --check`, and `isort --check-only`.
- **Validate Ansible** – `ansible-playbook -i inventory/hosts <playbook>.yml`
  or run the role tests in `ansible/tests`.

## Development Commands

All Python commands must run with the virtual environment activated or by prefixing the executable path.

### Environment Setup

```bash
python -m venv .venv
source .venv/bin/activate
# Install development dependencies (includes production deps)
.venv/bin/pip install -r requirements-dev.txt
```

### Testing

```bash
source .venv/bin/activate
.venv/bin/pytest --cov=pyplayground tests/
```

### Code Quality

```bash
source .venv/bin/activate
.venv/bin/black pyplayground/
.venv/bin/isort pyplayground/
.venv/bin/flake8 pyplayground/
.venv/bin/mypy pyplayground/
```

## Code Organization and Reuse Policy

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

**Python Code Standards**

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

## Coding Style & Naming Conventions

Python follows *PEP 8* with an enforced line‑length of 88 characters. Use
`black`, `isort`, and `flake8` for formatting. Class names are **PascalCase**;
module and function names use **snake_case**. Constants are UPPER_SNAKE_CASE.
All modules expose a minimal public API – keep imports explicit.

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

## Documentation Standards

**CRITICAL**: Follow these rules when working with documentation:

- **No emojis or icons** - Documentation must be professional and text-only
- **Ask before creating** - Always ask the user for approval before generating or modifying documentation files
- **No unsolicited documentation** - Never proactively create README files, markdown documentation, or similar without explicit user request
- Main documentation in `docs/` directory
- Update documentation when making code changes

**This applies to all documentation including:**

- README files
- Markdown documentation (*.md)
- Code comments and docstrings (emojis prohibited)
- Commit messages (emojis prohibited)

## Testing Guidelines

The test suite is located under `tests/` and runs with **pytest**. Test files
should be named `test_*.py`. Use the `@pytest.mark.parametrize` decorator for
data‑driven tests. Coverage should hit at least 80 % – run `coverage run -m pytest`
and review `coverage report`.

## Commit & Pull Request Guidelines

### Commit messages

- Follow **Conventional Commits** style: e.g., `feat`, `fix`, `docs`, `refactor`.
  Include a short subject and, if needed, a body with the rationale.

### Pull requests

- Reference an issue number in the title or description.
- Provide clear steps to reproduce changes.
- Attach screenshots for UI/CLI output when relevant.
- Request review from at least one core maintainer.

## Git Commit Messages

**IMPORTANT**: Do NOT add attribution or co-authorship to commit messages.

Commit messages should:

- Follow conventional commit format when appropriate
- Be concise and descriptive
- Focus on the "why" rather than the "what"
- Match the repository's existing commit style
- **NOT include** any branding, attribution, or co-authorship footers

## System Commands Policy

**CRITICAL**: The `rm` command is strictly prohibited without explicit user permission.

- Never execute `rm` commands without prior approval from the user
- All file deletion operations must be reviewed and authorized by the user first
- When working with temporary files or directories, always ask for confirmation before removal
- If a script needs to delete files, implement an interactive prompt that requires explicit user consent

This policy protects against accidental data loss during development and testing activities.

- Avoid hard‑coding Vault tokens; use environment variables such as
  `VAULT_TOKEN` or files in `~/.vault-token`.
- Keep the `ansible.cfg` minimal – enable `hashiCorp/vault` lookup plugin.

Feel free to reach out on the repo's issue tracker for clarification. Happy coding!
