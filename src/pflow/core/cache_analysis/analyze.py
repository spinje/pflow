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

import hashlib
import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
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
    deterministic_serialize,
)
from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.llm_capabilities import get_min_cache_tokens
from pflow.core.llm_config import get_default_workflow_model
from pflow.core.llm_providers import detect_provider
from pflow.core.workflow.data_flow import validate_data_flow
from pflow.core.workflow_id import synthesize_inline_workflow_id
from pflow.runtime.template_resolver import TemplateResolver

from .cross_workflow import walk_cross_workflow
from .padding_advisor import PaddingCandidate, compute_padding_advisories
from .token_estimation import estimate_output_tokens, estimate_tokens
from .warning_catalog import make_diagnostic

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PerCallRow:
    """One row of the per-call cache report.

    Tri-state nullability for tokens / cacheable / ratio:

    - ``input_tokens_estimated`` is always populated (template tokenization
      always succeeds; ``estimate_tokens`` falls back to char-heuristic).
    - ``cacheable_tokens_estimated`` is ``None`` when no run data exists for
      the projection (Option C — pure greenfield, no memo/trace). ``int``
      otherwise. Renderer hides such rows from the per-call section; JSON
      exposes ``null`` for machine consumers.
    - ``cache_ratio_pct`` mirrors ``cacheable_tokens_estimated`` — ``None``
      when cacheable is None; derived ``int`` otherwise.
    """

    node_path: str
    model: str
    is_batch: bool
    batch_size_estimated: int | None
    input_tokens_estimated: int
    cacheable_tokens_estimated: int | None
    cache_ratio_pct: int | None
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
    """One pre-sorted dispatch row for the recommended-actions section.

    Scope fields (``node_id``, ``scope_workflow``) — at most one is set:

    - **Per-node**: ``node_id`` set, ``scope_workflow=None``. The finding is
      attributable to a specific node in the workflow IR.
    - **Workflow-level**: ``node_id=None``, ``scope_workflow=<path>``. The
      finding spans multiple nodes in one workflow file (e.g., shared-context
      detection that finds N nodes referencing the same value).
    - **Unscoped**: both ``None``. Defensive fallback; current emitters
      always populate one or the other.

    Carrying scope on the action (rather than re-deriving from the warning's
    context at render time) lets the JSON consumer read scope without an
    id-to-context lookup, AND keeps text rendering trivial.
    """

    rank: int
    warning_id: str
    node_id: str | None
    estimated_savings_usd: float | None
    scope_workflow: str | None = None
    # CP5 #5: the diagnostic's rendered message — without this, four
    # ``[cache.shared-context-undeclared]`` recommendations on lyrics-generator
    # song-creator looked byte-identical (only the scope line distinguished
    # them) because the recommendations renderer didn't show messages. Carrying
    # the message lets the agent see WHAT each finding is about without having
    # to scroll to the cross-workflow / per-call sections.
    message: str = ""
    # Stage-1 final pass: short action-led title for the rank line. Sourced
    # from the catalog's ``headline_template`` via ``diag.context["headline"]``.
    # Renderer prefers this over message when present; empty falls back to
    # message (safety net for diagnostics not yet catalog-driven).
    headline: str = ""


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
    suggested_blocks: list[SuggestedBlock] = []

    # Canonical lookup identifier — mirrors ``runner.py``'s trace_workflow_path
    # AND ``MemoizationCache.workflow_path`` at write time (both use
    # ``resolved.file_path or synthesize_inline_workflow_id(ir)``). File/library
    # callers pass ``workflow_path=resolved.file_path``; inline callers pass
    # ``None`` and we derive the same ``ir-hash:<md5>`` the writer used.
    # Threaded through autoload (filename-hash glob), memo cache (SQL
    # ``workflow_path`` scoping), and cross-workflow walker (cycle detection /
    # labeling) — every site that correlates analyzer-time and runtime state.
    # ``"<inline>"`` is reserved for the displayed identifier — a human-readable
    # label kept separate from the lookup key.
    lookup_path = workflow_path if workflow_path is not None else synthesize_inline_workflow_id(workflow_ir)

    # CR-1305 W3: default-construct ``memo_cache`` from disk when the caller
    # didn't supply one. Production entry points (CLI / MCP / dry-run nudge)
    # don't manage ``MemoizationCache`` lifecycle; without this default,
    # ``data_source: "memo"`` was unreachable in production. Top-10% pattern:
    # construct dependencies at the lowest layer that has the data.
    if memo_cache is None:
        memo_cache = _default_memo_cache()

    trace_data, used_trace_path = _resolve_trace_data(trace_path, auto_load_trace, lookup_path, notes)

    cache_block = workflow_ir.get("cache")
    declared_chunks = _extract_declared_chunks(cache_block)

    per_call_rows, warnings = _build_per_call_rows_and_warnings(
        workflow_ir=workflow_ir,
        lookup_path=lookup_path,
        trace_data=trace_data,
        memo_cache=memo_cache,
        declared_chunks=declared_chunks,
    )
    rows_by_node = {row.node_path: row for row in per_call_rows}

    suggested_blocks, shared_warnings, cacheable_by_node = _populate_suggested_blocks(
        workflow_ir=workflow_ir,
        rows_by_node=rows_by_node,
        memo_cache=memo_cache,
        workflow_path=lookup_path,
        notes=notes,
    )
    warnings.extend(shared_warnings)

    # Stage-1 final pass (Concern B): enrich greenfield per-call rows with
    # PROJECTED cacheable token counts from the suggested-blocks pass. Memo
    # data drives projection; without it, ``cacheable_by_node`` carries None
    # for affected nodes → ``_enrich_with_projected_cacheable`` propagates
    # None → renderer hides the row (Option C).
    if cacheable_by_node:
        per_call_rows = [_enrich_with_projected_cacheable(row, cacheable_by_node) for row in per_call_rows]
        rows_by_node = {row.node_path: row for row in per_call_rows}

    # Option C — surface a Notes entry when the per-call section will render
    # empty so agents understand the absence is intentional. The renderer uses
    # the same predicate (``_row_has_real_data``) to decide visibility; we
    # mirror it here at analyze-time so the note appears in JSON too.
    if per_call_rows and not any(_row_has_real_data_in_analyze(r) for r in per_call_rows):
        notes.append(
            "Per-call cache report hidden — workflow has no run data yet. "
            "Run once to populate memo cache; analyze-cache then shows real "
            "per-node token estimates and cacheable projections."
        )
    warnings.extend(_emit_padding_advisories(workflow_ir=workflow_ir, rows_by_node=rows_by_node))
    warnings.extend(
        _consolidate_to_root_advisories(
            workflow_ir=workflow_ir,
            rows_by_node=rows_by_node,
            declared_chunks=declared_chunks,
            memo_cache=memo_cache,
            workflow_path=lookup_path,
        )
    )
    warnings.extend(_cache_validator_findings(workflow_ir))

    # --- Cross-workflow walker ------------------------------------------------
    cross_findings = _build_cross_workflow_findings(
        root_ir=workflow_ir,
        base_path=base_path,
        root_workflow_path=lookup_path,
        notes=notes,
    )
    warnings.extend(cross_findings.rename_detections)
    warnings.extend(cross_findings.prose_mismatches)
    warnings.extend(cross_findings.value_flow_opportunities)
    if trace_data is not None:
        warnings.extend(
            _emit_discrepancy_diagnostics(
                workflow_ir=workflow_ir,
                trace_data=trace_data,
                parameters=parameters or {},
                memo_cache=memo_cache,
                workflow_path=lookup_path,
                notes=notes,
            )
        )

    # --- Confidence aggregation (STRICT per DD#34) ---------------------------
    confidence, coverage = _aggregate_confidence(per_call_rows)

    summary = _build_summary(per_call_rows, warnings, ttl=_extract_cache_ttl(cache_block))
    recommended = _build_recommended_actions(warnings)

    # Gemini telemetry note (Spike 1 outcome — last in note ordering).
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
# Memo cache default-construction
# ---------------------------------------------------------------------------


def _default_memo_cache() -> Any:
    """Construct a read-only ``MemoizationCache`` from the default location.

    Returns ``None`` when ``~/.pflow/cache/cache.db`` doesn't exist (greenfield
    workflow that has never been run) or when construction fails (disk error,
    permissions, corrupted file). Either way the analyzer falls back to the
    ``estimator`` / ``heuristic`` tiers — no surprise SQLite file creation for
    a read-only analyze invocation.

    The existence-check before construction is load-bearing: ``MemoizationCache.__init__``
    creates the parent directory + opens a connection + runs ``_init_db()``
    which CREATES the schema. Skipping construction when the file is absent
    keeps analyze invocations side-effect-free on greenfield workflows.

    See CR-1305 W3 — pre-fix, the memo tier was unreachable from CLI/MCP/dry-run
    because no production caller passed a ``MemoizationCache``. Default-construct
    here unlocks ``data_source: "memo"`` in production at zero plumbing cost.
    """
    cache_path = Path.home() / ".pflow" / "cache" / "cache.db"
    if not cache_path.exists():
        return None
    try:
        from pflow.runtime.cache import MemoizationCache

        return MemoizationCache(db_path=cache_path, read_enabled=True)
    except Exception:
        logger.debug(
            "Failed to construct default memo_cache; analyzer falls back to estimator/heuristic",
            exc_info=True,
        )
        return None


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


