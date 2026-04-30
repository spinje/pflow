"""Text rendering for ``pflow analyze-cache`` (default mode).

Implements spec § "Output Format — Text" with section ordering:

1. Header (workflow path, scale, confidence label — only when actionable).
2. Summary (cost tri-state — partial / unavailable rendering).
3. Recommended actions (rank-ordered) — the canonical warnings view.
4. Suggested ## Cache block(s) — greenfield-only.
5. Cross-workflow alignment (Tier 2) — only when findings exist.
6. Per-call cache report (default-hide-clean unless ``--all-rows``).
7. Notes (info notes appended in the analyzer's locked order).

Cost tri-state contract (Suggestion 26):

- All priced → ``~$2.18``.
- Partial → ``~$0.84 (partial — 2 of 23 nodes use unpriced models)``.
- All unavailable → ``unavailable`` (NEVER ``$0.00``).

Default-hide-clean rule: rows with ``cache_ratio_pct >= 80`` and no inline
warnings collapse into a single ``Hidden: N nodes ...`` line. ``--all-rows``
overrides.

CP4 changes (#16, #9, #7, #6+#13 — agent UX cleanup):

- Dropped the "All warnings" section. Recommended actions IS the canonical
  warnings view, sorted by impact. JSON output (``warnings[]``) keeps the
  full machine-readable list — agents who want raw access run ``--format=json``.
- ``src=heuristic``/``src=estimator`` column values map to ``low``/``medium``/
  ``high`` confidence labels at render time. JSON keeps the granular 4-tier
  source for machine consumers.
- Per-call section header tells agents whether ratios reflect CURRENT state
  (greenfield: always 0%) or ACTUAL cache hit rate (steady-state: real data).
- ``Confidence: low_no_data`` header line is dropped (it duplicates the
  cost-section call-to-action). ``medium_from_memo`` / ``high_from_trace``
  labels stay — they carry actionable fidelity info.
"""

from __future__ import annotations

from collections.abc import Iterable

from pflow.core.diagnostic import Diagnostic, Severity

from .analyze import CacheAnalysis, PerCallRow

_HIDDEN_RATIO_THRESHOLD = 80


def render_text(analysis: CacheAnalysis, *, all_rows: bool = False) -> str:
    """Render the analyzer result as markdown-formatted text."""
    lines: list[str] = []
    lines.append(_render_header(analysis))
    lines.append(_render_summary(analysis))

    actions = _render_recommended_actions(analysis)
    if actions:
        lines.append(actions)

    blocks = _render_suggested_blocks(analysis)
    if blocks:
        lines.append(blocks)

    cross = _render_cross_workflow(analysis)
    if cross:
        lines.append(cross)

    per_call = _render_per_call(analysis, all_rows=all_rows)
    if per_call:
        lines.append(per_call)

    # ``_render_warnings`` ("## All warnings") deliberately NOT called from text
    # output (CP4 #16 — see module docstring). Recommended Actions IS the
    # canonical warnings view, sorted by impact. JSON consumers get the
    # full ``warnings[]`` list machine-readable via ``--format=json``.

    notes = _render_notes(analysis)
    if notes:
        lines.append(notes)

    return "\n\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _render_header(analysis: CacheAnalysis) -> str:
    """Render workflow path + scale, plus confidence WHEN it carries signal.

    CP5 #6: scale line lists the actual model names instead of just a count.
    Pre-fix "X LLM calls · Y models in use" required agents to scan the
    per-call table to learn which models. Post-fix:
      - 0 LLM nodes → "0 LLM nodes"
      - 1 model resolved → "7 LLM nodes using anthropic/claude-sonnet-4-5"
      - 2+ models → "7 LLM nodes using 2 models: anthropic/..., gemini/..."
      - LLM nodes but no model resolved → "7 LLM nodes (no model resolved)"

    CP4 #6+#13: ``Confidence: low_no_data`` was a noisy redundant signal —
    the cost-section's call-to-action ("run the workflow once for cost
    figures") tells the agent the same thing actionably. Suppressing the
    header line for the low-confidence case keeps the output tight.
    ``medium_from_memo`` / ``high_from_trace`` labels stay because they
    carry coverage info (e.g. "3 of 7 nodes have prior run data") that
    helps agents reason about how much to trust the per-call numbers.
    """
    s = analysis.summary
    coverage = analysis.estimate_confidence_coverage
    label = analysis.estimate_confidence
    lines = [
        f"# Cache Analysis: {analysis.workflow_path}",
        "",
        f"  {_format_scale_line(s.total_llm_calls_estimated, s.models_in_use)}",
    ]
    if label in {"medium_from_memo", "high_from_trace"}:
        # Per DD#34 line 638 — append coverage detail.
        source_count = (
            coverage.get("trace", 0)
            if label == "high_from_trace"
            else coverage.get("memo", 0) + coverage.get("trace", 0)
        )
        lines.append(f"  Confidence: {label} ({source_count} of {coverage.get('total', 0)} nodes)")
    return "\n".join(lines)


