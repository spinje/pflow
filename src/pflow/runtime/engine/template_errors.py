"""Template error message formatting for node wrapper.

Builds detailed, actionable error messages for template resolution failures:
- Type mismatches (dict/list where str expected, malformed JSON)
- Unresolved template variables with context, suggestions, and JSON hints
- Coalesce expression diagnostics (per-operand resolution status)
"""

from typing import Any

from ..template_resolver import TemplateResolver


def build_type_error_message(
    param_key: str,
    resolved_value: Any,
    template_str: str,
    expected_type: str,
    actual_type: str,
) -> str:
    """Build detailed, actionable error message for type mismatch.

    Args:
        param_key: Parameter name
        resolved_value: The resolved value (wrong type)
        template_str: Original template string
        expected_type: Expected type from metadata
        actual_type: Actual type of resolved value

    Returns:
        Formatted multi-section error message with fix suggestions
    """
    # Extract variable name from template for suggestions
    var_match = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.search(template_str)
    var_name = var_match.group(1) if var_match else "variable"

    # Build base error
    error_msg = (
        f"Parameter '{param_key}' expects {expected_type} but received {actual_type}\n\n"
        f"Template used: {template_str}\n"
        f"Resolved to: {actual_type} object\n"
    )

    # Add fix suggestions
    error_msg += "\n\U0001f4a1 Common fixes:\n"

    # Fix 1: Serialize to JSON (works for dict/list)
    error_msg += "  1. Serialize to JSON (recommended):\n"
    error_msg += f'     {param_key}: "{template_str}"\n\n'

    # Fix 2: Access specific field (for dicts) or item (for lists)
    if isinstance(resolved_value, dict):
        error_msg += "  2. Access a specific field:\n"
        error_msg += f"     {param_key}: ${{{var_name}.field_name}}\n\n"
    elif isinstance(resolved_value, list):
        error_msg += "  2. Access a specific item:\n"
        error_msg += f"     {param_key}: ${{{var_name}[0]}}\n\n"

    # Fix 3: Combine with text
    error_msg += "  3. Combine with text:\n"
    error_msg += f'     {param_key}: "Summary: {template_str}"\n'

    # Show available fields/items for dicts
    if isinstance(resolved_value, dict) and resolved_value:
        keys = list(resolved_value.keys())[:10]  # Limit to 10 keys
        error_msg += f"\n\nAvailable fields in {var_name}:\n"
        for key in keys:
            error_msg += f"  - {key}\n"

        if len(resolved_value) > 10:
            remaining = len(resolved_value) - 10
            error_msg += f"  ... and {remaining} more\n"

    # Show item count for lists
    elif isinstance(resolved_value, list):
        error_msg += f"\n\n{var_name} contains {len(resolved_value)} items\n"
        if len(resolved_value) > 0:
            error_msg += f"Access items with: ${{{var_name}[0]}}, ${{{var_name}[1]}}, etc.\n"

    return error_msg


def build_json_parse_error_message(
    param_key: str,
    resolved_value: str,
    template_str: str,
    expected_type: str,
    trimmed: str,
) -> str:
    """Build detailed error message for failed JSON parsing.

    Args:
        param_key: Parameter name
        resolved_value: The malformed JSON string
        template_str: Original template string
        expected_type: Expected type (dict/list/object/array)
        trimmed: Trimmed version of resolved_value

    Returns:
        Formatted error message with suggestions
    """
    # Preview of malformed JSON (limit to 200 chars)
    preview = trimmed[:200]
    if len(trimmed) > 200:
        preview += "..."

    # Detect common JSON issues
    issues = []
    if "'" in trimmed:
        issues.append("Single quotes detected (use double quotes: \"key\" not 'key')")
    if trimmed.count("{") != trimmed.count("}"):
        issues.append("Mismatched braces { }")
    if trimmed.count("[") != trimmed.count("]"):
        issues.append("Mismatched brackets [ ]")
    if ",}" in trimmed or ",]" in trimmed:
        issues.append("Trailing comma before closing brace/bracket")

    error_lines = [
        f"Parameter '{param_key}' expects {expected_type} but received malformed JSON string.",
        "",
        f"Template: {template_str}",
        f"Value preview: {preview}",
        "",
        f"The string starts with '{trimmed[0]}' suggesting JSON, but failed to parse.",
    ]

    if issues:
        error_lines.append("")
        error_lines.append("Detected issues:")
        for issue in issues:
            error_lines.append(f"  - {issue}")

    error_lines.extend([
        "",
        "Common JSON formatting issues:",
        "  - Missing closing brace/bracket",
        "  - Single quotes instead of double quotes",
        "  - Trailing commas in arrays/objects",
        "  - Unescaped special characters",
        "  - Missing quotes around object keys",
        "",
        "Fix: Ensure the source outputs valid JSON.",
        f"Test with: echo '{template_str}' | jq '.'",
    ])

    return "\n".join(error_lines)


