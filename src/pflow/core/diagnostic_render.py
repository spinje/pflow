"""Text rendering for Diagnostic objects."""

from __future__ import annotations

from typing import Any

from pflow.core.diagnostic import (
    CACHE_ADVISORY_CATEGORY,
    CACHE_FAILURE_CATEGORY,
    CACHE_WARNING_CATEGORY,
    CATEGORY_TITLES,
    Diagnostic,
    Severity,
)

_CACHE_CATEGORIES: frozenset[str] = frozenset({CACHE_FAILURE_CATEGORY, CACHE_WARNING_CATEGORY, CACHE_ADVISORY_CATEGORY})

# Context keys surfaced inline on cache warning/advisory diagnostics. These match
# the catalog payload keys emitted by ``cache_analysis`` (Task 159 F1) — the
# closed list of fields agents read to make remediation decisions.
_CACHE_INLINE_CONTEXT_KEYS: tuple[str, ...] = (
    "savings_pct",
    "savings_usd",
    "batch_size",
    "prefix_tokens_estimated",
    "target_file",
)


def format_diagnostic(
    diagnostic: Diagnostic,
    verbose: bool = False,
    error_number: int | None = None,
) -> str:
    """Render one diagnostic to text."""
    if diagnostic.severity == Severity.ERROR:
        return _format_error_diagnostic(
            diagnostic,
            verbose=verbose,
            error_number=error_number,
        )
    return _format_warning_or_info_diagnostic(diagnostic)


def _format_warning_or_info_diagnostic(diagnostic: Diagnostic) -> str:
    """Render one WARNING or INFO diagnostic.

    Most warnings are compact one-liners (cache_lint, api warnings, etc.). The
    exception is a WARNING-severity template_error carrying structured
    ``unresolved_references`` — that's permissive-mode template resolution
    surfacing the same rich data the strict-mode error path shows. Rendering
    it as a one-liner would silently drop per-ref details, peer suggestions,
    and paste-able fix hints — the whole point of permissive mode's
    pass-through in ``runner._extract_runtime_warnings``. So for template
    errors specifically, we fall through to the structured renderer.

    Cache-namespaced diagnostics (Task 159 DD#27) prefix the stable ``id``
    inline (e.g. ``[cache.batch-prewarm-recommended]``) and surface a
    closed list of structured context keys (savings_pct, savings_usd,
    batch_size, prefix_tokens_estimated, target_file) so agents reading
    text output can route on the warning ID without parsing JSON.
    """
    context = diagnostic.context or {}
    if context.get("category") == "template_error" and context.get("unresolved_references"):
        return _format_warning_template_error(diagnostic, context)

    if context.get("category") in _CACHE_CATEGORIES:
        return _format_cache_warning_or_advisory(diagnostic, context)

    icon = "⚠" if diagnostic.severity == Severity.WARNING else "\N{INFORMATION SOURCE}"
    if diagnostic.node_id:
        line = f"  {icon} [{diagnostic.node_id}] {diagnostic.message}"
    else:
        line = f"  {icon} {diagnostic.message}"
    if diagnostic.suggestions:
        for suggestion in diagnostic.suggestions:
            line += f"\n    → {suggestion}"
    return line


def _format_cache_warning_or_advisory(diagnostic: Diagnostic, context: dict[str, Any]) -> str:
    """Render a cache_warning / cache_advisory / cache_failure-as-warning diagnostic.

    Layout (one diagnostic, multi-line):
        ⚠ [cache.id] [node-id] message
            → suggestion
              savings_pct: 89
              savings_usd: 0.12

    The ``[cache.id]`` prefix is the agent-facing handle for stable warning
    routing. Inline context keys are limited to the closed list in
    ``_CACHE_INLINE_CONTEXT_KEYS`` so the renderer stays predictable as the
    catalog grows. Future catalog entries that need new context keys must
    extend this tuple deliberately.
    """
    icon = "⚠" if diagnostic.severity == Severity.WARNING else "\N{INFORMATION SOURCE}"
    id_prefix = f"[{diagnostic.id}] " if diagnostic.id else ""
    if diagnostic.node_id:
        line = f"  {icon} {id_prefix}[{diagnostic.node_id}] {diagnostic.message}"
    else:
        line = f"  {icon} {id_prefix}{diagnostic.message}"
    if diagnostic.suggestions:
        for suggestion in diagnostic.suggestions:
            line += f"\n    → {suggestion}"
    detail_lines: list[str] = []
    for key in _CACHE_INLINE_CONTEXT_KEYS:
        if key in context:
            detail_lines.append(f"      {key}: {context[key]}")
    if detail_lines:
        line += "\n" + "\n".join(detail_lines)
    return line


