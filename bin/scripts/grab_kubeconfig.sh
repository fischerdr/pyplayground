#!/bin/bash
#
# Script: grab_kubeconfig.sh
# Description: Functions to retrieve and store the kubeconfig and SSH private key for a given cluster name. Needs to be included in a main script.
# Usage: source ./grab_kubeconfig.sh
#
# Examples:
#   source ./grab_kubeconfig.sh
#   get_inventory_data "my-cluster"
#   get_vault_kubeconfig "my-cluster"
#   # This will create kube_configs/my-cluster.kubeconfig and kube_configs/my-cluster.sshpriv
#   # and export KUBECONFIG
#
# Dependencies:
#   - curl: for API requests
#   - jq: for JSON parsing
#
# Environment Variables:
#   - VAULT_TOKEN: Optional, vault token for authentication
#   - DEBUG: Optional, set to "true" for debug output
#
# Directory Structure:
#   - kube_configs/: Directory where kubeconfig and SSH key files are stored
#     - <cluster_name>.kubeconfig: Kubeconfig file for each cluster
#     - <cluster_name>.sshpriv: SSH private key file for each cluster

# Enable strict mode
set -euo pipefail
IFS=$'\n\t'

# Enable debug mode if requested
[[ "${DEBUG:-}" == "true" ]] && set -x

# Global constants
readonly CURL_CMD="/usr/bin/curl"
readonly JQ_CMD="/usr/bin/jq"
readonly VAULT_TOKEN_FILE="/src/vault_secrets/ansible-token"
readonly CURL_TIMEOUT=30
readonly KUBECONFIG_DIR="kube_configs"

# Logging function
# Usage: log <level> <message>
# Example: log "INFO" "Starting script"
log() {
    local level="$1"
    shift
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [${level}] $*" >&2
}

# Function to cleanup kubeconfig
# Usage: cleanup
# Description: Removes the created kubeconfig and SSH private key files and unsets KUBECONFIG environment variable
# Returns: 0 on success, 1 on failure
cleanup() {
    local kubeconfig_file="${KUBECONFIG:-}"
    local ssh_key_file=""
    local cleanup_failed=0
    
    if [[ -n "${kubeconfig_file}" ]]; then
        # Derive SSH key file path from kubeconfig path
        ssh_key_file="${kubeconfig_file%.kubeconfig}.sshpriv"
        
        # Remove kubeconfig file
        if [[ -f "${kubeconfig_file}" ]]; then
            log "INFO" "Removing kubeconfig file: ${kubeconfig_file}"
            rm -f "${kubeconfig_file}" || {
                log "ERROR" "Failed to remove kubeconfig file: ${kubeconfig_file}"
                cleanup_failed=1
            }
        fi
        
        # Remove SSH private key file
        if [[ -f "${ssh_key_file}" ]]; then
            log "INFO" "Removing SSH private key file: ${ssh_key_file}"
            rm -f "${ssh_key_file}" || {
                log "ERROR" "Failed to remove SSH private key file: ${ssh_key_file}"
                cleanup_failed=1
            }
        fi
        
        log "INFO" "Unsetting KUBECONFIG environment variable"
        unset KUBECONFIG
    else
        log "INFO" "No KUBECONFIG environment variable set, nothing to clean"
    fi
    return ${cleanup_failed}
}

# Common error handler
# Usage: error "error message"
# Returns: 1
# Description: Outputs error message to stderr and returns 1
error() {
    log "ERROR" "$1"
    return 1
}

# Curl wrapper with timeout
# Usage: curl_cmd [args...]
# Description: Executes curl with timeout and common options
curl_cmd() {
    "${CURL_CMD}" --max-time "${CURL_TIMEOUT}" "$@"
}

# Function to check if required commands exist
# Usage: check_requirements
# Returns: 0 if all required commands exist, 1 otherwise
# Description: Verifies that curl, jq commands are available in the system
check_requirements() {
    local required_cmds=(curl jq)
    for cmd in "${required_cmds[@]}"; do
        if ! command -v "${cmd}" >/dev/null; then
            error "Required command '${cmd}' not found. Please install it."
            return 1
        fi
    done
    log "INFO" "All required commands are available"
    return 0
}

