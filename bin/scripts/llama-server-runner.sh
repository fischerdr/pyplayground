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
CONTEXT_SIZE_SHORTHAND=32  # Default to 32k context (32768 tokens)
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
CACHE_TYPE_K=""
CACHE_TYPE_V=""
METRICS=false
KEEP=""
CTX_CHECKPOINTS=""
CACHE_REUSE=""
SWA_FULL=false
CHAT_TEMPLATE_KWARGS=""
THREADS=""
THREADS_BATCH=""

# Predefined model configurations (HF path) from docs/dockerrun_rocm.md
declare -A PREDEFINED_MODELS=(
    ["codestral"]="lmstudio-community/Codestral-22B-v0.1-GGUF:Q5_K_M"
    ["qwen-coder-30b"]="unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q8_0"
    ["qwen3-coder-next"]="unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_XL"
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

# Model presets from docs/dockerrun_rocm.md: each value is newline-separated VAR=value (CLI overrides when parse_args runs)
# Format: MODEL_PRESETS[model]="KEY1=val1"$'\n'"KEY2=val2" ...
# For JSON values use: CHAT_TEMPLATE_KWARGS=\"{\\\"enable_thinking\\\": false}\"
declare -A MODEL_PRESETS=(
    ["codestral"]="ALIAS=Codestral-Agent"$'\n'"PORT=10000"$'\n'"CONTEXT_SIZE_SHORTHAND=64"$'\n'"BATCH_SIZE=4096"$'\n'"UBATCH_SIZE=1024"$'\n'"FLASH_ATTENTION=2"$'\n'"TEMPERATURE=0.1"$'\n'"TOP_P=0.9"$'\n'"TOP_K=40"$'\n'"MIN_P=0.05"$'\n'"REPEAT_PENALTY=1.1"$'\n'"KV_UNIFIED=false"$'\n'"CACHE_TYPE_K="$'\n'"CACHE_TYPE_V="
    ["qwen-coder-30b"]="ALIAS=Qwen-Coder-30B"$'\n'"PORT=10000"$'\n'"CONTEXT_SIZE_SHORTHAND=64"$'\n'"BATCH_SIZE=4096"$'\n'"UBATCH_SIZE=1024"$'\n'"FLASH_ATTENTION=2"$'\n'"KV_UNIFIED=true"$'\n'"CACHE_TYPE_K=q8_0"$'\n'"CACHE_TYPE_V=q8_0"$'\n'"TEMPERATURE=0.1"$'\n'"TOP_P=0.9"$'\n'"TOP_K=40"$'\n'"MIN_P=0.05"$'\n'"REPEAT_PENALTY=1.1"
    ["qwen3-coder-next"]="ALIAS=Qwen3-Coder-Next"$'\n'"PORT=10000"$'\n'"CONTEXT_SIZE_SHORTHAND=96"$'\n'"BATCH_SIZE=4096"$'\n'"UBATCH_SIZE=256"$'\n'"FLASH_ATTENTION=on"$'\n'"KV_UNIFIED=true"$'\n'"CACHE_TYPE_K=q8_0"$'\n'"CACHE_TYPE_V=q8_0"$'\n'"TEMPERATURE=0.7"$'\n'"TOP_P=0.9"$'\n'"TOP_K=40"$'\n'"MIN_P=0.05"$'\n'"NO_MMAP=true"$'\n'"METRICS=true"$'\n'"KEEP=8192"$'\n'"CTX_CHECKPOINTS=128"$'\n'"CACHE_REUSE=64"$'\n'"MLOCK=true"$'\n'"SWA_FULL=true"$'\n'"PARALLEL=1"
    ["glm-4.7-flash-coder"]="ALIAS=GLM-4.7-Flash-Coder"$'\n'"PORT=10001"$'\n'"CONTEXT_SIZE_SHORTHAND=64"$'\n'"BATCH_SIZE=4096"$'\n'"UBATCH_SIZE=1024"$'\n'"FLASH_ATTENTION=2"$'\n'"KV_UNIFIED=true"$'\n'"CACHE_TYPE_K=q8_0"$'\n'"CACHE_TYPE_V=q8_0"$'\n'"CHAT_TEMPLATE_KWARGS=\"{\\\"enable_thinking\\\": false}\""$'\n'"TEMPERATURE=0.1"$'\n'"TOP_P=0.9"$'\n'"TOP_K=40"$'\n'"MIN_P=0.05"
    ["glm-4.7-pro"]="ALIAS=GLM-4.7-Pro"$'\n'"PORT=10001"$'\n'"CONTEXT_SIZE_SHORTHAND=64"$'\n'"BATCH_SIZE=4096"$'\n'"UBATCH_SIZE=1024"$'\n'"FLASH_ATTENTION=2"$'\n'"KV_UNIFIED=true"$'\n'"CACHE_TYPE_K=q8_0"$'\n'"CACHE_TYPE_V=q8_0"$'\n'"CHAT_TEMPLATE_KWARGS=\"{\\\"enable_thinking\\\": false}\""$'\n'"TEMPERATURE=0.1"$'\n'"TOP_P=0.9"$'\n'"TOP_K=40"$'\n'"MIN_P=0.05"
    ["glm-4.7-balanced"]="ALIAS=GLM-4.7-Balanced"$'\n'"PORT=10001"$'\n'"CONTEXT_SIZE_SHORTHAND=32"$'\n'"BATCH_SIZE=2048"$'\n'"UBATCH_SIZE=512"$'\n'"FLASH_ATTENTION=2"$'\n'"KV_UNIFIED=true"$'\n'"CACHE_TYPE_K=q5_k_m"$'\n'"CACHE_TYPE_V=q5_k_m"$'\n'"CHAT_TEMPLATE_KWARGS=\"{\\\"enable_thinking\\\": false}\""$'\n'"TEMPERATURE=0.1"$'\n'"TOP_P=0.9"$'\n'"TOP_K=40"$'\n'"MIN_P=0.05"
    ["glm-4.7-lite"]="ALIAS=GLM-4.7-Lite"$'\n'"PORT=10001"$'\n'"CONTEXT_SIZE_SHORTHAND=32"$'\n'"BATCH_SIZE=2048"$'\n'"UBATCH_SIZE=512"$'\n'"FLASH_ATTENTION=2"$'\n'"KV_UNIFIED=true"$'\n'"CACHE_TYPE_K=q5_k_m"$'\n'"CACHE_TYPE_V=q5_k_m"$'\n'"CHAT_TEMPLATE_KWARGS=\"{\\\"enable_thinking\\\": false}\""$'\n'"TEMPERATURE=0.1"$'\n'"TOP_P=0.9"$'\n'"TOP_K=40"$'\n'"MIN_P=0.05"
    ["gemma-3-vision"]="ALIAS=Gemma-3-27B-Vision"$'\n'"PORT=10002"$'\n'"CONTEXT_SIZE_SHORTHAND=64"$'\n'"BATCH_SIZE=4096"$'\n'"UBATCH_SIZE=1024"$'\n'"FLASH_ATTENTION=2"$'\n'"TEMPERATURE=0.7"$'\n'"TOP_P=0.9"$'\n'"TOP_K=20"$'\n'"MIN_P=0.05"$'\n'"REPEAT_PENALTY=1.1"
    ["gemma-3-vision-hq"]="ALIAS=Gemma-3-27B-Vision-HQ"$'\n'"PORT=10003"$'\n'"CONTEXT_SIZE_SHORTHAND=64"$'\n'"BATCH_SIZE=4096"$'\n'"UBATCH_SIZE=1024"$'\n'"FLASH_ATTENTION=2"$'\n'"KV_UNIFIED=true"$'\n'"CACHE_TYPE_K=q8_0"$'\n'"CACHE_TYPE_V=q8_0"$'\n'"TEMPERATURE=0.7"$'\n'"TOP_P=0.9"$'\n'"TOP_K=20"$'\n'"MIN_P=0.05"$'\n'"REPEAT_PENALTY=1.1"
    ["qwen3-vl-thinking"]="ALIAS=Qwen3-VL-32B-Thinking"$'\n'"PORT=10001"$'\n'"CONTEXT_SIZE_SHORTHAND=64"$'\n'"BATCH_SIZE=4096"$'\n'"UBATCH_SIZE=1024"$'\n'"FLASH_ATTENTION=on"$'\n'"KV_UNIFIED=true"$'\n'"CACHE_TYPE_K=q8_0"$'\n'"CACHE_TYPE_V=q8_0"$'\n'"TEMPERATURE=1.0"$'\n'"TOP_P=0.95"$'\n'"TOP_K=20"$'\n'"MIN_P=0.05"$'\n'"REPEAT_PENALTY=1.0"$'\n'"MLOCK=true"$'\n'"NO_MMAP=true"
    ["mistral-small-24b"]="ALIAS=Mistral-Small-24B"$'\n'"PORT=10001"$'\n'"CONTEXT_SIZE_SHORTHAND=32"$'\n'"BATCH_SIZE=4096"$'\n'"UBATCH_SIZE=1024"$'\n'"FLASH_ATTENTION=on"$'\n'"TEMPERATURE=0.4"$'\n'"TOP_P=0.95"$'\n'"TOP_K=20"$'\n'"MIN_P=0.05"$'\n'"REPEAT_PENALTY=1.0"$'\n'"MLOCK=true"$'\n'"NO_MMAP=true"
    ["gpt-oss-20b"]="ALIAS=gpt-oss-20b"$'\n'"PORT=10001"$'\n'"CONTEXT_SIZE_SHORTHAND=32"$'\n'"BATCH_SIZE=1024"$'\n'"UBATCH_SIZE=512"$'\n'"GPU_LAYERS=999"$'\n'"FLASH_ATTENTION=on"$'\n'"THREADS=12"$'\n'"THREADS_BATCH=24"$'\n'"PARALLEL=1"$'\n'"TEMPERATURE=0.85"$'\n'"TOP_P=0.9"$'\n'"TOP_K=20"$'\n'"MIN_P=0.05"$'\n'"REPEAT_PENALTY=1.1"$'\n'"NO_MMAP=true"$'\n'"MLOCK=true"
    ["glm-4.7-thinking"]="ALIAS=GLM-4.7-Flash-Thinking"$'\n'"PORT=10001"$'\n'"CONTEXT_SIZE_SHORTHAND=96"$'\n'"BATCH_SIZE=4096"$'\n'"UBATCH_SIZE=1024"$'\n'"FLASH_ATTENTION=on"$'\n'"KV_UNIFIED=true"$'\n'"CACHE_TYPE_K=q8_0"$'\n'"CACHE_TYPE_V=q8_0"$'\n'"TEMPERATURE=1.0"$'\n'"TOP_P=0.95"$'\n'"MIN_P=0.01"$'\n'"MLOCK=true"$'\n'"NO_MMAP=true"
)

# Get model name from args (for applying preset before full parse)
get_model_from_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -m|--model)
                MODEL="$2"
                return
                ;;
        esac
        shift
    done
}