def format_available_keys(available_display: list[str], context: dict[str, Any]) -> list[str]:
    """Format available keys section with type information.

    Args:
        available_display: List of keys to display (may include "... and N more")
        context: Resolution context

    Returns:
        List of formatted key lines
    """
    lines = ["Available context keys:"]

    for key in available_display:
        if key.startswith("... and"):
            lines.append(f"  {key}")
        else:
            value = context.get(key)
            value_type = type(value).__name__
            # Show preview for simple types
            if isinstance(value, (str, int, float, bool)) and not isinstance(value, bool):
                preview = str(value)[:50]
                if len(str(value)) > 50:
                    preview += "..."
                lines.append(f"  \u2022 {key} ({value_type}): {preview}")
            else:
                lines.append(f"  \u2022 {key} ({value_type})")

    return lines


def generate_suggestions(variables: set[str], available_keys: list[str]) -> list[str]:
    """Generate suggestions for close matches.

    Args:
        variables: Set of unresolved variable names
        available_keys: Available context keys

    Returns:
        List of suggestion strings
    """
    suggestions = []
    for var in variables:
        # For nested paths like "mynode.stdout", check if the first part
        # (node ID) is similar to any available key
        parts = var.split(".")
        node_id = parts[0]
        rest_of_path = ".".join(parts[1:]) if len(parts) > 1 else ""

        node_id_lower = node_id.lower()
        node_id_normalized = node_id.replace("_", "-").replace("-", "")

        for key in available_keys[:20]:
            if not isinstance(key, str):
                continue

            key_lower = key.lower()
            key_normalized = key.replace("_", "-").replace("-", "")

            # Check for similar node IDs (handles typos like mynode vs my-node)
            is_similar = (
                node_id_lower == key_lower
                or node_id_normalized == key_normalized
                or node_id_lower in key_lower
                or key_lower in node_id_lower
            )

            if is_similar and node_id != key:
                # Build the corrected variable path
                corrected = f"{key}.{rest_of_path}" if rest_of_path else key
                suggestions.append(f"Did you mean '${{{corrected}}}'? (instead of '${{{var}}}')")
                break

    return suggestions[:3]  # Limit to 3 suggestions


def detect_json_parse_hints(variables: set[str], context: dict[str, Any]) -> list[str]:
    """Detect if unresolved variables failed due to JSON parsing issues.

    When a variable like ${node.stdout.field} fails to resolve, check if
    node.stdout exists and is a string (not valid JSON). This helps users
    understand why nested access failed.

    Args:
        variables: Set of unresolved variable names
        context: Resolution context

    Returns:
        List of hint strings explaining JSON parse failures
    """
    hints = []

    for var in variables:
        parts = var.split(".")
        if len(parts) < 3:
            # Not a nested path like node.output.field
            continue

        # Check if parent path exists and is a string
        # e.g., for "node.stdout.field", check if "node.stdout" is a string
        node_id = parts[0]
        output_key = parts[1]

        if node_id in context and isinstance(context[node_id], dict):
            node_data = context[node_id]
            if output_key in node_data:
                value = node_data[output_key]
                if isinstance(value, str):
                    # Found it - the parent is a string, not parsed JSON
                    preview = value[:60] + "..." if len(value) > 60 else value
                    # Clean up preview for display (escape newlines)
                    preview = preview.replace("\n", "\\n")
                    hints.append(
                        f"${{{node_id}.{output_key}}} is a string, not JSON. "
                        f"Nested access (.{'.'.join(parts[2:])}) requires valid JSON."
                    )
                    hints.append(f'  Actual value: "{preview}"')
                    break  # One hint is enough

    return hints


