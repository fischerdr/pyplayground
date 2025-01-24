"""
Utility functions for searching secrets and passwords in various file types.

This module provides functionality to search for sensitive information patterns
in different file formats including JSON, YAML, and text files.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from typing_extensions import TypedDict
from yaml.constructor import SafeConstructor


# Type definitions
class PasswordInfo(TypedDict):
    """Type definition for secret/password information."""

    line: Optional[int]
    password: str
    text: Optional[str]
    type: str  # Type of secret found (e.g., "API Key", "Password", etc.)


class FileResult(TypedDict):
    """Type definition for file search results."""

    file: str
    passwords: List[PasswordInfo]


# Create a custom YAML constructor to handle unknown tags
class CustomSafeConstructor(SafeConstructor):
    """Custom YAML constructor that safely handles unknown tags."""

    @classmethod
    def remove_implicit_resolver(cls, tag_to_remove: str) -> None:
        """
        Remove implicit resolvers for a particular tag.

        Args:
            tag_to_remove: Tag to remove from implicit resolvers
        """
        if not hasattr(cls, "yaml_implicit_resolvers"):
            return

        for ch, items in cls.yaml_implicit_resolvers.items():
            cls.yaml_implicit_resolvers[ch] = [
                (tag, regexp) for tag, regexp in items if tag != tag_to_remove
            ]


def create_custom_yaml_loader() -> type:
    """
    Create a custom YAML loader that safely handles unknown tags.

    Returns:
        A custom YAML loader class
    """

    class CustomLoader(yaml.SafeLoader):
        """Custom YAML loader with safe tag handling."""

        pass

    # Handle custom tags by returning their values as strings
    def construct_undefined(self: yaml.Loader, node: yaml.Node) -> Any:
        if isinstance(node, yaml.ScalarNode):
            return node.value
        elif isinstance(node, yaml.SequenceNode):
            return [self.construct_undefined(item) for item in node.value]
        elif isinstance(node, yaml.MappingNode):
            return {
                self.construct_undefined(key): self.construct_undefined(value)
                for key, value in node.value
            }
        return None

    # Register the custom constructor for all tags
    CustomLoader.add_constructor(None, construct_undefined)
    return CustomLoader


# Common patterns for secret detection
SECRET_PATTERNS = {
    "API Key": [
        r'(?i)api[_-]?key["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r'(?i)api[_-]?secret["\']?\s*[:=]\s*["\']([^"\']+)["\']',
    ],
    "AWS Key": [
        r'(?i)aws[_-]?access[_-]?key[_-]?id["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r'(?i)aws[_-]?secret[_-]?access[_-]?key["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r"(?i)arn:aws:[a-z0-9-]+:[a-z0-9-]+:\d{12}:[a-zA-Z0-9-]+[/][a-zA-Z0-9-]+",
    ],
    "Password": [
        # Direct assignments excluding template variables
        r'(?i)password["\']?\s*[:=]\s*["\']([^"\'{}]+)["\'](?!\s*}})',
        r'(?i)passwd["\']?\s*[:=]\s*["\']([^"\'{}]+)["\'](?!\s*}})',
        r'(?i)pass["\']?\s*[:=]\s*["\']([^"\'{}]+)["\'](?!\s*}})',
        # JSON/Dict style password fields
        r'["\'](?:\w+)?[Pp]assword(?:\w+)?["\']\s*:\s*["\']([^"\'{}]+)["\'](?!\s*}})',
        r'["\'](?:\w+)?[Pp]asswd(?:\w+)?["\']\s*:\s*["\']([^"\'{}]+)["\'](?!\s*}})',
        # Password name fields
        r'["\']Password(?:Name|Id|Key|Field|Type)?["\']\s*:\s*["\']([^"\'{}]+)["\'](?!\s*}})',
        # New password fields
        r'["\'](?:New|Old|Current|Default|Admin)?Password["\']\s*:\s*["\']([^"\'{}]+)["\'](?!\s*}})',
    ],
    "Private Key": [
        r"-----BEGIN (?:RSA )?PRIVATE KEY-----[^-]*-----END (?:RSA )?PRIVATE KEY-----",
        r"-----BEGIN OPENSSH PRIVATE KEY-----[^-]*-----END OPENSSH PRIVATE KEY-----",
    ],
    "Token": [
        r'(?i)token["\']?\s*[:=]\s*["\']([^"\'{}]+)["\'](?!\s*}})',
        r'(?i)auth[_-]token["\']?\s*[:=]\s*["\']([^"\'{}]+)["\'](?!\s*}})',
        r'(?i)bearer["\']?\s*[:=]\s*["\']([^"\'{}]+)["\'](?!\s*}})',
    ],
    "Environment Variable": [
        r'(?i)(?:password|passwd|pass|token|secret|key)\s*=\s*(?:os\.getenv\([\'"][\w_]+[\'"]\)|environ\.get\([\'"][\w_]+[\'"]\))',
    ],
}


def should_ignore_line(line: str) -> bool:
    """
    Check if a line should be ignored for secret scanning.

    Args:
        line: The line to check

    Returns:
        True if the line should be ignored, False otherwise
    """
    ignore_patterns = [
        # Basic template variables
        r"{{\s*[\w\._-]+\s*}}",  # Simple variable
        # Template variables with filters or functions
        r"{{\s*[\w\._-]+\s*\|[^}]+}}",  # Variables with filters
        r"{{\s*[\w\._-]+\.[^}]+}}",  # Variables with attributes/methods
        # Ansible/Jinja2 specific patterns
        r"{{\s*[\w\._-]+\s*\|\s*default\([^}]+\)\s*}}",  # default filter
        r"{{\s*[\w\._-]+\.stdout(?:_lines)?\s*}}",  # stdout/stdout_lines
        r"{{\s*[\w\._-]+\.stdout(?:_lines)?\[[-\d]+\]\s*}}",  # array access
        # GitHub Actions variables
        r"\$\{\{\s*(?:secrets|env|vars|inputs|github)\.[A-Z0-9_]+\s*\}\}",  # ${{ secrets.TOKEN }}
        r"\$\{\{[\s\w\._-]+\}\}",  # Other GitHub Actions expressions
        # Template logic
        r"{%\s*[\w\._\s]+\s*%}",
        # Test patterns
        # r'r["\'].*?password.*?["\']',  # Raw string containing 'password'
        # r"assert.*password",  # Assertions about passwords
        # r"mock.*password",  # Mocked password functions
        # r"test.*password",  # Test cases for passwords
        # r"\[.*?password.*?\]",  # Password in list/array context
    ]

    # Combine all patterns into one regex for efficiency
    combined_pattern = "|".join(f"(?:{pattern})" for pattern in ignore_patterns)
    return bool(re.search(combined_pattern, line, re.IGNORECASE))


def should_ignore_file(file_path: Path) -> bool:
    """
    Check if a file should be ignored based on its path.

    Args:
        file_path: Path to the file

    Returns:
        True if the file should be ignored, False otherwise
    """
    # Patterns for test-related files
    test_patterns = [
        r"test_.*\.py$",  # Python test files
        r".*_test\.py$",  # Alternative test file naming
        r".*/tests/.*",  # Files in test directories
        r".*_spec\.rb$",  # Ruby spec files
        r".*/spec/.*",  # Ruby spec directories
        r".*\.spec\.ts$",  # TypeScript spec files
        r".*\.test\.ts$",  # TypeScript test files
        r".*\.spec\.js$",  # JavaScript spec files
        r".*\.test\.js$",  # JavaScript test files
    ]

    # Check if the file matches any test patterns
    file_str = str(file_path)
    return any(re.search(pattern, file_str) for pattern in test_patterns)


def is_sensitive_key(key: str) -> Optional[str]:
    """
    Check if a dictionary key indicates sensitive information.

    Args:
        key: The key to check

    Returns:
        The type of sensitive information if found, None otherwise
    """
    key = str(key).lower()

    # Password-related keys
    if any(x in key for x in ["password", "passwd", "pass"]):
        return "Password"
    # Token-related keys
    elif any(x in key for x in ["token", "bearer", "auth"]):
        return "Token"
    # API key related
    elif any(x in key for x in ["api_key", "apikey", "api_secret"]):
        return "API Key"
    # AWS specific
    elif any(x in key for x in ["aws_key", "aws_secret", "aws_token"]):
        return "AWS Key"
    # General secrets
    elif any(x in key for x in ["secret", "private", "key"]):
        return "Secret"
    return None


def extract_from_dict(
    data: Union[Dict, List], key_filter: str = "password"
) -> List[tuple[str, str]]:
    """
    Recursively extract sensitive values from dictionary or list.

    Args:
        data: The dictionary or list to search through
        key_filter: The key to filter by (default is 'password')

    Returns:
        List of tuples containing (secret_type, value)
    """
    results: List[tuple[str, str]] = []

    def recurse(obj: Union[Dict, List]) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if secret_type := is_sensitive_key(k):
                    if isinstance(v, str):
                        results.append((secret_type, v))
                    elif isinstance(v, dict):
                        # Check nested dictionary values for sensitive data
                        for sub_k, sub_v in v.items():
                            if isinstance(sub_v, str):
                                results.append((f"{secret_type} ({sub_k})", sub_v))
                elif isinstance(v, (dict, list)):
                    recurse(v)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    recurse(item)

    recurse(data)
    return results


def extract_from_text_with_line_numbers(content: str) -> List[PasswordInfo]:
    """
    Extract secrets using regex patterns from text content.

    Args:
        content: The text content to search

    Returns:
        List of dictionaries containing line number, secret value, and context
    """
    results: List[PasswordInfo] = []

    for line_number, line in enumerate(content.splitlines(), start=1):
        # Skip lines that should be ignored
        if should_ignore_line(line):
            continue

        # Skip lines that are purely template variables
        if re.match(r"^\s*(?:\$)?{{\s*.*\s*}}\s*$", line.strip()):
            continue

        for secret_type, patterns in SECRET_PATTERNS.items():
            for pattern in patterns:
                matches = re.finditer(pattern, line)
                for match in matches:
                    # Get the first group if it exists, otherwise use the full match
                    secret_value = match.group(1) if match.groups() else match.group(0)

                    # Skip if the secret value contains template syntax
                    if re.search(r"(?:\$)?{{.*}}|\{%.*%\}", secret_value):
                        continue

                    # Skip if the value looks like a test pattern
                    if re.search(r'^r["\'].*["\']$', secret_value):
                        continue

                    results.append(
                        {
                            "line": line_number,
                            "password": secret_value,
                            "text": line.strip(),
                            "type": secret_type,
                        }
                    )

    return results


def process_file(file_path: Path, ignore_tests: bool = True) -> Optional[FileResult]:
    """
    Process a single file for secret patterns.

    Args:
        file_path: Path to the file to process
        ignore_tests: Whether to ignore test files and directories

    Returns:
        Dictionary containing file information and found secrets, or None if processing fails
    """
    logger = logging.getLogger(__name__)

    # Skip test files if ignore_tests is True
    if ignore_tests and should_ignore_file(file_path):
        logger.debug(f"Skipping test file: {file_path}")
        return None

    try:
        content = file_path.read_text(encoding="utf-8")

        # Handle different file types
        if file_path.suffix == ".json":
            try:
                data = json.loads(content)
                secrets = extract_from_dict(data)
                passwords = [
                    {"line": None, "password": secret[1], "text": None, "type": secret[0]}
                    for secret in secrets
                ]
                # Also check for patterns in the raw content
                passwords.extend(extract_from_text_with_line_numbers(content))
            except json.JSONDecodeError:
                # If JSON parsing fails, treat as text
                passwords = extract_from_text_with_line_numbers(content)

        elif file_path.suffix in (".yaml", ".yml"):
            try:
                # Use custom loader for YAML files
                CustomLoader = create_custom_yaml_loader()
                data = yaml.load(content, Loader=CustomLoader)
                if data:  # Only process if YAML parsing succeeded
                    secrets = extract_from_dict(data)
                    passwords = [
                        {"line": None, "password": secret[1], "text": None, "type": secret[0]}
                        for secret in secrets
                    ]
                    # Also check for patterns in the raw content
                    passwords.extend(extract_from_text_with_line_numbers(content))
                else:
                    passwords = extract_from_text_with_line_numbers(content)
            except yaml.YAMLError as e:
                logger.warning(
                    f"YAML parsing error in {file_path}, falling back to text scanning: {str(e)}"
                )
                passwords = extract_from_text_with_line_numbers(content)

        else:  # Handle as text file
            passwords = extract_from_text_with_line_numbers(content)

        if passwords:
            return {"file": str(file_path), "passwords": passwords}

    except Exception as e:
        logger.error(f"Error processing {file_path}: {str(e)}")

    return None
