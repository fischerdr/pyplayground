#!/bin/bash
#
# Description: This script checks S3 and Vault authentication for all Portworx pods in an OpenShift cluster.
#
# Usage: ./chkauths3.sh <kubeconfig_file>
#        DEBUG=1 ./chkauths3.sh <kubeconfig_file>  (for verbose debug logging)
#

set -euo pipefail

# --- Constants ---
readonly OC="oc"
readonly MAX_PARALLEL=10

# --- Logging Functions ---

# Generic log function
# Usage: log "LEVEL" "message"
log() {
    local level="$1"
    shift
    echo >&2 "[$(date +'%Y-%m-%d %H:%M:%S')] [${level}]" "$@"
}

# Log informational messages
log_info() {
    log "INFO" "$@"
}

# Log warning messages
log_warn() {
    log "WARN" "$@"
}

# Log error messages and exit
log_error() {
    log "ERROR" "$@"
    exit 1
}

# Log debug messages (only if DEBUG is set)
log_debug() {
    # This function is redefined in main() if DEBUG is set.
    :
}

# --- Script Functions ---

# Processes a single Portworx pod to validate credentials and Vault login.
# Arguments:
#   $1: pod name
#   $2: temporary directory path
#   $3: Portworx authentication token
process_pod() {
    local pod="$1"
    local tmp_dir="$2"
    local px_token="$3"
    local stc_node
    local s3val

    # Get node name for this pod
    stc_node=$(${OC} get -n portworx -o json "${pod}" | jq -er '.spec.nodeName' 2>/dev/null || echo "unknown")
    log_debug "Pod ${pod} is on node ${stc_node}"

    # Validate S3 credentials safely and check exit code
    local s3val
    local s3val_exit_code=0
    # shellcheck disable=SC2016
    s3val=$(${OC} -n portworx -c portworx exec -i "${pod}" -- \
        bash -c 'export PXCTL_AUTH_TOKEN="$1" && /opt/pwx/bin/pxctl credentials validate px-snap-creds' \
        _ "${px_token}" 2>&1) || s3val_exit_code=$?
    log_debug "Validating s3 credentials for ${pod}"

    # Check credential validation: exit code must be 0 AND success string must be present.
    if [[ ${s3val_exit_code} -eq 0 ]] && [[ "${s3val}" =~ "successfully" ]]; then
        log_debug "S3 credential validation for ${pod} succeeded."
        echo "pod ${pod} verified" >>"${tmp_dir}/success"
    else
        log_debug "S3 credential validation for ${pod} failed. Exit code: ${s3val_exit_code}"
        local s3_failure_reason
        if [[ ${s3val_exit_code} -ne 0 ]]; then
            s3_failure_reason="command failed with exit code ${s3val_exit_code}"
        else
            s3_failure_reason="command succeeded but success string was not in output"
        fi

        # Use printf to format the entire multi-line output into a single, atomic write.
        # This is more robust against parallel write race conditions than multiple echo commands.
        # The extra \n at the end adds a blank line between failure entries for readability.
        printf "node: %s pod %s s3 validate %s. Output:\n%s\n\n" \
            "${stc_node}" \
            "${pod}" \
            "${s3_failure_reason}" \
            "$(echo "${s3val}" | sed 's/^/    /')" \
            >>"${tmp_dir}/failure"
    fi

    # Run vault login and check command exit status
    local vault_output
    local vault_exit_code=0
    # shellcheck disable=SC2016
    # The `|| vault_exit_code=$?` part captures non-zero exit codes from the command.
    vault_output=$(${OC} -n portworx -c portworx exec -i "${pod}" -- \
        bash -c 'export PXCTL_AUTH_TOKEN="$1" && /opt/pwx/bin/pxctl secrets vault login' \
        _ "${px_token}" 2>&1) || vault_exit_code=$?

    # Filter the known informational warning message from the output
    local vault_output_filtered
    vault_output_filtered=$(echo "${vault_output}" | grep -vF '** WARNING' || true)

    # Check for success: exit code must be 0 AND the success string must be present.
    if [[ ${vault_exit_code} -eq 0 ]] && [[ "${vault_output_filtered}" =~ "Successfully authenticated with Vault" ]]; then
        log_debug "Vault login for ${pod} command succeeded."
        # Success: Do nothing further.
    else
        # Failure: Log details for this pod.
        log_debug "Vault login for ${pod} failed. Exit code: ${vault_exit_code}"
        
        local vault_failure_reason
        if [[ ${vault_exit_code} -ne 0 ]]; then
            vault_failure_reason="command failed with exit code ${vault_exit_code}"
        else
            vault_failure_reason="command succeeded but success string was not in output"
        fi

        # Use printf for a single, atomic write to prevent interleaved output.
        # The extra \n at the end adds a blank line between failure entries for readability.
        printf "node: %s pod %s vault login %s. Output:\n%s\n\n" \
            "${stc_node}" \
            "${pod}" \
            "${vault_failure_reason}" \
            "$(echo "${vault_output_filtered}" | sed 's/^/    /')" \
            >>"${tmp_dir}/failure"
    fi
}

