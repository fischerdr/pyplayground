# Vault Scripts Usage Guide

This document explains how to use the updated Vault namespace review scripts with the new configuration system.

## Prerequisites

1. **Environment Setup**: Copy `.env.example` to `.env` and configure your Vault connection details:

   ```bash
   cp .env.example .env
   ```

2. **Required Environment Variables**:
   - `VAULT_ADDR`: Your Vault server address (e.g., `https://vault.example.com:8200`)
   - `VAULT_TOKEN`: Your Vault authentication token

3. **Optional Environment Variables**:
   - `VAULT_NAMESPACE`: Target namespace (defaults to "root")
   - `VAULT_DEBUG`: Enable debug mode (true/false, defaults to false)
   - `VAULT_LOG_LEVEL`: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL, defaults to INFO)
   - `VAULT_OUTPUT_DIR`: Output directory for results (defaults to "./tmp")

## Scripts

### 1. Example Vault Usage (`example_vault_usage.py`)

This script demonstrates various ways to use the Vault namespace review functionality.

**Usage**:

```bash
# Use defaults from environment variables
python pyplayground/example_vault_usage.py

# Override namespace
python pyplayground/example_vault_usage.py --namespace my-namespace

# Enable debug mode
python pyplayground/example_vault_usage.py --debug

# Combine options
python pyplayground/example_vault_usage.py --namespace my-namespace --debug
```

**Features**:

- Loads configuration from `.env` file automatically
- Demonstrates policy analysis
- Shows group analysis
- Performs auth method analysis
- Saves results to configured output directory
- Demonstrates error handling

### 2. Test Vault Namespace Review (`test_vault_namespace_review.py`)

This script provides a simple way to test the Vault namespace review functionality.

**Usage**:

```bash
# Use defaults from environment variables
python pyplayground/test_vault_namespace_review.py

# Override namespace
python pyplayground/test_vault_namespace_review.py --namespace my-namespace

# Enable debug mode
python pyplayground/test_vault_namespace_review.py --debug

# Specify output file
python pyplayground/test_vault_namespace_review.py --output results.json

# Combine options
python pyplayground/test_vault_namespace_review.py --namespace my-namespace --debug --output results.json
```

**Features**:

- Loads configuration from `.env` file automatically
- Performs comprehensive namespace review
- Saves results to JSON file
- Displays results in console (Rich formatting)
- Proper error handling and exit codes

## Configuration Priority

The scripts follow this configuration priority:

1. **Command-line arguments** (highest priority)
2. **Environment variables** (from `.env` file or system)
3. **Default values** (lowest priority)

## Example Configuration

Here's an example `.env` file:

```bash
# Required Vault Configuration
VAULT_ADDR=https://vault.example.com:8200
VAULT_TOKEN=your-vault-token-here

# Optional Configuration
VAULT_NAMESPACE=my-namespace
VAULT_DEBUG=false
VAULT_LOG_LEVEL=INFO
VAULT_OUTPUT_DIR=./tmp
```

## Output

Both scripts will:

- Create the output directory if it doesn't exist
- Save results in JSON format
- Use Rich console formatting for better readability
- Provide detailed logging

## Error Handling

The scripts include comprehensive error handling:

- Validates required environment variables
- Handles Vault API errors gracefully
- Provides meaningful error messages
- Uses proper exit codes for automation

## Integration with CI/CD

The scripts are designed to work well in CI/CD pipelines:

- Use environment variables for configuration
- Provide proper exit codes
- Support both interactive and non-interactive modes
- Generate structured output for further processing