def _format_warning_template_error(diagnostic: Diagnostic, context: dict[str, Any]) -> str:
    """Render a template_error warning with the same structured block as errors.

    Uses the same context-block renderer as the error path so permissive-mode
    template errors don't silently drop per-ref details, peer suggestions, and
    paste-able fix hints. Keeps the warning icon + node_id header so it's
    visually distinct from a hard error.
    """
    icon = "⚠"
    if diagnostic.node_id:
        header = f"  {icon} [{diagnostic.node_id}] {diagnostic.message}"
    else:
        header = f"  {icon} {diagnostic.message}"

    lines = [header]
    location = _format_location(diagnostic, context)
    if location:
        lines.append(f"  At: {location}")
    lines.extend(_format_template_error_lines(context))
    return "\n".join(lines)


def _format_error_diagnostic(
    diagnostic: Diagnostic,
    verbose: bool,
    error_number: int | None = None,
) -> str:
    """Render one ERROR diagnostic in the unified titled format."""
    lines: list[str] = []
    context = diagnostic.context or {}

    # 1. Title line — agent-routing handle. The stable warning ``id``, when
    # present, appears in brackets next to the title so text-mode consumers
    # can grep on the id without parsing JSON. Diagnostics without an ``id``
    # (every pflow diagnostic pre-Task-159) render unchanged.
    title = diagnostic.title or CATEGORY_TITLES.get(context.get("category", ""), "Error")
    prefix = f"Error {error_number}" if error_number is not None else "Error"
    if diagnostic.id:
        lines.append(f"{prefix}: {title} [{diagnostic.id}]")
    else:
        lines.append(f"{prefix}: {title}")
    lines.append("")

    # 2. Message
    lines.append(diagnostic.message)

    # 3. Location (At:)
    location = _format_location(diagnostic, context)
    if location:
        lines.append(f"  At: {location}")

    # 4. Context blocks (universal — called for ALL error types)
    context_lines = _format_all_context_blocks(diagnostic, context)
    if context_lines:
        lines.extend(context_lines)

    # 5. Suggestions
    suggestions = diagnostic.suggestions or []
    if suggestions:
        lines.append("")
        if len(suggestions) == 1:
            lines.append(f"  → {suggestions[0]}")
        else:
            lines.append("To fix this:")
            for i, s in enumerate(suggestions, 1):
                lines.append(f"  {i}. {s}")

    # 6. See also (guide topic pointer for rule-class errors)
    if diagnostic.see_also:
        lines.append("")
        lines.append(f"See also: pflow guide {' '.join(diagnostic.see_also)}")

    # 7. Verbose hint
    technical_details = context.get("technical_details")
    if verbose and technical_details:
        lines.append("")
        lines.append("Technical details:")
        lines.append(str(technical_details))
    elif technical_details:
        lines.append("")
        lines.append("Run with --verbose for technical details.")

    return "\n".join(lines)


def _format_location(diagnostic: Diagnostic, context: dict[str, Any]) -> str | None:
    """Build the ``At:`` location line from node_id, path, and line.

    File + line pairs render as ``path:line`` (editor-clickable, universal
    convention). File without a line renders as ``path``. Line without a
    file renders as ``line N``.
    """
    parts: list[str] = []
    if diagnostic.node_id:
        parts.append(f"node '{diagnostic.node_id}'")
    path = context.get("path") or context.get("source_file")
    line = context.get("line")
    if line is None:
        line = context.get("source_line")

    if path and path != "root":
        if line is not None:
            parts.append(f"{path}:{line}")
        else:
            parts.append(str(path))
    elif line is not None:
        parts.append(f"line {line}")

    return ", ".join(parts) if parts else None


def _format_all_context_blocks(diagnostic: Diagnostic, context: dict[str, Any]) -> list[str]:
    """Render all context blocks for any error type."""
    lines: list[str] = []
    lines.extend(_format_compilation_context_lines(context))
    lines.extend(_format_similar_names_block(context))
    lines.extend(_format_exception_type_line(context))

    if (raw := context.get("raw_response")) and isinstance(raw, dict):
        lines.extend(_format_api_response_lines(raw))

    if (mcp_error := context.get("mcp_error")) and isinstance(mcp_error, dict):
        lines.extend(_format_mcp_error_lines(mcp_error))

    lines.extend(_format_available_fields_block(context))

    if context.get("category") == "template_error":
        lines.extend(_format_template_error_lines(context))

    if "shell_command" in context:
        lines.extend(_format_shell_error_lines(context))

    return lines