def _format_scale_line(node_count: int, models_in_use: tuple[str, ...]) -> str:
    """Render the scale line with model names listed instead of just a count.

    Renders as ``"N LLM nodes ..."`` (the "calls" wording was misleading —
    the count IS nodes, calls per run depend on batch sizes).
    """
    nodes_word = "node" if node_count == 1 else "nodes"
    if node_count == 0:
        return "0 LLM nodes"
    if not models_in_use:
        return f"{node_count} LLM {nodes_word} (no model resolved — set settings.default_model)"
    if len(models_in_use) == 1:
        return f"{node_count} LLM {nodes_word} using {models_in_use[0]}"
    return f"{node_count} LLM {nodes_word} using {len(models_in_use)} models: {', '.join(models_in_use)}"


def _render_summary(analysis: CacheAnalysis) -> str:
    s = analysis.summary
    current_str = _format_cost(s.current_cost_per_run_usd, s.partial_cost_usd, s.unavailable_models)
    optimized_str = _format_cost(s.optimized_cost_per_run_usd, s.partial_cost_usd, s.unavailable_models)
    rerun_str = _format_cost(s.rerun_cost_per_run_usd, s.partial_cost_usd, s.unavailable_models)

    actionable_word = "opportunity" if s.actionable_opportunities == 1 else "opportunities"
    summary_lines = [
        "## Summary",
        "",
        f"  Current cost per run:        {current_str}",
        f"  Optimized cost per run:      {optimized_str}",
        f"  Cost on rerun (within 1h):   {rerun_str}",
    ]

    # Aggregate savings — meaningful even on greenfield (output cost cancels;
    # input-only math). Only render when ``prompt_cache:`` is declared on at
    # least one node (otherwise the figure is 0 by construction).
    if s.aggregate_savings_first_run_usd is not None and s.aggregate_savings_first_run_usd > 0:
        first_str = f"~${s.aggregate_savings_first_run_usd:.2f}/run"
        rerun_savings = s.aggregate_savings_rerun_usd
        if rerun_savings is not None and rerun_savings > 0:
            summary_lines.append(
                f"  Estimated savings if applied: {first_str} (first run); ~${rerun_savings:.2f}/run on rerun"
            )
        else:
            summary_lines.append(f"  Estimated savings if applied: {first_str}")

    summary_lines.extend([
        "",
        f"  {s.actionable_opportunities} {actionable_word} "
        f"({s.warnings_count} warning{'s' if s.warnings_count != 1 else ''}, "
        f"{s.info_count} info)",
    ])

    if s.partial_cost_usd and s.unavailable_models:
        models_csv = ", ".join(s.unavailable_models)
        summary_lines.append("")
        summary_lines.append(f"  Unpriced models: {models_csv}")
    elif s.current_cost_per_run_usd is None and s.aggregate_savings_first_run_usd is not None:
        # Greenfield path — pricing data exists, but output token counts are
        # unavailable. Tell the agent how to light up the absolute figures.
        summary_lines.append("")
        summary_lines.append(
            "  Absolute cost figures need a prior run (output token counts come from "
            "memo cache or a 2.1.0 trace). Run the workflow once and re-run analyze-cache."
        )
    elif s.current_cost_per_run_usd is None and not s.unavailable_models:
        # All-unavailable case — surface explicit reason. The branch fires on
        # three distinct sub-cases; conflating them produced the lyrics-generator
        # bug where ``Cost data unavailable: workflow has no LLM nodes`` rendered
        # above a per-call table listing 2 LLM nodes:
        #   1. Zero LLM nodes total (rare; e.g. parent workflow that only
        #      delegates to sub-workflows).
        #   2. LLM nodes exist but no model could be resolved (no per-node
        #      ``model:``, ``get_default_workflow_model()`` returned None).
        #   3. LLM nodes with priced models but no run history yet (greenfield
        #      without shared context — no opportunity figure to show).
        summary_lines.append("")
        if s.total_llm_calls_estimated == 0:
            summary_lines.append("  Cost data unavailable: workflow has no LLM nodes.")
        elif not s.models_in_use:
            summary_lines.append(
                "  Cost data unavailable: no model resolved for LLM nodes "
                "(set settings.default_model or add per-node `- model:`)."
            )
        else:
            summary_lines.append("  Cost data unavailable: run the workflow once for cost figures.")
    return "\n".join(summary_lines)


