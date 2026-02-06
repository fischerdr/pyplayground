# Different podman runs

```bash
podman run -ti --name local-ai \
 -p 8080:8080 \
 --group-add video \
 --security-opt seccomp=unconfined \
 --security-opt apparmor=unconfined \
 --device /dev/kfd \
 --device /dev/dri \
 -v localai:/models \
 -v /opt/rocm/:/opt/rocm/ \
 -e HSA_OVERRIDE_GFX_VERSION=11.0.0 \
 -e DEBUG=true \
 -e REBUILD=true \
 -e BUILD_TYPE=hipblas \
 -e GPU_TARGETS=gfx1100 \
 quay.io/go-skynet/local-ai:master-aio-gpu-hipblas
```

```bash
podman run -ti --name local-ai \
  -p 8080:8080 \
  --group-add video \
  --security-opt seccomp=unconfined \
  --security-opt apparmor=unconfined \
  --device /dev/kfd \
  --device /dev/dri \
  --ipc=host \
  --shm-size 16G \
  -v ${PWD}/models:/models \
  -e HSA_OVERRIDE_GFX_VERSION=11.0.0 \
  -e GPU_TARGETS=gfx1151 \
  -e BUILD_TYPE=vulkan \
  -e DEBUG=true \
  localai/localai:master-aio-gpu-vulkan

```

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

podman run -d -p 3000:8080 \
    -e OLLAMA_BASE_URL=http://flyyn.modmtrx.net:11434 \
    -v open-webui:/app/backend/data \
    --name open-webui \
    --restart always \
    --net host \
    ghcr.io/open-webui/open-webui:main
    
podman run -d -p 3000:8080 \
    -v open-webui:/app/backend/data \
    -e OLLAMA_BASE_URL=http://flyyn.modmtrx.net:11434 \
    --name open-webui \
    --restart always \
    ghcr.io/open-webui/open-webui:main
```

```bash
podman run -d \
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
```bash
podman run -d --replace  --name ollama-rocm   --device=/dev/kfd   --device=/dev/dri   --group-add video -e OLLAMA_GPU_LAYERS=49 -e OLLAMA_KEEP_ALIVE=2m  -e HSA_OVERRIDE_GFX_VERSION=11.0.0 --ipc=host -v ollama:/root/.ollama   -p 11434:11434 ollama/ollama:0.12.0-rc0-rocm

```

```yaml
version: '3.8'

services:
  ollama:
    image: ollama/ollama:rocm
    container_name: ollama
    restart: unless-stopped
    # ROCm GPU access for AMD GPUs
    devices:
      - /dev/kfd:/dev/kfd    # AMD GPU kernel driver
      - /dev/dri:/dev/dri    # Direct Rendering Infrastructure
    # Expose Ollama API port
    ports:
      - "11434:11434"
    # Persistent storage for models
    volumes:
      - ollama:/root/.ollama
    # Security options for ROCm GPU access
    security_opt:
      - seccomp=unconfined
      - apparmor=unconfined
    # Add video group for GPU access
    group_add:
      - video
    environment:
      # === ROCm GPU Configuration ===
      # Override GPU version for compatibility
      - HSA_OVERRIDE_GFX_VERSION=11.0.0
      # Use only the first GPU (adjust as needed)
      - HIP_VISIBLE_DEVICES=0
      # === Server Configuration ===
      # Listen on all interfaces (allows external connections)
      - OLLAMA_HOST=0.0.0.0:11434
      # Allow connections from any origin (adjust for security)
      - OLLAMA_ORIGINS=*
      # Enable debug logging (set to 1 for troubleshooting)
      - OLLAMA_DEBUG=0
      # === Model Management ===
      # Keep models loaded for 1 hour (prevents GPU hangs)
      - OLLAMA_KEEP_ALIVE=1h
      # Allow up to 2 models loaded simultaneously
      - OLLAMA_MAX_LOADED_MODELS=2
      # Allow 5 minutes for model loading
      - OLLAMA_LOAD_TIMEOUT=5m
      # Don't automatically prune unused model files
      - OLLAMA_NOPRUNE=false
      # === Performance Settings ===
      # Handle 2 parallel requests (conservative for stability)
      - OLLAMA_NUM_PARALLEL=2
      # Queue up to 100 requests
      - OLLAMA_MAX_QUEUE=100
      # === GPU Optimization ===
      # Spread models across GPUs if multiple available
      - OLLAMA_SCHED_SPREAD=false
      # Enable flash attention for memory efficiency
      - OLLAMA_FLASH_ATTENTION=true
      # Reserve 512MB VRAM per GPU (adjust based on your GPU memory)
      - OLLAMA_GPU_OVERHEAD=536870912
      # Use 16-bit float for K/V cache (good balance of speed/memory)
      - OLLAMA_KV_CACHE_TYPE=f16
      # === Optional Advanced Settings ===
      # Uncomment to force specific LLM library
      # - OLLAMA_LLM_LIBRARY=rocm
      # Uncomment to use custom models directory
      # - OLLAMA_MODELS=/custom/models/path
    # Optional: Resource limits to prevent system overload
    # deploy:
    #   resources:
    #     limits:
    #       memory: 16G
    #     reservations:
    #       memory: 8G
# Named volume for persistent model storage
volumes:
  ollama:
    driver: local
# Optional: Custom network for isolation
# networks:
#   ollama-network:
#     driver: bridge

```

