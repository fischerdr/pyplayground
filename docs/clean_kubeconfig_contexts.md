# Clean Kubeconfig Contexts

## Overview

The `clean_kubeconfig_contexts.py` script is a utility for consolidating and cleaning up Kubernetes configuration files (kubeconfig). It identifies redundant contexts that share the same cluster and user credentials, consolidates them into a single context with a specified namespace, and removes unused clusters and users.

## Features

- Identifies and removes redundant contexts (same cluster/user combinations)
- Creates a consolidated context with a specified namespace
- Cleans up unused clusters and users from the kubeconfig
- Supports dry-run mode to preview changes without applying them
- Provides detailed logging of all operations
- Lists all available contexts in the kubeconfig with rich, colorful formatting
- Displays details of the current context in a visually appealing panel

## Prerequisites

- Python 3.9 or higher
- Kubernetes Python client library (`kubernetes`)
- Click Python package for CLI interface
- PyYAML for YAML file handling
- Rich library for enhanced terminal output

## Installation

1. Ensure you have the required Python version installed
2. Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Clean and consolidate contexts
python src/clean_kubeconfig_contexts.py --kubeconfig <path-to-kubeconfig> --namespace <target-namespace> --context-name <new-context-name> [--dry-run] [--verbose]

# List all contexts
python src/clean_kubeconfig_contexts.py --list-contexts [--verbose]

# Show current context
python src/clean_kubeconfig_contexts.py --show-current-context
```

### Command Line Options

| Option | Required | Description |
|--------|----------|-------------|
| `--kubeconfig` | No | Path to the kubeconfig file (default: `~/.kube/config`) |
| `--namespace` | Yes* | Target namespace for the consolidated context |
| `--context-name` | Yes* | Name of the new consolidated context |
| `--dry-run` | No | Show what would be changed without applying |
| `--verbose`, `-v` | No | Enable verbose logging |
| `--list-contexts` | No | List all available contexts in the kubeconfig |
| `--show-current-context` | No | Show the current context and its details |

*Required for cleanup operations, not needed for listing contexts or showing current context.

## Examples

### Basic Usage

```bash
python src/clean_kubeconfig_contexts.py --kubeconfig <path-to-kubeconfig> --namespace default --context-name consolidated-context
```

This command will:

1. Identify redundant contexts in your kubeconfig
2. Create a new context named "consolidated-context" with namespace "default"
3. Remove redundant contexts
4. Clean up unused clusters and users

### Dry Run Mode

```bash
python src/clean_kubeconfig_contexts.py --kubeconfig <path-to-kubeconfig> --namespace default --context-name consolidated-context --dry-run
```

This will show what changes would be made without actually applying them.

### Verbose Logging

```bash
python src/clean_kubeconfig_contexts.py --kubeconfig <path-to-kubeconfig> --namespace default --context-name consolidated-context --verbose
```

Enables detailed logging of all operations.

### List All Contexts

```bash
python src/clean_kubeconfig_contexts.py --kubeconfig <path-to-kubeconfig> --list-contexts
```

Lists all available contexts in the kubeconfig file with a simple, colorful table format.

```bash
python src/clean_kubeconfig_contexts.py --kubeconfig <path-to-kubeconfig> --list-contexts --verbose
```

Lists all contexts with detailed information including cluster, user, and namespace in a rich, formatted table.

### Show Current Context

```bash
python src/clean_kubeconfig_contexts.py --show-current-context
```

Displays detailed information about the currently active context in a visually appealing panel.

## How It Works

1. The script loads the kubeconfig file using the Kubernetes Python client's `KubeConfigLoader`
2. It identifies contexts that share the same cluster and user credentials
3. It creates a new context with the specified name and namespace using the first valid cluster/user pair
4. It removes redundant contexts that use the same cluster/user combination
5. It identifies and removes clusters and users that are no longer referenced by any context

## Troubleshooting

### Common Issues

1. **API errors**: Ensure that your kubeconfig file is valid and accessible
2. **Permission errors**: Make sure you have write permissions to your kubeconfig file
3. **YAML parsing errors**: If the kubeconfig file is corrupted, fix it manually or recreate it

### Logs

Logs are written to both the console and to `logs/clean_kubeconfig_contexts.log`. Check these logs for detailed information about any errors.

## Security Considerations

- The script modifies your kubeconfig file, which contains sensitive authentication information
- It does not transmit any data outside your local system
- Always review changes in dry-run mode before applying them
- The script uses the default kubeconfig location, which is typically `~/.kube/config`

## Contributing

When contributing to this script, please follow the project's Python development guidelines:

- Use type hints consistently
- Add comprehensive docstrings
- Follow PEP8 style guide
- Use the logging module for tracking progress and errors
- Ensure proper error handling for all file operations and API calls
