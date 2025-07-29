#!/bin/bash
#
# Script Name: check_image_tags.sh
# Description: Check Docker and Podman images on local machine and compare with available tags on Docker Hub
# Last Modified: 2025-01-27
#
# Dependencies:
#   - docker (Docker CLI)
#   - podman (Podman CLI)
#   - jq (JSON processor)
#   - curl (HTTP client)
#   - grep (text search)
#   - sort (text sorting)
#
# Environment Variables:
#   DOCKER_HUB_USERNAME - Docker Hub username (optional, for private repos)
#   DOCKER_HUB_TOKEN - Docker Hub access token (optional, for private repos)
#
# Usage:
#   ./check_image_tags.sh [-h] [-d] [-p] [-a] [-u username] [-t token] [image_name]
#
# Return Values:
#   0 - Success
#   1 - Error (missing dependencies, API failure, etc.)
#

# Exit on error and undefined variables
set -euo pipefail

# Configuration Parameters
SCRIPT_NAME=$(basename "$0")
readonly SCRIPT_NAME
# SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# readonly SCRIPT_DIR
readonly DOCKER_HUB_API_BASE="https://registry.hub.docker.com/v2/repositories"
readonly DOCKER_HUB_TOKEN_URL="https://auth.docker.io/token"

# Default settings
CHECK_DOCKER=true
CHECK_PODMAN=true
CHECK_ALL=false
CHECK_UPDATES=false
DEBUG_MODE=0
DOCKER_HUB_USERNAME="${DOCKER_HUB_USERNAME:-}"
DOCKER_HUB_TOKEN="${DOCKER_HUB_TOKEN:-}"
SPECIFIC_IMAGE=""

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
# readonly PURPLE='\033[0;35m'
readonly CYAN='\033[0;36m'
readonly NC='\033[0m' # No Color

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

log_warn() {
    echo >&2 "[WARN] [${SCRIPT_NAME}] $(date '+%Y-%m-%d %H:%M:%S') - $*"
}

# Function to print colored output
print_colored() {
    local color="$1"
    local message="$2"
    echo -e "${color}${message}${NC}"
}

# Display usage information
usage() {
    cat << EOF
Usage: ${SCRIPT_NAME} [-h] [-d] [-p] [-a] [-u username] [-t token] [image_name]

Check Docker and Podman images on local machine and compare with available tags on Docker Hub.

Options:
    -h              Show this help message and exit
    -d              Check only Docker images
    -p              Check only Podman images
    -a              Check all available tags for each image (may be slow)
    -u username     Docker Hub username for private repositories
    -t token        Docker Hub access token for private repositories
    --updates       Check for available updates to local images
    --debug         Enable debug logging
    image_name      Check specific image name (e.g., 'nginx' or 'library/nginx')

Environment Variables:
    DOCKER_HUB_USERNAME    Docker Hub username (alternative to -u)
    DOCKER_HUB_TOKEN       Docker Hub access token (alternative to -t)

Examples:
    # Check all local images (Docker and Podman)
    ${SCRIPT_NAME}
    
    # Check only Docker images
    ${SCRIPT_NAME} -d
    
    # Check only Podman images
    ${SCRIPT_NAME} -p
    
    # Check specific image
    ${SCRIPT_NAME} nginx
    
    # Check all tags for specific image
    ${SCRIPT_NAME} -a nginx
    
    # Check for available updates
    ${SCRIPT_NAME} --updates
    
    # Use Docker Hub credentials
    ${SCRIPT_NAME} -u myusername -t mytoken nginx

Notes:
    - Requires docker and/or podman to be installed and running
    - Uses Docker Hub public API (rate limited)
    - For private repositories, provide username and token
    - The -a flag may be slow for images with many tags
EOF
    exit 1
}

