#!/usr/bin/env bash

set -euo pipefail

# --- Constants ---
DEFAULT_PORTWORX_NAMESPACE="kube-system"
PORTWORX_PROVISIONER="pxd.portworx.com"
PORTWORX_POD_LABEL_SELECTOR="name=portworx,storage=true"
SCRIPT_NAME=$(basename "$0")

# --- Globals (populated by arguments) ---
KUBECONFIG_PATH=""
PX_NAMESPACE="${DEFAULT_PORTWORX_NAMESPACE}"
OUTPUT_FILE_BASE="px-volume-summary" # Base name, timestamp and .csv will be added
declare -a SKIP_NAMESPACE_PREFIXES=()
declare -a ENV_VARS_PXCTL=()
DEBUG_MODE=0
OUTPUT_TO_STDOUT=0

# --- Logging Functions ---
log_info() {
    echo >&2 "[INFO] [${SCRIPT_NAME}] $(date '+%Y-%m-%d %H:%M:%S') - $*"
}

log_debug() {
    if [[ "${DEBUG_MODE}" -eq 1 ]]; then
        echo >&2 "[DEBUG] [${SCRIPT_NAME}] $(date '+%Y-%m-%d %H:%M:%S') - $*"
    fi
}

log_error() {
    echo >&2 "[ERROR] [${SCRIPT_NAME}] $(date '+%Y-%m-%d %H:%M:%S') - $*"
}

usage() {
    cat <<EOF
Usage: ${SCRIPT_NAME} [OPTIONS]

Query Portworx PVs/PVCs, enrich with pxctl details, and output results in CSV format.

Options:
  --kubeconfig <path>     Path to the kubeconfig file. (Env: KUBECONFIG)
  --px-namespace <ns>     Namespace where Portworx pods are running. (Default: ${DEFAULT_PORTWORX_NAMESPACE})
  -o, --output-file <path> Base path for the output CSV file (without extension).
                           Relative paths are saved to ./tmp/. Timestamp and .csv are appended.
                           If not provided, output is to stdout.
  --skip-namespace-prefix <prefix>
                          Prefix of namespaces to skip (e.g., 'kube-'). Can be used multiple times.
  -e, --env-var <VAR=VALUE> Environment variable to set for pxctl. Can be used multiple times.
  --debug                 Enable debug logging.
  -h, --help              Show this help message.
EOF
    exit 0
}

# --- Helper Functions ---

# Checks if a string starts with any of the prefixes in an array
# $1: string to check
# $2: array of prefixes (passed by name)
string_starts_with_any_prefix() {
    local string_to_check="$1"
    local -n prefixes_array="$2" # Pass array by reference

    for prefix in "${prefixes_array[@]}"; do
        if [[ "${string_to_check}" == "${prefix}"* ]]; then
            return 0 # True, string starts with one of the prefixes
        fi
    done
    return 1 # False
}

# --- Core Logic Functions ---

find_portworx_pod() {
    local namespace="$1"
    log_info "Searching for Portworx pod with labels '${PORTWORX_POD_LABEL_SELECTOR}' in namespace '${namespace}'..."

    local pod_info
    if ! pod_info=$(kubectl --kubeconfig "${KUBECONFIG_PATH:-}" get pods -n "${namespace}" -l "${PORTWORX_POD_LABEL_SELECTOR}" -o json); then
        log_error "Failed to get pod information from Kubernetes for namespace '${namespace}'."
        return 1
    fi
    
    PX_POD_NAME=$(echo "$pod_info" | jq -e -r '.items[] | select(.status.phase=="Running") | .metadata.name' | head -n 1)
    if [[ -z "${PX_POD_NAME}" ]]; then
        log_error "No *running* Portworx pods found in namespace '${namespace}' with labels '${PORTWORX_POD_LABEL_SELECTOR}'."
        return 1
    fi

    PX_CONTAINER_NAME=$(echo "$pod_info" | jq -e -r --arg pod_name "$PX_POD_NAME" '.items[] | select(.metadata.name==$pod_name and .spec.containers and (.spec.containers | length > 0)) | .spec.containers[0].name')
    if [[ -z "${PX_CONTAINER_NAME}" ]]; then
        log_error "Portworx pod '${PX_POD_NAME}' found but has no containers defined or name could not be retrieved."
        return 1
    fi

    log_info "Found running Portworx pod: '${PX_POD_NAME}', container: '${PX_CONTAINER_NAME}'"
    return 0
}

