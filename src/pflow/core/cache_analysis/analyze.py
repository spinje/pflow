"""Tier 2 + Tier 3 cache analyzer entry point.

``analyze(workflow, parameters)`` composes:

- F1.2 ``token_estimation`` (per-call tier),
- F1.3 ``cross_workflow`` walker (Tier 2),
- F1.4 ``padding_advisor`` (sensitivity-floored advisories),
- F2.2 ``summarize`` (one-line nudge — separately surfaced).

…into a single :class:`CacheAnalysis` result. The analyzer is
*opt-in*: per DD#36 it never gates ``pflow run``; it only fires from
``pflow analyze-cache`` and ``pflow run --dry-run``.

**Predicted cache_key byte-identity** (load-bearing, Round 4 high-value fix):
this module imports ``_resolve_chunk_value`` and ``_resolve_static_prefix_for_cache``
from ``pflow.core.cache_render`` so the analyzer's predicted cache_keys are
byte-identical to the runtime's. Inline reimplementation diverges from runtime
resolution and produces false ``cache.discrepancy`` reports.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Imported for the predicted-cache_key contract (Round 4 high-value fix #2):
# when ``cache.discrepancy`` detection wires up in v1.x, it MUST use the shared
# resolution helpers from ``core.cache_render`` so predicted cache_keys are
# byte-identical to runtime's. Eager import here locks the layer-policy
# contract — if a future contributor moves either helper, this file fails to
# import and the test suite catches it. v1 scaffolds the discrepancy slot but
# defers full prediction; the helpers will be consumed when that lands.
from pflow.core.cache_render import (  # noqa: F401 — see docstring.
    _CHUNK_ABSENT,
    _resolve_chunk_value,
    _resolve_static_prefix_for_cache,
)
from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.llm_capabilities import get_min_cache_tokens
from pflow.core.llm_providers import detect_provider

from .cross_workflow import walk_cross_workflow
from .token_estimation import estimate_output_tokens, estimate_tokens
from .warning_catalog import make_diagnostic

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PerCallRow:
    """One row of the per-call cache report."""

    node_path: str
    model: str
    is_batch: bool
    batch_size_estimated: int | None
    input_tokens_estimated: int
    cacheable_tokens_estimated: int
    cache_ratio_pct: int
    data_source: str  # "trace" | "memo" | "estimator" | "heuristic"
    declared_prompt_cache: list[str] | None
    warnings: tuple[str, ...] = ()
    # Output token data — None on greenfield (never run); ``output_data_source ∈
    # {"trace", "memo", "unavailable"}``. See ``cost_estimation.py`` for how
    # ``None`` propagates through the absolute-cost figures (per the
    # tri-state contract).
    output_tokens_estimated: int | None = None
    output_data_source: str = "unavailable"


@dataclass(frozen=True)
class RecommendedAction:
    """One pre-sorted dispatch row for the recommended-actions section."""

    rank: int
    warning_id: str
    node_id: str | None
    estimated_savings_usd: float | None


@dataclass(frozen=True)
class SuggestedBlockChunk:
    name: str
    var: str
    size_tokens_est: int
    prose_placeholder: str


@dataclass(frozen=True)
class SuggestedBlock:
    target_file: str
    ttl: str
    chunks: tuple[SuggestedBlockChunk, ...]
    per_node_assignments: dict[str, list[str]]
    estimated_savings_usd: float | None


@dataclass(frozen=True)
class CrossWorkflowFindings:
    boundaries_analyzed: int
    rename_detections: tuple[Diagnostic, ...]
    prose_mismatches: tuple[Diagnostic, ...]
    value_flow_opportunities: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class AnalysisSummary:
    current_cost_per_run_usd: float | None
    optimized_cost_per_run_usd: float | None
    rerun_cost_per_run_usd: float | None
    savings_pct_first_run: int | None
    savings_pct_rerun: int | None
    blocking_errors: int
    actionable_opportunities: int
    warnings_count: int
    info_count: int
    total_llm_calls_estimated: int
    total_input_tokens_estimated: int
    total_cacheable_tokens_estimated: int
    models_in_use: tuple[str, ...]
    partial_cost_usd: bool
    unavailable_models: tuple[str, ...]
    # Aggregate dollar savings if ``prompt_cache:`` declarations are utilized.
    # Computed from input-only math (output cost cancels in current - optimized
    # / current - rerun), so these are populated even on greenfield workflows
    # whose absolute cost figures stay ``None``. ``None`` only when no priced
    # rows have any ``prompt_cache:`` declared.
    aggregate_savings_first_run_usd: float | None = None
    aggregate_savings_rerun_usd: float | None = None


@dataclass(frozen=True)
class CacheAnalysis:
    """Structured analyzer result. Renderers transform this into text or JSON."""

    workflow_path: str
    analyzed_at: str
    estimate_confidence: str
    estimate_confidence_coverage: dict[str, int]
    trace_path: str | None
    summary: AnalysisSummary
    recommended_actions: tuple[RecommendedAction, ...]
    suggested_blocks: tuple[SuggestedBlock, ...]
    per_call: tuple[PerCallRow, ...]
    cross_workflow: CrossWorkflowFindings
    warnings: tuple[Diagnostic, ...]
    notes: tuple[str, ...]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def analyze(
    workflow_ir: dict[str, Any],
    *,
    parameters: dict[str, Any] | None = None,
    workflow_path: str | None = None,
    base_path: Path | None = None,
    trace_path: Path | None = None,
    auto_load_trace: bool = True,
    memo_cache: Any = None,
) -> CacheAnalysis:
    """Compose the full analysis.

    ``parameters`` is optional per DD#35; token estimation falls back when
    input substitution can't fully resolve a prompt.

    ``trace_path`` is an explicit override (mode-4 from-trace). When ``None``
    and ``auto_load_trace`` is ``True``, the analyzer scans
    ``~/.pflow/debug/`` for the most recent 2.1.0 trace whose ``workflow_path``
    matches; 2.0.0 traces are skipped (with an info note appended to the
    result), per DD#34.

    ``memo_cache`` is a ``MemoizationCache`` instance for the ``memo`` token
    tier. Pass ``None`` to disable that tier.
    """
    notes: list[str] = []
    trace_data: dict[str, Any] | None = None
    used_trace_path: str | None = None

    # --- Trace loading --------------------------------------------------------
    if trace_path is not None:
        trace_data = _load_trace_explicit(trace_path, notes)
        used_trace_path = str(trace_path)
    elif auto_load_trace:
        trace_data, used_trace_path = _autoload_trace(workflow_path, notes)

    # --- Per-call rows --------------------------------------------------------
    per_call_rows: list[PerCallRow] = []
    warnings: list[Diagnostic] = []
    suggested_blocks: list[SuggestedBlock] = []

    cache_block = workflow_ir.get("cache")
    declared_chunks: list[str] = []
    if isinstance(cache_block, dict):
        items = cache_block.get("items") or []
        if isinstance(items, list):
            declared_chunks = [item.get("name", "") for item in items if isinstance(item, dict) and item.get("name")]

    for node in workflow_ir.get("nodes", []) or []:
        if not isinstance(node, dict) or node.get("type") != "llm":
            continue
        row = _build_per_call_row(
            node=node,
            workflow_path=workflow_path,
            trace_data=trace_data,
            memo_cache=memo_cache,
            declared_chunks=declared_chunks,
        )
        per_call_rows.append(row)
        # Per-node analytical findings.
        warnings.extend(_per_node_warnings(node, row))

    # --- Cross-workflow walker ------------------------------------------------
    cross_findings = _build_cross_workflow_findings(
        root_ir=workflow_ir,
        base_path=base_path,
        root_workflow_path=workflow_path,
        notes=notes,
    )
    warnings.extend(cross_findings.rename_detections)
    warnings.extend(cross_findings.prose_mismatches)
    warnings.extend(cross_findings.value_flow_opportunities)

    # --- Confidence aggregation (STRICT per DD#34) ---------------------------
    confidence, coverage = _aggregate_confidence(per_call_rows)

    # --- Summary --------------------------------------------------------------
    cache_ttl: str | None = None
    if isinstance(cache_block, dict):
        ttl_value = cache_block.get("ttl")
        if ttl_value in ("5m", "1h"):
            cache_ttl = ttl_value
    summary = _build_summary(per_call_rows, warnings, ttl=cache_ttl)

    # --- Recommended actions (impact-descending) ----------------------------
    recommended = _build_recommended_actions(warnings)

    # --- Gemini telemetry note (Spike 1 outcome — last in note ordering) -----
    if trace_data is not None:
        _maybe_append_gemini_note(per_call_rows, notes)

    return CacheAnalysis(
        workflow_path=workflow_path or "<inline>",
        analyzed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        estimate_confidence=confidence,
        estimate_confidence_coverage=coverage,
        trace_path=used_trace_path,
        summary=summary,
        recommended_actions=tuple(recommended),
        suggested_blocks=tuple(suggested_blocks),
        per_call=tuple(per_call_rows),
        cross_workflow=cross_findings,
        warnings=tuple(warnings),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# Trace loading
# ---------------------------------------------------------------------------


def _load_trace_explicit(path: Path, notes: list[str]) -> dict[str, Any] | None:
    """Load an explicit ``--from-trace`` path.

    Per F3.1 contract: missing path or invalid JSON → caller reports as
    non-zero exit. Here we raise so the CLI layer can format the error.
    2.0.0 traces load successfully but emit a graceful info note.
    """
    if not path.exists():
        raise FileNotFoundError(f"Trace file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Trace file {path} is not a valid pflow trace (JSON parse error).") from exc
    if not isinstance(data, dict) or "format_version" not in data:
        raise ValueError(f"Trace file {path} is not a valid pflow trace (missing format_version field).")
    fv = str(data.get("format_version", ""))
    if not fv.startswith("2."):
        raise ValueError(f"Trace file {path} format_version={fv!r}; analyze-cache requires 2.x.")
    if not fv.startswith("2.1"):
        notes.append(
            f"Loaded {fv} trace from {path} — discrepancy analysis omitted "
            "(requires 2.1.0 cache_key/cache_age_sec fields). Re-run the workflow "
            "to produce a 2.1.0 trace, OR use --no-trace-autoload to skip trace loading."
        )
    return data


def _scan_trace_dir(debug_dir: Path, workflow_path: str) -> tuple[list[tuple[Path, dict[str, Any]]], int, int]:
    """Walk ``debug_dir`` collecting traces matching ``workflow_path``.

    Returns ``(matching_2_1, matching_2_0_count, unparseable_count)``. Traces
    are visited newest-first so ``matching_2_1[0]`` is the newest 2.1.0 hit.
    """
    matching_2_1: list[tuple[Path, dict[str, Any]]] = []
    matching_2_0_count = 0
    unparseable_count = 0

    for trace_file in sorted(debug_dir.glob("workflow-trace-*.json"), reverse=True):
        try:
            data = json.loads(trace_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            unparseable_count += 1
            logger.debug("Skipping unparseable trace %s", trace_file, exc_info=True)
            continue
        if not isinstance(data, dict):
            unparseable_count += 1
            continue
        if data.get("workflow_path") != workflow_path:
            continue
        fv = str(data.get("format_version", ""))
        if fv.startswith("2.1"):
            matching_2_1.append((trace_file, data))
        elif fv.startswith("2."):
            matching_2_0_count += 1

    return matching_2_1, matching_2_0_count, unparseable_count


def _autoload_trace(workflow_path: str | None, notes: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    """Scan ``~/.pflow/debug/`` for the newest matching 2.1.0 trace.

    2.0.0 traces with a matching workflow path are SKIPPED with an info note
    (DD#34 — auto-load requires 2.1.0). Unparseable files emit a single info
    note when ≥1 skipped.

    Note ordering (Round 5 fix): 2.0.0-skip note first, unparseable-skip note
    second. F2 callers append the Gemini telemetry note third when applicable.
    """
    debug_dir = Path.home() / ".pflow" / "debug"
    if not debug_dir.exists() or workflow_path is None:
        return None, None

    matching_2_1, matching_2_0_count, unparseable_count = _scan_trace_dir(debug_dir, workflow_path)

    # Note ordering: 2.0.0-skip FIRST.
    if matching_2_0_count > 0:
        notes.append(
            f"Found {matching_2_0_count} 2.0.0 traces matching this workflow but "
            "skipped (auto-load requires 2.1.0). Use --from-trace <path> to load "
            "a specific trace, or --no-trace-autoload to disable auto-loading."
        )
    # Unparseable-skip SECOND.
    if unparseable_count > 0:
        notes.append(
            f"Found {unparseable_count} unparseable trace files in ~/.pflow/debug/ (run with --verbose for details)."
        )

    if matching_2_1:
        path, data = matching_2_1[0]
        return data, str(path)
    return None, None


# ---------------------------------------------------------------------------
# Per-node analysis
# ---------------------------------------------------------------------------


def _build_per_call_row(
    *,
    node: dict[str, Any],
    workflow_path: str | None,
    trace_data: dict[str, Any] | None,
    memo_cache: Any,
    declared_chunks: list[str],
) -> PerCallRow:
    """Compose a single PerCallRow for an LLM node."""
    node_id = str(node.get("id", "?"))
    model = str(node.get("params", {}).get("model") or node.get("model") or "")
    prompt = node.get("params", {}).get("prompt", "")
    if not isinstance(prompt, str):
        prompt = str(prompt) if prompt is not None else ""
    batch = node.get("batch")
    is_batch = isinstance(batch, dict) and bool(batch)
    batch_size = _estimate_batch_size(batch) if isinstance(batch, dict) and is_batch else None

    input_tokens, source = estimate_tokens(
        model,
        prompt,
        trace=trace_data,
        memo_cache=memo_cache,
        node_id=node_id,
        workflow_path=workflow_path,
    )
    output_tokens, output_source = estimate_output_tokens(
        trace=trace_data,
        memo_cache=memo_cache,
        node_id=node_id,
        workflow_path=workflow_path,
    )
    declared_subset = node.get("prompt_cache") or None
    if declared_subset is not None and not isinstance(declared_subset, list):
        declared_subset = None

    cacheable_tokens = _estimate_cacheable_tokens(
        prompt=prompt,
        declared_subset=declared_subset,
        declared_chunks=declared_chunks,
    )
    ratio = _safe_pct(cacheable_tokens, input_tokens)

    return PerCallRow(
        node_path=node_id,
        model=model,
        is_batch=is_batch,
        batch_size_estimated=batch_size,
        input_tokens_estimated=input_tokens,
        cacheable_tokens_estimated=cacheable_tokens,
        cache_ratio_pct=ratio,
        data_source=source,
        declared_prompt_cache=list(declared_subset) if declared_subset else None,
        output_tokens_estimated=output_tokens,
        output_data_source=output_source,
    )


def _per_node_warnings(node: dict[str, Any], row: PerCallRow) -> list[Diagnostic]:
    """Emit analytical-tier warnings for one LLM node.

    v1 covers the inexpensive checks: ``cache.below-min-tokens``,
    ``cache.prewarm-no-prefix``. The richer detection (``cache.dynamic-before-static``,
    ``cache.batch-prewarm-recommended`` with savings ratio, padding-advisory math)
    requires the per-call data already on ``row`` plus prompt-template parsing
    not implemented in v1's scaffold (see Phase F follow-ups).
    """
    diagnostics: list[Diagnostic] = []
    node_id = row.node_path

    # cache.below-min-tokens — declared cache content below provider minimum.
    if row.declared_prompt_cache and row.cacheable_tokens_estimated > 0 and row.model:
        min_tokens = get_min_cache_tokens(row.model)
        if row.cacheable_tokens_estimated < min_tokens:
            diagnostics.append(
                make_diagnostic(
                    "cache.below-min-tokens",
                    node_id=node_id,
                    model=row.model,
                    cacheable_tokens=int(row.cacheable_tokens_estimated),
                    min_tokens=int(min_tokens),
                )
            )

    # cache.prewarm-no-prefix — prewarm: true with no static prefix before
    # the first ${batch_alias.X} reference. Detected by inspecting the unresolved
    # template at position 0.
    prewarm = node.get("prewarm")
    batch = node.get("batch")
    if prewarm is True and isinstance(batch, dict):
        alias = str(batch.get("as", "item"))
        prompt = node.get("params", {}).get("prompt", "") or ""
        if isinstance(prompt, str):
            marker = "${" + alias + "."
            position = prompt.find(marker)
            if position == 0:
                diagnostics.append(
                    make_diagnostic(
                        "cache.prewarm-no-prefix",
                        node_id=node_id,
                        batch_alias=alias,
                        first_dynamic_position=0,
                    )
                )

    return diagnostics


def _estimate_batch_size(batch: dict[str, Any]) -> int | None:
    """Heuristic estimate of batch size from inline-static items list."""
    items = batch.get("items")
    if isinstance(items, list):
        return len(items)
    return None


def _estimate_cacheable_tokens(*, prompt: str, declared_subset: list[str] | None, declared_chunks: list[str]) -> int:
    """Conservative estimate of how many prompt tokens are cacheable.

    v1: assume each declared chunk in the node's subset contributes a uniform
    fraction of the total prompt token budget; if no subset declared but the
    file has a ``## Cache`` block, return 0 (the chunks aren't yet referenced
    by this node). For more nuanced numbers we'd need per-chunk token counts
    from the F1.2 estimator — deferred until the algorithm proves out.
    """
    if not declared_subset:
        return 0
    # Stub: 75% of prompt is cacheable when there's a declared subset (proxy
    # for "the system prefix dominates the prompt budget"). Refined in v1.x.
    return max(0, len(prompt) * 75 // 400)


def _safe_pct(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round(100 * numerator / denominator)


# ---------------------------------------------------------------------------
# Cross-workflow walking
# ---------------------------------------------------------------------------


def _build_cross_workflow_findings(
    *,
    root_ir: dict[str, Any],
    base_path: Path | None,
    root_workflow_path: str | None,
    notes: list[str],
) -> CrossWorkflowFindings:
    """Run the F1.3 walker and emit rename / prose-mismatch / value-flow diagnostics.

    The walker appends notes to the supplied list when it stops descending
    a branch (max_depth or cycle) — the analyzer surfaces these via
    ``CacheAnalysis.notes`` so agents see truncation rather than silent
    incompleteness.
    """
    # ``walk_cross_workflow`` may raise FileNotFoundError / ValueError on broken
    # sub-workflow refs; we let it propagate so the analyzer surfaces the same
    # validation error the runner would (per F1.3 contract).
    edges = walk_cross_workflow(
        root_ir,
        base_path=base_path,
        root_workflow_path=root_workflow_path,
        notes=notes,
    )

    rename_diags: list[Diagnostic] = []
    for edge in edges:
        if edge.is_rename and edge.parent_value_expr is not None:
            rename_diags.append(
                make_diagnostic(
                    "cache.cross-workflow-rename-detected",
                    parent_workflow=edge.parent_workflow,
                    child_workflow=edge.child_workflow,
                    parent_value_expr=edge.parent_value_expr,
                    child_input_name=edge.child_input_name,
                    line_in_parent=edge.line_in_parent,
                    parent_node_id=edge.parent_node_id,
                )
            )

    return CrossWorkflowFindings(
        boundaries_analyzed=len(edges),
        rename_detections=tuple(rename_diags),
        prose_mismatches=(),  # v1 stub — prose-mismatch detection requires both files' parse trees
        value_flow_opportunities=(),  # v1 stub — same
    )


# ---------------------------------------------------------------------------
# Confidence aggregation — STRICT per DD#34 verbatim
# ---------------------------------------------------------------------------


def _aggregate_confidence(
    rows: list[PerCallRow],
) -> tuple[str, dict[str, int]]:
    """STRICT semantics per DD#34 line 634.

    - ``all rows trace`` → ``high_from_trace``
    - ``all rows in {trace, memo}`` → ``medium_from_memo``
    - ``any estimator/heuristic`` → ``low_no_data``
    """
    sources = [row.data_source for row in rows]
    coverage: dict[str, int] = {
        "trace": sum(1 for s in sources if s == "trace"),
        "memo": sum(1 for s in sources if s == "memo"),
        "estimator": sum(1 for s in sources if s == "estimator"),
        "heuristic": sum(1 for s in sources if s == "heuristic"),
        "total": len(sources),
    }
    if not sources:
        return "low_no_data", coverage
    if all(src == "trace" for src in sources):
        return "high_from_trace", coverage
    if all(src in ("trace", "memo") for src in sources):
        return "medium_from_memo", coverage
    return "low_no_data", coverage


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------


def _build_summary(rows: list[PerCallRow], warnings: list[Diagnostic], *, ttl: str | None = None) -> AnalysisSummary:
    """Aggregate per-call rows + warning counts into the spec's summary block.

    Absolute cost figures (current/optimized/rerun) require output token data
    per the tri-state contract — ``None`` on greenfield, real after at least
    one run, partial when some priced rows have memo data and others don't.

    Aggregate savings figures are input-only (output cost cancels) and
    therefore work on greenfield even when absolutes stay ``None``.
    """
    # Lazy-import to avoid a circular when ``cost_estimation.py`` imports
    # ``PerCallRow`` from this module at module load time.
    from .cost_estimation import compute_aggregate_costs

    total_calls = len(rows)
    total_input = sum(r.input_tokens_estimated for r in rows)
    total_cacheable = sum(r.cacheable_tokens_estimated for r in rows)
    models = sorted({r.model for r in rows if r.model})
    blocking_errors = sum(1 for d in warnings if d.severity == Severity.ERROR)
    warnings_count = sum(1 for d in warnings if d.severity == Severity.WARNING)
    info_count = sum(1 for d in warnings if d.severity == Severity.INFO)
    actionable = warnings_count + info_count

    output_tokens_by_node: dict[str, int | None] = {r.node_path: r.output_tokens_estimated for r in rows}
    cost = compute_aggregate_costs(rows, output_tokens_by_node=output_tokens_by_node, ttl=ttl)

    savings_pct_first_run = _safe_pct_or_none(cost.savings_first_run_usd, cost.current_usd)
    savings_pct_rerun = _safe_pct_or_none(cost.savings_rerun_usd, cost.current_usd)

    return AnalysisSummary(
        current_cost_per_run_usd=cost.current_usd,
        optimized_cost_per_run_usd=cost.optimized_usd,
        rerun_cost_per_run_usd=cost.rerun_usd,
        savings_pct_first_run=savings_pct_first_run,
        savings_pct_rerun=savings_pct_rerun,
        blocking_errors=blocking_errors,
        actionable_opportunities=actionable,
        warnings_count=warnings_count,
        info_count=info_count,
        total_llm_calls_estimated=total_calls,
        total_input_tokens_estimated=total_input,
        total_cacheable_tokens_estimated=total_cacheable,
        models_in_use=tuple(models),
        partial_cost_usd=cost.partial,
        unavailable_models=cost.unavailable_models,
        aggregate_savings_first_run_usd=cost.savings_first_run_usd,
        aggregate_savings_rerun_usd=cost.savings_rerun_usd,
    )


def _safe_pct_or_none(numerator: float | None, denominator: float | None) -> int | None:
    """Compute a percent only when both numerator and denominator are real."""
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(100 * numerator / denominator)


# ---------------------------------------------------------------------------
# Recommended actions
# ---------------------------------------------------------------------------


def _build_recommended_actions(
    warnings: list[Diagnostic],
) -> list[RecommendedAction]:
    """Order warnings by impact descending; rank starts at 1.

    Impact heuristic: ``context.savings_usd`` if present, else the severity
    rank (ERROR > WARNING > INFO). Stable secondary sort on ``id``.
    """

    def _key(d: Diagnostic) -> tuple[int, float, str]:
        # Severity weight (higher = more impactful when no savings_usd).
        sev_weight = {Severity.ERROR: 2, Severity.WARNING: 1, Severity.INFO: 0}.get(d.severity, 0)
        savings = 0.0
        ctx = d.context or {}
        savings_value = ctx.get("savings_usd")
        if isinstance(savings_value, (int, float)):
            savings = float(savings_value)
        return (-sev_weight, -savings, d.id or "")

    sorted_warnings = sorted(warnings, key=_key)
    actions: list[RecommendedAction] = []
    for rank, d in enumerate(sorted_warnings, start=1):
        ctx = d.context or {}
        savings = ctx.get("savings_usd")
        if not isinstance(savings, (int, float)):
            savings = None
        actions.append(
            RecommendedAction(
                rank=rank,
                warning_id=d.id or "",
                node_id=d.node_id,
                estimated_savings_usd=float(savings) if savings is not None else None,
            )
        )
    return actions


# ---------------------------------------------------------------------------
# Gemini telemetry note (Spike 1 outcome — last in note ordering)
# ---------------------------------------------------------------------------


_GEMINI_TELEMETRY_NOTE = (
    "Gemini telemetry note: LiteLLM's Vertex/Gemini translation surfaces "
    "explicit-cache reads via 'cache_read_input_tokens' (or "
    "'prompt_tokens_details.cached_tokens'); 'cache_creation_input_tokens' is "
    "0/absent even when caching is working. Verification path is reads on "
    "subsequent calls. Spike 1 disambiguator (progress log §36) confirmed the "
    "marker does real work — no caching fires without it."
)


def _maybe_append_gemini_note(rows: list[PerCallRow], notes: list[str]) -> None:
    """Append the Gemini telemetry note if any analyzed call targets Gemini."""
    for row in rows:
        if not row.model:
            continue
        try:
            provider_info = detect_provider(row.model)
        except Exception:
            # detect_provider raises on malformed model strings; the row is
            # still analyzable — skip the gemini note for it but surface at
            # debug so a typo isn't completely silent.
            logger.debug("detect_provider failed for model %r", row.model, exc_info=True)
            continue
        if provider_info is None:
            continue
        if provider_info.name == "gemini":
            notes.append(_GEMINI_TELEMETRY_NOTE)
            return


__all__ = [
    "AnalysisSummary",
    "CacheAnalysis",
    "CrossWorkflowFindings",
    "PerCallRow",
    "RecommendedAction",
    "SuggestedBlock",
    "SuggestedBlockChunk",
    "analyze",
]