def _format_cost(value: float | None, partial: bool, unavailable_models: tuple[str, ...]) -> str:
    """Tri-state cost rendering per the F2 contract."""
    if value is None:
        if unavailable_models:
            return f"unavailable (all {len(unavailable_models)} models lack pricing data)"
        return "unavailable"
    if partial:
        # Partial — caller must already have appended " (partial — N of M ...)" to value.
        # We don't have N/M here, so just mark as partial.
        return f"~${value:.2f} (partial)"
    return f"~${value:.2f}"


def _render_recommended_actions(analysis: CacheAnalysis) -> str:
    if not analysis.recommended_actions:
        return ""
    lines = ["## Recommended actions (ordered by impact)", ""]
    for action in analysis.recommended_actions:
        lines.append(f"  {action.rank}. [{action.warning_id}]  {_format_savings_usd(action.estimated_savings_usd)}")
        if action.node_id:
            lines.append(f"     Node: {action.node_id}")
        elif action.scope_workflow:
            # Workflow-level finding (e.g. shared-context spanning N nodes in one
            # file). Without this branch, the scope line would be absent and the
            # finding would render indistinguishable from per-node ones — the
            # GH #2 surface. Use basename to keep the line short.
            lines.append(f"     Workflow: {_short_workflow_label(action.scope_workflow)}")
        # CP5 #5: render the diagnostic's message below scope so each
        # recommendation is self-explanatory. Without this, four findings
        # sharing the same warning_id looked byte-identical except for the
        # scope line — agents had to drill into other sections to learn
        # what each one was about.
        if action.message:
            lines.extend(_indent_message(action.message, prefix="     "))
    return "\n".join(lines)


def _indent_message(message: str, *, prefix: str) -> list[str]:
    """Indent each line of a multi-line message under a recommendations bullet.

    Long messages render as multiple lines; the prefix keeps them visually
    aligned with the rank line above.
    """
    return [f"{prefix}{line}" for line in message.splitlines() if line.strip()]


def _short_workflow_label(path: str) -> str:
    """Render a workflow path as a short label for the recommended-actions section.

    Filesystem paths get their basename; non-path identifiers (e.g.
    ``"<inline>"``, ``"ir-hash:<md5>"``) pass through as-is.
    """
    if "/" in path:
        return path.rsplit("/", 1)[-1] or path
    return path


def _format_savings_usd(value: float | None) -> str:
    """Tri-state savings rendering — mirrors ``warning_catalog.format_dry_run_nudge``.

    ``None`` (no estimate) and sub-cent (``< $0.005``, rounds-to-zero) both
    render as ``"savings unavailable"``. Emitting ``-$0.00/run`` would imply
    "we computed it, it's zero" when the actual data is too sparse — same
    tri-state contract violation top-10% codebases avoid (Bug D).
    """
    if value is None or value < 0.005:
        return "savings unavailable"
    return f"-${value:.2f}/run"


