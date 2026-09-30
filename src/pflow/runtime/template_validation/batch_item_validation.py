"""Batch item field validation (Pass 8).

Validates ${item.field} references against inferred item structure.
When batch items come from an upstream node's results array, checks
that referenced fields actually exist on each item.
"""

from collections import defaultdict
from typing import Any

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.templates import Field, Reference, parse
from pflow.runtime.template_validation.operands import OperandPolicy, TemplateOperand
from pflow.runtime.template_validation.path_validation import validate_nested_path
from pflow.runtime.template_validation.utils import (
    dotted_parts,
    find_similar_paths,
    sanitize_for_display,
)


def validate_batch_item_fields(
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
    operands: list[TemplateOperand],
) -> list[Diagnostic]:
    """Validate ${item.field} references against inferred item structure.

    For batch nodes where items come from an upstream batch node's results,
    validates that referenced fields actually exist on each item. Only the
    node's own ``FIELD_CHECK`` references are checked — a ``??`` operand may
    miss the field at runtime (#441), and another batch node may share the alias.

    Falls back to permissive (no validation) when item structure cannot
    be inferred (e.g., items from workflow input, inline array, or
    non-batch source).
    """
    diagnostics: list[Diagnostic] = []
    field_checked: defaultdict[str | None, list[Reference]] = defaultdict(list)
    for operand in operands:
        if operand.policy is OperandPolicy.FIELD_CHECK:
            field_checked[operand.node_id].append(operand.ref)

    for node in workflow_ir.get("nodes", []):
        node_id = node.get("id")
        batch_config = node.get("batch")
        if not batch_config or not node_id:
            continue

        item_alias = batch_config.get("as", "item")
        items_template = batch_config.get("items")
        if not items_template:
            continue

        item_structure = _infer_batch_item_structure(items_template, node_outputs)
        if not item_structure:
            continue

        seen_errors: set[str] = set()  # Mutated by _check_batch_item_ref to dedup
        for ref in field_checked[node_id]:
            if ref.root != item_alias or not ref.path or not isinstance(ref.path[0], Field):
                continue
            error = _check_batch_item_ref(ref, item_structure, item_alias, items_template, node_id, seen_errors)
            if error:
                diagnostics.append(error)

    return diagnostics


def _infer_batch_item_structure(
    items_template: Any,
    node_outputs: dict[str, Any],
) -> dict[str, Any] | None:
    """Infer the structure of batch items from the items template.

    When items: ${upstream.results}, looks up the upstream node's results
    output and extracts the per-item structure (inner node outputs + 'item').
    The first operand (left to right across ``??``) with a known item
    structure wins.

    Returns:
        Dict mapping field names to type info, or None if structure cannot be inferred.
    """
    if not isinstance(items_template, str):
        return None

    for expression in parse(items_template).expressions:
        for operand in expression.operands:
            if not isinstance(operand, Reference):
                continue
            source_output = node_outputs.get(operand.raw)
            if source_output and isinstance(source_output, dict):
                items_info = source_output.get("items")
                if isinstance(items_info, dict) and "structure" in items_info:
                    structure = items_info["structure"]
                    if isinstance(structure, dict):
                        return structure

    return None


def _check_batch_item_ref(
    ref: Reference,
    item_structure: dict[str, Any],
    item_alias: str,
    items_template: Any,
    node_id: str,
    seen_errors: set[str],
) -> Diagnostic | None:
    """Check a single ${item.field} reference against item structure."""
    first = ref.path[0]
    assert isinstance(first, Field)  # noqa: S101 — the caller selects `${alias.field…}` references
    first_field = first.name

    if first_field not in item_structure:
        if first_field in seen_errors:
            return None
        seen_errors.add(first_field)
        return _build_batch_item_field_diagnostic(
            node_id, item_alias, items_template, first_field, ref.raw, item_structure
        )

    # First field exists — validate deeper fields if any
    field_info = item_structure[first_field]
    if sum(isinstance(segment, Field) for segment in ref.path) > 1 and isinstance(field_info, dict):
        is_valid, _ = validate_nested_path(ref.path[1:], field_info, f"${{{ref.raw}}}", item_alias)
        if not is_valid and ref.raw not in seen_errors:
            seen_errors.add(ref.raw)
            return _build_batch_item_nested_diagnostic(node_id, item_alias, ref, field_info)

    return None


