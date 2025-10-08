#!/bin/bash
# -*- coding: utf-8 -*-
#
# setk8s_ssh_env.sh - Shell script equivalent of setk8s_ssh_env Ansible role
#
# Purpose: Configure Kubernetes SSH environment by retrieving kubeconfig from Vault
# Dependencies: curl, jq, kubectl, vault CLI
# Variables: CLUSTER_NAME, CLUSTER_ADM_KUBE_DIR, VAULT_TOKEN_PATH, INVENTORY_URL
#
# Author: Generated from Ansible role setk8s_ssh_env
# Version: 1.0.0
# License: Same as project

set -euo pipefail

# =============================================================================
# CONFIGURATION AND CONSTANTS
# =============================================================================

# Script configuration
readonly SCRIPT_NAME="$(basename "$0")"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly LOG_DIR="${PROJECT_ROOT}/.logs"
readonly TMP_DIR="${PROJECT_ROOT}/tmp"
readonly CACHE_DIR="${PROJECT_ROOT}/cache"

# Default configuration values
readonly DEFAULT_VAULT_TOKEN_PATH="/run/secrets/vault-token"
readonly DEFAULT_VAULT_PROD_ADDRESS="https://vault-prod.example.com"
readonly DEFAULT_VAULT_DEV_ADDRESS="https://vault-dev.example.com"
readonly DEFAULT_VAULT_TEST_ADDRESS="https://vault-test.example.com"
readonly DEFAULT_VAULT_ENG_ADDRESS="https://vault-eng.example.com"
readonly DEFAULT_VAULT_NAMESPACE="automation"
readonly DEFAULT_VAULT_MOUNT_POINT="secret"
readonly DEFAULT_INVENTORY_URL="https://inventory.example.com"
readonly DEFAULT_CA_CERT_PATH="/etc/ssl/certs/ca-certificates.crt"
readonly DEFAULT_K8S_NS="portworx"
readonly DEFAULT_SERVICE_ACCOUNT_NAME="pxbackup-sa"
readonly DEFAULT_CLUSTER_ROLE_NAME="pxbackup-cluster-role"
readonly DEFAULT_SA_ROLE_NAME="pxbackup-role"
readonly DEFAULT_CLUSTER_ROLE_BINDING_NAME="pxbackup-cluster-rolebinding"
readonly DEFAULT_SA_ROLE_BINDING_NAME="pxbackup-rolebinding"

# =============================================================================
# GLOBAL VARIABLES
# =============================================================================

# Configuration variables (can be overridden by environment)
VAULT_TOKEN_PATH="${VAULT_TOKEN_PATH:-${DEFAULT_VAULT_TOKEN_PATH}}"
VAULT_PROD_ADDRESS="${VAULT_PROD_ADDRESS:-${DEFAULT_VAULT_PROD_ADDRESS}}"
VAULT_DEV_ADDRESS="${VAULT_DEV_ADDRESS:-${DEFAULT_VAULT_DEV_ADDRESS}}"
VAULT_TEST_ADDRESS="${VAULT_TEST_ADDRESS:-${DEFAULT_VAULT_TEST_ADDRESS}}"
VAULT_ENG_ADDRESS="${VAULT_ENG_ADDRESS:-${DEFAULT_VAULT_ENG_ADDRESS}}"
VAULT_NAMESPACE="${VAULT_NAMESPACE:-${DEFAULT_VAULT_NAMESPACE}}"
VAULT_MOUNT_POINT="${VAULT_MOUNT_POINT:-${DEFAULT_VAULT_MOUNT_POINT}}"
INVENTORY_URL="${INVENTORY_URL:-${DEFAULT_INVENTORY_URL}}"
CA_CERT_PATH="${CA_CERT_PATH:-${DEFAULT_CA_CERT_PATH}}"
K8S_NS="${K8S_NS:-${DEFAULT_K8S_NS}}"
SERVICE_ACCOUNT_NAME="${SERVICE_ACCOUNT_NAME:-${DEFAULT_SERVICE_ACCOUNT_NAME}}"
CLUSTER_ROLE_NAME="${CLUSTER_ROLE_NAME:-${DEFAULT_CLUSTER_ROLE_NAME}}"
SA_ROLE_NAME="${SA_ROLE_NAME:-${DEFAULT_SA_ROLE_NAME}}"
CLUSTER_ROLE_BINDING_NAME="${CLUSTER_ROLE_BINDING_NAME:-${DEFAULT_CLUSTER_ROLE_BINDING_NAME}}"
SA_ROLE_BINDING_NAME="${SA_ROLE_BINDING_NAME:-${DEFAULT_SA_ROLE_BINDING_NAME}}"
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
KUBECONFIG_ADMIN=""
KUBECONFIG_PATH=""

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
    log_debug "Cleaning up temporary files"
    # Remove any temporary files if needed
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
    log_info "Project root: ${PROJECT_ROOT}"
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
    
    if [[ -z "${CLUSTER_ADM_KUBE_DIR:-}" ]]; then
        missing_vars+=("CLUSTER_ADM_KUBE_DIR")
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