def _format_compilation_context_lines(context: dict[str, Any]) -> list[str]:
    """Render compilation-specific context fields."""
    lines: list[str] = []
    if phase := context.get("phase"):
        lines.append(f"  Phase: {phase}")
    if node_type := context.get("node_type"):
        lines.append(f"  Node type: {node_type}")
    if sub_path := context.get("sub_workflow_path"):
        lines.append(f"  Sub-workflow: {sub_path}")
    if source_file := context.get("source_file"):
        lines.append(f"  Loaded from file: {source_file}")
    return lines


def _format_similar_names_block(context: dict[str, Any]) -> list[str]:
    """Render a 'Did you mean' list from similar_names context."""
    similar = context.get("similar_names")
    if not similar:
        return []
    lines = ["", "Did you mean one of these?"]
    for name in similar:
        lines.append(f"  - {name}")
    return lines


def _format_exception_type_line(context: dict[str, Any]) -> list[str]:
    """Render exception type when available (for generic exceptions)."""
    if exc_type := context.get("exception_type"):
        return [f"  Type: {exc_type}"]
    return []


def _format_available_fields_block(context: dict[str, Any]) -> list[str]:
    """Render available field suggestions when provided in diagnostic context.

    Producers populate ``available_fields_label`` to describe what the list
    contains (e.g. "outputs", "nodes", "inputs", "parameters"). The fallback
    ``"fields"`` is deliberately generic so it is never technically wrong —
    producers that want accurate wording must set the label explicitly.

    Truncation policy: for small closed sets (≤10 items) show every entry —
    truncating hurts agent UX (e.g., hiding 2 of 7 canonical types forces the
    agent to guess or pivot to JSON output). For larger sets, truncate to 5
    and note how many more exist.
    """
    available = context.get("available_fields")
    if not available:
        return []

    label = context.get("available_fields_label", "fields")
    total = context.get("available_fields_total", len(available))

    # Show all entries for small closed sets; truncate only when the full list
    # would genuinely overwhelm the error output.
    show_all = len(available) <= 10
    shown_count = len(available) if show_all else 5

    lines = [
        "",
        f"  Available {label} (showing {shown_count} of {total}):",
    ]
    for field_name in available[:shown_count]:
        lines.append(f"    - {field_name}")
    if not show_all:
        lines.append(f"    ... and {len(available) - shown_count} more (in error details)")
    return lines


def _format_template_error_lines(context: dict[str, Any]) -> list[str]:
    """Render structured unresolved_references for template errors.

    Iterates ``context["output_failures"]`` uniformly — node-param,
    single-output, and multi-output cases all produce one or more
    blocks via ``_format_output_block``. Each block carries its own
    ``kind`` ("param" | "output"), template, and optional source line.
    """
    refs = context.get("unresolved_references") or []
    output_failures = context.get("output_failures") or []

    if not refs and not output_failures:
        return []

    lines: list[str] = [""]
    for block in output_failures:
        lines.extend(_format_output_block(block))

    lines.extend(_format_all_unavailable_coalesce_summary(refs))
    lines.extend(_format_context_keys_block(context))

    return lines


def _format_context_keys_block(context: dict[str, Any]) -> list[str]:
    """Render the 'Available nodes in context:' block.

    Always rendered when there are unresolved refs — agents need to see what
    nodes DO exist even when all the succeeded peers happen to be hidden. Also
    surfaces failed nodes (from ``__failures__``) marked ``(failed)`` so the
    agent can distinguish "node doesn't exist" from "node failed".
    """
    succeeded = list(context.get("available_context_keys") or [])
    failed = list(context.get("failed_context_keys") or [])

    if not succeeded and not failed:
        return [
            "  Available nodes in context:",
            "    (none — no other nodes have executed)",
        ]

    lines = ["  Available nodes in context:"]
    for key in succeeded[:20]:
        lines.append(f"    - {key}")
    for key in failed[:20]:
        lines.append(f"    - {key} (failed — see failure detail above)")
    extra = max(0, len(succeeded) - 20) + max(0, len(failed) - 20)
    if extra:
        lines.append(f"    ... and {extra} more")
    return lines


