#!/bin/sh -eu
#
# Script Name: update-dsm-cert-remote.sh
# Description: Remotely updates SSL certificates on Synology DSM 7.* NAS from pfSense host
# Last Modified: 2025-12-18
#
# Dependencies:
#   - sshpass (for password authentication)
#   - ssh (OpenSSH client)
#   - scp (secure copy)
#   - openssl (for certificate fingerprinting)
#
# Environment Variables:
#   DSMPASS - Password for DSM authentication (recommended over command-line parameter)
#
# Usage:
#   DSMPASS="password" ./update-dsm-cert-remote.sh \
#     --host 192.168.1.2 \
#     --user admin \
#     --domain example.com \
#     --cert-desc "Main Certificate" \
#     [--cert-path /cf/conf/acme/]
#
# Exit Codes:
#   0  - Success, no update needed (certificate unchanged)
#   10 - Success, certificate updated
#   64 - Missing parameters
#   65 - Certificate ID not found on DSM
#   66 - Certificate files not found on pfSense
#   69 - SSH connection failed
#   73 - Certificate import failed
#   77 - Required tools not found
#
### Exit codes based on:
### * see glibc: https://sourceware.org/git/?p=glibc.git;a=blob;f=misc/sysexits.h;hb=HEAD
### * see https://tldp.org/LDP/abs/html/exitcodes.html

SCRIPTNAME="$(basename "${0}")"

#################################
# Functions
#################################

# Display usage information
usage() {
    cat << EOF
Usage: ${SCRIPTNAME} [OPTIONS]

Remotely update SSL certificate on Synology DSM 7.* NAS.

Required Options:
  --host HOST          DSM hostname or IP address
  --user USER          DSM username (e.g., admin)
  --domain DOMAIN      Certificate domain name (e.g., example.com)
  --cert-desc DESC     Certificate description in DSM

Optional:
  --cert-path PATH     Path to certificate files (default: /cf/conf/acme/)
  --password PASS      DSM password (prefer DSMPASS environment variable)
  -h, --help           Display this help message

Environment Variables:
  DSMPASS              DSM user password (recommended over --password)

Examples:
  # Using environment variable for password (recommended):
  DSMPASS="mypassword" ${SCRIPTNAME} \\
    --host 192.168.1.2 \\
    --user admin \\
    --domain example.com \\
    --cert-desc "Main Certificate"

  # Using custom certificate path:
  DSMPASS="mypassword" ${SCRIPTNAME} \\
    --host nas.local \\
    --user admin \\
    --domain example.com \\
    --cert-desc "Main Certificate" \\
    --cert-path /path/to/certs/

Exit Codes:
  0  - No update needed (certificate unchanged)
  10 - Certificate successfully updated
  64 - Missing required parameters
  65 - Certificate ID not found
  66 - Certificate files not found
  69 - SSH connection failed
  73 - Certificate import failed
  77 - Required tools not found

EOF
}

# Log message with timestamp
log_message() {
    printf '[%s] %s: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${SCRIPTNAME}" "${1}"
}

# Log error message
log_error() {
    printf '[%s] ERROR/%s: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${SCRIPTNAME}" "${1}" >&2
}

# Check if required tools are available
check_required_tools() {
    local missing_tools=""
    
    for tool in sshpass ssh scp openssl; do
        if ! command -v "${tool}" >/dev/null 2>&1; then
            missing_tools="${missing_tools} ${tool}"
        fi
    done
    
    if [ -n "${missing_tools}" ]; then
        log_error "Missing required tools:${missing_tools}"
        log_error "On pfSense, install sshpass: pkg install sshpass"
        return 77
    fi
    
    return 0
}

# Calculate certificate fingerprint
get_cert_fingerprint() {
    local cert_file="${1}"
    
    if [ ! -f "${cert_file}" ]; then
        log_error "Certificate file not found: ${cert_file}"
        return 1
    fi
    
    openssl x509 -in "${cert_file}" -noout -fingerprint -sha256 2>/dev/null | \
        sed 's/SHA256 Fingerprint=//' | \
        tr -d ':'
}

# Get remote certificate fingerprint via SSH
get_remote_cert_fingerprint() {
    local host="${1}"
    local user="${2}"
    local password="${3}"
    local cert_id="${4}"
    
    local remote_cert_path="/usr/syno/etc/certificate/_archive/${cert_id}/cert.pem"
    
    sshpass -p "${password}" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR "${user}@${host}" \
        "test -f '${remote_cert_path}' && openssl x509 -in '${remote_cert_path}' -noout -fingerprint -sha256 2>/dev/null" 2>/dev/null | \
        sed 's/SHA256 Fingerprint=//' | \
        tr -d ':' || echo ""
}

