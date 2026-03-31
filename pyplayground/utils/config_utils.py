"""Configuration utility functions."""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Union

from dotenv import load_dotenv

from .logging_utils import get_project_root

logger = logging.getLogger(__name__)

# Get the project root directory
PROJECT_ROOT = get_project_root()
DEFAULT_CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")


def load_env_file(env_file: Optional[Union[str, Path]] = None) -> None:
    """Load environment variables from a .env file.

    Args:
        env_file: Optional path to .env file (default: .env in project root)
    """
    try:
        if env_file is None:
            env_file = os.path.join(PROJECT_ROOT, ".env")

        if os.path.exists(env_file):
            load_dotenv(dotenv_path=env_file, override=True)
            logger.debug(f"Loaded environment variables from {env_file}")
        else:
            logger.warning(f"Environment file not found: {env_file}")

    except Exception as e:
        logger.error(f"Failed to load .env file: {e}")
        raise


def get_env_var(key: str, default: Optional[str] = None, required: bool = False, as_type: type = str) -> Optional[Any]:
    """Get an environment variable with optional default value and type conversion.

    Args:
        key: Environment variable name
        default: Default value if not found
        required: If True, raise error when not found
        as_type: Type to convert the value to (str, int, float, bool)

    Returns:
        Environment variable value or default

    Raises:
        ValueError: If required is True and variable not found
        TypeError: If value cannot be converted to specified type
    """
    value = os.environ.get(key, default)

    if required and value is None:
        raise ValueError(f"Required environment variable {key} not set")

    if value is not None:
        try:
            if as_type is bool:
                # Handle string conversion to boolean
                if isinstance(value, str):
                    return value.lower() in ("true", "1", "yes", "on")
            return as_type(value)
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to convert {key}={value} to type {as_type.__name__}: {e}")
            raise TypeError(f"Cannot convert {key} to {as_type.__name__}")

    return value


def load_json_config(config_name: str, config_dir: Optional[Union[str, Path]] = DEFAULT_CONFIG_DIR) -> Dict[str, Any]:
    """Load configuration from a JSON file in the config directory.

    Args:
        config_name: Name of the config file (with or without .json extension)
        config_dir: Directory containing config files (default: PROJECT_ROOT/config)

    Returns:
        Dict containing configuration

    Raises:
        FileNotFoundError: If config file not found
        json.JSONDecodeError: If config file is invalid JSON
    """
    try:
        if not config_name.endswith(".json"):
            config_name += ".json"

        config_path_str = str(config_dir) if config_dir else str(DEFAULT_CONFIG_DIR)
        config_path = os.path.join(config_path_str, config_name)

        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r") as f:
            config: Dict[str, Any] = json.load(f)
            logger.debug(f"Loaded configuration from {config_path}")
            return config

    except FileNotFoundError:
        logger.error(f"Config file not found: {config_path}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config file {config_path}: {e}")
        raise


def save_json_config(
    config: Dict[str, Any],
    config_name: str,
    config_dir: Optional[Union[str, Path]] = DEFAULT_CONFIG_DIR,
) -> None:
    """Save configuration to a JSON file in the config directory.

    Args:
        config: Configuration dictionary to save
        config_name: Name of the config file (with or without .json extension)
        config_dir: Directory to save config file (default: PROJECT_ROOT/config)

    Raises:
        IOError: If unable to write to file
    """
    try:
        if config_dir and not os.path.exists(str(config_dir)):
            os.makedirs(str(config_dir))

        if not config_name.endswith(".json"):
            config_name += ".json"

        config_path = os.path.join(str(config_dir), config_name)

        with open(config_path, "w") as f:
            json.dump(config, f, indent=4)
            logger.debug(f"Saved configuration to {config_path}")

    except IOError as e:
        logger.error(f"Failed to save config file {config_path}: {e}")
        raise


def merge_configs(*configs: Dict[str, Any]) -> Dict[str, Any]:
    """Merge multiple configuration dictionaries.

    Later configs override earlier ones.

    Args:
        *configs: Configuration dictionaries to merge

    Returns:
        Merged configuration dictionary
    """
    result = {}
    for config in configs:
        result.update(config)
    return result
