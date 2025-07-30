# Tower to AAP Credential Migration Tools

This directory contains tools for migrating encrypted credentials from Ansible Tower to Red Hat Ansible Automation Platform (AAP).

## Overview

The migration process consists of two scripts:

1. **`tower_credential_migrator.py`** - Extracts and decrypts credentials from Tower
2. **`aap_credential_importer.py`** - Imports credentials into AAP using the REST API

## Why These Tools Are Needed

Standard Tower export/import tools cannot handle encrypted credential data because:

- Tower/AAP APIs intentionally mask encrypted fields for security (`"$encrypted$"`)
- Direct database access is required to retrieve the encrypted data
- Tower's `SECRET_KEY` is needed to decrypt the credentials
- AAP must re-encrypt using its own `SECRET_KEY`

## Architecture

```text
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│   Tower Instance    │    │   Export File       │    │   AAP Instance      │
│                     │    │                     │    │                     │
│ ┌─────────────────┐ │    │ ┌─────────────────┐ │    │ ┌─────────────────┐ │
│ │ Encrypted       │ │───▶│ │ Decrypted       │ │───▶│ │ Re-encrypted    │ │
│ │ Credentials     │ │    │ │ Credentials     │ │    │ │ Credentials     │ │
│ │ (Database)      │ │    │ │ (JSON)          │ │    │ │ (via API)       │ │
│ └─────────────────┘ │    │ └─────────────────┘ │    │ └─────────────────┘ │
│                     │    │                     │    │                     │
│ SECRET_KEY_TOWER    │    │  Secure Transfer    │    │ SECRET_KEY_AAP      │
└─────────────────────┘    └─────────────────────┘    └─────────────────────┘
```

## Script 1: Tower Credential Extractor

### Purpose

Extracts and decrypts all credentials from a Tower instance for migration.

### Requirements

- Must run on the **source Tower instance**
- Requires **root privileges** to access `SECRET_KEY`
- Direct database access to Tower's PostgreSQL database

### Usage

```bash
# Run on Tower instance as root
sudo python tower_credential_migrator.py

# With custom options
sudo python tower_credential_migrator.py \
    --tower-host db.example.com \
    --tower-password mypass \
    --output-file my_credentials.json

# Dry run to test
sudo python tower_credential_migrator.py --dry-run
```

### Features

- **Automatic SECRET_KEY discovery** from `/etc/tower/conf.d/`
- **Credential type extraction** - Exports custom credential type definitions
- **Database connection with retry logic**
- **Progress bars** and rich console output
- **Secure file permissions** (600) on export file
- **Comprehensive error handling** and logging
- **Credential validation** and summary display

### Output

Creates a JSON file with decrypted credential data and credential types:

```json
{
  "metadata": {
    "export_date": "2024-01-15T10:30:00",
    "total_credentials": 25,
    "total_credential_types": 8,
    "export_tool": "tower_credential_migrator",
    "version": "2.0"
  },
  "credential_types": [
    {
      "id": 15,
      "name": "Custom API Key",
      "description": "Custom credential type for API keys",
      "kind": "cloud",
      "namespace": "my_org",
      "managed": false,
      "inputs": {
        "fields": [
          {"id": "api_key", "label": "API Key", "type": "string", "secret": true}
        ]
      },
      "injectors": {
        "extra_vars": {
          "custom_api_key": "{{ api_key }}"
        }
      }
    }
  ],
  "credentials": [
    {
      "id": 1,
      "name": "Production SSH Key",
      "credential_type_name": "Machine",
      "inputs": {
        "username": "ansible",
        "ssh_private_key": "-----BEGIN RSA PRIVATE KEY-----\n...",
        "become_password": "decrypted_sudo_password"
      }
    }
  ]
}
```

## Script 2: AAP Credential Importer

### Purpose of AAP Credential Importer

Imports decrypted credentials into AAP using the REST API.

### Requirements for AAP Credential Importer

- Network access to target AAP instance
- AAP admin credentials
- Exported credentials JSON file

### Usage of AAP Credential Importer

```bash
# Basic import
python aap_credential_importer.py \
    --aap-url https://aap.example.com \
    --aap-username admin \
    --credentials-file tower_credentials_export.json

# With SSL verification disabled
python aap_credential_importer.py \
    --aap-url https://aap.example.com \
    --aap-username admin \
    --credentials-file credentials.json \
    --no-verify-ssl

# Dry run to validate
python aap_credential_importer.py \
    --aap-url https://aap.example.com \
    --aap-username admin \
    --credentials-file credentials.json \
    --dry-run
```

### Features of AAP Credential Importer

