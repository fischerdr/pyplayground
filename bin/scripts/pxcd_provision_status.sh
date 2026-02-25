#!/usr/bin/env bash

set -euo pipefail

# --- Constants ---
DEFAULT_PORTWORX_NAMESPACE="kube-system"
PORTWORX_POD_LABEL_SELECTOR="name=portworx,storage=true"
TARGET_CONTAINER_NAME_PREF="portworx" # Preferred container name
SCRIPT_NAME=$(basename "$0")
JSON_OUTPUT_DIR="./tmp"
JSON_OUTPUT_FILENAME="${JSON_OUTPUT_DIR}/pxcd_provision_status.json"

# --- Globals (populated by arguments) ---
KUBECONFIG_PATH=""
PX_NAMESPACE="${DEFAULT_PORTWORX_NAMESPACE}"
declare -a ENV_VARS_PXCTL=()
OUTPUT_AS_JSON=0
DEBUG_MODE=0

# --- Globals (derived) ---
PX_POD_NAME=""
PX_CONTAINER_NAME=""

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

Gets the Portworx cluster provision status from a running pod.

Options:
  -n, --namespace <ns>    Namespace where Portworx pods are running. (Default: ${DEFAULT_PORTWORX_NAMESPACE})
  -k, --kubeconfig <path> Path to the kubeconfig file. (Env: KUBECONFIG)
  -e, --env-var <VAR=VALUE> Environment variable to set for pxctl. Can be used multiple times.
  -j, --output-json       Output the processed data as JSON to ${JSON_OUTPUT_FILENAME} instead of a table.
  -d, --debug             Enable debug logging.
  -h, --help              Show this help message.
EOF
    exit 0
}

# --- Helper Functions ---
check_deps() {
    local dep
    for dep in kubectl jq bc; do
        if ! command -v "${dep}" &> /dev/null; then
            log_error "${dep} command not found. Please ensure it is installed and in your PATH."
            exit 1
        fi
    done
}

# $1: size_bytes
format_bytes_human() {
    local size_bytes=$1
    if ! [[ "$size_bytes" =~ ^[0-9]+$ ]]; then
        echo "N/A"
        return
    fi
    if [[ "$size_bytes" -eq 0 ]]; then
        echo "0 B"
        return
    fi

    local units=("B" "KiB" "MiB" "GiB" "TiB")
    local i=0
    local s_val="${size_bytes}.0" # Add .0 for bc scale

    while (( $(echo "$s_val >= 1024 && $i < 4" | bc -l) )); do
        s_val=$(echo "scale=1; $s_val / 1024" | bc -l)
        i=$((i + 1))
    done
    # Remove .0 if it's an integer after formatting
    printf "%.1f %s\n" "$s_val" "${units[$i]}" | sed 's/\.0 / /'
}

# --- Core Logic Functions ---

