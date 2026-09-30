"""Type checking utilities for template variable validation.

This module provides compile-time type checking for template variables,
ensuring that resolved values match expected parameter types.
"""

from collections.abc import Sequence
from typing import Any

from pflow.core.templates import TRUSTED_TRAVERSABLE_TYPES, Field, Segment, parse_path
from pflow.core.types import outer_base_type
from pflow.registry.registry import Registry

from .utils import descend_index

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
#     Runtime behavior (see core/templates.py::_convert_to_string):
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


def infer_template_type(template: str, workflow_ir: dict[str, Any], node_outputs: dict[str, Any]) -> str | None:
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
    ref = parse_path(template)
    if ref is None:
        return None

    # Check workflow inputs first — they are simple types, no nested structure
    input_def = workflow_ir.get("inputs", {}).get(ref.root)
    if isinstance(input_def, dict) and "type" in input_def:
        return str(input_def["type"]) if not ref.path and input_def["type"] else None

    # A node ID root (namespacing enabled): node.output_key.nested.path
    if workflow_ir.get("enable_namespacing", True) and ref.root in {n.get("id") for n in workflow_ir.get("nodes", [])}:
        if not ref.path or not isinstance(ref.path[0], Field):
            return None  # Invalid: just node ID
        output_info = node_outputs.get(f"{ref.root}.{ref.path[0].name}")
        return None if output_info is None else _infer_nested_type(ref.path[1:], output_info)

    # Direct output lookup (no namespacing or old workflow format)
    if ref.root in node_outputs:
        return _infer_nested_type(ref.path, node_outputs[ref.root])

    # Cannot infer (unknown variable)
    return None


def _infer_nested_type(segments: Sequence[Segment], output_info: dict[str, Any]) -> str | None:
    """Infer the type at ``segments`` below a declared output.

    A field reads the current ``structure``; an index descends to the element
    (``descend_index`` — the same rule Pass 5 validates with). A field below a
    structure-less trusted-traversable type is ``"any"``; below anything else,
    unknown (``None``).
    """
    info = output_info
    for segment in segments:
        if not isinstance(segment, Field):
            element, _ = descend_index(info)
            if element is None:
                return None
            info = element
            continue
        structure = info.get("structure") or {}
        if not structure:
            types_in_union = {t.strip() for t in str(info.get("type", "any")).split("|")}
            return "any" if types_in_union & TRUSTED_TRAVERSABLE_TYPES else None
        field_info = structure.get(segment.name)
        if not (isinstance(field_info, dict) and "type" in field_info):
            return None
        info = field_info
    output_type = info.get("type", "any")
    return str(output_type) if output_type else None


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
