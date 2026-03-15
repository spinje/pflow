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

    Uses TemplateResolver.resolve_template() to support the full template syntax
    including coalesce (??), nested index templates, and type preservation.

    Args:
        source_expr: Template expression like "${node.output}" or "node.output"
        shared_storage: The shared storage dictionary

    Returns:
        The resolved value or None if not found
    """
    # Normalize to ${...} format so resolve_template() can handle it
    if not source_expr.startswith("${"):
        source_expr = "${" + source_expr[1:] + "}" if source_expr.startswith("$") else "${" + source_expr + "}"

    # Use resolve_template() which handles coalesce (??), nested indices,
    # type preservation, and all other template syntax
    result = TemplateResolver.resolve_template(source_expr, shared_storage)

    # resolve_template returns the original string if unresolved
    if result == source_expr:
        return None
    return result


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
