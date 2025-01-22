# PyPlayground

A Python-based mock and testing environment for various infrastructure components including Kubernetes, VMware, and HashiCorp Vault APIs. This repository serves as a development and testing playground for simulating and mocking these systems.

## Project Overview

This project provides mock implementations and testing utilities for:
- Kubernetes (K8s) API simulation
- VMware infrastructure mocking
- HashiCorp Vault API testing
- DND simulator components

## Project Structure

```
.
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
- Dependencies tracked in:
  - requirements.txt (production dependencies)
  - requirements-dev.txt (development dependencies)
  - pyproject.toml (project configuration)
- All dependency files kept in sync

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

1. Create and activate virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

3. Run tests:
```bash
pytest
```

## Development Process

When making changes:
1. Follow type hinting and documentation requirements
2. Ensure tests are written and passing
3. Run black, flake8, and mypy before committing
4. Update documentation as needed
5. Keep dependency files in sync
6. Focus on specific issues rather than making broad changes

## License

[Add appropriate license information]