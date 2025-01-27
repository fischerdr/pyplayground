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
#   - DOCKER_BUILD_ARGS: Additional docker build arguments (optional)

# Enable strict mode
set -euo pipefail
IFS=$'\n\t'

# Script constants
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_NAME="$(basename "${0}")"
readonly DEFAULT_CONTAINER_NAME="pyplayground-dev"
readonly IMAGE_NAME="pyplayground-dev:latest"

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

# Build the development image
log_info "Building development image..."
if ! docker build "${DOCKER_BUILD_ARGS:-}" -t "${IMAGE_NAME}" -f "${SCRIPT_DIR}/Dockerfile.dev" "${SCRIPT_DIR}"; then
    error_exit "Failed to build Docker image"
fi

# Create necessary directories if they don't exist
log_info "Creating necessary directories..."
mkdir -p "${SCRIPT_DIR}"/{logs,config,tmp,cache}

# Run the container
log_info "Starting development container..."
container_name="${CONTAINER_NAME:-${DEFAULT_CONTAINER_NAME}}"

# Stop any existing container with the same name
if docker ps -a -q -f name="^/${container_name}$" > /dev/null; then
    log_info "Stopping existing container..."
    docker stop "${container_name}" > /dev/null || true
    docker rm "${container_name}" > /dev/null || true
fi

# Start new container
exec docker run --rm -it \
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