# Get certificate ID from DSM by description
get_cert_id_from_dsm() {
    local host="${1}"
    local user="${2}"
    local password="${3}"
    local cert_desc="${4}"
    
    log_message "Querying DSM for certificate ID with description: ${cert_desc}"
    
    local cert_id
    cert_id=$(sshpass -p "${password}" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR "${user}@${host}" \
        "/usr/bin/jq -r --arg desc '${cert_desc}' 'to_entries[] | select( .value.desc == \$desc ) | .key' /usr/syno/etc/certificate/_archive/INFO" 2>/dev/null)
    
    if [ -z "${cert_id}" ]; then
        log_error "No certificate ID found for description: ${cert_desc}"
        return 65
    fi
    
    log_message "Found certificate ID: ${cert_id}"
    printf '%s' "${cert_id}"
    return 0
}

# Test SSH connection
test_ssh_connection() {
    local host="${1}"
    local user="${2}"
    local password="${3}"
    
    log_message "Testing SSH connection to ${user}@${host}"
    
    if ! sshpass -p "${password}" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR -o ConnectTimeout=10 "${user}@${host}" "echo 'Connected'" >/dev/null 2>&1; then
        log_error "SSH connection failed to ${user}@${host}"
        return 69
    fi
    
    log_message "SSH connection successful"
    return 0
}

# Transfer certificate files to DSM
transfer_cert_files() {
    local host="${1}"
    local user="${2}"
    local password="${3}"
    local cert_path="${4}"
    local domain="${5}"
    local remote_tmpdir="${6}"
    
    log_message "Transferring certificate files to DSM"
    
    # Transfer private key
    if ! sshpass -p "${password}" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR "${cert_path}/${domain}.key" "${user}@${host}:${remote_tmpdir}/privkey.pem" 2>/dev/null; then
        log_error "Failed to transfer private key"
        return 1
    fi
    
    # Transfer certificate
    if ! sshpass -p "${password}" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR "${cert_path}/${domain}.crt" "${user}@${host}:${remote_tmpdir}/cert.pem" 2>/dev/null; then
        log_error "Failed to transfer certificate"
        return 1
    fi
    
    # Transfer CA chain
    if ! sshpass -p "${password}" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR "${cert_path}/${domain}.ca" "${user}@${host}:${remote_tmpdir}/chain.pem" 2>/dev/null; then
        log_error "Failed to transfer CA chain"
        return 1
    fi
    
    log_message "Certificate files transferred successfully"
    return 0
}

# Import certificate on DSM
import_cert_on_dsm() {
    local host="${1}"
    local user="${2}"
    local password="${3}"
    local remote_tmpdir="${4}"
    local cert_id="${5}"
    local cert_desc="${6}"
    
    log_message "Importing certificate on DSM"
    
    # Execute certificate import via synowebapi
    local result
    result=$(sshpass -p "${password}" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR "${user}@${host}" \
        "/usr/syno/bin/synowebapi --exec-fastwebapi api='SYNO.Core.Certificate' method='import' version='1' key_tmp='\"${remote_tmpdir}/privkey.pem\"' cert_tmp='\"${remote_tmpdir}/cert.pem\"' inter_cert_tmp='\"${remote_tmpdir}/chain.pem\"' id='\"${cert_id}\"' desc='\"${cert_desc}\"'" 2>/dev/null)
    
    # Check if import was successful
    local success
    success=$(printf '%s' "${result}" | grep -o '"success"[[:space:]]*:[[:space:]]*true' || echo "")
    
    if [ -z "${success}" ]; then
        log_error "Certificate import failed"
        log_error "API response: ${result}"
        return 73
    fi
    
    log_message "Certificate imported successfully"
    return 0
}

# Cleanup remote temporary directory
cleanup_remote_tmpdir() {
    local host="${1}"
    local user="${2}"
    local password="${3}"
    local remote_tmpdir="${4}"
    
    if [ -n "${remote_tmpdir}" ]; then
        log_message "Cleaning up remote temporary directory"
        sshpass -p "${password}" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
            -o LogLevel=ERROR "${user}@${host}" \
            "rm -rf '${remote_tmpdir}'" 2>/dev/null || true
    fi
}

#################################
# Main Script
#################################

# Default values
CERT_PATH="/cf/conf/acme"
DSM_HOST=""
DSM_USER=""
DSM_PASSWORD="${DSMPASS:-}"
CERT_DOMAIN=""
CERT_DESC=""

# Parse command-line arguments
while [ $# -gt 0 ]; do
    case "${1}" in
        --host)
            DSM_HOST="${2}"
            shift 2
            ;;
        --user)
            DSM_USER="${2}"
            shift 2
            ;;
        --password)
            DSM_PASSWORD="${2}"
            shift 2
            ;;
        --domain)
            CERT_DOMAIN="${2}"
            shift 2
            ;;
        --cert-desc)
            CERT_DESC="${2}"
            shift 2
            ;;
        --cert-path)
            CERT_PATH="${2}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            log_error "Unknown option: ${1}"
            usage
            exit 64
            ;;
    esac
