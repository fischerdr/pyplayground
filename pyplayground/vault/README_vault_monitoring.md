# Vault Multi-Namespace Monitoring Tools

This directory contains enhanced tools for testing and monitoring Vault Kubernetes authentication across multiple namespaces.

## Overview

The enhanced monitoring system consists of two main scripts:

1. **`setup_vault_test_environment.py`** - Creates test namespaces and configures Vault policies, roles, and test data
2. **`multi_namespace_vault_monitor.py`** - Tests Vault access across multiple namespaces with comprehensive reporting

## Prerequisites

- Python 3.9+
- Kubernetes cluster with appropriate permissions
- Vault server with Kubernetes authentication enabled
- Required Python packages (see requirements.txt)

## Quick Start

### 1. Setup Test Environment

First, create the test environment with one Kubernetes namespace and multiple Vault namespaces:

```bash
python pyplayground/vault/setup_vault_test_environment.py \
    --namespace "test-namespace" \
    --vault-namespaces "vault-ns1,vault-ns2" \
    --secret-paths "test/secret1,test/secret2" \
    --vault-addr "https://vault.example.com" \
    --vault-token "your-vault-root-token"
```

### 2. Run Monitoring Tests

After setup, test the Vault access across Vault namespaces:

```bash
python pyplayground/vault/multi_namespace_vault_monitor.py \
    --namespace "test-namespace" \
    --secret-paths "test/secret1,test/secret2" \
    --vault-namespaces "vault-ns1,vault-ns2"
```

## Detailed Usage

### Setup Script (`setup_vault_test_environment.py`)

Creates a complete test environment including:

- **Single Kubernetes Namespace**: Creates one Kubernetes namespace
- **Service Account**: Creates `vault-auth` service account for authentication
- **Vault Policies**: Creates policies for accessing specific secret paths in each Vault namespace
- **Vault Roles**: Configures Kubernetes authentication roles for each Vault namespace
- **Test Secrets**: Creates sample KV2 secrets with test data in each Vault namespace
- **Connection Secrets**: Creates Kubernetes secrets with Vault connection info

#### Options

