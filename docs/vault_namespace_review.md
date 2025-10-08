# Vault Namespace Review Script

This script provides a comprehensive review of Vault Enterprise namespaces, including policies, groups, and authentication methods. It uses the existing `logging_utils.py` and `vault_utils.py` utilities from the pyplayground project.

## Features

- **Authentication & Connection**: Token-based authentication using environment variables
- **Policy Review**: List and retrieve details for all policies in the namespace
- **Group Review**: List and retrieve details for all identity groups in the namespace
- **Auth Method Review**: List and retrieve details for all enabled authentication methods
- **Structured Output**: JSON format output for easy integration with other tools
- **Comprehensive Logging**: Uses the project's logging utilities for detailed logging
- **Error Handling**: Robust error handling with detailed error reporting

## Prerequisites

- Python 3.9+
- `hvac` library
- Access to a Vault Enterprise cluster
- Valid Vault token with appropriate permissions

## Required Permissions

The scripts require specific Vault permissions to access system APIs and identity information. The token must have the following capabilities:

### System API Permissions

```hcl
# For listing and reading policies
path "sys/policies/*" {
  capabilities = ["read", "list"]
}

# For listing and reading auth methods
path "sys/auth" {
  capabilities = ["read", "list"]
}

# For reading namespace information (if available)
path "sys/namespaces/*" {
  capabilities = ["read", "list"]
}
```

### Identity API Permissions

```hcl
# For listing and reading identity groups
path "identity/group/*" {
  capabilities = ["read", "list"]
}

# For listing and reading identity entities (if needed)
path "identity/entity/*" {
  capabilities = ["read", "list"]
}
```

### Complete Policy Example

```hcl
# Vault Namespace Review Policy
path "sys/policies/*" {
  capabilities = ["read", "list"]
}

path "sys/auth" {
  capabilities = ["read", "list"]
}

path "sys/namespaces/*" {
  capabilities = ["read", "list"]
}

path "identity/group/*" {
  capabilities = ["read", "list"]
}

path "identity/entity/*" {
  capabilities = ["read", "list"]
}
```

### Testing Permissions

You can verify your token has the required permissions by running:

```bash
# Test policy access
vault policy list

# Test auth method access  
vault auth list

# Test identity access
vault identity group list
```

## Installation

1. Ensure you have the required dependencies:

   ```bash
   pip install hvac
   ```

2. Set up your environment variables:

   ```bash
   export VAULT_ADDR="https://your-vault-server:8200"
   export VAULT_TOKEN="your-vault-token"
   export VAULT_NAMESPACE="your-default-namespace"  # Optional
   ```

## Usage

### Basic Usage

```bash
# Review the root namespace
python vault_namespace_review.py

# Review a specific namespace
python vault_namespace_review.py --namespace "my-namespace"

# Enable debug logging
python vault_namespace_review.py --namespace "my-namespace" --debug

# Save output to a file
python vault_namespace_review.py --namespace "my-namespace" --output results.json
```

### Command Line Options

- `--namespace`: Vault namespace to review (defaults to VAULT_NAMESPACE env var, then 'root')
- `--debug`: Enable debug logging
- `--output`: Output file for JSON results (defaults to stdout)

### Environment Variables

- `VAULT_ADDR`: Vault server address (required)
- `VAULT_TOKEN`: Vault authentication token (required)
- `VAULT_NAMESPACE`: Default namespace (optional, can be overridden by --namespace)

## Output Format

The script outputs structured JSON data with the following structure:

```json
{
  "namespace_info": {
    "name": "namespace-name",
    "timestamp": "2024-01-01T12:00:00",
    "errors": []
  },
  "policies": {
    "policies": [
      {
        "name": "policy-name",
        "rules": "policy-rules-hcl",
        "type": "policy-type"
      }
    ],
    "errors": []
  },
  "groups": {
    "groups": [
      {
        "id": "group-id",
        "name": "group-name",
        "type": "group-type",
        "member_entity_ids": ["entity1", "entity2"],
        "member_group_ids": ["group1", "group2"],
        "policies": ["policy1", "policy2"],
        "metadata": {}
      }
    ],
    "errors": []
  },@
  "auth_methods": {
    "auth_methods": [
      {
        "path": "auth/path",
        "type": "auth-type",
        "description": "auth-description",
        "accessor": "auth-accessor",
        "config": {}
      }
    ],
    "errors": []
  },
  "summary": {
    "total_policies": 5,
    "total_groups": 3,
    "total_auth_methods": 2,
    "errors": []
  }
}
```