def _format_output_block(block: dict[str, Any]) -> list[str]:
    """Render one unresolved-template block.

    Used for node-param errors (``kind="param"``) and output-resolution
    errors (``kind="output"``, default). The block carries its own
    template and optional source line so the renderer is format-uniform
    across single- and multi-block cases.
    """
    name = block.get("output_name", "<unknown>")
    template = block.get("template", "")
    refs = block.get("unresolved_references") or []
    header = f"  In parameter '{name}':" if block.get("kind") == "param" else f"  In output '{name}':"
    lines = [header, f"    {template}"]
    source_line = block.get("source_line")
    source_file = block.get("source_file")
    if source_line is not None and source_file:
        lines.append(f"    (at {source_file}:{source_line})")
    elif source_line is not None:
        lines.append(f"    (at line {source_line})")
    lines.append("")
    for ref in refs:
        lines.extend(_format_one_reference(ref))
        lines.append("")
    return lines


def _format_all_unavailable_coalesce_summary(refs: list[dict[str, Any]]) -> list[str]:
    """Render the shared fix block when one coalesce expression has no usable operand.

    Fires when every operand of a single ``??`` expression is either failed or
    absent — the user's fallback chain has nothing to fall through to. The
    per-reference blocks suppress their own fix hints when ``in_coalesce=True``,
    so this summary is the only fix the agent sees.
    """
    all_in_one_unavailable_coalesce = (
        len(refs) >= 2
        and all(ref.get("in_coalesce") and ref.get("status") in ("failed", "absent") for ref in refs)
        and len({ref.get("coalesce_expr") for ref in refs}) == 1
    )
    if not all_in_one_unavailable_coalesce:
        return []

    coalesce_expr = refs[0].get("coalesce_expr") or ""
    peer_pool: list[str] = []
    for ref in refs:
        for peer in ref.get("peer_suggestions") or []:
            if peer not in peer_pool:
                peer_pool.append(peer)

    sample_field = _extract_field_path(refs[0].get("var", "field"))
    peer_example = peer_pool[0] if peer_pool else "<another-node>"

    any_failed = any(ref.get("status") == "failed" for ref in refs)
    header = (
        "  All coalesce operands failed. To fix:"
        if all(ref.get("status") == "failed" for ref in refs)
        else "  All coalesce operands are unavailable (failed or did not execute). To fix:"
    )
    lines = [
        header,
        f"    • Add another fallback: ${{{coalesce_expr} ?? {peer_example}.{sample_field}}}",
    ]
    if any_failed:
        lines.append("    • Investigate the underlying failures (see Error/Stderr above)")
    lines.extend([
        "    • If aggregate failure is acceptable, add `- on-error: <handler>`",
        "      on the node that consumes this output",
        "",
    ])
    return lines


def _format_one_reference(ref: dict[str, Any]) -> list[str]:
    """Render one reference block based on its status."""
    var = ref.get("var", "")
    root = ref.get("root", "")
    status = ref.get("status", "")
    bullet = "✗" if status != "succeeded" else "✓"
    header = f"  {bullet} ${{{var}}}"

    if status == "absent":
        return _format_absent_reference(header, ref, root, var)

    if status == "failed":
        return _format_failed_reference(header, ref, root, var)

    if status == "path_error":
        return _format_path_error_reference(header, ref, root, var)

    return [header, f"      → unknown status: {status}"]


def _format_absent_reference(header: str, ref: dict[str, Any], root: str, var: str) -> list[str]:
    lines = [
        header,
        f"      → Node '{root}' did not execute (branch not taken or not declared)",
    ]
    peers = ref.get("peer_suggestions") or []
    if not ref.get("in_coalesce", False) and peers:
        field = _extract_field_path(var)
        lines.append("")
        lines.append("        To fix:")
        lines.append(f"          • Use coalesce: ${{{var} ?? {peers[0]}.{field}}}")
    return lines


def _format_failed_reference(header: str, ref: dict[str, Any], root: str, var: str) -> list[str]:
    failure = ref.get("failure") or {}
    category = failure.get("category", "")
    error = failure.get("error") or "(no error message)"
    data = failure.get("data") or {}

    lines = [
        header,
        f"      → Node '{root}' executed but FAILED ({_describe_failure_category(category)})",
        f"        Error: {_truncate_error_text(error)}",
    ]
    lines.extend(_render_failure_data_block(category, data))

    secondary_hint = ref.get("secondary_hint")
    if secondary_hint:
        lines.append("")
        lines.append(f"      ⚠ Additional issue: field '{_extract_field_path(var)}' may also be a typo")
        lines.append(f"        Did you mean: ${{{secondary_hint}}}?")
        lines.append("        (this won't resolve even if the failure is fixed)")

    if not ref.get("in_coalesce", False):
        lines.extend(_format_failed_reference_fixes(ref, root, var))

    return lines


