# Vault Multi-Namespace Monitor - Ansible Role Documentation

## Overview

This Ansible role provides comprehensive Vault monitoring capabilities for testing Kubernetes authentication across multiple Vault namespaces. It's based on the original Python script `multi_namespace_vault_monitor.py` but implemented as a reusable Ansible role.

## Role Structure

```
ansible/roles/vault_multi_namespace_monitor/
├── defaults/main.yml          # Default variables
├── vars/main.yml              # Role variables
├── tasks/
│   ├── main.yml               # Main role tasks
│   └── vault_test_tasks.yml   # Individual test tasks
├── handlers/main.yml          # Role handlers
├── meta/main.yml              # Role metadata
└── README.md                  # Role documentation
```

## Key Features

### ✅ Complete Feature Parity
- Vault authentication using Kubernetes service account JWT tokens
- Multi-namespace testing across different Vault namespaces
- Secret access testing with detailed error reporting
- Comprehensive result reporting and summary

### ✅ Role Benefits
- **Reusability**: Can be used in multiple playbooks
- **Modularity**: Clean separation of concerns
- **Configuration**: Flexible variable-based configuration
- **Integration**: Easy integration with existing Ansible workflows
- **Maintainability**: Well-structured and documented

## Usage Examples

### 1. Basic Role Usage

```yaml
---
- name: Vault Multi-Namespace Monitoring
  hosts: localhost
  gather_facts: false
  roles:
    - vault_multi_namespace_monitor
  vars:
    vault_monitor_target_namespace: "production"
    vault_monitor_secret_paths: "app/config,db/credentials"
    vault_monitor_vault_namespaces: "prod-ns1,prod-ns2"
```

### 2. Advanced Role Usage

```yaml
---
- name: Vault Multi-Namespace Monitoring
  hosts: localhost
  gather_facts: false
  roles:
    - vault_multi_namespace_monitor
  vars:
    vault_monitor_target_namespace: "production"
    vault_monitor_secret_paths: "app/config,db/credentials,monitoring/alerts"
    vault_monitor_vault_namespaces: "prod-ns1,prod-ns2,monitoring-ns"
    vault_monitor_px_namespace: "portworx"
    vault_monitor_debug: true
    vault_monitor_mask_values: false
    vault_monitor_k8s_verify_ssl: true
```

### 3. Using with Inventory

```yaml
---
- name: Vault Multi-Namespace Monitoring
  hosts: localhost
  gather_facts: false
  roles:
    - vault_multi_namespace_monitor
  vars:
    vault_monitor_target_namespace: "{{ target_namespace }}"
    vault_monitor_secret_paths: "{{ secret_paths }}"
    vault_monitor_vault_namespaces: "{{ vault_namespaces }}"
```

### 4. Multiple Environment Testing

```yaml
---
- name: Vault Monitoring for All Environments
  hosts: localhost
  gather_facts: false
  roles:
    - vault_multi_namespace_monitor
  vars:
    vault_monitor_target_namespace: "{{ env }}"
    vault_monitor_secret_paths: "{{ secret_paths }}"
    vault_monitor_vault_namespaces: "{{ vault_namespaces }}"
    vault_monitor_debug: "{{ debug | default(false) }}"
  loop:
    - env: "production"
      secret_paths: "app/config,db/credentials"
      vault_namespaces: "prod-ns1,prod-ns2"
    - env: "staging"
      secret_paths: "app/config"
      vault_namespaces: "staging-ns"
```

## Role Variables

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `vault_monitor_target_namespace` | Kubernetes namespace to test | `"production"` |
| `vault_monitor_secret_paths` | Comma-separated list of secret paths | `"app/config,db/credentials"` |
| `vault_monitor_vault_namespaces` | Comma-separated list of Vault namespaces | `"prod-ns1,prod-ns2"` |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `vault_monitor_px_namespace` | `"portworx"` | Portworx namespace |
| `vault_monitor_kubeconfig` | `""` | Path to kubeconfig file |
| `vault_monitor_debug` | `false` | Enable debug output |
| `vault_monitor_mask_values` | `true` | Mask sensitive values |
| `vault_monitor_k8s_verify_ssl` | `true` | Verify SSL for Kubernetes API |
| `vault_monitor_k8s_ssl_ca_cert` | `""` | Path to CA certificate |

### Internal Variables

| Variable | Description |
|----------|-------------|
| `vault_monitor_test_results` | List of test results |
| `vault_monitor_vault_conn_info` | Vault connection information |
| `vault_monitor_sa_jwt` | Service account JWT token |

## Role Tasks

### Main Tasks (`tasks/main.yml`)

1. **Validate required variables** - Ensures all required variables are set
2. **Parse input lists** - Converts comma-separated strings to lists
3. **Validate list lengths** - Ensures secret paths and vault namespaces match
4. **Get Vault connection info** - Retrieves Vault configuration from Kubernetes secret
5. **Get service account JWT** - Retrieves JWT token for authentication
6. **Run Vault tests** - Executes tests for each namespace/secret combination
7. **Display results** - Shows comprehensive test results and summary

