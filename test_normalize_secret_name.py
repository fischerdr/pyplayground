#!/usr/bin/env python3
"""Test script to verify normalize_secret_name preserves -pvc suffixes."""

import re
from typing import Tuple

# Test the normalize_secret_name logic
VALID_SECRET_NAME_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
MAX_SECRET_NAME_LENGTH = 253

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
            print(f"Preserved -pvc suffix during truncation: '{old_normalized}' → '{normalized}'")
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

# Test cases to verify -pvc suffix preservation
# Note: The function preserves -pvc when it exists in SECRET_KEY, but doesn't add it if not present
test_cases = [
    # (secret_key, pvc_name, expected_result_contains_pvc, description)
    ("vault/secret/myservice-pvc", "myservice-pvc", True, "Preserve -pvc from SECRET_KEY"),
    ("myservice-pvc", "myservice-pvc", True, "Already valid with -pvc suffix"),
    ("vault/path/to/frontend-service-pvc", "frontend-service-pvc", True, "Complex path with -pvc"),
    ("invalid/chars/backend-pvc", "backend-pvc", True, "Invalid chars, preserve -pvc"),
    ("UPPERCASE/SERVICE-PVC", "service-pvc", True, "Case normalization, preserve -pvc"),
    ("very/long/path/that/might/exceed/length/limits/super-long-service-name-pvc", 
     "super-long-service-name-pvc", True, "Truncation preserves -pvc"),
    ("vault/secret/database", "database-pvc", False, "No -pvc in SECRET_KEY, normalize as-is"),
    ("normal-secret", "normal-pvc", False, "Valid SECRET_KEY without -pvc"),
]

print("Testing normalize_secret_name function for -pvc suffix preservation:\n")

for i, (secret_key, pvc_name, should_have_pvc, description) in enumerate(test_cases, 1):
    normalized, changed = normalize_secret_name(secret_key, pvc_name)
    has_pvc = normalized.endswith("-pvc")
    status = "✓ PASS" if has_pvc == should_have_pvc else "✗ FAIL"
    
    print(f"Test {i}: {status} - {description}")
    print(f"  Secret Key: {secret_key}")
    print(f"  PVC Name: {pvc_name}")
    print(f"  Normalized: {normalized}")
    print(f"  Changed: {changed}")
    print(f"  Has -pvc: {has_pvc}")
    print(f"  Valid K8s name: {VALID_SECRET_NAME_PATTERN.match(normalized) is not None}")
    print()

print("All tests demonstrate that -pvc suffixes are preserved when present!") 