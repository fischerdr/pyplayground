#!/bin/bash

# check_vault_token.sh
#
# This script checks a Vault token's information and permissions using the Vault HTTP API.
# It verifies the token's validity and displays its associated metadata and capabilities.
#
# Usage:
#   ./check_vault_token.sh -t <token> -a <vault_addr>
#   Example: ./check_vault_token.sh -t hvs.dumy123 -a http://vault.example.com:8200

# Function declarations
function print_usage() {
    echo "Usage: $0 -t <token> -a <vault_addr>"
    echo "Options:"
    echo "  -t    Vault token to check"
    echo "  -a    Vault server address (e.g., http://vault.example.com:8200)"
    echo "  -h    Show this help message"
}

function check_dependencies() {
    if ! command -v curl &> /dev/null; then
        echo "Error: curl is required but not installed."
        exit 1
    fi
    if ! command -v jq &> /dev/null; then
        echo "Error: jq is required but not installed."
        exit 1
    fi
}

function check_token_info() {
    local token="$1"
    local vault_addr="$2"
    
    # Check token information
    local response
    response=$(curl -s -H "X-Vault-Token: $token" \
        "$vault_addr/v1/auth/token/lookup-self" | jq '.')
    
    if echo "$response" | jq -e '.errors' >/dev/null; then
        echo "Error checking token:"
        echo "$response" | jq -r '.errors[]'
        return 1
    fi
    
    echo "Token Information:"
    echo "$response" | jq '.'
}

function check_token_capabilities() {
    local token="$1"
    local vault_addr="$2"
    local path="$3"
    
    local response
    response=$(curl -s -H "X-Vault-Token: $token" \
        --request POST \
        --data "{\"path\": \"$path\"}" \
        "$vault_addr/v1/sys/capabilities-self" | jq '.')
    
    if echo "$response" | jq -e '.errors' >/dev/null; then
        echo "Error checking capabilities:"
        echo "$response" | jq -r '.errors[]'
        return 1
    fi
    
    echo "Token Capabilities for path '$path':"
    echo "$response" | jq '.'
}

# Main script execution
check_dependencies

# Parse command line arguments
while getopts "t:a:h" opt; do
    case "$opt" in
        t) TOKEN="$OPTARG" ;;
        a) VAULT_ADDR="$OPTARG" ;;
        h) print_usage; exit 0 ;;
        ?) print_usage; exit 1 ;;
    esac
done

# Validate required parameters
if [ -z "$TOKEN" ] || [ -z "$VAULT_ADDR" ]; then
    echo "Error: Missing required parameters"
    print_usage
    exit 1
fi

# Check token info and capabilities
check_token_info "$TOKEN" "$VAULT_ADDR"
if [ $? -eq 0 ]; then
    # Check capabilities for common paths
    for path in "secret/" "auth/" "sys/auth" "sys/policies"; do
        check_token_capabilities "$TOKEN" "$VAULT_ADDR" "$path"
    done
fi
