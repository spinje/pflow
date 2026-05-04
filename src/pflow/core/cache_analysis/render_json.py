"""JSON rendering for ``pflow analyze-cache --format=json`` and the MCP tool.

Format-version policy locked at this module:

- Current version is :data:`JSON_FORMAT_VERSION` (current literal ``"4.0"``).
- Consumer rule: ``format_version.startswith(JSON_FORMAT_VERSION_MAJOR + ".")``.
  Minor bumps (``4.0`` → ``4.1``) are additive; major bumps (``5.x``) are
  breaking. Mirrors the trace ``2.x`` policy at ``trace_report.py:463``.
  This is NOT the trace ``2.x`` namespace — analyze-cache JSON output and
  trace JSON files share the major-version vocabulary but are independent
  schemas.

The constants live here (where they're used) and the package ``__init__``
re-exports them for the public API surface. Top-10% precedent: pytest's
``__version__`` lives in ``pytest/__init__.py`` because that's the public
boundary; we mirror that convention without the upward-import circularity.

Empty-array contract: ``cross_workflow.*`` arrays are always present (empty
when no findings). Text mode hides empty sections; JSON exposes them so
agents can treat absence as a positive signal.
"""

from __future__ import annotations

from typing import Any, Final

from pflow.core.diagnostic import Diagnostic

from .analyze import CacheAnalysis, PerCallRow, RecommendedAction, SuggestedBlock

