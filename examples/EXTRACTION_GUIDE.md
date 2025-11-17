# PXSecretMigrate - Extraction and Setup Guide

## Quick Start

This bundle contains everything needed to create a standalone git repository for the Portworx Secret Migration tools.

### Location
**Bundle File**: `/development/git/pyplayground/tmp/pxsecretmigrate-standalone.tar.gz`
**Size**: 62KB

---

## Step 1: Extract the Bundle

```bash
# Create a new directory
mkdir ~/pxsecretmigrate
cd ~/pxsecretmigrate

# Extract the bundle
tar -xzf /development/git/pyplayground/tmp/pxsecretmigrate-standalone.tar.gz

# Verify extraction
ls -la
```

You should see:
```
.
├── .flake8                    # Linting configuration
├── .gitignore                 # Git ignore patterns
├── CLAUDE.md                  # AI context documentation
├── README.md                  # Main documentation
├── pyproject.toml             # Python project config
├── requirements.txt           # Python dependencies
├── logs/                      # Logs directory (with .gitkeep)
├── tmp/                       # Temp files directory (with .gitkeep)
└── pxsecretmigrate/          # Main package
    ├── __init__.py
    ├── k8s_px_pvc_data_exporter.py
    ├── k8s_px_pvc_vault_secret_checker.py
    ├── k8s_px_volume_details.py
    ├── px_vault_to_k8s_secret_migrator.py
    ├── verify_px_k8s_secret_migration.py
    ├── README.md              # Detailed script docs
    └── utils/                 # Utility modules (nested)
        ├── __init__.py
        ├── k8s_utils.py
        ├── vault_utils.py
        ├── px_api.py
        ├── migration_utils.py
        └── logging_utils.py
```

---

## Step 2: Initialize Git Repository

```bash
# Initialize git
git init

# Add all files
git add .

# Create initial commit
git commit -m "Initial commit: Portworx Secret Migration Tools

Extracted from pyplayground monorepo as standalone project.

Tools for migrating Portworx volume encryption keys from
HashiCorp Vault to Kubernetes Secrets.

Features:
- Export PVC data from Kubernetes clusters
- Validate Vault secret accessibility
- Migrate encryption keys to K8s Secrets
- Verify migration success
- Query detailed volume information

Includes comprehensive documentation and utilities."
```

---