# Apply doc defaults for predefined model (CLI overrides when parse_args runs later)
apply_model_preset() {
    local m="${1:-}"
    [[ -z "$m" ]] && return
    [[ ! -v PREDEFINED_MODELS[$m] ]] && return
    [[ ! -v MODEL_PRESETS[$m] ]] && return

    local line
    while IFS= read -r line; do
        [[ -n "$line" ]] && eval "$line"
    done <<< "${MODEL_PRESETS[$m]}"
}

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
    echo "  -f, --flash-attention MODE     Flash attention mode (on/off/auto/2) (default: auto)"
    echo "  -k, --kv-unified               Enable unified KV cache"
    echo "  --cache-type-k TYPE            Key cache quantization (e.g. q5_k_m, q8_0)"
    echo "  --cache-type-v TYPE            Value cache quantization (e.g. q5_k_m, q8_0)"
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
    echo "  --metrics                      Enable metrics endpoint"
    echo "  --keep N                       Sliding window / keep N tokens (e.g. 8192)"
    echo "  --ctx-checkpoints N            Context checkpoints (e.g. 128)"
    echo "  --cache-reuse N                Cache reuse slots (e.g. 64)"
    echo "  --swa-full                     Enable full sliding window attention"
    echo "  --chat-template-kwargs JSON    Chat template kwargs (e.g. enable_thinking for GLM)"
    echo "  --threads N                   CPU threads (e.g. gpt-oss-20b uses 12)"
    echo "  --threads-batch N             Threads for batch (e.g. 24)"
    echo "  -h, --help                     Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 -m codestral"
    echo "  $0 -m qwen3-coder-next -c 64 --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 --no-mmap --metrics --mlock --swa-full"
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
        Q4_K_M|Q5_K_XL|Q8_0|UD-Q4_K_XL|q5_k_m|q8_0)
            return 0
            ;;
        *)
            echo "Error: Invalid quantization model '$quant'. Valid values are: Q4_K_M, Q5_K_XL, Q8_0, UD-Q4_K_XL"
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
                CONTEXT_SIZE_SHORTHAND="$2"
                validate_context_size "$CONTEXT_SIZE_SHORTHAND"
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
            --cache-type-k)
                CACHE_TYPE_K="$2"
                shift 2
                ;;
            --cache-type-v)
                CACHE_TYPE_V="$2"
                shift 2
                ;;
            --metrics)
                METRICS=true
                shift
                ;;
            --keep)
                KEEP="$2"
                shift 2
                ;;
            --ctx-checkpoints)
                CTX_CHECKPOINTS="$2"
                shift 2
                ;;
            --cache-reuse)
                CACHE_REUSE="$2"
                shift 2
                ;;
            --swa-full)
                SWA_FULL=true
                shift
                ;;
            --chat-template-kwargs)
                CHAT_TEMPLATE_KWARGS="$2"
                shift 2
                ;;
            --threads)
                THREADS="$2"
                shift 2
                ;;
            --threads-batch)
                THREADS_BATCH="$2"
                shift 2
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
    
    # Flash attention setting (on/off/auto or numeric e.g. 2 per doc)
    case "$FLASH_ATTENTION" in
        on|off|auto|2)
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

    # Cache type (optional, per doc)
    if [[ -n "$CACHE_TYPE_K" ]]; then
        cmd="$cmd --cache-type-k $CACHE_TYPE_K"
    fi
    if [[ -n "$CACHE_TYPE_V" ]]; then
        cmd="$cmd --cache-type-v $CACHE_TYPE_V"
    fi

    # Fit KV cache to context
    cmd="$cmd --fit $FIT_KV_CACHE"

    # Chat template kwargs (e.g. GLM enable_thinking)
    if [[ -n "$CHAT_TEMPLATE_KWARGS" ]]; then
        cmd="$cmd --chat-template-kwargs '$CHAT_TEMPLATE_KWARGS'"
    fi

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

    # Threads (e.g. gpt-oss-20b)
    if [[ -n "$THREADS" ]]; then
        cmd="$cmd --threads $THREADS"
    fi
    if [[ -n "$THREADS_BATCH" ]]; then
        cmd="$cmd --threads-batch $THREADS_BATCH"
    fi

    # Context size (using the mapped value)
    local ctx_size
    ctx_size=$(get_context_size "$CONTEXT_SIZE_SHORTHAND")
    cmd="$cmd --ctx-size $ctx_size"
    
    # Memory management flags
    if [[ "$MLOCK" == true ]]; then
        cmd="$cmd --mlock"
    fi
    
    if [[ "$NO_MMAP" == true ]]; then
        cmd="$cmd --no-mmap"
    fi

    # Optional doc options (e.g. qwen3-coder-next: metrics, keep, ctx-checkpoints, cache-reuse, swa-full)
    if [[ "$METRICS" == true ]]; then
        cmd="$cmd --metrics"
    fi
    if [[ -n "$KEEP" ]]; then
        cmd="$cmd --keep $KEEP"
    fi
    if [[ -n "$CTX_CHECKPOINTS" ]]; then
        cmd="$cmd --ctx-checkpoints $CTX_CHECKPOINTS"
    fi
    if [[ -n "$CACHE_REUSE" ]]; then
        cmd="$cmd --cache-reuse $CACHE_REUSE"
    fi
    if [[ "$SWA_FULL" == true ]]; then
        cmd="$cmd --swa-full"
    fi

    # Logging parameters (always included)
    cmd="$cmd --log-prefix --log-timestamps"

    echo "$cmd"
}

# Main execution function
main() {
    get_model_from_args "$@"
    apply_model_preset "$MODEL"
    parse_args "$@"

    validate_context_size "$CONTEXT_SIZE_SHORTHAND"

    # Build and execute the command
    local final_cmd=$(build_command)
    echo "Executing: $final_cmd"
    eval "$final_cmd"
}

# Run main with all arguments
main "$@"
