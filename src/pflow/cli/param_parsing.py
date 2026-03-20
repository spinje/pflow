"""Parameter parsing utilities for CLI commands."""

from __future__ import annotations

import json
from typing import Any


def infer_type(value: str) -> Any:
    """Infer type from string value.

    Supports:
    - Booleans: 'true', 'false' (case-insensitive)
    - Numbers: integers and floats
    - JSON: arrays and objects starting with '[' or '{'
    - Strings: everything else (default)

    Args:
        value: String value to infer type from

    Returns:
        Inferred Python value with appropriate type
    """
    # Boolean detection
    if value.lower() in ("true", "false"):
        return value.lower() == "true"

    # Number detection
    try:
        # Try integer first (more restrictive)
        if "." not in value and "e" not in value.lower():
            return int(value)
        # Then try float
        return float(value)
    except ValueError:
        pass

    # JSON detection for arrays and objects
    if value.startswith(("[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass

    # Default to string
    return value


def parse_workflow_params(args: tuple[str, ...]) -> dict[str, Any]:
    """Parse key=value parameters from command arguments.

    Args:
        args: Tuple of command line arguments

    Returns:
        Dictionary of parsed parameters with inferred types
    """
    params = {}
    for arg in args:
        # Only process arguments with '='
        if "=" in arg:
            key, value = arg.split("=", 1)
            # Use type inference for the value
            params[key] = infer_type(value)
    return params
