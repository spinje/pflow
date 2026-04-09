"""Output resolution for workflows with namespacing.

This module handles the resolution of workflow output declarations that use
source expressions to map namespaced node values to root-level outputs.

Raises OutputResolutionError when a non-coalesce output source cannot be
resolved (e.g., references a node that didn't execute). Coalesce expressions
(using ??) where all operands are absent are silently skipped — the user
explicitly opted into fallthrough behavior.
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
    source_expr = _normalize_source(source_expr)

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

    Returns the structured ``unresolved_references`` list consumed by the
    template-error rendering pipeline in ``core/diagnostic.py``. All
    per-reference detail (status, failure category/data, peer suggestions,
    typo hints) lives on the structured refs — no parallel prose format.
    """
    from pflow.runtime.engine.template_errors import classify_unresolved_references

    structured_refs = classify_unresolved_references(normalized, shared_storage)
    available_keys = sorted(k for k in shared_storage if not str(k).startswith("_"))

    return {
        "source_expr": source_expr,
        "unresolved_references": structured_refs,
        "template": normalized,
        "available_context_keys": available_keys,
    }


def _is_all_absent_coalesce(normalized: str, shared_storage: dict[str, Any]) -> bool:
    """True if every operand of a coalesce expression is ABSENT.

    All-absent coalesce is the legitimate Task 128 branch-convergence fallthrough —
    the user explicitly opted into "skip this output if none of the operands ran"
    semantics via ``??``. This must be silently skipped.

    Any FAILED or PATH_ERROR operand (node executed and failed, or succeeded with a
    typo) is NOT a legitimate fallthrough — those are real errors the user needs
    to see. Returns False so the caller records a failure.

    Non-coalesce templates always return False (caller records a failure).
    """
    inner = TemplateResolver.extract_simple_template_var(normalized)
    if not (inner and TemplateResolver.is_coalesce_expression(inner)):
        return False

    from pflow.runtime.engine.template_errors import classify_unresolved_references

    refs = classify_unresolved_references(normalized, shared_storage)
    return bool(refs) and all(ref.get("status") == "absent" for ref in refs)


def _record_output_failure(
    output_name: str,
    output_config: dict[str, Any],
    source_expr: str,
    normalized: str,
    shared_storage: dict[str, Any],
) -> dict[str, Any]:
    """Build an OutputResolutionError failure entry with source-file context."""
    failure = _diagnose_unresolved_output(source_expr, normalized, shared_storage)
    failure["output_name"] = output_name
    if "_source_line" in output_config:
        failure["source_line"] = output_config["_source_line"]
    source_file = shared_storage.get("_pflow_workflow_file")
    if source_file:
        failure["source_file"] = source_file
    return failure


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

        # Unresolved — silently skip only if this is a legitimate all-absent
        # coalesce (Task 128 branch-convergence). Any FAILED / PATH_ERROR operand
        # falls through to error recording so the agent sees the actual failure.
        if _is_all_absent_coalesce(normalized, shared_storage):
            continue

        failures.append(_record_output_failure(output_name, output_config, source_expr, normalized, shared_storage))

    if failures:
        from pflow.core.user_errors import OutputResolutionError

        raise OutputResolutionError(failures=failures)
