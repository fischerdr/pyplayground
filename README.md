# PyPlayground

A Python-based mock and testing environment for various infrastructure components including Kubernetes, VMware, and HashiCorp Vault APIs. This repository serves as a development and testing playground for simulating and mocking these systems.

## Project Overview

This project provides mock implementations and testing utilities for:

- Kubernetes (K8s) API simulation
- VMware infrastructure mocking
- HashiCorp Vault API testing
- DND simulator components

## Project Structure

```text
├── utils/          # Utility functions shared across the project
├── docs/           # Project documentation
├── tests/          # Unit and integration tests
├── .venv/          # Python virtual environment
├── logs/           # Application log files
└── config/         # Configuration files
```

## Development Standards

### Python Standards

- Minimum Python version: 3.9
- Maximum Python version: 3.14
- Code formatting: Black
- Linting: Flake8
- Type checking: MyPy
- Testing framework: pytest
- CLI frameworks: Click and Typer
- Comprehensive logging implementation in all modules
- Type hints required for all functions and classes
- Docstrings required for all modules, classes, and functions

### Documentation Standards

- Comprehensive documentation maintained in `docs/` directory
- Documentation covers:
  - Application setup
  - Configuration
  - Usage guides
  - API references

### Code Organization

- Utility functions are centralized in `utils/` directory
- Common functions used across multiple scripts must be moved to utils
- Configuration managed through `config/` directory
- Logs stored in `logs/` directory

### Environment and Dependencies

- Virtual environment maintained in `.venv/` directory
- Dependencies are defined in `pyproject.toml`:
  - `[project.dependencies]` for production dependencies.
  - `[project.optional-dependencies].dev` for development dependencies.
- Pinned requirement files (`requirements.txt`, `requirements-dev.txt`) are **generated** from `pyproject.toml` using `pip-tools`.
  - **Do not edit `requirements.txt` or `requirements-dev.txt` manually.**

### Shell Scripting Standards

- Double quotes required for variable expansion
- Function definitions must precede their usage
- Variables must be defined before use
- Functions should be placed at the top of shell scripts

### Container Standards

- Container base images limited to:
  - CentOS
  - Fedora
  - Alpine

## Getting Started

1. **Clone the repository:**

   ```bash
   git clone <repository-url>
   cd pyplayground
   ```

2. **Create and activate virtual environment:**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies for development:**
   This command installs all dependencies (production + development) based on the pinned versions in `requirements-dev.txt`.

   ```bash
   pip install -r requirements-dev.txt
   # Or, to ensure only these dependencies are installed/updated:
   # pip install pip-tools
   # pip-sync requirements-dev.txt
   ```

   *(For production environments, use `pip install -r requirements.txt`)*

4. **Run tests:**

   ```bash
   pytest
   ```

## Dependency Management

- **To add or update dependencies:**
  1. Modify the `[project.dependencies]` or `[project.optional-dependencies].dev` section in `pyproject.toml`.
  2. Regenerate the pinned requirement files:

     ```bash
     # Ensure pip-tools is installed (it's a dev dependency)
     pip-compile --resolver=backtracking -o requirements.txt pyproject.toml
     pip-compile --resolver=backtracking --extra dev -o requirements-dev.txt pyproject.toml
     ```

  3. Commit the changes to `pyproject.toml` **and** the updated `requirements.txt` / `requirements-dev.txt` files.

## Development Process

When making changes:

1. Follow type hinting and documentation requirements
2. Ensure tests are written and passing
3. Run linters/formatters (e.g., via pre-commit hooks or manually: `black .`, `isort .`, `flake8`, `mypy src`)
4. Update documentation as needed
5. Follow the dependency management process outlined above.
6. Focus on specific issues rather than making broad changes

## License

[Add appropriate license information]
