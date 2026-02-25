#!/bin/bash
# -*- coding: utf-8 -*-
#
# setup_k8s_env.sh - Combines features of grab_kubeconfig.sh and setk8s_ssh_env.sh
#
# Purpose: Configure Kubernetes environment by retrieving kubeconfig and SSH private key from Vault.
# Dependencies: curl, jq, kubectl, vault CLI
# Variables: CLUSTER_NAME, KUBECONFIG_DIR, VAULT_TOKEN, VAULT_TOKEN_FILE, INVENTORY_URL
#
# Author: Gemini Assistant
# Version: 1.0.0
# License: Same as project

set -euo pipefail

# =============================================================================
# CONFIGURATION AND CONSTANTS
# =============================================================================

# Script configuration
readonly SCRIPT_NAME="$(basename "$0")"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
readonly LOG_DIR="${PROJECT_ROOT}/logs"
readonly TMP_DIR="${PROJECT_ROOT}/tmp"
readonly CACHE_DIR="${PROJECT_ROOT}/cache"

# Default configuration values
readonly DEFAULT_VAULT_TOKEN_FILE="${HOME}/.vault-token"
readonly DEFAULT_VAULT_PROD_ADDRESS="https://vault-prod.example.com"
readonly DEFAULT_VAULT_DEV_ADDRESS="https://vault-dev.example.com"
readonly DEFAULT_VAULT_TEST_ADDRESS="https://vault-test.example.com"
readonly DEFAULT_VAULT_ENG_ADDRESS="https://vault-eng.example.com"
readonly DEFAULT_VAULT_NAMESPACE="automation"
readonly DEFAULT_VAULT_MOUNT_POINT="secret"
readonly DEFAULT_INVENTORY_URL="https://inventory.example.com"
readonly DEFAULT_CA_CERT_PATH="/etc/ssl/certs/ca-certificates.crt"
readonly DEFAULT_KUBECONFIG_DIR="kube_configs"

# =============================================================================
# GLOBAL VARIABLES
# =============================================================================

# Configuration variables (can be overridden by environment)
VAULT_TOKEN_FILE="${VAULT_TOKEN_FILE:-${DEFAULT_VAULT_TOKEN_FILE}}"
VAULT_PROD_ADDRESS="${VAULT_PROD_ADDRESS:-${DEFAULT_VAULT_PROD_ADDRESS}}"
VAULT_DEV_ADDRESS="${VAULT_DEV_ADDRESS:-${DEFAULT_VAULT_DEV_ADDRESS}}"
VAULT_TEST_ADDRESS="${VAULT_TEST_ADDRESS:-${DEFAULT_VAULT_TEST_ADDRESS}}"
VAULT_ENG_ADDRESS="${VAULT_ENG_ADDRESS:-${DEFAULT_VAULT_ENG_ADDRESS}}"
VAULT_NAMESPACE="${VAULT_NAMESPACE:-${DEFAULT_VAULT_NAMESPACE}}"
VAULT_MOUNT_POINT="${VAULT_MOUNT_POINT:-${DEFAULT_VAULT_MOUNT_POINT}}"
INVENTORY_URL="${INVENTORY_URL:-${DEFAULT_INVENTORY_URL}}"
CA_CERT_PATH="${CA_CERT_PATH:-${DEFAULT_CA_CERT_PATH}}"
KUBECONFIG_DIR="${KUBECONFIG_DIR:-${DEFAULT_KUBECONFIG_DIR}}"
VALIDATE_CERTS="${VALIDATE_CERTS:-true}"

# Parsed cluster variables
CLUSTER_USER=""
PLATFORM=""
CLUSTER_ENV=""
REGION_ZONE=""
REGION=""
ZONE=""
CLUSTER_ID=""
CLUSTER_HAS_ZONE=""
VAULT_ADDRESS=""
VAULT_DEFAULT_PATH=""
KUBECONFIG_PATH=""
SSH_KEY_PATH=""
KUBECONFIG_DATA=""
SSH_PRIVATE_KEY=""

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

# Logging functions
log_info() {
    echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S') - $*" | tee -a "${LOG_FILE}"
}

log_warn() {
    echo "[WARN] $(date '+%Y-%m-%d %H:%M:%S') - $*" | tee -a "${LOG_FILE}" >&2
}

