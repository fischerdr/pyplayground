#!/bin/bash
# Shell script to run Vault multi-namespace monitoring tests
# Based on the Python script multi_namespace_vault_monitor.py

set -euo pipefail

# Default values
TARGET_NAMESPACE=""
SECRET_PATHS=""
VAULT_NAMESPACES=""
PX_NAMESPACE="portworx"
KUBECONFIG=""
DEBUG=false
MASK_VALUES=true
K8S_VERIFY_SSL=true
K8S_SSL_CA_CERT=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to display usage
usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Vault Multi-Namespace Monitoring - Ansible Playbook Runner

Required Options:
  -n, --namespace NAMESPACE        Kubernetes namespace to test
  -s, --secret-paths PATHS         Comma-separated list of secret paths
  -v, --vault-namespaces NAMESPACES Comma-separated list of Vault namespaces

Optional Options:
  -p, --px-namespace NAMESPACE     Portworx namespace (default: portworx)
  -k, --kubeconfig PATH            Path to kubeconfig file
  -d, --debug                      Enable debug output
  -m, --no-mask                    Don't mask sensitive values
  --no-verify-ssl                   Disable SSL verification for Kubernetes API
  --ssl-ca-cert PATH               Path to CA certificate for Kubernetes API
  -h, --help                       Show this help message

Examples:
  # Basic usage
  $0 -n production -s "app/config,db/credentials" -v "prod-ns1,prod-ns2"

  # With debug output
  $0 -n production -s "app/config" -v "prod-ns" -d

  # With custom kubeconfig
  $0 -n production -s "app/config" -v "prod-ns" -k /path/to/kubeconfig

  # Without masking values
  $0 -n production -s "app/config" -v "prod-ns" --no-mask
EOF
}

# Function to log messages
log() {
    local level=$1
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    case $level in
        INFO)
            echo -e "${BLUE}[INFO]${NC} ${timestamp}: ${message}"
            ;;
        WARN)
            echo -e "${YELLOW}[WARN]${NC} ${timestamp}: ${message}"
            ;;
        ERROR)
            echo -e "${RED}[ERROR]${NC} ${timestamp}: ${message}"
            ;;
        SUCCESS)
            echo -e "${GREEN}[SUCCESS]${NC} ${timestamp}: ${message}"
            ;;
    esac
}

# Function to validate required tools
validate_requirements() {
    log INFO "Validating requirements..."
    
    # Check if ansible-playbook is available
    if ! command -v ansible-playbook &> /dev/null; then
        log ERROR "ansible-playbook is not installed or not in PATH"
        exit 1
    fi
    
    # Check if kubectl is available
    if ! command -v kubectl &> /dev/null; then
        log ERROR "kubectl is not installed or not in PATH"
        exit 1
    fi
    
    # Check if kubeconfig is accessible
    if [[ -n "$KUBECONFIG" && ! -f "$KUBECONFIG" ]]; then
        log ERROR "Kubeconfig file not found: $KUBECONFIG"
        exit 1
    fi
    
    log SUCCESS "All requirements validated"
}

# Function to install Ansible collections
install_collections() {
    log INFO "Installing required Ansible collections..."
    
    if [[ -f "requirements.yml" ]]; then
        ansible-galaxy collection install -r requirements.yml
        log SUCCESS "Ansible collections installed"
    else
        log WARN "requirements.yml not found, skipping collection installation"
    fi
}

# Function to validate Kubernetes connectivity
validate_k8s_connectivity() {
    log INFO "Validating Kubernetes connectivity..."
    
    local kubeconfig_arg=""
    if [[ -n "$KUBECONFIG" ]]; then
        kubeconfig_arg="--kubeconfig=$KUBECONFIG"
    fi
    
    if kubectl $kubeconfig_arg get nodes &> /dev/null; then
        log SUCCESS "Kubernetes connectivity validated"
    else
        log ERROR "Cannot connect to Kubernetes cluster"
        exit 1
    fi
}

