"""Output resolution for workflows with namespacing.

This module handles the resolution of workflow output declarations that use
source expressions to map namespaced node values to root-level outputs.
"""

from typing import Any, Optional

from pflow.runtime.template_resolver import TemplateResolver


def resolve_output_source(source_expr: str, shared_storage: dict[str, Any]) -> Optional[Any]:
    """Resolve a source expression to get output value.

    Handles multiple source expression formats:
    - ${node.output} - Template format with brackets
    - $node.output - Dollar prefix format
    - node.output - Plain format

    Args:
        source_expr: Template expression like "${node.output}" or "node.output"
        shared_storage: The shared storage dictionary

    Returns:
        The resolved value or None if not found
    """
    # Strip template syntax wrappers (${...} or $...)
    if source_expr.startswith("${") and source_expr.endswith("}"):
        source_expr = source_expr[2:-1]
    elif source_expr.startswith("$"):
        source_expr = source_expr[1:]

    # Use existing TemplateResolver.resolve_value which handles path traversal
    return TemplateResolver.resolve_value(source_expr, shared_storage)


def populate_declared_outputs(
    shared_storage: dict[str, Any],
    workflow_ir: dict[str, Any],
) -> None:
    """Populate declared outputs in shared storage using their source expressions.

    This resolves source expressions and writes values to root level of shared storage,
    making them available for output access. This is necessary for workflows with
    automatic namespacing enabled, where node outputs are isolated under node_id.key.

    Args:
        shared_storage: The shared storage dictionary (modified in place)
        workflow_ir: The workflow IR specification containing output declarations
    """
    outputs = workflow_ir.get("outputs", {})
    if not outputs:
        return

    for output_name, output_config in outputs.items():
        # Skip outputs without source field (backward compatibility)
        if not isinstance(output_config, dict) or "source" not in output_config:
            continue

        source_expr = output_config["source"]

        # Resolve the source expression
        try:
            value = resolve_output_source(source_expr, shared_storage)
            if value is not None:
                # Write to root level for output access
                shared_storage[output_name] = value
        except Exception:  # noqa: S110
            # Silently continue - outputs are best-effort
            # This matches the current CLI behavior where output resolution
            # failures don't stop workflow execution
            pass