def _format_failed_reference_fixes(ref: dict[str, Any], root: str, var: str) -> list[str]:
    # Prefer the corrected var (if the user had both a typo AND a failure)
    # so the paste-able fix uses the real field name, not the typo.
    fix_var = ref.get("corrected_var") or var
    field = _extract_field_path(fix_var)
    peers = ref.get("peer_suggestions") or []
    lines = ["", "        To fix:"]
    if peers:
        primary_peer = peers[0]
        fix_template = f"${{{fix_var} ?? {primary_peer}.{field}}}"
        lines.append(f"          • Use coalesce: {fix_template}")
        if len(peers) > 1:
            other_peers = ", ".join(peers[1:])
            lines.append(f"            (other peers with this field: {other_peers})")
    else:
        lines.append(f"          • Use coalesce with a peer node: ${{{fix_var} ?? <peer>.{field}}}")
    lines.append(f"          • Add `- on-error: <handler>` to node '{root}' so the workflow")
    lines.append("            routes to a handler on failure")
    return lines


def _format_path_error_reference(header: str, ref: dict[str, Any], root: str, var: str) -> list[str]:
    available = ref.get("available_fields") or []
    suggestion = ref.get("did_you_mean")
    lines = [
        header,
        f"      → Node '{root}' executed but does not produce field '{_extract_field_path(var)}'",
    ]
    if available:
        display = available[:8]
        field_list = ", ".join(display)
        if len(available) > 8:
            field_list += f", ... ({len(available) - 8} more)"
        lines.append(f"        Available fields: {field_list}")
    if suggestion:
        lines.append("")
        lines.append("        To fix:")
        lines.append(f"          • Did you mean: ${{{suggestion}}}")
    return lines


def _render_failure_data_block(category: str, data: dict[str, Any]) -> list[str]:
    """Render the failure detail block, dispatched purely by category.

    Category is set authoritatively at the failure site by
    ``mark_node_failed`` (engine step 17.5 maps the compile-time node
    type name to a category). Readers dispatch on the string — not on
    data-key presence — so a success output that happens to contain
    ``status_code`` can't be misclassified.

    Each renderer returns either populated detail lines or a single
    ``(no ... details captured)`` fallback so callers can't end up with a
    blank block when a failure record has empty ``data``.
    """
    if not isinstance(data, dict):
        return ["        (no details captured)"]
    if category == "shell_failure":
        return _render_shell_failure_block(data)
    if category == "http_failure":
        return _render_http_failure_block(data)
    if category == "mcp_failure":
        return _render_mcp_failure_block(data)
    return _render_generic_failure_block(data)


