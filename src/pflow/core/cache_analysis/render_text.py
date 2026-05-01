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

from pflow.core.diagnostic import Diagnostic

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

    # "## All warnings" section was removed entirely (CP4 #16 — see module
    # docstring). Recommended Actions IS the canonical warnings view, sorted
    # by impact. JSON consumers get the full ``warnings[]`` list via
    # ``--format=json``.

    notes = _render_notes(analysis)
    if notes:
        lines.append(notes)

    return "\n\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


_HETEROGENEOUS_MODEL_TAG = "model varies per batch item"


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
        f"  {_format_scale_line(s.total_llm_calls_estimated, s.models_in_use, heterogeneous_node_paths=s.heterogeneous_model_node_paths)}",
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


def _format_scale_line(
    node_count: int,
    models_in_use: tuple[str, ...],
    *,
    heterogeneous_node_paths: tuple[str, ...] = (),
) -> str:
    """Render the scale line with model names listed instead of just a count.

    Renders as ``"N LLM nodes ..."`` (the "calls" wording was misleading —
    the count IS nodes, calls per run depend on batch sizes).

    Stage C.1: heterogeneous batch sub-workflows (``model: ${item.model}``)
    are excluded from ``models_in_use`` upstream so the literal template
    string doesn't leak into the rendered list. This function appends a
    "+ N nodes with model varying per batch item (names...)" suffix when
    such nodes exist — naming them so the agent doesn't have to scan the
    per-call table to find which nodes vary.
    """
    nodes_word = "node" if node_count == 1 else "nodes"
    if node_count == 0:
        return "0 LLM nodes"
    hetero_count = len(heterogeneous_node_paths)
    homogeneous_count = node_count - hetero_count
    hetero_suffix = _format_heterogeneous_suffix(heterogeneous_node_paths)

    if homogeneous_count == 0 and hetero_count > 0:
        # All-heterogeneous workflow — no homogeneous models to list.
        hetero_word = "node" if hetero_count == 1 else "nodes"
        names_csv = ", ".join(heterogeneous_node_paths)
        if hetero_count == 1:
            return f"{node_count} LLM {nodes_word} ({heterogeneous_node_paths[0]}: {_HETEROGENEOUS_MODEL_TAG})"
        return (
            f"{node_count} LLM {nodes_word} with {_HETEROGENEOUS_MODEL_TAG} ({hetero_count} {hetero_word}: {names_csv})"
        )

    if not models_in_use:
        return f"{node_count} LLM {nodes_word} (no model resolved — set settings.default_model)"
    if len(models_in_use) == 1:
        base = f"{node_count} LLM {nodes_word} using {models_in_use[0]}"
    else:
        base = f"{node_count} LLM {nodes_word} using {len(models_in_use)} models: {', '.join(models_in_use)}"
    return f"{base}{hetero_suffix}"


