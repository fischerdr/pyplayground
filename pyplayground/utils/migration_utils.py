#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utility functions for the Portworx Vault to Kubernetes secret migration scripts."""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

# --- Constants ---
SECRET_KEY_LABEL = "SECRET_KEY"
SECRET_CONTEXT_LABEL = "SECRET_CONTEXT"
VALID_SECRET_NAME_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
MAX_SECRET_NAME_LENGTH = 253

# --- Globals ---
logger = logging.getLogger(__name__)


def normalize_secret_name(secret_key: str, pvc_name: str) -> Tuple[str, bool]:
    """Normalize SECRET_KEY to a valid Kubernetes secret name.

    IMPORTANT: Preserves '-pvc' suffixes as Portworx requires this naming
    pattern to locate encryption keys correctly.

    Returns:
        Tuple of (normalized_name, was_changed)
    """
    original_key = secret_key

    # If secret_key is already valid, use it
    if len(secret_key) <= MAX_SECRET_NAME_LENGTH and VALID_SECRET_NAME_PATTERN.match(secret_key):
        return secret_key, False

    # Convert to lowercase and replace invalid characters with hyphens
    normalized = re.sub(r"[^a-z0-9-]", "-", secret_key.lower())

    # Replace multiple consecutive hyphens with single hyphen
    normalized = re.sub(r"-+", "-", normalized)

    # Remove leading/trailing hyphens only (preserve alphanumeric + internal hyphens)
    normalized = normalized.strip("-")

    # Truncate if too long, but preserve the -pvc suffix if present
    if len(normalized) > MAX_SECRET_NAME_LENGTH:
        if normalized.endswith("-pvc") and len(normalized) > 4:
            # Preserve -pvc suffix, truncate the beginning part
            max_prefix_length = MAX_SECRET_NAME_LENGTH - 4  # Save space for "-pvc"
            prefix = normalized[:-4][:max_prefix_length].rstrip("-")
            old_normalized = normalized
            normalized = f"{prefix}-pvc"
            logger.debug(f"Preserved -pvc suffix during truncation: '{old_normalized}' → '{normalized}'")
        else:
            normalized = normalized[:MAX_SECRET_NAME_LENGTH].rstrip("-")

    # If result is empty or still invalid, use PVC name as fallback
    if not normalized or not VALID_SECRET_NAME_PATTERN.match(normalized):
        normalized = pvc_name.lower()
        # For PVC names, preserve the structure but ensure K8s compliance
        normalized = re.sub(r"[^a-z0-9-]", "-", normalized)
        normalized = re.sub(r"-+", "-", normalized).strip("-")

    # Final validation - if still invalid, use a generic name
    if not VALID_SECRET_NAME_PATTERN.match(normalized):
        normalized = f"px-secret-{hash(original_key) & 0x7fffffff}"

    return normalized, True


def parse_export_data(input_file: str) -> Dict[str, List[Dict[str, Any]]]:
    """Parse and validate the JSON export file."""
    logger.debug(f"Parsing export data from {input_file}")

    try:
        with open(input_file, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Input file not found: {input_file}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in input file: {e}")
        raise ValueError(f"Invalid JSON in input file: {e}") from e

    if not isinstance(data, dict):
        logger.error("Input data must be a dictionary with namespaces as keys")
        raise ValueError("Input data must be a dictionary with namespaces as keys")

    # Validate structure
    total_entries = 0
    for namespace, pvc_list in data.items():
        if not isinstance(pvc_list, list):
            logger.warning(f"Namespace '{namespace}' does not contain a list of PVCs, skipping")
            continue
        total_entries += len(pvc_list)

    logger.info(f"Loaded {total_entries} PVC entries from {len(data)} namespaces")
    return data


def validate_pvc_entry(pvc_entry: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Validate a PVC entry and extract required fields.

    Returns:
        Dict with required fields or None if validation fails
    """
    required_fields = ["pvc", "pv", "portworxvolumeinspect_labels", "vault_data"]

    for field in required_fields:
        if field not in pvc_entry:
            logger.warning(f"Missing required field '{field}' in PVC entry: {pvc_entry.get('pvc', 'unknown')}")
            return None

    # Check for vault_data errors
    vault_data = pvc_entry["vault_data"]
    if not isinstance(vault_data, dict) or "error" in vault_data:
        error_msg = vault_data.get("error", "Unknown vault error") if isinstance(vault_data, dict) else "Invalid vault data"
        logger.warning(f"Vault data error for PVC '{pvc_entry['pvc']}': {error_msg}")
        return None

    # Extract volume labels
    volume_labels = pvc_entry["portworxvolumeinspect_labels"]
    if not isinstance(volume_labels, dict):
        logger.warning(f"Invalid volume labels for PVC '{pvc_entry['pvc']}'")
        return None

    secret_key = volume_labels.get(SECRET_KEY_LABEL)
    secret_context = volume_labels.get(SECRET_CONTEXT_LABEL)

    if not secret_key:
        logger.warning(f"Missing SECRET_KEY label for PVC '{pvc_entry['pvc']}'")
        return None

    if not secret_context:
        logger.warning(f"Missing SECRET_CONTEXT label for PVC '{pvc_entry['pvc']}'")
        return None

    # Extract the first key from vault_data as the encryption key
    vault_data_content = vault_data.get("data", {})
    if not vault_data_content:
        logger.warning(f"No data found in vault for PVC '{pvc_entry['pvc']}'")
        return None

    encryption_key = next(iter(vault_data_content.values()), None)
    if not encryption_key:
        logger.warning(f"No encryption key found in vault data for PVC '{pvc_entry['pvc']}'")
        return None

    return {
        "pvc_name": pvc_entry["pvc"],
        "pv_name": pvc_entry["pv"],
        "secret_key": secret_key,
        "secret_context": secret_context,
        "encryption_key": encryption_key,
    }