log_error() {
    echo "[ERROR] $(date '+%Y-%m-%d %H:%M:%S') - $*" | tee -a "${LOG_FILE}" >&2
}

log_debug() {
    if [[ "${DEBUG:-false}" == "true" ]]; then
        echo "[DEBUG] $(date '+%Y-%m-%d %H:%M:%S') - $*" | tee -a "${LOG_FILE}"
    fi
}

# Error handling
error_exit() {
    log_error "$1"
    exit "${2:-1}"
}

# Cleanup function
cleanup() {
    log_debug "Running cleanup..."
    # This script doesn't create temp files that need cleanup, but the hook is here.
    return 0
}

# Setup function
setup() {
    # Create necessary directories
    mkdir -p "${LOG_DIR}" "${TMP_DIR}" "${CACHE_DIR}"
    
    # Set up log file
    LOG_FILE="${LOG_DIR}/${SCRIPT_NAME}-$(date '+%Y%m%d-%H%M%S').log"
    
    # Set up trap for cleanup
    trap cleanup EXIT
    
    log_info "Starting ${SCRIPT_NAME}"
    log_info "Log file: ${LOG_FILE}"
}

# Validation functions
validate_required_tools() {
    local missing_tools=()
    
    for tool in curl jq kubectl vault; do
        if ! command -v "${tool}" >/dev/null 2>&1; then
            missing_tools+=("${tool}")
        fi
    done
    
    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        error_exit "Missing required tools: ${missing_tools[*]}"
    fi
    
    log_info "All required tools are available"
}

validate_required_variables() {
    local missing_vars=()
    
    if [[ -z "${CLUSTER_NAME:-}" ]]; then
        missing_vars+=("CLUSTER_NAME")
    fi
    
    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        error_exit "Missing required variables: ${missing_vars[*]}"
    fi
    
    log_info "All required variables are set"
}

validate_cluster_name_format() {
    local cluster_name="$1"
    
    # Check for format with zone: <cluster_user>-<platform>-<env>-<region><zone>-<id>
    if [[ "${cluster_name}" =~ ^[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-zA-Z0-9]+[abc]-[a-z0-9]+$ ]]; then
        CLUSTER_HAS_ZONE="true"
        return 0
    fi
    
    # Check for format without zone: <cluster_user>-<platform>-<env>-<region>-<id>
    if [[ "${cluster_name}" =~ ^[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-zA-Z0-9]+-[a-z0-9]+$ ]]; then
        CLUSTER_HAS_ZONE="false"
        return 0
    fi
    
    error_exit "Invalid cluster name format. Expected formats:
    - With zone: <cluster_user>-<platform>-<env>-<region><zone>-<id>
    - Without zone: <cluster_user>-<platform>-<env>-<region>-<id>"
}

# =============================================================================
# CLUSTER VARIABLE PARSING FUNCTIONS
# =============================================================================

parse_cluster_name() {
    local cluster_name="$1"
    local -a parts
    
    log_info "Parsing cluster name: ${cluster_name}"
    
    # Validate format
    validate_cluster_name_format "${cluster_name}"
    
    # Split cluster name into parts
    IFS='-' read -ra parts <<< "${cluster_name}"
    
    # Set common variables
    CLUSTER_USER="${parts[0]}"
    PLATFORM="${parts[1]}"
    
    # Parse environment
    case "${parts[2]}" in
        "p") CLUSTER_ENV="prod" ;;
        "t") CLUSTER_ENV="test" ;;
        "d") CLUSTER_ENV="dev" ;;
        *) CLUSTER_ENV="${parts[2]}" ;;
    esac
    
    if [[ "${CLUSTER_HAS_ZONE}" == "true" ]]; then
        # Parse with zone
        REGION_ZONE="${parts[3]}"
        REGION="${parts[3]%[abc]}"
        ZONE="zone-${parts[3]: -1}"
        CLUSTER_ID="${parts[4]}"
    else
        # Parse without zone
        REGION="${parts[3]}"
        ZONE="all-zones"
        CLUSTER_ID="${parts[4]}"
    fi
    
    log_info "Parsed cluster information:"
    log_info "  Cluster User: ${CLUSTER_USER}"
    log_info "  Platform: ${PLATFORM}"
    log_info "  Environment: ${CLUSTER_ENV}"
    log_info "  Region: ${REGION}"
    log_info "  Zone: ${ZONE}"
    log_info "  Cluster ID: ${CLUSTER_ID}"
}

