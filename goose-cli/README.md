# AI Development Environment (Ollama + Goose)

This project provides a containerized development environment for **Python AI workflows**.
It includes:

* **Ollama** – local model server exposing an OpenAI-compatible API
* **Goose** – interactive AI CLI that connects to Ollama
* **Python development stack** – preinstalled libraries and tools

The environment is orchestrated with **Podman Compose**, ensuring Goose starts only once Ollama is online.

---

## Prerequisites (RHEL / Fedora / Corporate Workstation)

1. **Install Podman and Compose plugin**

   ```bash
   sudo dnf install -y podman podman-compose
   ```

   Verify installation:

   ```bash
   podman --version
   podman-compose version
   ```

2. **Enable user session service**

   Podman supports rootless containers. Ensure the systemd service is active for your user:

   ```bash
   systemctl --user enable --now podman.socket
   ```

3. **(Optional) Allow GPU passthrough**

   * For **NVIDIA**: Install `nvidia-container-toolkit`.
   * For **AMD ROCm**: Enable ROCm runtime.
     (These are optional; the base setup works on CPU.)

---

## Setup

1. Clone this repository:

   ```bash
   git clone https://github.com/your-org/ai-dev-env.git
   cd ai-dev-env
   ```

2. Build Goose image (includes `.gooserc` and Python libraries):

   ```bash
   podman-compose build
   ```

3. Start the stack:

   ```bash
   podman-compose up -d
   ```

---

## Usage

### Verify Ollama API

```bash
curl http://localhost:11434/api/tags
```

If healthy, Ollama responds with a list of available models.

### Pull a Model (inside Ollama container)

```bash
podman exec -it ollama ollama pull codellama:7b-instruct
```

You can substitute with any supported model.

### Run Goose CLI

Attach to Goose container:

```bash
podman exec -it goose bash
```

Then start Goose:

```bash
goose
```

Goose connects to Ollama via `http://ollama:11434/v1`.

---

## Development Workflow

* Place your Python code in the `workspace/` directory (mounted into the Goose container).
* Use Goose interactively for AI-assisted coding.
* Use Ollama’s REST API for programmatic inference.

Example Python snippet (from host or Goose):

```python
import requests

resp = requests.post(
    "http://localhost:11434/v1/completions",
    json={"model": "codellama:7b-instruct", "prompt": "Write a Python hello world"}
)
print(resp.json())
```

---

## Stopping / Restarting

```bash
podman-compose down
podman-compose up -d
```

Persistent data (Ollama models) is stored in the `ollama_models` volume.

---

## Notes for RHEL / Fedora Corporate Systems

* **SELinux**: If you encounter permission issues on volumes, append `:Z` to volume mounts in `podman-compose.yml`. Example:

  ```yaml
  volumes:
    - ollama_models:/root/.ollama:Z
  ```

* **Rootless Podman**: This environment is designed to run rootless. If corporate security policy requires rootful Podman, adjust accordingly.

* **Systemd Integration**: For long-running deployments, you can generate systemd units:

  ```bash
  podman generate systemd --new --files --name ai-dev-env
  ```

---

## Roadmap

* Preload models at startup for faster Goose initialization.
* Expand development stack with testing and benchmarking tools.
* Integrate with corporate CI/CD pipelines for reproducible AI-assisted workflows.