# Function to get vault token from environment or file
# Usage: get_vault_token
# Returns: 
#   - 0 and prints token if found in VAULT_TOKEN env or token file
#   - 1 if no valid token found
# Description: Attempts to retrieve vault token first from VAULT_TOKEN environment
#             variable, then from VAULT_TOKEN_FILE if env var is not set
get_vault_token() {
    if [[ -n "${VAULT_TOKEN:-}" ]]; then
        log "DEBUG" "Using vault token from environment"
        echo "${VAULT_TOKEN}"
        return 0
    elif [[ -r "${VAULT_TOKEN_FILE}" ]]; then
        log "DEBUG" "Reading vault token from file"
        if token=$(cat "${VAULT_TOKEN_FILE}"); then
            echo "${token}"
            return 0
        fi
    fi
    error "No valid vault token found"
    return 1
}

# Function to normalize vault path by removing mount prefix
# Usage: normalize_vault_path <path>
# Returns: Normalized path without mount prefix
normalize_vault_path() {
    local path="$1"
    # Remove leading and trailing slashes
    path="${path#/}"
    path="${path%/}"
    # Remove static_secrets prefix if present
    path="${path#static_secrets/}"
    echo "${path}"
}

# Function to get inventory data and extract vault config
# Usage: get_inventory_data <cluster_name>
# Arguments:
#   cluster_name - Name of the cluster to get inventory data for
# Returns: 
#   - 0 if vault config successfully extracted and exported
#   - 1 if any step fails
# Description: Retrieves inventory data for a cluster and extracts vault configuration.
#             Sets VAULT_ADDR, VAULT_NAMESPACE, and VAULT_PATH environment variables
get_inventory_data() {
    local cluster_name="$1"
    local inventory_url="https://inventory.com/v2/inventory/${cluster_name}"
    local response vault_config
    
    log "INFO" "Retrieving inventory data for cluster ${cluster_name}"
    response=$(curl_cmd -s "${inventory_url}") || error "Failed to retrieve inventory data"

    # Extract all vault configuration at once
    vault_config=$("${JQ_CMD}" -r '{
        address: .kubernetes_platform.secrets_management.platform_vault[0].address,
        namespace: .kubernetes_platform.secrets_management.platform_vault[0].namespace,
        path: .kubernetes_platform.secrets_management.platform_vault[0].default_path
    }' <<< "${response}") || error "Failed to parse vault configuration"

    # Extract and validate vault config
    VAULT_ADDR=$("${JQ_CMD}" -r '.address' <<< "${vault_config}")
    VAULT_NAMESPACE=$("${JQ_CMD}" -r '.namespace' <<< "${vault_config}")
    VAULT_PATH=$("${JQ_CMD}" -r '.path' <<< "${vault_config}")
    
    # Normalize the vault path
    VAULT_PATH=$(normalize_vault_path "${VAULT_PATH}")

    # Validate all vault configuration at once
    if [[ -z "${VAULT_ADDR}" || "${VAULT_ADDR}" == "null" || \
          -z "${VAULT_NAMESPACE}" || "${VAULT_NAMESPACE}" == "null" || \
          -z "${VAULT_PATH}" || "${VAULT_PATH}" == "null" ]]; then
        error "Missing required vault configuration in inventory"
        return 1
    fi

    export VAULT_ADDR VAULT_NAMESPACE VAULT_PATH
    log "INFO" "Successfully extracted vault configuration"
    return 0
}

# Validate cluster name for safe file operations
# Usage: validate_cluster_name <cluster_name>
# Returns: 0 if valid, 1 if invalid
validate_cluster_name() {
    local cluster_name="$1"
    # Check for empty name
    [[ -z "${cluster_name}" ]] && error "Cluster name cannot be empty" && return 1
    
    # Check for valid characters (alphanumeric, dash, dot, underscore)
    if [[ ! "${cluster_name}" =~ ^[a-zA-Z0-9._-]+$ ]]; then
        error "Cluster name contains invalid characters. Use only alphanumeric, dash, dot, or underscore"
        return 1
    fi
    return 0
}

