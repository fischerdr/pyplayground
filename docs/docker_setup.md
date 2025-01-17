# Docker Setup and Configuration

This document describes the Docker configuration for the Python playground project.

## Base Image

The project uses Fedora as its base image to maintain consistency with the development environment. We chose Fedora because:
- It matches our build system OS
- Provides up-to-date system packages
- Has good support for Python development

Alternative base images that are supported:
- CentOS 8
- Alpine Linux

## System Packages

The container includes the following system packages:

### Development Tools
- Python 3.9 and development tools
- gcc for compiling Python packages with C extensions
- git for version control

### Utilities
- curl for making HTTP requests
- wget for downloading files

### HashiCorp Tools
- vault-agent for Vault integration and secrets management
- HashiCorp repository configured for updates

### Kubernetes Tools
- kubectl for managing Kubernetes clusters
- Helm 3 for Kubernetes package management
- Kubernetes repository configured for updates

## Package Repositories

The container is configured with the following package repositories:
1. Fedora default repositories
2. HashiCorp repository for Vault tools
3. Kubernetes repository for kubectl

## Using Kubernetes Tools

### kubectl
```bash
# Set your kubeconfig
export KUBECONFIG=/path/to/your/kubeconfig

# Test connection
kubectl cluster-info

# View nodes
kubectl get nodes
```

### Helm
```bash
# Add a repository
helm repo add stable https://charts.helm.sh/stable

# Update repositories
helm repo update

# Search for charts
helm search repo stable/

# Install a chart
helm install my-release stable/chart-name
```

## Tool Usage Examples

### Kubernetes Tools (kubectl and Helm)

#### kubectl Configuration
```bash
# Copy your kubeconfig into the container
docker cp ~/.kube/config pyplayground:/root/.kube/config

# Or mount it as a volume
docker run -v ~/.kube/config:/root/.kube/config pyplayground

# Test connection and get cluster info
kubectl cluster-info
kubectl get nodes -o wide
kubectl get pods -A

# Common kubectl commands
# List all pods in a namespace
kubectl get pods -n your-namespace

# Get pod logs
kubectl logs -f pod-name -n your-namespace

# Execute command in pod
kubectl exec -it pod-name -n your-namespace -- /bin/bash

# Apply manifests
kubectl apply -f manifest.yaml

# Port forwarding
kubectl port-forward svc/service-name 8080:80 -n your-namespace
```

#### Helm Usage
```bash
# Repository Management
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# Search for charts
helm search repo bitnami/
helm search repo bitnami/postgresql --versions

# Install a chart
helm install my-postgres bitnami/postgresql \
  --namespace database \
  --create-namespace \
  --set postgresqlPassword=secretpassword \
  --set persistence.size=10Gi

# List installations
helm list -A

# Upgrade a release
helm upgrade my-postgres bitnami/postgresql \
  --namespace database \
  --set postgresqlPassword=newsecretpassword

# Rollback a release
helm rollback my-postgres 1 -n database

# Uninstall a release
helm uninstall my-postgres -n database
```

### Vault Tools

#### Vault Agent Configuration
```bash
# Create a basic Vault Agent config
cat <<EOF > vault-agent-config.hcl
exit_after_auth = false
pid_file = "/tmp/vault-agent.pid"

auto_auth {
    method "kubernetes" {
        mount_path = "auth/kubernetes"
        config = {
            role = "my-role"
        }
    }
}

template {
    source      = "/etc/vault/templates/secret.tmpl"
    destination = "/etc/secrets/config.json"
}
EOF

# Run Vault Agent
vault agent -config=vault-agent-config.hcl

# Check Vault status
vault status

# Login with token
vault login $VAULT_TOKEN

# Read secrets
vault kv get secret/my-secret
```

### Git Operations

```bash
# Configure Git
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"

# Clone repository
git clone https://github.com/username/repo.git

# Branch operations
git checkout -b feature/new-feature
git branch -a
git branch -d old-branch

# Commit changes
git add .
git commit -m "feat: add new feature"
git push origin feature/new-feature

# Rebase and merge
git fetch origin
git rebase origin/main
git merge feature/branch
```

### Network Utilities

