#!/usr/bin/env bash
#
# Script: test_kubeconfigs.sh
# Description: Tests kubeconfig files in a directory to ensure they work and have valid SSL certificates
# Usage: ./test_kubeconfigs.sh [directory]
#
# Examples:
#   ./test_kubeconfigs.sh /path/to/kubeconfigs
#   ./test_kubeconfigs.sh  # Uses default directory ./kube_configs
#
# Dependencies:
#   - kubectl: for testing kubeconfig files
#   - openssl: for testing SSL certificates
#
# Exit Codes:
#   - 0: All tests passed
#   - 1: General error
#   - 2: Missing required commands
#   - 3: Invalid directory

# Enable strict mode
set -euo pipefail
IFS=$'\n\t'

# Enable debug mode if requested
[[ "${DEBUG:-}" == "true" ]] && set -x

# Global constants
readonly DEFAULT_KUBECONFIG_DIR="kube_configs"
readonly KUBECTL_CMD="kubectl"
readonly OPENSSL_CMD="openssl"
readonly RESULTS_FILE="kubeconfig_test_results.txt"
readonly SUCCESS_MARKER="✅"
readonly FAILURE_MARKER="❌"

# Logging function
# Usage: log <level> <message>
# Example: log "INFO" "Starting script"
log() {
    local level="$1"
    shift
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [${level}] $*" >&2
}

# Error handling function
# Usage: error <message>
# Example: error "Failed to access directory"
error() {
    log "ERROR" "$1"
    return 1
}

# Warning function
# Usage: warning <message>
# Example: warning "No kubeconfig files found"
warning() {
    log "WARNING" "$1"
}

