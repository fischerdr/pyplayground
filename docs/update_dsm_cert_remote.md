# Remote Synology DSM Certificate Update Guide

This document explains how to remotely update SSL certificates on a Synology DSM 7.* NAS from a pfSense host using the `update-dsm-cert-remote.sh` script.

## Overview

The `update-dsm-cert-remote.sh` script automates the process of updating SSL certificates on a Synology NAS. It connects to the NAS via SSH, transfers certificate files, and uses the Synology Web API to import them. The script includes intelligent certificate fingerprint checking to avoid unnecessary updates when the certificate hasn't changed.

## Prerequisites

### On pfSense Host

1. **Required Packages**: Install sshpass for password-based SSH authentication:

   ```bash
   pkg install sshpass
   ```

2. **Certificate Files**: Ensure your ACME certificates are available (typically in `/cf/conf/acme/`):
   - `<domain>.key` - Private key
   - `<domain>.crt` - Certificate
   - `<domain>.ca` - CA chain

3. **Network Access**: Ensure pfSense can reach the Synology NAS on port 22 (SSH)

### On Synology DSM

1. **SSH Access**: Enable SSH service
   - Go to Control Panel > Terminal & SNMP
   - Enable SSH service
   - Note: Consider using a non-standard port for security

2. **User Account**: Ensure the user account has admin privileges

3. **Certificate Description**: Know the exact description of the certificate in DSM
   - Go to Control Panel > Security > Certificate
   - Note the description field of the certificate you want to update

## Installation

1. Copy the script to your pfSense host:

   ```bash
   scp bin/scripts/update-dsm-cert-remote.sh admin@pfsense-host:/usr/local/sbin/
   ```

2. Make the script executable:

   ```bash
   chmod +x /usr/local/sbin/update-dsm-cert-remote.sh
   ```

## Usage

### Basic Usage

```bash
DSMPASS="your-password" /usr/local/sbin/update-dsm-cert-remote.sh \
  --host 192.168.1.2 \
  --user admin \
  --domain example.com \
  --cert-desc "Main Certificate"
```

### Command-Line Options

#### Required Options

- `--host HOST` - DSM hostname or IP address
- `--user USER` - DSM username (typically `admin`)
- `--domain DOMAIN` - Certificate domain name (e.g., `example.com`)
- `--cert-desc DESC` - Exact certificate description as shown in DSM

#### Optional Options

- `--cert-path PATH` - Path to certificate files (default: `/cf/conf/acme/`)
- `--password PASS` - DSM password (not recommended; use `DSMPASS` environment variable instead)
- `-h, --help` - Display help message

### Environment Variables

- `DSMPASS` - DSM user password (recommended method for passing password)

### Exit Codes

The script uses specific exit codes to indicate the result:

- `0` - Success, no update needed (certificate unchanged)
- `10` - Success, certificate updated
- `64` - Missing required parameters
- `65` - Certificate ID not found on DSM
- `66` - Certificate files not found on pfSense
- `69` - SSH connection failed
- `73` - Certificate import failed
- `77` - Required tools not found

## Examples

### Example 1: Basic Update with Environment Variable

```bash
# Set password as environment variable (recommended)
DSMPASS="SecurePassword123" /usr/local/sbin/update-dsm-cert-remote.sh \
  --host nas.example.com \
  --user admin \
  --domain example.com \
  --cert-desc "Wildcard Certificate"
```

### Example 2: Update with Custom Certificate Path

```bash
DSMPASS="SecurePassword123" /usr/local/sbin/update-dsm-cert-remote.sh \
  --host 192.168.1.100 \
  --user admin \
  --domain mydomain.com \
  --cert-desc "Main Certificate" \
  --cert-path /custom/path/to/certs
```

### Example 3: Using with ACME Hook

Create a post-renewal hook script in pfSense ACME package:

```bash
#!/bin/sh
# ACME post-renewal hook for DSM certificate update

DOMAIN="example.com"
DSM_HOST="192.168.1.2"
DSM_USER="admin"
CERT_DESC="Main Certificate"

# Password stored securely (consider using encrypted storage)
DSMPASS="your-password" /usr/local/sbin/update-dsm-cert-remote.sh \
  --host "${DSM_HOST}" \
  --user "${DSM_USER}" \
  --domain "${DOMAIN}" \
  --cert-desc "${CERT_DESC}"

EXIT_CODE=$?

if [ ${EXIT_CODE} -eq 10 ]; then
    logger -t "acme-hook" "DSM certificate updated successfully for ${DOMAIN}"
elif [ ${EXIT_CODE} -eq 0 ]; then
    logger -t "acme-hook" "DSM certificate unchanged for ${DOMAIN}"
else
    logger -t "acme-hook" "DSM certificate update failed for ${DOMAIN} with exit code ${EXIT_CODE}"
fi

exit ${EXIT_CODE}
```