def _render_suggested_blocks(analysis: CacheAnalysis) -> str:
    if not analysis.suggested_blocks:
        return ""
    chunks = []
    for block in analysis.suggested_blocks:
        chunks.append(f"## Suggested ## Cache block — {block.target_file}")
        chunks.append("")
        chunks.append("  Paste between ## Inputs and ## Steps:")
        chunks.append("")
        chunks.append("  ## Cache")
        chunks.append("")
        chunks.append(f"  - ttl: {block.ttl}")
        chunks.append("")
        chunks.append("  ```cache")
        for chunk in block.chunks:
            chunks.append(f"  {chunk.prose_placeholder}")
            chunks.append("")
            chunks.append(f"  {chunk.var}")
            chunks.append("")
        chunks.append("  ```")
        if block.per_node_assignments:
            chunks.append("")
            chunks.append("  Per-node `prompt_cache:` declarations")
            chunks.append("")
            chunks.append("  Add to each node's params. Order MUST match the ## Cache block above —")
            chunks.append("  pflow rejects mismatched orders as `cache.order-mismatch` ERROR.")
            chunks.append("")
            for node_id, assignment in block.per_node_assignments.items():
                chunks.append(f"  ### {node_id}")
                chunks.append(f"  - prompt_cache: [{', '.join(assignment)}]")
                chunks.append("")
    # Drop trailing blank line.
    while chunks and chunks[-1] == "":
        chunks.pop()
    return "\n".join(chunks)


def _render_cross_workflow(analysis: CacheAnalysis) -> str:
    """Render the "Sub-workflow boundaries" section (CP5 #3).

    Each finding renders as a multi-line block:
      ▸ <parent> → <child>  (<context>)
        <what was detected, in plain language>
        → <action the agent should take>
        [<warning_id>]

    This shape replaced the single-line "Cross-workflow alignment (Tier 2)"
    output which produced byte-identical-looking lines on lyrics-generator
    (the catalog message text alone wasn't enough to distinguish multiple
    findings of the same ID). The new section pulls structured data from
    ``diag.context`` per finding type so each block is self-explanatory and
    actionable, without requiring agents to look up what an ID means or
    where the boundary lives.
    """
    cf = analysis.cross_workflow
    if not (cf.rename_detections or cf.prose_mismatches or cf.value_flow_opportunities):
        return ""
    lines = [
        "## Sub-workflow boundaries",
        "",
        "  When this workflow calls a sub-workflow, values that flow across can be",
        "  cached on either side. Each finding below describes one missed opportunity.",
        "",
    ]
    # Order: value-flow first (highest leverage — these unlock new caching),
    # rename + prose-mismatch second (alignment fixes for already-declared caches).
    for diag in cf.value_flow_opportunities:
        lines.extend(_format_value_flow_finding(diag))
        lines.append("")
    for diag in cf.rename_detections:
        lines.extend(_format_rename_finding(diag))
        lines.append("")
    for diag in cf.prose_mismatches:
        lines.extend(_format_prose_mismatch_finding(diag))
        lines.append("")
    # Drop trailing blank line.
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _workflow_short_name(path: str) -> str:
    """Extract a compact identifier for a workflow path.

    ``/abs/path/song-creator.pflow.md`` → ``song-creator``
    ``<inline>`` / ``ir-hash:abc`` → unchanged
    """
    if "/" in path:
        path = path.rsplit("/", 1)[-1]
    if path.endswith(".pflow.md"):
        return path[: -len(".pflow.md")]
    return path


def _format_value_flow_finding(diag: Diagnostic) -> list[str]:
    """Format a ``cache.shared-context-undeclared`` boundary finding.

    Layout:
      ▸ <parent-name> → <child-name>  (via <type:workflow node-id>)
        <chunks> are used by N LLM nodes across the boundary;
        no ## Cache block on either side.
        → Add <chunks> to either workflow's ## Cache.
        [cache.shared-context-undeclared]
    """
    ctx = diag.context or {}
    parent = _workflow_short_name(str(ctx.get("affected_workflow", "")))
    child = _workflow_short_name(str(ctx.get("child_workflow", "")))
    via_node = diag.node_id or "?"
    chunks = ctx.get("shared_chunks") or []
    chunks_text = ", ".join(f"`{c}`" for c in chunks) or "value"
    node_count = ctx.get("node_count", "?")
    chunk_word = "are" if len(chunks) != 1 else "is"
    return [
        f"  ▸ {parent} → {child}  (via {via_node})",
        f"    {chunks_text} {chunk_word} used by {node_count} LLM nodes across the boundary; no ## Cache block on either side.",
        f"    → Add {chunks_text} to either workflow's ## Cache block.",
        f"    [{diag.id}]",
    ]