JSON_FORMAT_VERSION: Final[str] = "4.0"
"""Current JSON output format version. Bump minor on additive changes.

Version history:

- ``1.0`` — initial agent-facing JSON shape (Phase F).
- ``1.1`` — Stage-1 final pass (Concern B): ``per_call[].cacheable_tokens_estimated``
  and ``per_call[].cache_ratio_pct`` semantics extended to include PROJECTED
  values in greenfield mode (sum of detected shared-context chunks the node
  would use if the suggested ## Cache block were declared). Pre-1.1, both
  fields were always 0 in greenfield. Field shapes unchanged.
- ``2.0`` — Task 159 Stage 0 data-model redesign. Top-level shape stable;
  internal data sources changed:

  * ``recommended_actions`` is now a renderer-derived view computed on demand
    from ``warnings`` (was pre-computed on ``CacheAnalysis``). JSON entries
    are byte-equivalent to 1.1 for the same input findings — agents see no
    shape change. Cross-workflow alignment IDs (``cache.cross-workflow-rename-detected``,
    ``cache.cross-workflow-prose-mismatch``) are now FILTERED from this
    array — they appear under ``cross_workflow.*`` only. Consumers that
    relied on the latent duplication will see those IDs disappear from
    ``recommended_actions``.
  * ``cross_workflow.{rename_detections, prose_mismatches, value_flow_opportunities}``
    arrays are now derived views (filtered from ``warnings`` by
    ``Diagnostic.id``). Empty-array contract preserved.
  * ``per_call[].warnings`` array DROPPED — the field was vestigial in 1.x
    (single producer never populated it). Per-row warning markers are
    derivable by filtering the top-level ``warnings`` array by
    ``node_id``.

  Structural intent: ``warnings`` is the single source of truth for
  findings; views are projections. mypy / rustc / clippy / ruff all use
  this shape — pre-computed views in the data model create duplication and
  drift.
- ``2.0`` (Stage C.1, additive): new ``per_call[].model_is_heterogeneous``
  boolean field — ``True`` when the IR's ``params.model`` was an
  unresolved ``${...}`` template (heterogeneous batch sub-workflow); when
  ``True`` the ``model`` field is empty string so consumers can dispatch
  on either. New ``summary.heterogeneous_model_node_count`` (int) and
  ``summary.heterogeneous_model_node_paths`` (list[str]) surface the
  count and node identities — the ``${item.model}`` literal no longer
  leaks into ``models_in_use`` (which previously rendered as
  ``"${item.model}"`` in the scale line). Field shapes additive; consumers
  matching ``format_version.startswith("2.")`` ignore the new fields.
- ``2.0`` (unified ``estimate_cacheable_tokens``, additive): new
  ``per_call[].cacheable_data_source`` string field. Sources: ``"trace"``,
  ``"memo"``, ``"estimator"``, ``"unavailable"``. Independent from
  ``data_source`` (input) — Tier 1 for cacheable reads
  ``cache_creation_input_tokens + cache_read_input_tokens`` from the trace
  event (not ``input_tokens``), so the two metrics may legitimately
  diverge. SEMANTIC change: ``cacheable_tokens_estimated`` previously
  ran a static heuristic on the prompt template; now it follows the
  4-tier hierarchy (trace → memo → estimator → unavailable) symmetric
  with ``input_tokens_estimated``. Heterogeneous-batch greenfield rows
  may shift from ``0`` to ``null`` (no projection possible without
  model). Field shapes additive.
- ``2.1`` (Track A / B / C): three new ``per_call[]`` fields, all additive.

  * ``cost_usd`` (number | null): per-call recorded cost from the trace
    when available (sum of llm_call + batch_items[*].llm_call costs); null
    for rows without trace data (recompute path fires).
  * ``cost_data_source`` (string): tier label for the cost figure. 4-state:
    ``"trace"`` (priced; all leaves priced — high confidence),
    ``"trace_partial"`` (cost from trace + recompute mix; at least one leaf
    had unpriced model — medium-high confidence),
    ``"recomputed"`` (no trace; computed from ``tokens x LiteLLM rate`` —
    medium confidence; matches pre-Track-A behavior),
    ``"unavailable"`` (pricing missing AND no trace data — low confidence).
  * ``cacheable_data_source`` gains a new value: ``"parameters"`` — fired
    when greenfield workflow-input refs resolve via the agent's
    ``--inputs`` (was previously labeled ``"memo"`` even though the
    underlying data came from parameters).

  SEMANTIC fixes (no shape changes):
  * ``current_cost_per_run_usd`` now reflects what the workflow actually
    paid (honoring implicit caching like Gemini's). Pre-fix, it recomputed
    from ``tokens x full_rate`` and over-estimated by 50-200%+ on cached
    runs. Tier label on ``per_call[].cost_data_source`` lets consumers
    distinguish trace-honored from recomputed.
  * ``input_tokens_estimated`` for greenfield workflow-input refs now
    counts the RESOLVED prompt's tokens (via ``--inputs``) instead of the
    literal template's ~5-char ``${context}`` placeholder. Before fix,
    greenfield projections under-estimated by 99% on input-heavy prompts.
  * ``data_source`` on rows whose prompt resolved partially (some
    ``${...}`` refs left unsubstituted) now reports ``"estimator-partial"``
    instead of ``"estimator"`` — high-confidence projection requires full
    resolution.
- ``3.0`` — breaking rename: ``summary.optimized_cost_per_run_usd`` is now
  ``summary.cost_without_caching_usd``. The value was always the no-cache
  hypothetical, not an optimization target. ``per_call[].workflow_path`` is
  added so consumers can distinguish same-id LLM nodes across sub-workflows.
- ``4.0`` — breaking field rename: ``summary``'s three overloaded cost
  fields are replaced with five atomic primitives. Each carries one
  meaning so agents reading any single field know what it represents
  independent of greenfield/trace context.

  Removed (raised silent-failure risk because their meaning shifted with
  context):

  * ``summary.current_cost_per_run_usd`` — previously meant "actually paid
    when trace exists, no-cache hypothetical otherwise." Two semantics in
    one field.
  * ``summary.cost_without_caching_usd`` — previously a HYBRID (no-cache
    for undeclared rows + with-cache first-run projection for declared
    rows). The label said "without caching" but the value included
    cache-write costs for declared rows.
  * ``summary.rerun_cost_per_run_usd`` — renamed to
    ``rerun_within_ttl_hypothetical_usd`` for shape symmetry.

  Added:

  * ``summary.actually_paid_usd`` (number | null): trace-driven recorded
    cost. ``null`` for greenfield (no trace). Includes provider-side
    implicit caching (Gemini) and any other discount the trace recorded.
    The honest "what did this run actually cost?" figure.
  * ``summary.actually_paid_tier`` (string): confidence tier for
    ``actually_paid_usd``. Values: ``"trace"`` (every leaf priced),
    ``"trace_partial"`` (some leaves had unpriced model), ``"unavailable"``
    (no trace data).
  * ``summary.no_cache_hypothetical_usd`` (number | null): pure no-cache
    recompute baseline — ``input × full_rate + output × output_rate``
    over all priced rows. The "what would this cost without ANY caching?"
    projection.
  * ``summary.first_run_with_cache_hypothetical_usd`` (number | null):
    first-run projection that honors declared ``prompt_cache:`` (write
    rate on cacheable + input rate on non-cacheable + output rate on
    output for declared rows; no-cache math for undeclared rows). Equals
    ``no_cache_hypothetical_usd`` exactly when no row declares cache.
  * ``summary.rerun_within_ttl_hypothetical_usd`` (number | null):
    projection for every call after the first within TTL (all cacheable
    at read rate).

  Sub-workflow rollup entries (``summary.sub_workflow_rollup.per_workflow[]``)
  carry the same four primitives at child-workflow scope. Removed:
  ``current_cost_usd``, ``cost_without_caching_usd``. Added:
  ``actually_paid_usd``, ``no_cache_hypothetical_usd``,
  ``first_run_with_cache_hypothetical_usd``,
  ``rerun_within_ttl_hypothetical_usd``.

  Consumers that read these fields by name MUST update. Consumers that
  match ``format_version.startswith("4.")`` continue to work on minor
  bumps (additive fields, additive warning IDs).
"""

