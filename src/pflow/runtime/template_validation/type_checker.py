"""Type checking utilities for template variable validation.

This module provides compile-time type checking for template variables,
ensuring that resolved values match expected parameter types.
"""

import re
from typing import Any

from pflow.core.types import outer_base_type
from pflow.registry.registry import Registry

# Type compatibility matrix
# source_type -> list of compatible target types
#
# BIDIRECTIONAL JSON compatibility for dict/list ↔ str:
#
#   Direction 1: str → dict/list (auto-parse feature)
#     Allows: ${shell.stdout} (type: str) → values (type: list) parameter
#     Runtime behavior (see runtime/engine/template_resolution.py):
#     - Simple templates (${var}) with JSON strings auto-parse to dict/list
#     - Complex templates ("text ${var}") stay as strings (escape hatch)
#     - Auto-parsing only happens when:
#       1. Template is simple (${var}, not "text ${var}")
#       2. String looks like JSON (starts with { or [)
#       3. String size ≤ 10MB (security limit)
#       4. Parsed type matches expected type
#     - Graceful fallback: invalid JSON stays as string, validation catches it
#
#   Direction 2: dict/list → str (auto-serialize feature)
#     Allows: ${node.results} (type: list) → command (type: str) parameter
#     Runtime behavior (see template_resolver.py:_convert_to_string):
#     - Complex templates ("echo ${var}") serialize dict/list to JSON
#     - Simple templates (${var} alone) preserve type (runtime check blocks)
#     - Enables embedding arrays/objects in shell commands, prompts, etc.
#
#   This bidirectional compatibility enables shell+jq → MCP workflows.
TYPE_COMPATIBILITY_MATRIX = {
    "any": [
        "any",
        "str",
        "string",
        "int",
        "integer",
        "float",
        "number",
        "bool",
        "boolean",
        "dict",
        "object",
        "list",
        "array",
    ],  # any is universal
    "str": ["any", "str", "string", "dict", "object", "list", "array"],  # str can auto-parse to structured types
    "string": ["any", "str", "string", "dict", "object", "list", "array"],  # Alias for str
    "int": ["any", "int", "integer", "float", "number", "str", "string"],  # int can widen to float/number/str
    "integer": ["any", "int", "integer", "float", "number", "str", "string"],  # Alias for int
    "float": ["any", "float", "number", "str", "string"],  # float can stringify
    "number": ["any", "float", "number", "int", "integer", "str", "string"],  # number (generic numeric) → int/float/str
    "bool": ["any", "bool", "boolean", "str", "string"],  # bool can stringify
    "boolean": ["any", "bool", "boolean", "str", "string"],  # Alias for bool
    "dict": ["any", "dict", "object", "str", "string"],  # dict ↔ str bidirectional (parse/serialize JSON)
    "object": ["any", "dict", "object", "str", "string"],  # Alias for dict
    "list": ["any", "list", "array", "str", "string"],  # list ↔ str bidirectional (parse/serialize JSON)
    "array": ["any", "list", "array", "str", "string"],  # Alias for list
}


def is_type_compatible(source_type: str, target_type: str) -> bool:
    """Check if source_type can be used where target_type is expected.

    Args:
        source_type: Type of the value being provided
        target_type: Type expected by the parameter

    Returns:
        True if compatible, False otherwise

    Examples:
        >>> is_type_compatible("int", "float")
        True
        >>> is_type_compatible("str", "int")
        False
        >>> is_type_compatible("dict|str", "str")  # union: every member must match
        True
    """
    # Exact match
    if source_type == target_type:
        return True

    # Handle union types in source (ALL types must be compatible with target)
    if "|" in source_type:
        source_types = [t.strip() for t in source_type.split("|")]
        return all(is_type_compatible(st, target_type) for st in source_types)

    # Handle union types in target (source must be compatible with ANY target type)
    if "|" in target_type:
        target_types = [t.strip() for t in target_type.split("|")]
        return any(is_type_compatible(source_type, tt) for tt in target_types)

    # Strip parameterized generics to their outer collection type before the
    # matrix lookup. The producer side already canonicalizes (list[str] -> array),
    # but registry param types keep generics verbatim (list[str]); without this an
    # array source could never satisfy a list[str] param. Element types are not
    # compared — consistent with code-node outputs, which also collapse to the
    # bare collection type. A future strict pass (Task 120) could add element-type
    # checking here. (issue #460)
    source_base = outer_base_type(source_type)
    target_base = outer_base_type(target_type)
    # Identity short-circuit: covers unknown-but-equal bracketed types (e.g. a
    # user-named generic `foo[bar]` outside the canonical vocabulary). For
    # canonical names this is redundant — every matrix entry already lists itself.
    if source_base == target_base:
        return True
    return target_base in TYPE_COMPATIBILITY_MATRIX.get(source_base, [])


