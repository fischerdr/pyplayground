# Project Organization Guide

## Directory Structure

This document outlines the standard project organization for our Python and shell script projects.

### Root Directory Structure

```text
project_root/
├── bin/           # Executables and scripts directory
│   ├── scripts/   # Shell scripts and custom executables
│   └── tools/     # External binaries and tools
│       ├── k8s/        # Kubernetes tools (kubectl, helm)
│       ├── hashicorp/  # HashiCorp tools (vault)
│       ├── vmware/     # VMware tools
│       └── openshift/  # OpenShift tools (oc)
├── src/           # Python source code
│   └── your_package/
├── templates/     # Template files directory
│   ├── k8s/      # Kubernetes templates (yaml, json)
│   ├── scripts/  # Script templates
│   ├── config/   # Configuration templates
│   └── docs/     # Documentation templates
├── utils/         # Shared utility functions
├── tests/         # Test directory
├── docs/          # Documentation
├── logs/          # Log files
├── config/        # Configuration files
└── .venv/         # Virtual environment
```

## Project Purpose

This Python project is used for:

- Vault integration
- Kubernetes (k8s) operations
- DND simulator
- VMware integration
- Mock APIs for k8s, VMware, and Vault testing

## Directory Purposes

### Python Code Organization

- `src/`: Main Python package source code
  - Contains all primary Python modules
  - Follows Python packaging best practices
  - Uses Python 3.9-3.14

### Shell Scripts Organization

- `bin/`: Contains all executable content
  - `bin/scripts/`: Shell scripts and custom executables
    - All shell scripts must follow shell script standards
    - Functions defined at top of file
    - Variables defined before use
    - Use double quotes for variable expansion
  - `bin/tools/`: External binaries and tools
    - Organized by vendor/purpose
    - Version controlled through .gitignore
    - Required versions documented in README.md
    - Consider using version managers (asdf, tfenv)
    - Subdirectories:
      - `k8s/`: Kubernetes related tools (kubectl, helm)
      - `hashicorp/`: HashiCorp tools (vault)
      - `vmware/`: VMware related tools
      - `openshift/`: OpenShift tools (oc)

### Template Organization

- `templates/`: Contains all template files used by scripts and applications
  - `templates/k8s/`: Kubernetes-related templates
    - YAML manifests (*.yaml,*.yml)
    - JSON configurations (*.json)
    - Jinja2 templates (*.j2)
    - CRD templates
  - `templates/scripts/`: Script templates
    - Shell script templates (*.sh.j2)
    - Python script templates (*.py.j2)
    - Common code snippets
  - `templates/config/`: Configuration templates
    - Application configs (*.yaml.j2,*.json.j2)
    - Environment files (*.env.j2)
    - Service configurations
  - `templates/docs/`: Documentation templates
    - README templates (*.md.j2)
    - API documentation templates
    - Markdown templates

Notes:

- Templates should use clear variable placeholders
- Include example values in comments
- Document required variables
- Use consistent naming conventions
- Keep templates version controlled
- Include validation scripts where applicable
- File extensions:
  - Use `.j2` for Jinja2 templates
  - Use `.yaml` or `.yml` for YAML files
  - Use `.json` for JSON files
  - Original extension + `.j2` for templated files (e.g., `config.yaml.j2`)

### Utility Functions

- `utils/`: Shared utility functions
  - Common code used across multiple scripts
  - Promotes code reuse
  - Reduces duplication
  - Should be imported whenever functionality is needed in multiple scripts

### Supporting Directories

- `tests/`: Unit and integration tests
  - Uses pytest framework
  - Includes both unit and integration tests
- `docs/`: Project documentation
  - Comprehensive setup guides
  - Configuration documentation
  - Usage examples
  - Must be reviewed and updated with any code changes
- `logs/`: Log files
  - Application logs
  - Debug information
  - Used for tracking progress and errors
- `config/`: Configuration files
  - Application settings
  - Environment-specific configs

## Development Standards

### Python Standards

- Minimum Python version: 3.9
- Maximum Python version: 3.14
- CLI Tools:
  - click/typer for command-line interfaces
- Code Quality:
  - black for code formatting
  - isort for import sorting
  - flake8 for code linting
- Testing: pytest for all unit tests
- Logging: Always use logging for tracking progress and errors
- Documentation:
  - Comprehensive docstrings required
  - Type hints required
  - Inline comments for complex logic
- Line length: 100 characters maximum

### Shell Script Standards

- Use double quotes for variable expansion
- Define functions before calling them
- Place functions at the top of the file
- Define variables before use

### Project Configuration

- Keep pyproject.toml in sync with:
  - requirements.txt
  - requirements-dev.txt
- Use double quotes for environment variable values
- Docker containers should use either:
  - CentOS Stream
  - Fedora Stream
  - Alpine
- Binary and tool versions:
  - Document required versions in README.md
  - Use version managers where available
  - Add binary paths to PATH in shell configuration
  - Keep binaries out of version control

### Documentation Requirements

- Update documentation when making changes
- Keep README.md current
- Maintain comprehensive docs in docs/ directory
- Review documentation when changes are made
- Update pyproject.toml when necessary

## Usage Examples

[Add specific usage examples for your project here]

## Contributing

[Add contribution guidelines or link to CONTRIBUTING.md]
