# Vault Multi-Namespace Monitor - Ansible Playbook

This Ansible playbook is based on the Python script `multi_namespace_vault_monitor.py` and provides the same functionality for testing Vault Kubernetes authentication across multiple namespaces.

## Overview

The playbook tests:

- Vault authentication using Kubernetes service account JWT tokens
- Access to specific Vault secrets across different Vault namespaces
- Comprehensive reporting of test results

## Prerequisites

### Required Collections

Install the required Ansible collections:

```bash
ansible-galaxy collection install -r requirements.yml
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

## Usage

### Basic Usage

```bash
ansible-playbook playbook.yml \
  -e target_namespace="my-namespace" \
  -e secret_paths="secret1,secret2" \
  -e vault_namespaces="vault-ns1,vault-ns2"
```

### Advanced Usage

```bash
ansible-playbook playbook.yml \
  -e target_namespace="production" \
  -e secret_paths="app/config,db/credentials" \
  -e vault_namespaces="prod-ns1,prod-ns2" \
  -e px_namespace="portworx" \
  -e kubeconfig="/path/to/kubeconfig" \
  -e debug=true \
  -e mask_values=false \
  -e k8s_verify_ssl=true \
  -e k8s_ssl_ca_cert="/path/to/ca.crt"
```

### Using Inventory File

Create an inventory file `inventory.yml`:

```yaml
all:
  hosts:
    localhost:
      vars:
        target_namespace: "production"
        secret_paths: "app/config,db/credentials,monitoring/alerts"
        vault_namespaces: "prod-ns1,prod-ns2,monitoring-ns"
        px_namespace: "portworx"
        debug: true
        mask_values: true
```

Then run:

```bash
ansible-playbook -i inventory.yml playbook.yml
```

## Variables

### Required Variables

- `target_namespace`: Kubernetes namespace to test
- `secret_paths`: Comma-separated list of secret paths to test
- `vault_namespaces`: Comma-separated list of Vault namespaces to test

### Optional Variables

- `px_namespace`: Portworx namespace (default: "portworx")
- `kubeconfig`: Path to kubeconfig file (default: uses default lookup)
- `debug`: Enable debug output (default: false)
- `mask_values`: Mask sensitive values in output (default: true)
- `k8s_verify_ssl`: Verify SSL for Kubernetes API (default: true)
- `k8s_ssl_ca_cert`: Path to CA certificate for Kubernetes API

## Output

The playbook provides:

1. **Summary Table**: Overview of all test results
2. **Detailed Results**: Individual test results with success/failure status
3. **Error Messages**: Specific error details for failed tests
4. **Final Summary**: Overall success rate and status

### Example Output

```text
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

The playbook handles various error conditions:

- Missing Kubernetes secrets
- Invalid service account tokens
- Vault authentication failures
- Secret access permissions issues
- Network connectivity problems

## Comparison with Python Script

This Ansible playbook provides the same functionality as the original Python script with these advantages:

- **Infrastructure as Code**: Version controlled and repeatable
- **No Python Dependencies**: Uses Ansible's built-in modules
- **Better Error Handling**: Structured error reporting
- **Integration**: Easy integration with existing Ansible workflows
- **Scalability**: Can be extended with additional Ansible modules

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
ansible-playbook playbook.yml -e debug=true -v
```

## Contributing

When modifying this playbook:

1. Maintain compatibility with the original Python script functionality
2. Follow Ansible best practices
3. Update documentation for any new variables or features
4. Test with various Vault configurations

## License

This playbook follows the same license as the original Python script.