def infer_template_type(  # noqa: C901
    template: str, workflow_ir: dict[str, Any], node_outputs: dict[str, Any]
) -> str | None:
    """Infer the type of a template variable path.

    Args:
        template: Template variable without ${} (e.g., "node.response.data")
        workflow_ir: Workflow IR for context
        node_outputs: Node output metadata from registry

    Returns:
        Inferred type string or None if cannot infer

    Examples:
        >>> workflow_ir = {"nodes": [{"id": "node"}]}
        >>> node_outputs = {
        ...     "node.result": {"type": "dict", "structure": {"count": {"type": "int"}}}
        ... }
        >>> infer_template_type("node.result", workflow_ir, node_outputs)
        'dict'
        >>> infer_template_type("node.result.count", workflow_ir, node_outputs)
        'int'
    """
    parts = template.split(".")

    # Handle array indices in base path (e.g., "items[0]" -> "items")
    base_var = parts[0]
    base_var_clean = re.sub(r"\[\d+\]", "", base_var)

    enable_namespacing = workflow_ir.get("enable_namespacing", True)

    # Check workflow inputs first
    workflow_inputs = workflow_ir.get("inputs", {})
    if base_var_clean in workflow_inputs:
        input_def = workflow_inputs[base_var_clean]
        if isinstance(input_def, dict) and "type" in input_def:
            if len(parts) == 1 and base_var == base_var_clean:
                input_type = input_def["type"]
                return str(input_type) if input_type else None
            # Inputs are simple types, no nested structure
            return None

    # Check if base_var is a node ID (when namespacing enabled)
    if enable_namespacing:
        node_ids = {n.get("id") for n in workflow_ir.get("nodes", [])}
        if base_var_clean in node_ids:
            # Namespaced: node.output_key.nested.path
            if len(parts) < 2:
                return None  # Invalid: just node ID

            # Clean the output key from array indices too
            output_key_part = re.sub(r"\[\d+\]", "", parts[1])
            node_output_key = f"{base_var_clean}.{output_key_part}"

            if node_output_key not in node_outputs:
                return None

            output_info = node_outputs[node_output_key]

            # No nested path - return base type
            if len(parts) == 2 and parts[1] == output_key_part:
                output_type = output_info.get("type", "any")
                return str(output_type)

            # Indexed base access (e.g. `results[0].field`) descends into the
            # item structure, not the top-level array structure. Mirrors the
            # equivalent traversal in path_validation.py::_validate_array_access
            # so that batch outputs get the same type visibility they already
            # have for path existence checks.
            if parts[1] != output_key_part and isinstance(output_info.get("items"), dict):
                return _infer_nested_type(parts[2:], output_info["items"])

            # Nested path - traverse structure
            return _infer_nested_type(parts[2:], output_info)

    # Direct output lookup (no namespacing or old workflow format)
    if base_var_clean in node_outputs:
        output_info = node_outputs[base_var_clean]

        if len(parts) == 1 and base_var == base_var_clean:
            output_type = output_info.get("type", "any")
            return str(output_type)

        return _infer_nested_type(parts[1:], output_info)

    # Cannot infer (unknown variable)
    return None


def _infer_nested_type(path_parts: list[str], output_info: dict[str, Any]) -> str | None:
    """Infer type by traversing nested structure.

    Args:
        path_parts: Remaining path parts to traverse
        output_info: Output metadata with structure

    Returns:
        Inferred type or None
    """
    structure = output_info.get("structure", {})

    # No structure - check if base type allows traversal
    if not structure:
        base_type = output_info.get("type", "any")
        types_in_union = [t.strip() for t in base_type.split("|")]
        if any(t in ["dict", "object", "any"] for t in types_in_union):
            return "any"  # Unknown nested type but traversable
        return None

    # Traverse structure
    current = structure
    for i, part in enumerate(path_parts):
        # Remove array indices for field lookup: items[0] -> items
        field_name = re.sub(r"\[\d+\]", "", part)

        if field_name not in current:
            return None

        field_info = current[field_name]

        if isinstance(field_info, dict) and "type" in field_info:
            # This is a typed field
            if i == len(path_parts) - 1:
                # Final field - return its type
                field_type = field_info["type"]
                return str(field_type) if field_type else None
            else:
                # More to traverse
                current = field_info.get("structure", {})
                if not current:
                    # No more structure info - check if type allows traversal
                    field_type = field_info["type"]
                    if field_type in ["dict", "object", "any"]:
                        return "any"
                    return None
        else:
            return None

    return None


def get_parameter_type(node_type: str, param_name: str, registry: Registry) -> str | None:
    """Get expected type for a node parameter.

    Args:
        node_type: Node type name
        param_name: Parameter name
        registry: Registry instance

    Returns:
        Expected type string or None if not found
    """
    nodes_metadata = registry.get_nodes_metadata([node_type])

    if node_type not in nodes_metadata:
        return None

    interface = nodes_metadata[node_type]["interface"]
    params = interface.get("params", [])

    for param in params:
        if isinstance(param, dict) and param.get("key") == param_name:
            param_type = param.get("type", "any")
            return str(param_type) if param_type else "any"

    return None