def diagnose_coalesce(template_str: str, context: dict[str, Any]) -> tuple[list[str], set[str]]:
    """Diagnose coalesce expressions in a template and return error lines.

    For each coalesce expression, determines per-operand status:
    - Root absent: branch/node didn't execute
    - Root present but path failed: likely typo
    - Resolved: operand worked (shouldn't appear in unresolved templates)

    Args:
        template_str: Original template string (may contain multiple ${...})
        context: Resolution context

    Returns:
        Tuple of (diagnostic_lines, coalesce_variables) where
        coalesce_variables is the set of variable names already diagnosed
        (so they can be excluded from the generic unresolved list).
    """
    lines: list[str] = []
    diagnosed_vars: set[str] = set()

    for match in TemplateResolver.TEMPLATE_PATTERN.finditer(template_str):
        expr = match.group(1)
        if not TemplateResolver.is_coalesce_expression(expr):
            continue

        operands = TemplateResolver.split_coalesce_operands(expr)
        diagnosed_vars.update(operands)

        # Diagnose each operand
        operand_lines: list[str] = []
        for operand in operands:
            root = TemplateResolver._ROOT_SPLIT_PATTERN.split(operand)[0]
            if root not in context:
                operand_lines.append(f"  - ${{{operand}}}: node '{root}' did not execute")
            elif TemplateResolver.variable_exists(operand, context):
                operand_lines.append(f"  - ${{{operand}}}: resolved (OK)")
            else:
                # Root present but path failed — typo
                operand_lines.append(f"  - ${{{operand}}}: node '{root}' executed but path '{operand}' not found")

        lines.append(f"Coalesce expression ${{{expr}}} failed \u2014 no operand resolved:")
        lines.extend(operand_lines)

    return lines, diagnosed_vars


def build_enhanced_template_error(param_key: str, template: str, context: dict[str, Any]) -> str:
    """Build detailed error message for unresolved template.

    Args:
        param_key: Parameter name
        template: Original template string
        context: Resolution context (shared store + initial params)

    Returns:
        Formatted error message with context and suggestions
    """
    template_str = str(template)

    # Diagnose coalesce expressions first (with per-operand status)
    coalesce_lines, coalesce_vars = diagnose_coalesce(template_str, context)

    # Extract all variable names, filter to unresolved, exclude already-diagnosed coalesce vars
    all_variables = TemplateResolver.extract_variables(template_str)
    variables = {v for v in all_variables if not TemplateResolver.variable_exists(v, context)} - coalesce_vars

    # Build error header
    error_parts: list[str] = []
    if coalesce_lines:
        error_parts.append(f"Unresolved template in parameter '{param_key}':")
        error_parts.append("")
        error_parts.extend(coalesce_lines)
        if variables:
            error_parts.append("")
            error_parts.append(f"Also unresolved: {', '.join(f'${{{v}}}' for v in variables)}")
    elif variables:
        error_parts.append(
            f"Unresolved variables in parameter '{param_key}': {', '.join(f'${{{v}}}' for v in variables)}"
        )
    else:
        # Edge case: all variables individually exist but template still unresolved
        error_parts.append(f"Unresolved template in parameter '{param_key}'")

    # Append context keys, JSON hints, and suggestions
    all_unresolved = variables | {v for v in coalesce_vars if not TemplateResolver.variable_exists(v, context)}
    _append_error_context(error_parts, all_unresolved, context)

    return "\n".join(error_parts)


def _append_error_context(error_parts: list[str], unresolved: set[str], context: dict[str, Any]) -> None:
    """Append available keys, JSON hints, and suggestions to error message."""
    available_keys = [k for k in context if not k.startswith("__")]
    available_keys.sort()

    if len(available_keys) > 20:
        available_display = available_keys[:20]
        available_display.append(f"... and {len(available_keys) - 20} more")
    else:
        available_display = available_keys

    if available_keys:
        error_parts.append("")
        error_parts.extend(format_available_keys(available_display, context))

    json_hints = detect_json_parse_hints(unresolved, context)
    if json_hints:
        error_parts.append("")
        error_parts.append("\u26a0\ufe0f JSON parsing issue:")
        for hint in json_hints:
            error_parts.append(f"  {hint}")
        error_parts.append("  Fix: Ensure upstream node outputs valid JSON.")
    else:
        suggestions = generate_suggestions(unresolved, available_keys)
        if suggestions:
            error_parts.append("")
            error_parts.append("\U0001f4a1 Suggestions:")
            for s in suggestions:
                error_parts.append(f"  {s}")
