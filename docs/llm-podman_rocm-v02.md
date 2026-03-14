# ROCm GPU Container Runtime Reference

This document provides container runtime commands and configurations for running LLM servers with AMD ROCm GPU support using Podman.

## Table of Contents

- [Common ROCm Environment Variables](#common-rocm-environment-variables)
- [Open-WebUI Containers](#open-webui-containers)
- [Ollama Containers](#ollama-containers)
- [Ollama Docker Compose](#ollama-docker-compose)
- [Utilities and Aliases](#utilities-and-aliases)
- [llama.cpp Server Configurations](#llamacpp-server-configurations)

---

## Common ROCm Environment Variables

Key environment variables used across ROCm containers:

| Variable | Description | Example |
|----------|-------------|---------|
| `HSA_OVERRIDE_GFX_VERSION` | Override GPU architecture version for compatibility | `11.0.0` |
| `HIP_VISIBLE_DEVICES` | Select specific GPU(s) to use | `0` |
| `GPU_TARGETS` | Specific GPU architecture target | `gfx1100`, `gfx1151` |

---

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

---

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

### Ollama with ROCm (Vulkan Configuration)

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

---

## Ollama Docker Compose

**Use case**: Production deployment with comprehensive environment configuration.

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

### Optional: Resource Limits

```yaml
services:
  ollama:
    deploy:
      resources:
        limits:
          memory: 16G
        reservations:
          memory: 8G
```

### Optional: Custom Network

```yaml
services:
  ollama:
    networks:
      - ollama-network

networks:
  ollama-network:
    driver: bridge
```

### Environment Variable Reference

#### ROCm GPU Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `HSA_OVERRIDE_GFX_VERSION` | — | Override GPU architecture (e.g., `11.0.0`) |
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
| `OLLAMA_KEEP_ALIVE` | `1h` | How long to keep models loaded |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Maximum models loaded simultaneously |
| `OLLAMA_LOAD_TIMEOUT` | `5m` | Model loading timeout |
| `OLLAMA_NOPRUNE` | `false` | Disable automatic pruning of unused models |
| `OLLAMA_MODELS` | — | Custom models directory path (optional) |

#### Performance Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_NUM_PARALLEL` | `2` | Number of parallel requests |
| `OLLAMA_MAX_QUEUE` | `100` | Maximum queued requests |

#### GPU Optimization

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_SCHED_SPREAD` | `false` | Spread models across multiple GPUs |
| `OLLAMA_FLASH_ATTENTION` | `true` | Enable flash attention for memory efficiency |
| `OLLAMA_GPU_OVERHEAD` | `536870912` | Reserved VRAM per GPU (512MB in bytes) |
| `OLLAMA_KV_CACHE_TYPE` | `f16` | K/V cache precision |
| `OLLAMA_LLM_LIBRARY` | — | Force specific LLM library (e.g., `rocm`) |

---

## Utilities and Aliases

### Podman Interactive ROCm Alias

**Use case**: Quick access to ROCm-enabled container with common devices and capabilities.

```bash
alias drun='sudo podman run -it --network=host --device=/dev/kfd --device=/dev/dri \
  --group-add=video --ipc=host --cap-add=SYS_PTRACE \
  --security-opt seccomp=unconfined --shm-size 8G \
  -v $HOME/podmanx:/podmanx -w /podmanx'
```

### Podman Compose Management

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

---

## llama.cpp Server Configurations

See also: [amd-strix-halo-toolboxes](https://github.com/kyuz0/amd-strix-halo-toolboxes) for Strix Halo specific llama-server setup scripts.

### Common Parameter Reference

#### Memory and Context Parameters

| Parameter | Description | Typical Values |
|-----------|-------------|----------------|
| `--ctx-size` | Context window size | `32768`, `65536`, `98304`, `131072` |
| `--batch-size` | Logical maximum batch size | `2048`, `4096` |
| `--ubatch-size` | Physical micro-batch size | `256`, `512`, `1024` |
| `--cache-type-k` | Key cache quantization | `q8_0`, `bf16` |
| `--cache-type-v` | Value cache quantization | `q8_0`, `bf16` |
| `--keep` | Tokens to pin from initial prompt | `8192` |
| `--cache-reuse` | Min chunk size for KV cache reuse | `64` |
| `--ctx-checkpoints` | Max context checkpoints per slot | `64`, `128` |

#### GPU Parameters

| Parameter | Description | Typical Values |
|-----------|-------------|----------------|
| `-ngl` | GPU layers to offload | `99` (all layers) |
| `-fa` | Flash attention | `on`, `off`, `auto` |
| `--kv-unified` | Unified KV buffer across all sequences | flag |
| `--no-mmap` | Disable memory-mapped loading (required for ROCm unified memory) | flag |
| `--swa-full` | Full-size SWA cache (pure transformer models only) | flag |

#### Reasoning / Thinking Parameters

| Parameter | Description | Values |
|-----------|-------------|--------|
| `--reasoning` | Enable or disable thinking mode | `on`, `off`, `auto` |
| `--reasoning-format` | How thinking tokens appear in API response | `none`, `deepseek`, `auto` |
| `--reasoning-budget` | Token budget for thinking (-1 = unlimited, 0 = off) | `-1`, `0`, `N` |

> **Note on `--reasoning off` vs `--chat-template-kwargs`:** `--reasoning off` is the preferred first-class flag. The kwargs approach (`{"enable_thinking": false}`) is equivalent but more fragile under shell escaping.

> **Note on `--reasoning-format`:** Defaults to `auto` which detects from the model's Jinja template. Setting `deepseek` explicitly routes `<think>` blocks to `message.reasoning_content`, keeping `message.content` clean for agent parsers.

#### Generation Parameters

| Parameter | Description | Typical Values |
|-----------|-------------|----------------|
| `--temp` | Temperature | `0.6`–`1.0` |
| `--top-p` | Nucleus sampling | `0.90`–`0.95` |
| `--top-k` | Top-k sampling | `20`–`40` |
| `--min-p` | Minimum probability | `0.01`–`0.05` |
| `--repeat-penalty` | Repetition penalty | `1.0` (disabled for most models) |

#### Temperature Presets

```bash
# Precise coding / tool-calling (Qwen3.5, GLM)
--temp 0.6 --top-p 0.95 --top-k 20 --min-p 0.00

# Balanced coding (Qwen3-Coder-Next)
--temp 1.0 --top-p 0.95 --top-k 40 --min-p 0.01

# Tool calls / fast response (GLM-4.7-Flash)
--temp 0.7 --top-p 1.0 --min-p 0.01 --repeat-penalty 1.0

# Balanced general purpose
--temp 0.7 --top-p 0.9 --top-k 20 --min-p 0.05

# Creative / exploration
--temp 0.85 --top-p 0.95 --top-k 50 --min-p 0.02 \
  --presence-penalty 0.1 --frequency-penalty 0.1
```

### VRAM Optimization Notes

```bash
# KV cache quantization (quality vs memory tradeoff)
--cache-type-k q8_0 --cache-type-v q8_0     # Best quality, ROCm-safe
--cache-type-k bf16 --cache-type-v bf16     # Native ROCm dtype (older configs)

# Context window sizing guidance (128GB unified memory)
--ctx-size 131072   # Q6_K_XL quants with headroom
--ctx-size 98304    # Q8_K_XL quants with headroom
--ctx-size 65536    # Conservative / multi-slot

# --no-mmap is required on ROCm unified memory
# Eliminates page fault overhead during model warmup on gfx1151
```

### Router Mode Configuration

```bash
llama-server \
  --host 0.0.0.0 --port 10000 \
  --temp 1.0 --top-p 0.95 --min-p 0.01 \
  --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 \
  -fa on -ngl 99 --seed 42 --fit on --jinja \
  --batch-size 4096 --ubatch-size 1024 \
  --ctx-size 65536 \
  --log-prefix --log-timestamps
```

---

### Production Configurations — case (128GB, gfx1151)

#### Qwen3-Coder-Next 79.7B — Primary Precision Coding

- **Model**: `unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_XL`
- **Host**: `case.modmtrx.net` port `10001`
- **Context**: 64k tokens
- **Slots**: 1 (single-slot, cache-reuse optimized)
- **Use case**: Primary agent for structured code, NASM, YAML, configs — best output discipline, 37 TPS

```bash
llama-server \
  --alias "Qwen3-Coder-Next" \
  --host 0.0.0.0 --port 10001 \
  -hf unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_XL \
  --temp 1.0 --top-p 0.95 --min-p 0.01 --top-k 40 \
  --reasoning off \
  --reasoning-format deepseek \
  -fa on -ngl 99 --seed 42 --jinja \
  --no-mmap \
  -np 1 \
  --batch-size 4096 --ubatch-size 256 \
  --ctx-size 65536 \
  --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 \
  --keep 8192 --cache-reuse 64 --ctx-checkpoints 128 \
  --swa-full \
  --metrics --log-prefix --log-timestamps
```

#### Qwen3.5-35B-A3B — Python / High-Level Secondary (Q8_K_XL)

- **Model**: `unsloth/Qwen3.5-35B-A3B-GGUF:UD-Q8_K_XL`
- **Host**: `case.modmtrx.net` port `10000`
- **Context**: 96k tokens
- **Slots**: 2
- **Use case**: Python refactoring, explanation, high-level work, multimodal. Not suitable for structured artifacts (over-generates structurally).

```bash
llama-server \
  --alias "Qwen3.5-35B-A3B" \
  --host 0.0.0.0 --port 10000 \
  -hf unsloth/Qwen3.5-35B-A3B-GGUF:UD-Q8_K_XL \
  --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0.00 \
  --reasoning off \
  --reasoning-format deepseek \
  -fa on -ngl 99 --seed 42 --jinja \
  --no-mmap \
  -np 2 \
  --batch-size 4096 --ubatch-size 512 \
  --ctx-size 98304 \
  --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 \
  --keep 8192 --cache-reuse 64 --ctx-checkpoints 64 \
  --image-min-tokens 2048 \
  --metrics --log-prefix --log-timestamps
```

#### Qwen3.5-35B-A3B — Python / High-Level Secondary (Q6_K_XL)

- **Model**: `unsloth/Qwen3.5-35B-A3B-GGUF:UD-Q6_K_XL`
- **Host**: `case.modmtrx.net` port `10000`
- **Context**: 131k tokens (Q6 saves ~17GB vs Q8, enabling larger context)
- **Slots**: 2
- **Use case**: Same role as Q8 variant. Q6_K_XL is near-lossless vs Q8 (perplexity delta ~0.004) with meaningful memory and speed gains.

```bash
llama-server \
  --alias "Qwen3.5-35B-A3B" \
  --host 0.0.0.0 --port 10000 \
  -hf unsloth/Qwen3.5-35B-A3B-GGUF:UD-Q6_K_XL \
  --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0.00 \
  --reasoning off \
  --reasoning-format deepseek \
  -fa on -ngl 99 --seed 42 --jinja \
  --no-mmap \
  -np 2 \
  --batch-size 4096 --ubatch-size 512 \
  --ctx-size 131072 \
  --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 \
  --keep 8192 --cache-reuse 64 --ctx-checkpoints 64 \
  --image-min-tokens 2048 \
  --metrics --log-prefix --log-timestamps
```

#### Qwen3.5-27B — Quality-Focused Alternative (Q6_K_XL)

- **Model**: `unsloth/Qwen3.5-27B-GGUF:UD-Q6_K_XL`
- **Host**: `case.modmtrx.net` port `10000`
- **Context**: 131k tokens
- **Slots**: 2
- **Use case**: Dense model, higher benchmark scores than 35B-A3B on coding (+6 LiveCodeBench, +3 SWE-bench) but 3–4× slower generation. Text-only — no multimodal.

```bash
llama-server \
  --alias "Qwen3.5-27B" \
  --host 0.0.0.0 --port 10000 \
  -hf unsloth/Qwen3.5-27B-GGUF:UD-Q6_K_XL \
  --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0.00 \
  --reasoning off \
  --reasoning-format deepseek \
  -fa on -ngl 99 --seed 42 --jinja \
  --no-mmap \
  -np 2 \
  --batch-size 4096 --ubatch-size 256 \
  --ctx-size 131072 \
  --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 \
  --keep 8192 --cache-reuse 64 --ctx-checkpoints 64 \
  --metrics --log-prefix --log-timestamps
```

#### Qwen3.5-27B — Quality-Focused Alternative (Q8_K_XL)

- **Model**: `unsloth/Qwen3.5-27B-GGUF:UD-Q8_K_XL`
- **Host**: `case.modmtrx.net` port `10000`
- **Context**: 96k tokens (Q8 ~35.5GB vs Q6 ~22GB, ctx reduced accordingly)
- **Slots**: 2
- **Use case**: Max quality variant. Same role as Q6 with marginal quality gain.

```bash
llama-server \
  --alias "Qwen3.5-27B" \
  --host 0.0.0.0 --port 10000 \
  -hf unsloth/Qwen3.5-27B-GGUF:UD-Q8_K_XL \
  --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0.00 \
  --reasoning off \
  --reasoning-format deepseek \
  -fa on -ngl 99 --seed 42 --jinja \
  --no-mmap \
  -np 2 \
  --batch-size 4096 --ubatch-size 256 \
  --ctx-size 98304 \
  --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 \
  --keep 8192 --cache-reuse 64 --ctx-checkpoints 64 \
  --metrics --log-prefix --log-timestamps
```

---

### Production Configurations — flyyn (64GB, gfx1151)

#### GLM-4.7-Flash — Fast One-Off Tasks (UD-Q6_K_XL) ✅ Current

- **Model**: `unsloth/GLM-4.7-Flash-GGUF:UD-Q6_K_XL`
- **Host**: `flyyn.modmtrx.net` port `10000`
- **Context**: 96k tokens
- **Slots**: 2
- **Use case**: Fast single-function / short script generation. Best efficiency model. 776 lines, 3 min wall time in NASM eval.

```bash
llama-server \
  --alias "GLM-4.7-Flash" \
  --host 0.0.0.0 --port 10000 \
  -hf unsloth/GLM-4.7-Flash-GGUF:UD-Q6_K_XL \
  --temp 0.7 --top-p 1.0 --min-p 0.01 --repeat-penalty 1.0 \
  --reasoning off \
  --reasoning-format deepseek \
  -fa on -ngl 99 --seed 42 --jinja \
  --no-mmap \
  --parallel 2 \
  --fit on \
  --batch-size 4096 --ubatch-size 256 \
  --ctx-size 98304 \
  --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 \
  --metrics --log-prefix --log-timestamps
```

---

### Experimental / Reference Configurations

These configs have been tested but are not currently in production rotation.

#### Qwen3-Coder-30B (High-Precision Code Generation)

- **Model**: `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q8_0`
- **Context**: 96k tokens
- **VRAM**: ~32GB

```bash
llama-server --alias "Qwen-Coder-30B" --host 0.0.0.0 --port 10000 \
  -hf unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q8_0 \
  -ngl 99 -np 1 --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 \
  -fa on --seed 42 \
  --temp 0.7 --top-p 0.9 --top-k 40 --min-p 0.05 --repeat-penalty 1.1 \
  --jinja --batch-size 4096 --ubatch-size 1024 \
  --ctx-size 98304 --no-mmap \
  --keep 8192 --ctx-checkpoints 128 --cache-reuse 64 --swa-full \
  --metrics --log-prefix --log-timestamps
```

#### Qwen3-VL-32B (Vision + Thinking)

- **Model**: `unsloth/Qwen3-VL-32B-Thinking-GGUF:Q8_0`
- **Context**: 64k tokens
- **VRAM**: ~34GB
- **Use case**: Multi-modal model supporting image analysis and reasoning

```bash
llama-server --alias "Qwen3-VL-32B-Thinking" --host 0.0.0.0 --port 10001 \
  -hf unsloth/Qwen3-VL-32B-Thinking-GGUF:Q8_0 \
  -ngl 99 --parallel 1 -fa on --seed 42 --kv-unified \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --temp 1.00 --top-p 0.95 --top-k 20 --min-p 0.05 --repeat-penalty 1.0 \
  --no-mmap --jinja \
  --batch-size 4096 --ubatch-size 1024 --ctx-size 65536 \
  --log-prefix --log-timestamps
```

#### Gemma-3-27B (Vision Model — Q5_K_XL)

- **Model**: `unsloth/gemma-3-27b-it-GGUF:Q5_K_XL`
- **Context**: 64k tokens
- **VRAM**: ~18GB
- **Use case**: Multi-modal vision tasks with reduced VRAM footprint

```bash
llama-server --alias "Gemma-3-27B-Vision" --host 0.0.0.0 --port 10002 \
  -hf unsloth/gemma-3-27b-it-GGUF:Q5_K_XL \
  -ngl 99 --parallel 1 -fa on --seed 42 --fit on \
  --temp 0.7 --top-p 0.9 --top-k 20 --min-p 0.05 --repeat-penalty 1.1 \
  --jinja --batch-size 4096 --ubatch-size 1024 \
  --ctx-size 65536 --log-prefix --log-timestamps
```

#### Gemma-3-27B (Vision Model — Q8_0)

- **Model**: `unsloth/gemma-3-27b-it-GGUF:Q8_0`
- **Context**: 64k tokens
- **VRAM**: ~28GB
- **Use case**: High-precision multi-modal vision tasks

```bash
llama-server --alias "Gemma-3-27B-Vision-HQ" --host 0.0.0.0 --port 10003 \
  -hf unsloth/gemma-3-27b-it-GGUF:Q8_0 \
  -ngl 99 --parallel 1 -fa on --seed 42 --fit on \
  --kv-unified --cache-type-k q8_0 --cache-type-v q8_0 \
  --temp 0.7 --top-p 0.9 --top-k 20 --min-p 0.05 --repeat-penalty 1.1 \
  --jinja --batch-size 4096 --ubatch-size 1024 \
  --ctx-size 65536 --log-prefix --log-timestamps
```

#### Mistral-Small-24B (Instruction Following)

- **Model**: `unsloth/Mistral-Small-3.2-24B-Instruct-2506-GGUF:UD-Q4_K_XL`
- **Context**: 32k tokens
- **VRAM**: ~16GB
- **Use case**: Balanced reasoning and instruction following

```bash
llama-server --alias "Mistral-Small-24B" --host 0.0.0.0 --port 10001 \
  -hf unsloth/Mistral-Small-3.2-24B-Instruct-2506-GGUF:UD-Q4_K_XL \
  -ngl 99 --parallel 1 -fa on --seed 42 --fit on \
  --temp 0.4 --top-p 0.95 --top-k 20 --min-p 0.05 --repeat-penalty 1.0 \
  --no-mmap --jinja --ctx-size 32768 -b 4096 \
  --log-prefix --log-timestamps
```

#### GPT-OSS-20B (Reasoning Engine)

- **Model**: `unsloth/gpt-oss-20b-GGUF:Q5_K_M`
- **Context**: 32k tokens
- **VRAM**: ~14GB
- **Use case**: Dedicated reasoning and problem-solving tasks

```bash
llama-server --alias "gpt-oss-20b" --host 0.0.0.0 --port 10001 \
  -hf unsloth/gpt-oss-20b-GGUF:Q5_K_M \
  -ngl 999 -b 1024 --threads 12 --threads-batch 24 --parallel 1 -fa on \
  --seed 42 --temp 0.85 --top-p 0.9 --top-k 20 --min-p 0.05 --repeat-penalty 1.1 \
  --jinja --no-mmap --ctx-size 32768 \
  --log-prefix --log-timestamps
```

#### GLM-4.7-Flash — VRAM-Optimized Variants

These are reference configurations for systems with discrete VRAM constraints (not Strix Halo).

**High-End (24GB+ VRAM)**

```bash
llama-server --alias "GLM-4.7-Pro" --host 0.0.0.0 --port 10001 \
  -hf unsloth/GLM-4.7-Flash-GGUF:Q8_0 \
  --reasoning off \
  -ngl 99 --parallel 1 --kv-unified \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  -fa on --fit on --seed 42 \
  --temp 0.1 --top-p 0.9 --top-k 40 --min-p 0.05 \
  --jinja --batch-size 4096 --ubatch-size 1024 \
  --ctx-size 65536 --log-prefix --log-timestamps
```

**Performance (12–16GB VRAM)**

```bash
llama-server --alias "GLM-4.7-Balanced" --host 0.0.0.0 --port 10001 \
  -hf unsloth/GLM-4.7-Flash-GGUF:Q8_0 \
  --reasoning off \
  -ngl 99 --parallel 1 --kv-unified \
  --cache-type-k q5_k_m --cache-type-v q5_k_m \
  -fa on --fit on --seed 42 \
  --temp 0.1 --top-p 0.9 --top-k 40 --min-p 0.05 \
  --jinja --batch-size 2048 --ubatch-size 512 \
  --ctx-size 32768 --log-prefix --log-timestamps
```

**Budget (8–12GB VRAM)**

```bash
llama-server --alias "GLM-4.7-Lite" --host 0.0.0.0 --port 10001 \
  -hf unsloth/GLM-4.7-Flash-GGUF:Q5_K_XL \
  --reasoning off \
  -ngl 99 --parallel 1 --kv-unified \
  --cache-type-k q5_k_m --cache-type-v q5_k_m \
  -fa on --fit on --seed 42 \
  --temp 0.1 --top-p 0.9 --top-k 40 --min-p 0.05 \
  --jinja --batch-size 2048 --ubatch-size 512 \
  --ctx-size 32768 --log-prefix --log-timestamps
```

#### Codestral-22B (Code Agent)

- **Model**: `lmstudio-community/Codestral-22B-v0.1-GGUF:Q5_K_M`
- **Context**: 64k tokens
- **VRAM**: ~14GB

```bash
llama-server --alias "Codestral-Agent" --host 0.0.0.0 --port 10000 \
  -hf lmstudio-community/Codestral-22B-v0.1-GGUF:Q5_K_M \
  -ngl 99 --parallel 1 -fa on --seed 42 --fit on \
  --temp 0.1 --top-p 0.9 --top-k 40 --min-p 0.05 --repeat-penalty 1.1 \
  --jinja --batch-size 4096 --ubatch-size 1024 \
  --ctx-size 65536 --log-prefix --log-timestamps
```