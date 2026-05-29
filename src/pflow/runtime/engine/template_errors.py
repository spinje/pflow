"""Template error message formatting.

Builds detailed, actionable error messages for template resolution failures:
- Type mismatches (dict/list where str expected, malformed JSON)
- Unresolved template variables, producing a structured Diagnostic with
  per-reference status (absent / failed / path_error)
- Coalesce expression diagnostics

The unresolved-template path produces a Diagnostic whose context contains
structured ``unresolved_references`` data. The Diagnostic context blocks
in ``core/diagnostic.py`` render this into the agent-actionable format.
"""

from __future__ import annotations

from typing import Any

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.runtime.node_state import NodeStatus, get_node_failure, get_node_status
from pflow.runtime.template_resolver import TemplateResolver


def build_type_error_message(
    param_key: str,
    resolved_value: Any,
    template_str: str,
    expected_type: str,
    actual_type: str,
) -> str:
    """Build detailed, actionable error message for type mismatch.

    Returns a plain string used in a ValueError. Type mismatch errors are
    a different class from unresolved-template errors and don't need the
    structured Diagnostic treatment.
    """
    var_match = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.search(template_str)
    var_name = var_match.group(1) if var_match else "variable"

    error_msg = (
        f"Parameter '{param_key}' expects {expected_type} but received {actual_type}\n\n"
        f"Template used: {template_str}\n"
        f"Resolved to: {actual_type} object\n"
    )
    error_msg += "\n\U0001f4a1 Common fixes:\n"
    error_msg += "  1. Serialize to JSON (recommended):\n"
    error_msg += f'     {param_key}: "{template_str}"\n\n'
    if isinstance(resolved_value, dict):
        error_msg += "  2. Access a specific field:\n"
        error_msg += f"     {param_key}: ${{{var_name}.field_name}}\n\n"
    elif isinstance(resolved_value, list):
        error_msg += "  2. Access a specific item:\n"
        error_msg += f"     {param_key}: ${{{var_name}[0]}}\n\n"
    error_msg += "  3. Combine with text:\n"
    error_msg += f'     {param_key}: "Summary: {template_str}"\n'

    if isinstance(resolved_value, dict) and resolved_value:
        keys = list(resolved_value.keys())[:10]
        error_msg += f"\n\nAvailable fields in {var_name}:\n"
        for key in keys:
            error_msg += f"  - {key}\n"
        if len(resolved_value) > 10:
            remaining = len(resolved_value) - 10
            error_msg += f"  ... and {remaining} more\n"
    elif isinstance(resolved_value, list):
        error_msg += f"\n\n{var_name} contains {len(resolved_value)} items\n"
        if len(resolved_value) > 0:
            error_msg += f"Access items with: ${{{var_name}[0]}}, ${{{var_name}[1]}}, etc.\n"

    return error_msg


def build_json_parse_error_message(
    param_key: str,
    resolved_value: str,
    template_str: str,
    expected_type: str,
    trimmed: str,
) -> str:
    """Build detailed error message for failed JSON parsing.

    Same plain-string approach as build_type_error_message. JSON parse
    errors are a different class from unresolved-template errors.
    """
    preview = trimmed[:200]
    if len(trimmed) > 200:
        preview += "..."

    issues = []
    if "'" in trimmed:
        issues.append("Single quotes detected (use double quotes: \"key\" not 'key')")
    if trimmed.count("{") != trimmed.count("}"):
        issues.append("Mismatched braces { }")
    if trimmed.count("[") != trimmed.count("]"):
        issues.append("Mismatched brackets [ ]")
    if ",}" in trimmed or ",]" in trimmed:
        issues.append("Trailing comma before closing brace/bracket")

    error_lines = [
        f"Parameter '{param_key}' expects {expected_type} but received malformed JSON string.",
        "",
        f"Template: {template_str}",
        f"Value preview: {preview}",
        "",
        f"The string starts with '{trimmed[0]}' suggesting JSON, but failed to parse.",
    ]
    if issues:
        error_lines.append("")
        error_lines.append("Detected issues:")
        for issue in issues:
            error_lines.append(f"  - {issue}")
    error_lines.extend([
        "",
        "Common JSON formatting issues:",
        "  - Missing closing brace/bracket",
        "  - Single quotes instead of double quotes",
        "  - Trailing commas in arrays/objects",
        "  - Unescaped special characters",
        "  - Missing quotes around object keys",
        "",
        "Fix: Ensure the source outputs valid JSON.",
        f"Test with: echo '{template_str}' | jq '.'",
    ])
    return "\n".join(error_lines)