# Validate directory permissions
# Usage: validate_dir_permissions <directory>
# Returns: 0 if directory is writable, 1 if not
validate_dir_permissions() {
    local dir="$1"
    # Create directory if it doesn't exist
    if [[ ! -d "${dir}" ]]; then
        mkdir -p "${dir}" || {
            error "Failed to create directory ${dir}"
            return 1
        }
    fi
    
    # Check if directory is writable
    if [[ ! -w "${dir}" ]]; then
        error "Directory ${dir} is not writable"
        return 1
    fi
    return 0
}

# Function to get kubeconfig from vault using inventory configuration
# Usage: get_vault_kubeconfig <cluster_name>
# Arguments:
#   cluster_name - Name of the cluster to get kubeconfig for
# Returns: 
#   - 0 if kubeconfig and SSH private key successfully retrieved and saved
#   - 1 if any step fails
# Description: Uses vault configuration to retrieve kubeconfig and SSH private key from vault's KV2 store
#             at static_secrets mount point. Saves kubeconfig to file in kube_configs directory
#             and exports KUBECONFIG environment variable. Also saves SSH private key with secure permissions.
get_vault_kubeconfig() {
    local cluster_name="$1"
    local vault_token response kubeconfig ssh_private_key
    
    # Validate cluster name
    validate_cluster_name "${cluster_name}" || return 1
    
    vault_token=$(get_vault_token) || return 1
    [[ -z "${VAULT_ADDR}" || -z "${VAULT_NAMESPACE}" || -z "${VAULT_PATH}" ]] && \
        error "Vault configuration not set. Run get_inventory_data first." && return 1

    log "INFO" "Retrieving kubeconfig and SSH private key from vault"
    # Construct KV2 path and get secrets
    local kv2_path="static_secrets/data/${VAULT_PATH}"
    response=$(curl_cmd -s \
        -H "X-Vault-Token: ${vault_token}" \
        -H "X-Vault-Namespace: ${VAULT_NAMESPACE}" \
        "${VAULT_ADDR}/v1/${kv2_path}") || error "Failed to retrieve secrets from Vault"

    # Extract kubeconfig
    kubeconfig=$("${JQ_CMD}" -r '.data.data.kubeconfig' <<< "${response}") || \
        error "Failed to parse kubeconfig from vault response"

    [[ -z "${kubeconfig}" || "${kubeconfig}" == "null" ]] && \
        error "No kubeconfig found in vault response" && return 1

    # Extract SSH private key
    ssh_private_key=$("${JQ_CMD}" -r '.data.data.ssh_private.key' <<< "${response}") || \
        error "Failed to parse SSH private key from vault response"

    [[ -z "${ssh_private_key}" || "${ssh_private_key}" == "null" ]] && \
        error "No SSH private key found in vault response" && return 1

    # Validate directory permissions before saving
    validate_dir_permissions "${KUBECONFIG_DIR}" || return 1
    
    # Save kubeconfig to file and export KUBECONFIG
    local kubeconfig_file="${KUBECONFIG_DIR}/${cluster_name}.kubeconfig"
    echo "${kubeconfig}" > "${kubeconfig_file}"
    export KUBECONFIG="${kubeconfig_file}"
    log "INFO" "Successfully saved kubeconfig to ${kubeconfig_file} and exported KUBECONFIG"
    
    # Save SSH private key to file with secure permissions
    local ssh_key_file="${KUBECONFIG_DIR}/${cluster_name}.sshpriv"
    echo "${ssh_private_key}" > "${ssh_key_file}"
    chmod 600 "${ssh_key_file}" || {
        error "Failed to set secure permissions on SSH private key file"
        return 1
    }
    log "INFO" "Successfully saved SSH private key to ${ssh_key_file} with secure permissions"
    
    return 0
}
