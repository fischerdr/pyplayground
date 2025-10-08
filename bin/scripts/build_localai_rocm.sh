#!/bin/bash

# Logging setup
LOG_FILE="localai_rocm_build_$(date +%Y%m%d_%H%M%S).log"
LOG_DIR="logs"

# Create logs directory if it doesn't exist with proper permissions
mkdir -p "$LOG_DIR" 2>/dev/null || {
    echo "Error: Cannot create log directory $LOG_DIR"
    exit 1
}

# Ensure log directory is writable
if [ ! -w "$LOG_DIR" ]; then
    echo "Error: Log directory $LOG_DIR is not writable"
    exit 1
fi

# Function to log messages with error handling
log_message() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local message="[$timestamp] $1"
    echo "$message"
    echo "$message" >> "$LOG_DIR/$LOG_FILE" 2>/dev/null || {
        echo "Warning: Could not write to log file $LOG_DIR/$LOG_FILE"
    }
}

# Function to safely append to log file
append_to_log() {
    local content="$1"
    echo "$content" >> "$LOG_DIR/$LOG_FILE" 2>/dev/null || {
        echo "Warning: Could not append to log file $LOG_DIR/$LOG_FILE"
    }
}

# ROCm Environment Setup Function
setup_rocm() {
    local rocm_path="${1:-/opt/rocm-6.4.1}"
    local gfx_arch="${2:-gfx1151}"
    local hsa_version="${3:-11.0.0}"
    local hip_device="${4:-1}"

    log_message "Setting up ROCm environment..."
    log_message "  ROCM_PATH: $rocm_path"
    log_message "  GFX_ARCH: $gfx_arch"
    log_message "  HSA_VERSION: $hsa_version"
    log_message "  HIP_DEVICE: $hip_device"

    # Core ROCm paths
    export ROCM_PATH="$rocm_path"
    export ROCM_HOME="$rocm_path"
    export HIP_PLATFORM=amd
    export __HIP_PLATFORM_AMD__=1

    # HIP configuration
    export HIP_PATH="$(hipconfig -R 2>/dev/null || echo "$rocm_path")"
    export HIP_CLANG_PATH="$(hipconfig -l 2>/dev/null || echo "$rocm_path/llvm/bin")"
    export HIP_INCLUDE_PATH="$rocm_path/include"
    export HIPCXX="$HIP_CLANG_PATH/clang"
    export HIP_LIB_PATH="$rocm_path/lib"
    # Correct path for ROCm device libraries
    export HIP_DEVICE_LIB_PATH="$rocm_path/lib/llvm/lib/clang/19/lib/amdgcn/bitcode"

    # Compiler flags
    export HIPCC_COMPILE_FLAGS_APPEND="$(hipconfig -C 2>/dev/null || echo '') -D__HIP_PLATFORM_AMD__"
    export HIP_CLANG_FLAGS="--rocm-path=$rocm_path -D__HIP_PLATFORM_AMD__ --rocm-device-lib-path=$HIP_DEVICE_LIB_PATH"

    # CMAKE configuration
    export CMAKE_HIP_COMPILER="$rocm_path/llvm/bin/clang"
    export CMAKE_HIP_COMPILER_ROCM_ROOT="$rocm_path"

    # Update PATH
    export PATH="$rocm_path/bin:$HIP_CLANG_PATH:$PATH"

    # Library paths
    export LD_LIBRARY_PATH="$rocm_path/lib:$rocm_path/lib64:$rocm_path/llvm/lib:$HIP_DEVICE_LIB_PATH:$LD_LIBRARY_PATH"
    export LIBRARY_PATH="$rocm_path/lib:$rocm_path/lib64:$LIBRARY_PATH"

    # Include paths
    export CPATH="$HIP_INCLUDE_PATH:$CPATH"
    export PKG_CONFIG_PATH="$rocm_path/lib/pkgconfig:$PKG_CONFIG_PATH"

    log_message "ROCm environment setup complete!"
    log_message "  HIP_DEVICE_LIB_PATH: $HIP_DEVICE_LIB_PATH"
}

