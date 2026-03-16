"""Batch item field validation (Pass 8).

Validates ${item.field} references against inferred item structure.
When batch items come from an upstream node's results array, checks
that referenced fields actually exist on each item.
"""

from typing import Any, Optional

from pflow.runtime.template_resolver import TemplateResolver
from pflow.runtime.template_validation.path_validation import validate_nested_path
from pflow.runtime.template_validation.utils import (
    find_similar_paths,
    sanitize_for_display,
)


def validate_batch_item_fields(
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
) -> list[str]:
    """Validate ${item.field} references against inferred item structure.

    For batch nodes where items come from an upstream batch node's results,
    validates that referenced fields actually exist on each item.

    Falls back to permissive (no validation) when item structure cannot
    be inferred (e.g., items from workflow input, inline array, or
    non-batch source).
    """
    errors: list[str] = []

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

        field_refs = _extract_item_field_refs(node.get("params", {}), item_alias)

        seen_errors: set[str] = set()  # Mutated by _check_batch_item_ref to dedup
        for field_path, full_template in field_refs:
            error = _check_batch_item_ref(
                field_path, full_template, item_structure, item_alias, items_template, node_id, seen_errors
            )
            if error:
                errors.append(error)

    return errors


def _infer_batch_item_structure(
    items_template: Any,
    node_outputs: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Infer the structure of batch items from the items template.

    When items: ${upstream.results}, looks up the upstream node's results
    output and extracts the per-item structure (inner node outputs + 'item').

    Returns:
        Dict mapping field names to type info, or None if structure cannot be inferred.
    """
    if not isinstance(items_template, str):
        return None

    # Extract template references preserving left-to-right ?? order.
    # extract_variables() returns a set (loses order), so we parse directly.
    matches = TemplateResolver.TEMPLATE_PATTERN.findall(items_template)
    if not matches:
        return None

    operands: list[str] = []
    for match in matches:
        operands.extend(TemplateResolver.split_coalesce_operands(match))

    for operand in operands:
        source_output = node_outputs.get(operand)
        if source_output and isinstance(source_output, dict):
            items_info = source_output.get("items")
            if isinstance(items_info, dict) and "structure" in items_info:
                structure = items_info["structure"]
                if isinstance(structure, dict):
                    return structure

    return None


def _collect_templates_from_value(
    value: Any,
) -> set[str]:
    """Recursively collect template variables from a parameter value."""
    templates: set[str] = set()
    if isinstance(value, str) and TemplateResolver.has_templates(value):
        templates.update(TemplateResolver.extract_variables(value))
    elif isinstance(value, dict):
        for val in value.values():
            templates.update(_collect_templates_from_value(val))
    elif isinstance(value, list):
        for list_item in value:
            templates.update(_collect_templates_from_value(list_item))
    return templates


def _extract_item_field_refs(
    params: dict[str, Any],
    item_alias: str,
) -> list[tuple[str, str]]:
    """Extract ${item.field} references from a node's params.

    Returns:
        List of (field_path, full_template) tuples.
        field_path is everything after the alias (e.g., "response" from "item.response").
    """
    prefix = f"{item_alias}."
    refs: list[tuple[str, str]] = []

    for param_value in params.values():
        for template in _collect_templates_from_value(param_value):
            if template.startswith(prefix):
                field_path = template[len(prefix) :]
                if field_path:
                    refs.append((field_path, template))

    return refs


def _check_batch_item_ref(
    field_path: str,
    full_template: str,
    item_structure: dict[str, Any],
    item_alias: str,
    items_template: Any,
    node_id: str,
    seen_errors: set[str],
) -> Optional[str]:
    """Check a single ${item.field} reference against item structure. Returns error or None."""
    parts = field_path.split(".")
    first_field = parts[0].split("[")[0]

    if first_field not in item_structure:
        if first_field in seen_errors:
            return None
        seen_errors.add(first_field)
        return _format_batch_item_field_error(
            node_id, item_alias, items_template, first_field, full_template, item_structure
        )

    # First field exists — validate deeper path if any
    if len(parts) > 1:
        field_info = item_structure[first_field]
        if isinstance(field_info, dict):
            is_valid, _ = validate_nested_path(parts[1:], field_info, f"${{{full_template}}}", item_alias)
            if not is_valid and full_template not in seen_errors:
                seen_errors.add(full_template)
                return _format_batch_item_nested_error(node_id, item_alias, parts, full_template, field_info)

    return None


def _format_batch_item_field_error(
    node_id: str,
    item_alias: str,
    items_template: Any,
    first_field: str,
    full_template: str,
    item_structure: dict[str, Any],
) -> str:
    """Format error message for invalid batch item field access."""
    safe_node_id = sanitize_for_display(node_id)
    safe_alias = sanitize_for_display(item_alias)
    items_source = items_template if isinstance(items_template, str) else str(items_template)
    safe_source = sanitize_for_display(items_source)

    available_paths = [
        (f"{safe_alias}.{field}", info.get("type", "any") if isinstance(info, dict) else "any")
        for field, info in item_structure.items()
    ]
    suggestions = find_similar_paths(first_field, available_paths)

    lines = [
        f"Node '{safe_node_id}': ${{{full_template}}} references "
        f"field '{first_field}' which is not available on batch items.",
        "",
        f"Items come from: {safe_source}",
        f"Available fields on ${{{safe_alias}}}:",
    ]

    for field_name, field_info in item_structure.items():
        field_type = field_info.get("type", "any") if isinstance(field_info, dict) else "any"
        lines.append(f"  ${{{safe_alias}.{field_name}}} ({field_type})")

    if suggestions:
        lines.append("")
        if len(suggestions) == 1:
            sugg_path, _ = suggestions[0]
            lines.append(f"Did you mean: ${{{sugg_path}}}?")
        else:
            lines.append("Did you mean one of these?")
            for sugg_path, _ in suggestions:
                lines.append(f"  - ${{{sugg_path}}}")

    return "\n".join(lines)


def _format_batch_item_nested_error(
    node_id: str,
    item_alias: str,
    parts: list[str],
    full_template: str,
    field_info: dict[str, Any],
) -> str:
    """Format error for invalid nested path on a batch item field.

    Example: ${item.llm_usage.nope} where llm_usage has known structure.
    """
    safe_node_id = sanitize_for_display(node_id)
    safe_alias = sanitize_for_display(item_alias)

    # Walk through intermediate parts to find where validation actually fails.
    # For ${item.a.b.c} where c doesn't exist on b, we need to identify b as
    # the parent — not a — so the error message and available fields are correct.
    current_info = field_info
    valid_depth = 0
    for part in parts[1:-1]:
        sub = current_info.get("structure", {}) if isinstance(current_info, dict) else {}
        if part in sub and isinstance(sub[part], dict):
            current_info = sub[part]
            valid_depth += 1
        else:
            break

    parent_path = f"{safe_alias}.{'.'.join(parts[: 1 + valid_depth])}"
    bad_field = parts[1 + valid_depth].split("[")[0]
    parent_name = parts[valid_depth]
    parent_type = current_info.get("type", "any") if isinstance(current_info, dict) else "any"
    nested_structure = current_info.get("structure", {}) if isinstance(current_info, dict) else {}

    lines = [
        f"Node '{safe_node_id}': ${{{full_template}}} \u2014 "
        f"'{bad_field}' does not exist on '{parent_name}' ({parent_type}).",
    ]

    if nested_structure:
        lines.append("")
        lines.append(f"Available fields on ${{{parent_path}}}:")
        for field_name, sub_info in nested_structure.items():
            sub_type = sub_info.get("type", "any") if isinstance(sub_info, dict) else "any"
            lines.append(f"  ${{{parent_path}.{field_name}}} ({sub_type})")

        available_paths = [
            (f"{parent_path}.{f}", i.get("type", "any") if isinstance(i, dict) else "any")
            for f, i in nested_structure.items()
        ]
        suggestions = find_similar_paths(bad_field, available_paths)
        if suggestions:
            lines.append("")
            if len(suggestions) == 1:
                sugg_path, _ = suggestions[0]
                lines.append(f"Did you mean: ${{{sugg_path}}}?")
            else:
                lines.append("Did you mean one of these?")
                for sugg_path, _ in suggestions:
                    lines.append(f"  - ${{{sugg_path}}}")
    else:
        lines.append("")
        lines.append(
            f"'{parent_name}' has type '{parent_type}' with no known sub-fields. Nested access may fail at runtime."
        )

    return "\n".join(lines)
