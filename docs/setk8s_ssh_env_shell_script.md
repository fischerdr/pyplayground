# setk8s_ssh_env Shell Script Documentation

## Overview

The `setk8s_ssh_env.sh` script is a shell script equivalent of the `setk8s_ssh_env` Ansible role. It provides the same functionality for configuring Kubernetes SSH environments by retrieving kubeconfig files from HashiCorp Vault.

## Purpose

This script automates the process of:

1. Parsing cluster names to extract environment and configuration information
2. Retrieving cluster configuration from an inventory service
3. Authenticating with HashiCorp Vault
4. Downloading kubeconfig files from Vault
5. Testing the kubeconfig connection to ensure it works properly

## Features

- **Cluster Name Parsing**: Automatically parses cluster names to extract user, platform, environment, region, and zone information
- **Inventory Integration**: Retrieves cluster configuration from a centralized inventory service
- **Vault Integration**: Securely retrieves kubeconfig files from HashiCorp Vault
- **Connection Testing**: Validates kubeconfig files by testing cluster connectivity
- **Comprehensive Logging**: Provides detailed logging for troubleshooting and auditing
- **Error Handling**: Robust error handling with meaningful error messages
- **Security**: Follows security best practices for handling sensitive data

## Requirements

### System Dependencies

The script requires the following tools to be installed and available in the system PATH:

- **curl**: For HTTP requests to the inventory service
- **jq**: For JSON processing and parsing
- **kubectl**: For Kubernetes cluster connectivity testing
- **vault**: HashiCorp Vault CLI for Vault operations

### Environment Setup

Ensure the following directories exist and are writable:

- `.logs/`: For script execution logs
- `tmp/`: For temporary files
- `cache/`: For cached data

## Configuration

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `CLUSTER_NAME` | Name of the cluster to configure | `user-platform-env-region-id` |
| `CLUSTER_ADM_KUBE_DIR` | Directory to store kubeconfig files | `/home/user/.kube` |

### Optional Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_TOKEN_PATH` | `/run/secrets/vault-token` | Path to Vault token file |
| `INVENTORY_URL` | `https://inventory.example.com` | Inventory service URL |
| `VAULT_PROD_ADDRESS` | `https://vault-prod.example.com` | Production Vault address |
| `VAULT_DEV_ADDRESS` | `https://vault-dev.example.com` | Development Vault address |
| `VAULT_TEST_ADDRESS` | `https://vault-test.example.com` | Test Vault address |
| `VAULT_ENG_ADDRESS` | `https://vault-eng.example.com` | Engineering Vault address |
| `VAULT_NAMESPACE` | `automation` | Vault namespace |
| `VAULT_MOUNT_POINT` | `secret` | Vault mount point |
| `CA_CERT_PATH` | `/etc/ssl/certs/ca-certificates.crt` | Path to CA certificate |
| `VALIDATE_CERTS` | `true` | Validate SSL certificates |
| `DEBUG` | `false` | Enable debug logging |

## Usage

### Basic Usage

```bash
# Set required variables
export CLUSTER_NAME="user-platform-env-region-id"
export CLUSTER_ADM_KUBE_DIR="/home/user/.kube"

# Run the script
./scripts/setk8s_ssh_env.sh
```

### Advanced Usage

```bash
# With custom Vault configuration
export CLUSTER_NAME="user-platform-env-region-id"
export CLUSTER_ADM_KUBE_DIR="/home/user/.kube"
export VAULT_TOKEN_PATH="/custom/path/token"
export VAULT_PROD_ADDRESS="https://custom-vault.example.com"
export DEBUG=true

./scripts/setk8s_ssh_env.sh
```

### Command Line Options

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help message and usage information |
| `-v, --version` | Show version information |
| `-d, --debug` | Enable debug logging |

## Cluster Name Format

The script expects cluster names to follow specific naming conventions:

### With Zone Format

```text
<cluster_user>-<platform>-<env>-<region><zone>-<id>
```

Example: `user-platform-env-regiona-123`

### Without Zone Format

```text
<cluster_user>-<platform>-<env>-<region>-<id>
```

Example: `user-platform-env-region-123`

### Environment Codes

- `p`: Production
- `t`: Test
- `d`: Development
- Other values are used as-is

### Zone Codes

- `a`, `b`, `c`: Zone identifiers

## Workflow

1. **Validation**: Validates required tools and environment variables
2. **Cluster Parsing**: Parses the cluster name to extract configuration information
3. **Inventory Lookup**: Retrieves cluster configuration from the inventory service
4. **Vault Configuration**: Sets up Vault connection parameters based on inventory or defaults
5. **Token Validation**: Reads and validates the Vault token
6. **Kubeconfig Retrieval**: Downloads the kubeconfig from Vault
7. **File Writing**: Writes the kubeconfig to the specified directory
8. **Connection Testing**: Tests the kubeconfig by connecting to the cluster

## Security Considerations

### Token Handling

- Vault tokens are read from secure file locations
- Tokens are not logged or displayed in output
- Tokens are validated before use

### File Permissions

- Kubeconfig files are created with restrictive permissions (600)
- Directory permissions are set appropriately (750)

### SSL/TLS

- SSL certificate validation is enabled by default
- Can be disabled for development environments using `VALIDATE_CERTS=false`

