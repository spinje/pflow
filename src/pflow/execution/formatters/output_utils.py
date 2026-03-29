"""Unified output auto-detection for workflow execution.

When a workflow finishes without declared outputs, pflow guesses which
shared store key is "the output." This module provides the single
implementation used by both CLI text mode and JSON/MCP paths, ensuring
identical results regardless of output format.
"""

from typing import Any


def _is_valid_output_value(value: Any) -> bool:
    """Check if a value is valid for output.

    Rejects None and empty/whitespace-only strings.
    Accepts everything else (0, False, empty dict/list are valid).
    """
    return value is not None and (not isinstance(value, str) or value.strip() != "")


def _find_in_namespaces(shared_storage: dict[str, Any], key: str) -> Any:
    """Find the last occurrence of a key in namespaced storage.

    Iterates non-internal dict values in shared_storage, returns
    the last valid match for the given key. "Last" means most
    downstream in a sequential workflow (dict insertion order).

    Args:
        shared_storage: The shared storage dictionary
        key: The key to search for

    Returns:
        The last valid value found, or None
    """
    last_value = None

    for storage_key, namespace_dict in shared_storage.items():
        if not isinstance(namespace_dict, dict):
            continue
        if storage_key.startswith("_"):
            continue

        if key in namespace_dict:
            value = namespace_dict[key]
            if _is_valid_output_value(value):
                last_value = value

    return last_value


def find_auto_output(shared_storage: dict[str, Any]) -> tuple[str | None, Any]:
    """Find the auto-detectable output with the highest priority.

    Unified implementation used by both CLI text and JSON/MCP paths.

    Priority order: result > response > output > text > data > stdout
    Search order: root first, then namespaces (root is where declared outputs live)
    Validity filter: skips None and empty/whitespace strings
    Key filter: skips _ and __ prefixed keys
    Last-key fallback: if no priority key matches, takes the last valid non-internal key

    Args:
        shared_storage: The shared storage dictionary

    Returns:
        Tuple of (key_found, value) or (None, None) if no output found
    """
    priority_keys = ["result", "response", "output", "text", "data", "stdout"]

    for key in priority_keys:
        # Check root level first
        if key in shared_storage:
            value = shared_storage[key]
            if _is_valid_output_value(value):
                return key, value

        # Then check inside namespace dicts
        ns_value = _find_in_namespaces(shared_storage, key)
        if ns_value is not None:
            return key, ns_value

    # Last-key fallback: take the last valid non-internal key
    for key in reversed(list(shared_storage.keys())):
        if key.startswith("_"):
            continue
        value = shared_storage[key]
        if _is_valid_output_value(value):
            return key, value

    return None, None
