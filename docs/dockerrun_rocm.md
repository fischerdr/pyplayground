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
	-e HSA_OVERRIDE_GFX_VERSION=11.0.0 \
	-e DEBUG=true \
	-e REBUILD=true \
	-e BUILD_TYPE=hipblas \
	-e GPU_TARGETS=gfx906 \
	quay.io/go-skynet/local-ai:master-aio-gpu-hipblas
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
    --name open-webui \
    --restart always \
    ghcr.io/open-webui/open-webui:ollama
```

```bash
docker run -d \
  --name ollama-rocm \
  --device=/dev/kfd \
  --device=/dev/dri \
  --group-add video \
  -e HSA_OVERRIDE_GFX_VERSION=10.3.0 \
  -e HIP_VISIBLE_DEVICES=0 \
  -v ollama:/root/.ollama \
  -p 11434:11434 \
  ollama/ollama:0.10.0-rc0-rocm
 ```
 
 ```yaml
 version: '3.9'

services:
  ollama:
    image: ollama/ollama:0.10.0-rc0-rocm
    container_name: ollama-rocm
    ports:
      - "11434:11434"
    devices:
      - /dev/kfd
      - /dev/dri
    group_add:
      - "video"
    volumes:
      - ollama:/root/.ollama
    environment:
      - HSA_OVERRIDE_GFX_VERSION=10.3.0
      - HIP_VISIBLE_DEVICES=0
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
              driver: radeon
              count: all

volumes:
  ollama:
```

## docker command line
```bash
alias drun='sudo docker run -it --network=host --device=/dev/kfd --device=/dev/dri --group-add=video --ipc=host --cap-add=SYS_PTRACE --security-opt seccomp=unconfined --shm-size 8G -v $HOME/dockerx:/dockerx -w /dockerx'
```