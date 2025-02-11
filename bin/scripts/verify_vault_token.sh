#!/bin/bash

# Vault & Kubernetes Authentication Test Script

# Exit on error and undefined variables
set -euo pipefail

# Configuration Parameters
VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"        # Vault address
K8S_AUTH_PATH="${K8S_AUTH_PATH:-kubernetes}"            # Vault Kubernetes auth path
K8S_ROLE="${K8S_ROLE:-default}"                          # Vault role for authentication
JWT_TOKEN_PATH="${JWT_TOKEN_PATH:-/var/run/secrets/kubernetes.io/serviceaccount/token}" # JWT token path
NAMESPACE_PATH="${NAMESPACE_PATH:-/var/run/secrets/kubernetes.io/serviceaccount/namespace}"

# Function to log messages
log() {
  local level="$1"
  local message="$2"
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] [$level] $message"
}

# Validate prerequisites
validate_prerequisites() {
  command -v curl >/dev/null 2>&1 || { log "ERROR" "curl is required but not installed."; exit 1; }
  command -v jq >/dev/null 2>&1 || { log "ERROR" "jq is required but not installed."; exit 1; }
}

# Fetch Service Account JWT Token
fetch_jwt_token() {
  if [[ ! -f "$JWT_TOKEN_PATH" ]]; then
    log "ERROR" "JWT token file not found at $JWT_TOKEN_PATH"
    exit 1
  fi
  cat "$JWT_TOKEN_PATH"
}

# Authenticate with Vault using Kubernetes Auth Method
authenticate_with_vault() {
  local jwt_token="$1"

  log "INFO" "Authenticating with Vault at $VAULT_ADDR using role '$K8S_ROLE'..."

  local response
  response=$(curl -s --request POST \
    --data "{\"role\": \"$K8S_ROLE\", \"jwt\": \"$jwt_token\"}" \
    "$VAULT_ADDR/v1/auth/$K8S_AUTH_PATH/login")

  if echo "$response" | jq -e '.errors' >/dev/null; then
    log "ERROR" "Authentication failed: $(echo "$response" | jq -r '.errors[]')"
    exit 1
  fi

  local client_token
  client_token=$(echo "$response" | jq -r '.auth.client_token')

  if [[ -z "$client_token" || "$client_token" == "null" ]]; then
    log "ERROR" "No client token received from Vault."
    exit 1
  fi

  log "SUCCESS" "Authenticated successfully. Client Token: $client_token"
  echo "$client_token"
}

# Validate Vault Token
validate_vault_token() {
  local token="$1"

  log "INFO" "Validating Vault token..."

  local response
  response=$(curl -s --header "X-Vault-Token: $token" "$VAULT_ADDR/v1/auth/token/lookup-self")

  if echo "$response" | jq -e '.errors' >/dev/null; then
    log "ERROR" "Token validation failed: $(echo "$response" | jq -r '.errors[]')"
    exit 1
  fi

  local policies
  policies=$(echo "$response" | jq -r '.data.policies[]')

  log "SUCCESS" "Token is valid. Associated Policies: $policies"
}

# Main Execution Flow
main() {
  validate_prerequisites

  local jwt_token
  jwt_token=$(fetch_jwt_token)

  local vault_token
  vault_token=$(authenticate_with_vault "$jwt_token")

  validate_vault_token "$vault_token"
}

# Execute script
main "$@"