# Validate prerequisites
validate_prerequisites() {
    local missing_deps=()
    
    # Check for jq
    if ! command -v jq >/dev/null 2>&1; then
        missing_deps+=("jq")
    fi
    
    # Check for curl
    if ! command -v curl >/dev/null 2>&1; then
        missing_deps+=("curl")
    fi
    
    # Check for grep
    if ! command -v grep >/dev/null 2>&1; then
        missing_deps+=("grep")
    fi
    
    # Check for sort
    if ! command -v sort >/dev/null 2>&1; then
        missing_deps+=("sort")
    fi
    
    # Check for at least one container runtime
    if [[ "$CHECK_DOCKER" == true ]] && ! command -v docker >/dev/null 2>&1; then
        log_warn "Docker is not installed or not in PATH"
        CHECK_DOCKER=false
    fi
    
    if [[ "$CHECK_PODMAN" == true ]] && ! command -v podman >/dev/null 2>&1; then
        log_warn "Podman is not installed or not in PATH"
        CHECK_PODMAN=false
    fi
    
    if [[ "$CHECK_DOCKER" == false && "$CHECK_PODMAN" == false ]]; then
        log_error "Neither Docker nor Podman is available"
        exit 1
    fi
    
    # Report missing dependencies
    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log_error "Missing required dependencies: ${missing_deps[*]}"
        exit 1
    fi
}

# Get Docker Hub access token
get_docker_hub_token() {
    local username="$1"
    local password="$2"
    
    log_debug "Attempting to get Docker Hub token for user: $username"
    
    if [[ -z "$username" || -z "$password" ]]; then
        log_debug "Username or password not provided, skipping token authentication"
        return 0
    fi
    
    local token
    if token=$(curl -s -u "$username:$password" "$DOCKER_HUB_TOKEN_URL?service=registry.docker.io&scope=repository:library/hello-world:pull" | jq -r '.token'); then
        if [[ "$token" != "null" && -n "$token" ]]; then
            log_debug "Successfully obtained Docker Hub token"
            echo "$token"
            return 0
        fi
    fi
    
    log_warn "Failed to get Docker Hub token, using public API"
    return 1
}

# Get available tags from Docker Hub
get_docker_hub_tags() {
    local image_name="$1"
    local token="$2"
    
    log_debug "Fetching tags for image: $image_name"
    
    # Normalize image name
    if [[ ! "$image_name" =~ / ]]; then
        image_name="library/$image_name"
        log_debug "Normalized image name to: $image_name"
    fi
    
    local url="$DOCKER_HUB_API_BASE/$image_name/tags"
    local curl_args=()
    
    if [[ -n "$token" ]]; then
        curl_args+=("-H" "Authorization: Bearer $token")
        log_debug "Using authenticated request for $image_name"
    else
        log_debug "Using public API request for $image_name"
    fi
    
    local response
    if response=$(curl -s "${curl_args[@]}" "$url"); then
        if echo "$response" | jq -e '.results' >/dev/null 2>&1; then
            local tag_count
            tag_count=$(echo "$response" | jq -r '.results[].name' | wc -l)
            log_debug "Successfully fetched $tag_count tags for $image_name"
            echo "$response" | jq -r '.results[].name' | sort
            return 0
        else
            log_warn "Failed to parse response for $image_name"
            log_debug "Response content: ${response:0:200}..."
            return 1
        fi
    else
        log_warn "Failed to fetch tags for $image_name"
        return 1
    fi
}

# Get local Docker images
get_docker_images() {
    if [[ "$CHECK_DOCKER" == false ]]; then
        log_debug "Docker checking disabled, skipping"
        return 0
    fi
    
    log_info "Fetching local Docker images..."
    
    if ! docker info >/dev/null 2>&1; then
        log_warn "Docker daemon is not running or not accessible"
        return 1
    fi
    
    log_debug "Executing: docker images --format json"
    docker images --format json | jq -r 'select(.Repository != "<none>" and .Repository != null) | "\(.Repository):\(.Tag)"' | while IFS= read -r image; do
        if [[ -n "$image" ]]; then
            log_debug "Found Docker image: $image"
            echo "$image"
        fi
    done
}

