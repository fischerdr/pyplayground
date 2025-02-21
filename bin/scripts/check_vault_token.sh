#!/bin/bash
#
# Script Name: check_vault_token.sh
# Description: Validates Vault token for Portworx service account in OpenShift and displays token policies
# Last Modified: 2025-02-21
#
# Dependencies:
#   - oc (OpenShift CLI)
#   - jq (JSON processor)
#   - curl (HTTP client)
#   - base64 (Base64 encoder/decoder)
#
# Environment Variables:
#   None required - all parameters are passed via command line
#
# Required OpenShift Resources:
#   - Service Account with token
#   - Secret 'px-vault' containing:
#     - VAULT_ADDR
#     - VAULT_AUTH_MOUNT_PATH
#     - VAULT_NAMESPACE
#
# Usage:
#   ./check_vault_token.sh [-h] [namespace] [service_account] [authrole]
#
# Return Values:
#   0 - Success
#   1 - Error (missing dependencies, authentication failure, etc.)
#

# Exit on error and undefined variables
set -euo pipefail

# Configuration Parameters
readonly OCP_NAMESPACE="${1:-portworx}"
readonly OCP_SA="${2:-portworx}"
readonly OCP_AUTHROLE="${3:-default}"

# Function to log messages
log() {
    local level="$1"
    local message="$2"
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [$level] $message"
}

# Display usage information
usage() {
    cat << EOF
Usage: $(basename "$0") [-h] [namespace] [service_account] [authrole]

Validate Vault token for a service account in OpenShift namespace and display token policies.

Arguments:
    -h                      Show this help message and exit
    namespace               Namespace of the service account (default: portworx)
    service_account         Name of the service account (default: portworx)
    authrole               Vault authentication role (default: default)

Examples:
    # Using defaults
    $(basename "$0")
    
    # Specifying all parameters
    $(basename "$0") my-namespace my-service-account my-authrole
    
    # Show this help message
    $(basename "$0") -h

Notes:
    - Requires a px-vault secret in the specified namespace containing Vault configuration
    - Service account must have a valid token
    - Vault authentication role must be configured in Vault
    - Will display token policies, TTL, and renewable status upon successful authentication
EOF
    exit 1
}

# Validate prerequisites
validate_prerequisites() {
    local cmds=("oc" "jq" "curl" "base64")
    for cmd in "${cmds[@]}"; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            log "ERROR" "$cmd is required but not installed." >&2
            exit 1
        fi
    done
}

# Fetch service account token
fetch_sa_token() {
    log "INFO" "Fetching service account token..." >&2
    
    local token
    if ! token=$(oc get secret -n "$OCP_NAMESPACE" -ojson | \
        jq -re ".items[] | select(.metadata.name | test(\"${OCP_SA}-token\"))|.data.token| @base64d"); then
        log "ERROR" "Failed to get service account token" >&2
        exit 1
    fi
    
    if [[ -z "$token" ]]; then
        log "ERROR" "Service account token is empty" >&2
        exit 1
    fi
    
    SA_TOKEN="$token"
}

# Fetch Vault configuration
fetch_vault_config() {
    log "INFO" "Fetching Vault configuration..." >&2
    
    local url mount_path namespace
    
    url=$(oc get secret -n "$OCP_NAMESPACE" px-vault -ojson | \
        jq -er '.data.VAULT_ADDR | @base64d')
    mount_path=$(oc get secret -n "$OCP_NAMESPACE" px-vault -ojson | \
        jq -er '.data.VAULT_AUTH_MOUNT_PATH | @base64d')
    namespace=$(oc get secret -n "$OCP_NAMESPACE" px-vault -ojson | \
        jq -er '.data.VAULT_NAMESPACE | @base64d')
    
    if [[ -z "$url" || -z "$mount_path" || -z "$namespace" ]]; then
        log "ERROR" "Failed to get Vault configuration from px-vault secret" >&2
        exit 1
    fi
    
    # Set values in the global associative array
    VAULT_CONFIG["url"]="$url"
    VAULT_CONFIG["mount_path"]="$mount_path"
    VAULT_CONFIG["namespace"]="$namespace"
}

