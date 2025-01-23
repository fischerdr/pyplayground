#!/bin/bash
#
# Script: annonupdate.sh
# Description: Updates Portworx annotations using vault-stored kubeconfig
# Usage: ./annonupdate.sh <cluster_name>
#
# Dependencies:
#   - curl: for API requests
#   - jq: for JSON parsing
#   - nc: for network connectivity checks
#   - oc: for OpenShift/Kubernetes operations
#
# Environment Variables:
#   - VAULT_TOKEN: Optional, vault token for authentication
#   - DEBUG: Optional, set to "true" for debug output

# Enable strict mode
set -euo pipefail
IFS=$'\n\t'

# Enable debug mode if requested
[[ "${DEBUG:-}" == "true" ]] && set -x

# Global constants
readonly OC_CMD="/usr/bin/oc"
readonly CURL_CMD="/usr/bin/curl"
readonly JQ_CMD="/usr/bin/jq"
readonly VAULT_TOKEN_FILE="/src/vault_secrets/ansible-token"
readonly PORTWORX_NAMESPACE="portworx"
readonly CURL_TIMEOUT=30

# Portworx annotation constants
readonly PORTWORX_ANNOTATIONS=(
    "operator.libopenstorage.org/common-image-registries=gcr.io,k8s.gcr.io"
    "operator.libopenstorage.org/cordoned-restart-delay-secs=30"
    "portworx.io/scc-priority=3"
    "portworx.io/portworx-proxy=false"
    "portworx.io/preflight-check=false"
    "portworx.io/disable-storage-class=true"
)

# Logging function
# Usage: log <level> <message>
# Example: log "INFO" "Starting script"
log() {
    local level="$1"
    shift
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [${level}] $*" >&2
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
# Description: Verifies that curl, jq, nc, and oc commands are available in the system
check_requirements() {
    local required_cmds=(curl jq nc oc)
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

# Function to get kubeconfig from vault using inventory configuration
# Usage: get_vault_kubeconfig
# Returns: 
#   - 0 if kubeconfig successfully retrieved and saved
#   - 1 if any step fails
# Description: Uses vault configuration to retrieve kubeconfig from vault's KV2 store
#             at static_secrets mount point. Saves kubeconfig to temp file and sets
#             KUBECONFIG environment variable
get_vault_kubeconfig() {
    local vault_token response kubeconfig kubeconfig_file
    
    vault_token=$(get_vault_token) || return 1
    [[ -z "${VAULT_ADDR}" || -z "${VAULT_NAMESPACE}" || -z "${VAULT_PATH}" ]] && \
        error "Vault configuration not set. Run get_inventory_data first." && return 1

    log "INFO" "Retrieving kubeconfig from vault"
    # Construct KV2 path and get kubeconfig
    local kv2_path="static_secrets/data/${VAULT_PATH}"
    response=$(curl_cmd -s \
        -H "X-Vault-Token: ${vault_token}" \
        -H "X-Vault-Namespace: ${VAULT_NAMESPACE}" \
        "${VAULT_ADDR}/v1/${kv2_path}") || error "Failed to retrieve kubeconfig from Vault"

    kubeconfig=$("${JQ_CMD}" -r '.data.data.kubeconfig' <<< "${response}") || \
        error "Failed to parse kubeconfig from vault response"

    [[ -z "${kubeconfig}" || "${kubeconfig}" == "null" ]] && \
        error "No kubeconfig found in vault response" && return 1

    # Save kubeconfig to temporary file
    kubeconfig_file="$(mktemp)"
    echo "${kubeconfig}" > "${kubeconfig_file}"
    export KUBECONFIG="${kubeconfig_file}"
    log "INFO" "Successfully retrieved and saved kubeconfig"
    return 0
}

# Function to update portworx annotations
# Usage: update_portworx_annotations
# Returns: 
#   - 0 if annotations successfully updated
#   - 1 if StorageCluster not found or update fails
# Description: Updates various portworx annotations on the StorageCluster
#             resource in the portworx namespace
update_portworx_annotations() {
    local stc
    
    log "INFO" "Checking for StorageCluster in namespace ${PORTWORX_NAMESPACE}"
    stc=$("${OC_CMD}" get stc -n "${PORTWORX_NAMESPACE}" --no-headers -o name 2>/dev/null)
    [[ -z "${stc}" ]] && error "No StorageCluster found in namespace ${PORTWORX_NAMESPACE}" && return 1

    log "INFO" "Updating StorageCluster annotations"
    # Update annotations
    "${OC_CMD}" annotate "${stc}" -n "${PORTWORX_NAMESPACE}" --overwrite "${PORTWORX_ANNOTATIONS[@]}" || \
        { error "Failed to update annotations"; return 1; }
    
    log "INFO" "Successfully updated StorageCluster annotations"
    return 0
}

# Cleanup function
# Usage: cleanup
# Returns: None
# Description: Removes temporary kubeconfig file if it exists.
#             Designed to be called by trap on script exit
cleanup() {
    if [[ -n "${KUBECONFIG:-}" && -f "${KUBECONFIG}" ]]; then
        log "INFO" "Cleaning up temporary kubeconfig file"
        rm -f "${KUBECONFIG}"
    fi
}

# Main execution function
# Usage: main <cluster_name>
# Arguments:
#   cluster_name - Name of the cluster to update portworx annotations for
# Returns: 
#   - 0 if all operations succeed
#   - 1 if any operation fails
# Description: Main script execution flow. Gets vault configuration from inventory,
#             retrieves kubeconfig from vault, and updates portworx annotations
main() {
    local cluster_name="$1"
    : "${cluster_name:?Usage: $0 <cluster_name>}"

    log "INFO" "Starting portworx annotation update for cluster ${cluster_name}"
    
    trap cleanup EXIT
    check_requirements || exit 1
    get_inventory_data "${cluster_name}" || exit 1
    get_vault_kubeconfig || exit 1

    # Check portworx namespace and update annotations
    "${OC_CMD}" get namespace "${PORTWORX_NAMESPACE}" --no-headers \
        --output="go-template={{.metadata.name}}" &>/dev/null || \
        { error "Portworx namespace not found"; exit 1; }

    update_portworx_annotations || { error "Failed to update portworx annotations"; exit 1; }
    log "INFO" "Successfully completed all operations"
}

# Execute main function
main "$@"