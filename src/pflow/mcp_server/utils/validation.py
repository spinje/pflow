"""Input validation utilities for MCP server.

This module provides validation functions for security and correctness.

Note: generate_dummy_parameters has been moved to pflow.core.validation_utils
for reuse across CLI and MCP.
"""

import logging
import re
from typing import Any, Optional

from pflow.core.validation_utils import generate_dummy_parameters  # noqa: F401 - Re-export for compatibility

logger = logging.getLogger(__name__)


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
