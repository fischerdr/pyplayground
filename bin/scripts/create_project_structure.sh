#!/bin/bash

# Project Structure Creation Script
# This script creates a standardized Python project structure

# Function to display usage information
function show_usage() {
    echo "Usage: $0 <project_directory> <project_name>"
    echo "Example: $0 /path/to/projects my_project"
    exit 1
}

# Function to create directory with .gitkeep
function create_dir_with_gitkeep() {
    mkdir -p "$1"
    touch "$1/.gitkeep"
}

# Function to safely create a file
function safe_create_file() {
    local file="$1"
    local content_func="$2"
    
    if [ -f "$file" ]; then
        echo "File $file already exists. Skipping creation."
        echo "If you want to see the template content, check the script source."
    else
        echo "Creating $file"
        eval "$content_func"
    fi
}

# Check arguments
if [ $# -ne 2 ]; then
    show_usage
fi

PROJECT_DIR="$1"
PROJECT_NAME="$2"
BASE_DIR="$PROJECT_DIR/$PROJECT_NAME"

echo "Creating project structure in: $BASE_DIR"

# Create base directory
mkdir -p "$BASE_DIR"
cd "$BASE_DIR" || exit 1

# Create main directory structure
echo "Creating main directory structure..."
mkdir -p src/"$PROJECT_NAME"
create_dir_with_gitkeep "bin/scripts"
create_dir_with_gitkeep "bin/tools/k8s"
create_dir_with_gitkeep "bin/tools/hashicorp"
create_dir_with_gitkeep "bin/tools/vmware"
create_dir_with_gitkeep "bin/tools/openshift"
create_dir_with_gitkeep "templates/k8s"
create_dir_with_gitkeep "templates/scripts"
create_dir_with_gitkeep "templates/config"
create_dir_with_gitkeep "templates/docs"
create_dir_with_gitkeep "utils"
create_dir_with_gitkeep "tests"
create_dir_with_gitkeep "docs"
create_dir_with_gitkeep "logs"
create_dir_with_gitkeep "config"
mkdir -p .venv

# Create initial Python files
echo "Creating initial Python files..."
touch src/"$PROJECT_NAME"/__init__.py
touch utils/__init__.py

# Create basic configuration files
echo "Creating configuration files..."

# Create pyproject.toml
safe_create_file "pyproject.toml" 'cat > pyproject.toml << EOL
[build-system]
requires = ["setuptools>=45", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "$PROJECT_NAME"
version = "0.1.0"
description = "Add your project description here"
requires-python = ">=3.9,<3.15"

[tool.black]
line-length = 100
target-version = ["py39"]

[tool.isort]
profile = "black"
line_length = 100
EOL'

# Create requirements files
safe_create_file "requirements.txt" 'cat > requirements.txt << EOL
click>=8.0.0
typer>=0.9.0
EOL'

safe_create_file "requirements-dev.txt" 'cat > requirements-dev.txt << EOL
black
isort
flake8
pytest
mypy
click>=8.0.0
typer>=0.9.0
EOL'

# Create logging configuration
safe_create_file "config/logging.conf" 'cat > config/logging.conf << EOL
[loggers]
keys=root

[handlers]
keys=consoleHandler,fileHandler

[formatters]
keys=defaultFormatter

[logger_root]
level=INFO
handlers=consoleHandler,fileHandler
qualname=root
propagate=0

[handler_consoleHandler]
class=StreamHandler
level=INFO
formatter=defaultFormatter
args=(sys.stdout,)

[handler_fileHandler]
class=handlers.RotatingFileHandler
level=INFO
formatter=defaultFormatter
args=("logs/app.log", "a", 1000000, 5)

[formatter_defaultFormatter]
format=%(asctime)s - %(name)s - %(levelname)s - %(message)s
datefmt=%Y-%m-%d %H:%M:%S
EOL'

# Create a basic Python CLI template
safe_create_file "src/$PROJECT_NAME/cli.py" 'cat > src/"$PROJECT_NAME"/cli.py << EOL
#!/usr/bin/env python3
"""Command line interface for $PROJECT_NAME."""

import logging
import logging.config
import os
from pathlib import Path
from typing import Optional

import click
import typer

# Setup logging
logging.config.fileConfig(
    Path(__file__).parent.parent.parent / "config" / "logging.conf",
    disable_existing_loggers=False
)
logger = logging.getLogger(__name__)

app = typer.Typer(help="$PROJECT_NAME CLI tool")

@app.command()
def hello(name: Optional[str] = None) -> None:
    """Say hello to the user."""
    logger.info("Hello command called")
    if name:
        typer.echo(f"Hello {name}!")
    else:
        typer.echo("Hello World!")

if __name__ == "__main__":
    logger.info("Starting CLI application")
    app()
EOL'

# Create .gitignore
safe_create_file ".gitignore" 'cat > .gitignore << EOL
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
share/python-wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# Virtual Environment
.venv/
venv/
ENV/
env/
.env

# Testing and Coverage
htmlcov/
.tox/
.nox/
.coverage
.coverage.*
.cache
nosetests.xml
coverage.xml
*.cover
*.py,cover
.hypothesis/
.pytest_cache/
cover/

# Type Checking
.mypy_cache/
.dmypy.json
dmypy.json
.pyre/
.pytype/

# IDE
.vscode/*
!.vscode/settings.json
!.vscode/tasks.json
!.vscode/launch.json
!.vscode/extensions.json
!.vscode/*.code-snippets
.idea/

# Logs and Databases
*.log
*.sqlite3
logs/
!logs/.gitkeep

# Binary and External Tools
bin/tools/*
!bin/tools/.gitkeep
bin/tools/k8s/*
bin/tools/hashicorp/*
bin/tools/vmware/*
bin/tools/openshift/*

# Keep script directories but ignore binaries
!bin/scripts/
bin/scripts/**/*.exe
bin/scripts/**/*.bin
bin/scripts/**/*.dll

# Templates
templates/**/*.generated.*
templates/**/*.rendered
templates/**/*.tmp
templates/**/*.temp
!templates/**/*.example
!templates/**/*.template
!templates/**/*.tpl
!templates/**/*.j2
!templates/**/*.yaml
!templates/**/*.yml
!templates/**/*.json
templates/**/_rendered/
templates/**/rendered/

# Build and Temp
*.manifest
*.spec
cython_debug/
__pypackages__/
.pdm.toml
.pdm-python
.pdm-build/

# Documentation Build
docs/_build/
/site

# Misc
*.retry
pip-selfcheck.json
EOL'

# Create README.md
safe_create_file "README.md" 'cat > README.md << EOL
# $PROJECT_NAME

## Overview
Add your project overview here.

## Project Structure
This project follows a standardized structure:

\`\`\`
project_root/
├── bin/           # Executables and scripts directory
│   ├── scripts/   # Shell scripts and custom executables
│   └── tools/     # External binaries and tools
├── src/           # Python source code
├── templates/     # Template files directory
├── utils/         # Shared utility functions
├── tests/         # Test directory
├── docs/          # Documentation
├── logs/          # Log files
├── config/        # Configuration files
└── .venv/         # Virtual environment
\`\`\`

## Setup
1. Create and activate virtual environment:
   \`\`\`bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/Mac
   # or
   .venv\\Scripts\\activate  # Windows
   \`\`\`

2. Install dependencies:
   \`\`\`bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt  # for development
   \`\`\`

## Development
- Use black for code formatting
- Use isort for import sorting
- Use flake8 for code linting
- Use pytest for testing
- Use mypy for type checking

## Documentation
See the [docs/](docs/) directory for detailed documentation.
EOL'

# Create initial documentation
safe_create_file "docs/project_setup.md" 'cat > docs/project_setup.md << EOL
# Project Setup Guide

## Prerequisites
- Python 3.9 or higher
- pip (Python package installer)
- virtualenv or venv

## Installation Steps
[Add installation steps here]

## Configuration
[Add configuration instructions here]

## Development Setup
[Add development setup instructions here]
EOL'

# Create example templates
echo "Creating example templates..."

# K8s template example
safe_create_file "templates/k8s/deployment.yaml.j2" 'cat > templates/k8s/deployment.yaml.j2 << EOL
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ app_name }}
  namespace: {{ namespace }}
  labels:
    app: {{ app_name }}
spec:
  replicas: {{ replicas | default(1) }}
  selector:
    matchLabels:
      app: {{ app_name }}
  template:
    metadata:
      labels:
        app: {{ app_name }}
    spec:
      containers:
      - name: {{ container_name | default(app_name) }}
        image: {{ image }}:{{ tag | default("latest") }}
        ports:
        - containerPort: {{ port | default(8080) }}
EOL'

# JSON config template
safe_create_file "templates/config/config.json.j2" 'cat > templates/config/config.json.j2 << EOL
{
  "application": "{{ app_name }}",
  "version": "{{ version | default("1.0.0") }}",
  "environment": "{{ env | default("development") }}",
  "logging": {
    "level": "{{ log_level | default("INFO") }}",
    "file": "{{ log_file | default("app.log") }}"
  },
  "database": {
    "host": "{{ db_host }}",
    "port": {{ db_port | default(5432) }},
    "name": "{{ db_name }}",
    "user": "{{ db_user }}"
  }
}
EOL'

# Environment template
safe_create_file "templates/config/env.j2" 'cat > templates/config/env.j2 << EOL
# Environment Configuration
# Generated from template

# Application
APP_NAME="{{ app_name }}"
APP_ENV="{{ env | default("development") }}"
APP_DEBUG="{{ debug | default("false") }}"

# Database
DB_HOST="{{ db_host }}"
DB_PORT="{{ db_port | default("5432") }}"
DB_NAME="{{ db_name }}"
DB_USER="{{ db_user }}"

# Kubernetes
K8S_NAMESPACE="{{ k8s_namespace | default("default") }}"
K8S_CONTEXT="{{ k8s_context }}"

# Vault
VAULT_ADDR="{{ vault_addr | default("http://localhost:8200") }}"
VAULT_TOKEN="{{ vault_token }}"
EOL'

# Add example values file
safe_create_file "templates/k8s/values.yaml" 'cat > templates/k8s/values.yaml << EOL
# Default values for application deployment
app_name: myapp
namespace: default
replicas: 1
container_name: myapp
image: myapp
tag: latest
port: 8080

# Database configuration
db_host: localhost
db_port: 5432
db_name: myapp
db_user: myapp

# Environment
env: development
log_level: INFO
debug: false

# Kubernetes
k8s_namespace: default
k8s_context: minikube

# Vault
vault_addr: http://localhost:8200
EOL'

echo "Project structure created successfully!"
echo "Next steps:"
echo "1. cd $BASE_DIR"
echo "2. git init"
echo "3. python -m venv .venv"
echo "4. source .venv/bin/activate  # Linux/Mac or .venv\\Scripts\\activate # Windows"
echo "5. pip install -r requirements-dev.txt"