def _format_rename_finding(diag: Diagnostic) -> list[str]:
    """Format a ``cache.cross-workflow-rename-detected`` finding.

    Layout:
      ▸ <parent-name> → <child-name>  (line N)
        Parent passes `<parent-expr>` as input named `<child-input>` —
        same value, two names across the boundary.
        → Rename one side or use matching prose in both ## Cache blocks.
        [cache.cross-workflow-rename-detected]
    """
    ctx = diag.context or {}
    parent = _workflow_short_name(str(ctx.get("parent_workflow", "")))
    child = _workflow_short_name(str(ctx.get("child_workflow", "")))
    parent_expr = ctx.get("parent_value_expr", "?")
    child_input = ctx.get("child_input_name", "?")
    line = ctx.get("line_in_parent", "?")
    return [
        f"  ▸ {parent} → {child}  (line {line})",
        f"    Parent passes `{parent_expr}` as input named `{child_input}` — same value, two names across the boundary.",
        "    → Rename one side, or use the same chunk identifier and prose in both ## Cache blocks.",
        f"    [{diag.id}]",
    ]


def _format_prose_mismatch_finding(diag: Diagnostic) -> list[str]:
    """Format a ``cache.cross-workflow-prose-mismatch`` finding.

    Layout:
      ▸ <parent-name> → <child-name>
        Chunk `<name>` is declared in both ## Cache blocks with different
        prose-before-${var}; cross-workflow byte-level cache hit won't fire.
        → Pick one prose label and use it in both files.
        [cache.cross-workflow-prose-mismatch]
    """
    ctx = diag.context or {}
    parent = _workflow_short_name(str(ctx.get("parent_workflow", "")))
    child = _workflow_short_name(str(ctx.get("child_workflow", "")))
    chunk_name = ctx.get("chunk_name", "?")
    return [
        f"  ▸ {parent} → {child}",
        (
            f"    Chunk `{chunk_name}` declared in both ## Cache blocks with "
            "different prose-before-${var}; the byte-level cache hit won't fire."
        ),
        f"    → Pick one prose label and use it in both files' ## Cache blocks for `{chunk_name}`.",
        f"    [{diag.id}]",
    ]


def _render_per_call(analysis: CacheAnalysis, *, all_rows: bool) -> str:
    if not analysis.per_call:
        return ""
    rows = list(analysis.per_call)
    # Analytical detections (cache.dynamic-before-static, cache.padding-advisory,
    # cache.batch-prewarm-recommended, cache.below-min-tokens, etc.) emit Diagnostic
    # objects to ``analysis.warnings`` rather than populating ``row.warnings`` (the
    # inline tuple). The default-hide rule MUST consult analysis-wide warnings;
    # otherwise nodes with cache_ratio ≥ 80% AND analytical warnings get silently
    # hidden from the default report — agents miss high-leverage recommendations.
    nodes_with_warnings = {d.node_id for d in analysis.warnings if d.node_id}
    visible, hidden_count = _select_visible_rows(
        rows,
        all_rows=all_rows,
        nodes_with_warnings=nodes_with_warnings,
    )
    if not visible and hidden_count == 0:
        return ""

    # Build per-row inline warning markers from analysis.warnings keyed by node_id.
    warnings_by_node: dict[str, list[str]] = {}
    for diag in analysis.warnings:
        if diag.node_id and diag.id:
            warnings_by_node.setdefault(diag.node_id, []).append(diag.id)

    lines = ["## Per-call cache report"]
    explainer = _per_call_scope_explainer(rows)
    if explainer:
        lines.append(f"  {explainer}")
    if not all_rows and len(visible) < len(rows):
        lines.append(
            f"  Showing {len(visible)} of {len(rows)} LLM nodes; all-clean rows hidden (--all-rows shows everything)."
        )
    lines.append("")
    for row in visible:
        marker = f"(×{row.batch_size_estimated})" if row.is_batch and row.batch_size_estimated else ""
        inline_ids = warnings_by_node.get(row.node_path) or list(row.warnings)
        warning_marker = ", ".join(inline_ids)
        lines.append(
            f"  {row.node_path:30s} {marker:<6} model={row.model:35s} "
            f"tokens={row.input_tokens_estimated:>5}  "
            f"cacheable={row.cacheable_tokens_estimated:>5}  "
            f"ratio={row.cache_ratio_pct:>3}%  "
            f"src={_data_source_display(row.data_source)}  {warning_marker}"
        )
    if hidden_count > 0:
        lines.append("")
        lines.append(
            f"  Hidden: {hidden_count} nodes at ≥{_HIDDEN_RATIO_THRESHOLD}% projected "
            "cache ratio with no warnings (rerun with --all-rows)."
        )
    return "\n".join(lines)