def _autoload_trace(workflow_path: str | None, notes: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    """Find the newest 2.1.0 trace whose ``workflow_path`` matches.

    O(matching-traces) lookup, not O(directory-size): trace filenames encode
    an 8-char md5 hash of ``workflow_path`` at write time (see
    ``runtime/workflow_trace.format_trace_filename``). The reader globs by the
    same hash prefix so we only read files that could match.

    Pre-2.1.0 traces and 2.1.0 traces written before the hash-prefix scheme
    are not findable via auto-load — pass ``--from-trace <path>`` to load
    them explicitly. Per DD#34, auto-load is a convenience; explicit loading
    is the contract.

    The ``notes`` parameter is preserved for future use (e.g., a Gemini
    telemetry note appended by F2 callers).
    """
    del notes  # currently unused; preserved for caller contract symmetry
    if workflow_path is None:
        return None, None
    debug_dir = Path.home() / ".pflow" / "debug"
    if not debug_dir.exists():
        return None, None

    wf_hash = hashlib.md5(workflow_path.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    pattern = f"workflow-trace-{wf_hash}-*.json"

    for trace_file in sorted(debug_dir.glob(pattern), reverse=True):
        try:
            data = json.loads(trace_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.debug("Skipping unparseable trace %s", trace_file, exc_info=True)
            continue
        if not isinstance(data, dict):
            continue
        # Hash-collision guard: 8 hex chars = 32 bits → vanishingly unlikely
        # for trace files, but the inner check makes it impossible.
        if data.get("workflow_path") != workflow_path:
            continue
        if str(data.get("format_version", "")).startswith("2.1"):
            return data, str(trace_file)
    return None, None


# ---------------------------------------------------------------------------
# Pipeline helpers (lift complexity out of ``analyze()``)
# ---------------------------------------------------------------------------


def _resolve_trace_data(
    trace_path: Path | None,
    auto_load_trace: bool,
    lookup_path: str,
    notes: list[str],
) -> tuple[dict[str, Any] | None, str | None]:
    """Load trace data via explicit path or autoload, returning ``(data, path)``."""
    if trace_path is not None:
        return _load_trace_explicit(trace_path, notes), str(trace_path)
    if auto_load_trace:
        return _autoload_trace(lookup_path, notes)
    return None, None


def _extract_declared_chunks(cache_block: Any) -> list[str]:
    """Extract chunk names from a workflow's ``## Cache`` block IR."""
    if not isinstance(cache_block, dict):
        return []
    items = cache_block.get("items") or []
    if not isinstance(items, list):
        return []
    return [item.get("name", "") for item in items if isinstance(item, dict) and item.get("name")]


def _extract_cache_ttl(cache_block: Any) -> str | None:
    """Read the validated TTL from a ``## Cache`` block (``"5m"`` / ``"1h"``)."""
    if not isinstance(cache_block, dict):
        return None
    ttl_value = cache_block.get("ttl")
    return ttl_value if ttl_value in ("5m", "1h") else None


def _build_per_call_rows_and_warnings(
    *,
    workflow_ir: dict[str, Any],
    lookup_path: str,
    trace_data: dict[str, Any] | None,
    memo_cache: Any,
    declared_chunks: list[str],
) -> tuple[list[PerCallRow], list[Diagnostic]]:
    """Walk LLM nodes, build per-call rows, collect per-node analytical warnings."""
    rows: list[PerCallRow] = []
    warnings: list[Diagnostic] = []
    nodes = workflow_ir.get("nodes", []) or []
    # Pre-build node-id → node lookup once so per-node detectors that need to
    # inspect upstream nodes (e.g. ``cache.opaque-prompt`` checks the upstream
    # type) don't re-scan the IR per LLM node.
    nodes_by_id: dict[str, dict[str, Any]] = {
        str(n.get("id", "")): n for n in nodes if isinstance(n, dict) and n.get("id")
    }
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "llm":
            continue
        row = _build_per_call_row(
            node=node,
            workflow_path=lookup_path,
            trace_data=trace_data,
            memo_cache=memo_cache,
            declared_chunks=declared_chunks,
        )
        rows.append(row)
        warnings.extend(_per_node_warnings(node, row, declared_chunks=declared_chunks, nodes_by_id=nodes_by_id))
    return rows, warnings


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
    # Effective model resolution mirrors compiler.py:281-285 — explicit per-node
    # ``model:`` wins; absence falls back to ``get_default_workflow_model()``
    # (settings.default_model → API-key auto-detect → None). Without this fallback
    # the per-call table renders ``model=`` empty for nodes that inherit the
    # default, ``models_in_use`` undercounts, and cost computation can never
    # price these rows. Tests that need deterministic model values monkeypatch
    # ``pflow.core.cache_analysis.analyze.get_default_workflow_model``.
    explicit = node.get("params", {}).get("model") or node.get("model")
    model = str(explicit) if explicit else (get_default_workflow_model() or "")
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
    # Initial cacheable/ratio:
    # - Steady-state (declared subset): heuristic value > 0; show real ratio.
    # - Greenfield (no declared subset): cacheable=0 placeholder. ``analyze()``
    #   may overwrite via ``_enrich_with_projected_cacheable`` if memo data
    #   exists; otherwise the row is hidden by the renderer (Option C).
    cacheable_tokens_with_clamp: int | None
    if cacheable_tokens > 0:
        cacheable_tokens_with_clamp = min(cacheable_tokens, input_tokens)
        ratio: int | None = _safe_pct(cacheable_tokens_with_clamp, input_tokens)
    else:
        cacheable_tokens_with_clamp = 0
        ratio = 0

    return PerCallRow(
        node_path=node_id,
        model=model,
        is_batch=is_batch,
        batch_size_estimated=batch_size,
        input_tokens_estimated=input_tokens,
        cacheable_tokens_estimated=cacheable_tokens_with_clamp,
        cache_ratio_pct=ratio,
        data_source=source,
        declared_prompt_cache=list(declared_subset) if declared_subset else None,
        output_tokens_estimated=output_tokens,
        output_data_source=output_source,
    )


def _row_has_real_data_in_analyze(row: PerCallRow) -> bool:
    """Mirror of ``render_text._row_has_real_data`` for analyze-time decisions.

    Kept as a private duplicate (analyze.py shouldn't depend on render_text.py)
    that MUST stay byte-equivalent — see ``render_text._row_has_real_data``
    for contract documentation.
    """
    return row.data_source in {"trace", "memo"} or bool(row.declared_prompt_cache)


def _enrich_with_projected_cacheable(row: PerCallRow, cacheable_by_node: dict[str, int | None]) -> PerCallRow:
    """Replace greenfield ``cacheable_tokens_estimated`` with projected value.

    When the suggested-blocks pass detected shared context for this node:

    - ``int`` value (memo populated): replace with the projected sum, clamped
      to ``input_tokens_estimated``. Ratio re-derives.
    - ``None`` value (memo empty for at least one chunk — Option C): set
      cacheable AND ratio to ``None`` so the renderer can hide the row.

    Nodes not in ``cacheable_by_node`` (no detected shared refs) are returned
    unchanged. Steady-state rows are NOT enriched here —
    ``_populate_suggested_blocks`` skips workflows with declared ``## Cache``,
    so this only fires for greenfield.
    """
    if row.node_path not in cacheable_by_node:
        return row
    projected = cacheable_by_node[row.node_path]
    if projected is None:
        # No memo data — cacheable unmeasurable. Tri-state contract: explicit
        # None instead of misleading 0.
        return replace(
            row,
            cacheable_tokens_estimated=None,
            cache_ratio_pct=None,
        )
    if projected <= 0:
        return row
    bounded = min(projected, row.input_tokens_estimated)
    return replace(
        row,
        cacheable_tokens_estimated=bounded,
        cache_ratio_pct=_safe_pct(bounded, row.input_tokens_estimated),
    )


def _per_node_warnings(
    node: dict[str, Any],
    row: PerCallRow,
    *,
    declared_chunks: list[str],
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    """Emit analytical-tier warnings for one LLM node.

    Full-path matching is load-bearing: cache chunk identifiers are
    ``creative-direction.response`` rather than root ids.

    ``nodes_by_id`` is the workflow-wide node lookup (id → node dict). Detectors
    that need to inspect upstream node types (e.g. ``cache.opaque-prompt``)
    consume it; detectors that only inspect the focal node ignore it.
    """
    diagnostics: list[Diagnostic] = []
    node_id = row.node_path

    # cache.below-min-tokens — declared cache content below provider minimum.
    # ``cacheable_tokens_estimated`` may be None for greenfield rows without
    # memo data; this warning gates on declared_prompt_cache so it only fires
    # in steady-state where cacheable is always int.
    cacheable = row.cacheable_tokens_estimated
    if row.declared_prompt_cache and cacheable is not None and cacheable > 0 and row.model:
        min_tokens = get_min_cache_tokens(row.model)
        if cacheable < min_tokens:
            diagnostics.append(
                make_diagnostic(
                    "cache.below-min-tokens",
                    node_id=node_id,
                    model=row.model,
                    cacheable_tokens=int(cacheable),
                    min_tokens=int(min_tokens),
                )
            )

    diagnostics.extend(_batch_prewarm_recommendations(node, row))
    diagnostics.extend(_dynamic_before_static_warnings(node, row, declared_chunks=declared_chunks))
    diagnostics.extend(_opaque_prompt_warnings(node, row, nodes_by_id=nodes_by_id))

    # cache.prewarm-no-prefix — prewarm: true with no static prefix before
    # the first batch-scoped reference. Detected by inspecting the unresolved
    # template at position 0.
    #
    # Boundary regex MUST match the runtime gate at ``nodes/llm/llm.py``
    # (``re.compile(r"\$\{" + re.escape(alias) + r"(\.|\[)")``) so analyzer
    # and runtime agree on what counts as batch-scoped — both ``${item.field}``
    # and ``${item[0].field}`` are batch references. Earlier dot-only matcher
    # silently missed every ``${alias[N]...}`` workflow (CR-1430 C1).
    prewarm = node.get("prewarm")
    batch = node.get("batch")
    if prewarm is True and isinstance(batch, dict):
        alias = str(batch.get("as", "item"))
        prompt = node.get("params", {}).get("prompt", "") or ""
        if isinstance(prompt, str):
            pattern = re.compile(r"\$\{" + re.escape(alias) + r"(\.|\[)")
            match = pattern.search(prompt)
            if match is not None and match.start() == 0:
                diagnostics.append(
                    make_diagnostic(
                        "cache.prewarm-no-prefix",
                        node_id=node_id,
                        batch_alias=alias,
                        first_dynamic_position=0,
                    )
                )

    return diagnostics


def _batch_prewarm_recommendations(node: dict[str, Any], row: PerCallRow) -> list[Diagnostic]:
    """Emit ``cache.batch-prewarm-recommended`` per DD#33.

    ``prewarm: false`` is an explicit opt-out and suppresses this warning; only
    absence of the field means the author has not made a decision.
    """
    batch = node.get("batch")
    if "prewarm" in node or not isinstance(batch, dict):
        return []
    batch_size = row.batch_size_estimated
    if batch_size is None or batch_size < 2:
        return []
    prompt = node.get("params", {}).get("prompt", "") or ""
    if not isinstance(prompt, str):
        return []

    alias = str(batch.get("as", "item"))
    match = re.compile(r"\$\{" + re.escape(alias) + r"(\.|\[)").search(prompt)
    if match is None or match.start() == 0:
        return []

    prefix_tokens = estimate_tokens(row.model, prompt[: match.start()])[0]
    dynamic_tokens = estimate_tokens(row.model, prompt[match.start() :])[0]
    if prefix_tokens < get_min_cache_tokens(row.model):
        return []

    savings_ratio = ((batch_size - 1) * 1.15 * prefix_tokens) / (batch_size * ((1.25 * prefix_tokens) + dynamic_tokens))
    savings_pct = round(100 * savings_ratio)
    if savings_pct < 5:
        return []

    return [
        make_diagnostic(
            "cache.batch-prewarm-recommended",
            node_id=row.node_path,
            batch_size=batch_size,
            prefix_tokens_estimated=prefix_tokens,
            savings_pct=savings_pct,
            savings_usd=_estimate_token_savings_usd(row.model, prefix_tokens, batch_size - 1),
        )
    ]


def _dynamic_before_static_warnings(
    node: dict[str, Any],
    row: PerCallRow,
    *,
    declared_chunks: list[str],
) -> list[Diagnostic]:
    """Detect a dynamic template reference before a large stable suffix."""
    if not row.declared_prompt_cache or not declared_chunks:
        return []
    prompt = node.get("params", {}).get("prompt", "") or ""
    if not isinstance(prompt, str):
        return []

    declared = set(declared_chunks)
    for match in TemplateResolver.TEMPLATE_PATTERN.finditer(prompt):
        var_expr = match.group(1)
        operands = TemplateResolver.split_coalesce_operands(var_expr)
        if any(operand in declared for operand in operands):
            continue

        cacheable_tokens = estimate_tokens(row.model, prompt[match.end() :])[0]
        if cacheable_tokens < get_min_cache_tokens(row.model):
            break

        affected_calls = row.batch_size_estimated if row.is_batch and row.batch_size_estimated else 1
        tokens_before = estimate_tokens(row.model, prompt[: match.start()])[0]
        return [
            make_diagnostic(
                "cache.dynamic-before-static",
                node_id=row.node_path,
                dynamic_ref=var_expr,
                dynamic_line=1 + prompt[: match.start()].count("\n"),
                cacheable_tokens=cacheable_tokens,
                affected_calls=affected_calls,
                savings_usd=_estimate_token_savings_usd(row.model, cacheable_tokens, affected_calls),
                projected_ratio_pct=_safe_pct(cacheable_tokens, cacheable_tokens + tokens_before),
            )
        ]
    return []


def _opaque_prompt_warnings(
    node: dict[str, Any],
    row: PerCallRow,
    *,
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    """Detect LLM nodes whose prompt is a single var-ref to a code-node output.

    Static walkers (``cache.dynamic-before-static``, ``cache.batch-prewarm-recommended``,
    ``cache.shared-context-undeclared``) read ``node.params.prompt`` as a literal
    template. When the prompt is just ``${X}`` and X resolves through a
    ``type: code`` node, those walkers see one ref and find nothing — even when
    the assembled prompt has substantial cache potential. This detector points
    the agent at the refactor.

    Two patterns trigger:
      - **Direct**: ``prompt: ${some_code.result.field}``.
      - **Through batch alias**: ``prompt: ${item.X}`` AND
        ``batch.items: ${some_code.result}``.

    Coalesce expressions (``${a ?? b}``) are skipped — they have multiple paths
    and the "opaque" framing doesn't fit cleanly.
    """
    prompt = node.get("params", {}).get("prompt", "")
    if not isinstance(prompt, str):
        return []
    stripped = prompt.strip()
    if not TemplateResolver.is_simple_template(stripped):
        return []

    inner = stripped[2:-1]
    if TemplateResolver.is_coalesce_expression(inner):
        return []
    root = TemplateResolver.extract_root_node_id(inner)

    upstream_node = nodes_by_id.get(root)
    if upstream_node is None:
        # Try one level of indirection through the batch alias.
        upstream_node = _resolve_through_batch_alias(node, root, nodes_by_id)

    if upstream_node is None or upstream_node.get("type") != "code":
        return []

    return [
        make_diagnostic(
            "cache.opaque-prompt",
            node_id=row.node_path,
            var_ref=inner,
            upstream_node_id=str(upstream_node.get("id", "?")),
        )
    ]


def _resolve_through_batch_alias(
    node: dict[str, Any],
    root: str,
    nodes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """If ``root`` is the node's batch alias, follow ``batch.items`` to its source node."""
    batch = node.get("batch")
    if not isinstance(batch, dict):
        return None
    alias = str(batch.get("as", "item"))
    if root != alias:
        return None
    items_expr = batch.get("items", "")
    if not isinstance(items_expr, str):
        return None
    items_stripped = items_expr.strip()
    if not TemplateResolver.is_simple_template(items_stripped):
        return None
    items_inner = items_stripped[2:-1]
    if TemplateResolver.is_coalesce_expression(items_inner):
        return None
    items_root = TemplateResolver.extract_root_node_id(items_inner)
    return nodes_by_id.get(items_root)


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


def _populate_suggested_blocks(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    memo_cache: Any,
    workflow_path: str,
    notes: list[str],
) -> tuple[list[SuggestedBlock], list[Diagnostic], dict[str, int | None]]:
    """Build greenfield suggested ``## Cache`` blocks + advisory + per-node cacheable.

    Returns ``(blocks, warnings, cacheable_by_node)``. The per-node map
    carries projected cacheable token counts:

    - ``int`` value: every chunk the node uses had memo data → real projection.
    - ``None`` value: at least one chunk had no memo data → projection
      unavailable. The renderer hides rows where the value is ``None`` (per
      Option C — pure-greenfield-no-memo rows would otherwise show
      misleading template-tokens-as-cacheable numbers).

    v1 covers greenfield only (per DD#3). When ``## Cache`` is already
    declared, append a note so agents understand why no suggestion was
    produced — silent return would otherwise hide the deferral. Cacheable
    map is empty in steady-state; existing declared-subset heuristic on
    rows is unaffected.
    """
    declared_names = set(_cache_item_names(workflow_ir))
    if declared_names:
        notes.append(
            "Suggested-blocks: workflow already declares ## Cache; steady-state "
            "(partial-block) suggestions deferred to v1.x."
        )
        return [], [], {}

    ref_to_nodes, first_seen = _collect_llm_template_references(workflow_ir)
    shared_refs = [(ref, nodes) for ref, nodes in ref_to_nodes.items() if len(nodes) >= 2]
    if not shared_refs:
        return [], [], {}

    # Sort key has 5 dimensions (CP3 #4 fix — sibling clustering):
    #   1. Most-shared root first. Roots like ``concept`` (used by 7 nodes via
    #      various sub-paths) outrank singleton roots regardless of any
    #      individual sub-path's count.
    #   2. Root segment alphabetical — deterministic tie-break BETWEEN roots
    #      with equal popularity. Crucially, this also keeps ALL sub-paths of
    #      the same root contiguous in the output (siblings cluster).
    #   3. Within a root, most-shared sub-path first. ``concept.core_idea``
    #      (used by 7) outranks ``concept.angle`` (used by 4).
    #   4. First-seen-in-prompt-walk-order — preserves narrative order between
    #      otherwise-equivalent refs.
    #   5. Alphabetical — final deterministic tie-break.
    # Pre-fix the sort scattered ``concept.core_idea`` / ``concept.title`` /
    # ``concept.angle`` across positions 1, 2, 5 because they had different
    # share counts and got ranked individually. Lyrics-generator song-creator
    # rendered ``concept.angle`` between ``creative-direction.response`` and
    # ``song-architecture.response`` — broke narrative flow AND made the
    # generated ``prompt_cache:`` lists non-prefix-contiguous for nodes using
    # only some sub-paths.
    root_to_nodes: dict[str, set[str]] = {}
    for ref, nodes in shared_refs:
        root_to_nodes.setdefault(_template_root_segment(ref), set()).update(nodes)
    root_popularity = {root: len(node_set) for root, node_set in root_to_nodes.items()}

    shared_refs.sort(
        key=lambda item: (
            -root_popularity[_template_root_segment(item[0])],
            _template_root_segment(item[0]),
            -len(item[1]),
            first_seen[item[0]],
            item[0],
        )
    )
    chunks: list[SuggestedBlockChunk] = []
    assignments: dict[str, list[str]] = {}
    total_savings: float | None = 0.0
    affected_nodes: set[str] = set()
    # Per-node projected cacheable totals. Value semantics:
    # - ``int``: all chunks the node uses had memo data → real projection.
    # - ``None`` (sentinel): at least one chunk had no memo data → projection
    #   unavailable. ``analyze()`` propagates None through PerCallRow; the
    #   renderer hides such rows per Option C. Once a node's total is None,
    #   it stays None even if subsequent chunks have data — partial info
    #   would still mislead, so honest "unknown" is the contract.
    cacheable_by_node: dict[str, int | None] = {}

    for ref, node_ids in shared_refs:
        first_row = rows_by_node.get(node_ids[0])
        model = first_row.model if first_row else ""
        size_tokens = _estimate_ref_tokens(ref, model=model, memo_cache=memo_cache, workflow_path=workflow_path)
        # ``size_tokens_est`` on the suggested-block chunk stays ``int`` — the
        # block is paste-ready prose so we render 0 (or the real value) rather
        # than expose ``None``. Agents reading the chunk size see "0" and know
        # to disregard until run data exists.
        display_size = size_tokens if size_tokens is not None else 0
        chunks.append(
            SuggestedBlockChunk(
                name=ref,
                var=f"${{{ref}}}",
                size_tokens_est=display_size,
                prose_placeholder=f"<DESCRIBE {ref} — appears verbatim in cached system prefix>",
            )
        )
        chunk_savings = _savings_for_shared_ref(ref, node_ids, rows_by_node, size_tokens)
        if chunk_savings is None:
            total_savings = None
        elif total_savings is not None:
            total_savings += chunk_savings
        for node_id in node_ids:
            affected_nodes.add(node_id)
            assignments.setdefault(node_id, []).append(ref)
            # None propagation: once a node has any unknown chunk, the whole
            # node's projection is unknown.
            existing = cacheable_by_node.get(node_id, 0)
            if size_tokens is None or existing is None:
                cacheable_by_node[node_id] = None
            else:
                cacheable_by_node[node_id] = existing + size_tokens

    target_file = workflow_path or "<root>"
    block = SuggestedBlock(
        target_file=target_file,
        ttl="5m",
        chunks=tuple(chunks),
        per_node_assignments={node_id: assignments[node_id] for node_id in sorted(assignments)},
        estimated_savings_usd=total_savings,
    )
    warning = make_diagnostic(
        "cache.shared-context-undeclared",
        node_id=None,
        node_count=len(affected_nodes),
        shared_chunks=[chunk.name for chunk in chunks],
        affected_workflow=target_file,
        savings_usd=total_savings,
    )
    return [block], [warning], cacheable_by_node


def _collect_llm_template_references(workflow_ir: dict[str, Any]) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Return ``template_ref -> node_ids`` for LLM prompt references."""
    ref_to_nodes: dict[str, list[str]] = {}
    first_seen: dict[str, int] = {}
    for node_idx, node in enumerate(workflow_ir.get("nodes", []) or []):
        if not isinstance(node, dict) or node.get("type") != "llm":
            continue
        prompt = node.get("params", {}).get("prompt", "")
        if not isinstance(prompt, str):
            continue
        batch_aliases = _batch_aliases(node)
        seen_in_node: set[str] = set()
        for match in TemplateResolver.TEMPLATE_PATTERN.finditer(prompt):
            for ref in TemplateResolver.split_coalesce_operands(match.group(1)):
                if _is_batch_scoped_ref(ref, batch_aliases) or ref in seen_in_node:
                    continue
                seen_in_node.add(ref)
                ref_to_nodes.setdefault(ref, []).append(str(node["id"]))
                first_seen.setdefault(ref, node_idx)
    return ref_to_nodes, first_seen


def _template_root_segment(ref: str) -> str:
    """Return the first segment of a template path.

    Examples:
        ``concept.core_idea`` → ``concept``
        ``concept`` → ``concept``
        ``items[0].name`` → ``items``
        ``creative-direction.response`` → ``creative-direction``

    Used by:
    - the ``_populate_suggested_blocks`` sort key (CP3 #4 — sibling clustering),
    - the ``_consolidate_to_root_advisories`` detector (CP3 #3 — sub-path
      clusters that fall below the provider's min-cache threshold).
    """
    return ref.split(".", 1)[0].split("[", 1)[0]


def _consolidate_to_root_advisories(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    declared_chunks: list[str],
    memo_cache: Any,
    workflow_path: str,
) -> list[Diagnostic]:
    """Emit ``cache.consolidate-to-root-recommended`` advisories.

    Fires when sub-paths of a parent dict (e.g. ``concept.core_idea``,
    ``concept.title``) are individually below the provider's min-cache token
    threshold AND consolidating to ``${root}`` would cross the threshold.
    The pre-fix sub-path declarations cache_control markers silently no-op
    at the provider; the agent thinks they're caching but they aren't.

    Greenfield path (no ``## Cache`` declared): audits shared template
    references. Only fires when memo data is available — without it,
    ``_estimate_ref_tokens`` falls back to tokenizing the literal
    ``${concept}`` string (~3 tokens), making the threshold check naturally
    suppress the advisory for pure-greenfield workflows. After the first
    run, memo data populates and the advisory becomes meaningful.

    Brownfield path (``## Cache`` declared with sub-path chunks): audits the
    declared chunks directly. The user has explicitly chosen these chunks;
    the advisory tells them why caching isn't actually firing.
    """
    candidates = _collect_consolidate_candidates(workflow_ir, declared_chunks)
    if not candidates:
        return []
    candidate_set = set(candidates)
    by_root = _group_subpaths_by_root(candidates)
    if not by_root:
        return []

    # Use the first node's resolved model as representative for threshold lookup.
    # Heterogeneous-model workflows would warrant per-model checks; defer to
    # v1.x if real usage hits the pattern.
    rows = list(rows_by_node.values())
    representative_model = next((row.model for row in rows if row.model), "")
    if not representative_model:
        return []
    min_tokens = get_min_cache_tokens(representative_model)

    diagnostics: list[Diagnostic] = []
    for root, sub_paths in sorted(by_root.items()):
        diag = _check_root_for_consolidation(
            root=root,
            sub_paths=sub_paths,
            candidate_set=candidate_set,
            model=representative_model,
            min_tokens=min_tokens,
            memo_cache=memo_cache,
            workflow_path=workflow_path,
        )
        if diag is not None:
            diagnostics.append(diag)
    return diagnostics


def _collect_consolidate_candidates(workflow_ir: dict[str, Any], declared_chunks: list[str]) -> list[str]:
    """Pick the chunk set the consolidate-advisory should examine."""
    if declared_chunks:
        # Brownfield — agent has explicitly declared these chunks.
        return list(set(declared_chunks))
    # Greenfield — shared template references (≥2 LLM nodes).
    ref_to_nodes, _ = _collect_llm_template_references(workflow_ir)
    return [ref for ref, node_ids in ref_to_nodes.items() if len(node_ids) >= 2]


def _group_subpaths_by_root(candidates: list[str]) -> dict[str, list[str]]:
    """Group sub-paths by their root segment.

    Root form chunks (``concept`` itself, where root == ref) are excluded:
    they ARE the root, not candidates for consolidation. Only genuine
    sub-paths (``concept.title``) get grouped.
    """
    by_root: dict[str, list[str]] = {}
    for ref in candidates:
        root = _template_root_segment(ref)
        if root != ref:
            by_root.setdefault(root, []).append(ref)
    return by_root


def _check_root_for_consolidation(
    *,
    root: str,
    sub_paths: list[str],
    candidate_set: set[str],
    model: str,
    min_tokens: int,
    memo_cache: Any,
    workflow_path: str,
) -> Diagnostic | None:
    """Run the threshold check for one root group.

    Returns a Diagnostic when consolidation would cross the threshold; None
    when any of the suppression rules fires:
      - <2 sub-paths (no consolidation case)
      - root already declared/used (redundancy, not consolidation)
      - some sub-path already crosses threshold (caching already works)
      - root itself wouldn't cross threshold (cache.below-min-tokens covers it)
    """
    if len(sub_paths) < 2:
        return None
    if root in candidate_set:
        # Root already declared/used directly — sub-paths are a redundancy
        # issue, not a consolidation case. The right fix is "remove the
        # redundant sub-path entries", not "consolidate to root".
        return None
    sub_path_tokens = [
        _estimate_ref_tokens(sp, model=model, memo_cache=memo_cache, workflow_path=workflow_path) for sp in sub_paths
    ]
    # Pre-Option-C this advisory relied on ``_estimate_ref_tokens`` returning
    # ~3-5 tokens (literal ``${ref}``) on memo miss — implicit suppression via
    # "small number trickles past threshold". Now ``_estimate_ref_tokens``
    # returns ``None`` on memo miss; explicit check needed. The advisory's
    # whole premise (compare sub-path tokens vs root tokens vs threshold) is
    # only meaningful with real value sizes. Any None → skip.
    if any(t is None for t in sub_path_tokens):
        return None
    max_subpath = max(t for t in sub_path_tokens if t is not None)
    if max_subpath >= min_tokens:
        # At least one sub-path is large enough to cache on its own;
        # cache_control on the largest sub-path already fires.
        return None
    root_tokens = _estimate_ref_tokens(root, model=model, memo_cache=memo_cache, workflow_path=workflow_path)
    if root_tokens is None or root_tokens < min_tokens:
        # Either no run data for the root (unmeasurable) or even consolidation
        # wouldn't cross the threshold (``cache.below-min-tokens`` covers
        # the latter case for declared subsets).
        return None
    return make_diagnostic(
        "cache.consolidate-to-root-recommended",
        node_id=None,
        root=root,
        sub_paths=sorted(sub_paths),
        model=model,
        min_tokens=min_tokens,
        max_subpath_tokens=max_subpath,
        root_tokens=root_tokens,
        affected_workflow=workflow_path,
    )


def _batch_aliases(node: dict[str, Any]) -> set[str]:
    batch = node.get("batch")
    if not isinstance(batch, dict):
        return set()
    return {str(batch.get("as", "item"))}


def _is_batch_scoped_ref(ref: str, aliases: set[str]) -> bool:
    return any(ref == alias or ref.startswith(f"{alias}.") or ref.startswith(f"{alias}[") for alias in aliases)


def _emit_padding_advisories(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
) -> list[Diagnostic]:
    """Build and filter ``cache.padding-advisory`` candidates."""
    cache_items = _cache_items(workflow_ir)
    declared_names = [str(item["name"]) for item in cache_items]
    if not declared_names:
        return []
    candidates: list[PaddingCandidate] = []
    for node in workflow_ir.get("nodes", []) or []:
        if not isinstance(node, dict) or node.get("type") != "llm":
            continue
        subset = node.get("prompt_cache")
        if not isinstance(subset, list) or not subset:
            continue
        current_subset = tuple(str(item) for item in subset)
        if current_subset[0] not in declared_names:
            continue
        first_pos = declared_names.index(current_subset[0])
        if first_pos == 0:
            continue
        row = rows_by_node.get(str(node.get("id")))
        if row is None:
            continue
        rate = _input_rate(row.model)
        if rate is None:
            continue
        prefix_tokens = sum(_estimate_chunk_tokens(item, row.model) for item in cache_items[:first_pos])
        call_count = row.batch_size_estimated if row.is_batch and row.batch_size_estimated else 1
        savings_usd = 0.9 * prefix_tokens * call_count * rate
        candidates.append(
            PaddingCandidate(
                node_id=row.node_path,
                current_subset=current_subset,
                suggested_subset=tuple(declared_names[:first_pos]) + current_subset,
                savings_usd=savings_usd,
            )
        )
    return compute_padding_advisories(candidates)


def _cache_validator_findings(workflow_ir: dict[str, Any]) -> list[Diagnostic]:
    """Surface validator-shipped cache findings in analyze-cache output.

    Defensive: ``validate_data_flow`` can raise ``AttributeError`` and
    similar producer-bugs on malformed IR (e.g. batch config that's a
    string rather than a dict). For an analysis tool, the safer path is
    to log + skip surfacing rather than crash the entire ``analyze-cache``
    invocation. The malformed-IR cases will surface separately at
    ``pflow run`` validation; the analyzer's job is best-effort signal.
    """
    try:
        diagnostics = validate_data_flow(workflow_ir, check_inputs=False)
    except Exception:
        logger.debug("validate_data_flow raised on malformed IR; skipping cache findings", exc_info=True)
        return []
    return [diag for diag in diagnostics if diag.id is not None and diag.id.startswith("cache.")]


def _cache_items(workflow_ir: dict[str, Any]) -> list[dict[str, Any]]:
    cache = workflow_ir.get("cache")
    if not isinstance(cache, dict):
        return []
    items = cache.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and isinstance(item.get("name"), str)]


def _cache_item_names(workflow_ir: dict[str, Any]) -> list[str]:
    return [str(item["name"]) for item in _cache_items(workflow_ir)]


def _estimate_chunk_tokens(item: dict[str, Any], model: str) -> int:
    text = f"{item.get('prose_before', '')}\n${{{item.get('var', item.get('name', ''))}}}"
    return estimate_tokens(model, text)[0]


def _estimate_ref_tokens(ref: str, *, model: str, memo_cache: Any, workflow_path: str | None) -> int | None:
    """Tokenize a template reference's resolved value.

    Returns:
        - Real token count when memo cache holds a recent value for the ref's
          root node (high-fidelity).
        - ``None`` when memo is empty / lookup fails (no run data — projection
          unavailable). Callers MUST distinguish ``None`` from a small int.

    The previous fallback (tokenize the literal ``${ref}`` string, ~3-5 tokens)
    was structurally misleading: it produced a tiny number that looked like a
    real estimate but actually represented "we have no data" — agents reading
    ``cacheable=38`` thought the opportunity was small when actually it was
    unmeasured. ``None`` propagation lets the renderer hide misleading rows
    explicitly per Option C (see render_text._render_per_call).
    """
    value = _latest_value_for_ref(ref, memo_cache=memo_cache, workflow_path=workflow_path)
    if value is not None:
        return estimate_tokens(model, deterministic_serialize(value))[0]
    return None


def _latest_value_for_ref(ref: str, *, memo_cache: Any, workflow_path: str | None) -> Any:
    if memo_cache is None:
        return None
    root = TemplateResolver.extract_root_node_id(ref)
    try:
        latest = memo_cache.get_latest_for_node(root, workflow_path=workflow_path)
    except Exception:
        logger.debug("memo_cache.get_latest_for_node failed while estimating %s", ref, exc_info=True)
        return None
    if latest is None:
        return None
    output, _created_at = latest
    if not isinstance(output, dict):
        return None
    resolved = TemplateResolver.resolve_template(f"${{{ref}}}", {root: output})
    if isinstance(resolved, str) and resolved == f"${{{ref}}}":
        return None
    return resolved


def _savings_for_shared_ref(
    ref: str,
    node_ids: list[str],
    rows_by_node: dict[str, PerCallRow],
    tokens: int | None,
) -> float | None:
    if tokens is None:
        # No memo data → can't compute savings honestly. Mirror the existing
        # cost tri-state contract: None propagates rather than fabricating 0.
        return None
    total = 0.0
    for node_id in node_ids[1:]:
        row = rows_by_node.get(node_id)
        if row is None:
            return None
        savings = _estimate_token_savings_usd(row.model, tokens, 1)
        if savings is None:
            return None
        total += savings
    return total


def _estimate_token_savings_usd(model: str, tokens: int, calls: int) -> float | None:
    rate = _input_rate(model)
    if rate is None:
        return None
    return 0.9 * tokens * calls * rate


def _input_rate(model: str) -> float | None:
    from .cost_estimation import get_model_pricing

    pricing = get_model_pricing(model)
    return pricing.input_rate if pricing is not None else None


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
    result = walk_cross_workflow(
        root_ir,
        base_path=base_path,
        root_workflow_path=root_workflow_path,
        notes=notes,
    )
    edges = result.edges

    rename_diags: list[Diagnostic] = []
    prose_mismatches: list[Diagnostic] = []
    value_flow_opportunities: list[Diagnostic] = []
    for edge in edges:
        if edge.is_rename and edge.parent_value_expr is not None:
            # Evidence-basis principle: the rename warning predicts that
            # cross-workflow byte-level cache match WILL fail because of
            # diverging prose labels. That prediction is only meaningful
            # when (a) the parent value is a stable identifier (not a
            # batch iteration variable), and (b) at least one side has
            # ``## Cache`` declared so there's actual state to break.
            # Without these, the warning fires hypothetically and floods
            # the agent-facing report with non-actionable noise. See
            # GH #362 for the empirical case (lyrics-generator: 23
            # rename warnings, all from batch aliases or non-cache
            # boundaries — zero actionable).
            if edge.is_batch_alias_root:
                continue  # Iteration-variable substitution, not a rename.
            parent_has_cache = bool(result.cache_items_by_workflow.get(edge.parent_workflow))
            child_has_cache = bool(result.cache_items_by_workflow.get(edge.child_workflow))
            if not parent_has_cache and not child_has_cache:
                continue  # No cached state to break — prediction unactionable.
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
            continue

        prose_mismatches.extend(_cross_workflow_prose_mismatches(edge, result.cache_items_by_workflow))
        opportunity = _cross_workflow_value_flow_opportunity(
            edge,
            result.cache_items_by_workflow,
            result.irs_by_workflow,
        )
        if opportunity is not None:
            value_flow_opportunities.append(opportunity)

    return CrossWorkflowFindings(
        boundaries_analyzed=len(edges),
        rename_detections=tuple(rename_diags),
        prose_mismatches=tuple(prose_mismatches),
        value_flow_opportunities=tuple(value_flow_opportunities),
    )


def _cross_workflow_prose_mismatches(
    edge: Any,
    cache_items_by_workflow: dict[str, tuple[dict[str, Any], ...]],
) -> list[Diagnostic]:
    parent_by_name = _items_by_name(cache_items_by_workflow.get(edge.parent_workflow, ()))
    child_by_name = _items_by_name(cache_items_by_workflow.get(edge.child_workflow, ()))
    diagnostics: list[Diagnostic] = []
    for chunk_name in sorted(parent_by_name.keys() & child_by_name.keys()):
        parent_prose = str(parent_by_name[chunk_name].get("prose_before", ""))
        child_prose = str(child_by_name[chunk_name].get("prose_before", ""))
        if parent_prose == child_prose:
            continue
        diagnostics.append(
            make_diagnostic(
                "cache.cross-workflow-prose-mismatch",
                parent_workflow=edge.parent_workflow,
                child_workflow=edge.child_workflow,
                chunk_name=chunk_name,
                parent_prose=parent_prose,
                child_prose=child_prose,
            )
        )
    return diagnostics


def _cross_workflow_value_flow_opportunity(
    edge: Any,
    cache_items_by_workflow: dict[str, tuple[dict[str, Any], ...]],
    irs_by_workflow: dict[str, dict[str, Any]],
) -> Diagnostic | None:
    if edge.parent_value_expr is None:
        return None
    parent_declared = set(_items_by_name(cache_items_by_workflow.get(edge.parent_workflow, ())))
    child_declared = set(_items_by_name(cache_items_by_workflow.get(edge.child_workflow, ())))
    if edge.parent_value_expr in parent_declared or edge.child_input_name in child_declared:
        return None

    # Bug E fix — count LLM nodes that actually reference this value on each
    # side of the boundary. The catalog message_template renders ``{node_count}
    # LLM nodes share static context``; pre-fix used a hardcoded ``2`` (parent
    # + child boundary), which was factually wrong when the child has 0 LLM
    # nodes referencing the input. Counting ``len(refs) >= 1`` rather than the
    # boundary is the honest report.
    parent_count = _count_llm_nodes_referencing_path(
        irs_by_workflow.get(edge.parent_workflow, {}),
        edge.parent_value_expr,
    )
    child_count = _count_llm_nodes_referencing_path(
        irs_by_workflow.get(edge.child_workflow, {}),
        edge.child_input_name,
    )
    node_count = parent_count + child_count
    if node_count < 2:
        # No or only one LLM consumer on the combined boundary — declaring
        # this value in ## Cache wouldn't share across enough calls to be
        # worthwhile. Suppress the noisy advisory; agents see real
        # opportunities, not boundary trivia.
        return None
    return make_diagnostic(
        "cache.shared-context-undeclared",
        node_id=edge.parent_node_id,
        node_count=node_count,
        shared_chunks=[edge.child_input_name],
        affected_workflow=edge.parent_workflow,
        # CP5 #5: presence of ``child_workflow`` in context selects the
        # boundary-scope message template (see make_diagnostic dispatch).
        # Workflow-scope emission at ``_populate_suggested_blocks`` does NOT
        # set this key — it gets the workflow-scope template by default.
        child_workflow=edge.child_workflow,
        savings_usd=None,
    )


def _count_llm_nodes_referencing_path(ir: dict[str, Any], template_path: str) -> int:
    """Count LLM nodes whose ``params.prompt`` references ``${template_path}``.

    Uses the template-pattern walker to handle both bare references
    (``${X}``) and dotted-path references (``${X.field}``, ``${X[0]}``).
    For coalesce expressions (``${a ?? b}``), each operand is checked
    independently — symmetric with ``_dynamic_before_static_warnings``.
    """
    if not isinstance(ir, dict):
        return 0
    nodes = ir.get("nodes")
    if not isinstance(nodes, list):
        return 0
    count = 0
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "llm":
            continue
        prompt = node.get("params", {}).get("prompt", "")
        if not isinstance(prompt, str):
            continue
        for match in TemplateResolver.TEMPLATE_PATTERN.finditer(prompt):
            for operand in TemplateResolver.split_coalesce_operands(match.group(1)):
                # Match exact path OR dotted-prefix (``${creative.direction}``
                # references the ``creative`` chunk identifier when keyed by root).
                if operand == template_path or operand.startswith(f"{template_path}."):
                    count += 1
                    break
            else:
                continue
            break  # each LLM node counted at most once
    return count


def _items_by_name(items: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {str(item["name"]): item for item in items if isinstance(item.get("name"), str)}


# ---------------------------------------------------------------------------
# Trace discrepancy detection
# ---------------------------------------------------------------------------


def _iter_llm_events(events: list[dict[str, Any]]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Walk trace events recursively, including cached events."""
    for event in events:
        if "llm_call" in event:
            yield str(event.get("node_id", "unknown")), event
        for item in event.get("batch_items", []) or []:
            if not isinstance(item, dict):
                continue
            if "llm_call" in item:
                yield str(event.get("node_id", "unknown")), item
            yield from _iter_llm_events(item.get("events", []) or [])
        yield from _iter_llm_events(event.get("sub_workflow_events", []) or [])


def _predict_cache_keys(
    workflow_ir: dict[str, Any],
    parameters: dict[str, Any],
    memo_cache: Any,
    workflow_path: str | None,
) -> tuple[dict[str, str], list[str]]:
    """Consume planner-produced cache keys rather than re-deriving them.

    Returns ``(predicted_keys, notes)`` where ``predicted_keys`` is empty when
    we can't trust the prediction (no memo cache, partial inputs, compilation
    failure). Each empty-result branch appends a note explaining why so the
    agent reading the analyzer output understands what's missing.
    """
    notes: list[str] = []
    if memo_cache is None:
        notes.append(
            "Discrepancy detection: predicted-key matching unavailable (no memo cache available). "
            "Observable-field attributions (TTL expiry, chunk skipped) still apply."
        )
        return {}, notes

    # When the workflow declares inputs but the caller passed none, predicted
    # keys would be derived from defaults — diverging from the trace's run-time
    # values and flooding the report with false ``key_mismatch`` attributions.
    # Trace 2.1.0 doesn't carry an input fingerprint, so we can't compare; the
    # honest fallback is observable-only attribution.
    if not parameters and isinstance(workflow_ir.get("inputs"), dict) and workflow_ir["inputs"]:
        notes.append(
            "Discrepancy detection: predicted-key matching skipped — workflow declares inputs that "
            "weren't supplied. Pass `key=value` pairs matching the trace's run for full detection. "
            "Observable-field attributions (TTL expiry, chunk skipped) still apply."
        )
        return {}, notes

    try:
        from pflow.core.exceptions import (
            CompilationError,
            MarkdownParseError,
            SchemaValidationError,
            WorkflowValidationError,
        )
        from pflow.execution.plan import build_plan
        from pflow.registry import Registry
        from pflow.runtime import compile_workflow

        registry = Registry()
        compiled = compile_workflow(workflow_ir, registry, parameters or {})
        plan = build_plan(
            compiled,
            parameters or {},
            memo_cache,
            registry,
            _parent_workflow_file=workflow_path,
        )
    except (
        CompilationError,
        MarkdownParseError,
        SchemaValidationError,
        WorkflowValidationError,
        FileNotFoundError,
        ValueError,
    ) as exc:
        notes.append(
            f"Discrepancy detection: predicted-key matching unavailable ({type(exc).__name__}). "
            "Provide required inputs via `pflow analyze-cache <workflow> key=value` for full detection. "
            "Observable-field attributions (TTL expiry, chunk skipped) still apply."
        )
        return {}, notes
    keys, plan_notes = _flatten_plan_keys(plan)
    notes.extend(plan_notes)
    return keys, notes


def _flatten_plan_keys(plan: Any) -> tuple[dict[str, str], list[str]]:
    """Flatten parent and nested sub-plans to ``node_id -> cache_key``.

    Detects **heterogeneous batch sub-workflow collision**: per-item child
    plans share ``node_id`` but compute different ``cache_key`` per item.
    Drops colliding nodes (observable-only fallback) rather than picking an
    arbitrary winner that would falsely flag ``key_mismatch`` for the other
    items, and emits a notes entry explaining the coverage gap.

    BFS-downstream coverage gaps are reported separately by
    ``_emit_discrepancy_diagnostics`` based on actual silent-skip count
    against trace events — counting plan structure here would emit false
    notes for non-cache workflows whose downstream entries have
    ``cache_key=None`` for orthogonal reasons.
    """
    keys: dict[str, str] = {}
    collisions: set[str] = set()

    def _walk(p: Any) -> None:
        for entry in getattr(p, "entries", []) or []:
            node_id = str(entry.node_id)
            cache_key = getattr(entry, "cache_key", None)
            if cache_key is not None:
                key_str = str(cache_key)
                existing = keys.get(node_id)
                if existing is not None and existing != key_str:
                    collisions.add(node_id)
                else:
                    keys[node_id] = key_str
            sub_plan = getattr(entry, "sub_plan", None)
            if sub_plan is not None:
                _walk(sub_plan)

    _walk(plan)

    # Drop colliding nodes — keeping any one item's key would silently
    # misattribute the others as ``key_mismatch``.
    for node_id in collisions:
        keys.pop(node_id, None)

    notes: list[str] = []
    if collisions:
        notes.append(
            f"Discrepancy detection: predicted-key matching skipped for {len(collisions)} "
            "heterogeneous batch sub-workflow node(s); per-item upstream values diverge. "
            "Observable-field attributions still apply."
        )
    return keys, notes


def _emit_discrepancy_diagnostics(
    *,
    workflow_ir: dict[str, Any],
    trace_data: dict[str, Any],
    parameters: dict[str, Any],
    memo_cache: Any,
    workflow_path: str | None,
    notes: list[str],
) -> list[Diagnostic]:
    # Trace consumer rule (runtime/CLAUDE.md): gate on the major version and
    # exclude 2.0.0 explicitly. 2.0.0 traces lack cache_key/cache_age_sec; a
    # graceful note is already emitted at trace-load time. Future 2.2+ traces
    # are forward-compat: they carry at least the 2.1 fields per the additive
    # rule. Per-event guards below handle missing optional fields.
    fv = str(trace_data.get("format_version", ""))
    if not fv.startswith("2.") or fv.startswith("2.0"):
        return []

    predicted_keys, predict_notes = _predict_cache_keys(workflow_ir, parameters, memo_cache, workflow_path)
    notes.extend(predict_notes)

    diagnostics: list[Diagnostic] = []
    silent_skip_no_predicted_key = 0
    for node_id, event in _iter_llm_events(trace_data.get("nodes", []) or []):
        llm_call = event.get("llm_call") or {}
        if not isinstance(llm_call, dict):
            continue

        cache_create = int(llm_call.get("cache_creation_input_tokens") or 0)
        cache_read = int(llm_call.get("cache_read_input_tokens") or 0)
        chunks_skipped = llm_call.get("cache_chunks_skipped")
        # When cache wasn't engaged at all the discrepancy machinery has
        # nothing to compare — UNLESS a chunk was skipped, which is exactly
        # the reason the cache disengaged in the first place. Skipping that
        # case would make `chunk_skipped` attribution unreachable for the
        # branch-absent scenario it was designed for.
        if cache_create == 0 and cache_read == 0 and not chunks_skipped:
            continue

        actual_key = llm_call.get("cache_key") or event.get("cache_key")
        cache_age_sec = llm_call.get("cache_age_sec") or event.get("cache_age_sec")
        predicted_key = predicted_keys.get(node_id)

        actual_pct = _safe_pct(cache_read, cache_read + cache_create)
        predicted_pct = 100 if predicted_key is not None else 0
        predicted_label = _compute_predicted_label(predicted_key, actual_key)

        if predicted_key is None and not (chunks_skipped or (cache_age_sec is not None and float(cache_age_sec) > 300)):
            # Cache engaged but we have no predicted_key (BFS-downstream,
            # heterogeneous batch collision, partial inputs, compile failure)
            # AND no observable signal — count silently-skipped events so we
            # can emit a single coverage note instead of misleading silence.
            silent_skip_no_predicted_key += 1
            continue
        if predicted_key is not None and abs(predicted_pct - actual_pct) < 5:
            continue

        root_cause, summary, extra = _attribute_root_cause(
            cache_age_sec=cache_age_sec,
            chunks_skipped=chunks_skipped,
            predicted_key=predicted_key,
            actual_key=actual_key,
            ttl=_extract_cache_ttl(workflow_ir.get("cache")),
            provider=detect_provider(llm_call.get("model")),
            node_id=node_id,
            workflow_path=workflow_path,
            predicted_pct=predicted_pct,
            actual_pct=actual_pct,
        )
        diagnostics.append(
            make_diagnostic(
                "cache.discrepancy",
                node_id=node_id,
                trace_path=str(trace_data.get("workflow_path") or "<unknown>"),
                predicted_pct=predicted_pct,
                predicted_label=predicted_label,
                actual_pct=actual_pct,
                root_cause=root_cause,
                root_cause_summary=summary,
                cache_age_sec=cache_age_sec,
                predicted_cache_key=predicted_key,
                actual_cache_key=actual_key,
                **extra,
            )
        )
    if silent_skip_no_predicted_key > 0:
        notes.append(
            f"Discrepancy detection: skipped attribution for {silent_skip_no_predicted_key} "
            "trace event(s) with no predicted cache_key and no observable signal "
            "(BFS-downstream, heterogeneous batch, or partial inputs)."
        )
    return _aggregate_and_cap_discrepancies(diagnostics, max_total=20, notes=notes)


def _compute_predicted_label(predicted_key: str | None, actual_key: Any) -> str:
    """Compute a human-readable label for the planner's prediction.

    Bug F fix — ``predicted_pct`` is binary (100 if planner produced a
    cache_key, 0 otherwise) and rendering it as ``"predicted hit_ratio 100%"``
    is misleading: it sounds like a measured hit ratio. The label
    distinguishes:

    - ``"miss"`` — planner couldn't produce a cache_key (BFS-downstream,
      heterogeneous batch, partial inputs); discrepancy attribution falls back
      to observable signals.
    - ``"hit (bytes diverged at runtime)"`` — both keys are present AND
      different (e.g., upstream value changed between analyzer-time and the
      traced run). Triggers ``key_mismatch`` attribution downstream.
    - ``"hit"`` — predicted_key is set; the actual_key either matches OR was
      not recorded by the trace (older fixtures, future schema changes).
      Treating "actual_key absent" as a match avoids false-positive
      "diverged" rendering on traces that simply lack the field.
    """
    if predicted_key is None:
        return "miss"
    if actual_key is not None and predicted_key != actual_key:
        return "hit (bytes diverged at runtime)"
    return "hit"


def _attribute_root_cause(
    *,
    cache_age_sec: Any,
    chunks_skipped: Any,
    predicted_key: str | None,
    actual_key: Any,
    ttl: str | None,
    provider: Any,
    node_id: str,
    workflow_path: str | None,
    predicted_pct: int,
    actual_pct: int,
) -> tuple[str, str, dict[str, Any]]:
    if chunks_skipped:
        skipped = str(chunks_skipped[0])
        return (
            "chunk_skipped",
            f"Cache chunk {skipped!r} skipped at runtime (branch absent)",
            {"skipped_chunk": skipped},
        )
    if chunks_skipped is None:
        return (
            "unknown",
            f"Cache chunks-skipped field absent on this trace event "
            f"(predicted={predicted_pct}%, actual={actual_pct}%); cannot attribute for {node_id}",
            {},
        )

    effective_ttl = ttl
    if effective_ttl is None and provider is not None and provider.name in {"anthropic", "openai", "gemini"}:
        effective_ttl = "5m"

    if cache_age_sec is not None:
        age = float(cache_age_sec)
        if effective_ttl == "5m" and age >= 300:
            return (
                "ttl_expiry",
                f"Cache entry was {age:.0f}s old (>= 5m TTL); upstream write expired",
                {"affected_workflow": workflow_path or "<root>"},
            )
        if effective_ttl == "1h" and age >= 3600:
            return (
                "ttl_expiry",
                f"Cache entry was {age:.0f}s old (>= 1h TTL)",
                {"affected_workflow": workflow_path or "<root>"},
            )

    if predicted_key is not None and predicted_key != actual_key:
        return ("key_mismatch", "Upstream value changed between predicted run and actual run", {})

    return (
        "unknown",
        f"Cannot attribute discrepancy to known causes "
        f"(predicted={predicted_pct}%, actual={actual_pct}%); inspect trace events for {node_id}",
        {},
    )


def _aggregate_and_cap_discrepancies(
    diags: list[Diagnostic],
    *,
    max_total: int,
    notes: list[str] | None = None,
) -> list[Diagnostic]:
    groups: dict[tuple[str | None, str], list[Diagnostic]] = {}
    for diag in diags:
        ctx = diag.context or {}
        groups.setdefault((diag.node_id, str(ctx.get("root_cause", "unknown"))), []).append(diag)

    aggregated: list[Diagnostic] = []
    for group in groups.values():
        representative = group[0]
        merged_context = {**(representative.context or {}), "affected_invocations": len(group)}
        # ``replace`` rather than in-place mutation: ``make_diagnostic`` may
        # share context refs across diagnostics in the same group, so mutating
        # ``representative.context`` would leak ``affected_invocations`` to
        # the rest of the group (silent shared-state bug).
        aggregated.append(replace(representative, context=merged_context))
    aggregated.sort(key=lambda diag: -int((diag.context or {}).get("affected_invocations", 1)))
    if notes is not None and len(aggregated) > max_total:
        notes.append(
            f"Discrepancies: {len(aggregated) - max_total} additional group(s) suppressed by cap "
            f"(showing top {max_total} by frequency)."
        )
    return aggregated[:max_total]


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
    # ``cacheable_tokens_estimated`` may be ``None`` for greenfield rows
    # without memo (Option C — projection unmeasurable). Sum only the known
    # values; None rows contribute 0 to the aggregate (honest "we don't know"
    # rather than fabricated 0). Top-level summary still useful — agents
    # see the partial signal from steady-state / post-run rows.
    total_cacheable = sum(r.cacheable_tokens_estimated or 0 for r in rows)
    models = sorted({r.model for r in rows if r.model})
    blocking_errors = sum(1 for d in warnings if d.severity == Severity.ERROR)
    warnings_count = sum(1 for d in warnings if d.severity == Severity.WARNING)
    info_count = sum(1 for d in warnings if d.severity == Severity.INFO)
    actionable = warnings_count + info_count

    output_tokens_by_node: dict[str, int | None] = {r.node_path: r.output_tokens_estimated for r in rows}
    cost = compute_aggregate_costs(rows, output_tokens_by_node=output_tokens_by_node, ttl=ttl)

    # CR-1430 C2 fix: percentage numerator and denominator must be over the SAME
    # rowset. ``cost.current_usd`` is computed over rows-with-output (subset);
    # ``cost.savings_first_run_usd`` was input-only over ALL priced rows
    # (superset) — dividing the two could yield ``savings > current`` →
    # nonsensical ``-117%`` in the renderer. The cohort-consistent percentage
    # is ``(current - optimized) / current`` — both sides over rows-with-output.
    # The aggregate input-only savings figure remains separately exposed via
    # ``aggregate_savings_first_run_usd`` so greenfield workflows still surface
    # an absolute savings opportunity even when ``current_usd`` is None.
    cohort_first_run_savings = (
        cost.current_usd - cost.optimized_usd
        if cost.current_usd is not None and cost.optimized_usd is not None
        else None
    )
    cohort_rerun_savings = (
        cost.current_usd - cost.rerun_usd if cost.current_usd is not None and cost.rerun_usd is not None else None
    )
    savings_pct_first_run = _safe_pct_or_none(cohort_first_run_savings, cost.current_usd)
    savings_pct_rerun = _safe_pct_or_none(cohort_rerun_savings, cost.current_usd)

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

    Sort key dimensions (lexicographic, all ascending after negation/inversion):

    1. **Severity** (ERROR > WARNING > INFO) — structural blockers first.
    2. **Detection-class priority** (``RECOMMENDED_ACTION_PRIORITY`` in
       ``warning_catalog``) — actionable opportunities ahead of informational
       alignment findings. Resolves the common "all INFO, no savings" case
       where alphabetical tie-break used to bury ``cache.shared-context-
       undeclared`` (priority 10) under ``cache.cross-workflow-rename-
       detected`` (priority 50). See GH #1 / #361 thread for the surface.
    3. **Savings** (when known) — higher dollar impact ranks ahead within a
       priority tier.
    4. **Stable alphabetical** on ``d.id`` — deterministic tie-break.
    """
    from .warning_catalog import DEFAULT_RECOMMENDED_ACTION_PRIORITY, RECOMMENDED_ACTION_PRIORITY

    def _key(d: Diagnostic) -> tuple[int, int, float, str]:
        # Severity weight (higher = more impactful when no savings_usd).
        sev_weight = {Severity.ERROR: 2, Severity.WARNING: 1, Severity.INFO: 0}.get(d.severity, 0)
        priority = RECOMMENDED_ACTION_PRIORITY.get(d.id or "", DEFAULT_RECOMMENDED_ACTION_PRIORITY)
        savings = 0.0
        ctx = d.context or {}
        savings_value = ctx.get("savings_usd")
        if isinstance(savings_value, (int, float)):
            savings = float(savings_value)
        return (-sev_weight, priority, -savings, d.id or "")

    sorted_warnings = sorted(warnings, key=_key)
    actions: list[RecommendedAction] = []
    for rank, d in enumerate(sorted_warnings, start=1):
        ctx = d.context or {}
        savings = ctx.get("savings_usd")
        if not isinstance(savings, (int, float)):
            savings = None
        # Workflow-level scope: when the warning has no per-node ``node_id`` but
        # ``context.affected_workflow`` is set, surface that as ``scope_workflow``
        # so the renderer can label it "Workflow: <path>" instead of leaving the
        # scope line absent (which makes workflow-level findings indistinguishable
        # from per-node findings in agent-readable output — the GH #2 surface).
        scope_workflow: str | None = None
        if d.node_id is None:
            affected = ctx.get("affected_workflow")
            if isinstance(affected, str) and affected:
                scope_workflow = affected
        # Catalog-as-SSoT: looks up headline_template by diag.id and formats
        # against context. Works whether the diag came from make_diagnostic OR
        # was built directly via Diagnostic(...) (validator emitters in
        # data_flow.py — _make_order_mismatch_diagnostic etc.).
        from .warning_catalog import resolve_headline_for

        headline = resolve_headline_for(d)
        actions.append(
            RecommendedAction(
                rank=rank,
                warning_id=d.id or "",
                node_id=d.node_id,
                estimated_savings_usd=float(savings) if savings is not None else None,
                scope_workflow=scope_workflow,
                message=d.message or "",
                headline=headline,
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
