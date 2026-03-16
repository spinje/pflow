"""Template type validation (Passes 6 and 7).

Pass 6: Validates template variable types match parameter expectations.
Pass 7: Blocks structured data (dict/list) in shell command parameters.
"""

import re
from typing import Any, Optional

from pflow.registry import Registry
from pflow.runtime.template_resolver import TemplateResolver
from pflow.runtime.type_checker import (
    get_parameter_type,
    infer_template_type,
    is_type_compatible,
)

# Pattern to detect templates exactly wrapped in single quotes: '${var}'
# This is an escape hatch for structured types in shell commands.
#
# Matches:   '${var}', '${node.field}', '${data.items[0].name}'
# Does NOT match: '${a} ${b}', 'prefix ${var}', '$${var}' (escaped)
#
# Note: Array indices use [] not {}, so [^}]+ correctly captures paths
# like 'data.items[0].value' without stopping at brackets.
_QUOTED_TEMPLATE_PATTERN = re.compile(r"'\$\{([^}]+)\}'")

# Types that are safe in shell commands (string-like or unknown type)
# When a union contains one of these, runtime coercion to string is acceptable.
_SHELL_SAFE_TYPES = {"str", "string", "any"}


def _extract_base_type(type_str: str) -> str:
    """Extract base type from generic type string.

    Generic types like list[dict] or dict[str, any] have a base type
    (list, dict) that determines their shell command compatibility.

    Examples:
        list[dict] -> list
        dict[str, any] -> dict
        str -> str
        list -> list

    Args:
        type_str: Type string, possibly with generic parameters

    Returns:
        Base type without generic parameters
    """
    return type_str.split("[")[0]


def _is_shell_safe_type(inferred_type: str, blocked_types: set[str]) -> tuple[bool, str | None]:
    """Check if a type is safe for shell command embedding.

    Args:
        inferred_type: The inferred type string (may be union like "dict|str")
        blocked_types: Set of blocked type names

    Returns:
        Tuple of (is_safe, blocked_type_if_not_safe)
        - (True, None) if type is safe
        - (False, "dict") if blocked, with the first blocked type
    """
    # Split union and get base type for each component
    type_parts = [t.strip() for t in inferred_type.split("|")]
    base_types = [_extract_base_type(t) for t in type_parts]

    # Tier 1: If union contains a safe base type (str, string, any), allow it
    if any(t in _SHELL_SAFE_TYPES for t in base_types):
        return (True, None)

    # Check if any base type is blocked
    blocked_parts = [t for t in base_types if t in blocked_types]
    if blocked_parts:
        return (False, blocked_parts[0])

    return (True, None)


# ---------------------------------------------------------------------------
# Pass 6: Type matching
# ---------------------------------------------------------------------------


def validate_template_types(workflow_ir: dict[str, Any], node_outputs: dict[str, Any], registry: Registry) -> list[str]:
    """Validate template variable types match parameter expectations.

    Args:
        workflow_ir: Workflow IR
        node_outputs: Node output metadata from registry
        registry: Registry instance

    Returns:
        List of type mismatch errors
    """
    errors: list[str] = []

    for node in workflow_ir.get("nodes", []):
        node_type = node.get("type")
        node_id = node.get("id")
        params = node.get("params", {})

        for param_name, param_value in params.items():
            expected_type = get_parameter_type(node_type, param_name, registry)
            _check_param_type(param_name, param_value, expected_type, node_id, workflow_ir, node_outputs, errors)

    return errors


def _check_param_type(
    param_name: str,
    value: Any,
    expected_type: Optional[str],
    node_id: str,
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
    errors: list[str],
) -> None:
    """Recursively validate template types in a parameter value."""
    if isinstance(value, str) and TemplateResolver.has_templates(value):
        if expected_type and expected_type != "any":
            _check_string_template_types(param_name, value, expected_type, node_id, workflow_ir, node_outputs, errors)
    elif isinstance(value, dict):
        for val in value.values():
            _check_param_type(param_name, val, None, node_id, workflow_ir, node_outputs, errors)
    elif isinstance(value, list):
        for item in value:
            _check_param_type(param_name, item, None, node_id, workflow_ir, node_outputs, errors)