## Step 3: Set Up Python Environment

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate  # On Linux/Mac
# OR
.venv\Scripts\activate     # On Windows

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt
```

---

## Step 4: Verify Installation

```bash
# Check Python syntax
python3 -m py_compile pxsecretmigrate/*.py pxsecretmigrate/utils/*.py

# Test script help (run as module)
python -m pxsecretmigrate.k8s_px_pvc_data_exporter --help

# Should display usage information
```

---

## Step 5: Create Remote Repository

### On GitHub:

1. Go to https://github.com/new
2. Repository name: `pxsecretmigrate`
3. Description: "Tools for migrating Portworx volume encryption keys from HashiCorp Vault to Kubernetes Secrets"
4. Choose public or private
5. Do NOT initialize with README (we already have one)
6. Click "Create repository"

### Connect to Remote:

```bash
# Add remote (replace with your URL)
git remote add origin git@github.com:YOUR_USERNAME/pxsecretmigrate.git

# Set main branch
git branch -M main

# Push to remote
git push -u origin main
```

---

## Step 6: Test the Tools

### Export PVC Data (requires cluster access):
```bash
python -m pxsecretmigrate.k8s_px_pvc_data_exporter \
  --kubeconfig ~/.kube/config \
  --output-file test-export
```

### Check Help for All Scripts:
```bash
for script in k8s_px_pvc_data_exporter k8s_px_pvc_vault_secret_checker k8s_px_volume_details px_vault_to_k8s_secret_migrator verify_px_k8s_secret_migration; do
  echo "=== $script ==="
  python -m pxsecretmigrate.$script --help
  echo
done
```

---

## What's Included

### Configuration Files
- **pyproject.toml**: Python project configuration (build system, dependencies, tools)
- **requirements.txt**: Pinned production dependencies (7 packages)
- **.flake8**: Linting rules and code style configuration
- **.gitignore**: Git ignore patterns for Python projects

### Documentation
- **README.md**: User-facing documentation with quick start guide
- **CLAUDE.md**: AI assistant context and development notes
- **pxsecretmigrate/README.md**: Detailed script documentation

### Source Code
- **pxsecretmigrate/**: Main package with 5 migration scripts
- **pxsecretmigrate/utils/**: Shared utility modules (k8s, vault, px_api, migration, logging)

### Key Features
1. Utils nested under pxsecretmigrate/ (matches your structure)
2. All imports use: `from pxsecretmigrate.utils.*`
3. Minimal dependency set (7 core packages including python-dotenv)
4. Standalone documentation
5. Proper Python package structure
6. Ready for pip installation with `pip install -e .`

---

## Dependencies

### Core Dependencies (Auto-installed from requirements.txt)
- `click` - CLI framework
- `hvac` - HashiCorp Vault client
- `kubernetes` - Kubernetes Python client
- `python-dotenv` - Environment variable management
- `pyyaml` - YAML parsing
- `requests` - HTTP library
- `rich` - Terminal formatting

### Optional Development Dependencies
Install with: `pip install -e ".[dev]"`
- `pytest` - Testing framework
- `black` - Code formatting
- `flake8` - Linting
- `mypy` - Type checking
- `isort` - Import sorting

---

## Running Scripts

Scripts MUST be run as Python modules due to the nested utils structure:

```bash
# Correct way
python -m pxsecretmigrate.k8s_px_pvc_data_exporter --help

# This works after installing with pip install -e .
python pxsecretmigrate/k8s_px_pvc_data_exporter.py --help
```

---

## Directory Structure After Setup

```
pxsecretmigrate/
├── .git/                      # Git repository (after git init)
├── .venv/                     # Virtual environment (after setup)
├── .flake8                    # Linting config
├── .gitignore                 # Git ignore
├── CLAUDE.md                  # AI context
├── README.md                  # Main docs
├── pyproject.toml             # Project config
├── requirements.txt           # Dependencies
├── logs/                      # Log files (created at runtime)
│   └── .gitkeep
├── tmp/                       # Temp files (created at runtime)
│   └── .gitkeep
└── pxsecretmigrate/          # Main package
    ├── __init__.py
    ├── README.md
    ├── *.py (5 scripts)
    └── utils/                 # Nested utilities
        ├── __init__.py
        └── *.py (5 modules)
```

---

## Usage Examples

### Complete Migration Workflow

```bash
# 1. Export current state
python -m pxsecretmigrate.k8s_px_pvc_data_exporter \
  --output-file production-cluster

# 2. Check Vault secrets
python -m pxsecretmigrate.k8s_px_pvc_vault_secret_checker

# 3. Test migration (dry-run)
python -m pxsecretmigrate.px_vault_to_k8s_secret_migrator \
  --input tmp/production-cluster_*.json \
  --dry-run

# 4. Perform migration
python -m pxsecretmigrate.px_vault_to_k8s_secret_migrator \
  --input tmp/production-cluster_*.json

# 5. Verify migration
python -m pxsecretmigrate.verify_px_k8s_secret_migration \
  --input tmp/production-cluster_*.json
```

---

## Troubleshooting

### Import Errors
If you see `ModuleNotFoundError: No module named 'pxsecretmigrate'`:
```bash
# Make sure you're running as a module
python -m pxsecretmigrate.k8s_px_pvc_data_exporter --help

# OR install in editable mode
pip install -e .
```

### Virtual Environment
```bash
# Make sure virtual environment is activated
source .venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Script Execution Errors
```bash
# Verify Python version (3.9+)
python --version

# Check syntax
python -m py_compile pxsecretmigrate/*.py pxsecretmigrate/utils/*.py
```

### Git Issues
```bash
# If remote already exists
git remote remove origin
git remote add origin <new-url>
```

---

## Next Steps

1. ✓ Extract bundle
2. ✓ Initialize git repository
3. ✓ Set up Python environment
4. ✓ Verify installation
5. ✓ Create remote repository
6. Test with your Kubernetes cluster
7. Add CI/CD pipelines (optional)
8. Create releases/tags
9. Share with team

---

## Support

- Check [README.md](README.md) for usage documentation
- Review [CLAUDE.md](CLAUDE.md) for development context
- See [pxsecretmigrate/README.md](pxsecretmigrate/README.md) for detailed script docs

---

## Important Notes

- **Utils are nested**: `pxsecretmigrate/utils/` (not at root level)
- **Run as modules**: Use `python -m pxsecretmigrate.script_name`
- **Includes dotenv**: python-dotenv dependency added for environment variable management

---

**Created**: November 17, 2025
**Extracted from**: pyplayground monorepo
**Bundle Location**: `/development/git/pyplayground/tmp/pxsecretmigrate-standalone.tar.gz`