find_portworx_pod_and_container() {
    local ns="$1"
    log_info "Searching for Portworx pod with labels '${PORTWORX_POD_LABEL_SELECTOR}' in namespace '${ns}'..."

    local pod_json
    if ! pod_json=$(kubectl --kubeconfig "${KUBECONFIG_PATH:-}" get pods -n "${ns}" -l "${PORTWORX_POD_LABEL_SELECTOR}" -o json); then
        log_error "Failed to get pod information from Kubernetes for namespace '${ns}'."
        return 1
    fi
        
    PX_POD_NAME=$(echo "$pod_json" | jq -e -r '.items[] | select(.status.phase=="Running") | .metadata.name' | head -n 1)
    if [[ -z "${PX_POD_NAME}" ]]; then
        log_error "No *running* Portworx pods found in namespace '${ns}' with labels '${PORTWORX_POD_LABEL_SELECTOR}'."
        return 1
    fi
    log_debug "Found candidate Portworx pod: '${PX_POD_NAME}'"

    # Determine container name: prefer TARGET_CONTAINER_NAME_PREF, else first container
    PX_CONTAINER_NAME=$(echo "$pod_json" | jq -e -r --arg pod_name "$PX_POD_NAME" --arg pref_cont "$TARGET_CONTAINER_NAME_PREF" '
        .items[] | 
        select(.metadata.name == $pod_name) | 
        ( .spec.containers[] | select(.name == $pref_cont) | .name ) // ( .spec.containers[0].name )
    ' | head -n 1)

    if [[ -z "${PX_CONTAINER_NAME}" ]]; then
        log_error "Could not determine container name for Portworx pod '${PX_POD_NAME}'."
        return 1
    fi

    log_info "Using Portworx pod: '${PX_POD_NAME}', container: '${PX_CONTAINER_NAME}'"
    return 0
}

prepare_execution_command_string() {
    local base_command="$1"
    # Pass array by name
    local array_name="$2" # Accept the name of the array
    local -a tmp_array=() # Temporary local array to hold elements
    eval "tmp_array=(\"\${${array_name}[@]}\")"
    
    local env_exports_str=""
    if [[ ${#tmp_array[@]} -gt 0 ]]; then
        for var_assignment in "${tmp_array[@]}"; do # Iterate over the local copy
            if [[ ! "$var_assignment" == *"="* ]]; then
                log_error "Invalid environment variable format: '$var_assignment'. Use VAR=VALUE."
                return 1 # Indicate error
            fi
            # Quote the value part carefully, escaping existing quotes
            local key="${var_assignment%%=*}"
            local value="${var_assignment#*=}"
            env_exports_str+="export ${key}=\"${value//\"/\\\"}\" && "
        done
    fi
    echo "${env_exports_str}${base_command}"
    return 0
}

execute_pxctl_command() {
    local full_cmd_str="$1"
    log_info "Executing command in container '${PX_CONTAINER_NAME}' of pod '${PX_POD_NAME}'..."

    local output_stderr_file
    output_stderr_file=$(mktemp)
    local actual_exit_code=0
    local stdout_data=""

    if stdout_data=$(kubectl --kubeconfig "${KUBECONFIG_PATH:-}" exec -n "${PX_NAMESPACE}" "${PX_POD_NAME}" -c "${PX_CONTAINER_NAME}" \
        -- /bin/sh -c "${full_cmd_str}" 2> "${output_stderr_file}"); then
        log_info "Command execution finished successfully." # Moved from after stderr processing
    else
        actual_exit_code=$?
        log_error "pxctl command execution failed with exit code: ${actual_exit_code}."
    fi
        
    local stderr_data
    stderr_data=$(<"${output_stderr_file}")
    rm -f "${output_stderr_file}"

    if [[ -n "$stderr_data" ]]; then
        log_info "Command produced output on stderr:"
        # Output to script's stderr
        echo -e "\n--- PXCTL STDERR ---\n${stderr_data}\n--- END PXCTL STDERR ---" >&2
    fi
    
    if [[ $actual_exit_code -eq 0 ]]; then
        echo "$stdout_data"
        return 0
    else
        return "$actual_exit_code" 
    fi
}

# Parses raw provisionInfo data and outputs a structured JSON.
# First part: summary. Second part (multiple lines): node details.
# This is a bit of a workaround to pass structured data in bash.
# Output format:
# {"total_nodes":X,"up_nodes":Y,"storage_nodes_reporting_pools":Z, "total_pool_used_bytes": W}
# {"px_node_id": "...", "k8s_hostname": "...", ...} (one per node)
parse_pxctl_json_data() {
    local pxctl_json="$1"

    # Summary Data
    local total_nodes up_nodes
    total_nodes=$(echo "$pxctl_json" | jq -r '.provisionInfo | length')
    up_nodes=$(echo "$pxctl_json" | jq -r '.provisionInfo | map(select(.Status=="Up")) | length')
    
    # Storage Node Details (stream of JSON objects)
    local node_details_stream
    node_details_stream=$(echo "$pxctl_json" | jq -c '
        .provisionInfo | to_entries | .[] |
        select(.value.Provision[0].Pool.Info?) | # Only nodes with Pool Info
        {
            px_node_id: .key,
            k8s_hostname: (.value.Provision[0].Pool.labels."kubernetes.io/hostname" // "N/A"),
            node_status: (.value.Status // "N/A"),
            pool_status: (.value.Provision[0].Pool.Info.Status // "N/A"),
            pool_size_bytes: (.value.Provision[0].Pool.Info.TotalSize // 0),
            pool_used_bytes: (.value.Provision[0].Pool.Info.Used // 0),
            drive_count: (.value.Provision[0].Pool.Info.ResourcesCount // 0)
        }
    ')

    local storage_nodes_count=0
    local total_pool_used_bytes=0
    if [[ -n "$node_details_stream" ]]; then
      storage_nodes_count=$(echo "$node_details_stream" | wc -l)
      while IFS= read -r node_detail_json; do
          used_bytes=$(echo "$node_detail_json" | jq -r '.pool_used_bytes')
          total_pool_used_bytes=$((total_pool_used_bytes + used_bytes))
      done <<< "$node_details_stream"
    fi

    echo "{\"total_nodes\":${total_nodes},\"up_nodes\":${up_nodes},\"storage_nodes_reporting_pools\":${storage_nodes_count}, \"total_pool_used_bytes\":${total_pool_used_bytes}}"
    
    # Output node details stream if it's not empty
    if [[ -n "$node_details_stream" ]]; then
        echo "$node_details_stream"
    fi
}

output_data_as_json() {
    local summary_json="$1"
    # Rest of the lines are node details
    shift
    local node_details_array_json="["
    local first=true
    while [[ $# -gt 0 ]]; do
        if ! $first; then
            node_details_array_json+=","
        fi
        node_details_array_json+="$1"
        first=false
        shift
    done
    node_details_array_json+="]"

    # Combine into final JSON
    local final_json
    final_json=$(jq -n --argjson summary "$summary_json" --argjson nodes "$node_details_array_json" \
        '{summary: $summary, storage_node_details: $nodes}')

    mkdir -p "${JSON_OUTPUT_DIR}"
    echo "$final_json" > "${JSON_OUTPUT_FILENAME}"
    log_info "JSON output saved successfully to: ${JSON_OUTPUT_FILENAME}"
    echo "JSON output saved to: ${JSON_OUTPUT_FILENAME}" # User-facing
}

output_data_as_table() {
    local summary_json="$1"
    shift # remove summary from arguments, rest are node_detail_jsons

    local total_nodes up_nodes total_pool_used_bytes_summary storage_nodes_reporting_pools
    total_nodes=$(echo "$summary_json" | jq -r '.total_nodes')
    up_nodes=$(echo "$summary_json" | jq -r '.up_nodes')
    total_pool_used_bytes_summary=$(echo "$summary_json" | jq -r '.total_pool_used_bytes')
    storage_nodes_reporting_pools=$(echo "$summary_json" | jq -r '.storage_nodes_reporting_pools')

    local total_pool_used_formatted
    total_pool_used_formatted=$(format_bytes_human "$total_pool_used_bytes_summary")

    # ANSI Colors
    local color_bold=$'\033[1m'
    local color_cyan=$'\033[36m'
    local color_green=$'\033[32m'
    local color_red=$'\033[31m'
    local color_magenta=$'\033[35m'
    local color_dim=$'\033[2m'
    local color_reset=$'\033[0m'

    printf '%s%sPortworx Storage Node Provision Status%s\n' "${color_bold}" "${color_magenta}" "${color_reset}"
    printf "%-38s | %-25s | %-12s | %-12s | %-10s | %-10s | %-6s\n" \
        "PX Node ID" "K8s Hostname" "Node Status" "Pool Status" "Pool Size" "Pool Used" "Drives"
    printf "%s\n" "---------------------------------------+---------------------------+--------------+--------------+------------+------------+--------"

    if [[ "$#" -eq 0 ]]; then
        printf "No storage nodes with provisioned pools found.\n"
    else
        while [[ $# -gt 0 ]]; do
            local node_detail_json="$1"
            local px_node_id k8s_hostname node_status pool_status pool_size_bytes pool_used_bytes drive_count
            px_node_id=$(echo "$node_detail_json" | jq -r '.px_node_id')
            k8s_hostname=$(echo "$node_detail_json" | jq -r '.k8s_hostname')
            node_status=$(echo "$node_detail_json" | jq -r '.node_status')
            pool_status=$(echo "$node_detail_json" | jq -r '.pool_status')
            pool_size_bytes=$(echo "$node_detail_json" | jq -r '.pool_size_bytes')
            pool_used_bytes=$(echo "$node_detail_json" | jq -r '.pool_used_bytes')
            drive_count=$(echo "$node_detail_json" | jq -r '.drive_count')

            local node_status_colored="${node_status}"
            if [[ "$node_status" == "Up" ]]; then node_status_colored="${color_green}${node_status}${color_reset}"; else node_status_colored="${color_bold}${color_red}${node_status}${color_reset}"; fi
            
            local pool_status_colored="${pool_status}"
            if [[ "$pool_status" == "Up" ]]; then pool_status_colored="${color_green}${pool_status}${color_reset}"; else pool_status_colored="${color_bold}${color_red}${pool_status}${color_reset}"; fi
            
            local pool_size_h pool_used_h
            pool_size_h=$(format_bytes_human "$pool_size_bytes")
            pool_used_h=$(format_bytes_human "$pool_used_bytes")

            printf "%-38s | %-25s | %-18s | %-18s | %10s | %10s | %6s\n" \
                "${color_dim}${px_node_id}${color_reset}" \
                "${color_cyan}${k8s_hostname}${color_reset}" \
                "${node_status_colored}" \
                "${pool_status_colored}" \
                "${pool_size_h}" \
                "${pool_used_h}" \
                "${drive_count}"
            shift
        done
        printf "%s\n" "---------------------------------------+---------------------------+--------------+--------------+------------+------------+--------"
        printf "%-38s | %-25s | %-12s | %-12s | %-10s | %10s | %-6s\n" \
          "${color_bold}Totals (${storage_nodes_reporting_pools} storage nodes)${color_reset}" "" "" "" "" "${color_bold}${total_pool_used_formatted}${color_reset}" ""
    fi
    printf '\n%sTotal Nodes Found: %s, Nodes Up: %s%s\n' "${color_dim}" "$total_nodes" "$up_nodes" "${color_reset}"

}


# --- Main Execution ---
main() {
    log_info "Starting Portworx provision status script (Bash version)..."
    check_deps

    if [[ -n "${KUBECONFIG_PATH}" ]]; then log_info "Using kubeconfig: ${KUBECONFIG_PATH}"; fi
    log_info "Portworx namespace: ${PX_NAMESPACE}"
    if [[ ${#ENV_VARS_PXCTL[@]} -gt 0 ]]; then log_info "Using pxctl environment variables: ${ENV_VARS_PXCTL[*]}"; fi
    if [[ "${OUTPUT_AS_JSON}" -eq 1 ]]; then log_info "Output mode: JSON to ${JSON_OUTPUT_FILENAME}"; else log_info "Output mode: Table to console"; fi

    if ! find_portworx_pod_and_container "${PX_NAMESPACE}"; then
        log_error "Failed to find a suitable Portworx pod/container. Exiting."
        exit 1
    fi

    local base_pxctl_cmd="/opt/pwx/bin/pxctl cluster provision-status -j"
    local full_pxctl_cmd
    if ! full_pxctl_cmd=$(prepare_execution_command_string "$base_pxctl_cmd" "ENV_VARS_PXCTL"); then
        exit 1
    fi
    
    local pxctl_stdout
    # Check the success of execute_pxctl_command itself
    if ! pxctl_stdout=$(execute_pxctl_command "$full_pxctl_cmd"); then
        local cmd_exit_code=$? 
        # Error is already logged by execute_pxctl_command
        log_error "pxctl command execution failed. Cannot proceed."
        exit "$cmd_exit_code"
    fi

    # If execute_pxctl_command returned 0, pxctl_stdout should contain the output.
    # Check if stdout is empty, which is an error condition for this script's logic.
    if [[ -z "$pxctl_stdout" ]]; then
        log_error "pxctl command succeeded but returned no output. Cannot parse status."
        exit 1
    fi
    

    # Read parsed data into an array. First line is summary, rest are node details.
    declare -a parsed_data_lines=()
    while IFS= read -r line; do
        parsed_data_lines+=("$line")
    done < <(parse_pxctl_json_data "$pxctl_stdout")

    if [[ ${#parsed_data_lines[@]} -eq 0 ]]; then
        log_error "Failed to parse pxctl JSON output or output was empty."
        exit 1
    fi

    local summary_data_json="${parsed_data_lines[0]}"
    # Slice the array to get node details (from index 1 to end)
    declare -a node_details_json_lines=("${parsed_data_lines[@]:1}")


    if [[ "${OUTPUT_AS_JSON}" -eq 1 ]]; then
        output_data_as_json "$summary_data_json" "${node_details_json_lines[@]}"
    else
        output_data_as_table "$summary_data_json" "${node_details_json_lines[@]}"
    fi
    
    log_info "Portworx provision status script finished successfully."
}


# --- Argument Parsing ---
if [[ $# -eq 0 && -z "${KUBECONFIG:-}" ]]; then 
    usage 
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--namespace)
            PX_NAMESPACE="$2"
            shift 2
            ;;
        -k|--kubeconfig)
            KUBECONFIG_PATH="$2"
            shift 2
            ;;
        -e|--env-var)
            ENV_VARS_PXCTL+=("$2")
            shift 2
            ;;
        -j|--output-json)
            OUTPUT_AS_JSON=1
            shift
            ;;
        -d|--debug)
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

if [[ -z "${KUBECONFIG_PATH}" && -n "${KUBECONFIG:-}" ]]; then
    KUBECONFIG_PATH="${KUBECONFIG}"
fi

# --- Entry Point ---
main 