# CP4 #9 — ``data_source`` mapping: pflow's internal 4-tier source classification
# leaks the implementation detail of WHICH estimator produced the number. Agents
# only need to know how much to trust it; the granular source stays in JSON for
# machine consumers (per ``per_call[].data_source`` schema).
_DATA_SOURCE_DISPLAY: dict[str, str] = {
    "trace": "high",
    "memo": "high",
    "estimator": "medium",
    "heuristic": "low",
}


def _data_source_display(value: str) -> str:
    """Map an internal data_source value to the user-facing confidence label.

    Unknown values pass through unchanged so a future tier (e.g. ``inferred``)
    surfaces verbatim until this map gets a row — fail-loud, fail-actionable.
    """
    return _DATA_SOURCE_DISPLAY.get(value, value)


def _per_call_scope_explainer(rows: list[PerCallRow]) -> str:
    """Return a one-line explainer describing what ``ratio=`` means here.

    CP4 #7: greenfield workflows (no ``prompt_cache:`` declared anywhere)
    show ``ratio=0%`` for every row, which alongside ``N opportunities`` in
    the summary produces a confusing top-to-bottom read. The explainer
    tells the agent which scenario they're in:

    - Greenfield: ratios are CURRENT (always 0% pre-cache); opportunities are
      what's recoverable. Returns the recoverable-savings hint.
    - Steady-state: ratios reflect actual cache hits from declared subsets.
      Returns the actual-cache hint.

    Detection: if any row has ``declared_prompt_cache != None``, at least one
    node has opted into a declared subset → steady-state mode.
    """
    is_steady_state = any(row.declared_prompt_cache is not None for row in rows)
    if is_steady_state:
        return "Actual cache ratios from declared `prompt_cache:` subsets."
    return "Current ratios (always 0% pre-cache); see Recommended actions for the recoverable opportunities."


def _select_visible_rows(
    rows: Iterable[PerCallRow],
    *,
    all_rows: bool,
    nodes_with_warnings: set[str],
) -> tuple[list[PerCallRow], int]:
    """Apply the default-hide-clean rule.

    Returns ``(visible_rows, hidden_count)``. Sorted: warnings first, then by
    ``input_tokens_estimated`` descending.
    """
    rows_list = list(rows)
    if all_rows:
        sorted_rows = sorted(rows_list, key=lambda r: -r.input_tokens_estimated)
        return sorted_rows, 0
    visible = [r for r in rows_list if _is_row_visible_by_default(r, nodes_with_warnings)]
    hidden = len(rows_list) - len(visible)
    sorted_visible = sorted(visible, key=lambda r: -r.input_tokens_estimated)
    return sorted_visible, hidden


def _is_row_visible_by_default(row: PerCallRow, nodes_with_warnings: set[str]) -> bool:
    """Per spec — show rows with warnings (inline OR analysis-wide) OR ratio < 80%."""
    if row.warnings or row.node_path in nodes_with_warnings:
        return True
    return row.cache_ratio_pct < _HIDDEN_RATIO_THRESHOLD


def _render_warnings(analysis: CacheAnalysis) -> str:
    if not analysis.warnings:
        return ""
    lines = ["## All warnings", ""]
    for diag in analysis.warnings:
        sev = {
            Severity.ERROR: "error",
            Severity.WARNING: "warning",
            Severity.INFO: "info",
        }.get(diag.severity, "")
        node_part = f"  {diag.node_id}" if diag.node_id else ""
        id_part = f"[{diag.id}]" if diag.id else ""
        lines.append(f"  {sev:8s} {id_part}{node_part}")
    return "\n".join(lines)


def _render_notes(analysis: CacheAnalysis) -> str:
    if not analysis.notes:
        return ""
    lines = ["## Notes", ""]
    for note in analysis.notes:
        lines.append(f"  · {note}")
    return "\n".join(lines)


__all__ = ["render_text"]