# Authenticate with Vault
authenticate_with_vault() {
    log "INFO" "Authenticating with Vault..." >&2
    
    local response
    response=$(curl -s --request POST --data "{\"jwt\": \"$SA_TOKEN\", \"role\": \"$OCP_AUTHROLE\"}" \
        -H "X-Vault-Namespace: ${VAULT_CONFIG[namespace]}" \
        "${VAULT_CONFIG[url]}/v1/auth/${VAULT_CONFIG[mount_path]}/login")
    
    if [[ $? -ne 0 ]]; then
        log "ERROR" "Failed to authenticate with Vault" >&2
        exit 1
    fi
    
    if echo "$response" | jq -e '.errors' >/dev/null; then
        log "ERROR" "Authentication failed: $(echo "$response" | jq -r '.errors[]')" >&2
        exit 1
    fi
    
    log "SUCCESS" "Successfully authenticated with Vault" >&2
    
    # Extract the client token
    local client_token
    client_token=$(echo "$response" | jq -r '.auth.client_token')
    if [[ -z "$client_token" || "$client_token" == "null" ]]; then
        log "ERROR" "No client token found in response" >&2
        exit 1
    fi
    
    VAULT_TOKEN="$client_token"
}

# Show Vault token policies
show_vault_policies() {
    log "INFO" "Fetching token policies..." >&2
    
    local response
    response=$(curl -s \
        -H "X-Vault-Token: $VAULT_TOKEN" \
        -H "X-Vault-Namespace: ${VAULT_CONFIG[namespace]}" \
        "${VAULT_CONFIG[url]}/v1/auth/token/lookup-self")
    
    if [[ $? -ne 0 ]]; then
        log "ERROR" "Failed to lookup token" >&2
        exit 1
    fi
    
    if echo "$response" | jq -e '.errors' >/dev/null; then
        log "ERROR" "Token lookup failed: $(echo "$response" | jq -r '.errors[]')" >&2
        exit 1
    fi
    
    log "INFO" "Token Metadata:" >&2
    echo "$response" | jq -r '
        "Token Policies: " + (.data.policies | join(", ")) +
        "\nToken TTL: " + (.data.ttl|tostring) + " seconds" +
        "\nToken Renewable: " + (.data.renewable|tostring)
    '
    
    # Store policies for later use
    VAULT_POLICIES=($(echo "$response" | jq -r '.data.policies[]'))
}

# Show policy contents
show_policy_contents() {
    log "INFO" "Fetching policy contents..." >&2
    
    for policy in "${VAULT_POLICIES[@]}"; do
        # Skip default policy as it's built into Vault
        if [[ "$policy" == "default" ]]; then
            continue
        fi
        
        log "INFO" "Policy: $policy" >&2
        local response
        response=$(curl -s \
            -H "X-Vault-Token: $VAULT_TOKEN" \
            -H "X-Vault-Namespace: ${VAULT_CONFIG[namespace]}" \
            "${VAULT_CONFIG[url]}/v1/sys/policy/$policy")
        
        if [[ $? -ne 0 ]]; then
            log "ERROR" "Failed to fetch policy: $policy" >&2
            continue
        fi
        
        if echo "$response" | jq -e '.errors' >/dev/null; then
            log "ERROR" "Failed to fetch policy $policy: $(echo "$response" | jq -r '.errors[]')" >&2
            continue
        fi
        
        echo -e "\nPolicy: $policy"
        echo "================="
        echo "$response" | jq -r '.data.rules // .data.policy' | sed 's/^/  /'
    done
}

# Main execution flow
main() {
    # Check for help flag
    if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
        usage
    fi
    validate_prerequisites
    # Global variable for service account token
    local SA_TOKEN
    fetch_sa_token
    # Declare global associative array for Vault configuration
    declare -A VAULT_CONFIG
    fetch_vault_config
    # Global variable for Vault token
    local VAULT_TOKEN
    # Global array for policy names
    local VAULT_POLICIES
    authenticate_with_vault
    show_vault_policies
    show_policy_contents
}

# Execute script
main "$@"