- **REST API-based import** - lets AAP handle encryption
- **Credential type creation** - creates missing custom credential types first
- **Improved type mapping** - uses name-based mapping instead of unreliable ID mapping
- **Organization mapping** - preserves organizational structure
- **Duplicate detection** - skips existing credentials and credential types
- **Batch processing** with progress tracking
- **Comprehensive validation** and error reporting
- **Retry logic** for API calls

## Migration Process of AAP Credential Importer

### Step 1: Extract from Tower

```bash
# On Tower instance
sudo python tower_credential_migrator.py \
    --output-file /tmp/tower_credentials.json
```

### Step 2: Secure Transfer

```bash
# Copy file to AAP-accessible machine
scp /tmp/tower_credentials.json admin@migration-host:/secure/path/
```

### Step 3: Import to AAP

```bash
# On machine with AAP access
python aap_credential_importer.py \
    --aap-url https://new-aap.example.com \
    --aap-username admin \
    --credentials-file /secure/path/tower_credentials.json
```

## Security Considerations of AAP Credential Importer

### Export File Security of AAP Credential Importer

- Export files contain **decrypted credentials**
- Files have restrictive permissions (600)
- **Delete export files** after successful import
- Use secure transfer methods (SCP, encrypted storage)

### Network Security of AAP Credential Importer

- Use HTTPS for AAP connections
- Consider VPN/private networks for API access
- Validate SSL certificates in production

### Access Controls of AAP Credential Importer

- Tower extraction requires root access
- AAP import requires admin privileges
- Use dedicated service accounts when possible

## Credential Type Mapping of AAP Credential Importer

The importer automatically maps Tower credential types to AAP equivalents:

| Tower Type | AAP Type |
|------------|----------|
| Machine | Machine |
| SSH | Machine |
| SCM | Source Control |
| AWS | Amazon Web Services |
| GCE | Google Compute Engine |
| Azure | Microsoft Azure |
| VMware | VMware vCenter |
| OpenStack | OpenStack |
| Vault | Vault |

## Error Handling of AAP Credential Importer

### Common Issues and Solutions of AAP Credential Importer

#### Could not auto-discover SECRET_KEY"

- Verify running as root
- Check `/etc/tower/conf.d/secrets.py` exists
- Manually provide `--secret-key` parameter

#### Database connection failed

- Verify database connection parameters
- Check network connectivity
- Ensure database user has read permissions

#### Unsupported credential type

- Check credential type mapping
- Verify credential type exists in target AAP
- Update type mapping if needed

#### AAP API authentication failed

- Verify AAP credentials
- Check AAP URL and connectivity
- Ensure user has admin privileges

## Dependencies of AAP Credential Importer

### Python Packages of AAP Credential Importer

```bash
pip install click rich psycopg2-binary cryptography requests
```

### System Requirements of AAP Credential Importer

- Python 3.9+
- PostgreSQL client libraries
- Network access to databases and APIs

## Logging of AAP Credential Importer

Both scripts provide comprehensive logging:

- **INFO level**: Progress and success messages  
- **DEBUG level**: Detailed operation information
- **ERROR level**: Failure details and stack traces

Use `--debug` flag for troubleshooting.

## Validation

### Pre-Migration Checks

1. **Database connectivity** to Tower instance
2. **SECRET_KEY accessibility** on Tower host  
3. **AAP API connectivity** and authentication
4. **Credential type compatibility** between instances

### Post-Migration Verification

1. **Credential count** matches between Tower and AAP
2. **Credential types** are correctly mapped
3. **Test sample credentials** in AAP job templates
4. **Verify encrypted fields** are accessible in AAP

## Troubleshooting

### Debug Mode

Enable debug logging for detailed information:

```bash
python tower_credential_migrator.py --debug
python aap_credential_importer.py --debug
```

### Dry Run Mode

Test operations without making changes:

```bash
python tower_credential_migrator.py --dry-run
python aap_credential_importer.py --dry-run
```

### Manual Verification

Query credentials directly in AAP:

```bash
curl -k -u admin:password https://aap.example.com/api/v2/credentials/
```

## Best Practices

1. **Test in non-production** environment first
2. **Backup AAP database** before import
3. **Validate sample credentials** after import
4. **Delete export files** after successful migration
5. **Document any custom mappings** required
6. **Plan for credential rotation** post-migration

## Support

For issues related to these migration tools:

1. Check logs with `--debug` flag
2. Verify all prerequisites are met
3. Test with `--dry-run` mode first
4. Consult error handling section above

## References

- [Ansible Tower Documentation](https://docs.ansible.com/ansible-tower/)
- [AAP REST API Guide](https://docs.ansible.com/automation-controller/latest/html/controllerapi/)
- [AAP Credential Management](https://access.redhat.com/documentation/en-us/red_hat_ansible_automation_platform/)