### Logging

- Sensitive information is not logged
- Debug logging can be enabled for troubleshooting

## Error Handling

The script includes comprehensive error handling:

- **Validation Errors**: Clear messages for missing tools or variables
- **Network Errors**: Proper handling of HTTP request failures
- **Vault Errors**: Specific error messages for Vault authentication and data retrieval
- **Kubernetes Errors**: Connection testing with meaningful error messages

## Logging Format

### Log Levels

- **INFO**: General information about script execution
- **WARN**: Warning messages for non-critical issues
- **ERROR**: Error messages for failures
- **DEBUG**: Detailed debugging information (when enabled)

### Log Location

Logs are written to `.logs/setk8s_ssh_env.sh-YYYYMMDD-HHMMSS.log`

### Log Format

```text
[LEVEL] YYYY-MM-DD HH:MM:SS - Message
```

## Examples

### Example 1: Basic Production Cluster Setup

```bash
#!/bin/bash
export CLUSTER_NAME="produser-aws-p-uswest1a-cluster1"
export CLUSTER_ADM_KUBE_DIR="/opt/kubeconfigs"
export VAULT_TOKEN_PATH="/run/secrets/vault-token"

./scripts/setk8s_ssh_env.sh
```

### Example 2: Development Cluster with Custom Vault

```bash
#!/bin/bash
export CLUSTER_NAME="devuser-gcp-d-uscentral1-devcluster"
export CLUSTER_ADM_KUBE_DIR="/home/developer/.kube"
export VAULT_TOKEN_PATH="/custom/vault/token"
export VAULT_DEV_ADDRESS="https://dev-vault.company.com"
export DEBUG=true

./scripts/setk8s_ssh_env.sh
```

### Example 3: Engineering Cluster Setup

```bash
#!/bin/bash
export CLUSTER_NAME="enguser-azure-e-europewest1-engcluster"
export CLUSTER_ADM_KUBE_DIR="/opt/eng/kubeconfigs"
export VAULT_ENG_ADDRESS="https://eng-vault.company.com"

./scripts/setk8s_ssh_env.sh
```

## Troubleshooting

### Common Issues

#### 1. Missing Dependencies

**Error**: `Missing required tools: curl jq kubectl vault`
**Solution**: Install the missing tools using your system's package manager

#### 2. Invalid Cluster Name Format

**Error**: `Invalid cluster name format`
**Solution**: Ensure the cluster name follows the expected format

#### 3. Vault Authentication Failure

**Error**: `Vault token is invalid`
**Solution**: Check that the Vault token file exists and contains a valid token

#### 4. Kubeconfig Connection Failure

**Error**: `Failed to connect to cluster using kubeconfig`
**Solution**: Verify that the kubeconfig is valid and the cluster is accessible

### Debug Mode

Enable debug mode for detailed troubleshooting:

```bash
export DEBUG=true
./scripts/setk8s_ssh_env.sh
```

### Log Analysis

Check the log file for detailed execution information:

```bash
tail -f .logs/setk8s_ssh_env.sh-*.log
```

## Integration

### CI/CD Integration

The script can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions step
- name: Setup Kubernetes Environment
  run: |
    export CLUSTER_NAME="${{ env.CLUSTER_NAME }}"
    export CLUSTER_ADM_KUBE_DIR="/tmp/kubeconfigs"
    export VAULT_TOKEN_PATH="${{ secrets.VAULT_TOKEN_PATH }}"
    ./scripts/setk8s_ssh_env.sh
```

### Ansible Integration

The script can be called from Ansible playbooks:

```yaml
- name: Setup kubeconfig using shell script
  ansible.builtin.shell: |
    export CLUSTER_NAME="{{ cluster_name }}"
    export CLUSTER_ADM_KUBE_DIR="{{ kubeconfig_dir }}"
    export VAULT_TOKEN_PATH="{{ vault_token_path }}"
    ./scripts/setk8s_ssh_env.sh
  args:
    chdir: "{{ project_root }}"
```

## Comparison with Ansible Role

| Feature | Ansible Role | Shell Script |
|---------|--------------|--------------|
| **Dependencies** | Ansible, Python, Collections | curl, jq, kubectl, vault |
| **Configuration** | YAML variables | Environment variables |
| **Error Handling** | Ansible error handling | Custom error handling |
| **Logging** | Ansible logging | Custom logging system |
| **Idempotency** | Built-in | Manual implementation |
| **Portability** | Requires Ansible | Standalone script |
| **Performance** | Overhead of Ansible | Direct execution |

## Maintenance

### Regular Updates

- Update Vault addresses as infrastructure changes
- Update default values to match current environment
- Review and update error messages for clarity

### Testing

- Test with different cluster name formats
- Verify Vault integration with different environments
- Test error handling scenarios

### Security Reviews

- Review token handling procedures
- Verify file permission settings
- Check for any sensitive data in logs

## Support

For issues or questions:

1. Check the log files for detailed error information
2. Enable debug mode for additional troubleshooting
3. Verify all dependencies are installed and accessible
4. Ensure environment variables are set correctly

## Version History

- **v1.0.0**: Initial release, equivalent to setk8s_ssh_env Ansible role
