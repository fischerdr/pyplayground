#!/bin/bash

# Exit immediately if any command exits with a non-zero status
set -e

# Function to display usage
usage() {
    echo "Usage: $0 -d DOMAIN_NAME [-m MEMORY_SIZE] [-c CPU_COUNT]"
    echo "  -d DOMAIN_NAME   Name of the KVM domain to resize (required)"
    echo "  -m MEMORY_SIZE   New memory size with unit (e.g., 2GB, 2048MB) (optional)"
    echo "  -c CPU_COUNT     New number of CPUs (optional)"
    echo "At least one of -m or -c must be specified."
    exit 1
}

# Function to convert memory size to KiB
convert_to_kib() {
    local size=$1
    if [[ "$size" =~ ^([0-9]+)([MmGg][Bb])$ ]]; then
        local value="${BASH_REMATCH[1]}"
        local unit="${BASH_REMATCH[2]}"
        case "$unit" in
            MB|mb) echo $((value * 1024)) ;;          # Convert MB to KiB
            GB|gb) echo $((value * 1024 * 1024)) ;;   # Convert GB to KiB
            *) echo "Error: Unsupported memory unit '$unit'."; exit 1 ;;
        esac
    else
        echo "Error: Invalid memory format '$size'. Use <value>MB or <value>GB."
        exit 1
    fi
}

# Parse command-line arguments
while getopts "d:m:c:" opt; do
    case $opt in
        d) DOMAIN_NAME="$OPTARG" ;;
        m) MEMORY_SIZE_RAW="$OPTARG" ;;
        c) CPU_COUNT="$OPTARG" ;;
        *) usage ;;
    esac
done

# Check if domain name is provided
if [[ -z "$DOMAIN_NAME" ]]; then
    usage
fi

# Ensure at least one of MEMORY_SIZE or CPU_COUNT is provided
if [[ -z "$MEMORY_SIZE_RAW" && -z "$CPU_COUNT" ]]; then
    echo "Error: At least one of -m (memory size) or -c (CPU count) must be specified."
    exit 1
fi

# Check if the domain exists
if ! virsh dominfo "$DOMAIN_NAME" > /dev/null 2>&1; then
    echo "Error: Domain '$DOMAIN_NAME' does not exist."
    exit 1
fi

# Convert memory size if provided
if [[ -n "$MEMORY_SIZE_RAW" ]]; then
    MEMORY_SIZE=$(convert_to_kib "$MEMORY_SIZE_RAW")
fi

# Get current memory size and CPU count
CURRENT_MEMORY=$(virsh dominfo "$DOMAIN_NAME" | grep "Used memory" | awk '{print $3}')
CURRENT_CPU_COUNT=$(virsh dominfo "$DOMAIN_NAME" | grep "CPU(s)" | awk '{print $2}')

# Display current configuration
echo "Current configuration of domain '$DOMAIN_NAME':"
echo "  Memory: ${CURRENT_MEMORY} KiB (approximately $((${CURRENT_MEMORY} / 1024)) MiB)"
echo "  CPUs: ${CURRENT_CPU_COUNT}"

# Resize memory if specified
if [[ -n "$MEMORY_SIZE" ]]; then
    echo "Setting maximum memory of domain '$DOMAIN_NAME' to ${MEMORY_SIZE_RAW} (${MEMORY_SIZE} KiB)..."
    virsh setmaxmem "$DOMAIN_NAME" "${MEMORY_SIZE}" --config
    echo "Setting active memory of domain '$DOMAIN_NAME' to ${MEMORY_SIZE_RAW} (${MEMORY_SIZE} KiB)..."
    virsh setmem "$DOMAIN_NAME" "${MEMORY_SIZE}" --config
fi

# Resize CPUs if specified
if [[ -n "$CPU_COUNT" ]]; then
    echo "Resizing CPU count of domain '$DOMAIN_NAME' to ${CPU_COUNT}..."
    virsh setvcpus "$DOMAIN_NAME" "${CPU_COUNT}" --config
fi

echo "Resize operation completed successfully."

# Check if the domain is running
if virsh domstate "$DOMAIN_NAME" | grep -iq "running"; then
    echo "The domain is currently running. Restarting for changes to take effect..."
    virsh shutdown "$DOMAIN_NAME"
    sleep 5
    virsh start "$DOMAIN_NAME"
    echo "Domain restarted successfully."
else
    echo "The domain is not running. Changes will take effect on the next start."
fi
