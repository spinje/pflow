"""Shared formatters for workflow validation results.

This module provides formatting functions for displaying validation results
across CLI and MCP interfaces. All formatters return strings that can be
displayed directly or incorporated into structured responses.

Usage:
    >>> from pflow.execution.formatters.validation_formatter import format_validation_success
    >>> message = format_validation_success()
    >>> print(message)
    ✓ Schema validation passed
    ✓ Data flow validation passed
    ✓ Template structure validation passed
    ✓ Node types validation passed

    Workflow is valid and ready to execute!
"""


def format_validation_success() -> str:
    """Format validation success message (minimal, token-efficient).

    Returns concise success message. All 4 validation checks passed:
    1. Schema validation (IR structure compliance)
    2. Data flow validation (execution order, no cycles)
    3. Template structure validation (${variable} references)
    4. Node types validation (registry verification)

    Returns:
        Single-line success message

    Example:
        >>> result = format_validation_success()
        >>> result
        '✓ Workflow is valid'
    """
    return "✓ Workflow is valid"


def format_validation_failure(errors: list[str], suggestions: list[str] | None = None) -> str:
    """Format validation failure message with error list and suggestions.

    Shows validation errors with truncation after 10 errors to avoid
    overwhelming output. Auto-generates actionable suggestions from
    error messages if not provided.

    Args:
        errors: List of validation error messages
        suggestions: Optional list of actionable fix suggestions (auto-generated if None)

    Returns:
        Multi-line text with error list (max 10 shown) and suggestions

    Examples:
        >>> result = format_validation_failure(["Error 1", "Error 2"])
        >>> "✗ Static validation failed:" in result
        True
        >>> "• Error 1" in result
        True
        >>> "• Error 2" in result
        True

        >>> errors = [f"Error {i}" for i in range(15)]
        >>> result = format_validation_failure(errors)
        >>> "• Error 0" in result
        True
        >>> "• Error 9" in result
        True
        >>> "• Error 10" not in result
        True
        >>> "... and 5 more errors" in result
        True

        >>> result = format_validation_failure(["Unknown node type: 'foo'"])
        >>> "Suggestions:" in result
        True
        >>> "registry list" in result
        True
    """
    lines = ["✗ Static validation failed:"]

    # Show first 10 errors with bullet points
    for error in errors[:10]:
        lines.append(f"  • {error}")

    # Show count of additional errors
    if len(errors) > 10:
        lines.append(f"  ... and {len(errors) - 10} more errors")

    # Auto-generate suggestions if not provided
    if suggestions is None:
        from pflow.core.validation_utils import generate_validation_suggestions

        error_list = [{"message": err, "type": "validation"} for err in errors]
        suggestions = generate_validation_suggestions(error_list)

    # Add suggestions if available
    if suggestions:
        lines.append("")
        lines.append("Suggestions:")
        for suggestion in suggestions:
            lines.append(f"  • {suggestion}")

    return "\n".join(lines)
