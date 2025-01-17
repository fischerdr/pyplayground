# Vault Tools Documentation

## List Secrets Tool

This tool provides functionality to list keys in a Vault KV store using the hvac client library.

### Prerequisites

- Python 3.9 or higher (< 3.14)
- Access to a HashiCorp Vault server
- Vault token with appropriate permissions

### Installation

1. Create and activate a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

For development, install additional dependencies:
```bash
pip install -r requirements-dev.txt
```

### Configuration

The tool requires the following environment variables:
- `VAULT_ADDR`: The address of your Vault server (e.g., "http://vault:8200")
- `VAULT_TOKEN`: A valid Vault token with permissions to list secrets
- `VAULT_NAMESPACE`: (Optional) Vault namespace for Enterprise installations

You can set these either in your environment or using a `.env` file.

#### Using Environment Variables Directly
```bash
export VAULT_ADDR="http://vault:8200"
export VAULT_TOKEN="your-vault-token"
export VAULT_NAMESPACE="optional-namespace"  # Optional
```

#### Using .env File
1. Copy the example .env file:
```bash
cp .env.example .env
```

2. Edit the `.env` file with your specific values:
```ini
VAULT_ADDR="http://vault:8200"
VAULT_TOKEN="your-vault-token"
VAULT_NAMESPACE="optional-namespace"  # Optional
```

The script will automatically load these environment variables from the `.env` file using python-dotenv when it runs. This is more convenient than setting environment variables manually and helps keep your configuration separate from your code.

**Note**: Make sure to add `.env` to your `.gitignore` file to prevent sensitive credentials from being committed to version control.

### Usage

```bash
# List secrets at the root of the static_secrets KV store
python -m vault_tools.list_secrets

# List secrets at a specific path
python -m vault_tools.list_secrets --path="my/secret/path"

# Use a different KV store mount point
python -m vault_tools.list_secrets --mount-point="different_secrets"

# Hide secret values when displaying data
python -m vault_tools.list_secrets --no-data

# Show unmasked secret values (use with caution!)
python -m vault_tools.list_secrets --unmask

# Specify Vault address and token directly
python -m vault_tools.list_secrets --vault-addr="http://vault:8200" --vault-token="my-token"
```

### Features

- Interactive navigation through secret paths using arrow keys
- User-friendly menu-based selection interface
- Automatic detection of secret data vs directories
- Configurable masking of sensitive values
- Recursive exploration of nested paths
- Optional data display control

### Security Features

- Sensitive string values are masked by default (shown as ********)
- Optional unmasking with --unmask flag (use with caution!)
- Warning displayed when showing unmasked values
- Non-string values (numbers, booleans) are never masked

### Command Line Options

- `--mount-point`, `-m`: KV store mount point (default: "static_secrets")
- `--path`, `-p`: Path within the KV store (default: "")
- `--vault-addr`: Vault server address (optional, can use VAULT_ADDR env var)
- `--vault-token`: Vault token (optional, can use VAULT_TOKEN env var)
- `--namespace`, `-n`: Vault namespace (optional, can use VAULT_NAMESPACE env var)
- `--show-data/--no-data`: Show or hide secret data when available (default: show)
- `--mask/--unmask`: Mask or unmask sensitive values in output (default: mask)

### Navigation

The tool provides an interactive menu-based interface for navigating through secrets:
- Use ↑ and ↓ arrow keys to move between options
- Press Enter to select a key to explore
- Select "Exit" or press Ctrl+C to stop exploring the current path
- Secret values are automatically displayed when found (unless --no-data is used)

### Development

Run tests:
```bash
pytest
```

Format code:
```bash
black vault_tools/
```

Type checking:
```bash
mypy vault_tools/