get_portworx_sc_names() {
    log_debug "Fetching StorageClasses..."
    local sc_json
    if ! sc_json=$(kubectl --kubeconfig "${KUBECONFIG_PATH:-}" get sc -o json); then
        log_error "Failed to get StorageClasses from Kubernetes."
        # Depending on strictness, you might want to return 1 here or allow continuation
        # Python script allowed continuation if no SCs, so we do too.
        PORTWORX_SC_NAMES=()
        return 0 
    fi

    # Read sc names into the global array PORTWORX_SC_NAMES
    readarray -t PORTWORX_SC_NAMES < <(echo "$sc_json" | jq -r --arg PROV "$PORTWORX_PROVISIONER" '.items[] | select(.provisioner==$PROV) | .metadata.name')

    if [[ ${#PORTWORX_SC_NAMES[@]} -eq 0 ]]; then
        log_info "No StorageClasses found with provisioner '${PORTWORX_PROVISIONER}'. Cannot identify Portworx volumes directly by SC."
        return 0 # Indicate success but no SCs
    fi
    log_info "Found ${#PORTWORX_SC_NAMES[@]} Portworx StorageClasses: ${PORTWORX_SC_NAMES[*]}"
    return 0
}

get_portworx_pvs() {
    log_debug "Fetching all PVs and filtering for Portworx..."
    local pvs_json
    if ! pvs_json=$(kubectl --kubeconfig "${KUBECONFIG_PATH:-}" get pv -o json); then
        log_error "Failed to get PersistentVolumes from Kubernetes."
        # Return empty or handle error to prevent further processing
        return 1 # Indicate failure
    fi

    # Build a jq filter for SC names
    local sc_names_jq_array="["
    if [[ ${#PORTWORX_SC_NAMES[@]} -gt 0 ]]; then
      for sc_name in "${PORTWORX_SC_NAMES[@]}"; do
          sc_names_jq_array+="\"${sc_name}\","
      done
      sc_names_jq_array="${sc_names_jq_array%,}]" # Remove trailing comma and close array
    else
        sc_names_jq_array="[]" # Empty array if no SCs
    fi
    
    # jq query to filter PVs and output essential fields as JSON lines
    # One PV per line, makes it easier to process in bash loop
    echo "$pvs_json" | jq -c --argjson sc_array "$sc_names_jq_array" --arg PROV "$PORTWORX_PROVISIONER" '
        .items[] |
        select(
            (.spec.storageClassName as $sc | IN($sc_array[]; $sc)) or
            (.spec.csi.driver == $PROV)
        ) |
        {
            pv_name: .metadata.name,
            capacity_bytes: (.spec.capacity.storage // "N/A"),
            claim_ref_namespace: (.spec.claimRef.namespace // ""),
            claim_ref_name: (.spec.claimRef.name // ""),
            storage_class_name: (.spec.storageClassName // "N/A"),
            csi_driver: (.spec.csi.driver // "N/A")
        }
    '
}

execute_pxctl_inspect() {
    local pv_name="$1"
    local px_ns="$2"
    local px_pod="$3"
    local px_container="$4"
    
    local env_exports_str=""
    if [[ ${#ENV_VARS_PXCTL[@]} -gt 0 ]]; then
        for var_assignment in "${ENV_VARS_PXCTL[@]}"; do
            # Basic quoting for safety. VAR="VALUE"
            env_exports_str+="export ${var_assignment%%=*}=\"${var_assignment#*=}\" && "
        done
    fi

    local base_command="pxctl volume inspect \"${pv_name}\" -j"
    local full_command_str="${env_exports_str}${base_command}"

    log_debug "Executing in pod '${px_pod}/${px_container}': ${full_command_str}"

    local output_stderr_file
    output_stderr_file=$(mktemp)
    local actual_exit_code=0
    local stdout_data=""

    # Capture stdout and stderr separately, and exit code
    # Simpler: redirect stderr to a file.
    if stdout_data=$(kubectl --kubeconfig "${KUBECONFIG_PATH:-}" exec -n "${px_ns}" "${px_pod}" -c "${px_container}" -- /bin/sh -c "${full_command_str}" 2> "${output_stderr_file}"); then
        log_debug "pxctl command for PV '${pv_name}' finished successfully."
    else
        actual_exit_code=$?
        # This log will be more generic; specific error details if any are in stderr_data
        log_info "pxctl command execution for PV '${pv_name}' failed with exit code ${actual_exit_code}."
    fi
    
    local stderr_data
    stderr_data=$(<"${output_stderr_file}")
    rm -f "${output_stderr_file}"

    if [[ -n "$stdout_data" ]]; then
        log_debug "pxctl stdout for PV '${pv_name}': ${stdout_data:0:500}..."
    fi
    if [[ -n "$stderr_data" ]]; then
        log_info "pxctl stderr for PV '${pv_name}': ${stderr_data:0:500}..." # Info, as python script logged as warning
    fi
    
    local pv_used_bytes="N/A"
    local ha_level="N/A"

    if [[ $actual_exit_code -eq 0 && -n "$stdout_data" ]]; then
        # Handle pxctl output possibly being a list with one item, or a direct object
        local first_char
        first_char=$(echo "$stdout_data" | head -c 1)
        local effective_json="$stdout_data"
        if [[ "$first_char" == "[" ]]; then
            # If it's an array, try to get the first element
            effective_json=$(echo "$stdout_data" | jq -r '.[0] // {}') # Fallback to empty obj if array is empty or not objects
        fi

        # Ensure effective_json is not empty before parsing
        if [[ -n "$effective_json" && "$effective_json" != "null" && "$effective_json" != "{}" ]]; then
            pv_used_bytes=$(echo "$effective_json" | jq -r '.usage // "N/A"')
            ha_level=$(echo "$effective_json" | jq -r '.spec.ha_level // "N/A"')
        else
            log_info "pxctl output for PV '${pv_name}' was JSON but not the expected format or was empty after potential array extraction."
        fi

    elif [[ $actual_exit_code -ne 0 ]]; then
        # This case is now handled by the initial 'else' block of the 'if kubectl exec ...'
        # but we can still log the stderr here if it's particularly relevant to parsing attempts.
        log_debug "pxctl command for PV '${pv_name}' had non-zero exit code ${actual_exit_code}. Stderr: ${stderr_data}"
    else
        # This case (actual_exit_code == 0 but no stdout_data) implies success but empty output from pxctl
        log_info "pxctl command for PV '${pv_name}' succeeded but produced no stdout."
    fi
    
    # Return as a single string for easy parsing by caller, e.g., space separated
    echo "${pv_used_bytes} ${ha_level}"
}


# --- Main Execution ---
main() {
    log_info "Starting Portworx Volume Detail script (Bash version)..."

    # Initialize K8s Clients (implicitly done by kubectl, check availability)
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl command not found. Please ensure it is installed and in your PATH."
        exit 1
    fi
    if ! command -v jq &> /dev/null; then
        log_error "jq command not found. Please ensure it is installed and in your PATH."
        exit 1
    fi

    if [[ -n "${KUBECONFIG_PATH}" ]]; then
        log_info "Using kubeconfig: ${KUBECONFIG_PATH}"
    fi
    log_info "Portworx namespace: ${PX_NAMESPACE}"
    log_info "Output format: CSV"
    if [[ "${OUTPUT_TO_STDOUT}" -eq 0 ]]; then
        log_info "Base output file path: ${OUTPUT_FILE_BASE}"
    else
        log_info "Outputting to stdout."
    fi
    if [[ ${#SKIP_NAMESPACE_PREFIXES[@]} -gt 0 ]]; then
        log_info "Skipping namespaces starting with: ${SKIP_NAMESPACE_PREFIXES[*]}"
    fi
    if [[ ${#ENV_VARS_PXCTL[@]} -gt 0 ]]; then
        log_info "Using pxctl environment variables: ${ENV_VARS_PXCTL[*]}"
    fi

    # 1. Find Portworx Pod
    if ! find_portworx_pod "${PX_NAMESPACE}"; then
        log_error "Failed to find a suitable Portworx pod. Exiting."
        exit 1
    fi

    # 2. Get Portworx Storage Classes
    if ! get_portworx_sc_names; then # This function now returns 0 even on "failure" to find SCs to match python logic
        # This condition might not be strictly necessary if get_portworx_sc_names always returns 0
        # but it's harmless. The critical part is if PORTWORX_SC_NAMES is empty.
        log_info "Continuing without specific Portworx StorageClasses if any error occurred or none found."
    fi
    # if [[ ${#PORTWORX_SC_NAMES[@]} -eq 0 ]]; then # This is logged within get_portworx_sc_names
    #      log_info "No Portworx StorageClasses found. Will rely solely on CSI driver for PV identification."
    # fi

    # 3. Prepare CSV Output
    local csv_output_target="/dev/stdout"
    if [[ "${OUTPUT_TO_STDOUT}" -eq 0 ]]; then
        local timestamp
        timestamp=$(date +"%Y%m%d_%H%M%S")
        local output_dir
        # Handle absolute vs relative output_file_base for tmp directory
        if [[ "${OUTPUT_FILE_BASE}" == /* ]]; then
            output_dir=$(dirname "${OUTPUT_FILE_BASE}")
            csv_output_target="${OUTPUT_FILE_BASE}_${timestamp}.csv"
        else
            output_dir="./tmp"
            csv_output_target="${output_dir}/${OUTPUT_FILE_BASE}_${timestamp}.csv"
        fi
        
        if ! mkdir -p "${output_dir}"; then 
            log_error "Failed to create output directory: ${output_dir}"
            exit 1
        fi
        log_info "CSV output will be saved to: ${csv_output_target}"
    fi

    # Write CSV Header
    echo "pv_name,namespace,pvc_name,pv_size_bytes,pv_used_bytes,ha_level" > "${csv_output_target}"
    
    # 4. Get and Process Portworx PVs
    local pv_count=0
    local processed_pv_count=0
    
    # Get all PVs first, then count for progress logging
    local all_filtered_pvs_stream
    if ! all_filtered_pvs_stream=$(get_portworx_pvs); then # Check exit status of get_portworx_pvs
        log_error "Failed to retrieve Portworx PVs. Exiting."
        # Ensure header is written if file output was intended, even if no data rows
        if [[ "${OUTPUT_TO_STDOUT}" -eq 0 ]]; then 
            echo "CSV output file created at: ${csv_output_target} but contains no data due to PV fetch error."
        fi
        exit 1
    fi

    declare -a all_filtered_pvs=()
    if [[ -n "$all_filtered_pvs_stream" ]]; then # Check if stream is not empty
        while IFS= read -r pv_json_line; do
            all_filtered_pvs+=("$pv_json_line")
        done <<< "$all_filtered_pvs_stream"
    fi

    pv_count=${#all_filtered_pvs[@]}
    log_info "Found ${pv_count} potential Portworx PVs to process."

    if [[ $pv_count -eq 0 ]]; then
        log_info "No Portworx PVs found matching the criteria. Exiting."
        # The Python script exits with 0 if no PVs found, CSV header was written
        if [[ "${OUTPUT_TO_STDOUT}" -eq 0 ]]; then 
             echo "CSV output saved to: ${csv_output_target}" # User-facing confirmation for empty file
        fi
        exit 0
    fi

    for pv_json_line in "${all_filtered_pvs[@]}"; do
        ((processed_pv_count++))
        local pv_name claim_ref_namespace claim_ref_name capacity_bytes
        pv_name=$(echo "$pv_json_line" | jq -r '.pv_name')
        claim_ref_namespace=$(echo "$pv_json_line" | jq -r '.claim_ref_namespace')
        claim_ref_name=$(echo "$pv_json_line" | jq -r '.claim_ref_name')
        capacity_bytes=$(echo "$pv_json_line" | jq -r '.capacity_bytes')
        
        # Skip if PV is bound to a PVC in a skipped namespace
        if [[ -n "${claim_ref_namespace}" ]] && string_starts_with_any_prefix "${claim_ref_namespace}" "SKIP_NAMESPACE_PREFIXES"; then
            log_debug "Skipping PV '${pv_name}' because its claimRef namespace '${claim_ref_namespace}' is in a skipped prefix list."
            continue
        fi

        log_info "Processing PV ${processed_pv_count}/${pv_count}: ${pv_name}"

        local pvc_namespace_out="${claim_ref_namespace:-N/A}" # Default to N/A if empty
        local pvc_name_out="${claim_ref_name:-N/A}"         # Default to N/A if empty

        #  local pxctl_results --- unsure if this is needed
        read -r pv_used_bytes_res ha_level_res < <(execute_pxctl_inspect "${pv_name}" "${PX_NAMESPACE}" "${PX_POD_NAME}" "${PX_CONTAINER_NAME}")
        
        # Output CSV row
        echo "${pv_name},${pvc_namespace_out},${pvc_name_out},${capacity_bytes},${pv_used_bytes_res},${ha_level_res}" >> "${csv_output_target}"
    done

    log_info "Finished processing all identified Portworx PVs."
    if [[ "${OUTPUT_TO_STDOUT}" -eq 0 ]]; then
         log_info "CSV output saved to: ${csv_output_target}"
         echo "CSV output saved to: ${csv_output_target}" # User-facing confirmation
    fi
    log_info "Portworx Volume Detail script (Bash version) finished successfully."
}


# --- Argument Parsing ---
if [[ $# -eq 0 && -z "${KUBECONFIG:-}" ]]; then # Show help if no args and KUBECONFIG not set
    usage 
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kubeconfig)
            KUBECONFIG_PATH="$2"
            shift 2
            ;;
        --px-namespace)
            PX_NAMESPACE="$2"
            shift 2
            ;;
        -o|--output-file)
            OUTPUT_FILE_BASE="$2"
            OUTPUT_TO_STDOUT=0 # Explicitly set when -o is used
            shift 2
            ;;
        --skip-namespace-prefix)
            SKIP_NAMESPACE_PREFIXES+=("$2")
            shift 2
            ;;
        -e|--env-var)
            ENV_VARS_PXCTL+=("$2")
            shift 2
            ;;
        --debug)
            DEBUG_MODE=1
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo >&2 "Unknown option: $1"
            usage
            ;;
    esac
done

# If KUBECONFIG_PATH is not set by arg, check env var
if [[ -z "${KUBECONFIG_PATH}" && -n "${KUBECONFIG:-}" ]]; then
    KUBECONFIG_PATH="${KUBECONFIG}"
fi

# If output file base is not specified via -o, but the script is not called with other args that imply stdout intent
# then we default to stdout for safety.
# The python script defaulted to "px-volume-summary" (file output) if no format implies console.
# Here, if -o is NOT given, we assume stdout.
if [[ ! "$*" =~ "-o" ]] && [[ ! "$*" =~ "--output-file" ]]; then
    # No -o provided by user, check if it remained its default value from script init
    if [[ "${OUTPUT_FILE_BASE}" == "px-volume-summary" ]]; then # Default value means user did not specify -o
         OUTPUT_TO_STDOUT=1
    fi
fi


# --- Entry Point ---
main
