# Different docker runs

```bash
docker run -ti --name local-ai \
 -p 8080:8080 \
 --group-add video \
 --security-opt seccomp=unconfined \
 --security-opt apparmor=unconfined \
 --device /dev/kfd \
 --device /dev/dri \
 --ipc=host \
 --shm-size 16G \
 --net host \
 -v ${PWD}/models:/models \
 -v /opt/rocm/:/opt/rocm/ \
 -e HSA_OVERRIDE_GFX_VERSION=11.0.0 \
 -e DEBUG=true \
 -e REBUILD=true \
 -e BUILD_TYPE=hipblas \
 -e GPU_TARGETS=gfx1151 \
 quay.io/go-skynet/local-ai:master-aio-gpu-hipblas
```

```bash
docker run -ti --name local-ai \
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
docker run -d -p 3000:8080 \
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
docker run -d -p 3000:8080 \
 --group-add video \
 --security-opt seccomp=unconfined \
 --security-opt apparmor=unconfined \
    -e OLLAMA_BASE_URL=https://flyyn.modmtrx.net:11434 \
    -v open-webui:/app/backend/data \
    --name open-webui \
    --restart always \
    ghcr.io/open-webui/open-webui:main

docker run -d -p 3000:8080 \
    -v open-webui:/app/backend/data \
    -e OLLAMA_BASE_URL=http://flyyn.modmtrx.net:11434 \
    --name open-webui \
    --restart always \
    ghcr.io/open-webui/open-webui:main
```

```bash
docker run -d \
  --name ollama-rocm \
  --device=/dev/kfd \
  --device=/dev/dri \
  --group-add video \
  -e HSA_OVERRIDE_GFX_VERSION=11.0.0 \
  -e HIP_VISIBLE_DEVICES=0 \
  -e OLLAMA_FLASH_ATTENTION=true \
  -v ollama:/root/.ollama \
  -p 11434:11434 \
  ollama/ollama:0.11.4-rocm
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

## docker command line

```bash
alias drun='sudo docker run -it --network=host --device=/dev/kfd --device=/dev/dri --group-add=video --ipc=host --cap-add=SYS_PTRACE --security-opt seccomp=unconfined --shm-size 8G -v $HOME/dockerx:/dockerx -w /dockerx'
```

```bash
# Start without shm-size
docker-compose up -d

# Monitor memory usage
docker stats ollama

# Check if there are any shared memory errors in logs
docker-compose logs ollama | grep -i "shm\|memory"

```