JSON_FORMAT_VERSION_MAJOR: Final[str] = "4"
"""Major version prefix. Consumer rule: ``format_version.startswith("4.")``."""


def render_json(analysis: CacheAnalysis) -> dict[str, Any]:
    """Render the analyzer result as the agent-facing JSON dict.

    Output shape mirrors spec § "Output Format — JSON" verbatim. Reuses
    :meth:`Diagnostic.to_dict` for warnings so agents see the same shape they
    get from any other pflow diagnostic surface.

    Stage 0 (Task 159): ``recommended_actions`` is computed on demand from
    ``analysis.warnings`` via ``view_helpers.build_recommended_actions``;
    cross-workflow alignment findings (rename, prose-mismatch) are excluded
    from the ranked list (they're surfaced under ``cross_workflow.*``). The
    JSON shape stays stable.
    """
    from .view_helpers import build_recommended_actions

    actions = build_recommended_actions(list(analysis.warnings))
    return {
        "format_version": JSON_FORMAT_VERSION,
        "workflow_path": analysis.workflow_path,
        "analyzed_at": analysis.analyzed_at,
        "estimate_confidence": analysis.estimate_confidence,
        "estimate_confidence_coverage": dict(analysis.estimate_confidence_coverage),
        "trace_path": analysis.trace_path,
        "summary": _summary_to_dict(analysis),
        "recommended_actions": [_action_to_dict(a) for a in actions],
        "suggested_blocks": [_block_to_dict(b) for b in analysis.suggested_blocks],
        "per_call": [_per_call_to_dict(r) for r in analysis.per_call],
        "cross_workflow": _cross_workflow_to_dict(analysis),
        "warnings": [_warning_to_dict(w) for w in analysis.warnings],
        "notes": list(analysis.notes),
    }


