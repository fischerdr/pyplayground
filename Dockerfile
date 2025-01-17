# Use Fedora as base image
FROM fedora:latest

# Add HashiCorp and Kubernetes repositories
RUN dnf install -y dnf-plugins-core && \
    dnf config-manager --add-repo https://rpm.releases.hashicorp.com/fedora/hashicorp.repo && \
    cat <<EOF | tee /etc/yum.repos.d/kubernetes.repo
[kubernetes]
name=Kubernetes
baseurl=https://packages.cloud.google.com/yum/repos/kubernetes-el7-\$basearch
enabled=1
gpgcheck=1
gpgkey=https://packages.cloud.google.com/yum/doc/yum-key.gpg https://packages.cloud.google.com/yum/doc/rpm-package-key.gpg
EOF

# Install system packages, Python 3.9, and development tools
RUN dnf update -y && \
    dnf install -y \
    python3.9 \
    python3.9-devel \
    python3-pip \
    gcc \
    git \
    curl \
    wget \
    vault-agent \
    kubectl \
    && dnf clean all \
    && rm -rf /var/cache/dnf/*

# Install Helm
RUN curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Create a symbolic link for python3.9
RUN ln -sf /usr/bin/python3.9 /usr/bin/python

# Set the working directory in the container
WORKDIR /app

# Create required directories
RUN mkdir -p /app/logs /app/config /app/utils /app/tests /app/docs

# Copy requirements files
COPY requirements*.txt ./

# Install dependencies
RUN python -m pip install --no-cache-dir -r requirements.txt && \
    if [ -f requirements-dev.txt ]; then \
        python -m pip install --no-cache-dir -r requirements-dev.txt; \
    fi

# Copy the application code
COPY . .

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Create volume mount points for logs and config
VOLUME ["/app/logs", "/app/config"]

# Default command (can be overridden)
CMD ["python", "-m", "pytest"]
