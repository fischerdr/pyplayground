#!/usr/bin/env bash
#
# Script Name: renew_vault_token.sh
# Description: Checks a Vault token's validity and renews it if it's under 20 minutes from expiration
# Last Modified: 2025-04-04
#
# Dependencies:
#   - curl (HTTP client)
#   - jq (JSON processor)
#
# Usage:
#   ./renew_vault_token.sh /path/to/token/file [vault_addr]
#
# Return Values:
#   0 - Success (token valid or successfully renewed)
#   1 - Error (missing dependencies, token invalid, renewal failed, etc.)
#

# Exit on error and undefined variables
set -euo pipefail

# Configuration Parameters
readonly TOKEN_FILE="${1:-}"
readonly VAULT_ADDR="${2:-${VAULT_ADDR:-http://127.0.0.1:8200}}"
readonly RENEWAL_THRESHOLD=1200  # 20 minutes in seconds

# Logging function
log() {
    local level="$1"
    local message="$2"
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [$level] $message"
}

# Display usage information
usage() {
    cat << EOF
Usage: $(basename "$0") TOKEN_FILE [VAULT_ADDR]

Check a Vault token's validity and renew it if it's under 20 minutes from expiration.

Arguments:
    TOKEN_FILE              Path to file containing the Vault token
    VAULT_ADDR              Vault server address (default: http://127.0.0.1:8200 or VAULT_ADDR env var)

Examples:
    # Using token file and default Vault address
    $(basename "$0") /path/to/token/file
    
    # Specifying both token file and Vault address
    $(basename "$0") /path/to/token/file https://vault.example.com:8200
    
    # Using VAULT_ADDR environment variable
    export VAULT_ADDR="https://vault.example.com:8200"
    $(basename "$0") /path/to/token/file

Notes:
    - The token file should contain only the token string
    - The script will update the token file if renewal is successful
    - Requires curl and jq to be installed
EOF
    exit 1
}

# Validate prerequisites
validate_prerequisites() {
    local cmds=("curl" "jq")
    for cmd in "${cmds[@]}"; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            log "ERROR" "$cmd is required but not installed."
            exit 1
        fi
    done
}

# Validate input parameters
validate_input() {
    if [[ -z "$TOKEN_FILE" ]]; then
        log "ERROR" "Token file path is required."
        usage
    fi

    if [[ ! -f "$TOKEN_FILE" ]]; then
        log "ERROR" "Token file does not exist: $TOKEN_FILE"
        exit 1
    fi

    if [[ ! -r "$TOKEN_FILE" ]]; then
        log "ERROR" "Token file is not readable: $TOKEN_FILE"
        exit 1
    fi

    if [[ ! -w "$TOKEN_FILE" ]]; then
        log "ERROR" "Token file is not writable: $TOKEN_FILE"
        exit 1
    fi
}

# Read token from file
read_token() {
    local token
    token=$(cat "$TOKEN_FILE")
    
    if [[ -z "$token" ]]; then
        log "ERROR" "Token file is empty: $TOKEN_FILE"
        exit 1
    fi
    
    echo "$token"
}

# Check token validity and TTL
check_token() {
    local token="$1"
    local response
    
    log "INFO" "Checking token validity and TTL..."
    
    response=$(curl -s -X GET \
        -H "X-Vault-Token: $token" \
        "$VAULT_ADDR/v1/auth/token/lookup-self")
    
    if echo "$response" | jq -e '.errors' >/dev/null; then
        log "ERROR" "Token validation failed: $(echo "$response" | jq -r '.errors[]')"
        exit 1
    fi
    
    local ttl
    ttl=$(echo "$response" | jq -r '.data.ttl')
    
    if [[ "$ttl" == "null" ]]; then
        log "ERROR" "Could not determine token TTL"
        exit 1
    fi
    
    local renewable
    renewable=$(echo "$response" | jq -r '.data.renewable')
    
    if [[ "$renewable" != "true" ]]; then
        log "WARNING" "Token is not renewable. TTL: $ttl seconds"
        return 1
    fi
    
    log "INFO" "Token is valid. TTL: $ttl seconds. Renewable: $renewable"
    echo "$ttl"
}

# Renew token
renew_token() {
    local token="$1"
    local response
    
    log "INFO" "Renewing token..."
    
    response=$(curl -s -X POST \
        -H "X-Vault-Token: $token" \
        "$VAULT_ADDR/v1/auth/token/renew-self")
    
    if echo "$response" | jq -e '.errors' >/dev/null; then
        log "ERROR" "Token renewal failed: $(echo "$response" | jq -r '.errors[]')"
        exit 1
    fi
    
    local new_token
    new_token=$(echo "$response" | jq -r '.auth.client_token')
    
    if [[ "$new_token" == "null" || -z "$new_token" ]]; then
        # If no new token is returned, the original token is still valid but with extended TTL
        log "INFO" "Token renewed successfully. Using original token with extended TTL."
        new_token="$token"
    else
        log "INFO" "Token renewed successfully. New token received."
    fi
    
    local new_ttl
    new_ttl=$(echo "$response" | jq -r '.auth.lease_duration')
    
    log "INFO" "New token TTL: $new_ttl seconds"
    echo "$new_token"
}

# Update token file
update_token_file() {
    local token="$1"
    
    log "INFO" "Updating token file..."
    
    # Create a temporary file in the same directory for atomic write
    local tmp_file
    tmp_file="${TOKEN_FILE}.tmp"
    
    echo "$token" > "$tmp_file"
    mv "$tmp_file" "$TOKEN_FILE"
    
    log "INFO" "Token file updated successfully"
}

# Main execution flow
main() {
    # Check for help flag
    if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
        usage
    fi
    
    validate_prerequisites
    validate_input
    
    local token
    token=$(read_token)
    
    local ttl
    if ! ttl=$(check_token "$token"); then
        log "WARNING" "Token is not renewable. No action taken."
        exit 0
    fi
    
    # Check if token needs renewal
    if [[ "$ttl" -lt "$RENEWAL_THRESHOLD" ]]; then
        log "INFO" "Token TTL ($ttl seconds) is below threshold ($RENEWAL_THRESHOLD seconds). Renewing..."
        
        local new_token
        new_token=$(renew_token "$token")
        
        update_token_file "$new_token"
        
        log "SUCCESS" "Token renewed and updated successfully"
    else
        log "INFO" "Token TTL ($ttl seconds) is above threshold ($RENEWAL_THRESHOLD seconds). No renewal needed."
    fi
}

# Execute script
main "$@"