def _build_batch_item_field_diagnostic(
    node_id: str,
    item_alias: str,
    items_template: Any,
    first_field: str,
    full_template: str,
    item_structure: dict[str, Any],
) -> Diagnostic:
    """Build diagnostic for invalid batch item field access."""
    safe_node_id = sanitize_for_display(node_id)
    safe_alias = sanitize_for_display(item_alias)
    items_source = items_template if isinstance(items_template, str) else str(items_template)
    safe_source = sanitize_for_display(items_source)

    available_fields: list[str] = []
    for field_name, field_info in item_structure.items():
        field_type = field_info.get("type", "any") if isinstance(field_info, dict) else "any"
        available_fields.append(f"${{{safe_alias}.{field_name}}} ({field_type})")

    available_paths = [
        (f"{safe_alias}.{field}", info.get("type", "any") if isinstance(info, dict) else "any")
        for field, info in item_structure.items()
    ]
    similar = find_similar_paths(first_field, available_paths)

    context: dict[str, Any] = {
        "category": "template_error",
        "template": f"${{{full_template}}}",
        "available_fields": available_fields,
        "available_fields_total": len(available_fields),
        "available_fields_label": "batch item fields",
        "items_source": safe_source,
        "batch_alias": safe_alias,
    }
    if similar:
        context["similar_names"] = [f"${{{path}}}" for path, _ in similar]

    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Template Error",
        node_id=node_id,
        message=(
            f"Node '{safe_node_id}': ${{{full_template}}} references field '{first_field}' "
            f"which is not available on batch items (items come from: {safe_source})."
        ),
        suggestions=[f"Use ${{{path}}}" for path, _ in similar] if similar else None,
        context=context,
        see_also=["batch"],
    )


def _build_batch_item_nested_diagnostic(
    node_id: str,
    item_alias: str,
    ref: Reference,
    field_info: dict[str, Any],
) -> Diagnostic:
    """Build diagnostic for invalid nested path on a batch item field.

    Example: ${item.llm_usage.nope} where llm_usage has known structure.
    """
    full_template = ref.raw
    safe_node_id = sanitize_for_display(node_id)
    safe_alias = sanitize_for_display(item_alias)
    # Per dotted part after the alias: its field name, and its display text (index included)
    parts = dotted_parts(ref)[1:]
    names = [segment.name for segment in ref.path if isinstance(segment, Field)]

    # Walk through intermediate parts to find where validation actually fails.
    # For ${item.a.b.c} where c doesn't exist on b, we need to identify b as
    # the parent — not a — so the error message and available fields are correct.
    current_info = field_info
    valid_depth = 0
    for name in names[1:-1]:
        sub = current_info.get("structure", {}) if isinstance(current_info, dict) else {}
        if name in sub and isinstance(sub[name], dict):
            current_info = sub[name]
            valid_depth += 1
        else:
            break

    parent_path = f"{safe_alias}.{'.'.join(parts[: 1 + valid_depth])}"
    bad_field = names[1 + valid_depth]
    parent_name = parts[valid_depth]
    parent_type = current_info.get("type", "any") if isinstance(current_info, dict) else "any"
    nested_structure = current_info.get("structure", {}) if isinstance(current_info, dict) else {}

    available_fields: list[str] = []
    similar: list[tuple[str, str]] = []
    if nested_structure:
        for field_name, sub_info in nested_structure.items():
            sub_type = sub_info.get("type", "any") if isinstance(sub_info, dict) else "any"
            available_fields.append(f"${{{parent_path}.{field_name}}} ({sub_type})")

        available_paths = [
            (f"{parent_path}.{f}", i.get("type", "any") if isinstance(i, dict) else "any")
            for f, i in nested_structure.items()
        ]
        similar = find_similar_paths(bad_field, available_paths)

    if similar:
        suggestions: list[str] | None = [f"Use ${{{path}}}" for path, _ in similar]
    elif not nested_structure:
        suggestions = [f"'{parent_name}' has no known sub-fields. Nested access may fail at runtime."]
    else:
        suggestions = None

    context: dict[str, Any] = {
        "category": "template_error",
        "template": f"${{{full_template}}}",
        "parent_path": parent_path,
        "parent_type": parent_type,
    }
    if available_fields:
        context["available_fields"] = available_fields
        context["available_fields_total"] = len(available_fields)
        context["available_fields_label"] = "nested fields"
    if similar:
        context["similar_names"] = [f"${{{path}}}" for path, _ in similar]

    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Template Error",
        node_id=node_id,
        message=(
            f"Node '{safe_node_id}': ${{{full_template}}} — '{bad_field}' does not exist on "
            f"'{parent_name}' ({parent_type})."
        ),
        suggestions=suggestions,
        context=context,
        see_also=["batch"],
    )