read_vault_token() {
    log_info "Reading Vault token from: ${VAULT_TOKEN_PATH}"
    
    if [[ ! -f "${VAULT_TOKEN_PATH}" ]]; then
        error_exit "Vault token file not found at ${VAULT_TOKEN_PATH}"
    fi
    
    local vault_token
    vault_token=$(cat "${VAULT_TOKEN_PATH}" | tr -d '\n\r' | xargs)
    
    if [[ -z "${vault_token}" ]]; then
        error_exit "Vault token file is empty or unreadable"
    fi
    
    echo "${vault_token}"
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
    
    if ! vault auth "${vault_opts[@]}" -method=token token="${vault_token}" >/dev/null 2>&1; then
        error_exit "Vault token is invalid"
    fi
    
    log_info "Vault token is valid"
}

retrieve_kubeconfig_from_vault() {
    local vault_token="$1"
    
    log_info "Retrieving kubeconfig from Vault"
    
    local vault_opts=()
    if [[ "${VALIDATE_CERTS}" == "true" ]]; then
        vault_opts+=("-ca-cert" "${CA_CERT_PATH}")
    else
        vault_opts+=("-tls-skip-verify")
    fi
    
    if [[ -n "${VAULT_NAMESPACE}" ]]; then
        vault_opts+=("-namespace" "${VAULT_NAMESPACE}")
    fi
    
    # Set Vault address
    export VAULT_ADDR="${VAULT_ADDRESS}"
    export VAULT_TOKEN="${vault_token}"
    
    local kubeconfig_data
    if ! kubeconfig_data=$(vault kv get "${vault_opts[@]}" \
        -field=kubeconfig \
        "${VAULT_MOUNT_POINT}/data/${VAULT_DEFAULT_PATH}" 2>/dev/null); then
        error_exit "Failed to retrieve kubeconfig from Vault"
    fi
    
    if [[ -z "${kubeconfig_data}" ]]; then
        error_exit "Retrieved kubeconfig is empty"
    fi
    
    echo "${kubeconfig_data}"
}

# =============================================================================
# KUBECONFIG FUNCTIONS
# =============================================================================

check_existing_kubeconfig() {
    local cluster_name="$1"
    local kube_dir="$2"
    
    if [[ -n "${kube_dir}" && -d "${kube_dir}" ]]; then
        local kubeconfig_file="${kube_dir}/${cluster_name}"
        if [[ -f "${kubeconfig_file}" ]]; then
            log_info "Existing kubeconfig found at: ${kubeconfig_file}"
            return 0
        fi
    fi
    
    return 1
}

write_kubeconfig() {
    local kubeconfig_data="$1"
    local cluster_name="$2"
    local kube_dir="$3"
    
    local kubeconfig_path="${kube_dir}/${cluster_name}"
    
    log_info "Writing kubeconfig to: ${kubeconfig_path}"
    
    # Ensure directory exists
    mkdir -p "$(dirname "${kubeconfig_path}")"
    
    # Write kubeconfig
    echo "${kubeconfig_data}" > "${kubeconfig_path}"
    chmod 600 "${kubeconfig_path}"
    
    KUBECONFIG_PATH="${kubeconfig_path}"
    log_info "Kubeconfig written successfully"
}

test_kubeconfig_connection() {
    local kubeconfig_path="$1"
    
    log_info "Testing kubeconfig connection"
    
    # Test connection by listing pods in default namespace
    local pod_list
    if ! pod_list=$(kubectl --kubeconfig="${kubeconfig_path}" get pods -n default --no-headers 2>/dev/null); then
        error_exit "Failed to connect to cluster using kubeconfig"
    fi
    
    local pod_count
    pod_count=$(echo "${pod_list}" | wc -l)
    
    log_info "Successfully connected to cluster"
    log_info "Found ${pod_count} pods in default namespace"
    
    if [[ "${DEBUG:-false}" == "true" ]]; then
        log_debug "Pod names:"
        echo "${pod_list}" | awk '{print "  - " $1}' | while read -r line; do
            log_debug "${line}"
        done
    fi
}

# =============================================================================
# MAIN EXECUTION FUNCTIONS
# =============================================================================

configure_cluster_variables() {
    log_info "Configuring cluster variables"
    
    parse_cluster_name "${CLUSTER_NAME}"
    
    # Get inventory data
    local inventory_data
    inventory_data=$(get_inventory_data "${CLUSTER_NAME}")
    
    # Setup Vault configuration
    setup_vault_config "${inventory_data}"
}

