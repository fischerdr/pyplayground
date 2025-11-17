# PXSecretMigrate Standalone Repository Bundle

## Bundle Information

**File**: `pxsecretmigrate-standalone.tar.gz`
**Location**: `/development/git/pyplayground/tmp/pxsecretmigrate-standalone.tar.gz`
**Size**: 62KB
**Created**: November 17, 2025

## Contents

This tar bundle contains everything needed to initialize `pxsecretmigrate` as a standalone git repository:

### Configuration Files
- `README.md` - User-facing documentation for the standalone project
- `CLAUDE.md` - AI context and development notes
- `pyproject.toml` - Python project configuration with minimal dependencies
- `requirements.txt` - Pinned Python dependencies
- `.flake8` - Linting configuration
- `.gitignore` - Git ignore patterns

### Source Code
- `pxsecretmigrate/` - Main package directory
  - `__init__.py` - Package initialization
  - `k8s_px_pvc_data_exporter.py` - Export PVC data
  - `k8s_px_pvc_vault_secret_checker.py` - Validate Vault secrets
  - `k8s_px_volume_details.py` - Query volume details
  - `px_vault_to_k8s_secret_migrator.py` - Perform migration
  - `verify_px_k8s_secret_migration.py` - Verify migration
  - `README.md` - Detailed script documentation

- `utils/` - Shared utility modules
  - `__init__.py` - Utils package initialization
  - `k8s_utils.py` - Kubernetes utilities
  - `vault_utils.py` - Vault utilities
  - `px_api.py` - Portworx API utilities
  - `migration_utils.py` - Migration helpers
  - `logging_utils.py` - Logging configuration

### Directory Structure
- `logs/` - Log files directory (with .gitkeep)
- `tmp/` - Temporary files directory (with .gitkeep)

## Key Changes from Original

1. **Import Paths Updated**
   - Changed from `from pyplayground.utils.*` to `from utils.*`
   - All imports updated in both main scripts and utility modules

2. **Streamlined Dependencies**
   - Reduced from 47+ dependencies to core requirements:
     - click (CLI)
     - hvac (Vault client)
     - kubernetes (K8s client)
     - pyyaml (YAML parsing)
     - requests (HTTP)
     - rich (Terminal formatting)

3. **Standalone Documentation**
   - New README.md tailored for standalone usage
   - CLAUDE.md for AI assistant context
   - Project structure documentation

4. **Package Structure**
   - Properly configured as Python package
   - Includes __init__.py files
   - Ready for pip installation

## Extracting and Using the Bundle

### Extract the Bundle
```bash
# Create a new directory for the repository
mkdir pxsecretmigrate
cd pxsecretmigrate

# Extract the bundle
tar -xzf /path/to/pxsecretmigrate-standalone.tar.gz

# Initialize git repository
git init
git add .
git commit -m "Initial commit: Portworx Secret Migration Tools

Extracted from pyplayground monorepo as standalone project.
Includes migration tools for moving Portworx encryption keys
from HashiCorp Vault to Kubernetes Secrets."
```

### Setup Development Environment
```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# For development
pip install -r requirements.txt
pip install -e .
```

### Verify Installation
```bash
# Test import
python -c "from utils import k8s_utils; print('Success!')"

# Run a script with --help
python pxsecretmigrate/k8s_px_pvc_data_exporter.py --help
```

### Create Remote Repository
```bash
# On GitHub/GitLab, create a new repository named 'pxsecretmigrate'

# Add remote and push
git remote add origin <your-repo-url>
git branch -M main
git push -u origin main
```

## Included Utilities

The bundle includes only the utility modules required by the pxsecretmigrate scripts:

1. **k8s_utils.py** - Kubernetes client setup, config loading, pod operations
2. **vault_utils.py** - Vault client creation, authentication, secret retrieval
3. **px_api.py** - Portworx API operations, pxctl command execution
4. **migration_utils.py** - Secret name normalization, validation
5. **logging_utils.py** - Logging setup and configuration

## Dependencies

### Production Dependencies
- click >= 8.1.0
- hvac >= 1.2.1
- kubernetes >= 25.3.0
- pyyaml >= 6.0.1
- requests >= 2.31.0
- rich >= 14.0.0

### Development Dependencies (Optional)
- pytest >= 7.4.0
- pytest-cov >= 4.1.0
- black >= 23.12.0
- mypy >= 1.8.0
- flake8 >= 7.0.0
- flake8-docstrings >= 1.7.0
- isort >= 5.13.0
- pip-tools >= 7.0.0

## File Count
Total: 26 files/directories

## Next Steps

1. Extract the bundle to create the repository structure
2. Initialize git repository
3. Create remote repository on GitHub/GitLab
4. Push initial commit
5. Set up CI/CD if needed
6. Create releases/tags as needed

## Notes

- All import paths have been updated for standalone usage
- The bundle is ready to be extracted and used immediately
- Documentation is complete and tailored for the standalone project
- Configuration files (.flake8, pyproject.toml) are included
- Empty directories (logs/, tmp/) include .gitkeep files for git tracking