def _check_string_template_types(
    param_name: str,
    value: str,
    expected_type: str,
    node_id: str,
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
    errors: list[str],
) -> None:
    """Validate template types in a string parameter value."""
    templates = TemplateResolver.extract_variables(value)
    for template in templates:
        inferred_type = infer_template_type(template, workflow_ir, node_outputs)
        if not inferred_type or inferred_type == "any":
            continue
        if not is_type_compatible(inferred_type, expected_type):
            error_msg = (
                f"Type mismatch in node '{node_id}' parameter '{param_name}': "
                f"template ${{{template}}} has type '{inferred_type}' "
                f"but parameter expects '{expected_type}'"
            )
            if inferred_type in ["dict", "list", "object"] and expected_type in ["str", "string"]:
                error_msg += _generate_type_fix_suggestion(template, node_outputs, expected_type)
            errors.append(error_msg)


# ---------------------------------------------------------------------------
# Pass 7: Shell command types
# ---------------------------------------------------------------------------


def validate_shell_command_types(workflow_ir: dict[str, Any], node_outputs: dict[str, Any]) -> list[str]:
    """Block dict/list types in shell command parameters.

    Shell commands cannot safely handle JSON embedded in command strings
    due to shell escaping issues. This check runs BEFORE template resolution
    to catch the problem at validation time rather than runtime.

    The general type checker allows dict/list → str (for LLM prompts, HTTP bodies),
    but shell commands are special - embedded JSON breaks shell parsing.

    Validation has three tiers:
    1. Fix 0: Extract base types from generics (list[dict] → list) before checking
    2. Tier 1: Auto-allow unions containing safe types (str, string, any)
    3. Tier 2: Allow templates wrapped in single quotes '${var}' as an escape hatch

    Args:
        workflow_ir: Workflow IR
        node_outputs: Node output metadata from registry

    Returns:
        List of errors for structured data in shell commands
    """
    errors = []
    # Types that cannot be safely embedded in shell command strings.
    # Includes both Python type names (dict, list) and JSON Schema names (object, array)
    # since workflow IR may use either convention.
    SHELL_BLOCKED_TYPES = {"dict", "object", "list", "array"}

    for node in workflow_ir.get("nodes", []):
        node_type = node.get("type")
        node_id = node.get("id")

        # Only check shell nodes
        if node_type != "shell":
            continue

        params = node.get("params", {})
        command = params.get("command", "")

        # Skip if command has no templates
        if not isinstance(command, str) or not TemplateResolver.has_templates(command):
            continue

        # Tier 2: Find templates exactly wrapped in single quotes (escape hatch)
        # Pattern '${var}' signals user accepts runtime coercion to string
        quoted_templates = {match.group(1) for match in _QUOTED_TEMPLATE_PATTERN.finditer(command)}

        # Check each template in the command and collect blocked ones
        templates = TemplateResolver.extract_variables(command)
        blocked_templates: list[tuple[str, str]] = []  # (template, type)

        for template in templates:
            # Tier 2: Skip if template is quoted (user accepts coercion)
            if template in quoted_templates:
                continue

            inferred_type = infer_template_type(template, workflow_ir, node_outputs)

            # Skip if cannot infer type (will be caught by path validation)
            if not inferred_type:
                continue

            # Check if type is safe (handles Fix 0 and Tier 1)
            is_safe, blocked_type = _is_shell_safe_type(inferred_type, SHELL_BLOCKED_TYPES)
            if not is_safe and blocked_type:
                blocked_templates.append((template, blocked_type))

        # Generate a single consolidated error if any templates are blocked
        if blocked_templates:
            display_cmd = command if len(command) <= 60 else command[:57] + "..."

            if len(blocked_templates) == 1:
                # Single template - simple case
                template, blocked_type = blocked_templates[0]
                errors.append(
                    f"Shell node '{node_id}': cannot use ${{{template}}} (type: {blocked_type}) "
                    f"in command parameter.\n\n"
                    f"PROBLEM: {blocked_type} data embedded in shell commands breaks parsing "
                    f"(quotes, backticks, $() cause errors).\n\n"
                    f"CURRENT (breaks):\n"
                    f'  "command": "{display_cmd}"\n\n'
                    f"FIX OPTIONS:\n\n"
                    f"1. Access specific fields (if they're strings/numbers):\n"
                    f"   ${{{template}.fieldname}}, ${{{template}.count}}, etc.\n\n"
                    f"2. Use stdin for the whole object:\n"
                    f'   {{"stdin": "${{{template}}}", "command": "jq \'.field\'"}}\n\n'
                    f"3. Quote the template to accept JSON coercion (if you've verified it's safe):\n"
                    f"   '${{{template}}}' - wrapping in single quotes signals you accept runtime coercion"
                )
            else:
                # Multiple templates - need different approach
                template_list = ", ".join(f"${{{t}}} ({typ})" for t, typ in blocked_templates)
                errors.append(
                    f"Shell node '{node_id}': multiple structured data templates in command: "
                    f"{template_list}\n\n"
                    f"PROBLEM: Shell commands can only receive ONE data source via stdin.\n\n"
                    f"CURRENT (breaks):\n"
                    f'  "command": "{display_cmd}"\n\n'
                    f"FIX OPTIONS:\n\n"
                    f"1. Use temp files - write each data source to a file, then read in shell:\n"
                    f"   ### save-a\n"
                    f"   - type: write-file\n"
                    f"   - file_path: /tmp/a.json\n"
                    f"   - content: ${{data-a}}\n\n"
                    f"   ### save-b\n"
                    f"   - type: write-file\n"
                    f"   - file_path: /tmp/b.json\n"
                    f"   - content: ${{data-b}}\n\n"
                    f"   ### process\n"
                    f"   - type: shell\n"
                    f"   ```shell command\n"
                    f"   jq -s '.[0] * .[1]' /tmp/a.json /tmp/b.json\n"
                    f"   ```\n\n"
                    f"2. Process each data source in separate shell nodes, combine results after\n\n"
                    f"3. Pass one via stdin, reference another via file\n\n"
                    f"4. Quote templates to accept JSON coercion (if you've verified they're safe):\n"
                    f"   '${{template}}' - wrapping in single quotes signals you accept runtime coercion"
                )

    return errors