def classify_unresolved_references(
    template_str: str,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Classify every variable reference in a template by execution status.

    Variables that resolve successfully are not included.
    """
    references: list[dict[str, Any]] = []
    seen_vars: set[str] = set()

    for match in TemplateResolver.TEMPLATE_PATTERN.finditer(template_str):
        expr = match.group(1)
        operands = TemplateResolver.split_coalesce_operands(expr)
        is_coalesce = len(operands) > 1

        for operand in operands:
            # Literal operands (Optional A) always resolve — never unresolved.
            # Without this, a literal like `0` leaks into "Node '0' did not
            # execute" errors with bogus peer suggestions.
            if TemplateResolver.is_literal_operand(operand):
                continue
            if operand in seen_vars:
                continue
            seen_vars.add(operand)

            ref = _classify_one_reference(
                operand,
                context,
                in_coalesce=is_coalesce,
                coalesce_expr=expr if is_coalesce else None,
            )
            if ref is not None:
                references.append(ref)

    return references


def _classify_one_reference(
    var: str,
    context: dict[str, Any],
    *,
    in_coalesce: bool,
    coalesce_expr: str | None,
) -> dict[str, Any] | None:
    """Classify a single variable reference. Returns None if it resolves."""
    root = TemplateResolver.extract_root_node_id(var)
    status = get_node_status(context, root)

    if status == NodeStatus.SUCCEEDED:
        if TemplateResolver.variable_exists(var, context):
            return None
        return {
            "var": var,
            "root": root,
            "status": "path_error",
            "in_coalesce": in_coalesce,
            "coalesce_expr": coalesce_expr,
            "available_fields": _get_available_fields(root, context),
            "did_you_mean": _suggest_field_correction(var, root, context),
            "peer_suggestions": _find_peer_nodes_with_field(root, var, context),
        }

    if status == NodeStatus.FAILED:
        failure = get_node_failure(context, root) or {}
        data = failure.get("data") or {}
        display_data = _extract_failure_display_data(failure.get("category"), data)
        secondary_hint = _suggest_field_correction(var, root, {root: data}) if isinstance(data, dict) else None
        # When the user also has a typo (e.g. ${primary.stddout} where primary
        # failed and has `stdout`), prefer the corrected path for peer search
        # and the paste-able fix template. The original typo'd var stays on
        # ``var`` so the renderer shows what the user actually wrote.
        search_var = secondary_hint if secondary_hint else var
        failure_context = {
            "category": failure.get("category"),
            "error": failure.get("error"),
            "data": display_data,
            **display_data,
        }
        return {
            "var": var,
            "root": root,
            "status": "failed",
            "in_coalesce": in_coalesce,
            "coalesce_expr": coalesce_expr,
            "failure": failure_context,
            "peer_suggestions": _find_peer_nodes_with_field(root, search_var, context),
            "secondary_hint": secondary_hint,
            "corrected_var": secondary_hint,
        }

    return {
        "var": var,
        "root": root,
        "status": "absent",
        "in_coalesce": in_coalesce,
        "coalesce_expr": coalesce_expr,
        "peer_suggestions": _find_peer_nodes_with_field(root, var, context),
    }


def _get_available_fields(node_id: str, context: dict[str, Any]) -> list[str]:
    """Return the dict keys of a node's output, sorted."""
    output = context.get(node_id)
    if isinstance(output, dict):
        return sorted(str(key) for key in output if not str(key).startswith("_"))
    return []


def _is_visible_context_key(key: Any) -> bool:
    """Return True for user-relevant context keys shown in diagnostics."""
    return not str(key).startswith("_")


def _find_peer_nodes_with_field(root: str, var: str, context: dict[str, Any], max_results: int = 3) -> list[str]:
    """Find sibling nodes whose output dict contains the same field path."""
    field_name = TemplateResolver.extract_first_field_segment(var)

    candidates: list[str] = []
    for key, value in context.items():
        if key == root:
            continue
        key_str = str(key)
        if not _is_visible_context_key(key_str):
            continue
        if field_name is None:
            if isinstance(value, dict):
                candidates.append(key_str)
        elif isinstance(value, dict) and field_name in value:
            candidates.append(key_str)
        if len(candidates) >= max_results:
            break
    return candidates


_SHELL_DISPLAY_FIELDS = ("exit_code", "command", "stdout", "stderr")
_HTTP_DISPLAY_FIELDS = (
    "status_code",
    "url",
    "method",
    "response",
    "response_body",
    "response_headers",
)
_MCP_DISPLAY_FIELDS = ("server", "tool", "error_details", "result")


def _extract_failure_display_data(category: str | None, data: Any) -> dict[str, Any]:
    """Extract a display-relevant subset of failure data by category.

    Dispatches purely on the category string (set authoritatively at the
    failure site by ``mark_node_failed``) rather than sniffing data-key
    presence. A success output that happens to contain ``status_code``
    can no longer be misclassified as an HTTP failure.
    """
    if not isinstance(data, dict):
        return {}

    if category == "shell_failure":
        return {key: data[key] for key in _SHELL_DISPLAY_FIELDS if data.get(key) is not None}

    if category == "http_failure":
        return {key: data[key] for key in _HTTP_DISPLAY_FIELDS if data.get(key) is not None}

    if category == "mcp_failure":
        return {key: data[key] for key in _MCP_DISPLAY_FIELDS if data.get(key) is not None}

    # Generic fallback: surface scalar fields only. The 500-char cap keeps
    # runaway stderr or binary blobs out of the structured failure payload.
    return {
        key: value
        for key, value in data.items()
        if not str(key).startswith("_") and isinstance(value, (str, int, float, bool)) and len(str(value)) < 500
    }


def _suggest_field_correction(var: str, root: str, context: dict[str, Any]) -> str | None:
    """Suggest a field name correction using close-string matching."""
    output = context.get(root)
    if not isinstance(output, dict):
        return None
    field_name = TemplateResolver.extract_first_field_segment(var)
    if field_name is None:
        return None
    available = list(output.keys())
    if field_name in available:
        return None

    import difflib

    matches = difflib.get_close_matches(field_name, [str(key) for key in available], n=1, cutoff=0.6)
    if not matches:
        return None
    # Rebuild the full path replacing only the first field segment.
    field_path = var.split(".", 1)[1]
    corrected_path = field_path.replace(field_name, matches[0], 1)
    return f"{root}.{corrected_path}"


def build_template_error_diagnostic(
    param_key: str,
    template: Any,
    context: dict[str, Any],
    *,
    node_id: str | None = None,
    source_file: str | None = None,
    source_line: int | None = None,
) -> Diagnostic:
    """Build a fully-structured Diagnostic for an unresolved template."""
    template_str = str(template)
    references = classify_unresolved_references(template_str, context)

    available_keys = sorted(key for key in context if _is_visible_context_key(key))
    failures = context.get("__failures__")
    failed_keys: list[str] = sorted(str(k) for k in failures) if isinstance(failures, dict) else []

    if references:
        ref_summary = ", ".join(f"${{{ref['var']}}}" for ref in references[:3])
        if len(references) > 3:
            ref_summary += f" (+{len(references) - 3} more)"
        message = f"Unresolved variables in parameter '{param_key}': {ref_summary}"
    else:
        message = f"Unresolved template in parameter '{param_key}'"

    # Node-param errors render through a single synthesized output_failures
    # entry with kind="param" — same iteration path as single/multi-output
    # resolution errors. source_file/source_line stay at top-level so
    # _format_location can render the universal `At:` line above the block.
    context_dict: dict[str, Any] = {
        "category": "template_error",
        "param_key": param_key,
        "template": template_str,
        "unresolved_references": references,
        "available_context_keys": available_keys,
        "failed_context_keys": failed_keys,
        "output_failures": [
            {
                "kind": "param",
                "output_name": param_key,
                "template": template_str,
                "unresolved_references": references,
            }
        ],
    }
    if source_file is not None:
        context_dict["source_file"] = source_file
    if source_line is not None:
        context_dict["source_line"] = source_line

    return Diagnostic(
        severity=Severity.ERROR,
        message=message,
        title="Template Resolution Failed",
        node_id=node_id,
        source="runtime",
        context=context_dict,
    )
