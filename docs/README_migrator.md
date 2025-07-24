# Portworx Vault to Kubernetes Secrets Migrator

This script (`px_vault_to_k8s_secret_migrator.py`) provides a safe, auditable migration of Portworx volume encryption keys from HashiCorp Vault to Kubernetes Secrets.

## Overview

The migrator consumes JSON output from `k8s_px_pvc_data_exporter.py` and performs the following operations:

1. **Parse and validate** the export data
2. **Normalize secret names** to comply with Kubernetes naming requirements
3. **Create Kubernetes secrets** with the encryption keys from Vault
4. **Update Portworx volume labels** to reference the new secrets
5. **Provide comprehensive logging** for audit and troubleshooting

## Usage

### Basic Usage

```bash
python px_vault_to_k8s_secret_migrator.py --input /path/to/export.json
```

### Dry Run Mode (Recommended First Step)

```bash
python px_vault_to_k8s_secret_migrator.py --input /path/to/export.json --dry-run
```

### Full Command Line Options

```bash
python px_vault_to_k8s_secret_migrator.py \
    --input /path/to/export.json \
    --dry-run \
    --px-namespace kube-system \
    --debug
```

## Command Line Options

- `--input` (required): Path to the JSON export file from k8s_px_pvc_data_exporter.py
- `--dry-run`: Simulate all actions without making any changes (highly recommended for initial testing)
- `--px-namespace`: Namespace for Portworx and where to look for Portworx pods (default: `kube-system`)
- `--debug`: Enable debug logging for detailed troubleshooting

## Prerequisites

### Dependencies

The script requires the following Python packages:

- `click` - Command line interface
- `kubernetes` - Kubernetes Python client
- `rich` - Rich text and beautiful formatting for terminal
- Standard library modules: `json`, `logging`, `os`, `re`, `subprocess`, `sys`

### Kubernetes Access

- Valid Kubernetes configuration (kubeconfig)
- Appropriate RBAC permissions to:
  - Read PVCs and PVs
  - Create secrets in target namespaces
  - List and access pods in the Portworx namespace
  - Execute commands in Portworx pods (for pxctl operations)

### Portworx Access

- Access to Portworx pods in the specified namespace (default: `kube-system`)
- Kubernetes permissions to execute commands in Portworx pods
- Portworx cluster accessible for volume label updates via pxctl

## Input Format

The script expects JSON input with the following structure:

```json
{
  "namespace-1": [
    {
      "pvc": "pvc-name",
      "pv": "pv-name",
      "vaultpath": "/path/to/secret",
      "vaultnamespace": "vault-namespace",
      "portworxvolumeinspect_labels": {
        "SECRET_KEY": "original-secret-key",
        "SECRET_CONTEXT": "target-namespace"
      },
      "vault_data": {
        "data": {
          "encryption-key": "base64-encoded-key"
        }
      }
    }
  ]
}
```

## Secret Name Normalization

When `SECRET_KEY` contains characters invalid for Kubernetes secret names:

1. **Invalid characters** are replaced with hyphens
2. **Leading/trailing non-alphanumeric** characters are removed
3. **Multiple consecutive hyphens** are collapsed to single hyphens
4. **Names longer than 253 characters** are truncated
5. **Invalid results** fall back to using the PVC name
6. **Still invalid results** get a generic name based on the original key hash

## Kubernetes Secret Creation

For each valid PVC entry:

- **Secret name**: Normalized version of `SECRET_KEY`
- **Namespace**: Value from `SECRET_CONTEXT` label
- **Data**: Single key-value pair where:
  - Key = original `SECRET_KEY`
  - Value = first encryption key from Vault data
- **Type**: `Opaque`
- **Behavior**: Skip if secret already exists (no overwrite)

## Portworx Label Updates

Volume labels are updated if:

- Normalized secret name differs from original `SECRET_KEY`
- Labels are missing or inconsistent

Updated labels:
- `SECRET_NAME=<normalized-name>`
- `px/secret-name=<normalized-name>`

## Error Handling

The script handles errors gracefully:

- **Per-entry validation**: Invalid entries are skipped with warnings
- **Kubernetes API errors**: Logged and reported per operation
- **pxctl command failures**: Logged with full command and error details
- **Overall success tracking**: Final summary shows success/failure counts

## Logging

Comprehensive logging includes:

- **INFO level**: Progress, success/failure summaries
- **DEBUG level**: Detailed operation information (use `--debug` flag)
- **WARNING level**: Skipped entries with reasons
- **ERROR level**: Failed operations with full context

## Safety Features

1. **Dry-run mode**: Test all operations without making changes
2. **No overwrites**: Existing secrets are preserved
3. **Validation**: Input data is thoroughly validated
4. **Audit trail**: All operations are logged
5. **Graceful failure**: Individual failures don't stop the entire migration

## Migration Workflow

1. **Export data** using `k8s_px_pvc_data_exporter.py`
2. **Review export** to understand scope and identify issues
3. **Test migration** using `--dry-run` flag
4. **Review dry-run logs** to verify expected operations
5. **Execute migration** without dry-run flag
6. **Verify results** by checking created secrets and updated labels
7. **Monitor applications** for any mounting issues during PX transition

## Troubleshooting

### Common Issues

- **Missing SECRET_KEY or SECRET_CONTEXT labels**: Check Portworx volume configuration
- **Vault data errors**: Verify Vault connectivity and permissions in export data
- **Kubernetes permission errors**: Ensure proper RBAC for secret creation
- **pxctl command failures**: Check Portworx pod access and cluster connectivity

### Debug Steps

1. Run with `--debug` flag for detailed logging
2. Check the export JSON structure and content
3. Verify Kubernetes connectivity: `kubectl auth can-i create secrets`
4. Test Portworx pod access: `kubectl get pods -n <px-namespace> -l name=portworx`
5. Test pxctl access via pod: `kubectl exec -it <portworx-pod> -n <px-namespace> -- pxctl status`
6. Review individual PVC entries for missing required fields

## Integration

This script is designed to work as part of a larger Portworx migration workflow:

1. Use alongside `k8s_px_pvc_data_exporter.py` for data export
2. Coordinate with Portworx configuration changes to use Kubernetes secrets
3. Plan application restart windows for volumes using new secret references

## Security Considerations

- **Encryption keys are handled securely** (no logging of key values)
- **Dry-run mode prevents accidental changes** during testing
- **Existing secrets are never overwritten** to prevent data loss
- **Access requires appropriate Kubernetes and Portworx permissions** 