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
│ │   Database      │ │    │ │   JSON Export   │ │    │ │   REST API      │ │
│ │   (PostgreSQL)  │ │    │ │                 │ │    │ │                 │ │
│ │                 │ │    │ │ • Credential    │ │    │ │ • Create        │ │
│ │ • Encrypted     │ │    │ │   Types         │ │    │ │   Credential    │ │
│ │   Credentials   │ │    │ │ • Credentials   │ │    │ │   Types         │ │
│ │ • Credential    │ │    │ │ • Metadata      │ │    │ │ • Import        │ │
│ │   Types         │ │    │ │                 │ │    │ │   Credentials   │ │
│ └─────────────────┘ │    │ └─────────────────┘ │    │ └─────────────────┘ │
│                     │    │                     │    │                     │
│ ┌─────────────────┐ │    │                     │    │                     │
│ │   SECRET_KEY    │ │    │                     │    │                     │
│ │   (Config)      │ │    │                     │    │                     │
│ └─────────────────┘ │    │                     │    │                     │
└─────────────────────┘    └─────────────────────┘    └─────────────────────┘
         │                           │                           │
         │                           │                           │
         ▼                           ▼                           ▼
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│   tower_credential_ │    │   Secure Transfer   │    │   aap_credential_   │
│   migrator.py       │    │   (SCP/SFTP/etc.)   │    │   importer.py       │
│                     │    │                     │    │                     │
│ • Extract from DB   │    │ • Encrypted file    │    │ • Create credential │
│ • Decrypt secrets   │    │ • Restricted perms  │    │   types first       │
│ • Export to JSON    │    │ • Secure transfer   │    │ • Import credentials│
└─────────────────────┘    └─────────────────────┘    └─────────────────────┘
```

## Technical Background: Tower Encryption

### 🔐 Encryption & Decryption Mechanism

#### 1. The Role of SECRET_KEY

- The `SECRET_KEY` can be defined in multiple locations:
  - `/etc/tower/settings.py` (main settings file)
  - `/etc/tower/conf.d/secrets.py` or `/etc/tower/conf.d/secret_key.py`
  - `/etc/tower/SECRET_KEY` (standalone file)
- This key is critical for encrypting and decrypting sensitive fields (like credential passwords)
- It must remain stable across system upgrades and reboots, or Tower will not be able to decrypt existing credential data

#### 2. Encryption Backend

- Tower uses Django's Fernet symmetric encryption, provided via the `cryptography` Python package
- This mechanism is invoked through a custom field wrapper used for sensitive model fields (`EncryptedCharField`, etc.)
- The encryption/decryption logic is embedded in the Tower/Controller codebase

#### 3. Key Derivation Process

Our implementation correctly follows Tower's key derivation:

```python
def get_encryption_key(self, field_name: str, pk: Optional[int] = None) -> bytes:
    """Generate encryption key for a specific field."""
    h = hashlib.sha512()
    h.update(self.secret_key)                    # Start with SECRET_KEY
    if pk is not None:
        h.update(str(pk).encode("utf-8"))        # Add credential ID
    h.update(field_name.encode("utf-8"))         # Add field name
    return base64.urlsafe_b64encode(h.digest())  # Generate Fernet key
```

#### 4. Storage Format

- Encrypted fields in the database are stored with the format: `$encrypted$UTF8$AESCBC$<base64_data>`
- These are opaque blobs that can only be decrypted with the correct derived key from `SECRET_KEY`

### 🔄 Decrypting Data (Our Implementation)

When our tool needs to decrypt a credential:

1. **Fetch encrypted string** from the database
2. **Derive the correct key** using the same algorithm as Tower
3. **Parse the encryption format** (`$encrypted$UTF8$AESCBC$...`)
4. **Decrypt using Fernet256** (our AES-256-CBC implementation)
5. **Return plaintext** for export

## Tool 1: Tower Credential Extractor

### Requirements

- Must run on the **source Tower instance**
- Requires **root privileges** to access `SECRET_KEY`
- Direct database access to Tower's PostgreSQL database

### Usage

```bash
# Run on Tower instance as root (auto-discovers SECRET_KEY and database config)
sudo python tower_credential_migrator.py

# With custom database options (overrides auto-discovery)
sudo python tower_credential_migrator.py \
    --tower-host db.example.com \
    --tower-password mypass \
    --output-file my_credentials.json

# Dry run to test
sudo python tower_credential_migrator.py --dry-run
```

### Environment Variable Configuration

The tool supports `.env` file configuration to override command line options. Create a `.env` file in the same directory as the script:

```bash
# Database Connection (overrides command line options)
TOWER_HOST=localhost
TOWER_PORT=5432
TOWER_DB=awx
TOWER_USER=awx
TOWER_PASSWORD=your_database_password_here

# Tower Configuration
TOWER_SECRET_KEY=your_tower_secret_key_here
TOWER_CONFIG_PATH=/etc/tower/conf.d

# Output Configuration
TOWER_OUTPUT_FILE=tower_credentials_export.json