#### curl Examples
```bash
# Basic GET request
curl https://api.example.com/endpoint

# POST request with JSON
curl -X POST https://api.example.com/endpoint \
  -H "Content-Type: application/json" \
  -d '{"key": "value"}'

# Download file
curl -O https://example.com/file.zip

# Follow redirects and show progress
curl -L -# https://example.com/download

# With authentication
curl -u username:password https://api.example.com
```

#### wget Examples
```bash
# Download file
wget https://example.com/file.tar.gz

# Download recursively
wget -r -np -k https://example.com/docs/

# Download with authentication
wget --user=username --password=password https://example.com/secure/file

# Resume interrupted download
wget -c https://example.com/large-file.zip

# Download to specific directory
wget -P /download/path https://example.com/file
```

### Container Volume Management

```bash
# Mount multiple volumes
docker run -it \
  -v ~/.kube:/root/.kube \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/logs:/app/logs \
  pyplayground

# Check volume mounts
docker inspect pyplayground | grep Mounts -A 20

# Backup volume data
docker run --rm \
  -v pyplayground_logs:/source \
  -v $(pwd)/backup:/backup \
  alpine tar czf /backup/logs.tar.gz -C /source .
```

### Development Workflow

```bash
# Build with development tools
docker build -t pyplayground:dev \
  --build-arg INSTALL_DEV_TOOLS=true .

# Run with source code mounted
docker run -it \
  -v $(pwd):/app \
  -v ~/.kube:/root/.kube \
  -p 8080:8080 \
  pyplayground:dev

# Run tests
docker run pyplayground:dev python -m pytest tests/

# Run specific test file
docker run pyplayground:dev python -m pytest tests/test_vault.py -v

# Run with debugger
docker run -it \
  -p 5678:5678 \
  pyplayground:dev python -m debugpy --listen 0.0.0.0:5678 your_script.py
```

## Python Environment

The Dockerfile sets up Python 3.9 (our minimum required version) with the following configuration:
- Python 3.9 and development tools installation
- pip for package management
- gcc for compiling Python packages with C extensions

## Project Structure

The Docker container maintains the following directory structure:

```
/app/
├── config/         # Configuration files
├── docs/          # Documentation
├── logs/          # Log files
├── tests/         # Test files
└── utils/         # Utility functions
```

### Volume Mounts

Two directories are configured as Docker volumes:
- `/app/logs`: For persistent storage of log files
- `/app/config`: For persistent configuration files

This ensures that logs and configuration data persist between container restarts.

## Dependencies

The container installs dependencies from two files:
1. `requirements.txt`: Core dependencies
2. `requirements-dev.txt`: Development dependencies (if present)

## Environment Variables

Default environment variables set in the container:
- `PYTHONPATH=/app`: Ensures Python can find our modules
- `PYTHONUNBUFFERED=1`: Prevents Python from buffering stdout/stderr

## Building the Container

To build the container:

```bash
docker build -t pyplayground .
```

## Running the Container

### Basic Run
```bash
docker run -it pyplayground
```

### With Volume Mounts
```bash
docker run -it \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/config:/app/config \
  pyplayground
```

### For Development
```bash
docker run -it \
  -v $(pwd):/app \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/config:/app/config \
  pyplayground bash
```

## Testing

The default command runs pytest:
```bash
docker run pyplayground
```

To run specific tests:
```bash
docker run pyplayground python -m pytest tests/specific_test.py
```

## Best Practices

1. **Image Size Optimization**:
   - Uses `--no-cache-dir` with pip
   - Cleans dnf cache after package installation
   - Combines RUN commands to reduce layers

2. **Security**:
   - Uses official Fedora base image
   - Keeps packages updated
   - Doesn't run as root (TODO: implement user creation)

3. **Persistence**:
   - Uses volumes for logs and configuration
   - Allows for easy backup and monitoring

## Troubleshooting

Common issues and solutions:

1. **Permission Issues**:
   ```bash
   # Fix permissions on log directory
   chmod 777 logs
   ```

2. **Python Path Issues**:
   ```bash
   # Run with explicit PYTHONPATH
   docker run -e PYTHONPATH=/app pyplayground
   ```

## Future Improvements

1. Add multi-stage building to reduce final image size
2. Implement non-root user for better security
3. Add health checks
4. Configure container logging
5. Add Docker Compose configuration for development

## References

- [Fedora Docker Image](https://hub.docker.com/_/fedora)
- [Python Docker Best Practices](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/)
- [Docker Volumes](https://docs.docker.com/storage/volumes/)
