"""Template type validation (Passes 6 and 7).

Pass 6: Validates template variable types match parameter expectations.
Pass 7: Blocks structured data (dict/list) in shell command parameters.
"""

import re
from typing import Any, Optional

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.registry import Registry
from pflow.runtime.template_resolver import TemplateResolver
from pflow.runtime.template_validation.type_checker import (
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


def validate_template_types(
    workflow_ir: dict[str, Any], node_outputs: dict[str, Any], registry: Registry
) -> list[Diagnostic]:
    """Validate template variable types match parameter expectations.

    Args:
        workflow_ir: Workflow IR
        node_outputs: Node output metadata from registry
        registry: Registry instance

    Returns:
        Type mismatch diagnostics
    """
    diagnostics: list[Diagnostic] = []

    for node in workflow_ir.get("nodes", []):
        node_type = node.get("type")
        node_id = node.get("id")
        params = node.get("params", {})

        for param_name, param_value in params.items():
            expected_type = get_parameter_type(node_type, param_name, registry)
            _check_param_type(param_name, param_value, expected_type, node_id, workflow_ir, node_outputs, diagnostics)

    return diagnostics


def _check_param_type(
    param_name: str,
    value: Any,
    expected_type: Optional[str],
    node_id: str,
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
    diagnostics: list[Diagnostic],
) -> None:
    """Recursively validate template types in a parameter value."""
    if isinstance(value, str) and TemplateResolver.has_templates(value):
        if expected_type and expected_type != "any":
            _check_string_template_types(
                param_name,
                value,
                expected_type,
                node_id,
                workflow_ir,
                node_outputs,
                diagnostics,
            )
    elif isinstance(value, dict):
        for val in value.values():
            _check_param_type(param_name, val, None, node_id, workflow_ir, node_outputs, diagnostics)
    elif isinstance(value, list):
        for item in value:
            _check_param_type(param_name, item, None, node_id, workflow_ir, node_outputs, diagnostics)


def _check_string_template_types(
    param_name: str,
    value: str,
    expected_type: str,
    node_id: str,
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
    diagnostics: list[Diagnostic],
) -> None:
    """Validate template types in a string parameter value."""
    templates = TemplateResolver.extract_variables(value)
    for template in templates:
        inferred_type = infer_template_type(template, workflow_ir, node_outputs)
        if not inferred_type or inferred_type == "any":
            continue
        if not is_type_compatible(inferred_type, expected_type):
            suggestions: list[str] | None = None
            available_fields: list[str] = []
            if inferred_type in ["dict", "list", "object"] and expected_type in ["str", "string"]:
                suggestions, available_fields = _generate_type_fix_suggestions(template, node_outputs, expected_type)

            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Validation Error",
                    node_id=node_id,
                    message=(
                        f"Type mismatch in parameter '{param_name}': template ${{{template}}} has type "
                        f"'{inferred_type}' but parameter expects '{expected_type}'."
                    ),
                    suggestions=suggestions,
                    context={
                        "category": "validation",
                        "path": f"nodes[id={node_id}].params.{param_name}",
                        "template": f"${{{template}}}",
                        "inferred_type": inferred_type,
                        "expected_type": expected_type,
                        "available_fields": available_fields or None,
                        "available_fields_total": len(available_fields) if available_fields else None,
                        "available_fields_label": "matching outputs" if available_fields else None,
                    },
                )
            )


# ---------------------------------------------------------------------------
# Pass 7: Shell command types
# ---------------------------------------------------------------------------


def _build_quoted_templates(command: str) -> set[str]:
    """Extract templates wrapped in single quotes as escape hatch.

    Splits coalesce operands so '${a ?? b}' exempts both 'a' and 'b'.
    """
    result: set[str] = set()
    for match in _QUOTED_TEMPLATE_PATTERN.finditer(command):
        for operand in TemplateResolver.split_coalesce_operands(match.group(1)):
            result.add(operand)
    return result


def validate_shell_command_types(workflow_ir: dict[str, Any], node_outputs: dict[str, Any]) -> list[Diagnostic]:
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
        Diagnostics for structured data in shell commands
    """
    diagnostics: list[Diagnostic] = []
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
        quoted_templates = _build_quoted_templates(command)

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
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        source="validator",
                        title="Validation Error",
                        node_id=node_id,
                        message=(
                            f"Shell node '{node_id}': cannot use ${{{template}}} (type: {blocked_type}) "
                            f"in command parameter — embedded {blocked_type} breaks shell parsing."
                        ),
                        suggestions=[
                            f"Access a specific field: ${{{template}.fieldname}}",
                            f'Use stdin for the whole object: stdin: "${{{template}}}", command: "jq \'.field\'"',
                            f"Quote the template to accept JSON coercion: '${{{template}}}'",
                        ],
                        context={
                            "category": "validation",
                            "path": f"nodes[id={node_id}].params.command",
                            "template": f"${{{template}}}",
                            "blocked_type": blocked_type,
                            "shell_command": display_cmd,
                        },
                    )
                )
            else:
                # Multiple templates - need different approach
                template_list = ", ".join(f"${{{t}}} ({typ})" for t, typ in blocked_templates)
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        source="validator",
                        title="Validation Error",
                        node_id=node_id,
                        message=(
                            f"Shell node '{node_id}': multiple structured data templates in command: "
                            f"{template_list}. Shell commands can only receive ONE data source via stdin."
                        ),
                        suggestions=[
                            "Use temp files: write each data source via write-file nodes, then read in shell.",
                            "Process each data source in separate shell nodes, then combine results.",
                            "Pass one via stdin and reference another via file.",
                            "Quote the template to accept JSON coercion: '${var}'",
                        ],
                        context={
                            "category": "validation",
                            "path": f"nodes[id={node_id}].params.command",
                            "shell_command": display_cmd,
                            "blocked_templates": [
                                {"template": f"${{{template_name}}}", "type": blocked_type_name}
                                for template_name, blocked_type_name in blocked_templates
                            ],
                        },
                    )
                )

    return diagnostics


# ---------------------------------------------------------------------------
# Type fix suggestions
# ---------------------------------------------------------------------------


def _generate_type_fix_suggestions(
    template: str, node_outputs: dict[str, Any], expected_type: str
) -> tuple[list[str], list[str]]:
    """Generate structured suggestions for type mismatches with actual available fields.

    Args:
        template: The template variable that has the wrong type
        node_outputs: Node output metadata from registry
        expected_type: The type that was expected

    Returns:
        Tuple of (suggestions, available_fields)
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
        return ([f"Access a specific field, for example ${{{template}.field}}.", "Serialize the value to JSON."], [])

    # Find fields that match the expected type
    matching_fields = []
    for field_name, field_info in structure.items():
        if isinstance(field_info, dict) and "type" in field_info:
            field_type = field_info["type"]
            # Check if this field matches the expected type
            if field_type in [expected_type, "str", "string"] and expected_type in ["str", "string"]:
                matching_fields.append(field_name)

    if matching_fields:
        suggestions = [f"Use ${{{template}.{field}}}" for field in matching_fields[:5]]
        available_fields = [f"${{{template}.{field}}}" for field in matching_fields]
        return (suggestions, available_fields)
    return (["Access a nested field or serialize the value to JSON."], [])


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
