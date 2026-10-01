"""Type checking utilities for template variable validation.

This module provides compile-time type checking for template variables,
ensuring that resolved values match expected parameter types.
"""

from collections.abc import Sequence
from typing import Any

from pflow.core.templates import TRUSTED_TRAVERSABLE_TYPES, Field, Segment, parse_path
from pflow.registry.registry import Registry

from .utils import descend_index


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