retrieve_master_kubeconfig() {
    log_info "Retrieving master kubeconfig"
    
    # Check if kubeconfig already exists
    if check_existing_kubeconfig "${CLUSTER_NAME}" "${CLUSTER_ADM_KUBE_DIR}"; then
        log_info "Kubeconfig already exists, skipping retrieval"
        KUBECONFIG_PATH="${CLUSTER_ADM_KUBE_DIR}/${CLUSTER_NAME}"
        return 0
    fi
    
    # Read and validate Vault token
    local vault_token
    vault_token=$(read_vault_token)
    validate_vault_token "${vault_token}"
    
    # Retrieve kubeconfig from Vault
    local kubeconfig_data
    kubeconfig_data=$(retrieve_kubeconfig_from_vault "${vault_token}")
    
    # Write kubeconfig to file
    write_kubeconfig "${kubeconfig_data}" "${CLUSTER_NAME}" "${CLUSTER_ADM_KUBE_DIR}"
    
    # Test kubeconfig connection
    test_kubeconfig_connection "${KUBECONFIG_PATH}"
}

# =============================================================================
# USAGE AND HELP FUNCTIONS
# =============================================================================

show_usage() {
    cat << EOF
Usage: ${SCRIPT_NAME} [OPTIONS]

Configure Kubernetes SSH environment by retrieving kubeconfig from Vault.

REQUIRED ENVIRONMENT VARIABLES:
    CLUSTER_NAME              Name of the cluster (e.g., user-platform-env-region-id)
    CLUSTER_ADM_KUBE_DIR      Directory to store kubeconfig files

OPTIONAL ENVIRONMENT VARIABLES:
    VAULT_TOKEN_PATH          Path to Vault token file (default: ${DEFAULT_VAULT_TOKEN_PATH})
    INVENTORY_URL             Inventory service URL (default: ${DEFAULT_INVENTORY_URL})
    VAULT_PROD_ADDRESS        Production Vault address (default: ${DEFAULT_VAULT_PROD_ADDRESS})
    VAULT_DEV_ADDRESS         Development Vault address (default: ${DEFAULT_VAULT_DEV_ADDRESS})
    VAULT_TEST_ADDRESS        Test Vault address (default: ${DEFAULT_VAULT_TEST_ADDRESS})
    VAULT_ENG_ADDRESS         Engineering Vault address (default: ${DEFAULT_VAULT_ENG_ADDRESS})
    VAULT_NAMESPACE           Vault namespace (default: ${DEFAULT_VAULT_NAMESPACE})
    VAULT_MOUNT_POINT         Vault mount point (default: ${DEFAULT_VAULT_MOUNT_POINT})
    CA_CERT_PATH              Path to CA certificate (default: ${DEFAULT_CA_CERT_PATH})
    VALIDATE_CERTS            Validate SSL certificates (default: true)
    DEBUG                     Enable debug logging (default: false)

OPTIONS:
    -h, --help                Show this help message
    -v, --version             Show version information
    -d, --debug               Enable debug logging

EXAMPLES:
    # Basic usage
    CLUSTER_NAME="user-platform-env-region-id" \\
    CLUSTER_ADM_KUBE_DIR="/home/user/.kube" \\
    ${SCRIPT_NAME}

    # With custom Vault configuration
    CLUSTER_NAME="user-platform-env-region-id" \\
    CLUSTER_ADM_KUBE_DIR="/home/user/.kube" \\
    VAULT_TOKEN_PATH="/custom/path/token" \\
    VAULT_PROD_ADDRESS="https://custom-vault.example.com" \\
    ${SCRIPT_NAME}

    # With debug logging
    DEBUG=true ${SCRIPT_NAME}

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
Generated from Ansible role setk8s_ssh_env

This script replicates the functionality of the setk8s_ssh_env Ansible role
for configuring Kubernetes SSH environments by retrieving kubeconfig from Vault.

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
    log_info "Starting kubeconfig setup process"
    
    # Configure cluster variables
    configure_cluster_variables
    
    # Retrieve master kubeconfig
    retrieve_master_kubeconfig
    
    log_info "Kubeconfig setup completed successfully"
    log_info "Kubeconfig path: ${KUBECONFIG_PATH}"
    
    # Display final status
    echo "SUCCESS: Successfully configured Kubernetes SSH environment"
    echo "Kubeconfig location: ${KUBECONFIG_PATH}"
    echo "Cluster: ${CLUSTER_NAME}"
    echo "Environment: ${CLUSTER_ENV}"
    echo "Region: ${REGION}"
    if [[ "${ZONE}" != "all-zones" ]]; then
        echo "Zone: ${ZONE}"
    fi
}

# Execute main function if script is run directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
