# Project State Documentation

## Project Overview

This project consists of a collection of Python scripts for interacting with Kubernetes clusters and PX-Backup systems. The scripts follow consistent coding standards and utilize shared utilities for common functionality.

## Scripts Overview

All Kubernetes-related scripts are prefixed with `k8s_` and located in the `src/` directory.

All Portworx scripts are prefixed with `px` and located in the `src/pxclients/` directory.

All PX-Backup scripts are prefixed with `pxbkup` and located in the `src/pxclients/` directory.

## Code Standards and Conventions

### Python Standards

1. Code Formatting:
   - Black formatting enforced
   - Flake8 linting rules followed
   - isort for import sorting
   - Maximum complexity rules enforced (Flake8 C901)

2. Documentation:
   - Comprehensive docstrings (Google style)
   - Type hints used throughout
   - Inline comments for complex logic

3. Error Handling:
   - Consistent exception handling patterns
   - Detailed error logging
   - User-friendly error messages

### Shared Utilities

Located in the `utils/` directory:

1. `k8s_utils.py`:
   - Kubernetes configuration management
   - Common cluster operations

2. `logging_utils.py`:
   - Centralized logging configuration
   - Consistent log formatting

3. `px_api.py`:
   - PX-Backup API client
   - Authentication utilities

4. `config_utils.py`:
   - Configuration management
   - Environment variable handling

#### future utils

- `pxbkup_utils.py`:
  - PX-Backup utilities

### Output Formatting

- Rich library used for console output
- Consistent color schemes:
  - Cyan: Names and identifiers
  - Yellow: Warnings and status
  - Red: Errors
  - Green: Success indicators
  - Blue: Pod information
  - Magenta: Container information

## Command Line Interface

All scripts use Click for CLI implementation with:

- Consistent help documentation
- Environment variable support
- Proper argument validation
- Uniform error handling

## Authentication and Security

1. PX-Backup Authentication:
   - Token-based authentication
   - Optional token generation flow
   - Secure password handling

2. Kubernetes Authentication:
   - Automatic kubeconfig loading
   - Support for various authentication methods

## Logging System

- Hierarchical logger configuration
- Debug mode support
- Consistent log formatting
- File and console output

## Error Handling Strategy

1. API Errors:
   - Specific handling for common API failures
   - Detailed error messages
   - Appropriate exit codes

2. User Input Validation:
   - Pre-execution validation
   - Clear error messages
   - Helpful usage hints

## Future Considerations

1. Potential Improvements:
   - Additional filtering options
   - Batch operation support
   - Configuration file support
   - Output format options (JSON, YAML)

2. Maintenance Notes:
   - Regular dependency updates needed
   - API version compatibility checks
   - Documentation updates for new features

## Dependencies

Core dependencies include (please refer to `pyproject.toml` for the complete and authoritative list of dependencies and their versions):

- kubernetes-client
- click
- rich
- requests
- urllib3
- python-dotenv

## Development Environment

- Python 3.9-3.14
- Linux-based development environment
- Kubernetes cluster access required
- PX-Backup system access required
- Portworx storage cluster installed and configured
- Portworx pod access required
- PX-Backup API access required
- PX-Backup API key required
- PX-Backup API secret required
- PX-Backup API token required

## Future Development

- Add more scripts
- Add more tests
- Add more documentation
- Add more examples

## Future Scripts
