"""Error handling utilities for MCP server.

This module provides error formatting and sanitization functions
to ensure LLM-friendly error messages without leaking sensitive data.
"""

import logging
import re
from typing import Any, Optional

from mcp.types import CallToolResult, TextContent

from pflow.core.security_utils import SENSITIVE_KEYS

logger = logging.getLogger(__name__)


def sanitize_error_message(error: Exception) -> str:
    """Sanitize error message to remove sensitive information.

    This function removes:
    - File paths (replaced with [PATH])
    - Tokens/keys (replaced with [REDACTED])
    - Stack traces (removed entirely)

    Args:
        error: The exception to sanitize

    Returns:
        Sanitized error message safe for LLM consumption
    """
    message = str(error)

    # Remove file paths
    message = re.sub(r"/[\w/.-]+", "[PATH]", message)
    message = re.sub(r"[A-Z]:\\[\w\\.-]+", "[PATH]", message)  # Windows paths

    # Remove potential tokens (long hex strings)
    message = re.sub(r"\b[a-f0-9]{32,}\b", "[TOKEN]", message, flags=re.IGNORECASE)

    # Remove potential API keys (common patterns)
    message = re.sub(r"\b[A-Z0-9]{20,}\b", "[KEY]", message)

    # Remove URLs with potential credentials
    message = re.sub(r"https?://[^:]+:[^@]+@[^\s]+", "https://[REDACTED]@[HOST]", message)

    return message


def sanitize_parameters(params: dict[str, Any]) -> dict[str, Any]:
    """Sanitize parameters to redact sensitive values.

    Args:
        params: Parameters dictionary to sanitize

    Returns:
        Sanitized parameters with sensitive values redacted
    """
    sanitized: dict[str, Any] = {}

    for key, value in params.items():
        key_lower = key.lower()

        # Check if key contains sensitive words
        is_sensitive = any(sensitive in key_lower for sensitive in SENSITIVE_KEYS)

        if is_sensitive:
            sanitized[key] = "<REDACTED>"
        elif isinstance(value, dict):
            # Recursively sanitize nested dicts
            sanitized[key] = sanitize_parameters(value)
        elif isinstance(value, str) and len(value) > 100:
            # Truncate very long strings (potential keys/tokens)
            sanitized[key] = value[:20] + "...<truncated>"
        else:
            sanitized[key] = value

    return sanitized


def format_error_result(
    error: Exception,
    error_type: str = "execution",
    suggestions: Optional[list[str]] = None,
    details: Optional[dict[str, Any]] = None,
) -> CallToolResult:
    """Format an error as an MCP CallToolResult.

    This ensures errors are visible to LLMs with the isError flag.

    Args:
        error: The exception that occurred
        error_type: Category of error (execution, validation, not_found, etc.)
        suggestions: Optional list of suggestions for recovery
        details: Optional additional error details

    Returns:
        CallToolResult with isError=True and formatted message
    """
    # Sanitize the error message
    safe_message = sanitize_error_message(error)

    # Build error message
    message_parts = [f"Error ({error_type}): {safe_message}"]

    if details:
        # Sanitize and add details
        safe_details = sanitize_parameters(details)
        for key, value in safe_details.items():
            message_parts.append(f"  {key}: {value}")

    if suggestions:
        message_parts.append("\nSuggestions:")
        for suggestion in suggestions:
            message_parts.append(f"  - {suggestion}")

    full_message = "\n".join(message_parts)

    # Log the full error for debugging (to stderr)
    logger.error(f"MCP tool error: {error}", exc_info=True)

    return CallToolResult(isError=True, content=[TextContent(type="text", text=full_message)])


def format_validation_error(field: str, issue: str, suggestions: Optional[list[str]] = None) -> CallToolResult:
    """Format a validation error with field information.

    Args:
        field: The field that failed validation
        issue: Description of the validation issue
        suggestions: Optional recovery suggestions

    Returns:
        CallToolResult with validation error details
    """
    message = f"Validation Error: {field} - {issue}"

    if suggestions:
        message += "\n\nSuggestions:"
        for suggestion in suggestions:
            message += f"\n  - {suggestion}"

    return CallToolResult(isError=True, content=[TextContent(type="text", text=message)])


def format_not_found_error(
    resource_type: str, resource_name: str, available: Optional[list[str]] = None
) -> CallToolResult:
    """Format a resource not found error.

    Args:
        resource_type: Type of resource (workflow, node, etc.)
        resource_name: Name of the missing resource
        available: Optional list of available alternatives

    Returns:
        CallToolResult with not found error and alternatives
    """
    message = f"{resource_type} not found: {resource_name}"

    if available:
        # Show first 5 alternatives
        shown = available[:5]
        message += f"\n\nAvailable {resource_type}s:"
        for item in shown:
            message += f"\n  - {item}"

        if len(available) > 5:
            message += f"\n  ... and {len(available) - 5} more"

    return CallToolResult(isError=True, content=[TextContent(type="text", text=message)])