def _render_shell_failure_block(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if command := data.get("command"):
        cmd_preview = command[:200] + "..." if len(command) > 200 else command
        lines.append(f"        Command: {cmd_preview}")
    if (exit_code := data.get("exit_code")) is not None:
        lines.append(f"        Exit code: {exit_code}")
    if stderr := data.get("stderr"):
        stderr_preview = stderr[:200] + "..." if len(stderr) > 200 else stderr
        lines.append(f"        Stderr: {stderr_preview}")
    if not lines:
        lines.append("        (no shell details captured — failure may have occurred before command ran)")
    return lines


def _render_http_failure_block(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if (status_code := data.get("status_code")) is not None:
        lines.append(f"        Status: {status_code}")
    if url := data.get("url"):
        lines.append(f"        URL: {url}")
    if method := data.get("method"):
        lines.append(f"        Method: {method}")
    if response := data.get("response") or data.get("response_body"):
        resp_preview = str(response)[:300]
        if len(str(response)) > 300:
            resp_preview += "..."
        lines.append(f"        Response: {resp_preview}")
    if not lines:
        lines.append("        (no HTTP details captured)")
    return lines


def _render_mcp_failure_block(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if server := data.get("server"):
        lines.append(f"        Server: {server}")
    if tool := data.get("tool"):
        lines.append(f"        Tool: {tool}")
    if details := data.get("error_details"):
        lines.append(f"        Details: {details}")
    if not lines:
        lines.append("        (no MCP details captured)")
    return lines


def _render_generic_failure_block(data: dict[str, Any]) -> list[str]:
    """Render scalar fields from an arbitrary failure data dict.

    - Skips ``error`` (already rendered on the primary ``Error:`` line)
    - Skips empty/None values
    - Truncates multi-line values at first line + ``(more)`` marker
    - Truncates single-line values at 200 chars with ``...``
    - Caps total shown fields at 6 to avoid runaway output
    """
    _skip = {"error"}
    lines: list[str] = []
    for key, value in list(data.items())[:6]:
        if str(key).startswith("_") or value is None or key in _skip:
            continue
        if not isinstance(value, (str, int, float, bool)):
            continue
        text = str(value)
        if not text.strip():
            continue
        if "\n" in text:
            first_line = text.split("\n", 1)[0]
            preview = (first_line[:200] + "...") if len(first_line) > 200 else first_line
            preview += " (more — run with --verbose)"
        elif len(text) > 200:
            preview = text[:200] + "..."
        else:
            preview = text
        lines.append(f"        {key}: {preview}")
    if not lines:
        lines.append("        (no additional details captured)")
    return lines


def _truncate_error_text(error: str, limit: int = 300) -> str:
    """Truncate an error string for the primary ``Error:`` line.

    Multi-line errors (e.g., Python tracebacks) collapse to the first line +
    a ``(more)`` marker so the diagnostic layout stays intact. Single-line
    errors over the limit are truncated with ``...``.
    """
    text = str(error)
    if "\n" in text:
        first_line = text.split("\n", 1)[0]
        if len(first_line) > limit:
            first_line = first_line[:limit] + "..."
        return f"{first_line} (more — run with --verbose)"
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _describe_failure_category(category: str) -> str:
    """Map node_state failure categories to human-readable descriptions."""
    return {
        "shell_failure": "shell command failed",
        "http_failure": "HTTP request failed",
        "mcp_failure": "MCP tool failed",
        "node_action_error": "node returned error action",
        "api_warning": "API warning",
        "routing_error": "no matching successor",
        "exception": "raised exception",
        "template_error": "template error",
    }.get(category, category or "unknown")


def _extract_field_path(var: str) -> str:
    """Extract the post-root field path from a variable reference.

    ``primary.stdout`` → ``stdout``, ``primary.data.inner`` → ``data.inner``.
    """
    if "." not in var:
        return var
    return var.split(".", 1)[1]


def _format_api_response_lines(raw_response: dict[str, Any]) -> list[str]:
    """Render HTTP API response details."""
    from pflow.core.security_utils import sanitize_parameters

    sanitized_raw = sanitize_parameters(raw_response)
    lines = ["", "  API Response:"]

    if errors_list := sanitized_raw.get("errors"):
        for api_error in errors_list[:3]:
            field = api_error.get("field", "unknown")
            message = api_error.get("message", api_error.get("code", "error"))
            lines.append(f"    - Field '{field}': {message}")
    elif message := sanitized_raw.get("message"):
        lines.append(f"    {message}")

    if doc_url := sanitized_raw.get("documentation_url"):
        lines.append("")
        lines.append(f"  Documentation: {doc_url}")

    return lines


def _format_mcp_error_lines(mcp_error: dict[str, Any]) -> list[str]:
    """Render MCP tool error details."""
    from pflow.core.security_utils import sanitize_parameters

    sanitized_mcp = sanitize_parameters(mcp_error)
    lines = ["", "  MCP Tool Error:"]

    if details := sanitized_mcp.get("details"):
        lines.append(f"    Field: {details.get('field')}")
        lines.append(f"    Expected: {details.get('expected')}")
        lines.append(f"    Received: {details.get('received')}")
    elif message := sanitized_mcp.get("message"):
        lines.append(f"    {message}")

    return lines


def _format_shell_error_lines(context: dict[str, Any]) -> list[str]:
    """Render shell command failure details."""
    lines = ["", "  Shell details:"]
    command = context.get("shell_command") or ""
    command_display = command[:200] + "..." if len(command) > 200 else command
    lines.append(f"    Command: {command_display}")
    if stdout := context.get("shell_stdout"):
        stdout_preview = stdout[:300] + "..." if len(stdout) > 300 else stdout
        lines.append(f"    Stdout: {stdout_preview}")
    if stderr := context.get("shell_stderr"):
        stderr_preview = stderr[:300] + "..." if len(stderr) > 300 else stderr
        lines.append(f"    Stderr: {stderr_preview}")
    return lines