# --- Main Function ---

main() {
    # Check for kubeconfig argument
    if [[ -z "${1:-}" ]]; then
        echo >&2 "Usage: $0 <kubeconfig_file>"
        exit 1
    fi

    local ocp_cluster="$1"
    export KUBECONFIG="${ocp_cluster}"

    # Setup temporary directory for parallel processing results
    local tmp_dir
    tmp_dir=$(mktemp -d)
    trap 'rm -rf "${tmp_dir}"' EXIT

    # Enable debug logging if DEBUG is set
    if [[ -n "${DEBUG:-}" ]]; then
        local debug_log="${tmp_dir}/debug.log"
        exec 3>>"${debug_log}"
        log_debug() { log "DEBUG" "$@" >&3; }
        log_info "Debug logging enabled. Log file: ${debug_log}"
    fi

    log_info "Validating cluster connection..."
    local ck_host
    ck_host=$(${OC} config view --minify -ojsonpath='{.clusters[0].cluster.server}' | cut -d '/' -f3 | cut -d ':' -f1)
    if ! nc -z -w5 "${ck_host}" 6443; then
        log_error "Cluster ${ck_host} is unreachable on port 6443"
    fi
    log_info "Cluster connection successful."

    log_info "Checking for Portworx namespace..."
    local px_ns
    px_ns=$(${OC} get namespace portworx --no-headers --output=go-template='{{.metadata.name}}' 2>/dev/null)
    if [[ -z "${px_ns}" ]]; then
        log_error "Portworx namespace 'portworx' not found"
    fi
    log_info "Portworx namespace found: ${px_ns}"

    log_info "Checking for Vault secrets in namespace ${px_ns}..."
    local vault_secrets
    vault_secrets=$(${OC} get secrets -n "${px_ns}" -o custom-columns=NAME:.metadata.name --no-headers 2>/dev/null | grep -E '^(vault-auth-|px-vault-auth)')
    if [[ -z "${vault_secrets}" ]]; then
        log_error "No vault-auth-* or px-vault-auth-* secrets found in namespace ${px_ns}"
    fi
    log_info "Found Vault secrets."

    log_info "Getting Portworx StorageCluster..."
    local px_stc
    px_stc=$(${OC} get stc -n portworx --no-headers -o name 2>/dev/null)
    if [[ -z "${px_stc}" ]]; then
        log_error "No StorageCluster found in namespace ${px_ns}"
    fi
    log_info "Found StorageCluster."

    log_info "Getting Portworx admin token..."
    local px_token
    px_token=$(${OC} -n portworx get secrets px-admin-token -ojsonpath='{.data.auth-token}' 2>/dev/null | base64 -d)
    if [[ -z "${px_token}" ]]; then
        log_error "Could not retrieve Portworx admin token."
    fi
    log_info "Successfully retrieved Portworx admin token."

    log_info "Getting Portworx pods..."
    local -a pods=()
    while IFS= read -r pod; do
        pods+=("$pod")
    done < <(${OC} get pods -n portworx --selector='name==portworx' -o name --no-headers)

    if [[ ${#pods[@]} -eq 0 ]]; then
        log_error "No Portworx pods found in namespace ${px_ns}"
    fi

    log_info "Processing ${#pods[@]} Portworx pods..."

    # Initialize results files
    : >"${tmp_dir}/success"
    : >"${tmp_dir}/failure"

    # Process pods in parallel with controlled concurrency
    for pod in "${pods[@]}"; do
        while [[ $(jobs -r -p | wc -l) -ge ${MAX_PARALLEL} ]]; do
            sleep 0.1
        done
        process_pod "${pod}" "${tmp_dir}" "${px_token}" &
    done
    wait

    # Display final results
    if [[ -s "${tmp_dir}/failure" ]]; then
        local failed_count
        # Count the number of failure entries by counting lines that start with "node:",
        # which is more accurate than counting all lines in the file (wc -l).
        failed_count=$(grep -c '^node:' "${tmp_dir}/failure")
        echo >&2 "" # Add a blank line for spacing before the summary
        log_warn "${#pods[@]} pods processed with ${failed_count} failure(s):"
        cat "${tmp_dir}/failure" >&2
        
        exit 1
    else
        # Successful run: no output
        exit 0
    fi
}

# --- Script execution ---
main "$@"