## Testing

Use the included test script to verify functionality:

```bash
# Test with default settings
python test_vault_namespace_review.py

# Test with specific namespace
python test_vault_namespace_review.py --namespace "my-namespace"

# Test with debug logging
python test_vault_namespace_review.py --debug

# Test and save results
python test_vault_namespace_review.py --output test_results.json
```

## Implementation Details

The script uses the following key components:

- **hvac library**: For Vault API interactions
- **vault_utils.py**: For Vault client creation and authentication
- **logging_utils.py**: For consistent logging across the project
- **argparse**: For command-line argument parsing
- **JSON output**: For structured data that can be piped to other tools

### Key Functions

- `perform_namespace_review()`: Main function that orchestrates the review process
- `get_policies()`: Retrieves and analyzes all policies in the namespace
- `get_groups()`: Retrieves and analyzes all identity groups in the namespace
- `get_auth_methods()`: Retrieves and analyzes all authentication methods in the namespace
- `get_namespace_info()`: Retrieves basic namespace information

## Error Handling

The script includes comprehensive error handling:

- **Authentication Errors**: Invalid tokens, connection failures
- **Permission Errors**: Insufficient permissions for specific operations
- **API Errors**: Unavailable APIs or malformed responses
- **Namespace Errors**: Invalid or non-existent namespaces

All errors are logged and included in the output JSON for review.

## Logging

The script uses the project's `logging_utils.py` for consistent logging:

- **Console Output**: WARNING level and above (errors and warnings)
- **File Output**: INFO level and above (detailed information)
- **Debug Mode**: DEBUG level for troubleshooting

Log files are created in the `logs/` directory with timestamps.

## Integration Examples

### Pipeline Integration

```bash
# Pipe output to jq for filtering
python vault_namespace_review.py --namespace "prod" | jq '.policies.policies[].name'

# Save and analyze results
python vault_namespace_review.py --namespace "prod" --output prod_review.json
jq '.summary' prod_review.json
```

### Script Integration

```python
from vault_namespace_review import perform_namespace_review

# Perform review programmatically
results = perform_namespace_review("my-namespace", debug=False)

# Process results
for policy in results["policies"]["policies"]:
    print(f"Policy: {policy['name']}")
```

## Security Considerations

- **Token Security**: Store Vault tokens securely and rotate regularly
- **Network Security**: Use HTTPS for Vault connections
- **Permission Principle**: Use tokens with minimal required permissions
- **Output Security**: Be careful with JSON output as it may contain sensitive information

### Permission Security Best Practices

- **Least Privilege**: Only grant the minimum permissions needed for namespace review
- **Namespace Isolation**: Ensure tokens can only access intended namespaces
- **Audit Logging**: Monitor access to sensitive system APIs
- **Token Expiration**: Use short-lived tokens for review operations
- **Policy Review**: Regularly audit token policies to ensure they haven't been over-privileged

## Troubleshooting

### Common Issues

1. **Authentication Failed**
   - Verify VAULT_ADDR is correct
   - Check VAULT_TOKEN is valid and not expired
   - Ensure token has appropriate permissions

2. **Namespace Not Found**
   - Verify namespace exists
   - Check token has access to the namespace
   - Use 'root' for the root namespace

3. **Permission Denied**
   - Token may not have sufficient permissions
   - Check token policies for required capabilities
   - Some operations may require admin privileges

### Permission-Specific Issues

1. **Missing System Permissions**
   - **Error**: `403 Forbidden` when trying to list policies
   - **Solution**: Add `sys/policies/*` with `read` and `list` capabilities

2. **Missing Identity Permissions**
   - **Error**: `403 Forbidden` when trying to list groups
   - **Solution**: Add `identity/group/*` with `read` and `list` capabilities

3. **Namespace-Specific Permissions**
   - **Error**: Can't access namespace information
   - **Solution**: Ensure the token has permissions in the target namespace, not just the parent

### Debug Mode

Enable debug logging for detailed troubleshooting:

```bash
python vault_namespace_review.py --namespace "my-namespace" --debug
```

This will provide detailed API calls, responses, and error information.

## Contributing

When contributing to this script:

1. Follow the existing code style and patterns
2. Use the project's logging utilities
3. Add appropriate error handling
4. Include type hints
5. Update this documentation

## License

This script is part of the pyplayground project and follows the same licensing terms.
