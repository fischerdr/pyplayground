# Secret Scanner Tool Documentation

## Overview

The Secret Scanner Tool is a Python-based utility designed to detect potential sensitive information in code and configuration files. It can identify various types of secrets including passwords, API keys, tokens, and private keys in multiple file formats.

## Features

### Secret Detection Types

- **Passwords**
  - Standard password assignments
  - JSON/Dictionary style password fields
  - Password name/type fields
  - Prefixed passwords (New/Old/Current/Default/Admin)
  - Environment variable references

- **API Keys**
  - API key assignments
  - API secrets
  - Authentication tokens

- **AWS Credentials**
  - AWS access key IDs
  - AWS secret access keys
  - AWS ARNs

- **Private Keys**
  - RSA private keys
  - OpenSSH private keys

- **Tokens**
  - Authentication tokens
  - Bearer tokens
  - Access tokens

### File Format Support

- Python files (`.py`)
- JSON files (`.json`)
- YAML files (`.yaml`, `.yml`)
- Markdown files (`.md`)
- Environment files (`.env`)
- Configuration files (`.conf`)

### Smart Detection

- Handles nested dictionary structures
- Safely processes YAML files with custom tags
- Ignores template variables (e.g., `{{ credentials.password }}`)
- Detects secrets in environment variable references

## Installation

### Requirements

- Python 3.9 or higher
- Dependencies listed in `requirements.txt`

### Setup

1. Clone the repository
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Make the script executable:

```bash
chmod +x find_passwords.py
```

## Usage

### Basic Usage

```bash
./find_passwords.py /path/to/scan
```

### Options

- `--log-level, -l`: Set logging level (DEBUG, INFO, WARNING, ERROR)

  ```bash
  ./find_passwords.py /path/to/scan --log-level DEBUG
  ```

### Output

The tool provides color-coded output with:

- File path where secret was found
- Type of secret detected
- Line number (when available)
- The secret value
- Context (surrounding code/text)

## Pattern Detection

### Password Patterns

```python
# Direct assignments
password = "secret123"
passwd = 'mypassword'

# JSON/Dict style
{"password": "secret123"}
{"PasswordName": "AdminPassword"}

# Prefixed passwords
{"NewPassword": "secret123"}
{"DefaultPassword": "pass123"}
```

### API Key Patterns

```python
api_key = "1234567890"
API_SECRET = "abcdef123456"
```

### AWS Credential Patterns

```python
aws_access_key_id = "AKIA1234567890"
aws_secret_access_key = "abcdef1234567890"
arn:aws:service:region:account-id:resource
```

### Environment Variable References

```python
password = os.getenv("DB_PASSWORD")
secret = environ.get("API_SECRET")
```

## Security Considerations

1. The tool may produce false positives - always review findings manually
2. Some secrets may be legitimate test data - use context to determine validity
3. Consider using this tool as part of your CI/CD pipeline to prevent secret exposure

## Project Structure

```text
.
├── find_passwords.py          # Main script
├── utils/
│   └── password_finder.py     # Core functionality
├── requirements.txt           # Project dependencies
└── docs/
    └── secret_scanner.md      # This documentation
```

## Development

### Adding New Patterns

To add new secret patterns, modify the `SECRET_PATTERNS` dictionary in `utils/password_finder.py`:

```python
SECRET_PATTERNS = {
    "New Secret Type": [
        r'pattern1',
        r'pattern2',
    ],
}
```

### Contributing

1. Follow Python best practices
2. Include type hints
3. Add docstrings for new functions
4. Update tests for new functionality
5. Update documentation for new features

## Troubleshooting

### Common Issues

1. **YAML Parsing Errors**
   - The tool will fall back to text-based scanning if YAML parsing fails
   - Check for custom YAML tags in your files

2. **False Positives**
   - Review the context of each finding
   - Adjust patterns if necessary

3. **Performance Issues**
   - Limit the scope of directories being scanned
   - Use more specific file patterns

## License

This tool is part of the internal codebase and should be used in accordance with your organization's policies.