# Function to build LocalAI with ROCm support
build_localai_rocm() {
    local gfx_target="${1:-gfx1151}"
    local build_type="${2:-hipblas}"
    local jobs="${3:-$(nproc)}"
    # Create a temporary file for build output
    local temp_output=$(mktemp)
    echo "temp_output: $temp_output"
    
    log_message "Building LocalAI with ROCm support..."
    log_message "  GPU Target: $gfx_target"
    log_message "  Build Type: $build_type"
    log_message "  Jobs: $jobs"
    log_message "  Log file: $LOG_DIR/$LOG_FILE"


    # Ensure ROCm environment is set up
    if [ -z "$ROCM_PATH" ]; then
        log_message "ROCm environment not set up. Running setup_rocm first..."
        setup_rocm
    fi

    # Build with comprehensive CMAKE arguments and proper ROCm overrides
    log_message "Starting build process..."
    
    
    # Run the build and capture output
    ROCM_HOME="$ROCM_PATH" \
    ROCM_PATH="$ROCM_PATH" \
    LD_LIBRARY_PATH="$ROCM_PATH/lib:$ROCM_PATH/llvm/lib:$LD_LIBRARY_PATH" \
    CXX="$ROCM_PATH/llvm/bin/clang++" \
    CC="$ROCM_PATH/llvm/bin/clang" \
    STABLE_BUILD_TYPE="" \
    GGML_HIP=1 \
    GPU_TARGETS="$gfx_target" \
    AMDGPU_TARGETS="$gfx_target" \
    CMAKE_ARGS="-DLLAMA_HIPBLAS=on \
-DCMAKE_HIP_COMPILER=$ROCM_PATH/llvm/bin/clang \
-DCMAKE_HIP_COMPILER_ROCM_ROOT=$ROCM_PATH \
-DROCM_PATH=$ROCM_PATH \
-DHIP_ROOT_DIR=$ROCM_PATH \
-DHIP_CLANG_PATH=$ROCM_PATH/llvm/bin \
-DHIP_DEVICE_LIB_PATH=$ROCM_PATH/lib/llvm/lib/clang/19/lib/amdgcn/bitcode \
-DCMAKE_PREFIX_PATH=$ROCM_PATH \
-DGGML_HIP=ON \
-DAMDGPU_TARGETS=$gfx_target \
-DGPU_TARGETS=$gfx_target \
-DCMAKE_HIP_FLAGS='--rocm-path=$ROCM_PATH -D__HIP_PLATFORM_AMD__ --rocm-device-lib-path=$ROCM_PATH/lib/llvm/lib/clang/19/lib/amdgcn/bitcode' \
-DCMAKE_CXX_FLAGS='-D__HIP_PLATFORM_AMD__ --rocm-device-lib-path=$ROCM_PATH/lib/llvm/lib/clang/19/lib/amdgcn/bitcode' \
-DCMAKE_C_FLAGS='-D__HIP_PLATFORM_AMD__ --rocm-device-lib-path=$ROCM_PATH/lib/llvm/lib/clang/19/lib/amdgcn/bitcode '" \
    BUILD_TYPE="$build_type" \
    GO_TAGS="tts,stablediffusion" \
    CGO_LDFLAGS="-O3 --rtlib=compiler-rt -unwindlib=libgcc -lhipblas -lrocblas --hip-link -L$ROCM_PATH/lib/llvm/lib" \
    make build 2>&1 | tee "$temp_output"
    
    local exit_code=${PIPESTATUS[0]}
    
    # Append the build output to our log file
    if [ -f "$temp_output" ]; then
        append_to_log "$(cat "$temp_output")"
        rm -f "$temp_output"
    fi
    
    if [ $exit_code -eq 0 ]; then
        log_message "Build completed successfully!"
    else
        log_message "Build failed with exit code: $exit_code"
        log_message "Check the log file for details: $LOG_DIR/$LOG_FILE"
    fi
    return $exit_code
}

# Main execution
if [ "$1" = "setup" ]; then
    setup_rocm "${2:-/opt/rocm-6.4.1}" "${3:-gfx1151}" "${4:-11.0.0}" "${5:-1}"
elif [ "$1" = "build" ]; then
    build_localai_rocm "${2:-gfx1151}" "${3:-hipblas}" "${4:-$(nproc)}"
elif [ "$1" = "build-silent" ]; then
    # Silent build - only log to file, no console output
    build_localai_rocm "${2:-gfx1151}" "${3:-hipblas}" "${4:-$(nproc)}" > /dev/null 2>&1
elif [ "$1" = "logs" ]; then
    # Show recent logs
    if [ -d "$LOG_DIR" ]; then
        echo "Recent build logs:"
        ls -la "$LOG_DIR"/*.log | tail -5
        echo ""
        echo "To view a specific log: tail -f $LOG_DIR/[logfile]"
    else
        echo "No logs directory found."
    fi
else
    echo "Usage:"
    echo "  $0 setup [rocm_path] [gfx_arch] [hsa_version] [hip_device]"
    echo "  $0 build [gfx_target] [build_type] [jobs]"
    echo "  $0 build-silent [gfx_target] [build_type] [jobs]  # Build without console output"
    echo "  $0 logs  # Show recent log files"
    echo ""
    echo "Examples:"
    echo "  $0 setup"
    echo "  $0 setup /opt/rocm-6.4.1 gfx1151"
    echo "  $0 build"
    echo "  $0 build gfx1151 hipblas"
    echo "  $0 build-silent gfx1151 hipblas  # Run in background"
    echo ""
    echo "Note: Make sure to run 'setup' first to configure the ROCm environment."
    echo "Logs will be saved to: $LOG_DIR/"
fi 