# =============================================================================
# VAULT FUNCTIONS
# =============================================================================

get_inventory_data() {
    local cluster_name="$1"
    local inventory_url="${INVENTORY_URL}/${cluster_name}"
    
    log_info "Retrieving cluster information from inventory: ${inventory_url}"
    
    local curl_opts=()
    if [[ "${VALIDATE_CERTS}" == "true" ]]; then
        curl_opts+=("--cacert" "${CA_CERT_PATH}")
    else
        curl_opts+=("--insecure")
    fi
    
    local response
    if ! response=$(curl -s "${curl_opts[@]}" \
        -H "Accept: application/json" \
        "${inventory_url}"); then
        error_exit "Failed to retrieve inventory data from ${inventory_url}"
    fi
    
    echo "${response}"
}

setup_vault_config() {
    local inventory_data="$1"
    
    log_info "Setting up Vault configuration"
    
    # Check if platform_vault exists in inventory response
    local platform_vault_exists
    platform_vault_exists=$(echo "${inventory_data}" | jq -r '.kubernetes_platform.secrets_management.platform_vault[0] // empty')
    
    if [[ -n "${platform_vault_exists}" ]]; then
        log_info "Using platform Vault configuration from inventory"
        
        VAULT_ADDRESS=$(echo "${inventory_data}" | jq -r '.kubernetes_platform.secrets_management.platform_vault[0].address')
        VAULT_NAMESPACE=$(echo "${inventory_data}" | jq -r '.kubernetes_platform.secrets_management.platform_vault[0].namespace')
        local vault_default_path_full
        vault_default_path_full=$(echo "${inventory_data}" | jq -r '.kubernetes_platform.secrets_management.platform_vault[0].default_path')
        
        VAULT_MOUNT_POINT=$(echo "${vault_default_path_full}" | cut -d'/' -f1)
        VAULT_DEFAULT_PATH=$(echo "${vault_default_path_full}" | cut -d'/' -f2-)
    else
        log_info "Using default Vault configuration based on cluster environment"
        
        # Set Vault address based on environment
        case "${CLUSTER_ENV}" in
            "prod") VAULT_ADDRESS="${VAULT_PROD_ADDRESS}" ;;
            "test") VAULT_ADDRESS="${VAULT_TEST_ADDRESS}" ;;
            "dev")
                if [[ "${CLUSTER_USER}" == "eng" ]]; then
                    VAULT_ADDRESS="${VAULT_ENG_ADDRESS}"
                else
                    VAULT_ADDRESS="${VAULT_DEV_ADDRESS}"
                fi
                ;;
            *) VAULT_ADDRESS="${VAULT_DEV_ADDRESS}" ;;
        esac
        
        VAULT_NAMESPACE="${VAULT_NAMESPACE}"
        VAULT_DEFAULT_PATH="${CLUSTER_USER}/${CLUSTER_NAME}"
    fi
    
    log_info "Vault configuration:"
    log_info "  Address: ${VAULT_ADDRESS}"
    log_info "  Namespace: ${VAULT_NAMESPACE}"
    log_info "  Mount Point: ${VAULT_MOUNT_POINT}"
    log_info "  Default Path: ${VAULT_DEFAULT_PATH}"
}

get_vault_token() {
    log_info "Attempting to find Vault token"
    
    if [[ -n "${VAULT_TOKEN:-}" ]]; then
        log_info "Using Vault token from VAULT_TOKEN environment variable"
        echo "${VAULT_TOKEN}"
        return 0
    fi
    
    if [[ -f "${HOME}/.vault-token" ]]; then
        log_info "Using Vault token from ${HOME}/.vault-token"
        cat "${HOME}/.vault-token"
        return 0
    fi
    
    if [[ -f "${VAULT_TOKEN_FILE}" ]]; then
        log_info "Using Vault token from VAULT_TOKEN_FILE: ${VAULT_TOKEN_FILE}"
        cat "${VAULT_TOKEN_FILE}"
        return 0
    fi
    
    error_exit "Could not find Vault token. Please set VAULT_TOKEN, or create ${HOME}/.vault-token or set VAULT_TOKEN_FILE."
}