### Test Tasks (`tasks/vault_test_tasks.yml`)

1. **Initialize test result** - Sets up result structure for each test
2. **Test Vault authentication** - Authenticates with Vault using Kubernetes auth
3. **Test secret access** - Attempts to read secrets from Vault
4. **Update results** - Records success/failure status and error messages

## Output Examples

### Summary Table
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
```

### Final Summary
```
=== FINAL SUMMARY ===
Success Rate: 2/3 tests passed
1 test(s) failed.
```

## Error Handling

The role handles various error conditions:

- **Missing Kubernetes secrets** - Fails with clear error message
- **Invalid service account tokens** - Reports authentication failures
- **Vault authentication failures** - Captures and reports auth errors
- **Secret access permissions issues** - Reports permission denied errors
- **Network connectivity problems** - Handles connection timeouts and failures

## Integration Examples

### 1. CI/CD Pipeline Integration

```yaml
# .github/workflows/vault-monitoring.yml
name: Vault Monitoring
on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM
  workflow_dispatch:

jobs:
  vault-monitoring:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run Vault Monitoring
        run: |
          ansible-playbook playbook_vault_monitor.yml \
            -e target_namespace="production" \
            -e secret_paths="app/config,db/credentials" \
            -e vault_namespaces="prod-ns1,prod-ns2"
```

### 2. Ansible Tower/AWX Integration

```yaml
# tower_job_template.yml
---
- name: Vault Multi-Namespace Monitoring
  hosts: localhost
  gather_facts: false
  roles:
    - vault_multi_namespace_monitor
  vars:
    vault_monitor_target_namespace: "{{ target_namespace }}"
    vault_monitor_secret_paths: "{{ secret_paths }}"
    vault_monitor_vault_namespaces: "{{ vault_namespaces }}"
    vault_monitor_debug: "{{ debug | default(false) }}"
```

### 3. Multi-Environment Testing

```yaml
---
- name: Vault Monitoring for All Environments
  hosts: localhost
  gather_facts: false
  roles:
    - vault_multi_namespace_monitor
  vars:
    vault_monitor_target_namespace: "{{ env }}"
    vault_monitor_secret_paths: "{{ secret_paths }}"
    vault_monitor_vault_namespaces: "{{ vault_namespaces }}"
    vault_monitor_debug: "{{ debug | default(false) }}"
  loop:
    - env: "production"
      secret_paths: "app/config,db/credentials,monitoring/alerts"
      vault_namespaces: "prod-ns1,prod-ns2,monitoring-ns"
    - env: "staging"
      secret_paths: "app/config,db/credentials"
      vault_namespaces: "staging-ns1,staging-ns2"
    - env: "development"
      secret_paths: "app/config"
      vault_namespaces: "dev-ns"
```

## Best Practices

### 1. Variable Naming
- Use descriptive variable names with the `vault_monitor_` prefix
- Group related variables together
- Provide clear default values

### 2. Error Handling
- Use `failed_when: false` for non-critical operations
- Provide meaningful error messages
- Handle edge cases gracefully

### 3. Performance
- Use `gather_facts: false` when not needed
- Minimize API calls where possible
- Use efficient data structures

### 4. Security
- Mask sensitive values by default
- Use secure defaults for SSL verification
- Handle credentials securely

## Troubleshooting

### Common Issues

1. **Kubernetes Connection Issues**
   - Verify `kubectl` is working: `kubectl get pods`
   - Check kubeconfig path and permissions
   - Ensure SSL certificates are valid

2. **Vault Authentication Issues**
   - Verify the `px-vault` secret exists and contains all required keys
   - Check that the service account has proper permissions
   - Ensure Vault server is accessible from the Ansible controller

3. **Secret Access Issues**
   - Verify secret paths exist in Vault
   - Check that the authenticated role has permissions to read the secrets
   - Ensure Vault namespaces are correctly configured

### Debug Mode
Enable debug mode for detailed output:
```bash
ansible-playbook playbook_vault_monitor.yml -e debug=true -v
```

## Migration from Playbook

If you're migrating from the standalone playbook to the role:

1. **Install the role**:
   ```bash
   ansible-galaxy install -r requirements.yml
   ```

2. **Update your playbooks**:
   ```yaml
   - hosts: localhost
     roles:
       - vault_multi_namespace_monitor
     vars:
       vault_monitor_target_namespace: "{{ target_namespace }}"
       vault_monitor_secret_paths: "{{ secret_paths }}"
       vault_monitor_vault_namespaces: "{{ vault_namespaces }}"
   ```

3. **Update variable names**:
   - `target_namespace` → `vault_monitor_target_namespace`
   - `secret_paths` → `vault_monitor_secret_paths`
   - `vault_namespaces` → `vault_monitor_vault_namespaces`
   - etc.

## Conclusion

The `vault_multi_namespace_monitor` role provides a robust, maintainable, and scalable solution for Vault multi-namespace monitoring. It maintains full compatibility with the original Python script while adding the benefits of Ansible role-based architecture.

The role is ready for production use and can be easily integrated into existing Ansible-based automation pipelines.
