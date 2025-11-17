"""Formatter for field retrieval results (Task 89).

This module provides formatting for the read-fields command, which retrieves
specific field values from cached execution results.
"""

import json
from typing import Any


def format_field_output(
    field_values: dict[str, Any],
    format_type: str = "text",
) -> str | dict[str, Any]:
    """Format field retrieval results.

    Args:
        field_values: Mapping of field paths to values (None if not found)
        format_type: "text" or "json"

    Returns:
        Formatted string (text mode) or dict (json mode)

    Example:
        >>> values = {"result[0].title": "Issue 1", "result[0].id": 123}
        >>> print(format_field_output(values, "text"))
        result[0].title: Issue 1
        result[0].id: 123
    """
    if format_type == "json":
        return field_values

    # Text format - display each field with its value
    lines = []
    for field_path, value in field_values.items():
        if value is None:
            lines.append(f"{field_path}: (not found)")
        elif isinstance(value, (dict, list)):
            # Pretty print complex values
            json_str = json.dumps(value, indent=2, default=str)
            lines.append(f"{field_path}:")
            for line in json_str.split("\n"):
                lines.append(f"  {line}")
        else:
            lines.append(f"{field_path}: {value}")

    return "\n".join(lines) if lines else "(no fields retrieved)"