# Function to run the playbook
run_playbook() {
    log INFO "Running Vault multi-namespace monitoring playbook..."
    
    # Build ansible-playbook command
    local cmd="ansible-playbook playbook.yml"
    
    # Add required variables
    cmd="$cmd -e target_namespace='$TARGET_NAMESPACE'"
    cmd="$cmd -e secret_paths='$SECRET_PATHS'"
    cmd="$cmd -e vault_namespaces='$VAULT_NAMESPACES'"
    
    # Add optional variables
    cmd="$cmd -e px_namespace='$PX_NAMESPACE'"
    cmd="$cmd -e debug='$DEBUG'"
    cmd="$cmd -e mask_values='$MASK_VALUES'"
    cmd="$cmd -e k8s_verify_ssl='$K8S_VERIFY_SSL'"
    
    if [[ -n "$KUBECONFIG" ]]; then
        cmd="$cmd -e kubeconfig='$KUBECONFIG'"
    fi
    
    if [[ -n "$K8S_SSL_CA_CERT" ]]; then
        cmd="$cmd -e k8s_ssl_ca_cert='$K8S_SSL_CA_CERT'"
    fi
    
    # Add verbose output if debug is enabled
    if [[ "$DEBUG" == "true" ]]; then
        cmd="$cmd -v"
    fi
    
    log INFO "Executing: $cmd"
    
    # Execute the command
    if eval "$cmd"; then
        log SUCCESS "Playbook execution completed successfully"
    else
        log ERROR "Playbook execution failed"
        exit 1
    fi
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--namespace)
            TARGET_NAMESPACE="$2"
            shift 2
            ;;
        -s|--secret-paths)
            SECRET_PATHS="$2"
            shift 2
            ;;
        -v|--vault-namespaces)
            VAULT_NAMESPACES="$2"
            shift 2
            ;;
        -p|--px-namespace)
            PX_NAMESPACE="$2"
            shift 2
            ;;
        -k|--kubeconfig)
            KUBECONFIG="$2"
            shift 2
            ;;
        -d|--debug)
            DEBUG=true
            shift
            ;;
        -m|--no-mask)
            MASK_VALUES=false
            shift
            ;;
        --no-verify-ssl)
            K8S_VERIFY_SSL=false
            shift
            ;;
        --ssl-ca-cert)
            K8S_SSL_CA_CERT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            log ERROR "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Validate required parameters
if [[ -z "$TARGET_NAMESPACE" || -z "$SECRET_PATHS" || -z "$VAULT_NAMESPACES" ]]; then
    log ERROR "Missing required parameters"
    usage
    exit 1
fi

# Validate that secret paths and vault namespaces have the same number of elements
IFS=',' read -ra SECRET_ARRAY <<< "$SECRET_PATHS"
IFS=',' read -ra VAULT_ARRAY <<< "$VAULT_NAMESPACES"

if [[ ${#SECRET_ARRAY[@]} -ne ${#VAULT_ARRAY[@]} ]]; then
    log ERROR "Secret paths and Vault namespaces must have the same number of elements"
    log ERROR "Secret paths: ${#SECRET_ARRAY[@]} elements"
    log ERROR "Vault namespaces: ${#VAULT_ARRAY[@]} elements"
    exit 1
fi

# Main execution
log INFO "Starting Vault multi-namespace monitoring"
log INFO "Target namespace: $TARGET_NAMESPACE"
log INFO "Secret paths: $SECRET_PATHS"
log INFO "Vault namespaces: $VAULT_NAMESPACES"
log INFO "Portworx namespace: $PX_NAMESPACE"
log INFO "Debug mode: $DEBUG"
log INFO "Mask values: $MASK_VALUES"

validate_requirements
install_collections
validate_k8s_connectivity
run_playbook

log SUCCESS "Vault multi-namespace monitoring completed"
