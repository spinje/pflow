"""Output resolution for workflows with namespacing.

This module handles the resolution of workflow output declarations that use
source expressions to map namespaced node values to root-level outputs.

Raises OutputResolutionError when a non-coalesce output source cannot be
resolved (e.g., references a node that didn't execute). Coalesce expressions
(using ??) where all operands are absent are silently skipped — the user
explicitly opted into fallthrough behavior.
"""

import re
from typing import Any, Optional

from pflow.runtime.template_resolver import TemplateResolver

_ROOT_SPLIT = re.compile(r"[.\[]")


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


def _normalize_source(source_expr: str) -> str:
    """Normalize a source expression to ${...} template format."""
    if source_expr.startswith("${"):
        return source_expr
    if source_expr.startswith("$"):
        return "${" + source_expr[1:] + "}"
    return "${" + source_expr + "}"


def _diagnose_unresolved_output(
    source_expr: str,
    normalized: str,
    shared_storage: dict[str, Any],
) -> dict[str, Any]:
    """Diagnose why an output source expression could not be resolved.

    Returns a dict with:
        - source_expr: the original source expression
        - diagnostics: list of human-readable diagnosis strings
        - raw_diagnostics: list of dicts with structured info per variable
    """
    variables = TemplateResolver.extract_variables(normalized)
    diagnostics: list[str] = []
    raw_diagnostics: list[dict[str, Any]] = []

    for var in sorted(variables):
        root = _ROOT_SPLIT.split(var, maxsplit=1)[0]

        if root not in shared_storage:
            msg = f"Variable '{var}': node '{root}' did not execute"
            diagnostics.append(msg)
            raw_diagnostics.append({"variable": var, "root": root, "root_absent": True})
        else:
            msg = f"Variable '{var}': node '{root}' executed but path '{var}' not found in its output"
            diagnostics.append(msg)
            raw_diagnostics.append({"variable": var, "root": root, "root_absent": False})

    return {
        "source_expr": source_expr,
        "diagnostics": diagnostics,
        "raw_diagnostics": raw_diagnostics,
    }


def populate_declared_outputs(
    shared_storage: dict[str, Any],
    workflow_ir: dict[str, Any],
) -> None:
    """Populate declared outputs in shared storage using their source expressions.

    This resolves source expressions and writes values to root level of shared storage,
    making them available for output access. This is necessary for workflows with
    automatic namespacing enabled, where node outputs are isolated under node_id.key.

    Raises OutputResolutionError when non-coalesce output sources fail to resolve.
    Outputs that DO resolve are populated before the error is raised.

    Args:
        shared_storage: The shared storage dictionary (modified in place)
        workflow_ir: The workflow IR specification containing output declarations

    Raises:
        OutputResolutionError: When one or more output sources cannot be resolved
            and no ?? coalesce operator is present.
    """
    outputs = workflow_ir.get("outputs", {})
    if not outputs:
        return

    failures: list[dict[str, Any]] = []

    for output_name, output_config in outputs.items():
        # Skip outputs without source field (backward compatibility)
        if not isinstance(output_config, dict) or "source" not in output_config:
            continue

        source_expr = output_config["source"]
        normalized = _normalize_source(source_expr)

        # Use resolve_template directly to distinguish unresolved from resolved-to-None
        result = TemplateResolver.resolve_template(normalized, shared_storage)

        if result != normalized:
            # Resolved successfully (or resolved to None)
            if result is not None:
                shared_storage[output_name] = result
            continue

        # Unresolved — check if this is a coalesce expression (user opted into fallthrough)
        inner = TemplateResolver.extract_simple_template_var(normalized)
        if inner and TemplateResolver.is_coalesce_expression(inner):
            # All-absent coalesce — silently skip (user explicitly used ??)
            continue

        # Non-coalesce source that can't resolve — record failure with diagnosis
        failure = _diagnose_unresolved_output(source_expr, normalized, shared_storage)
        failure["output_name"] = output_name
        failures.append(failure)

    if failures:
        from pflow.core.user_errors import OutputResolutionError

        raise OutputResolutionError(failures=failures)