# Function to check if required commands exist
# Usage: check_requirements
# Returns: 0 if all required commands exist, 2 otherwise
check_requirements() {
    local required_cmds=("${KUBECTL_CMD}" "${OPENSSL_CMD}")
    local missing_cmds=()
    
    for cmd in "${required_cmds[@]}"; do
        if ! command -v "${cmd}" >/dev/null; then
            missing_cmds+=("${cmd}")
        fi
    done
    
    if [[ ${#missing_cmds[@]} -gt 0 ]]; then
        log "ERROR" "Required commands not found: ${missing_cmds[*]}"
        log "ERROR" "Please install the missing commands and try again"
        return 2
    fi
    
    log "INFO" "All required commands are available"
    return 0
}

# Function to validate directory
# Usage: validate_directory <directory>
# Returns: 0 if directory is valid, 3 otherwise
validate_directory() {
    local dir="$1"
    
    if [[ ! -d "${dir}" ]]; then
        error "Directory does not exist: ${dir}"
        return 3
    fi
    
    if [[ ! -r "${dir}" ]]; then
        error "Directory is not readable: ${dir}"
        return 3
    fi
    
    log "INFO" "Directory is valid: ${dir}"
    return 0
}

# Function to test a kubeconfig file
# Usage: test_kubeconfig <kubeconfig_file>
# Returns: 0 if kubeconfig is valid, 1 otherwise
test_kubeconfig() {
    local kubeconfig_file="$1"
    local kubeconfig_name
    kubeconfig_name=$(basename "${kubeconfig_file}")
    local result_line="${kubeconfig_name}"
    local test_passed=true
    local server_url
    local cert_data
    
    log "INFO" "Testing kubeconfig: ${kubeconfig_file}"
    
    # Test 1: Check if the file is a valid kubeconfig
    if ! KUBECONFIG="${kubeconfig_file}" "${KUBECTL_CMD}" config view --raw &>/dev/null; then
        log "ERROR" "Invalid kubeconfig file: ${kubeconfig_file}"
        result_line="${result_line} | Invalid kubeconfig ${FAILURE_MARKER}"
        test_passed=false
    else
        # Extract server URL from kubeconfig
        server_url=$(KUBECONFIG="${kubeconfig_file}" "${KUBECTL_CMD}" config view --raw -o jsonpath='{.clusters[0].cluster.server}')
        
        # Test 2: Check if kubectl can connect to the server
        if ! KUBECONFIG="${kubeconfig_file}" "${KUBECTL_CMD}" cluster-info &>/dev/null; then
            log "ERROR" "Cannot connect to cluster: ${server_url}"
            result_line="${result_line} | Connection failed ${FAILURE_MARKER}"
            test_passed=false
        else
            result_line="${result_line} | Connection successful ${SUCCESS_MARKER}"
            
            # Test 3: Check SSL certificate
            cert_data=$(KUBECONFIG="${kubeconfig_file}" "${KUBECTL_CMD}" config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')
            
            if [[ -n "${cert_data}" ]]; then
                # Decode and verify certificate
                if ! echo "${cert_data}" | base64 --decode | "${OPENSSL_CMD}" x509 -noout -text &>/dev/null; then
                    log "ERROR" "Invalid SSL certificate in kubeconfig: ${kubeconfig_file}"
                    result_line="${result_line} | Invalid SSL cert ${FAILURE_MARKER}"
                    test_passed=false
                else
                    # Check certificate expiration
                    local cert_expiry
                    cert_expiry=$(echo "${cert_data}" | base64 --decode | "${OPENSSL_CMD}" x509 -noout -enddate | cut -d= -f2)
                    local expiry_timestamp
                    expiry_timestamp=$(date -d "${cert_expiry}" +%s)
                    local current_timestamp
                    current_timestamp=$(date +%s)
                    local days_remaining
                    days_remaining=$(( (expiry_timestamp - current_timestamp) / 86400 ))
                    
                    if [[ ${days_remaining} -lt 30 ]]; then
                        log "WARNING" "SSL certificate will expire in ${days_remaining} days: ${kubeconfig_file}"
                        result_line="${result_line} | SSL cert expires in ${days_remaining} days ⚠️"
                    else
                        result_line="${result_line} | SSL cert valid (${days_remaining} days) ${SUCCESS_MARKER}"
                    fi
                fi
            else
                log "WARNING" "No certificate-authority-data found in kubeconfig: ${kubeconfig_file}"
                result_line="${result_line} | No SSL cert data ⚠️"
            fi
        fi
    fi
    
    # Write result to results file
    echo "${result_line}" >> "${RESULTS_FILE}"
    
    if [[ "${test_passed}" == "true" ]]; then
        return 0
    else
        return 1
    fi
}

# Main function
# Usage: main <directory>
main() {
    local kubeconfig_dir="${1:-${DEFAULT_KUBECONFIG_DIR}}"
    local kubeconfig_files=()
    local valid_count=0
    local invalid_count=0
    
    # Check requirements
    check_requirements || return $?
    
    # Validate directory
    validate_directory "${kubeconfig_dir}" || return $?
    
    # Find kubeconfig files
    log "INFO" "Searching for kubeconfig files in ${kubeconfig_dir}"
    while IFS= read -r -d '' file; do
        kubeconfig_files+=("${file}")
    done < <(find "${kubeconfig_dir}" -type f -print0)
    
    if [[ ${#kubeconfig_files[@]} -eq 0 ]]; then
        warning "No files found in ${kubeconfig_dir}"
        return 0
    fi
    
    log "INFO" "Found ${#kubeconfig_files[@]} files to test"
    
    # Initialize results file
    echo "# Kubeconfig Test Results - $(date)" > "${RESULTS_FILE}"
    echo "# Directory: ${kubeconfig_dir}" >> "${RESULTS_FILE}"
    echo "# ----------------------------------------" >> "${RESULTS_FILE}"
    
    # Test each kubeconfig file
    for kubeconfig_file in "${kubeconfig_files[@]}"; do
        if test_kubeconfig "${kubeconfig_file}"; then
            valid_count=$((valid_count + 1))
        else
            invalid_count=$((invalid_count + 1))
        fi
    done
    
    # Write summary to results file
    echo "# ----------------------------------------" >> "${RESULTS_FILE}"
    echo "# Summary: ${valid_count} valid, ${invalid_count} invalid" >> "${RESULTS_FILE}"
    
    log "INFO" "Testing complete. Results saved to ${RESULTS_FILE}"
    log "INFO" "Summary: ${valid_count} valid, ${invalid_count} invalid kubeconfig files"
    
    if [[ ${invalid_count} -gt 0 ]]; then
        return 1
    fi
    
    return 0
}

# Run main function with provided arguments
main "$@"