# Get local Podman images
get_podman_images() {
    if [[ "$CHECK_PODMAN" == false ]]; then
        log_debug "Podman checking disabled, skipping"
        return 0
    fi
    
    log_info "Fetching local Podman images..."
    
    if ! podman info >/dev/null 2>&1; then
        log_warn "Podman is not running or not accessible"
        return 1
    fi
    
    log_debug "Executing: podman images --format json"
    podman images --format json | jq -r '.[] | select(.Repository != "<none>" and .Repository != null) | "\(.Repository):\(.Tag)"' | while IFS= read -r image; do
        if [[ -n "$image" ]]; then
            log_debug "Found Podman image: $image"
            echo "$image"
        fi
    done
}

# Parse image name and tag
parse_image() {
    local full_image="$1"
    local image_name
    local tag
    
    log_debug "Parsing image: $full_image"
    
    if [[ "$full_image" =~ : ]]; then
        image_name="${full_image%:*}"
        tag="${full_image#*:}"
        log_debug "Parsed as: image_name=$image_name, tag=$tag"
    else
        image_name="$full_image"
        tag="latest"
        log_debug "Parsed as: image_name=$image_name, tag=$tag (default)"
    fi
    
    echo "$image_name:$tag"
}

# Check if tag exists on Docker Hub
check_tag_exists() {
    local image_name="$1"
    local tag="$2"
    local hub_tags="$3"
    
    log_debug "Checking if tag '$tag' exists for image '$image_name'"
    
    if echo "$hub_tags" | grep -q "^${tag}$"; then
        log_debug "Tag '$tag' found for image '$image_name'"
        return 0
    else
        log_debug "Tag '$tag' not found for image '$image_name'"
        return 1
    fi
}

# Compare version numbers (simple semantic versioning)
compare_versions() {
    local version1="$1"
    local version2="$2"
    
    # Remove any non-numeric/alpha characters except dots and dashes
    local clean_v1="${version1//[^0-9a-zA-Z.-]/}"
    local clean_v2="${version2//[^0-9a-zA-Z.-]/}"
    
    # If versions are identical, return 0
    if [[ "$clean_v1" == "$clean_v2" ]]; then
        return 0
    fi
    
    # Split versions into components
    IFS='.' read -ra v1_parts <<< "$clean_v1"
    IFS='.' read -ra v2_parts <<< "$clean_v2"
    
    # Compare each component
    local max_parts=$(( ${#v1_parts[@]} > ${#v2_parts[@]} ? ${#v1_parts[@]} : ${#v2_parts[@]} ))
    
    for ((i=0; i<max_parts; i++)); do
        local v1_part="${v1_parts[i]:-0}"
        local v2_part="${v2_parts[i]:-0}"
        
        # Convert to numbers if possible
        if [[ "$v1_part" =~ ^[0-9]+$ ]] && [[ "$v2_part" =~ ^[0-9]+$ ]]; then
            if ((v1_part > v2_part)); then
                return 1  # v1 > v2
            elif ((v1_part < v2_part)); then
                return 2  # v1 < v2
            fi
        else
            # String comparison for non-numeric parts
            if [[ "$v1_part" > "$v2_part" ]]; then
                return 1  # v1 > v2
            elif [[ "$v1_part" < "$v2_part" ]]; then
                return 2  # v1 < v2
            fi
        fi
    done
    
    return 0  # Equal
}

# Find the latest version from a list of tags
find_latest_version() {
    local hub_tags="$1"
    local current_tag="$2"
    
    log_debug "Finding latest version from available tags"
    
    # Filter out tags that are clearly not version numbers
    local version_tags
    version_tags=$(echo "$hub_tags" | grep -E '^[0-9]+\.[0-9]+(\.[0-9]+)?$|^latest$|^stable$|^main$|^mainline$')
    
    if [[ -z "$version_tags" ]]; then
        log_debug "No version-like tags found, returning current tag"
        echo "$current_tag"
        return 0
    fi
    
    local latest_tag="$current_tag"
    
    while IFS= read -r tag; do
        if [[ -n "$tag" ]]; then
            log_debug "Comparing tag '$tag' with current latest '$latest_tag'"
            compare_versions "$tag" "$latest_tag"
            case $? in
                1)  # tag > latest_tag
                    latest_tag="$tag"
                    log_debug "New latest tag found: $tag"
                    ;;
                2)  # tag < latest_tag
                    log_debug "Tag $tag is older than current latest $latest_tag"
                    ;;
                0)  # tag == latest_tag
                    log_debug "Tag $tag is equal to current latest $latest_tag"
                    ;;
            esac
        fi
    done <<< "$version_tags"
    
    echo "$latest_tag"
}