def _summary_to_dict(analysis: CacheAnalysis) -> dict[str, Any]:
    s = analysis.summary
    return {
        # Phase 5 (4.0): atomic cost primitives. Each field carries one
        # meaning. ``actually_paid_usd`` is ``null`` for greenfield (no
        # trace); the three hypothetical fields are projections from IR
        # rows. Replaces 3.x's overloaded ``current_cost_per_run_usd`` /
        # ``cost_without_caching_usd`` / ``rerun_cost_per_run_usd``.
        "actually_paid_usd": s.actually_paid_usd,
        "actually_paid_tier": str(s.actually_paid_tier),
        "no_cache_hypothetical_usd": s.no_cache_hypothetical_usd,
        "first_run_with_cache_hypothetical_usd": s.first_run_with_cache_hypothetical_usd,
        "rerun_within_ttl_hypothetical_usd": s.rerun_within_ttl_hypothetical_usd,
        "savings_pct_first_run": s.savings_pct_first_run,
        "savings_pct_rerun": s.savings_pct_rerun,
        "aggregate_savings_first_run_usd": s.aggregate_savings_first_run_usd,
        "aggregate_savings_rerun_usd": s.aggregate_savings_rerun_usd,
        "blocking_errors": s.blocking_errors,
        "actionable_opportunities": s.actionable_opportunities,
        "warnings_count": s.warnings_count,
        "info_count": s.info_count,
        "total_llm_calls_estimated": s.total_llm_calls_estimated,
        "total_input_tokens_estimated": s.total_input_tokens_estimated,
        "total_cacheable_tokens_estimated": s.total_cacheable_tokens_estimated,
        "models_in_use": list(s.models_in_use),
        "partial_cost_usd": s.partial_cost_usd,
        "unavailable_models": list(s.unavailable_models),
        "unavailable_models_by_workflow": {
            str(workflow_path): list(models)
            for workflow_path, models in (s.unavailable_models_by_workflow or {}).items()
        },
        # Stage C.1 (2.0 minor-additive): heterogeneous batch sub-workflows
        # whose ``model: ${item.model}`` can't be aggregated as one model.
        # Excluded from ``models_in_use`` so the literal template doesn't
        # leak into the rendered list. Node paths surfaced separately so
        # agents can see WHICH nodes vary without scanning ``per_call[]``.
        "heterogeneous_model_node_count": s.heterogeneous_model_node_count,
        "heterogeneous_model_node_paths": list(s.heterogeneous_model_node_paths),
        "sub_workflow_rollup": _sub_workflow_rollup_to_dict(s.sub_workflow_rollup),
    }


def _sub_workflow_rollup_to_dict(rollup: Any) -> dict[str, Any] | None:
    if rollup is None:
        return None
    return {
        "workflows_included": list(rollup.workflows_included),
        "max_depth_walked": rollup.max_depth_walked,
        "truncated": rollup.truncated,
        "per_workflow": [
            {
                "workflow_path": entry.workflow_path,
                "called_by_node_id": entry.called_by_node_id,
                "llm_node_count": entry.llm_node_count,
                # Phase 5 (4.0): atomic primitives, mirrors AnalysisSummary
                # at child-workflow scope. ``actually_paid_usd`` is sourced
                # from the trace execution index for this child's
                # workflow_path; the hypotheticals come from this child's
                # IR row projections.
                "actually_paid_usd": entry.actually_paid_usd,
                "no_cache_hypothetical_usd": entry.no_cache_hypothetical_usd,
                "first_run_with_cache_hypothetical_usd": entry.first_run_with_cache_hypothetical_usd,
                "rerun_within_ttl_hypothetical_usd": entry.rerun_within_ttl_hypothetical_usd,
            }
            for entry in rollup.per_workflow
        ],
    }


def _action_to_dict(action: RecommendedAction) -> dict[str, Any]:
    return {
        "rank": action.rank,
        "warning_id": action.warning_id,
        "node_id": action.node_id,
        "estimated_savings_usd": action.estimated_savings_usd,
        # ``scope_workflow`` is set when the finding spans multiple nodes in one
        # workflow file (workflow-level scope) rather than being attributable to
        # one specific node. JSON consumers dispatch on (node_id, scope_workflow):
        # at most one is non-null.
        "scope_workflow": action.scope_workflow,
    }


def _block_to_dict(block: SuggestedBlock) -> dict[str, Any]:
    return {
        "target_file": block.target_file,
        "ttl": block.ttl,
        "chunks": [
            {
                "name": c.name,
                "var": c.var,
                "size_tokens_est": c.size_tokens_est,
                "prose_placeholder": c.prose_placeholder,
            }
            for c in block.chunks
        ],
        "per_node_assignments": dict(block.per_node_assignments),
        "estimated_savings_usd": block.estimated_savings_usd,
    }


