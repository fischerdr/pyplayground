FROM registry.access.redhat.com/ubi8/ubi:8.9

# System packages for dev
RUN microdnf install -y \
    git curl tar gzip make gcc gcc-c++ python311 python311-devel \
    postgresql-devel sqlite sqlite-devel \
    libffi-devel openssl-devel \
    # Ansible development system packages
    openssh-clients openssh-server \
    net-tools iputils procps-ng util-linux \
    # Additional system utilities
    vim nano htop tree \
    && microdnf clean all

# Add non-root user
RUN useradd -m -s /bin/bash goose
USER goose
WORKDIR /workspace

# Python setup
RUN python3.11 -m ensurepip --upgrade && \
    pip3 install --upgrade pip setuptools wheel

# Core Python dev libraries
RUN pip install \
    black flake8 mypy pylint \
    pytest pytest-cov \
    ipython jupyterlab \
    requests pyyaml click rich \
    psycopg2-binary sqlalchemy \
    fastapi uvicorn \
    # Additional Python dev tools
    isort pre-commit pip-tools \
    bandit coverage \
    # Ansible development tools
    ansible-core ansible-runner ansible-builder \
    ansible-lint molecule ansible-navigator \
    # Project-specific dependencies
    hvac kubernetes awxkit boto3 \
    pyvmomi structlog tenacity

# Goose CLI install
RUN curl -fsSL https://raw.githubusercontent.com/goosecli/goose/main/install.sh | bash -s -- --prefix /usr/local

# Add a restricted .gooserc for corporate use
COPY .gooserc /home/goose/.gooserc
RUN chown goose:goose /home/goose/.gooserc

ENTRYPOINT ["goose"]
