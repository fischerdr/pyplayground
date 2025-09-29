# Vault Multi-Namespace Monitor - Ansible Implementation

## Overview

This Ansible playbook implementation provides the same functionality as the Python script `multi_namespace_vault_monitor.py` but with the benefits of infrastructure as code, better configuration management, and integration with existing Ansible workflows.

## Files Created

### Core Playbook Files
- **`playbook.yml`** - Main playbook that orchestrates the Vault testing
- **`vault_test_tasks.yml`** - Individual test tasks for each namespace/secret combination
- **`requirements.yml`** - Ansible collection dependencies
- **`inventory.yml`** - Example inventory file with variable definitions
- **`ansible.cfg`** - Ansible configuration file

### Documentation Files
- **`README.md`** - Comprehensive usage documentation
- **`COMPARISON.md`** - Detailed comparison between Python script and Ansible playbook
- **`SUMMARY.md`** - This summary document

### Utility Files
- **`run_tests.sh`** - Shell script wrapper for easy execution
- **`test_playbook.yml`** - Test playbook for validation

## Key Features

### ✅ Complete Feature Parity
- Vault authentication using Kubernetes service account JWT tokens
- Multi-namespace testing across different Vault namespaces
- Secret access testing with detailed error reporting
- Comprehensive result reporting and summary

### ✅ Additional Benefits
- **Infrastructure as Code**: Version controlled and repeatable
- **Configuration Management**: Variables, inventory, and templating
- **No Python Dependencies**: Uses Ansible's built-in modules
- **Better Integration**: Easy integration with existing Ansible workflows
- **Audit Trail**: Complete audit trail of all operations
- **Rollback Capability**: Can rollback changes if needed

## Quick Start

### 1. Install Dependencies
```bash
ansible-galaxy collection install -r requirements.yml
```

### 2. Basic Usage
```bash
ansible-playbook playbook.yml \
  -e target_namespace="production" \
  -e secret_paths="app/config,db/credentials" \
  -e vault_namespaces="prod-ns1,prod-ns2"
```

### 3. Using the Shell Script Wrapper
```bash
./run_tests.sh -n production -s "app/config,db/credentials" -v "prod-ns1,prod-ns2"
```

### 4. Using Inventory File
```bash
# Edit inventory.yml with your values
ansible-playbook -i inventory.yml playbook.yml
```

## Configuration

### Required Variables
- `target_namespace`: Kubernetes namespace to test
- `secret_paths`: Comma-separated list of secret paths
- `vault_namespaces`: Comma-separated list of Vault namespaces

### Optional Variables
- `px_namespace`: Portworx namespace (default: "portworx")
- `kubeconfig`: Path to kubeconfig file
- `debug`: Enable debug output (default: false)
- `mask_values`: Mask sensitive values (default: true)
- `k8s_verify_ssl`: Verify SSL for Kubernetes API (default: true)
- `k8s_ssl_ca_cert`: Path to CA certificate for Kubernetes API

## Prerequisites

### Required Tools
- `ansible-playbook` (Ansible 2.9+)
- `kubectl` (Kubernetes CLI)
- Access to Kubernetes cluster with Vault secrets

### Required Kubernetes Resources
- Secret `px-vault` in Portworx namespace with Vault connection info
- Service account `portworx` with valid JWT token
- Network access to Vault server

## Output Example

```
=== VAULT MULTI-NAMESPACE TEST RESULTS ===
Total tests: 3
Successful tests: 2
Failed tests: 1

| Namespace | Secret Path | Vault Namespace | Auth | Secret Access | Status |
|-----------|-------------|-----------------|------|----------------|--------|
| production | app/config | prod-ns1 | ✓ | ✓ | Success |
| production | db/credentials | prod-ns2 | ✓ | ✗ | Secret Access Failed |
| production | monitoring/alerts | monitoring-ns | ✗ | ✗ | Authentication Failed |

=== FINAL SUMMARY ===
Success Rate: 2/3 tests passed
1 test(s) failed.
```

## Testing

### Validate Playbook
```bash
ansible-playbook test_playbook.yml
```

### Syntax Check
```bash
ansible-playbook --syntax-check playbook.yml
```

### Dry Run
```bash
ansible-playbook playbook.yml --check
```

## Troubleshooting

### Common Issues
1. **Kubernetes Connection**: Verify `kubectl` access
2. **Vault Authentication**: Check `px-vault` secret and service account
3. **Secret Access**: Verify secret paths and permissions
4. **Network Connectivity**: Ensure Vault server is accessible

### Debug Mode
```bash
ansible-playbook playbook.yml -e debug=true -v
```

## Integration

### CI/CD Pipeline
```yaml
# Example GitHub Actions workflow
- name: Run Vault Tests
  run: |
    ansible-playbook -i inventory.yml playbook.yml
```

### Ansible Tower/AWX
- Import playbook into Ansible Tower
- Configure inventory and variables
- Schedule regular execution
- Set up notifications for failures

## Maintenance

### Updating Collections
```bash
ansible-galaxy collection install -r requirements.yml --force
```

### Adding New Tests
1. Modify `vault_test_tasks.yml` for new test logic
2. Update `playbook.yml` for new test orchestration
3. Update documentation

### Monitoring
- Use Ansible Tower for centralized management
- Set up monitoring and alerting
- Regular testing and validation

## Conclusion

This Ansible playbook implementation provides a robust, maintainable, and scalable solution for Vault multi-namespace monitoring. It maintains full compatibility with the original Python script while adding the benefits of infrastructure as code and better integration with existing automation workflows.

The playbook is ready for production use and can be easily integrated into existing Ansible-based automation pipelines.