# Debug and Testing
TOWER_DEBUG=false
TOWER_DRY_RUN=false
```

**Environment variables take precedence over command line options.**

### Features

- **Automatic SECRET_KEY discovery** from multiple Tower config locations:
  - `/etc/tower/settings.py`
  - `/etc/tower/conf.d/secrets.py` or `/etc/tower/conf.d/secret_key.py`
  - `/etc/tower/SECRET_KEY`
- **Automatic database configuration discovery** from `/etc/tower/conf.d/postgres.py`
- **Environment variable configuration** via `.env` file support
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
        "password": "decrypted_password_here",
        "ssh_key_data": "-----BEGIN RSA PRIVATE KEY-----\n..."
      }
    }
  ]
}
```

## Tool 2: AAP Credential Importer

Imports decrypted credentials into AAP using the REST API.

### Requirements AAP Credential Importer

- Network access to target AAP instance
- AAP admin credentials
- Exported credentials JSON file

### Usage AAP Credential Importer

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

### Features AAP Credential Importer

- **REST API-based import** - lets AAP handle encryption
- **Credential type creation** - creates missing custom credential types first
- **Improved type mapping** - uses name-based mapping instead of unreliable ID mapping
- **Organization mapping** - preserves organizational structure
- **Duplicate detection** - skips existing credentials and credential types
- **Batch processing** with progress tracking
- **Comprehensive validation** and error reporting
- **Retry logic** for API calls

## Migration Process AAP Credential Importer

### Step 1: Extract from Tower

```bash
# On Tower instance
sudo python tower_credential_migrator.py \
    --output-file tower_migration_export.json \
    --debug
```

This will:

- Discover the Tower `SECRET_KEY` automatically
- Discover database configuration from `/etc/tower/conf.d/postgres.py`
- Connect to the Tower database
- Extract all credential types (including custom ones)
- Extract all credentials and decrypt their secrets
- Create a secure JSON export file

### Step 2: Transfer Securely

```bash
# Transfer the export file to your AAP instance or management machine
scp tower_migration_export.json user@aap-server:/tmp/
```

### Step 3: Import to AAP

```bash
# On AAP instance or management machine
python aap_credential_importer.py \
    --aap-url https://aap.example.com \
    --aap-username admin \
    --credentials-file /tmp/tower_migration_export.json \
    --dry-run  # First run dry-run to validate
```

This will:

- Connect to AAP using REST API
- Create missing custom credential types first
- Import all credentials with proper type mapping
- Let AAP handle re-encryption with its own `SECRET_KEY`

## Security Considerations

### 🔒 SECRET_KEY Management

- **Never share** the Tower `SECRET_KEY` - it's used to decrypt all credentials
- **Secure transfer** of the export file - it contains decrypted secrets
- **Restrict file permissions** - export files have 600 permissions by default
- **Clean up** export files after successful migration

### 🔐 Encryption Handling

- Our tools **never re-encrypt** data - we let AAP handle encryption
- **Direct database access** is required to bypass API limitations
- **Root privileges** are needed to access Tower's `SECRET_KEY`
- **Temporary decryption** - secrets are only decrypted during export

### 🛡️ Best Practices

1. **Run extraction on Tower instance** - minimizes exposure of `SECRET_KEY`
2. **Use secure transfer** - SCP/SFTP for moving export files
3. **Validate before import** - always run dry-run first
4. **Monitor import process** - check logs for any failures
5. **Clean up after migration** - remove export files from all systems

## Troubleshooting

### Common Issues

#### SECRET_KEY Not Found

```text
Error: Could not auto-discover SECRET_KEY
```

**Solution**: Check if running as root and verify the config paths:

```bash
sudo ls -la /etc/tower/
sudo ls -la /etc/tower/conf.d/
```

#### Database Connection Failed

```text
Error: Database connection failed
```

**Solution**: Verify database credentials and connectivity:

```bash
psql -h localhost -U awx -d awx
```

#### Credential Type Mapping Issues

```text
Warning: Could not map credential type 'Custom Type'
```

**Solution**: The importer will create missing credential types automatically.

#### Import Failures

```text
Error: API error 400: Invalid credential type
```

**Solution**: Run with `--debug` to see detailed error messages and check AAP logs.

### Debug Mode

Both tools support debug mode for troubleshooting:

```bash
# Tower extractor
sudo python tower_credential_migrator.py --debug

# AAP importer  
python aap_credential_importer.py --debug --credentials-file export.json
```

## Engineering Notes

### Cluster Considerations

- **All Tower nodes** must share the same `SECRET_KEY`
- **Database access** should be to the primary Tower database
- **Export once** from the primary Tower instance

### Backup and Restore

- **SECRET_KEY preservation** is critical for credential access
- **Export before upgrades** to ensure credential recovery
- **Test migration** in a non-production environment first

### Custom Credential Types

- **Custom types are preserved** through the migration process
- **Namespace handling** ensures proper organization in AAP
- **Input/Injector definitions** are maintained exactly as defined

## Support

For issues or questions:

1. Check the troubleshooting section above
2. Run with `--debug` flag for detailed logging
3. Review the error messages and logs
4. Ensure all prerequisites are met

## License

Apache 2.0 License - see LICENSE file for details.