def _per_call_to_dict(row: PerCallRow) -> dict[str, Any]:
    return {
        "node_path": row.node_path,
        "workflow_path": row.workflow_path,
        "model": row.model,
        "is_batch": row.is_batch,
        "batch_size_estimated": row.batch_size_estimated,
        "input_tokens_estimated": row.input_tokens_estimated,
        "output_tokens_estimated": row.output_tokens_estimated,
        "output_data_source": row.output_data_source,
        "cacheable_tokens_estimated": row.cacheable_tokens_estimated,
        "cache_ratio_pct": row.cache_ratio_pct,
        "data_source": row.data_source,
        # Independent tier label for the cacheable metric. Sources:
        # ``"trace"``, ``"memo"``, ``"estimator"``, ``"unavailable"``.
        # Independent from ``data_source`` (input) — the two may legitimately
        # diverge (e.g., trace fires for input but cacheable falls through
        # to memo when ``cache_creation+cache_read == 0``).
        "cacheable_data_source": row.cacheable_data_source,
        "declared_prompt_cache": row.declared_prompt_cache,
        # Stage C.1 (2.0 minor-additive): True when the IR's ``params.model``
        # was an unresolved ``${...}`` template (heterogeneous batch
        # sub-workflow). When True, ``model`` is the empty string so consumers
        # have a single clear discriminator.
        "model_is_heterogeneous": row.model_is_heterogeneous,
        # Track A (2.1 minor-additive): per-node recorded cost from trace.
        # ``null`` when no trace data — see ``cost_data_source`` for the
        # 4-state tier label.
        "cost_usd": row.cost_usd,
        "cost_data_source": row.cost_data_source,
        "did_not_execute_in_trace": row.did_not_execute_in_trace,
        # Stage 0.3 (Task 159): per-call ``warnings`` array dropped — production
        # never populated it. JSON consumers needing per-row warning markers
        # filter ``warnings[]`` (top-level) by ``node_id``.
    }


def _cross_workflow_to_dict(analysis: CacheAnalysis) -> dict[str, Any]:
    """Empty-array contract: always present, even when no findings.

    Stage 0 (Task 159): the three arrays are DERIVED from ``analysis.warnings``
    by filtering on ``Diagnostic.id``. Pre-Stage-0, the same Diagnostics were
    duplicated on ``analysis.cross_workflow.{rename_detections, prose_mismatches,
    value_flow_opportunities}`` AND in ``analysis.warnings`` — that
    pre-computed-view smell is gone. JSON shape preserved for consumer
    compatibility (1.x → 2.x bump documents the source change in the
    version-history block at module top).

    Filter discriminators:
    - ``rename_detections``: ``Diagnostic.id == "cache.cross-workflow-rename-detected"``
    - ``prose_mismatches``: ``Diagnostic.id == "cache.cross-workflow-prose-mismatch"``
    - ``value_flow_opportunities``: ``Diagnostic.id == "cache.shared-context-undeclared"``
      AND ``"child_workflow" in (Diagnostic.context or {})`` (the boundary-scope
      dispatch — workflow-scope shared-context findings are NOT
      cross-workflow).
    """
    cf = analysis.cross_workflow
    return {
        "boundaries_analyzed": cf.boundaries_analyzed,
        "rename_detections": [
            _warning_to_dict(d) for d in analysis.warnings if d.id == "cache.cross-workflow-rename-detected"
        ],
        "prose_mismatches": [
            _warning_to_dict(d) for d in analysis.warnings if d.id == "cache.cross-workflow-prose-mismatch"
        ],
        "value_flow_opportunities": [
            _warning_to_dict(d)
            for d in analysis.warnings
            if d.id == "cache.shared-context-undeclared" and "child_workflow" in (d.context or {})
        ],
    }


def _warning_to_dict(diag: Diagnostic) -> dict[str, Any]:
    return diag.to_dict()


__all__ = ["render_json"]