def _format_heterogeneous_suffix(heterogeneous_node_paths: tuple[str, ...]) -> str:
    """Compose the "+ N nodes ..." suffix appended to the scale line.

    Empty tuple → empty string. Single node → name it inline. Multiple →
    count + parenthesized csv (so agents can grep the rendered output for a
    specific node name without scanning the per-call table).
    """
    count = len(heterogeneous_node_paths)
    if count == 0:
        return ""
    names_csv = ", ".join(heterogeneous_node_paths)
    if count == 1:
        return f" + {heterogeneous_node_paths[0]} ({_HETEROGENEOUS_MODEL_TAG})"
    word = "node" if count == 1 else "nodes"
    return f" + {count} {word} with {_HETEROGENEOUS_MODEL_TAG} ({names_csv})"


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
            "  Absolute cost figures need a prior run. Run the workflow once, then "
            "re-run analyze-cache for real cost figures and cacheable projections."
        )
    elif s.current_cost_per_run_usd is None and not s.unavailable_models:
        # All-unavailable case — surface explicit reason. The branch fires on
        # four distinct sub-cases; conflating them produced the lyrics-generator
        # bug where ``Cost data unavailable: workflow has no LLM nodes`` rendered
        # above a per-call table listing 2 LLM nodes:
        #   1. Zero LLM nodes total (rare; e.g. parent workflow that only
        #      delegates to sub-workflows).
        #   2. ALL LLM nodes are heterogeneous (``model: ${item.X}`` from
        #      heterogeneous batch sub-workflows). The "set settings.default_model"
        #      hint would be wrong here — model resolution isn't the problem;
        #      pricing per-batch-item models can't be aggregated as one model.
        #   3. LLM nodes exist but no model could be resolved (no per-node
        #      ``model:``, ``get_default_workflow_model()`` returned None).
        #   4. LLM nodes with priced models but no run history yet (greenfield
        #      without shared context — no opportunity figure to show).
        summary_lines.append("")
        if s.total_llm_calls_estimated == 0:
            summary_lines.append("  Cost data unavailable: workflow has no LLM nodes.")
        elif s.heterogeneous_model_node_count == s.total_llm_calls_estimated:
            # Stage C.1: gate ahead of the "no model resolved" branch.
            summary_lines.append("  Cost data unavailable: all LLM nodes use models that vary per batch item.")
        elif not s.models_in_use:
            summary_lines.append(
                "  Cost data unavailable: no model resolved for LLM nodes "
                "(set settings.default_model or add per-node `- model:`)."
            )
        else:
            summary_lines.append("  Cost data unavailable: run the workflow once for cost figures.")
    return "\n".join(summary_lines)


def _format_cost(value: float | None, partial: bool, unavailable_models: tuple[str, ...]) -> str:
    """Tri-state cost rendering per the F2 contract.

    Stage C.2: when exactly ONE model is unpriced, name it directly so the
    agent doesn't have to scan ``models_in_use`` to find the culprit. The
    plural-count phrasing remains for N>1.
    """
    if value is None:
        if len(unavailable_models) == 1:
            return f"unavailable ({unavailable_models[0]} lacks pricing data)"
        if unavailable_models:
            return f"unavailable (all {len(unavailable_models)} models lack pricing data)"
        return "unavailable"
    if partial:
        # Partial — caller must already have appended " (partial — N of M ...)" to value.
        # We don't have N/M here, so just mark as partial.
        return f"~${value:.2f} (partial)"
    return f"~${value:.2f}"