### Example 4: Check if Update Would Run

```bash
# Dry-run: The script automatically checks fingerprints
# If fingerprints match, it exits with code 0 without updating
DSMPASS="SecurePassword123" /usr/local/sbin/update-dsm-cert-remote.sh \
  --host nas.example.com \
  --user admin \
  --domain example.com \
  --cert-desc "Main Certificate"

if [ $? -eq 0 ]; then
    echo "Certificate is up to date - no action taken"
elif [ $? -eq 10 ]; then
    echo "Certificate was updated"
fi
```

## How It Works

The script performs the following steps:

1. **Parameter Validation**: Checks that all required parameters are provided
2. **Tool Verification**: Ensures all required tools (sshpass, ssh, scp, openssl) are available
3. **File Verification**: Confirms certificate files exist on the pfSense host
4. **SSH Connection Test**: Verifies it can connect to the DSM host
5. **Certificate ID Lookup**: Queries DSM to find the certificate ID matching the description
6. **Fingerprint Comparison**: 
   - Calculates SHA256 fingerprint of local certificate
   - Retrieves fingerprint of currently installed certificate on DSM
   - Compares fingerprints to determine if update is needed
7. **File Transfer** (if needed):
   - Creates temporary directory on DSM
   - Transfers private key, certificate, and CA chain via SCP
8. **Certificate Import** (if needed):
   - Uses Synology Web API to import the new certificate
   - Verifies import success
9. **Cleanup**: Removes temporary directory on DSM

## Troubleshooting

### SSH Connection Failures

**Problem**: Script exits with code 69 (SSH connection failed)

**Solutions**:
- Verify SSH is enabled on DSM (Control Panel > Terminal & SNMP)
- Check firewall rules allow connection from pfSense to DSM on port 22
- Verify username and password are correct
- Try manual SSH connection: `ssh admin@nas-ip`

### Certificate Files Not Found

**Problem**: Script exits with code 66 (Certificate files not found)

**Solutions**:
- Verify the domain name matches your ACME certificate files
- Check the certificate path (default: `/cf/conf/acme/`)
- List files: `ls -la /cf/conf/acme/`
- Ensure files are named: `<domain>.key`, `<domain>.crt`, `<domain>.ca`

### Certificate ID Not Found

**Problem**: Script exits with code 65 (Certificate ID not found)

**Solutions**:
- Verify the certificate description exactly matches what's in DSM
- Log into DSM and check Control Panel > Security > Certificate
- Note the exact description (case-sensitive)
- Common descriptions: "Main Certificate", "Default Certificate", domain name

### Certificate Import Failed

**Problem**: Script exits with code 73 (Certificate import failed)

**Solutions**:
- Check certificate files are valid: `openssl x509 -in /cf/conf/acme/domain.crt -noout -text`
- Verify the private key matches: `openssl rsa -in /cf/conf/acme/domain.key -check`
- Check DSM logs: Log Center > System > Connection
- Ensure user has admin privileges on DSM

### Missing sshpass Tool

**Problem**: Script exits with code 77 (Required tools not found)

**Solutions**:
- Install sshpass: `pkg install sshpass`
- Alternative: Use SSH key-based authentication (see Security Considerations)

## Security Considerations

### Password Security

The script supports password authentication, but for production use, consider:

1. **SSH Key Authentication** (Recommended):
   - Generate SSH key pair on pfSense
   - Add public key to DSM user's authorized_keys
   - Modify script to use key-based authentication instead of sshpass

2. **Encrypted Storage**:
   - Store passwords in encrypted configuration files
   - Use pfSense's built-in password management

3. **Environment Variables**:
   - Use `DSMPASS` environment variable instead of `--password` parameter
   - Passwords in parameters can appear in process listings

### Network Security

1. **SSH Port**: Consider changing DSM's SSH port from default 22
2. **Firewall Rules**: Restrict SSH access to only pfSense IP
3. **SSH Key Restrictions**: Use `authorized_keys` restrictions like `from="pfsense-ip"`

### Certificate Security

1. **File Permissions**: Ensure certificate files have appropriate permissions (600 or 640)
2. **Temporary Files**: Script automatically cleans up temporary files on DSM
3. **Logging**: Script logs operations without exposing sensitive data

## Integration with pfSense ACME

### Automated Updates

To automatically update DSM certificates when ACME renews:

1. **Install ACME Package** (if not already installed):
   - System > Package Manager
   - Search for "acme"
   - Install