# ---------------------------------------------------------------------------
# Type fix suggestions
# ---------------------------------------------------------------------------


def _generate_type_fix_suggestion(  # noqa: C901
    template: str, node_outputs: dict[str, Any], expected_type: str
) -> str:
    """Generate helpful suggestions for type mismatches with actual available fields.

    Args:
        template: The template variable that has the wrong type
        node_outputs: Node output metadata from registry
        expected_type: The type that was expected

    Returns:
        Suggestion string with available fields
    """
    # For nested templates like node.output.field, we need to traverse to find structure
    # Find the structure for this template by traversing
    structure = None
    for key in node_outputs:
        if template.startswith(key + ".") or template == key:
            output_info = node_outputs[key]
            remaining_path = template[len(key) :].lstrip(".")

            if not remaining_path:
                # This IS the base output
                structure = output_info.get("structure", {})
                break
            else:
                # Need to traverse nested structure
                structure = _traverse_to_structure(output_info.get("structure", {}), remaining_path)
                if structure:
                    break

    if not structure:
        # Generic fallback
        return f"\n  \U0001f4a1 Suggestion: Access a specific field (e.g., ${{{template}.field}}) or serialize to JSON"

    # Find fields that match the expected type
    matching_fields = []
    for field_name, field_info in structure.items():
        if isinstance(field_info, dict) and "type" in field_info:
            field_type = field_info["type"]
            # Check if this field matches the expected type
            if field_type in [expected_type, "str", "string"] and expected_type in ["str", "string"]:
                matching_fields.append(field_name)

    if matching_fields:
        suggestion = "\n  \U0001f4a1 Available fields with correct type:"
        for field in matching_fields[:5]:  # Show up to 5
            suggestion += f"\n     - ${{{template}.{field}}}"
        if len(matching_fields) > 5:
            suggestion += f"\n     ... and {len(matching_fields) - 5} more"
        return suggestion
    else:
        return "\n  \U0001f4a1 Suggestion: Access a nested field or serialize to JSON"


def _traverse_to_structure(structure: dict[str, Any], path: str) -> Optional[dict[str, Any]]:
    """Traverse nested structure to find the structure at a given path.

    Args:
        structure: The structure dict to traverse
        path: Dot-separated path like "author.login"

    Returns:
        The structure dict at that path, or None if not found
    """
    if not path or not structure:
        return structure

    path_parts = path.split(".")
    current = structure

    for part in path_parts:
        if part in current:
            field_info = current[part]
            if isinstance(field_info, dict):
                current = field_info.get("structure", {})
                if not current:
                    return None
            else:
                return None
        else:
            return None

    return current