# Check for available updates
check_for_updates() {
    local image_name="$1"
    local current_tag="$2"
    local hub_tags="$3"
    
    log_debug "Checking for updates for $image_name:$current_tag"
    
    # Skip if current tag is 'latest' or similar
    if [[ "$current_tag" =~ ^(latest|stable|main|mainline)$ ]]; then
        log_debug "Current tag '$current_tag' is a floating tag, skipping update check"
        return 0
    fi
    
    local latest_tag
    latest_tag=$(find_latest_version "$hub_tags" "$current_tag")
    
    if [[ "$latest_tag" != "$current_tag" ]]; then
        log_debug "Update available: $current_tag -> $latest_tag"
        return 0
    else
        log_debug "No update available, current tag is latest"
        return 1
    fi
}

# Main function to check images
check_images() {
    local docker_hub_token="$1"
    local all_images=()
    
    log_debug "Starting image collection process"
    
    # Collect local images
    if [[ "$CHECK_DOCKER" == true ]]; then
        log_debug "Collecting Docker images..."
        while IFS= read -r image; do
            if [[ -n "$image" ]]; then
                all_images+=("$image")
                log_debug "Added Docker image: $image"
            fi
        done < <(get_docker_images)
    fi
    
    if [[ "$CHECK_PODMAN" == true ]]; then
        log_debug "Collecting Podman images..."
        while IFS= read -r image; do
            if [[ -n "$image" ]]; then
                all_images+=("$image")
                log_debug "Added Podman image: $image"
            fi
        done < <(get_podman_images)
    fi
    
    # Remove duplicates and sort
    log_debug "Removing duplicates and sorting images..."
    mapfile -t unique_images < <(printf '%s\n' "${all_images[@]}" | sort -u)
    
    log_debug "Total images collected: ${#all_images[@]}, unique images: ${#unique_images[@]}"
    
    if [[ ${#unique_images[@]} -eq 0 ]]; then
        log_info "No local images found"
        return 0
    fi
    
    log_info "Found ${#unique_images[@]} unique local images"
    echo
    
    # Process each image
    for full_image in "${unique_images[@]}"; do
        local parsed_image
        parsed_image=$(parse_image "$full_image")
        local image_name="${parsed_image%:*}"
        local tag="${parsed_image#*:}"
        
        log_debug "Processing image: $full_image (parsed: $image_name:$tag)"
        print_colored "$CYAN" "Checking: $full_image"
        
        # Get Docker Hub tags
        local hub_tags
        if hub_tags=$(get_docker_hub_tags "$image_name" "$docker_hub_token"); then
            if check_tag_exists "$image_name" "$tag" "$hub_tags"; then
                print_colored "$GREEN" "  ✓ Tag '$tag' exists on Docker Hub"
                
                # Check for updates if requested
                if [[ "$CHECK_UPDATES" == true ]]; then
                    if check_for_updates "$image_name" "$tag" "$hub_tags"; then
                        local latest_tag
                        latest_tag=$(find_latest_version "$hub_tags" "$tag")
                        if [[ "$latest_tag" != "$tag" ]]; then
                            print_colored "$BLUE" "  🔄 Update available: $tag → $latest_tag"
                        fi
                    else
                        print_colored "$GREEN" "  ✓ Already up to date"
                    fi
                fi
                
                # Show available tags if requested
                if [[ "$CHECK_ALL" == true ]]; then
                    local tag_count
                    tag_count=$(echo "$hub_tags" | wc -l)
                    print_colored "$BLUE" "  Available tags on Docker Hub ($tag_count total):"
                    echo "$hub_tags" | head -20 | while IFS= read -r available_tag; do
                        print_colored "$YELLOW" "    - $available_tag"
                    done
                    
                    if [[ "$tag_count" -gt 20 ]]; then
                        print_colored "$YELLOW" "    ... and $((tag_count - 20)) more tags"
                    fi
                fi
            else
                print_colored "$RED" "  ✗ Tag '$tag' not found on Docker Hub"
                
                # Show available tags if requested
                if [[ "$CHECK_ALL" == true ]]; then
                    local tag_count
                    tag_count=$(echo "$hub_tags" | wc -l)
                    print_colored "$BLUE" "  Available tags on Docker Hub ($tag_count total):"
                    echo "$hub_tags" | head -20 | while IFS= read -r available_tag; do
                        print_colored "$YELLOW" "    - $available_tag"
                    done
                    
                    if [[ "$tag_count" -gt 20 ]]; then
                        print_colored "$YELLOW" "    ... and $((tag_count - 20)) more tags"
                    fi
                fi
            fi
        else
            print_colored "$YELLOW" "  ? Could not fetch tags from Docker Hub"
        fi
        echo
    done
}

# Check specific image
check_specific_image() {
    local image_name="$1"
    local docker_hub_token="$2"
    
    log_info "Checking specific image: $image_name"
    
    # Get Docker Hub tags
    local hub_tags
    if hub_tags=$(get_docker_hub_tags "$image_name" "$docker_hub_token"); then
        local tag_count
        tag_count=$(echo "$hub_tags" | wc -l)
        print_colored "$GREEN" "Found $tag_count tags for '$image_name' on Docker Hub:"
        echo "$hub_tags"
    else
        log_error "Failed to fetch tags for '$image_name'"
        return 1
    fi
}

# Check for updates on all local images
check_updates_only() {
    local docker_hub_token="$1"
    local all_images=()
    
    log_info "Checking for available updates on local images..."
    
    # Collect local images
    if [[ "$CHECK_DOCKER" == true ]]; then
        log_debug "Collecting Docker images for update check..."
        while IFS= read -r image; do
            if [[ -n "$image" ]]; then
                all_images+=("$image")
                log_debug "Added Docker image for update check: $image"
            fi
        done < <(get_docker_images)
    fi
    
    if [[ "$CHECK_PODMAN" == true ]]; then
        log_debug "Collecting Podman images for update check..."
        while IFS= read -r image; do
            if [[ -n "$image" ]]; then
                all_images+=("$image")
                log_debug "Added Podman image for update check: $image"
            fi
        done < <(get_podman_images)
    fi
    
    # Remove duplicates and sort
    log_debug "Removing duplicates and sorting images for update check..."
    mapfile -t unique_images < <(printf '%s\n' "${all_images[@]}" | sort -u)
    
    log_debug "Total images collected for update check: ${#all_images[@]}, unique images: ${#unique_images[@]}"
    
    if [[ ${#unique_images[@]} -eq 0 ]]; then
        log_info "No local images found for update check"
        return 0
    fi
    
    log_info "Found ${#unique_images[@]} unique local images to check for updates"
    echo
    
    local update_count=0
    local up_to_date_count=0
    
    # Process each image
    for full_image in "${unique_images[@]}"; do
        local parsed_image
        parsed_image=$(parse_image "$full_image")
        local image_name="${parsed_image%:*}"
        local tag="${parsed_image#*:}"
        
        log_debug "Checking for updates: $full_image (parsed: $image_name:$tag)"
        print_colored "$CYAN" "Checking updates for: $full_image"
        
        # Get Docker Hub tags
        local hub_tags
        if hub_tags=$(get_docker_hub_tags "$image_name" "$docker_hub_token"); then
            if check_for_updates "$image_name" "$tag" "$hub_tags"; then
                local latest_tag
                latest_tag=$(find_latest_version "$hub_tags" "$tag")
                if [[ "$latest_tag" != "$tag" ]]; then
                    print_colored "$BLUE" "  🔄 Update available: $tag → $latest_tag"
                    ((update_count++))
                else
                    print_colored "$GREEN" "  ✓ Already up to date"
                    ((up_to_date_count++))
                fi
            else
                print_colored "$GREEN" "  ✓ Already up to date"
                ((up_to_date_count++))
            fi
        else
            print_colored "$YELLOW" "  ? Could not fetch tags from Docker Hub"
        fi
        echo
    done
    
    # Summary
    echo
    print_colored "$BLUE" "=== Update Summary ==="
    print_colored "$GREEN" "Up to date: $up_to_date_count"
    print_colored "$BLUE" "Updates available: $update_count"
    print_colored "$CYAN" "Total checked: ${#unique_images[@]}"
}

# Main function
main() {
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                usage
                ;;
            -d)
                CHECK_DOCKER=true
                CHECK_PODMAN=false
                shift
                ;;
            -p)
                CHECK_DOCKER=false
                CHECK_PODMAN=true
                shift
                ;;
            -a)
                CHECK_ALL=true
                shift
                ;;
            -u)
                DOCKER_HUB_USERNAME="$2"
                shift 2
                ;;
            -t)
                DOCKER_HUB_TOKEN="$2"
                shift 2
                ;;
            --updates)
                CHECK_UPDATES=true
                shift
                ;;
            --debug)
                DEBUG_MODE=1
                shift
                ;;
            -*)
                log_error "Invalid option: $1"
                usage
                ;;
            *)
                # This is the image name
                SPECIFIC_IMAGE="$1"
                shift
                ;;
        esac
    done
    
    log_debug "Starting main execution with settings:"
    log_debug "  CHECK_DOCKER=$CHECK_DOCKER"
    log_debug "  CHECK_PODMAN=$CHECK_PODMAN"
    log_debug "  CHECK_ALL=$CHECK_ALL"
    log_debug "  CHECK_UPDATES=$CHECK_UPDATES"
    log_debug "  DEBUG_MODE=$DEBUG_MODE"
    log_debug "  SPECIFIC_IMAGE=$SPECIFIC_IMAGE"
    
    # Validate prerequisites
    validate_prerequisites
    
    # Get Docker Hub token if credentials provided
    local docker_hub_token=""
    if [[ -n "$DOCKER_HUB_USERNAME" && -n "$DOCKER_HUB_TOKEN" ]]; then
        log_debug "Docker Hub credentials provided, attempting to get token"
        docker_hub_token=$(get_docker_hub_token "$DOCKER_HUB_USERNAME" "$DOCKER_HUB_TOKEN")
    else
        log_debug "No Docker Hub credentials provided, using public API"
    fi
    
    # Check images
    if [[ "$CHECK_UPDATES" == true ]]; then
        log_debug "Checking for updates on all local images"
        check_updates_only "$docker_hub_token"
    elif [[ -n "$SPECIFIC_IMAGE" ]]; then
        log_debug "Checking specific image: $SPECIFIC_IMAGE"
        check_specific_image "$SPECIFIC_IMAGE" "$docker_hub_token"
    else
        log_debug "Checking all local images"
        check_images "$docker_hub_token"
    fi
    
    log_info "Image tag check completed"
}

# Run main function
main "$@" 