def _render_recommended_actions(analysis: CacheAnalysis) -> str:
    """Render the agent-skim list: action headline + scope + reason paragraph.

    Stage 0 (Task 159): the ranked list is computed on demand from
    ``analysis.warnings`` via ``view_helpers.build_recommended_actions`` (no
    longer a pre-computed field on ``CacheAnalysis``). Cross-workflow
    alignment findings (rename, prose-mismatch) are filtered out by the view
    helper — they render in the "Sub-workflow boundaries" section.

    Stage-1 final UX pass: dropped the ``[cache.X]`` bracket prefix (visually
    coded category names as error codes — top-10% codebases like mypy/ruff
    don't bracket long namespaced descriptors). Headline now leads from the
    catalog's ``headline_template`` ("<category> — <action>"); scope on its
    own line; descriptive message indented underneath as the reason.
    """
    from .view_helpers import build_recommended_actions

    actions = build_recommended_actions(list(analysis.warnings))
    if not actions:
        return ""
    # Stage B.4 (Task 159): one-time block-level intro replaces per-finding
    # mechanic explanations. Each item below is one ## Cache edit; the intro
    # carries the "why caching matters" context once instead of repeating it
    # in every finding's reason paragraph.
    lines = [
        "## Recommended actions (ordered by impact)",
        "",
        "  Each item below is one edit that unlocks LLM-provider caching.",
        "  Declared values are sent once and reused at 0.1× input cost.",
        "",
    ]
    for action in actions:
        # Headline + savings on the rank line. Falls back to message when no
        # catalog headline (defense-in-depth for non-catalog diagnostics).
        title = action.headline or action.message or action.warning_id
        savings = _format_savings_usd(action.estimated_savings_usd)
        lines.append(f"  {action.rank}. {title}{_pad_savings(title, savings)}{savings}")
        if action.node_id:
            lines.append(f"     {action.node_id}")
        elif action.scope_workflow:
            # Workflow-level finding (e.g. shared-context spanning N nodes in one
            # file). Without this line the scope would be absent and findings
            # would render indistinguishable from per-node ones (the GH #2
            # surface). Basename keeps the line short.
            lines.append(f"     {_short_workflow_label(action.scope_workflow)}")
        # Reason paragraph — only rendered when distinct from the headline.
        # Skipping when message ≡ headline avoids duplicating the same prose
        # twice in narrow terminals.
        if action.message and action.message != action.headline:
            lines.extend(_indent_message(action.message, prefix="     "))
        lines.append("")
    # Drop trailing blank.
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _pad_savings(title: str, savings: str) -> str:
    """Right-align savings so the rank line reads as a column.

    Target column at 70; clamp to a minimum 2-space gap when the title is
    long. Mirrors the canonical mode-1 example in the spec where savings
    sit at a stable right column.
    """
    target = 70
    needed = target - len(title) - 2  # 2-char minimum gap before savings
    if needed < 2:
        return "  "
    return " " * needed


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
        chunks.append("  Paste between ## Inputs and ## Steps. Replace each `<TODO>` below with")
        chunks.append("  a short description of the value (1-2 sentences). The LLM reads this")
        chunks.append("  prose right before the value, so a clear label helps the LLM understand")
        chunks.append("  what it's looking at.")
        chunks.append("")
        chunks.append('  Example: "The core narrative idea this song is built around:" before')
        chunks.append("           ${concept.core_idea}.")
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
    """Render the "Sub-workflow boundaries" section.

    Stage 0 (Task 159): findings are derived from ``analysis.warnings`` by
    filtering on ``Diagnostic.id`` (no longer pre-stored on
    ``CacheAnalysis.cross_workflow``). Each cross-workflow alignment finding
    renders here EXCLUSIVELY — value-flow opportunities surface in
    Recommended actions only (per Stage B Option d Mix; the
    ``view_helpers._CROSS_WORKFLOW_ALIGNMENT_IDS`` filter keeps each finding
    visible in exactly one section).

    Stage-1 final UX pass: numbered findings using the same headline + scope +
    reason shape as Recommended actions, dropping the ``[cache.X]`` footer.
    The section header tells the agent the category; the per-finding
    headline + reason paragraph carries the discriminator without an ID
    lookup. Section structure (parent → child header + line number) provides
    the boundary scope; the catalog's ``headline_template`` provides the
    action.
    """
    # Filter analysis.warnings by Diagnostic.id to recover the two alignment
    # categories. Value-flow findings (cache.shared-context-undeclared with
    # child_workflow in context) are NOT rendered here — they're surfaced in
    # Recommended actions, which is the agent's primary action list.
    rename_detections = [d for d in analysis.warnings if d.id == "cache.cross-workflow-rename-detected"]
    prose_mismatches = [d for d in analysis.warnings if d.id == "cache.cross-workflow-prose-mismatch"]
    if not (rename_detections or prose_mismatches):
        return ""
    # Stage B.3 (Task 159): section narrows to alignment-only — rename +
    # prose-mismatch findings (inherently boundary-shaped, not aggregable).
    # Cross-boundary value-flow opportunities are emitted as collapsed
    # findings in Recommended actions above (one per (parent_workflow,
    # value_root) group). The cross-reference signposts where related
    # findings live so an agent skimming this section knows.
    lines = [
        "## Sub-workflow boundaries",
        "",
        "  Alignment between sub-workflows that share value names. Each finding",
        "  is a place where prose labels diverge or where a value gets renamed",
        "  across the boundary — fixing them lets cached bytes match across",
        "  sub-workflows. (Cross-boundary value-flow opportunities appear in",
        "  Recommended actions above.)",
        "",
    ]
    rank = 1
    for diag in rename_detections:
        lines.extend(_format_boundary_finding(diag, rank, scope_kind="rename"))
        lines.append("")
        rank += 1
    for diag in prose_mismatches:
        lines.extend(_format_boundary_finding(diag, rank, scope_kind="prose_mismatch"))
        lines.append("")
        rank += 1
    # Drop trailing blank line.
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _format_boundary_finding(diag: Diagnostic, rank: int, *, scope_kind: str) -> list[str]:
    """Format one cross-workflow finding as headline + scope + reason.

    Layout mirrors Recommended actions:
      <rank>. <headline>
         <scope: parent → child  (via <node>, line N)>
         <reason paragraph from diag.message>

    No ``[id]`` footer. The catalog's ``headline_template`` carries the
    action; ``diag.message`` carries the descriptive reason.
    """
    ctx = diag.context or {}
    parent = _workflow_short_name(str(ctx.get("parent_workflow", ctx.get("affected_workflow", ""))))
    child = _workflow_short_name(str(ctx.get("child_workflow", "")))

    # Scope formatting depends on which finding type — different context keys
    # are populated for each. Value-flow has a parent_node_id (via <node>);
    # rename has line_in_parent (line N); prose-mismatch has neither.
    if scope_kind == "value_flow":
        via = diag.node_id or ctx.get("parent_node_id") or "?"
        scope = f"{parent} → {child}  (via {via})"
    elif scope_kind == "rename":
        line = ctx.get("line_in_parent", "?")
        scope = f"{parent} → {child}  (line {line})"
    else:  # prose_mismatch
        scope = f"{parent} → {child}"

    # Catalog-as-SSoT (see warning_catalog.resolve_headline_for) — works for
    # both make_diagnostic-emitted and directly-constructed Diagnostics.
    from .warning_catalog import resolve_headline_for

    headline = resolve_headline_for(diag)
    title = headline or diag.message or (diag.id or "")

    out = [f"  {rank}. {title}"]
    out.append(f"     {scope}")
    if diag.message and diag.message != headline:
        out.extend(_indent_message(diag.message, prefix="     "))
    return out


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


