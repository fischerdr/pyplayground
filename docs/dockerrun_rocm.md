# ROCm GPU Container Runtime Reference

This document provides container runtime commands and configurations for running LLM servers with AMD ROCm GPU support using Podman.

## Table of Contents

- [Common ROCm Environment Variables](#common-rocm-environment-variables)
- [Open-WebUI Containers](#open-webui-containers)
- [Ollama Containers](#ollama-containers)
- [Ollama Docker Compose](#ollama-docker-compose)
- [Utilities and Aliases](#utilities-and-aliases)
- [llama.cpp Server Configurations](#llamacpp-server-configurations)

## Common ROCm Environment Variables

Key environment variables used across ROCm containers:

- `HSA_OVERRIDE_GFX_VERSION`: Override GPU architecture version (e.g., `11.0.0` for compatibility)
- `HIP_VISIBLE_DEVICES`: Select specific GPU(s) to use (e.g., `0` for first GPU)
- `GPU_TARGETS`: Specific GPU architecture target (e.g., `gfx1100`, `gfx1151`)

## Open-WebUI Containers

### Open-WebUI with Integrated Ollama

**Use case**: All-in-one solution with Ollama backend included.

```bash
podman run -d -p 3000:8080 \
  --group-add video \
  --security-opt seccomp=unconfined \
  --security-opt apparmor=unconfined \
  --device /dev/kfd \
  --device /dev/dri \
  --shm-size 16G \
  -v /opt/rocm:/opt/rocm:ro \
  -v ollama:/root/.ollama \
  -v open-webui:/app/backend/data \
  -e HSA_OVERRIDE_GFX_VERSION=11.0.0 \
  -e HIP_VISIBLE_DEVICES=0 \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:ollama
```

### Open-WebUI with Remote Ollama (HTTPS)

**Use case**: Connect to remote Ollama instance with HTTPS.

```bash
podman run -d -p 3000:8080 \
  --group-add video \
  --security-opt seccomp=unconfined \
  --security-opt apparmor=unconfined \
  -e OLLAMA_BASE_URL=https://flyyn.modmtrx.net:11434 \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:main
```

### Open-WebUI with Remote Ollama (HTTP + host network)

**Use case**: Connect to local Ollama on host network.

```bash
podman run -d -p 3000:8080 \
  -e OLLAMA_BASE_URL=http://flyyn.modmtrx.net:11434 \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  --net host \
  ghcr.io/open-webui/open-webui:main
```

### Open-WebUI with Remote Ollama (HTTP + bridged network)

**Use case**: Standard bridged network configuration with remote Ollama.

```bash
podman run -d -p 3000:8080 \
  -v open-webui:/app/backend/data \
  -e OLLAMA_BASE_URL=http://flyyn.modmtrx.net:11434 \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:main
```

## Ollama Containers

### Ollama with ROCm (Basic Configuration)

**Use case**: Standard Ollama setup with flash attention enabled.

```bash
podman run -d --replace \
  --name ollama-rocm \
  --device=/dev/kfd \
  --device=/dev/dri \
  --group-add video \
  -e HSA_OVERRIDE_GFX_VERSION=11.0.0 \
  -e HIP_VISIBLE_DEVICES=0 \
  -e OLLAMA_FLASH_ATTENTION=true \
  -v ollama:/root/.ollama \
  -p 11434:11434 \
  ollama/ollama:rocm
```

## Ollama with ROCm (Vulkan Configuration)

**Use case**: Ollama setup with Vulkan backend.

```bash
podman run -d \
  --name ollama-rocm \
  --device=/dev/kfd \
  --device=/dev/dri \
  --group-add video \
  -e "OLLAMA_VULKAN=1" \
  -e "HIP_VISIBLE_DEVICES=-1" \
  -e "GGML_VK_VISIBLE_DEVICES=0" \
  -e "OLLAMA_NUM_PARALLEL=4" \
  -e "OLLAMA_MAX_LOADED_MODELS=4" \
  -e "OLLAMA_FLASH_ATTENTION=1" \
  -e "OLLAMA_MAX_QUEUE=1024" \
  -e "OLLAMA_KEEP_ALIVE=12h" \
  -v ollama:/root/.ollama \
  -p 11434:11434 \
  ollama/ollama:rocm
```

### Ollama with ROCm (Advanced Configuration)

**Use case**: Custom GPU layer offloading and keep-alive settings.

```bash
podman run -d --replace \
  --name ollama-rocm \
  --device=/dev/kfd \
  --device=/dev/dri \
  --group-add video \
  -e OLLAMA_GPU_LAYERS=49 \
  -e OLLAMA_KEEP_ALIVE=2m \
  -e HSA_OVERRIDE_GFX_VERSION=11.0.0 \
  --ipc=host \
  -v ollama:/root/.ollama \
  -p 11434:11434 \
  ollama/ollama:0.12.0-rc0-rocm
```

## Ollama Docker Compose

**Use case**: Production deployment with comprehensive environment configuration and documentation.

### Basic Docker Compose File

```yaml
version: '3.8'

services:
  ollama:
    image: ollama/ollama:rocm
    container_name: ollama
    restart: unless-stopped
    devices:
      - /dev/kfd:/dev/kfd
      - /dev/dri:/dev/dri
    ports:
      - "11434:11434"
    volumes:
      - ollama:/root/.ollama
    security_opt:
      - seccomp=unconfined
      - apparmor=unconfined
    group_add:
      - video
    environment:
      # ROCm GPU Configuration
      - HSA_OVERRIDE_GFX_VERSION=11.0.0
      - HIP_VISIBLE_DEVICES=0
      # Server Configuration
      - OLLAMA_HOST=0.0.0.0:11434
      - OLLAMA_ORIGINS=*
      - OLLAMA_DEBUG=0
      # Model Management
      - OLLAMA_KEEP_ALIVE=1h
      - OLLAMA_MAX_LOADED_MODELS=2
      - OLLAMA_LOAD_TIMEOUT=5m
      - OLLAMA_NOPRUNE=false
      # Performance Settings
      - OLLAMA_NUM_PARALLEL=2
      - OLLAMA_MAX_QUEUE=100
      # GPU Optimization
      - OLLAMA_SCHED_SPREAD=false
      - OLLAMA_FLASH_ATTENTION=true
      - OLLAMA_GPU_OVERHEAD=536870912
      - OLLAMA_KV_CACHE_TYPE=f16

volumes:
  ollama:
    driver: local
```

### Environment Variable Reference

#### ROCm GPU Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `HSA_OVERRIDE_GFX_VERSION` | - | Override GPU architecture (e.g., `11.0.0`) |
| `HIP_VISIBLE_DEVICES` | `0` | Select GPU device(s) to use |

#### Server Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `0.0.0.0:11434` | Listen address and port |
| `OLLAMA_ORIGINS` | `*` | CORS allowed origins (adjust for security) |
| `OLLAMA_DEBUG` | `0` | Enable debug logging (`0` or `1`) |

#### Model Management

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_KEEP_ALIVE` | `1h` | How long to keep models loaded (prevents GPU hangs) |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Maximum models loaded simultaneously |
| `OLLAMA_LOAD_TIMEOUT` | `5m` | Model loading timeout |
| `OLLAMA_NOPRUNE` | `false` | Disable automatic pruning of unused models |
| `OLLAMA_MODELS` | - | Custom models directory path (optional) |

#### Performance Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_NUM_PARALLEL` | `2` | Number of parallel requests (conservative for stability) |
| `OLLAMA_MAX_QUEUE` | `100` | Maximum queued requests |

#### GPU Optimization

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_SCHED_SPREAD` | `false` | Spread models across multiple GPUs |
| `OLLAMA_FLASH_ATTENTION` | `true` | Enable flash attention for memory efficiency |
| `OLLAMA_GPU_OVERHEAD` | `536870912` | Reserved VRAM per GPU (512MB in bytes) |
| `OLLAMA_KV_CACHE_TYPE` | `f16` | K/V cache precision (`f16` = 16-bit float) |
| `OLLAMA_LLM_LIBRARY` | - | Force specific LLM library (e.g., `rocm`) |

### Optional: Resource Limits

Add resource constraints to prevent system overload:

```yaml
services:
  ollama:
    # ... other configuration ...
    deploy:
      resources:
        limits:
          memory: 16G
        reservations:
          memory: 8G
```

### Optional: Custom Network

Create isolated network for Ollama services:

```yaml
services:
  ollama:
    # ... other configuration ...
    networks:
      - ollama-network

networks:
  ollama-network:
    driver: bridge
```

## Utilities and Aliases

### Podman Interactive ROCm Alias

**Use case**: Quick access to ROCm-enabled container with common devices and capabilities.

```bash
alias drun='sudo podman run -it --network=host --device=/dev/kfd --device=/dev/dri --group-add=video --ipc=host --cap-add=SYS_PTRACE --security-opt seccomp=unconfined --shm-size 8G -v $HOME/podmanx:/podmanx -w /podmanx'
```

### Podman Compose Management

Common commands for managing Ollama with podman-compose:

```bash
# Start Ollama service
podman-compose up -d

# Stop Ollama service
podman-compose down

# View logs
podman-compose logs -f ollama

# Restart service
podman-compose restart ollama

# Monitor resource usage
podman stats ollama

# Check for shared memory errors
podman-compose logs ollama | grep -i "shm\|memory"

# Update to latest image
podman-compose pull
podman-compose up -d
```

## llama.cpp Server Configurations

### Common Parameter Reference

Before diving into specific models, here are the common parameters used across configurations:

#### Memory and Context Parameters

| Parameter | Description | Typical Values |
|-----------|-------------|----------------|
| `--ctx-size` | Context window size | `16384`, `32768`, `65536`,`98304` |
| `--batch-size` | Batch processing size (-b) | `2048`, `4096` |
| `--ubatch-size` | Micro-batch size | `512`, `1024` |
| `--cache-type-k` | Key cache quantization | `q5_k_m`, `q8_0` |
| `--cache-type-v` | Value cache quantization | `q5_k_m`, `q8_0` |

#### GPU Parameters

| Parameter | Description | Typical Values |
|-----------|-------------|----------------|
| `-ngl` | GPU layers to offload | `99` (all layers) |
| `-fa` | Flash attention | `on`, `off`, `auto` |
| `--kv-unified` | Unified KV cache | flag (no value) |
| `--fit` | Fit KV cache to context | `on` |

#### Generation Parameters

| Parameter | Description | Typical Values |
|-----------|-------------|----------------|
| `--temp` | Temperature | `0.1`-`1.0` |
| `--top-p` | Nucleus sampling | `0.85`-`0.95` |
| `--top-k` | Top-k sampling | `20`-`40` |
| `--min-p` | Minimum probability | `0.01`-`0.1` |
| `--repeat-penalty` | Repetition penalty | `1.0`-`1.1` |

#### Temperature Presets

```bash
# Precise/Deterministic (code generation)
--temp 0.4 --top-p 0.85 --top-k 40 --min-p 0.1 --repeat-penalty 1.1

# Balanced (general purpose)
--temp 0.7 --top-p 0.9 --top-k 20 --min-p 0.05 --repeat-penalty 1.1

# Creative (thinking, exploration, storytelling)
--temp 0.85 --top-p 0.95 --top-k 50 --min-p 0.02 --repeat-penalty 1.05 --presence-penalty 0.1 --frequency-penalty 0.1
```

### VRAM Optimization Parameters

```bash
# Cache quantization (memory vs quality tradeoff)
--cache-type-k q8_0 --cache-type-v q8_0   # Highest quality (~20% more VRAM)
--cache-type-k q5_k_m --cache-type-v q5_k_m # Balanced (~15% less VRAM)

# Batch size adjustments
--batch-size 4096 --ubatch-size 1024  # High throughput (more VRAM)
--batch-size 2048 --ubatch-size 512   # Lower VRAM usage

# Context window sizes
--ctx-size 98304  # 96k tokens (~40GB VRAM, requires --no-mmap)
--ctx-size 65536  # 64k tokens (default, ~25GB VRAM)
--ctx-size 32768  # 32k tokens (budget, ~15GB VRAM)
```

### Router Mode Configuration

**Use case**: Router mode for routing requests between multiple models with optimized settings.

```bash
llama-server --host 0.0.0.0 --port 10000 --temp 1.0 --top-p 0.95 --min-p 0.01 --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 -fa on -ngl 99 --seed 42 --fit on --jinja --batch-size 4096 --ubatch-size 1024 --ctx-size 65536 --log-prefix --log-timestamps
```

### Code Generation Models

Optimized for code generation, completion, and technical writing tasks.

#### Codestral-22B (Code Agent)

- **Model**: Mistral AI's specialized code model
- **Quantization**: Q5_K_M
- **Context**: 64k tokens
- **VRAM**: ~14GB
- **Use case**: Code generation and completion tasks

```bash
llama-server --alias "Codestral-Agent" --host 0.0.0.0 --port 10000 \
  -hf lmstudio-community/Codestral-22B-v0.1-GGUF:Q5_K_M \
  -ngl 99 --parallel 1 --fa 2 --seed 42 --fit on \
  --temp 0.1 --top-p 0.9 --top-k 40 --min-p 0.05 --repeat-penalty 1.1 \
  --jinja --batch-size 4096 --ubatch-size 1024 \
  --ctx-size 65536 --log-prefix --log-timestamps
```

#### Qwen3-Coder-30B (High-Precision Code Generation)

- **Model**: Alibaba's high-precision code model
- **Quantization**: Q8_0
- **Context**: 64k tokens
- **VRAM**: ~32GB
- **Use case**: High-quality code generation with Q8 precision

```bash
llama-server --alias "Qwen-Coder-30B" --host 0.0.0.0 --port 10000 \
  -hf unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q8_0 \
  -ngl 99 --parallel 1 --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 \
  -fa 2 --fit on --seed 42 \
  --temp 0.1 --top-p 0.9 --top-k 40 --min-p 0.05 --repeat-penalty 1.1 \
  --jinja --batch-size 4096 --ubatch-size 1024 \
  --ctx-size 65536 --log-prefix --log-timestamps

llama-server --alias "Qwen-Coder-30B" --host 0.0.0.0 --port 10000 \
    -hf unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q8_0 \
    -ngl 99 -np 1 --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 \
    -fa on --fit on --seed 42 \
    --temp 0.7 --top-p 0.9 --top-k 40 --min-p 0.05 --repeat-penalty 1.1 \
    --jinja --batch-size 4096 --ubatch-size 1024 \
    --ctx-size 98304 --log-prefix --log-timestamps --metrics \
    --keep 8192 --ctx-checkpoints 128 --cache-reuse 64 --mlock --swa-full 

llama-server --alias "Qwen3.5-35B-A3B" --host 0.0.0.0 --port 10000 -hf unsloth/Qwen3.5-35B-A3B-GGUF:UD-Q4_K_XL --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0.00 -fa on --fit on --seed 42 -ngl 99 -np 1 --jinja --batch-size 4096 --ctx-size 98304 --log-prefix --log-timestamps

```

#### Qwen3-Coder-Next (Balanced code generation)

- **Model**: Unsloth Qwen3-Coder-Next
- **Quantization**: UD-Q4_K_XL
- **Context**: 64k tokens
- **VRAM**: ~20GB
- **Use case**: Code generation with balanced temperature (temp 0.7)

```bash
llama-server --alias "Qwen3-Coder-Next" --host 0.0.0.0 --port 10000 \
  -hf unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_XL \
  --ctx-size 98304 --temp 0.7 --top-p 0.9 --min-p 0.05 --top-k 40 \
  --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 \
  --batch-size 4096 --ubatch-size 256 \
  -fa on -ngl 99 --seed 42 --fit on --jinja --log-prefix --log-timestamps --no-mmap \
  --metrics --keep 8192 --ctx-checkpoints 128 --cache-reuse 64 --mlock --swa-full -np 1
```

#### GLM-4.7-Flash-Coder (Fast Code Generation)

- **Model**: Zhipu AI's fast code model
- **Quantization**: Q8_0
- **Context**: 64k tokens
- **VRAM**: ~12GB
- **Use case**: Fast code generation with thinking disabled

```bash
llama-server --alias "GLM-4.7-Flash-Coder" --host 0.0.0.0 --port 10001 \
  -hf unsloth/GLM-4.7-Flash-GGUF:Q8_0 \
  --chat-template-kwargs '{"enable_thinking": false}' \
  -ngl 99 --parallel 1 --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 \
  -fa 2 --fit on --seed 42 \
  --temp 0.1 --top-p 0.9 --top-k 40 --min-p 0.05 \
  --jinja --batch-size 4096 --ubatch-size 1024 \
  --ctx-size 65536 --log-prefix --log-timestamps
```

### GLM-4.7-Coder VRAM-Optimized Configurations

#### High-End Configuration (24GB+ VRAM)

- **Model**: GLM-4.7-Flash with thinking disabled for code generation
- **Quantization**: Q8_0
- **Context**: 64k tokens
- **VRAM**: ~24GB
- **Use case**: Maximum quality code generation with 64k context and Q8 cache

**Best for:** Maximum quality code generation with 64k context and Q8 cache. Requires 24GB+ VRAM.

```bash
llama-server --alias "GLM-4.7-Pro" --host 0.0.0.0 --port 10001 \
  -hf unsloth/GLM-4.7-Flash-GGUF:Q8_0 \
  --chat-template-kwargs '{"enable_thinking": false}' \
  -ngl 99 --parallel 1 --kv-unified \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  -fa 2 --fit on --seed 42 \
  --temp 0.1 --top-p 0.9 --top-k 40 --min-p 0.05 \
  --jinja --batch-size 4096 --ubatch-size 1024 \
  --ctx-size 65536 --log-prefix --log-timestamps
```

#### Performance Configuration (12GB - 16GB VRAM)

- **Model**: GLM-4.7-Flash with thinking disabled for code generation
- **Quantization**: Q8_0
- **Context**: 32k tokens
- **VRAM**: ~16GB
- **Use case**: Mid-range GPUs with reduced context and optimized cache settings

**Best for:** Mid-range GPUs with reduced context and optimized cache settings.

```bash
llama-server --alias "GLM-4.7-Balanced" --host 0.0.0.0 --port 10001 \
  -hf unsloth/GLM-4.7-Flash-GGUF:Q8_0 \
  --chat-template-kwargs '{"enable_thinking": false}' \
  -ngl 99 --parallel 1 --kv-unified \
  --cache-type-k q5_k_m --cache-type-v q5_k_m \
  -fa 2 --fit on --seed 42 \
  --temp 0.1 --top-p 0.9 --top-k 40 --min-p 0.05 \
  --jinja --batch-size 2048 --ubatch-size 512 \
  --ctx-size 32768 --log-prefix --log-timestamps
```

#### Budget Configuration (8-12GB VRAM)

- **Model**: GLM-4.7-Flash with thinking disabled for code generation
- **Quantization**: Q5_K_XL
- **Context**: 32k tokens
- **VRAM**: ~12GB
- **Use case**: Lightweight configuration with Q5 quantization and reduced context

**Best for:** Lightweight configuration with Q5 quantization and reduced context.

```bash
llama-server --alias "GLM-4.7-Lite" --host 0.0.0.0 --port 10001 \
  -hf unsloth/GLM-4.7-Flash-GGUF:Q5_K_XL \
  --chat-template-kwargs '{"enable_thinking": false}' \
  -ngl 99 --parallel 1 --kv-unified \
  --cache-type-k q5_k_m --cache-type-v q5_k_m \
  -fa 2 --fit on --seed 42 \
  --temp 0.1 --top-p 0.9 --top-k 40 --min-p 0.05 \
  --jinja --batch-size 2048 --ubatch-size 512 \
  --ctx-size 32768 --log-prefix --log-timestamps
```

### Vision and Reasoning Models

#### Gemma-3-27B (Vision Model - Q5_K_XL)

- **Model**: Google's Gemma 3 27B vision-language model
- **Quantization**: Q5_K_XL
- **Context**: 64k tokens
- **VRAM**: ~18GB
- **Use case**: Multi-modal vision tasks with reduced VRAM footprint

```bash
llama-server --alias "Gemma-3-27B-Vision" --host 0.0.0.0 --port 10002 \
  -hf unsloth/gemma-3-27b-it-GGUF:Q5_K_XL \
  -ngl 99 --parallel 1 --fa 2 --seed 42 --fit on \
  --temp 0.7 --top-p 0.9 --top-k 20 --min-p 0.05 --repeat-penalty 1.1 \
  --jinja --batch-size 4096 --ubatch-size 1024 \
  --ctx-size 65536 --log-prefix --log-timestamps
```

#### Gemma-3-27B (Vision Model - Q8_0)

- **Model**: Google's Gemma 3 27B vision-language model
- **Quantization**: Q8_0
- **Context**: 64k tokens
- **VRAM**: ~28GB
- **Use case**: High-precision multi-modal vision tasks

```bash
llama-server --alias "Gemma-3-27B-Vision-HQ" --host 0.0.0.0 --port 10003 \
  -hf unsloth/gemma-3-27b-it-GGUF:Q8_0 \
  -ngl 99 --parallel 1 --fa 2 --seed 42 --fit on \
  --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 \
  --temp 0.7 --top-p 0.9 --top-k 20 --min-p 0.05 --repeat-penalty 1.1 \
  --jinja --batch-size 4096 --ubatch-size 1024 \
  --ctx-size 65536 --log-prefix --log-timestamps
```

#### Qwen3-VL-32B (Vision + Thinking)

- **Model**: Multi-modal model with vision and reasoning
- **Quantization**: Q8_0
- **Context**: 64k tokens
- **VRAM**: ~34GB
- **Use case**: Multi-modal model supporting image analysis and reasoning

```bash
llama-server --alias "Qwen3-VL-32B-Thinking" --host 0.0.0.0 --port 10001 \
  -hf unsloth/Qwen3-VL-32B-Thinking-GGUF:Q8_0 \
  -ngl 99 --parallel 1 -fa on --seed 42 --kv-unified \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --temp 1.00 --top-p 0.95 --top-k 20 --min-p 0.05 --repeat-penalty 1.0 \
  --fit on --mlock --no-mmap --jinja \
  --batch-size 4096 --ubatch-size 1024 --ctx-size 65536 \
  --log-prefix --log-timestamps
```

#### Mistral-Small-24B (Instruction Following)

- **Model**: Balanced reasoning model
- **Quantization**: UD-Q4_K_XL
- **Context**: 32k tokens
- **VRAM**: ~16GB
- **Use case**: Balanced reasoning and instruction following tasks

```bash
llama-server --alias "Mistral-Small-24B" --host 0.0.0.0 --port 10001 \
  -hf unsloth/Mistral-Small-3.2-24B-Instruct-2506-GGUF:UD-Q4_K_XL \
  -ngl 99 --parallel 1 -fa on --seed 42 --fit on \
  --temp 0.4 --top-p 0.95 --top-k 20 --min-p 0.05 --repeat-penalty 1.0 \
  --mlock --no-mmap --jinja --ctx-size 32768 -b 4096 \
  --log-prefix --log-timestamps
```

### Reasoning and Thinking Models

#### GPT-OSS-20B (Reasoning Engine)

- **Model**: Reasoning-optimized model
- **Quantization**: Q5_K_M
- **Context**: 32k tokens
- **VRAM**: ~14GB
- **Use case**: Dedicated reasoning and problem-solving tasks

```bash
llama-server --alias "gpt-oss-20b" --host 0.0.0.0 --port 10001 \
  -hf unsloth/gpt-oss-20b-GGUF:Q5_K_M \
  -ngl 999 -b 1024 --threads 12 --threads-batch 24 --parallel 1 -fa on \
  --seed 42 --temp 0.85 --top-p 0.9 --top-k 20 --min-p 0.05 --repeat-penalty 1.1 \
  --jinja --no-mmap --mlock --ctx-size 32768 \
  --log-prefix --log-timestamps
```

#### GLM-4.7-Flash (Extended Context Thinking)

- **Model**: Extended context reasoning model
- **Quantization**: Q8_0
- **Context**: 96k tokens
- **VRAM**: ~18GB
- **Use case**: Large context reasoning tasks with extended 96k context window

```bash
llama-server --alias "GLM-4.7-Flash-Thinking" --host 0.0.0.0 --port 10000 \
  -hf unsloth/GLM-4.7-Flash-GGUF:Q8_0 \
  # --temp 0.7 --top-p 1.0 --min-p 0.01 --repeat-penalty 1.0 tools calls \
  --temp 1.0 --top-p 0.95 --min-p 0.01 -fa on \
  -ngl 99 --parallel 1 --seed 42 --fit on \
  --kv-unified --cache-type-k bf16 --cache-type-v bf16 \
  --jinja --batch-size 4096 --ubatch-size 1024 \
  --no-mmap --ctx-size 131072 --reasoning-format deepseek --metrics \
  --log-prefix --log-timestamps

llama-server   --alias "GLM-4.7-Flash" --host 0.0.0.0 --port 10000   -hf unsloth/GLM-4.7-Flash-GGUF:Q8_0 --temp 0.7 --top-p 1.0 --min-p 0.01 --repeat-penalty 1.0 -fa on --seed 42 --parallel 1 --no-mmap   --fit on --jinja   --batch-size 4096 --ubatch-size 1024   --ctx-size 131072 -ngl 99   --cache-type-k Q8_0 --cache-type-v Q8_0 --reasoning-format deepseek --metrics --log-prefix --log-timestamps --kv-unified   --chat-template-kwargs '{"enable_thinking": false}' 

llama-server   --alias "Qwen3.5-35B-A3B"   --host 0.0.0.0 --port 10000   -hf unsloth/Qwen3.5-35B-A3B-GGUF:UD-Q8_K_XL   --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0.00   --presence-penalty 0.0 -fa on --seed 42 -np 1 --jinja --no-mmap --batch-size 4096 --ubatch-size 1024 --ctx-size 131072 -ngl 99 --image-min-tokens 2048 --metrics   --log-prefix --log-timestamps --kv-unified --cache-type-k q8_0 --cache-type-v q8_0

```
