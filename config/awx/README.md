# AWX Docker and Execution Environment Configuration

This directory contains the configuration files for building custom AWX execution environments (EEs) and Docker images for air-gapped installations.

## Directory Structure

```text
config/awx/
├── execution-environment.yml    # Main EE definition file
├── Dockerfile                   # Docker build instructions
├── build/                      # Build context directory
│   ├── requirements.yml        # Ansible collections and roles
│   ├── requirements.txt        # Python package dependencies
│   ├── bindep.txt             # System package dependencies
│   └── configs/               # Configuration files
│       ├── ansible.cfg        # Ansible configuration
│       └── pip.conf           # Python package configuration
└── README.md                  # This file
```

## Docker Configuration

The `Dockerfile` defines how to build the base Docker image for AWX. Key components:

- **Base Image**: Uses `quay.io/ansible/awx-ee:latest` as the foundation
- **Build Stages**:
  - `base`: Initial setup with system packages
  - `galaxy`: Ansible collections and roles installation
  - `builder`: Python package installation
  - `final`: Final image assembly

### Building Docker Image

1. Build the Docker image:

   ```bash
   cd config/awx
   docker build -t your-registry/awx-base:latest .
   ```

2. Push to your registry:

   ```bash
   docker push your-registry/awx-base:latest
   ```

## Execution Environment Configuration

The `execution-environment.yml` file defines how to build the custom AWX execution environment. Key components:

- **Base Images**:
  - Base: `quay.io/ansible/awx-ee:latest`
  - Builder: `quay.io/ansible/ansible-runner:latest`

- **Dependencies**:
  - Ansible collections and roles (requirements.yml)
  - Python packages (requirements.txt)
  - System packages (bindep.txt)

- **Build Options**:
  - Uses DNF package manager
  - Installs Git and Git LFS
  - Sets up proper working directory and permissions
  - Configures container initialization

### Building Execution Environment

1. Install ansible-builder:

   ```bash
   pip install ansible-builder
   ```

2. Build the execution environment:

   ```bash
   cd config/awx
   ansible-builder build -t your-registry/awx-ee:latest
   ```

3. Push to your registry:

   ```bash
   docker push your-registry/awx-ee:latest
   ```

## Adding to AWX

1. Log into AWX web interface
2. Navigate to Administration > Execution Environments
3. Click "Add"
4. Fill in the details:
   - Name: Your EE name
   - Image: your-registry/awx-ee:latest
   - Pull: Always pull container before running
   - Registry credentials: If using private registry

## Customization

### Adding Collections

Edit `build/requirements.yml`:

```yaml
collections:
  - name: community.general
    version: ">=7.0.0"
  - name: kubernetes.core
    version: ">=2.0.0"
```

### Adding Python Packages

Edit `build/requirements.txt`:

```txt
kubernetes>=28.0.0
requests>=2.31.0
```

### Adding System Dependencies

Edit `build/bindep.txt`:

```txt
git [platform:rpm]
gcc [platform:rpm]
python3-devel [platform:rpm]
```

## Docker Commands Reference

Common Docker commands for managing AWX images:

```bash
# List images
docker images | grep awx

# Remove image
docker rmi your-registry/awx-ee:latest

# View image history
docker history your-registry/awx-ee:latest

# Run container for testing
docker run -it --rm your-registry/awx-ee:latest /bin/bash

# Save image to tar file
docker save your-registry/awx-ee:latest > awx-ee.tar

# Load image from tar file
docker load < awx-ee.tar
```

## Notes

- The execution environment is based on the official AWX EE image
- Python 3.9 is used as the base Python version
- Ansible core version matches the AWX version
- Includes common SDKs for cloud providers (AWS, Azure, GCP)
- Supports Git LFS for large file handling

## Troubleshooting

1. Build failures:
   - Check network connectivity to registries
   - Verify registry credentials
   - Check for conflicting package versions
   - Ensure Docker daemon is running
   - Check available disk space

2. Runtime issues:
   - Verify EE is properly registered in AWX
   - Check container logs
   - Verify required credentials are configured
   - Check container resource limits
   - Verify network connectivity

## References

- [AWX Documentation](https://docs.ansible.com/automation-controller/latest/html/userguide/execution_environments.html)
- [Ansible Builder Documentation](https://ansible-builder.readthedocs.io/)
- [Docker Documentation](https://docs.docker.com/)
- [Container Registry Documentation](https://docs.ansible.com/automation-controller/latest/html/administration/container_registry.html)
