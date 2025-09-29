# Vault Multi-Namespace Monitor - Ansible Role

This Ansible role provides comprehensive Vault monitoring capabilities for testing Kubernetes authentication across multiple Vault namespaces.

## Overview

The role tests:
- Vault authentication using Kubernetes service account JWT tokens
- Access to specific Vault secrets across different Vault namespaces
- Comprehensive reporting of test results

## Requirements

### Ansible Collections
```bash
ansible-galaxy collection install kubernetes.core community.general
```

### Required Tools
- `kubectl` - Must be available in PATH
- Access to a Kubernetes cluster with Vault secrets configured
- Network access to Vault server

### Required Kubernetes Resources
- Secret named `px-vault` in the Portworx namespace containing:
  - `VAULT_ADDR`: Vault server address
  - `VAULT_BACKEND_PATH`: Vault KV backend path
  - `VAULT_AUTH_KUBERNETES_ROLE`: Kubernetes auth role
  - `VAULT_AUTH_MOUNT_PATH`: Kubernetes auth mount path
- Service account named `portworx` in the Portworx namespace with a valid token

## Role Variables

### Required Variables
- `vault_monitor_target_namespace`: Kubernetes namespace to test
- `vault_monitor_secret_paths`: Comma-separated list of secret paths to test
- `vault_monitor_vault_namespaces`: Comma-separated list of Vault namespaces to test

### Optional Variables
- `vault_monitor_px_namespace`: Portworx namespace (default: "portworx")
- `vault_monitor_kubeconfig`: Path to kubeconfig file (default: uses default lookup)
- `vault_monitor_debug`: Enable debug output (default: false)
- `vault_monitor_mask_values`: Mask sensitive values (default: true)
- `vault_monitor_k8s_verify_ssl`: Verify SSL for Kubernetes API (default: true)
- `vault_monitor_k8s_ssl_ca_cert`: Path to CA certificate for Kubernetes API

## Usage

### Basic Usage
```yaml
- hosts: localhost
  roles:
    - vault_multi_namespace_monitor
  vars:
    vault_monitor_target_namespace: "production"
    vault_monitor_secret_paths: "app/config,db/credentials"
    vault_monitor_vault_namespaces: "prod-ns1,prod-ns2"
```

### Advanced Usage
```yaml
- hosts: localhost
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

### Using with Playbook
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

## Example Playbooks

### Simple Playbook
```yaml
---
- name: Test Vault Multi-Namespace Access
  hosts: localhost
  gather_facts: false
  roles:
    - vault_multi_namespace_monitor
  vars:
    vault_monitor_target_namespace: "production"
    vault_monitor_secret_paths: "app/config,db/credentials"
    vault_monitor_vault_namespaces: "prod-ns1,prod-ns2"
```

### Advanced Playbook with Multiple Environments
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

## Output

The role provides comprehensive output including:
- Summary table of all test results
- Detailed results for each test
- Success/failure status for authentication and secret access
- Error messages for failed tests
- Final summary with success rate

### Example Output
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

## Error Handling

The role handles various error conditions:
- Missing Kubernetes secrets
- Invalid service account tokens
- Vault authentication failures
- Secret access permissions issues
- Network connectivity problems

## Dependencies

- `kubernetes.core` collection
- `community.general` collection

## License

MIT

## Author Information

Created by pyplayground team for Vault multi-namespace monitoring.