| Option | Required | Description |
|--------|----------|-------------|
| `--namespace` | Yes | Single Kubernetes namespace to create |
| `--vault-namespaces` | Yes | Comma-separated list of Vault namespaces to configure |
| `--secret-paths` | Yes | Comma-separated list of secret paths to create (must match vault namespaces order) |
| `--vault-addr` | Yes | Vault server address (e.g., https://vault.example.com) |
| `--vault-token` | Yes | Vault root token for setup operations |
| `--backend-path` | No | Vault KV mount path (default: "secret") |
| `--auth-mount-path` | No | Vault Kubernetes auth mount path (default: "kubernetes") |
| `--kv-mount-path` | No | Vault KV secrets engine mount path (default: "secret") |
| `--kubeconfig` | No | Path to kubeconfig file (uses default if not provided) |
| `--debug` | No | Enable debug logging |
| `--k8s-verify-ssl/--k8s-no-verify-ssl` | No | Enable/disable SSL verification for Kubernetes API |
| `--k8s-ssl-ca-cert` | No | Path to custom CA certificate for Kubernetes API |

#### Example Setup

```bash
# Basic setup
python pyplayground/vault/setup_vault_test_environment.py \
    --namespace "test-namespace" \
    --vault-namespaces "dev,staging" \
    --secret-paths "app/config,app/config" \
    --vault-addr "https://vault.company.com" \
    --vault-token "hvs.xxxxxxxxxxxxxxxx"

# Advanced setup with custom paths
python pyplayground/vault/setup_vault_test_environment.py \
    --namespace "test-namespace" \
    --vault-namespaces "vault-ns1,vault-ns2" \
    --secret-paths "myapp/config1,myapp/config2" \
    --vault-addr "https://vault.example.com" \
    --vault-token "your-token" \
    --backend-path "kv" \
    --auth-mount-path "k8s" \
    --kv-mount-path "kv" \
    --debug
```

### Monitoring Script (`multi_namespace_vault_monitor.py`)

Tests Vault Kubernetes authentication across multiple Vault namespaces with comprehensive reporting.

#### Features

- **Multi-Vault-Namespace Testing**: Tests multiple Vault namespaces simultaneously
- **Authentication Testing**: Verifies Kubernetes service account authentication
- **Secret Access Testing**: Tests reading KV2 secrets from Vault
- **Comprehensive Reporting**: Detailed pass/fail status for each test
- **Error Handling**: Robust error handling and logging
- **Rich Output**: Formatted console output with tables and panels
- **Data Masking**: Optional masking of sensitive values in output

#### Options

| Option | Required | Description |
|--------|----------|-------------|
| `--namespace` | Yes | Single Kubernetes namespace to test |
| `--secret-paths` | Yes | Comma-separated list of secret paths to test (must match vault namespaces order) |
| `--vault-namespaces` | Yes | Comma-separated list of Vault namespaces to test |
| `--kubeconfig` | No | Path to kubeconfig file (uses default if not provided) |
| `--px-namespace` | No | Kubernetes namespace for Portworx secrets (default: "kube-system") |
| `--debug` | No | Enable debug logging |
| `--mask/--no-mask` | No | Mask/unmask sensitive values (default: mask) |
| `--k8s-verify-ssl/--k8s-no-verify-ssl` | No | Enable/disable SSL verification for Kubernetes API |
| `--k8s-ssl-ca-cert` | No | Path to custom CA certificate for Kubernetes API |

#### Example Monitoring

```bash
# Basic monitoring
python pyplayground/vault/multi_namespace_vault_monitor.py \
    --namespace "test-namespace" \
    --secret-paths "test/secret1,test/secret2" \
    --vault-namespaces "vault-ns1,vault-ns2"

# Advanced monitoring with debug and no masking
python pyplayground/vault/multi_namespace_vault_monitor.py \
    --namespace "test-namespace" \
    --secret-paths "app/config,app/config" \
    --vault-namespaces "dev,staging" \
    --px-namespace "portworx" \
    --debug \
    --no-mask
```

## Output Examples

### Setup Script Output

The setup script provides detailed feedback on each component:

```
Vault Test Environment Setup Results
┌─────────────┬──────────────┬──────────────┬─────────────┬─────────────┬─────────────┬─────────────────┬─────────┐
│ Vault Namespace│ K8s Namespace│ Service Acct │ Vault Policy│ Vault Role  │ Test Secret │ Connection Secret│ Overall │
├─────────────┼──────────────┼──────────────┼─────────────┼─────────────┼─────────────┼─────────────────┼─────────┤
│ vault-ns1   │ ✓            │ ✓            │ ✓          │ ✓          │ ✓          │ ✓               │ ✓      │
│ vault-ns2   │ ✓            │ ✓            │ ✓          │ ✓          │ ✓          │ ✓               │ ✓      │
└─────────────┴──────────────┴──────────────┴─────────────┴─────────────┴─────────────┴─────────────────┴─────────┘
```

### Monitoring Script Output

The monitoring script provides comprehensive test results:

```
Vault Multi-Namespace Test Results
┌─────────────┬──────────────┬─────────────────┬──────┬───────────────┬──────────────┐
│ Namespace   │ Secret Path  │ Vault Namespace │ Auth │ Secret Access │ Overall Status│
├─────────────┼──────────────┼─────────────────┼──────┼───────────────┼──────────────┤
│ test-namespace│ test/secret1 │ vault-ns1       │ ✓    │ ✓             │ Success      │
│ test-namespace│ test/secret2 │ vault-ns2       │ ✓    │ ✓             │ Success      │
└─────────────┴──────────────┴─────────────────┴──────┴───────────────┴──────────────┘
```

## Test Data Structure

The setup script creates test secrets with the following structure:

```json
{
  "username": "test-user-{vault-namespace}",
  "password": "test-password-{vault-namespace}",
  "database": "test-db-{vault-namespace}",
  "api_key": "api-key-{vault-namespace}-{hash}"
}
```

## Error Handling

Both scripts include comprehensive error handling for:

- **Kubernetes API Errors**: Network issues, authentication failures, resource conflicts
- **Vault Authentication Errors**: Invalid tokens, network connectivity, permission issues
- **Secret Access Errors**: Invalid paths, forbidden access, missing secrets
- **Configuration Errors**: Missing required parameters, invalid formats

## Logging

Both scripts support debug logging for troubleshooting:

```bash
# Enable debug logging
python pyplayground/vault/multi_namespace_vault_monitor.py \
    --namespace "test-namespace" \
    --secret-paths "test/secret1" \
    --vault-namespaces "vault-ns1" \
    --debug
```

## Security Considerations

- **Token Security**: Use temporary tokens for setup operations
- **Data Masking**: Enable data masking in production environments
- **Access Control**: Ensure proper RBAC permissions for service accounts
- **Network Security**: Use TLS/SSL for all communications

## Troubleshooting

### Common Issues

1. **Authentication Failures**
   - Verify service account tokens are valid
   - Check Vault role configuration
   - Ensure proper namespace mapping

2. **Secret Access Failures**
   - Verify secret paths exist
   - Check Vault policies
   - Ensure proper KV mount configuration

3. **Kubernetes API Issues**
   - Verify kubeconfig is valid
   - Check RBAC permissions
   - Ensure cluster connectivity

### Debug Steps

1. Enable debug logging with `--debug`
2. Check Kubernetes service account tokens
3. Verify Vault authentication manually
4. Test secret access with Vault CLI
5. Review Vault audit logs

## Integration

These scripts integrate with the existing project utilities and follow project standards:

- **`pyplayground.utils.k8s_utils`**: Kubernetes client management, service account JWT retrieval, namespace operations
- **`pyplayground.utils.logging_utils`**: Structured logging with proper configuration
- **`pyplayground.utils.vault_utils`**: Vault client operations, secret retrieval, authentication

### Utility Functions Used

The scripts leverage existing utility functions to avoid code duplication:

- `get_k8s_client()`: Kubernetes API client initialization
- `get_service_account_jwt()`: Service account token retrieval
- `load_kube_config_auto()`: Automatic kubeconfig loading
- `create_vault_client()`: Vault client creation
- `login_with_kubernetes()`: Kubernetes authentication
- `get_secret()`: Vault secret retrieval
- `setup_logging()`: Logging configuration
- `get_logger()`: Logger instance creation

## Code Standards Compliance

These scripts follow all project coding standards:

### ✅ **Project Organization Rules**
- **Directory Structure**: Scripts properly placed in `pyplayground/vault/` directory
- **File Naming**: Using lowercase with underscores
- **Shebang and Encoding**: Proper headers (`#!/usr/bin/env python3`, `# -*- coding: utf-8 -*-`)

### ✅ **Python Standards**
- **Python Version**: Compatible with Python 3.9-3.14
- **Code Quality**: Applied black, isort, and flake8 formatting
- **Type Hints**: All function signatures have proper type hints
- **Documentation**: Comprehensive docstrings for all functions
- **Line Length**: 100 characters maximum

### ✅ **Utility Function Usage**
- **Code Reuse**: Leverages existing utility functions from `@utils` directory
- **No Duplication**: Removed duplicate functions in favor of utility functions
- **Consistent Patterns**: Uses established project patterns for logging, error handling, and client management

### ✅ **Error Handling & Logging**
- **Comprehensive Error Handling**: Robust error handling for all operations
- **Structured Logging**: Uses project logging utilities with proper configuration
- **Progress Tracking**: Visual progress indicators and detailed status reporting

## Contributing

When modifying these scripts:

1. **Follow Project Standards**: Apply black, isort, and flake8 formatting
2. **Use Utility Functions**: Leverage existing functions from `@utils` directory
3. **Add Comprehensive Error Handling**: Include proper exception handling
4. **Include Detailed Logging**: Use project logging utilities
5. **Update Documentation**: Keep README and docstrings current
6. **Test Thoroughly**: Test with multiple namespace configurations
7. **Maintain Type Hints**: Ensure all functions have proper type annotations