done

# Validate required parameters
if [ -z "${DSM_HOST}" ] || [ -z "${DSM_USER}" ] || [ -z "${CERT_DOMAIN}" ] || [ -z "${CERT_DESC}" ]; then
    log_error "Missing required parameters"
    usage
    exit 64
fi

if [ -z "${DSM_PASSWORD}" ]; then
    log_error "Password not provided. Set DSMPASS environment variable or use --password"
    usage
    exit 64
fi

# Check for required tools
check_required_tools || exit $?

log_message "Starting DSM certificate update for ${CERT_DOMAIN} on ${DSM_HOST}"

# Verify certificate files exist
LOCAL_CERT_FILE="${CERT_PATH}/${CERT_DOMAIN}.crt"
LOCAL_KEY_FILE="${CERT_PATH}/${CERT_DOMAIN}.key"
LOCAL_CA_FILE="${CERT_PATH}/${CERT_DOMAIN}.ca"

if [ ! -f "${LOCAL_CERT_FILE}" ]; then
    log_error "Certificate file not found: ${LOCAL_CERT_FILE}"
    exit 66
fi

if [ ! -f "${LOCAL_KEY_FILE}" ]; then
    log_error "Private key file not found: ${LOCAL_KEY_FILE}"
    exit 66
fi

if [ ! -f "${LOCAL_CA_FILE}" ]; then
    log_error "CA chain file not found: ${LOCAL_CA_FILE}"
    exit 66
fi

log_message "All certificate files found locally"

# Test SSH connection
test_ssh_connection "${DSM_HOST}" "${DSM_USER}" "${DSM_PASSWORD}" || exit $?

# Get certificate ID from DSM
CERT_ID=$(get_cert_id_from_dsm "${DSM_HOST}" "${DSM_USER}" "${DSM_PASSWORD}" "${CERT_DESC}") || exit $?

# Calculate local certificate fingerprint
log_message "Calculating local certificate fingerprint"
LOCAL_FINGERPRINT=$(get_cert_fingerprint "${LOCAL_CERT_FILE}") || exit 66

if [ -z "${LOCAL_FINGERPRINT}" ]; then
    log_error "Failed to calculate local certificate fingerprint"
    exit 66
fi

log_message "Local certificate fingerprint: ${LOCAL_FINGERPRINT}"

# Get remote certificate fingerprint
log_message "Getting remote certificate fingerprint"
REMOTE_FINGERPRINT=$(get_remote_cert_fingerprint "${DSM_HOST}" "${DSM_USER}" "${DSM_PASSWORD}" "${CERT_ID}")

if [ -n "${REMOTE_FINGERPRINT}" ]; then
    log_message "Remote certificate fingerprint: ${REMOTE_FINGERPRINT}"
    
    # Compare fingerprints
    if [ "${LOCAL_FINGERPRINT}" = "${REMOTE_FINGERPRINT}" ]; then
        log_message "Certificate fingerprints match - no update needed"
        exit 0
    fi
    
    log_message "Certificate fingerprints differ - update required"
else
    log_message "Unable to get remote fingerprint - proceeding with update"
fi

# Create temporary directory on DSM
log_message "Creating temporary directory on DSM"
REMOTE_TMPDIR=$(sshpass -p "${DSM_PASSWORD}" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o LogLevel=ERROR "${DSM_USER}@${DSM_HOST}" \
    "mktemp -d /tmp/cert-update-XXXXXX" 2>/dev/null)

if [ -z "${REMOTE_TMPDIR}" ]; then
    log_error "Failed to create temporary directory on DSM"
    exit 73
fi

log_message "Created temporary directory: ${REMOTE_TMPDIR}"

# Setup cleanup trap
trap 'cleanup_remote_tmpdir "${DSM_HOST}" "${DSM_USER}" "${DSM_PASSWORD}" "${REMOTE_TMPDIR}"' EXIT INT TERM

# Transfer certificate files
transfer_cert_files "${DSM_HOST}" "${DSM_USER}" "${DSM_PASSWORD}" "${CERT_PATH}" "${CERT_DOMAIN}" "${REMOTE_TMPDIR}" || exit 73

# Import certificate
import_cert_on_dsm "${DSM_HOST}" "${DSM_USER}" "${DSM_PASSWORD}" "${REMOTE_TMPDIR}" "${CERT_ID}" "${CERT_DESC}" || exit $?

log_message "Certificate update completed successfully"
exit 10
