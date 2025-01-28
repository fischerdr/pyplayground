#!/bin/bash
#
# Script Name: dev-shell.sh
# Description: Build and run development container with all necessary mounts
# Date Created: 2025-01-27
#
# Usage: ./dev-shell.sh
#
# Dependencies:
#   - docker
#   - Dockerfile.dev in the same directory
#
# Environment Variables:
#   - CONTAINER_NAME: Override default container name (optional)

# Enable strict mode
set -euo pipefail
IFS=$'\n\t'

# Script constants
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_NAME="$(basename "${0}")"
readonly DEFAULT_CONTAINER_NAME="pyplayground-dev"
readonly IMAGE_NAME="pyplayground-dev:latest"
readonly DOCKERFILE="${SCRIPT_DIR}/Dockerfile.dev"

# Logging functions
function log_info() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [INFO] $*"
}

function log_error() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [ERROR] $*" >&2
}

function error_exit() {
    local message="$1"
    local code="${2:-1}"
    log_error "${message}"
    exit "${code}"
}

# Validate required files exist
function validate_files() {
    if [[ ! -f "${DOCKERFILE}" ]]; then
        error_exit "Dockerfile.dev not found at ${DOCKERFILE}"
    fi
    
    if [[ ! -d "${SCRIPT_DIR}" ]]; then
        error_exit "Script directory ${SCRIPT_DIR} does not exist"
    fi
}

# Cleanup function
function cleanup() {
    local container_name="${CONTAINER_NAME:-${DEFAULT_CONTAINER_NAME}}"
    if docker ps -q -f name="^/${container_name}$" > /dev/null; then
        log_info "Cleaning up container ${container_name}"
        docker stop "${container_name}" > /dev/null || true
        docker rm "${container_name}" > /dev/null || true
    fi
}

# Set up cleanup trap
trap cleanup EXIT
trap 'error_exit "Script interrupted." 2' INT TERM

# Check dependencies
if ! command -v docker &> /dev/null; then
    error_exit "Docker is not installed. Please install Docker first."
fi

# Check if we need sudo for docker
DOCKER_CMD="docker"
if ! docker info >/dev/null 2>&1; then
    if ! sudo docker info >/dev/null 2>&1; then
        error_exit "Docker is not running or we don't have permission to use it"
    fi
    DOCKER_CMD="sudo docker"
    log_info "Using sudo for docker commands"
fi

# Validate files
validate_files

# Build the development image
log_info "Building development image..."
log_info "Current directory: $(pwd)"
log_info "Dockerfile path: ${DOCKERFILE}"

if [[ ! -f "${DOCKERFILE}" ]]; then
    error_exit "Dockerfile not found at ${DOCKERFILE}"
fi

log_info "Running docker build command..."
cd "${SCRIPT_DIR}"
${DOCKER_CMD} build \
    -t "${IMAGE_NAME}" \
    -f "${DOCKERFILE}" \
    .

log_info "Docker build completed successfully"

# Create necessary directories if they don't exist
log_info "Creating necessary directories..."
mkdir -p "${SCRIPT_DIR}"/{logs,config,tmp,cache}

# Run the container
log_info "Starting development container..."
container_name="${CONTAINER_NAME:-${DEFAULT_CONTAINER_NAME}}"

# Stop any existing container with the same name
if ${DOCKER_CMD} ps -a -q -f name="^/${container_name}$" > /dev/null; then
    log_info "Stopping existing container..."
    ${DOCKER_CMD} stop "${container_name}" > /dev/null || true
    ${DOCKER_CMD} rm "${container_name}" > /dev/null || true
fi

# Start new container
exec ${DOCKER_CMD} run --rm -it \
    --name "${container_name}" \
    -v "${SCRIPT_DIR}:/src" \
    -v "${SCRIPT_DIR}/logs:/src/logs" \
    -v "${SCRIPT_DIR}/config:/src/config" \
    -v "${SCRIPT_DIR}/tmp:/src/tmp" \
    -v "${SCRIPT_DIR}/cache:/src/cache" \
    -v "${HOME}/.ssh:/src/.ssh:ro" \
    -v "${HOME}/.gitconfig:/src/.gitconfig:ro" \
    --network host \
    "${IMAGE_NAME}" \
    /bin/bash
