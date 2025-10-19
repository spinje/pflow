"""Input validation utilities for MCP server.

This module provides validation functions for security and correctness,
including path traversal prevention and workflow name validation.

Note: generate_dummy_parameters has been moved to pflow.core.validation_utils
for reuse across CLI and MCP.
"""

import logging
import re
from pathlib import Path
from typing import Any, Optional

from pflow.core.validation_utils import generate_dummy_parameters  # noqa: F401 - Re-export for compatibility

logger = logging.getLogger(__name__)

# Path traversal patterns to block (always dangerous)
ALWAYS_DANGEROUS_PATTERNS = [
    r"\.\.",  # Parent directory
    # Tilde expansion is safe for local MCP servers (Python's Path.expanduser() handles it)
    r"[\x00]",  # Null bytes
]

# Absolute path patterns (only dangerous if allow_absolute=False)
ABSOLUTE_PATH_PATTERNS = [
    r"^/",  # Absolute paths (Unix)
    r"^[A-Z]:",  # Absolute paths (Windows)
]


def validate_file_path(path_str: str, allow_absolute: bool = False) -> tuple[bool, Optional[str]]:
    """Validate a file path for security.

    Prevents path traversal attacks and validates path safety.

    Args:
        path_str: The path string to validate
        allow_absolute: Whether to allow absolute paths

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check for always-dangerous patterns
    for pattern in ALWAYS_DANGEROUS_PATTERNS:
        if re.search(pattern, path_str):
            return False, f"Path contains dangerous pattern: {pattern}"

    # Check for absolute path patterns only if not allowed
    if not allow_absolute:
        for pattern in ABSOLUTE_PATH_PATTERNS:
            if re.search(pattern, path_str):
                return False, f"Path contains dangerous pattern: {pattern}"

    try:
        path = Path(path_str)

        # Check if absolute when not allowed
        if path.is_absolute() and not allow_absolute:
            return False, "Absolute paths not allowed"

        # Resolve the path to check for traversal
        # This will resolve .. and symlinks
        resolved = path.resolve()

        # Check if the resolved path is still under expected directory
        # For relative paths, ensure they don't escape
        if not path.is_absolute():
            cwd = Path.cwd()
            try:
                # Check if resolved path is under current directory
                resolved.relative_to(cwd)
            except ValueError:
                return False, "Path escapes current directory"

        return True, None

    except Exception as e:
        return False, f"Invalid path: {e!s}"


# generate_dummy_parameters is now imported from pflow.core.validation_utils above
# (removed duplicate definition)


def validate_execution_parameters(params: dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Validate execution parameters for safety.

    Checks for:
    - Parameter name security (shell-safe characters)
    - Reasonable parameter sizes
    - No code injection attempts
    - Valid data types

    Args:
        params: Execution parameters to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check parameter names for security (prevents shell injection via parameter names)
    from pflow.core.validation_utils import get_parameter_validation_error, is_valid_parameter_name

    for key in params:
        if not is_valid_parameter_name(key):
            error_msg = get_parameter_validation_error(key, "parameter")
            return False, error_msg

    # Check total size (prevent memory attacks)
    import json

    try:
        param_str = json.dumps(params)
        if len(param_str) > 1024 * 1024:  # 1MB limit
            return False, "Parameters too large (max 1MB)"
    except Exception as e:
        return False, f"Parameters not JSON serializable: {e}"

    # Check for suspicious patterns (basic code injection prevention)
    suspicious_patterns = [
        r"__import__",
        r"eval\s*\(",
        r"exec\s*\(",
        r"compile\s*\(",
        r"globals\s*\(",
        r"locals\s*\(",
    ]

    param_str = str(params)
    for pattern in suspicious_patterns:
        if re.search(pattern, param_str, re.IGNORECASE):
            return False, f"Suspicious pattern detected: {pattern}"

    return True, None
