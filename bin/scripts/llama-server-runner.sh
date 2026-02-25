#!/bin/bash

# llama-server runner script with customizable configurations
# Supports both predefined models and custom parameter configuration

set -euo pipefail

# Default values
MODEL=""
ALIAS="llama-server"
HOST="0.0.0.0"
PORT="10000"
QUANTIZATION="Q5_K_M"  # Default quantization model
CONTEXT_SIZE_SHorthand=32  # Default to 32k context (32768 tokens)
BATCH_SIZE=2048
UBATCH_SIZE=512
GPU_LAYERS=99
FLASH_ATTENTION="auto"
KV_UNIFIED=false
FIT_KV_CACHE="on"
TEMPERATURE=0.7
TOP_P=0.9
TOP_K=20
MIN_P=0.05
REPEAT_PENALTY=1.1
SEED=42
PARALLEL=1
JINJA=true
MLOCK=false
NO_MMAP=false

# Predefined model configurations from the document
declare -A PREDEFINED_MODELS=(
    ["codestral"]="lmstudio-community/Codestral-22B-v0.1-GGUF:Q5_K_M"
    ["qwen-coder-30b"]="unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q8_0"
    ["glm-4.7-flash-coder"]="unsloth/GLM-4.7-Flash-GGUF:Q8_0"
    ["glm-4.7-pro"]="unsloth/GLM-4.7-Flash-GGUF:Q8_0"
    ["glm-4.7-balanced"]="unsloth/GLM-4.7-Flash-GGUF:Q8_0"
    ["glm-4.7-lite"]="unsloth/GLM-4.7-Flash-GGUF:Q5_K_XL"
    ["gemma-3-vision"]="unsloth/gemma-3-27b-it-GGUF:Q5_K_XL"
    ["gemma-3-vision-hq"]="unsloth/gemma-3-27b-it-GGUF:Q8_0"
    ["qwen3-vl-thinking"]="unsloth/Qwen3-VL-32B-Thinking-GGUF:Q8_0"
    ["mistral-small-24b"]="unsloth/Mistral-Small-3.2-24B-Instruct-2506-GGUF:UD-Q4_K_XL"
    ["gpt-oss-20b"]="unsloth/gpt-oss-20b-GGUF:Q5_K_M"
    ["glm-4.7-thinking"]="unsloth/GLM-4.7-Flash-GGUF:Q8_0"
)

# Context size mapping (shorthand to actual token values)
declare -A CONTEXT_SIZE_MAP=(
    [16]=16384
    [32]=32768
    [64]=65536
    [96]=98304
    [128]=131072
)

# Function to display usage information
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -m, --model MODEL              Model name (e.g., 'codestral', 'glm-4.7-pro')"
    echo "                                 or full model path like 'hf:meta-llama/Llama-3.2-1B-Instruct'"
    echo "  -a, --alias ALIAS              Server alias (default: llama-server)"
    echo "  -H, --host HOST                Host address (default: 0.0.0.0)"
    echo "  -p, --port PORT                Port number (default: 10000)"
    echo "  -q, --quantization Q           Quantization model (Q4_K_M, Q5_K_XL, Q8_0) (default: Q5_K_M)"
    echo "  -c, --ctx-size SIZE            Context size shorthand (16,32,64,96,128) (default: 32)"
    echo "  -b, --batch-size SIZE          Batch processing size (default: 2048)"
    echo "  -u, --ubatch-size SIZE         Micro-batch size (default: 512)"
    echo "  -n, --ngl LAYERS               GPU layers to offload (default: 99)"
    echo "  -f, --flash-attention MODE     Flash attention mode (on/off/auto) (default: auto)"
    echo "  -k, --kv-unified               Enable unified KV cache"
    echo "  --fit                          Fit KV cache to context (default: on)"
    echo "  --temp TEMP                    Temperature for generation (default: 0.7)"
    echo "  --top-p P                      Top-p sampling (default: 0.9)"
    echo "  --top-k K                      Top-k sampling (default: 20)"
    echo "  --min-p P                      Minimum probability (default: 0.05)"
    echo "  --repeat-penalty PENALTY       Repetition penalty (default: 1.1)"
    echo "  --seed SEED                    Random seed (default: 42)"
    echo "  --parallel N                   Parallel processing (default: 1)"
    echo "  --no-jinja                     Disable Jinja template support"
    echo "  -l, --mlock                    Enable memory locking"
    echo "  --no-mmap                      Disable memory mapping"
    echo "  -h, --help                     Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 -m codestral"
    echo "  $0 -m glm-4.7-pro -c 64 -q Q8_0"
    echo "  $0 -m hf:meta-llama/Llama-3.2-1B-Instruct -c 96 --no-mmap"
    echo "  $0 --model mistral-small-24b --temp 0.4 --top-p 0.85 --mlock"
}

# Function to validate context size shorthand
validate_context_size() {
    local size=$1
    if [[ ! -v CONTEXT_SIZE_MAP[$size] ]]; then
        echo "Error: Invalid context size shorthand '$size'. Valid values are: ${!CONTEXT_SIZE_MAP[*]}"
        exit 1
    fi
}

