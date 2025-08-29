# Enhanced Vault Debug Logging Examples

This document demonstrates the enhanced debug logging that has been added to the Vault namespace review scripts. When debug mode is enabled (`--debug` flag or `VAULT_DEBUG=true`), the scripts now provide comprehensive logging information.

## Enhanced Logging Features

### 1. Policy Retrieval and Analysis

When retrieving policies, debug mode now shows:

```text
DEBUG: Starting policy retrieval process...
DEBUG: Vault client namespace: root
DEBUG: Vault client URL: http://vault:8200
DEBUG: Calling client.sys.list_policies()...
DEBUG: Raw policies response: {'data': {'policies': ['default', 'root', 'app-policy']}}
DEBUG: Policy names: ['default', 'root', 'app-policy']
DEBUG: Retrieving policy 1/3: 'default'
DEBUG: Raw policy response for 'default': {'data': {'rules': 'path "secret/*" {\n  capabilities = ["read"]\n}', 'type': 'acl'}}
DEBUG: Policy 'default' details:
DEBUG:   - Type: acl
DEBUG:   - Rules length: 45 characters
DEBUG:   - Rules content preview: path "secret/*" {
  capabilities = ["read"]
}...
DEBUG:   - Policy analysis for 'default':
DEBUG:     * Capabilities statements: 1
DEBUG:     * Path statements: 1
DEBUG:     * Secret path references: 1
DEBUG:     * Deny statements: 0
DEBUG: Successfully processed policy 'default'
```

### 2. Group/Role Retrieval and Analysis

When retrieving groups, debug mode shows:

```text
DEBUG: Starting identity groups retrieval process...
DEBUG: Vault client namespace: root
DEBUG: Vault client URL: http://vault:8200
DEBUG: Calling client.identity.list_groups()...
DEBUG: Raw groups response: {'data': {'keys': ['group-123', 'admin-group-456']}}
DEBUG: Group IDs: ['group-123', 'admin-group-456']
DEBUG: Retrieving group 1/2: 'group-123'
DEBUG: Raw group response for 'group-123': {'data': {'name': 'developers', 'type': 'internal', 'policies': ['app-policy', 'read-policy']}}
DEBUG: Group 'developers' (ID: group-123) details:
DEBUG:   - Type: internal
DEBUG:   - Member entities: 3 (['entity-1', 'entity-2', 'entity-3'])
DEBUG:   - Member groups: 0 ([])
DEBUG:   - Assigned policies: 2 (['app-policy', 'read-policy'])
DEBUG:   - Metadata keys: ['team', 'environment']
DEBUG:   - Metadata content: {'team': 'backend', 'environment': 'production'}
DEBUG: Successfully processed group 'developers' (ID: group-123)
```

### 3. Authentication Methods Analysis

When retrieving auth methods, debug mode shows:

```text
DEBUG: Starting authentication methods retrieval process...
DEBUG: Vault client namespace: root
DEBUG: Vault client URL: http://vault:8200
DEBUG: Calling client.sys.list_auth_methods()...
DEBUG: Raw auth methods response: {'data': {'token/': {'type': 'token'}, 'kubernetes/': {'type': 'kubernetes'}}}
DEBUG: Auth method paths: ['token/', 'kubernetes/']
DEBUG: Processing auth method 1/2: 'token/'
DEBUG: Auth method 'token/' details:
DEBUG:   - Type: token
DEBUG:   - Description: token based credentials
DEBUG:   - Accessor: auth_token_abc123
DEBUG:   - Config keys: ['default_lease_ttl', 'max_lease_ttl']
DEBUG:   - Configuration details:
DEBUG:     * default_lease_ttl: 768h
DEBUG:     * max_lease_ttl: 768h
DEBUG:   - Auth method analysis for 'token/':
DEBUG:     * Token auth method - check for proper token policies
DEBUG:     * NOTICE: Auth method 'token/' uses default mount path
DEBUG: Successfully processed auth method 'token/' (Type: token)
```

### 4. Authentication Role Bindings Analysis

When retrieving role bindings for auth methods, debug mode shows:

```text
DEBUG: Starting authentication role bindings retrieval process...
DEBUG: Processing 2 auth methods for role bindings
DEBUG: Retrieving role bindings for auth method: 'kubernetes/' (type: kubernetes)
DEBUG: Retrieving Kubernetes roles for auth path: kubernetes/
DEBUG: Raw Kubernetes roles list response: {'data': {'keys': ['webapp-role', 'api-role']}}
DEBUG: Found 2 Kubernetes roles: ['webapp-role', 'api-role']
DEBUG: Raw Kubernetes role response for 'webapp-role': {'data': {'bound_service_account_names': ['webapp'], 'bound_service_account_namespaces': ['default'], 'token_policies': ['webapp-policy']}}
DEBUG: Kubernetes role 'webapp-role' details:
DEBUG:   - Bound service accounts: ['webapp']
DEBUG:   - Bound namespaces: ['default']
DEBUG:   - Token policies: ['webapp-policy']
DEBUG:   - Token TTL: 3600
DEBUG:   - Token Max TTL: 7200
DEBUG:   - Audience: vault
DEBUG: Role binding retrieval completed for auth method 'kubernetes/': 2 roles found
DEBUG: Role bindings retrieval completed. Total roles across all auth methods: 2, Errors: 0
```

### 6. Token Information Analysis

When analyzing tokens, debug mode shows:

```text
DEBUG: Starting token information retrieval...
DEBUG: Current token (redacted): hvs.....abc1
DEBUG: Calling client.token.lookup_self()...
DEBUG: Token information details:
DEBUG:   - Accessor: hmac-sha256:abc123def456
DEBUG:   - Creation time: 2024-01-15T10:30:00Z
DEBUG:   - Creation TTL: 768h
DEBUG:   - Display name: kubernetes-vault-auth
DEBUG:   - Entity ID: entity-abc123
DEBUG:   - Expire time: 2024-02-15T10:30:00Z
DEBUG:   - Policies: ['default', 'app-policy']
DEBUG:   - Renewable: true
DEBUG:   - TTL: 720h
DEBUG:   - Type: service
DEBUG:   - Metadata: {'service_account_name': 'vault-auth', 'namespace': 'default'}
DEBUG:     * Service token - long-lived, suitable for applications
```

### 7. Authentication Process Logging

When authenticating with Kubernetes, debug mode shows:

```text
DEBUG: Attempting Kubernetes authentication...
DEBUG: Kubernetes authentication successful - detailed response:
DEBUG:   - Token accessor: hmac-sha256:abc123def456
DEBUG:   - Token policies: ['default', 'app-policy']
DEBUG:   - Token metadata: {'service_account_name': 'vault-auth', 'namespace': 'default'}
DEBUG:   - Token lease duration: 768h
DEBUG:   - Token renewable: true
DEBUG:   - Token entity_id: entity-abc123
DEBUG:   - Token client_token: hvs.....xyz9
DEBUG: Decoded JWT Payload Claims: {'iss': 'kubernetes/serviceaccount', 'sub': 'system:serviceaccount:default:vault-auth'}
```

### 8. Comprehensive Review Summary

At the end of the review, debug mode provides a detailed summary:

```text
DEBUG: === NAMESPACE REVIEW SUMMARY ===
DEBUG: Namespace: root
DEBUG: Total policies: 15
DEBUG: Total groups: 8
DEBUG: Total auth methods: 3
DEBUG: Total role bindings: 12
DEBUG: Total errors: 0
DEBUG: No errors encountered during review
DEBUG: === NAMESPACE REVIEW PROCESS COMPLETED ===
```

## Security Analysis Features

The enhanced logging includes automatic security analysis:

- **Policy Analysis**: Detects deny rules, admin privileges, wildcard permissions
- **Group Analysis**: Identifies groups without policies, nested group relationships
- **Auth Method Analysis**: Provides specific guidance for each auth method type
- **Role Binding Analysis**: Reviews authentication roles, service account bindings, policy assignments
- **Token Analysis**: Warns about root tokens, expiration times, and policy assignments

## Usage

To enable enhanced debug logging:

```bash
# Using command line flag
python -m pyplayground.test_vault_namespace_review --namespace root --debug

# Using environment variable
export VAULT_DEBUG=true
python -m pyplayground.test_vault_namespace_review --namespace root

# Using environment variable in .env file
echo "VAULT_DEBUG=true" >> .env
python -m pyplayground.test_vault_namespace_review --namespace root
```

## Benefits

1. **Troubleshooting**: Detailed API responses help diagnose connection and permission issues
2. **Security Auditing**: Automatic analysis highlights potential security concerns
3. **Performance Monitoring**: Progress indicators show which operations are slow
4. **Configuration Validation**: Detailed configuration logging helps verify settings
5. **Role Binding Auditing**: Complete visibility into auth method role configurations and policy assignments
6. **Error Diagnosis**: Enhanced exception logging with full context for debugging