validate_vault_token() {
    local vault_token="$1"
    
    log_info "Validating Vault token"
    
    local vault_opts=()
    if [[ "${VALIDATE_CERTS}" == "true" ]]; then
        vault_opts+=("-ca-cert" "${CA_CERT_PATH}")
    else
        vault_opts+=("-tls-skip-verify")
    fi
    
    if [[ -n "${VAULT_NAMESPACE}" ]]; then
        vault_opts+=("-namespace" "${VAULT_NAMESPACE}")
    fi
    
    # Temporarily set VAULT_ADDR and VAULT_TOKEN for the CLI command
    export VAULT_ADDR="${VAULT_ADDRESS}"
    export VAULT_TOKEN="${vault_token}"
    
    if ! vault token lookup "${vault_opts[@]}" >/dev/null 2>&1; then
        error_exit "Vault token is invalid or expired"
    fi
    
    log_info "Vault token is valid"
}

retrieve_creds_from_vault() {
    local vault_token="$1"
    
    log_info "Retrieving kubeconfig and SSH private key from Vault"
    
    local vault_opts=()
    if [[ "${VALIDATE_CERTS}" == "true" ]]; then
        vault_opts+=("-ca-cert" "${CA_CERT_PATH}")
    else
        vault_opts+=("-tls-skip-verify")
    fi
    
    if [[ -n "${VAULT_NAMESPACE}" ]]; then
        vault_opts+=("-namespace" "${VAULT_NAMESPACE}")
    fi
    
    # Set Vault address and token for the CLI command
    export VAULT_ADDR="${VAULT_ADDRESS}"
    export VAULT_TOKEN="${vault_token}"
    
    local secret_data
    if ! secret_data=$(vault kv get "${vault_opts[@]}" \
        -format=json \
        "${VAULT_MOUNT_POINT}/data/${VAULT_DEFAULT_PATH}" 2>/dev/null); then
        error_exit "Failed to retrieve secrets from Vault path: ${VAULT_MOUNT_POINT}/data/${VAULT_DEFAULT_PATH}"
    fi
    
    KUBECONFIG_DATA=$(echo "${secret_data}" | jq -r '.data.data.kubeconfig')
    SSH_PRIVATE_KEY=$(echo "${secret_data}" | jq -r '.data.data."ssh_private.key"')
    
    if [[ -z "${KUBECONFIG_DATA}" || "${KUBECONFIG_DATA}" == "null" ]]; then
        error_exit "Retrieved kubeconfig is empty"
    fi
    
    if [[ -z "${SSH_PRIVATE_KEY}" || "${SSH_PRIVATE_KEY}" == "null" ]]; then
        error_exit "Retrieved SSH private key is empty"
    fi
    
    log_info "Successfully retrieved kubeconfig and SSH key"
}

# =============================================================================
# KUBECONFIG & SSH KEY FUNCTIONS
# =============================================================================

write_creds() {
    local cluster_name="$1"
    local output_dir="$2"
    
    # Ensure directory exists
    log_info "Ensuring output directory exists: ${output_dir}"
    mkdir -p "${output_dir}"
    
    KUBECONFIG_PATH="${output_dir}/${cluster_name}.kubeconfig"
    SSH_KEY_PATH="${output_dir}/${cluster_name}.sshpriv"
    
    log_info "Writing kubeconfig to: ${KUBECONFIG_PATH}"
    echo "${KUBECONFIG_DATA}" > "${KUBECONFIG_PATH}"
    chmod 600 "${KUBECONFIG_PATH}"
    
    log_info "Writing SSH private key to: ${SSH_KEY_PATH}"
    echo "${SSH_PRIVATE_KEY}" > "${SSH_KEY_PATH}"
    chmod 600 "${SSH_KEY_PATH}"
    
    log_info "Credentials written successfully"
}

test_kubeconfig_connection() {
    local kubeconfig_path="$1"
    
    log_info "Testing kubeconfig connection"
    
    # Test connection by listing nodes
    if ! kubectl --kubeconfig="${kubeconfig_path}" get nodes >/dev/null 2>&1; then
        error_exit "Failed to connect to cluster using kubeconfig at ${kubeconfig_path}"
    fi
    
    log_info "Successfully connected to cluster"
}