# Function to validate quantization model
validate_quantization() {
    local quant=$1
    case "$quant" in
        Q4_K_M|Q5_K_XL|Q8_0|q5_k_m|q8_0)
            return 0
            ;;
        *)
            echo "Error: Invalid quantization model '$quant'. Valid values are: Q4_K_M, Q5_K_XL, Q8_0"
            exit 1
            ;;
    esac
}

# Function to parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -m|--model)
                MODEL="$2"
                shift 2
                ;;
            -a|--alias)
                ALIAS="$2"
                shift 2
                ;;
            -H|--host)
                HOST="$2"
                shift 2
                ;;
            -p|--port)
                PORT="$2"
                shift 2
                ;;
            -q|--quantization)
                QUANTIZATION="$2"
                validate_quantization "$QUANTIZATION"
                shift 2
                ;;
            -c|--ctx-size)
                CONTEXT_SIZE_SHorthand="$2"
                validate_context_size "$CONTEXT_SIZE_SHorthand"
                shift 2
                ;;
            -b|--batch-size)
                BATCH_SIZE="$2"
                shift 2
                ;;
            -u|--ubatch-size)
                UBATCH_SIZE="$2"
                shift 2
                ;;
            -n|--ngl)
                GPU_LAYERS="$2"
                shift 2
                ;;
            -f|--flash-attention)
                FLASH_ATTENTION="$2"
                shift 2
                ;;
            -k|--kv-unified)
                KV_UNIFIED=true
                shift
                ;;
            --fit)
                FIT_KV_CACHE="on"
                shift
                ;;
            --temp)
                TEMPERATURE="$2"
                shift 2
                ;;
            --top-p)
                TOP_P="$2"
                shift 2
                ;;
            --top-k)
                TOP_K="$2"
                shift 2
                ;;
            --min-p)
                MIN_P="$2"
                shift 2
                ;;
            --repeat-penalty)
                REPEAT_PENALTY="$2"
                shift 2
                ;;
            --seed)
                SEED="$2"
                shift 2
                ;;
            --parallel)
                PARALLEL="$2"
                shift 2
                ;;
            --no-jinja)
                JINJA=false
                shift
                ;;
            -l|--mlock)
                MLOCK=true
                shift
                ;;
            --no-mmap)
                NO_MMAP=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done
}

# Function to get actual context size from shorthand
get_context_size() {
    local shorthand=$1
    echo "${CONTEXT_SIZE_MAP[$shorthand]}"
}

# Function to build the llama-server command
build_command() {
    local cmd="llama-server --alias \"$ALIAS\" --host $HOST --port $PORT"
    
    # Add model parameter
    if [[ -n "$MODEL" ]]; then
        # Check if it's a predefined model or full path
        if [[ -v PREDEFINED_MODELS[$MODEL] ]]; then
            cmd="$cmd -hf ${PREDEFINED_MODELS[$MODEL]}"
        else
            # Assume it's a full HuggingFace path
            cmd="$cmd -hf $MODEL"
        fi
    else
        echo "Error: Model must be specified"
        usage
        exit 1
    fi
    
    # Add GPU parameters
    cmd="$cmd -ngl $GPU_LAYERS --parallel $PARALLEL"
    
    # Flash attention setting
    case "$FLASH_ATTENTION" in
        on|off|auto)
            cmd="$cmd -fa $FLASH_ATTENTION"
            ;;
        *)
            echo "Warning: Invalid flash attention mode '$FLASH_ATTENTION', using 'auto'"
            cmd="$cmd -fa auto"
            ;;
    esac
    
    # KV unified setting
    if [[ "$KV_UNIFIED" == true ]]; then
        cmd="$cmd --kv-unified"
    fi
    
    # Fit KV cache to context
    cmd="$cmd --fit $FIT_KV_CACHE"
    
    # Seed
    cmd="$cmd --seed $SEED"
    
    # Generation parameters
    cmd="$cmd --temp $TEMPERATURE --top-p $TOP_P --top-k $TOP_K --min-p $MIN_P --repeat-penalty $REPEAT_PENALTY"
    
    # Jinja template support
    if [[ "$JINJA" == true ]]; then
        cmd="$cmd --jinja"
    fi
    
    # Batch sizes
    cmd="$cmd --batch-size $BATCH_SIZE --ubatch-size $UBATCH_SIZE"
    
    # Context size (using the mapped value)
    local ctx_size=$(get_context_size "$CONTEXT_SIZE_SHorthand")
    cmd="$cmd --ctx-size $ctx_size"
    
    # Memory management flags
    if [[ "$MLOCK" == true ]]; then
        cmd="$cmd --mlock"
    fi
    
    if [[ "$NO_MMAP" == true ]]; then
        cmd="$cmd --no-mmap"
    fi
    
    # Logging parameters (always included)
    cmd="$cmd --log-prefix --log-timestamps"
    
    echo "$cmd"
}

# Main execution function
main() {
    parse_args "$@"
    
    # Build and execute the command
    local final_cmd=$(build_command)
    echo "Executing: $final_cmd"
    eval "$final_cmd"
}

# Run main with all arguments
main "$@"