## podman command line

```bash
alias drun='sudo podman run -it --network=host --device=/dev/kfd --device=/dev/dri --group-add=video --ipc=host --cap-add=SYS_PTRACE --security-opt seccomp=unconfined --shm-size 8G -v $HOME/podmanx:/podmanx -w /podmanx'
```

```bash
# Start without shm-size
podman-compose up -d

# Monitor memory usage
podman stats ollama

# Check if there are any shared memory errors in logs
podman-compose logs ollama | grep -i "shm\|memory"

```

## VLLM runs

```bash
codellama/CodeLlama-13b-Instruct-hf

--enforce-eager --gpu-memory-utilization 0.95  --cpu-offload-gb 8

vllm serve TheBloke/Phind-CodeLlama-34B-v2-GPTQ \
     --host 0.0.0.0 \
     --port 8000 \
     --download-dir /home/dfischer/vllm-models \
     --dtype float16 \
     --max-model-len 16384 \
     --max-num-batched-tokens 4096 \
     --quantization gptq \
     --enforce-eager

vllm serve Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4 \
     --host 0.0.0.0 \
     --port 8000 \
     --download-dir /home/dfischer/vllm-models \
     --quantization gptq \
     --dtype float16 \
     --max-model-len 32768 \
     --max-num-batched-tokens 4096
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct-GPTQ-Int8 \
     --host 0.0.0.0 \
     --port 8000 \
     --download-dir /home/dfischer/vllm-models \
     --quantization gptq \
     --dtype float16 \
     --max-model-len 32768 \
     --max-num-batched-tokens 8192

vllm serve TheBloke/CodeLlama-13B-Instruct-GPTQ \
     --host 0.0.0.0 \
     --port 8000 \
     --download-dir /home/dfischer/vllm-models \
     --dtype float16 \
     --max-model-len 16384 \
     --max-num-batched-tokens 4096 \
     --quantization gptq

export VLLM_USE_TRITON_FLASH_ATTN=0 ;vllm serve Qwen/Qwen2.5-Coder-7B-Instruct-GPTQ-Int8 \
--host 0.0.0.0 \
--port 8000 \
--download-dir /home/dfischer/vllm-models \
--quantization gptq \
--dtype float16 \
--max-model-len 32768 \
--max-num-batched-tokens 8192

vllm serve Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4 \
--host 0.0.0.0 \
--port 8000 \
--download-dir /home/dfischer/vllm-models \
--quantization gptq \
--dtype float16 \
--max-model-len 32768 \
--max-num-batched-tokens 4096

export VLLM_USE_TRITON_FLASH_ATTN=0; vllm serve Qwen/Qwen3-30B-A3B-GPTQ-Int4 \
--host 0.0.0.0 \
--port 8000 \
--download-dir /home/dfischer/vllm-models \
--quantization gptq \
--dtype float16 \
--max-model-len 32768 \
--max-num-batched-tokens 4096


```
# llama.cpp command lines
```bash

### Codeing type llm
llama-server --alias "locmod-code" --host 192.168.100.10 --port 10000 -hf lmstudio-community/Codestral-22B-v0.1-GGUF:Q5_K_M \
    -ngl 99 --ctx-size 16486 --parallel 1  -fa on --seed 42 --alias "local-model-autoc" --jinja 

llama-server --alias "locmod-codes" --host 192.168.100.10 --port 10000  -hf lmstudio-community/Codestral-22B-v0.1-GGUF:Q5_K_M \
    -ngl 99 --parallel 1 -fa on --seed 42 --temp 0.4 --top-p 0.85 --top-k 40 --min-p 0.1 --repeat-penalty 1.1 \
    --jinja --no-mmap  --mlock --no-webui --ctx-size 32768

llama-server  --alias "locmod-qwen-code" --host 192.168.100.10 --port 10000 -hf unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q5_K_M \
    -ngl 99  --parallel 1 -fa on --fit on \
    --seed 42 --temp 0.7 --top-p 0.9 --top-k 20 --min-p 0.05 --repeat-penalty 1.1 \
    --jinja --no-mmap  --mlock --no-webui --ctx-size 32768

llama-server --alias "locmod-qwen-code" --host 192.168.100.10 --port 10000 -hf unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q5_K_M \
    -ngl 99 -fa on --parallel 1 --fit on \
    --seed 42  --temp 0.7 --top-p 1.0 --top-k 20 --min-p 0.1 --repeat-penalty 1.1 \
    --mlock --no-mmap --jinja --no-webui --ctx-size 32768 -b 2048
    
## temp ex.     --temp 0.7 --top-p 0.9 --top-k 20 --min-p 0.05 --repeat-penalty 1.1 
# more concise  --temp 0.4 --top-p 0.85 --top-k 40 --min-p 0.1 --repeat-penalty 1.1
#
llama-server  --alias "unsloth/GLM-4.7-Flash-NT"  --host 192.168.100.10 --port 10001 -hf unsloth/GLM-4.7-Flash-GGUF:Q8_0 \
    --fit on --temp 1.0 --top-p 0.95 --min-p 0.01 --kv-unified  --cache-type-k q8_0 --cache-type-v q8_0  -fa on  \
    --batch-size 4096 --ubatch-size 1024 --ctx-size 32768 -ngl 99 --parallel 1 --seed 42 \
    --jinja  --no-webui --chat-template-kwargs "{"enable_thinking": false}"




#### Thinking/Images
llama-server --alias "locmod-think-image" --host 192.168.100.10 --port 10001 -hf unsloth/Qwen3-VL-32B-Thinking-GGUF:Q4_K_M \
    -ngl 99 --parallel 1 -fa on --seed 42  \
    --temp 1.00 --top-p 0.95 --top-k 20 --min-p 0.05 --repeat-penalty 1.0 \
    --fit on --mlock --no-mmap --jinja --no-webui --ctx-size 16386
 
llama-server --alias "unsloth/Mistral-Small-3.2-24B-Instruct-2506" --host 192.168.100.10 --port 10001 -hf unsloth/Mistral-Small-3.2-24B-Instruct-2506-GGUF:UD-Q4_K_XL  -ngl 99 --parallel 1 -fa on --seed 42 --temp 0.4 --top-p 0.95 --top-k 20 --min-p 0.05 --repeat-penalty 1.0 --fit on --mlock --no-mmap --jinja --ctx-size 32768 -b 4096

    
### Thinking
llama-server --alias "unsloth/gpt-oss-20b" --host 192.168.100.10 --port 10001 -hf unsloth/gpt-oss-20b-GGUF:Q5_K_M \
    -ngl 999  -b 1024 --threads 12 --threads-batch 24 --parallel 1 -fa on \
    --seed 42  --temp 0.85 --top-p 0.9 --top-k 20 --min-p 0.05 --repeat-penalty 1.1 \
    --jinja --no-mmap --mlock --ctx-size 32768

llama-server  --alias "unsloth/GLM-4.7-Flash"  --host 192.168.100.10 --port 10001 -hf unsloth/GLM-4.7-Flash-GGUF:Q8_0 \
    --fit on --temp 1.0 --top-p 0.95 --min-p 0.01 --kv-unified  --cache-type-k q8_0 --cache-type-v q8_0  -fa on  \
    --batch-size 4096 --ubatch-size 1024 --ctx-size 32768 -ngl 99 --parallel 1 --seed 42 \
    --jinja  --no-webui
```