# =============================================================================
# MAIN EXECUTION FUNCTIONS
# =============================================================================

configure_cluster_variables() {
    log_info "Configuring cluster variables"
    
    parse_cluster_name "${CLUSTER_NAME}"
    
    local inventory_data
    inventory_data=$(get_inventory_data "${CLUSTER_NAME}")
    
    setup_vault_config "${inventory_data}"
}

retrieve_and_write_creds() {
    log_info "Retrieving and writing credentials"
    
    # Get and validate Vault token
    local vault_token
    vault_token=$(get_vault_token)
    validate_vault_token "${vault_token}"
    
    # Retrieve credentials from Vault
    retrieve_creds_from_vault "${vault_token}"
    
    # Write credentials to files
    write_creds "${CLUSTER_NAME}" "${KUBECONFIG_DIR}"
    
    # Test kubeconfig connection
    test_kubeconfig_connection "${KUBECONFIG_PATH}"
}

# =============================================================================
# USAGE AND HELP FUNCTIONS
# =============================================================================

show_usage() {
    cat << EOF
Usage: ${SCRIPT_NAME} [OPTIONS]

Configure Kubernetes environment by retrieving kubeconfig and SSH private key from Vault.

REQUIRED ENVIRONMENT VARIABLES:
    CLUSTER_NAME              Name of the cluster (e.g., user-platform-env-region-id)

OPTIONAL ENVIRONMENT VARIABLES:
    KUBECONFIG_DIR            Directory to store credential files (default: ${DEFAULT_KUBECONFIG_DIR})
    VAULT_TOKEN               Vault token (overrides file-based tokens)
    VAULT_TOKEN_FILE          Path to Vault token file (default: ${DEFAULT_VAULT_TOKEN_FILE})
    INVENTORY_URL             Inventory service URL (default: ${DEFAULT_INVENTORY_URL})
    VAULT_NAMESPACE           Vault namespace (default: ${DEFAULT_VAULT_NAMESPACE})
    VALIDATE_CERTS            Validate SSL certificates (default: true)
    DEBUG                     Enable debug logging (default: false)

OPTIONS:
    -h, --help                Show this help message
    -v, --version             Show version information
    -d, --debug               Enable debug logging

EXAMPLES:
    # Basic usage
    CLUSTER_NAME="user-platform-env-region-id" ${SCRIPT_NAME}

    # With a custom output directory and Vault token file
    CLUSTER_NAME="user-platform-env-region-id" \\
    KUBECONFIG_DIR="/home/user/.kube/configs" \\
    VAULT_TOKEN_FILE="/custom/path/token" \\
    ${SCRIPT_NAME}

    # With debug logging enabled
    DEBUG=true CLUSTER_NAME="user-platform-env-region-id" ${SCRIPT_NAME}

DEPENDENCIES:
    - curl: For HTTP requests to inventory service
    - jq: For JSON processing
    - kubectl: For Kubernetes cluster testing
    - vault: For Vault operations

EOF
}

show_version() {
    cat << EOF
${SCRIPT_NAME} version 1.0.0

This script configures a Kubernetes environment by retrieving kubeconfig and SSH
private key from Vault, combining the best features of grab_kubeconfig.sh and
setk8s_ssh_env.sh.

EOF
}

# =============================================================================
# MAIN EXECUTION
# =============================================================================

main() {
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_usage
                exit 0
                ;;
            -v|--version)
                show_version
                exit 0
                ;;
            -d|--debug)
                export DEBUG=true
                shift
                ;;
            *)
                log_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done
    
    # Setup
    setup
    
    # Validate environment
    validate_required_tools
    validate_required_variables
    
    # Main execution
    log_info "Starting Kubernetes credential setup process"
    
    configure_cluster_variables
    
    retrieve_and_write_creds
    
    log_info "Setup completed successfully"
    
    # Display final status
    echo ""
    echo "SUCCESS: Successfully configured Kubernetes environment for ${CLUSTER_NAME}"
    echo "Kubeconfig location: ${KUBECONFIG_PATH}"
    echo "SSH Key location:    ${SSH_KEY_PATH}"
    echo ""
    echo "To use this configuration, you can run:"
    echo "export KUBECONFIG=${KUBECONFIG_PATH}"
}

# Execute main function if script is run directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
