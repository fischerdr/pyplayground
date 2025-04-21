# Project State Documentation

## Project Overview

This project consists of a collection of Python scripts for interacting with Kubernetes clusters and PX-Backup systems. The scripts follow consistent coding standards and utilize shared utilities for common functionality.

## Scripts Overview

### Kubernetes Scripts

All Kubernetes-related scripts are prefixed with `k8s_` and located in the `src/` directory.

1. `k8s_find_pod.py`
   - Purpose: Searches for a Kubernetes pod by name across all namespaces
   - Features:
     - Cross-namespace pod search
     - Node and IP information display
     - Rich console output formatting
     - Comprehensive logging
   - Main Functions:
     - `get_pod_info()`: Core search functionality
     - `_get_node_external_ip()`: Helper for node IP resolution

2. `k8s_inspect_pod.py`
   - Purpose: Detailed inspection of a specific Kubernetes pod
   - Features:
     - Container status information
     - Init container details
     - Volume mount information
     - Optional container log retrieval
   - Main Functions:
     - `get_pod_details()`: Fetches pod information
     - `get_pod_logs()`: Retrieves container logs
     - `display_pod_info()`: Formats and displays pod details

3. `k8s_get_backup_job_logs.py`
   - Purpose: Monitors PX-Backup jobs and retrieves logs
   - Features:
     - Integration with PX-Backup API
     - Kubernetes job tracking
     - Log retrieval from kopiaexecutor containers
     - Cluster filtering capabilities
   - Main Functions:
     - `fetch_running_backups()`: Gets active backup jobs
     - `find_jobs_for_backup()`: Locates associated K8s jobs
     - `get_kopia_logs_from_pod()`: Retrieves container logs

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

Core dependencies include:

- kubernetes-client
- click
- rich
- requests
- urllib3
- python-dotenv

## Development Environment

- Python 3.x
- Linux-based development environment
- Kubernetes cluster access required
- PX-Backup system access required