def _render_per_call(analysis: CacheAnalysis, *, all_rows: bool) -> str:
    if not analysis.per_call:
        return ""
    rows = list(analysis.per_call)
    # Option C — per-row data filter. A row is "real-data-bearing" iff:
    #   - input_tokens reflects ACTUAL runtime tokens (data_source in
    #     {trace, memo}), OR
    #   - the row has a declared subset (steady-state — declared chunks ARE
    #     the cacheable signal regardless of memo).
    # Pure greenfield (estimator/heuristic + no declared subset) rows are
    # filtered out: their input_tokens column shows TEMPLATE size (with
    # ${var} as ~5-token literals — NOT actual runtime size) and their
    # cacheable column is unprojectable without memo. Both columns mislead.
    # When ALL rows are filtered, the section is hidden entirely.
    real_data_rows = [r for r in rows if _row_has_real_data(r)]
    if not real_data_rows:
        return ""
    # Analytical detections (cache.dynamic-before-static, cache.padding-advisory,
    # cache.batch-prewarm-recommended, cache.below-min-tokens, etc.) emit Diagnostic
    # objects to ``analysis.warnings`` rather than populating ``row.warnings`` (the
    # inline tuple). The default-hide rule MUST consult analysis-wide warnings;
    # otherwise nodes with cache_ratio ≥ 80% AND analytical warnings get silently
    # hidden from the default report — agents miss high-leverage recommendations.
    nodes_with_warnings = {d.node_id for d in analysis.warnings if d.node_id}
    visible, hidden_count = _select_visible_rows(
        real_data_rows,
        all_rows=all_rows,
        nodes_with_warnings=nodes_with_warnings,
    )
    if not visible and hidden_count == 0:
        return ""

    # Build per-row inline warning markers from analysis.warnings keyed by node_id.
    # The ``cache.`` namespace prefix is stripped — every ID in this output is
    # ``cache.*`` so the prefix is 100% redundant in the per-call notes column.
    # Full IDs stay in JSON for machine consumers (DD#27).
    warnings_by_node: dict[str, list[str]] = {}
    for diag in analysis.warnings:
        if diag.node_id and diag.id:
            warnings_by_node.setdefault(diag.node_id, []).append(_strip_cache_prefix(diag.id))

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
        inline_ids = warnings_by_node.get(row.node_path, [])
        warning_marker = ", ".join(inline_ids)
        # Mixed-state rendering: a row that survives the filter (has memo
        # data for input) might still have None cacheable if the workflow
        # mixes nodes with/without memo for their refs. Render ``?`` to
        # distinguish from numeric zero.
        cacheable_str = (
            f"{row.cacheable_tokens_estimated:>5}" if row.cacheable_tokens_estimated is not None else "    ?"
        )
        ratio_str = f"{row.cache_ratio_pct:>3}%" if row.cache_ratio_pct is not None else "  ?%"
        # Stage C.1: heterogeneous rows have ``model = ""`` upstream so the
        # literal ``${item.model}`` template doesn't leak. Render ``<varies>``
        # so agents reading the per-call table see the same signal as the
        # scale line ("model varies per batch item"), not a missing field.
        model_display = "<varies>" if row.model_is_heterogeneous else row.model
        lines.append(
            f"  {row.node_path:30s} {marker:<6} model={model_display:35s} "
            f"tokens={row.input_tokens_estimated:>5}  "
            f"cacheable={cacheable_str}  "
            f"ratio={ratio_str}  "
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

    Two modes that survive the Option C row filter:

    - **Steady-state**: at least one row has ``declared_prompt_cache``.
      Values reflect declared subsets.
    - **Post-run greenfield**: rows have memo/trace data; values are projected
      from real run history.
    """
    is_steady_state = any(row.declared_prompt_cache is not None for row in rows)
    if is_steady_state:
        return "Actual cache ratios from declared `prompt_cache:` subsets."
    return "Projected cache ratios from prior run data."


def _row_has_real_data(row: PerCallRow) -> bool:
    """Per-row visibility check for the per-call cache report (Option C).

    A row is real-data-bearing iff it has a substantive signal to display:

    - ``data_source in {"trace", "memo"}`` — input_tokens is actual runtime
      size (post-substitution); cacheable can be projected from real chunks.
    - ``declared_prompt_cache`` non-empty — steady-state mode where the row
      is interesting regardless of memo (the declared subset itself IS the
      caching contract).
    - ``model_is_heterogeneous`` (Stage C.1) — the row CARRIES signal even
      without memo: the model-varies-per-item fact is what the agent needs
      to see (and the per-call line is the only place that names which node
      varies in detail). Hiding heterogeneous rows would force the agent to
      grep the JSON for ``model_is_heterogeneous`` flags.

    Pure-greenfield-no-memo rows that aren't heterogeneous fail all checks:
    input_tokens is template size with ``${var}`` references counted as
    ~5-token literals (NOT actual runtime size), and cacheable is
    unprojectable. Hiding such rows is more honest than rendering misleading
    numbers.
    """
    return row.data_source in {"trace", "memo"} or bool(row.declared_prompt_cache) or row.model_is_heterogeneous


def _strip_cache_prefix(warning_id: str) -> str:
    """Strip the ``cache.`` namespace prefix for compact text rendering.

    Every catalog ID is namespaced ``cache.*`` so the prefix is redundant in
    the analyze-cache text output. Full IDs stay in JSON via
    ``Diagnostic.to_dict()`` for machine consumers (DD#27).
    """
    return warning_id.removeprefix("cache.") if warning_id else warning_id


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
    """Per spec — show rows with analysis-wide warnings OR ratio < 80%.

    Stage 0.3: the inline ``row.warnings`` fallback is gone — production
    never populated it. Per-row warning visibility is keyed entirely by
    ``analysis.warnings`` filtered by node_id.

    ``cache_ratio_pct`` may be ``None`` (mixed-state row that survived the
    real-data filter but has no projection). Treat None as "below threshold"
    — show by default since the agent should at least see that the row exists.
    """
    if row.node_path in nodes_with_warnings:
        return True
    if row.cache_ratio_pct is None:
        return True
    return row.cache_ratio_pct < _HIDDEN_RATIO_THRESHOLD


def _render_notes(analysis: CacheAnalysis) -> str:
    if not analysis.notes:
        return ""
    lines = ["## Notes", ""]
    for note in analysis.notes:
        lines.append(f"  · {note}")
    return "\n".join(lines)


__all__ = ["render_text"]