2. **Configure ACME Certificate**:
   - Services > Acme Certificates
   - Add or edit certificate

3. **Add Renewal Hook**:
   - In certificate settings, find "Actions list"
   - Add "Shell Command" action
   - Command:
     ```bash
     DSMPASS="password" /usr/local/sbin/update-dsm-cert-remote.sh --host 192.168.1.2 --user admin --domain example.com --cert-desc "Main Certificate"
     ```

4. **Test the Hook**:
   - Use ACME's "Issue/Renew" button
   - Check logs for success message

### Scheduling

Alternatively, schedule periodic updates using cron:

1. **Add Cron Entry**:
   - System > Cron
   - Add new entry
   - Schedule: Daily or weekly
   - Command: (same as renewal hook)

2. **Monitor Execution**:
   - Check pfSense logs: Status > System Logs
   - Check DSM logs: Log Center

## Certificate File Mapping

The script maps pfSense ACME files to DSM format:

| pfSense ACME File | DSM File | Description |
|-------------------|----------|-------------|
| `<domain>.key` | `privkey.pem` | Private key |
| `<domain>.crt` | `cert.pem` | Certificate |
| `<domain>.ca` | `chain.pem` | CA certificate chain |

## Logging

The script provides detailed logging with timestamps:

```
[2025-12-18 10:30:15] update-dsm-cert-remote.sh: Starting DSM certificate update for example.com on 192.168.1.2
[2025-12-18 10:30:15] update-dsm-cert-remote.sh: All certificate files found locally
[2025-12-18 10:30:15] update-dsm-cert-remote.sh: Testing SSH connection to admin@192.168.1.2
[2025-12-18 10:30:16] update-dsm-cert-remote.sh: SSH connection successful
[2025-12-18 10:30:16] update-dsm-cert-remote.sh: Querying DSM for certificate ID with description: Main Certificate
[2025-12-18 10:30:16] update-dsm-cert-remote.sh: Found certificate ID: 8KdE7Q
[2025-12-18 10:30:16] update-dsm-cert-remote.sh: Calculating local certificate fingerprint
[2025-12-18 10:30:16] update-dsm-cert-remote.sh: Local certificate fingerprint: A1B2C3D4...
[2025-12-18 10:30:17] update-dsm-cert-remote.sh: Getting remote certificate fingerprint
[2025-12-18 10:30:17] update-dsm-cert-remote.sh: Remote certificate fingerprint: E5F6G7H8...
[2025-12-18 10:30:17] update-dsm-cert-remote.sh: Certificate fingerprints differ - update required
[2025-12-18 10:30:17] update-dsm-cert-remote.sh: Creating temporary directory on DSM
[2025-12-18 10:30:17] update-dsm-cert-remote.sh: Created temporary directory: /tmp/cert-update-a8k3df
[2025-12-18 10:30:17] update-dsm-cert-remote.sh: Transferring certificate files to DSM
[2025-12-18 10:30:18] update-dsm-cert-remote.sh: Certificate files transferred successfully
[2025-12-18 10:30:18] update-dsm-cert-remote.sh: Importing certificate on DSM
[2025-12-18 10:30:19] update-dsm-cert-remote.sh: Certificate imported successfully
[2025-12-18 10:30:19] update-dsm-cert-remote.sh: Certificate update completed successfully
```

## Best Practices

1. **Test First**: Test the script manually before automating
2. **Monitor Logs**: Regularly check pfSense and DSM logs
3. **Backup Certificates**: Keep backups of important certificates
4. **Use Descriptive Names**: Use clear certificate descriptions in DSM
5. **Document Configuration**: Document your setup (hosts, domains, descriptions)
6. **Regular Testing**: Periodically test the automation
7. **Security Hardening**: Use SSH keys instead of passwords when possible
8. **Network Isolation**: Keep management traffic on separate VLANs

## Related Documentation

- [Synology DSM Certificate Management](https://kb.synology.com/en-global/DSM/help/DSM/AdminCenter/connection_certificate)
- [pfSense ACME Package Documentation](https://docs.netgate.com/pfsense/en/latest/packages/acme/index.html)
- [OpenSSL Certificate Management](https://www.openssl.org/docs/man1.1.1/man1/x509.html)

## Support

For issues or questions:
- Check the Troubleshooting section above
- Review pfSense logs: Status > System Logs
- Review DSM logs: Log Center > Connection
- Verify certificate files with OpenSSL commands
- Test SSH connectivity manually

## Version History

- **1.0.0** (2025-12-18): Initial release
  - Remote certificate update via SSH
  - Fingerprint-based change detection
  - Comprehensive error handling
  - POSIX-compliant shell script
