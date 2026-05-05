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
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # ``CostTier`` lives in ``cost_estimation.py`` (where it's produced).
    # ``cost_estimation`` already imports ``PerCallRow`` from this module at
    # top level, so a non-TYPE_CHECKING import here would close the cycle.
    # Forward reference + delayed annotation evaluation (``from __future__
    # import annotations`` above) keeps the runtime resolution lazy.
    from .cost_estimation import CostTier

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
from pflow.core.llm_providers import detect_provider, normalize_model_name
from pflow.core.workflow.data_flow import validate_data_flow
from pflow.core.workflow_id import synthesize_inline_workflow_id
from pflow.runtime.template_resolver import TemplateResolver

from .context import AnalysisContext, _normalize_empty
from .cross_workflow import walk_cross_workflow
from .padding_advisor import PaddingCandidate, compute_padding_advisories
from .token_estimation import (
    _estimate_ref_tokens,
    estimate_cacheable_tokens,
    estimate_output_tokens,
    estimate_tokens,
)
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
    # Output token data — None on greenfield (never run); ``output_data_source ∈
    # {"trace", "memo", "unavailable"}``. See ``cost_estimation.py`` for how
    # ``None`` propagates through the absolute-cost figures (per the
    # tri-state contract).
    output_tokens_estimated: int | None = None
    output_data_source: str = "unavailable"
    # Stage C.1 (Task 159): True when the IR's ``params.model`` is an
    # unresolved ``${...}`` template (heterogeneous batch sub-workflow —
    # model varies per item). Such rows can't be priced as one model;
    # ``cost_estimation`` skips them and the renderer shows ``model=<varies>``
    # instead of leaking the literal template string. ``model`` is set to ``""``
    # for these rows so the existing pricing-iteration ``if row.model`` check
    # also short-circuits — defense-in-depth against future contributors who
    # forget to consult this flag.
    model_is_heterogeneous: bool = False
    # Tier label for ``cacheable_tokens_estimated``. Independent from
    # ``data_source`` (input) and ``output_data_source`` — the three metrics
    # may legitimately diverge (e.g., trace fires for input but cacheable
    # falls through to memo when ``cache_creation+cache_read == 0``).
    # Sources: ``"trace"``, ``"memo"``, ``"parameters"``, ``"estimator"``,
    # ``"unavailable"``. ``"parameters"`` is added by Track B (Phase B):
    # workflow-input refs resolved via the agent's ``--inputs``.
    cacheable_data_source: str = "unavailable"
    # Track A (Phase A): per-call recorded cost from the trace (sum of
    # llm_call + batch_items[*].llm_call costs for this node's event tree).
    # ``None`` when no trace event matched. Read by the renderer for the
    # per-call display column and by ``compute_actually_paid``'s row fallback
    # path. Projections (``compute_projections``) intentionally ignore this
    # field — they're pure IR-driven hypotheticals.
    cost_usd: float | None = None
    # Tier label for ``cost_usd``. 4-state per the cost-tier matrix:
    # - ``"trace"``: cost from trace; all leaves priced. High confidence.
    # - ``"trace_partial"``: cost from trace + recompute mix; at least one
    #   leaf had unpriced model. Medium-high confidence.
    # - ``"recomputed"``: no trace; computed from ``tokens x LiteLLM rate``.
    #   Medium confidence (matches what we did pre-fix).
    # - ``"unavailable"``: pricing missing AND no trace data. Low confidence.
    cost_data_source: str = "recomputed"
    workflow_path: str | None = None
    # True when this row is statically reachable in the workflow IR but absent
    # from a loaded trace while another node in the same workflow did execute.
    # This prevents erroring sub-workflows from fabricating recomputed costs
    # for LLM nodes that never actually ran.
    did_not_execute_in_trace: bool = False
    # Stage 0.3 (Task 159): the inline ``warnings: tuple[str, ...]`` field was
    # vestigial — single production producer never populated it; renderer
    # fallbacks at ``render_text.py:497, 617`` and the JSON ``per_call.warnings``
    # key were dead. Per-row inline warning markers are derived at render time
    # from ``analysis.warnings`` filtered by node_id (see
    # ``render_text._render_per_call``).


@dataclass(frozen=True)
class RecommendedAction:
    """One pre-sorted dispatch row for the recommended-actions section.

    Scope fields (``node_id``, ``scope_workflow``):

    - **Per-node**: ``node_id`` set. ``scope_workflow`` may also be set when
      the workflow location is known; same-id nodes can appear in parent and
      child workflows, so consumers should dispatch on ``(node_id,
      scope_workflow)`` when both are populated.
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
    # Task 159 follow-up: prompt-body refs to remove per node so the cached
    # chunks aren't sent inline at 1.0x rate alongside the cached 0.1x rate.
    # Keyed by node_id; values are sorted, deduplicated lists of body refs.
    # Empty dict for blocks with no overlapping refs (greenfield workflows
    # where the suggested ## Cache wouldn't conflict with existing prompts).
    prompt_body_cleanup: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class CrossWorkflowFindings:
    """Pure topology data about cross-workflow boundaries.

    Stage 0 (Task 159): the rename / prose-mismatch / value-flow Diagnostic
    tuples that used to live here have been removed. Findings live in
    ``CacheAnalysis.warnings``; renderers filter by ``Diagnostic.id`` to
    recover each category. JSON output preserves the per-category arrays
    as derived views (no duplication in the data model).
    """

    boundaries_analyzed: int


@dataclass(frozen=True)
class SubWorkflowRollupEntry:
    """Per-child-workflow cost figures in a sub-workflow rollup.

    Mirrors :class:`AnalysisSummary`'s atomic cost primitives at the
    per-child-workflow scope. ``actually_paid_usd`` is the recorded cost
    for this child's LLM events (trace-driven, scoped to ``workflow_path``);
    the hypothetical fields are pure projections from this child's IR rows.
    """

    workflow_path: str
    called_by_node_id: str
    llm_node_count: int
    actually_paid_usd: float | None = None
    no_cache_hypothetical_usd: float | None = None
    first_run_with_cache_hypothetical_usd: float | None = None
    rerun_within_ttl_hypothetical_usd: float | None = None


@dataclass(frozen=True)
class SubWorkflowRollup:
    workflows_included: tuple[str, ...]
    max_depth_walked: int
    truncated: bool
    per_workflow: tuple[SubWorkflowRollupEntry, ...]


@dataclass(frozen=True)
class TraceExecutionIndex:
    costs_by_key: dict[tuple[str | None, str], tuple[float | None, str]]
    llm_calls_by_key: dict[tuple[str | None, str], dict[str, Any]]
    executed_keys: set[tuple[str | None, str]]
    workflows_with_trace: set[str | None]
    current_cost_by_workflow: dict[str | None, float | None]


@dataclass(frozen=True)
class AnalysisSummary:
    """Atomic cost primitives + counts for an analyze-cache result.

    Each cost field carries exactly one meaning. The renderer composes
    context-aware presentation by selecting which atoms to display
    (greenfield vs trace+declared); no field is overloaded across contexts.

    Cost atoms:

    - ``actually_paid_usd`` — what the workflow actually paid this run.
      Populated ONLY when a trace contributed at least one priced LLM
      leaf. ``None`` for greenfield. Includes provider-side implicit
      caching (Gemini) and any other discount the trace recorded.
    - ``actually_paid_tier`` — confidence tier for ``actually_paid_usd``
      (``CostTier``). ``UNAVAILABLE`` when ``actually_paid_usd is None``.
    - ``no_cache_hypothetical_usd`` — pure no-cache recompute baseline:
      ``input × full_rate + output × output_rate`` per row. The "what
      would this cost without ANY caching?" projection. Populated when
      pricing + output tokens are available (post-run greenfield with
      memo, or any trace path).
    - ``first_run_with_cache_hypothetical_usd`` — first-run projection
      that honors declared ``prompt_cache:`` (write rate on cacheable +
      input rate on non-cacheable + output rate on output for declared
      rows; no-cache math for undeclared rows). Equals
      ``no_cache_hypothetical_usd`` exactly when no row declares cache.
    - ``rerun_within_ttl_hypothetical_usd`` — projection for every call
      after the first within TTL (all cacheable at read rate).
    - ``aggregate_savings_*`` — input-only deltas (output cancels);
      greenfield-safe — populated even when absolute fields are None.
    """

    actually_paid_usd: float | None
    actually_paid_tier: CostTier
    no_cache_hypothetical_usd: float | None
    first_run_with_cache_hypothetical_usd: float | None
    rerun_within_ttl_hypothetical_usd: float | None
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
    unavailable_models_by_workflow: dict[str | None, tuple[str, ...]] | None = None
    # Aggregate dollar savings if ``prompt_cache:`` declarations are utilized.
    # Computed from input-only math (output cost cancels in
    # ``no_cache - first_run_with_cache`` / ``no_cache - rerun_within_ttl``),
    # so these are populated even on greenfield workflows whose absolute
    # cost figures stay ``None``. ``None`` only when no priced rows have
    # any ``prompt_cache:`` declared.
    aggregate_savings_first_run_usd: float | None = None
    aggregate_savings_rerun_usd: float | None = None
    # Stage C.1: heterogeneous batch sub-workflows (``model: ${item.model}``)
    # can't be priced as one model. ``models_in_use`` excludes them so the
    # literal ``${...}`` template doesn't leak into the rendered scale line;
    # these counters surface the count + node identities separately so the
    # agent knows WHICH nodes vary (named in ``_format_scale_line``).
    # ``_render_summary`` also gates the "no model resolved" branch on these
    # to avoid the wrong "set settings.default_model" hint when the actual
    # cause is "varies per item."
    heterogeneous_model_node_count: int = 0
    heterogeneous_model_node_paths: tuple[str, ...] = ()
    # Phase 6 (4.x minor-additive): root vs sub-workflow LLM node count
    # split. The text renderer has computed this on-the-fly since Phase 5
    # sub-workflow rollup landed; promoting it into the data model gives
    # JSON consumers (MCP, structured tools) parity with text.
    # ``root_llm_node_count`` == ``total_llm_calls_estimated`` for
    # single-workflow analyses; ``sub_workflow_llm_node_count`` == 0 in
    # that case.
    root_llm_node_count: int = 0
    sub_workflow_llm_node_count: int = 0
    sub_workflow_rollup: SubWorkflowRollup | None = None


@dataclass(frozen=True)
class CacheAnalysis:
    """Structured analyzer result. Renderers transform this into text or JSON.

    Stage 0 (Task 159): ``recommended_actions`` is a renderer-derived view, not
    a pre-computed field. ``warnings`` is the single source of truth for
    findings; ranked / categorized / filtered views live in
    :mod:`view_helpers` (text + JSON renderers). mypy / rustc / clippy / ruff
    all use this shape — pre-computed views in the data model create
    duplication, drift, and ordering invariants that test fixtures encode
    incorrectly.
    """

    workflow_path: str
    analyzed_at: str
    estimate_confidence: str
    estimate_confidence_coverage: dict[str, int]
    trace_path: str | None
    summary: AnalysisSummary
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
    ``~/.pflow/debug/`` for the most recent 2.x trace whose ``workflow_path``
    matches, per DD#34.

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

    cw_result = walk_cross_workflow(
        workflow_ir,
        base_path=base_path,
        root_workflow_path=lookup_path,
        notes=notes,
    )
    edge_child_paths = _edge_child_paths(cw_result)
    trace_index = _build_trace_execution_index(trace_data, lookup_path, edge_child_paths)
    parameters_by_workflow = _build_parameters_by_workflow(
        cw_result,
        parameters or {},
        lookup_path,
        memo_cache=memo_cache,
        trace_data=trace_data,
        base_path=base_path,
    )

    # Build the AnalysisContext once and thread it through helpers. Bundles
    # (workflow_ir, parameters, memo_cache, trace_data, workflow_path,
    # base_path) so per-call helpers don't re-marshal these inputs at every
    # signature boundary. Methods on the context (resolve_ref_value,
    # cost_usd_for_node) own the policy that was previously scattered.
    ctx = AnalysisContext.build(
        workflow_ir=workflow_ir,
        parameters=parameters or {},
        memo_cache=memo_cache,
        trace_data=trace_data,
        workflow_path=lookup_path,
        base_path=base_path,
        parameters_by_workflow=parameters_by_workflow,
    )

    # Pass 1 (cheap): walk IR for shared template references — no tokenization.
    # Tier 2 of ``estimate_cacheable_tokens`` consumes the per-node candidate
    # subset to project cacheable counts via memo data.
    per_call_rows, warnings = _build_per_call_rows_and_warnings(
        ctx=ctx,
        cw_result=cw_result,
        trace_index=trace_index,
    )
    # Root-only by design: suggested-block, padding, and consolidate advisories
    # edit the analyzed file's ## Cache block. Child workflow recommendations
    # are exposed through the per-call rollup plus renderer drill-in commands
    # so agents run analyze-cache on the child before editing that file.
    rows_by_node = {row.node_path: row for row in per_call_rows if row.workflow_path == lookup_path}

    # Pass 2 (heavy): build paste-ready blocks. Uses ``model`` from rows +
    # tokenization for chunk sizes. Brownfield early-return preserved.
    suggested_blocks, shared_warnings = _populate_suggested_blocks(
        workflow_ir=workflow_ir,
        rows_by_node=rows_by_node,
        ctx=ctx,
        notes=notes,
    )
    warnings.extend(shared_warnings)

    # Option C — surface a Notes entry when the per-call section will render
    # empty so agents understand the absence is intentional. The renderer uses
    # the same predicate (``_row_has_real_data``) to decide visibility; we
    # mirror it here at analyze-time so the note appears in JSON too.
    if per_call_rows and not any(_row_has_real_data_in_analyze(r) for r in per_call_rows):
        notes.append(
            "Per-call cache report hidden — workflow has no run data yet. "
            "Run once, then re-run analyze-cache for real per-node token "
            "estimates and cacheable projections."
        )
    warnings.extend(_emit_padding_advisories(workflow_ir=workflow_ir, rows_by_node=rows_by_node))
    warnings.extend(
        _consolidate_to_root_advisories(
            workflow_ir=workflow_ir,
            rows_by_node=rows_by_node,
            declared_chunks=declared_chunks,
            ctx=ctx,
        )
    )
    warnings.extend(
        _detect_model_cache_fragmentation(
            workflow_ir=workflow_ir,
            rows_by_node=rows_by_node,
            declared_chunks=declared_chunks,
            ctx=ctx,
        )
    )
    warnings.extend(_cache_validator_findings(workflow_ir, workflow_path=lookup_path))

    # --- Cross-workflow walker ------------------------------------------------
    # Stage 0: walker now returns (graph_info, findings). Findings flow into
    # ``warnings`` (single source of truth); renderers categorize at output
    # time by filtering on ``Diagnostic.id``.
    cross_findings, cross_diagnostics = _build_cross_workflow_findings(cw_result=cw_result, notes=notes)
    warnings.extend(cross_diagnostics)
    if trace_data is not None:
        warnings.extend(
            _emit_discrepancy_diagnostics(
                ctx=ctx,
                cw_result=cw_result,
                notes=notes,
            )
        )

    # --- Confidence aggregation (STRICT per DD#34) ---------------------------
    confidence, coverage = _aggregate_confidence(per_call_rows)

    summary = _build_summary(
        per_call_rows,
        warnings,
        ttl=_extract_cache_ttl(cache_block),
        ctx=ctx,
        edge_child_paths=edge_child_paths,
    )
    summary = replace(
        summary,
        sub_workflow_rollup=_build_sub_workflow_rollup(
            cw_result,
            lookup_path,
            rows=per_call_rows,
            trace_index=trace_index,
            ttl=_extract_cache_ttl(cache_block),
            notes=notes,
        ),
    )

    # Recommended actions are a renderer-side projection over ``warnings``
    # (see ``view_helpers.build_recommended_actions``). No longer pre-computed
    # in the data model — Stage 0 of the data-shape redesign.

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
    Accepts any ``2.x`` trace; future additive minor bumps stay compatible
    via the ``startswith("2.")`` gate.
    """
    del notes  # currently unused; preserved for caller contract symmetry
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
    return data


def _autoload_trace(workflow_path: str | None, notes: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    """Find the newest 2.x trace whose ``workflow_path`` matches.

    O(matching-traces) lookup, not O(directory-size): trace filenames encode
    an 8-char md5 hash of ``workflow_path`` at write time (see
    ``runtime/workflow_trace.format_trace_filename``). The reader globs by the
    same hash prefix so we only read files that could match.

    Per DD#34, auto-load is a convenience; explicit loading
    (``--from-trace <path>``) is the contract.

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
        if str(data.get("format_version", "")).startswith("2."):
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


def _edge_child_paths(cw_result: Any) -> dict[str, str]:
    """Map parent workflow node id to child workflow path for trace threading.

    Used by the trace walker to attribute sub_workflow_events AND homogeneous
    static workflow batches to the resolved absolute child workflow path.
    The walker's ``cw_result.edges`` carry the runtime-resolved absolute
    path on each edge; this helper folds them into the
    ``parent_node_id → resolved_path`` shape that :meth:`TraceTree.walk`
    consumes via its ``edges=`` kwarg.

    **Why this still exists** (the cleanup plan called for deletion). Production
    traces store ``node_params["workflow"]`` as the RAW IR string the user
    wrote — often a relative path like ``./child.pflow.md``. The analyzer's
    ``cw_result.irs_by_workflow`` is keyed by the RESOLVED ABSOLUTE path
    produced by ``resolve_sub_workflow``. Pivoting attribution off
    ``node_params.workflow`` alone would mismatch the keys. This helper
    bridges raw → resolved by going through the walker's edges, which carry
    the resolved path.

    For HETEROGENEOUS workflow batches (one parent_node_id spawning child
    workflows of different paths via ``workflow: ${item.workflow}``), this
    map collapses the N edges into one (last-edge-wins) — that case is
    handled at higher precedence in :meth:`TraceTree.walk` by reading
    ``template_resolutions["workflow"]["resolved"]`` on each batch_item,
    so per-item attribution is correct even when this map is lossy. The
    edge-map fallback is consulted only for HOMOGENEOUS static workflow
    batches (single child workflow, no template), which have no per-item
    resolution metadata to override the parent-level edge.
    """
    paths: dict[str, str] = {}
    for edge in getattr(cw_result, "edges", ()) or ():
        parent_node_id = getattr(edge, "parent_node_id", None)
        child_workflow = getattr(edge, "child_workflow", None)
        if parent_node_id and child_workflow:
            paths[str(parent_node_id)] = str(child_workflow)
    return paths


def _build_trace_execution_index(
    trace_data: dict[str, Any] | None,
    root_workflow_path: str,
    edge_child_paths: dict[str, str],
) -> TraceExecutionIndex:
    """Index trace execution and LLM costs by ``(workflow_path, node_id)``.

    ``edge_child_paths`` provides the parent_node_id → resolved-absolute
    child workflow path mapping for sub_workflow_events. Heterogeneous
    workflow batches use per-item ``template_resolutions`` instead — this
    map's collision behaviour for those parents is intentionally bypassed
    inside :meth:`TraceTree.walk`.
    """
    if trace_data is None:
        return TraceExecutionIndex({}, {}, set(), set(), {})
    from pflow.core.trace_tree import TraceTree

    try:
        tree = TraceTree.from_dict(trace_data)
    except ValueError:
        return TraceExecutionIndex({}, {}, set(), set(), {})

    totals: dict[tuple[str | None, str], float] = {}
    workflow_totals: dict[str | None, float] = {}
    workflow_found: set[str | None] = set()
    found: set[tuple[str | None, str]] = set()
    partial: set[tuple[str | None, str]] = set()
    llm_calls_by_key: dict[tuple[str | None, str], dict[str, Any]] = {}
    executed_keys: set[tuple[str | None, str]] = set()
    workflows_with_trace: set[str | None] = set()
    for we in tree.walk(edges=edge_child_paths, workflow_path=root_workflow_path):
        # Batch items typically lack their own node_id; fall back to the
        # owner (the batch parent's id) so they're attributed to the parent.
        node_id = str(we.event.get("node_id", we.owner_node_id))
        executed_keys.add((we.workflow_path, node_id))
        workflows_with_trace.add(we.workflow_path)
    for leaf in tree.iter_llm_leaves(edges=edge_child_paths, workflow_path=root_workflow_path):
        call = leaf.llm_call
        if call is None:
            continue
        node_id = leaf.event_node_id if leaf.tier == "sub_workflow_descendant" else leaf.owner_node_id
        key = (leaf.workflow_path or root_workflow_path, node_id)
        workflow_key = leaf.workflow_path or root_workflow_path
        # Always populate the call index — cached events carry historical
        # ``input_tokens`` / ``output_tokens`` preserved from the original
        # run, which downstream tier-1 token readers (``_estimate_row_tokens``)
        # need to project costs for memo-hit-only traces. Cost summation is
        # gated separately below.
        llm_calls_by_key.setdefault(key, dict(call))
        if leaf.is_cached:
            # Cached events: this run paid $0 (cache hit). Skip the cost
            # summation only — the index population above gives token
            # readers access to the historical llm_call data without
            # inflating cost. Mirrors compute_actually_paid's
            # total_cost(include_cached=False).
            continue
        if "cost_usd" not in call:
            continue
        found.add(key)
        workflow_found.add(workflow_key)
        cost = call.get("cost_usd")
        if cost is None:
            partial.add(key)
            totals.setdefault(key, 0.0)
            workflow_totals.setdefault(workflow_key, 0.0)
        else:
            totals[key] = totals.get(key, 0.0) + float(cost)
            workflow_totals[workflow_key] = workflow_totals.get(workflow_key, 0.0) + float(cost)
    costs_by_key: dict[tuple[str | None, str], tuple[float | None, str]] = {
        key: (totals.get(key, 0.0), "trace_partial" if key in partial else "trace") for key in found
    }
    cost_by_workflow: dict[str | None, float | None] = {key: workflow_totals.get(key, 0.0) for key in workflow_found}
    return TraceExecutionIndex(
        costs_by_key=costs_by_key,
        llm_calls_by_key=llm_calls_by_key,
        executed_keys=executed_keys,
        workflows_with_trace=workflows_with_trace,
        current_cost_by_workflow=cost_by_workflow,
    )


def _build_sub_workflow_rollup(
    cw_result: Any,
    root_workflow_path: str,
    *,
    rows: list[PerCallRow],
    trace_index: TraceExecutionIndex,
    ttl: str | None,
    notes: list[str],
) -> SubWorkflowRollup | None:
    """Build metadata and dollar attribution for included child workflows."""
    from .cost_estimation import compute_projections

    workflows = [path for path in getattr(cw_result, "irs_by_workflow", {}) if path != root_workflow_path]
    if not workflows:
        return None
    parent_by_child: dict[str, str] = {}
    for edge in getattr(cw_result, "edges", ()) or ():
        child = str(getattr(edge, "child_workflow", ""))
        parent_by_child.setdefault(child, str(getattr(edge, "parent_node_id", "")))
    rows_by_workflow: dict[str | None, list[PerCallRow]] = {}
    for row in rows:
        rows_by_workflow.setdefault(row.workflow_path, []).append(row)
    entries_list: list[SubWorkflowRollupEntry] = []
    for path in sorted(workflows):
        workflow_rows = rows_by_workflow.get(path, [])
        output_tokens: Mapping[tuple[str | None, str] | str, int | None] = {
            (row.workflow_path, row.node_path): row.output_tokens_estimated for row in workflow_rows
        }
        projections = compute_projections(workflow_rows, output_tokens_by_node=output_tokens, ttl=ttl)
        entries_list.append(
            SubWorkflowRollupEntry(
                workflow_path=str(path),
                called_by_node_id=parent_by_child.get(str(path), ""),
                llm_node_count=_count_llm_nodes(getattr(cw_result, "irs_by_workflow", {}).get(path, {})),
                actually_paid_usd=trace_index.current_cost_by_workflow.get(path),
                no_cache_hypothetical_usd=projections.no_cache_hypothetical_usd,
                first_run_with_cache_hypothetical_usd=projections.first_run_with_cache_hypothetical_usd,
                rerun_within_ttl_hypothetical_usd=projections.rerun_within_ttl_hypothetical_usd,
            )
        )
    truncated = _has_cross_workflow_truncation(notes)
    return SubWorkflowRollup(
        workflows_included=tuple(entry.workflow_path for entry in entries_list),
        max_depth_walked=len(entries_list),
        truncated=truncated,
        per_workflow=tuple(entries_list),
    )


def _has_cross_workflow_truncation(notes: list[str]) -> bool:
    return any(
        "Cross-workflow walker reached max_depth" in note or "Cross-workflow walker detected cycle" in note
        for note in notes
    )


def _count_llm_nodes(ir: dict[str, Any]) -> int:
    return sum(1 for node in ir.get("nodes", []) or [] if isinstance(node, dict) and node.get("type") == "llm")


def _build_parameters_by_workflow(
    cw_result: Any,
    root_parameters: dict[str, Any],
    root_workflow_path: str,
    *,
    memo_cache: Any | None,
    trace_data: Mapping[str, Any] | None,
    base_path: Path | None,
) -> dict[str | None, dict[str, Any]]:
    """Build workflow-scoped parameter views from cross-workflow input edges."""
    params_by_workflow: dict[str | None, dict[str, Any]] = {root_workflow_path: dict(root_parameters)}
    irs_by_workflow = getattr(cw_result, "irs_by_workflow", {}) or {}
    remaining = list(getattr(cw_result, "edges", ()) or ())
    made_progress = True
    while remaining and made_progress:
        made_progress = False
        next_remaining = []
        for edge in remaining:
            parent_workflow = str(getattr(edge, "parent_workflow", root_workflow_path))
            if parent_workflow not in params_by_workflow:
                next_remaining.append(edge)
                continue
            child_workflow = getattr(edge, "child_workflow", None)
            child_input_name = getattr(edge, "child_input_name", None)
            if child_workflow is None or child_input_name is None:
                continue
            parent_ctx = AnalysisContext.build(
                workflow_ir=irs_by_workflow.get(parent_workflow, {}),
                parameters=params_by_workflow[parent_workflow],
                memo_cache=memo_cache,
                trace_data=trace_data,
                workflow_path=parent_workflow,
                base_path=base_path,
                parameters_by_workflow=params_by_workflow,
            )
            resolved = _resolve_child_input_value(getattr(edge, "parent_input_value", None), parent_ctx)
            if resolved is None:
                continue
            child_params = params_by_workflow.setdefault(str(child_workflow), {})
            child_params[str(child_input_name)] = resolved
            made_progress = True
        remaining = next_remaining
    return params_by_workflow


def _resolve_child_input_value(value: Any, parent_ctx: AnalysisContext) -> Any | None:
    """Resolve a workflow-node input value against its parent workflow context."""
    if not isinstance(value, str):
        return _normalize_empty(value)
    refs = _extract_unique_refs(value)
    if not refs:
        return _normalize_empty(value)
    shared = _build_shared_store_for_refs(refs, parent_ctx)
    try:
        resolved = TemplateResolver.resolve_template(value, shared)
    except Exception:
        logger.debug("failed to resolve child workflow input value", exc_info=True)
        return None
    if isinstance(resolved, str) and TemplateResolver.TEMPLATE_PATTERN.search(resolved):
        return None
    return _normalize_empty(resolved)


def _build_per_call_rows_and_warnings(
    *,
    ctx: AnalysisContext,
    cw_result: Any,
    trace_index: TraceExecutionIndex,
) -> tuple[list[PerCallRow], list[Diagnostic]]:
    """Walk every reachable workflow IR and build LLM rows."""
    rows: list[PerCallRow] = []
    warnings: list[Diagnostic] = []
    for workflow_path, workflow_ir in getattr(cw_result, "irs_by_workflow", {}).items():
        declared_chunks = _extract_declared_chunks(workflow_ir.get("cache"))
        candidate_subsets_by_node = _detect_candidate_subsets(workflow_ir)
        wf_ctx = AnalysisContext.build(
            workflow_ir=workflow_ir,
            parameters=ctx.parameters_for_workflow(workflow_path),
            memo_cache=ctx.memo_cache,
            trace_data=ctx.trace_data,
            workflow_path=workflow_path,
            base_path=ctx.base_path,
            parameters_by_workflow=ctx.parameters_by_workflow,
        )
        nodes = workflow_ir.get("nodes", []) or []
        nodes_by_id: dict[str, dict[str, Any]] = {
            str(n.get("id", "")): n for n in nodes if isinstance(n, dict) and n.get("id")
        }
        for node in nodes:
            if not isinstance(node, dict) or node.get("type") != "llm":
                continue
            node_id = str(node.get("id", "?"))
            row = _build_per_call_row(
                node=node,
                ctx=wf_ctx,
                declared_chunks=declared_chunks,
                candidate_subset=candidate_subsets_by_node.get(node_id),
                trace_cost=trace_index.costs_by_key.get((workflow_path, node_id)),
                trace_llm_call=trace_index.llm_calls_by_key.get((workflow_path, node_id)),
                did_not_execute_in_trace=(
                    workflow_path in trace_index.workflows_with_trace
                    and (workflow_path, node_id) not in trace_index.executed_keys
                ),
            )
            rows.append(row)
            warnings.extend(_per_node_warnings(node, row, declared_chunks=declared_chunks, nodes_by_id=nodes_by_id))
    return rows, warnings


def _detect_candidate_subsets(workflow_ir: dict[str, Any]) -> dict[str, list[str]]:
    """Map LLM node_id → list of shared template refs (≥2 nodes share each).

    Pure walker — no tokenization. Tier 2 of ``estimate_cacheable_tokens``
    consumes the per-node candidate to project cacheable counts via memo.

    Returns an empty dict when the workflow already declares ``## Cache``
    (greenfield-only signal — declared subsets win at Tier 1/2; candidates
    don't apply when ``prompt_cache:`` is set).
    """
    if _cache_item_names(workflow_ir):
        return {}
    ref_to_nodes, _ = _collect_llm_template_references(workflow_ir)
    candidates_by_node: dict[str, list[str]] = {}
    for ref, node_ids in ref_to_nodes.items():
        if len(node_ids) < 2:
            continue
        for node_id in node_ids:
            candidates_by_node.setdefault(node_id, []).append(ref)
    return candidates_by_node


# ---------------------------------------------------------------------------
# Per-node analysis
# ---------------------------------------------------------------------------


def _build_per_call_row(
    *,
    node: dict[str, Any],
    ctx: AnalysisContext,
    declared_chunks: list[str],
    candidate_subset: list[str] | None = None,
    trace_cost: tuple[float | None, str] | None = None,
    trace_llm_call: dict[str, Any] | None = None,
    did_not_execute_in_trace: bool = False,
) -> PerCallRow:
    """Compose a single PerCallRow for an LLM node."""
    workflow_path = ctx.workflow_path
    memo_cache = ctx.memo_cache
    node_id = str(node.get("id", "?"))
    # Effective model resolution mirrors compiler.py:281-285 — explicit per-node
    # ``model:`` wins; absence falls back to ``get_default_workflow_model()``
    # (settings.default_model → API-key auto-detect → None). Without this fallback
    # the per-call table renders ``model=`` empty for nodes that inherit the
    # default, ``models_in_use`` undercounts, and cost computation can never
    # price these rows. Tests that need deterministic model values monkeypatch
    # ``pflow.core.cache_analysis.analyze.get_default_workflow_model``.
    #
    # Stage C.1: when the explicit model is an unresolved ``${...}`` template
    # (heterogeneous batch sub-workflow — model varies per item), neither the
    # literal template nor the default-model fallback is honest. Mark the row
    # as heterogeneous; ``model = ""`` so the existing ``if row.model`` checks
    # in ``cost_estimation`` and ``_format_scale_line`` short-circuit, and
    # rendering shows ``model=<varies>`` instead of the literal ``${item.model}``
    # leaking through.
    explicit = node.get("params", {}).get("model") or node.get("model")
    model_is_heterogeneous = isinstance(explicit, str) and "${" in explicit
    if model_is_heterogeneous:
        model = ""
    elif explicit:
        model = str(explicit)
    else:
        model = get_default_workflow_model() or ""
    prompt = node.get("params", {}).get("prompt", "")
    if not isinstance(prompt, str):
        prompt = str(prompt) if prompt is not None else ""
    batch = node.get("batch")
    is_batch = isinstance(batch, dict) and bool(batch)
    batch_size = _estimate_batch_size(batch) if isinstance(batch, dict) and is_batch else None

    # Track C (Phase C): resolve the prompt template before tokenization so
    # ${context}, ${question}, etc. count as their actual byte lengths
    # instead of the literal ``${context}`` string (~5 chars). Trace tier
    # short-circuits before this — for trace data the input_tokens come
    # straight from ``llm_call.input_tokens`` and template resolution is
    # irrelevant. For the estimator tier on greenfield workflows, resolved
    # prompts produce realistic token counts when the agent passes
    # ``--inputs`` covering the referenced variables.
    resolved_prompt, has_unresolved = _resolve_prompt_for_tokenization(prompt, ctx, node)
    declared_subset = node.get("prompt_cache") or None
    if declared_subset is not None and not isinstance(declared_subset, list):
        declared_subset = None
    input_tokens, source, output_tokens, output_source = _estimate_row_tokens(
        model=model,
        resolved_prompt=resolved_prompt,
        memo_cache=memo_cache,
        node_id=node_id,
        workflow_path=workflow_path,
        has_unresolved=has_unresolved,
        trace_llm_call=trace_llm_call,
        declared_subset=declared_subset,
        ctx=ctx,
    )

    # Tiered cacheable estimation (mirrors ``estimate_tokens`` /
    # ``estimate_output_tokens``). Trace beats memo beats heuristic; honest
    # ``None`` when nothing is projectable. ``declared_chunks`` (workflow-level
    # ## Cache items) is consumed elsewhere; here we pass declared_subset
    # (this node's ``prompt_cache:``) and candidate_subset (greenfield
    # candidates from shared template references).
    trace_event = trace_llm_call
    cacheable_tokens, cacheable_source = estimate_cacheable_tokens(
        declared_subset=declared_subset,
        candidate_subset=candidate_subset,
        trace_event=trace_event,
        memo_cache=memo_cache,
        model=model,
        workflow_path=workflow_path,
        prompt=resolved_prompt,
        ctx=ctx,
    )

    # Explicit 3-way: None / 0 / positive (preserves Option C visibility
    # contract — None hides the row, 0 shows "no cacheable yet", positive
    # shows the real estimate).
    cacheable_with_clamp: int | None
    ratio: int | None
    if cacheable_tokens is None:
        cacheable_with_clamp = None
        ratio = None
    elif cacheable_tokens > 0:
        cacheable_with_clamp = min(cacheable_tokens, input_tokens)
        ratio = _safe_pct(cacheable_with_clamp, input_tokens)
    else:
        cacheable_with_clamp = 0
        ratio = 0

    # Track A (Phase A): per-node recorded cost from the trace. When trace
    # data exists for this node, the analyzer reports what the workflow
    # actually paid (honoring implicit caching like Gemini's). The renderer
    # uses this for the per-call cost column; the summary's actually-paid
    # figure is sourced separately via ``compute_actually_paid`` (which
    # prefers ``TraceTree.total_cost`` for the canonical sum).
    cost_value: float | None
    cost_source: str
    cost_value, cost_source = trace_cost if trace_cost is not None else ctx.cost_usd_for_node(node_id)
    if did_not_execute_in_trace:
        cost_value = None
        cost_source = "unavailable"
    elif cost_value is None:
        # No trace data — recompute fallback fires downstream. Mark the
        # tier label so the JSON consumer sees ``"recomputed"`` not
        # ``"unavailable"`` (the latter signals "no pricing data either",
        # which is checked by the renderer separately via ``unavailable_models``).
        cost_source = "recomputed"

    return PerCallRow(
        node_path=node_id,
        model=model,
        is_batch=is_batch,
        batch_size_estimated=batch_size,
        input_tokens_estimated=input_tokens,
        cacheable_tokens_estimated=cacheable_with_clamp,
        cache_ratio_pct=ratio,
        data_source=source,
        declared_prompt_cache=list(declared_subset) if declared_subset else None,
        output_tokens_estimated=output_tokens,
        output_data_source=output_source,
        model_is_heterogeneous=model_is_heterogeneous,
        cacheable_data_source=cacheable_source,
        cost_usd=cost_value,
        cost_data_source=cost_source,
        workflow_path=workflow_path,
        did_not_execute_in_trace=did_not_execute_in_trace,
    )


def _estimate_row_tokens(
    *,
    model: str,
    resolved_prompt: str,
    memo_cache: Any,
    node_id: str,
    workflow_path: str | None,
    has_unresolved: bool,
    trace_llm_call: dict[str, Any] | None,
    declared_subset: list[str] | None = None,
    ctx: AnalysisContext | None = None,
) -> tuple[int, str, int | None, str]:
    """Estimate input/output tokens for one workflow-scoped row.

    ``input_tokens`` is the LLM-billed total — prompt body PLUS cache content.
    Without that semantic, the cacheable-vs-input clamp at the call site
    would truncate correct cacheable estimates whenever ``## Cache`` chunks
    were referenced by name (``prompt_cache: [name]``) but not inlined in
    the prompt body. See Bug 4 in the verification report.

    Trace-tier accounting is provider-aware: providers that report
    ``input_tokens`` excluding the cache portion (with cache contribution in
    ``cache_creation_input_tokens`` + ``cache_read_input_tokens``) need both
    summed for total billed tokens. Either cache field can be zero on the
    same call — first-write events have ``cache_creation > 0, cache_read == 0``;
    rerun-within-TTL has ``cache_creation == 0, cache_read > 0``. Providers
    that fold cache into ``input_tokens`` already need no sum. The
    discriminator lives on ``ProviderInfo.splits_cache_from_input_tokens``
    (data-driven, not value-based) — value-based heuristics (e.g.
    ``cache_creation > 0``) silently misclassify split-style cache-read
    events as fold-style and truncate ``input_tokens`` on the most common
    cached scenario. Long-term fix: normalize ``billed_input_tokens`` at
    ``llm_client._normalize``.
    """
    if trace_llm_call is not None and isinstance(trace_llm_call.get("input_tokens"), int):
        input_tokens = int(trace_llm_call["input_tokens"])
        provider = detect_provider(trace_llm_call.get("model") or model)
        if provider is not None and provider.splits_cache_from_input_tokens:
            cache_creation = int(trace_llm_call.get("cache_creation_input_tokens") or 0)
            cache_read = int(trace_llm_call.get("cache_read_input_tokens") or 0)
            input_tokens = input_tokens + cache_creation + cache_read
        source = "trace"
    else:
        input_tokens, source = estimate_tokens(
            model,
            resolved_prompt,
            trace=None,
            memo_cache=memo_cache,
            node_id=node_id,
            workflow_path=workflow_path,
            has_unresolved_refs=has_unresolved,
        )
        if declared_subset and ctx is not None and model:
            input_tokens += _tokenize_declared_cache_chunks(
                declared_subset=declared_subset,
                workflow_ir=ctx.workflow_ir,
                model=model,
                memo_cache=memo_cache,
                workflow_path=workflow_path,
                ctx=ctx,
            )
    if trace_llm_call is not None and isinstance(trace_llm_call.get("output_tokens"), int):
        output_tokens: int | None = int(trace_llm_call["output_tokens"])
        output_source = "trace"
    else:
        output_tokens, output_source = estimate_output_tokens(
            trace=None,
            memo_cache=memo_cache,
            node_id=node_id,
            workflow_path=workflow_path,
        )
    return input_tokens, source, output_tokens, output_source


def _tokenize_declared_cache_chunks(
    *,
    declared_subset: list[str],
    workflow_ir: Mapping[str, Any],
    model: str,
    memo_cache: Any,
    workflow_path: str | None,
    ctx: AnalysisContext,
) -> int:
    """Tokenize the resolved values of declared cache chunks.

    Returns the total token count for chunks that resolved against parameters
    or memo. Unresolvable chunks contribute 0 (matching the partial-resolution
    semantics callers already accept for the prompt body itself).
    """
    if not isinstance(workflow_ir, Mapping):
        return 0
    cache_block = workflow_ir.get("cache")
    if not isinstance(cache_block, dict):
        return 0
    items = cache_block.get("items") or []
    if not isinstance(items, list):
        return 0
    chunks_by_name: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        var_expr = item.get("var") or name
        if isinstance(name, str) and isinstance(var_expr, str) and var_expr:
            chunks_by_name[name] = var_expr
    total = 0
    for chunk_name in declared_subset:
        var_expr = chunks_by_name.get(str(chunk_name))
        if not var_expr:
            continue
        tokens = _estimate_ref_tokens(
            var_expr,
            model=model,
            memo_cache=memo_cache,
            workflow_path=workflow_path,
            ctx=ctx,
        )
        if tokens is not None:
            total += tokens
    return total


def _resolve_prompt_for_tokenization(prompt: str, ctx: AnalysisContext, node: dict[str, Any]) -> tuple[str, bool]:
    """Substitute ``${...}`` refs in ``prompt`` against parameters + memo.

    Returns ``(resolved_text, has_unresolved_refs)``. ``has_unresolved_refs``
    is True when at least one ``${...}`` remained unresolved after the
    substitution pass — caller passes this through to ``estimate_tokens``
    so the tier label can shift to ``"estimator-partial"``.

    Batch nodes: alias references (``${item.X}``) are inherently dynamic
    (resolved per item at run-time); they always remain unresolved here
    and trip ``has_unresolved_refs=True`` — correct, tokenization without
    a concrete batch item is necessarily approximate.
    """
    if not isinstance(prompt, str) or not prompt:
        return prompt or "", False

    refs = _extract_unique_refs(prompt)
    if not refs:
        return prompt, False

    shared = _build_shared_store_for_refs(refs, ctx)

    try:
        resolved = TemplateResolver.resolve_template(prompt, shared)
    except Exception:
        # Defensive: a malformed template shouldn't take down the analyzer.
        logger.debug("template resolution raised on prompt for node %r", node.get("id"), exc_info=True)
        return prompt, True

    if not isinstance(resolved, str):
        # Single-ref templates can return non-string values (e.g. dict).
        from pflow.core.cache_render import deterministic_serialize

        resolved = deterministic_serialize(resolved)

    has_unresolved = bool(TemplateResolver.TEMPLATE_PATTERN.search(resolved))
    return resolved, has_unresolved


def _extract_unique_refs(prompt: str) -> list[str]:
    """Walk ``prompt`` for unique template refs (deduped, order-preserving)."""
    refs: list[str] = []
    for match in TemplateResolver.TEMPLATE_PATTERN.finditer(prompt):
        for operand in TemplateResolver.split_coalesce_operands(match.group(1)):
            if operand and operand not in refs:
                refs.append(operand)
    return refs


def _build_shared_store_for_refs(refs: list[str], ctx: AnalysisContext) -> dict[str, Any]:
    """Build a synthetic shared store keyed by root node ids for ``refs``."""
    shared: dict[str, Any] = {}
    for ref in refs:
        root = TemplateResolver.extract_root_node_id(ref)
        if not root or root in shared:
            continue
        # Resolve the ROOT, not the ref — TemplateResolver navigates dotted
        # paths against the root's value. The context's resolution policy
        # (parameters wins for input refs; memo for node-output refs) fires
        # transparently here.
        value = ctx.resolve_ref_value(root)
        if value is not None:
            shared[root] = value
    return shared


def _row_has_real_data_in_analyze(row: PerCallRow) -> bool:
    """Mirror of ``render_text._row_has_real_data`` for analyze-time decisions.

    Kept as a private duplicate (analyze.py shouldn't depend on render_text.py)
    that MUST stay byte-equivalent — see ``render_text._row_has_real_data``
    for contract documentation.
    """
    return row.data_source in {"trace", "memo"} or bool(row.declared_prompt_cache) or row.model_is_heterogeneous


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
    # in steady-state where cacheable is always int. ALSO gates on
    # ``cacheable_data_source != "trace"``: when source is trace AND cacheable
    # is nonzero, cache demonstrably worked at this size; the warning would
    # contradict trace evidence. When source is memo/estimator (or trace
    # fell through), the warning fires correctly.
    cacheable = row.cacheable_tokens_estimated
    if (
        row.declared_prompt_cache
        and cacheable is not None
        and cacheable > 0
        and row.model
        and row.cacheable_data_source != "trace"
    ):
        min_tokens = get_min_cache_tokens(row.model)
        if cacheable < min_tokens:
            diagnostics.append(
                make_diagnostic(
                    "cache.below-min-tokens",
                    node_id=node_id,
                    affected_workflow=row.workflow_path,
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
                        affected_workflow=row.workflow_path,
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
            affected_workflow=row.workflow_path,
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
                affected_workflow=row.workflow_path,
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
            affected_workflow=row.workflow_path,
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


def _starter_prose_for_ref(ref: str) -> str:
    """Auto-generated humble label for a suggested cache chunk.

    Single-segment paths render as ``The X:`` (underscores → spaces).
    Dotted paths render as ``The Y from X:`` (Y = field, X = node).

    The agent should replace these with workflow-domain-specific prose
    before first run; the analyzer can't synthesize semantic descriptions
    because it doesn't know the workflow's domain. The starter form is
    byte-valid as-is so caching works on first run even without editing.
    """
    if "." in ref:
        node, _, tail = ref.partition(".")
        field = tail.replace("_", " ")
        return f"The {field} from {node}:"
    return f"The {ref.replace('_', ' ')}:"


def _populate_suggested_blocks(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    ctx: AnalysisContext,
    notes: list[str],
) -> tuple[list[SuggestedBlock], list[Diagnostic]]:
    """Build greenfield suggested ``## Cache`` blocks + advisory.

    v1 covers greenfield only (per DD#3). When ``## Cache`` is already
    declared, append a note so agents understand why no suggestion was
    produced — silent return would otherwise hide the deferral.

    Per-node cacheable projection used to flow back via this pass; that
    responsibility now lives in ``estimate_cacheable_tokens`` (Tier 2 reads
    candidate subsets directly from the IR walker via
    ``_detect_candidate_subsets``).
    """
    declared_names = set(_cache_item_names(workflow_ir))
    if declared_names:
        notes.append(
            "Suggested-blocks: workflow already declares ## Cache; steady-state "
            "(partial-block) suggestions deferred to v1.x."
        )
        return [], []

    ref_to_nodes, first_seen = _collect_llm_template_references(workflow_ir)
    shared_refs = [(ref, nodes) for ref, nodes in ref_to_nodes.items() if len(nodes) >= 2]
    if not shared_refs:
        return [], []

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

    memo_cache = ctx.memo_cache
    workflow_path = ctx.workflow_path
    for ref, node_ids in shared_refs:
        first_row = rows_by_node.get(node_ids[0])
        model = first_row.model if first_row else ""
        size_tokens = _estimate_ref_tokens(
            ref, model=model, memo_cache=memo_cache, workflow_path=workflow_path, ctx=ctx
        )
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
                prose_placeholder=_starter_prose_for_ref(ref),
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

    target_file = workflow_path or "<root>"
    block = SuggestedBlock(
        target_file=target_file,
        ttl="5m",
        chunks=tuple(chunks),
        per_node_assignments={node_id: assignments[node_id] for node_id in sorted(assignments)},
        estimated_savings_usd=total_savings,
        prompt_body_cleanup=_compute_prompt_body_cleanup(workflow_ir, chunks, assignments),
    )
    warning = make_diagnostic(
        "cache.shared-context-undeclared",
        node_id=None,
        node_count=len(affected_nodes),
        shared_chunks=[chunk.name for chunk in chunks],
        affected_workflow=target_file,
        savings_usd=total_savings,
    )
    return [block], [warning]


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
    ctx: AnalysisContext,
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
            ctx=ctx,
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
    ctx: AnalysisContext,
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
    memo_cache = ctx.memo_cache
    workflow_path = ctx.workflow_path
    sub_path_tokens = [
        _estimate_ref_tokens(sp, model=model, memo_cache=memo_cache, workflow_path=workflow_path, ctx=ctx)
        for sp in sub_paths
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
    root_tokens = _estimate_ref_tokens(root, model=model, memo_cache=memo_cache, workflow_path=workflow_path, ctx=ctx)
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


def _detect_model_cache_fragmentation(
    *,
    workflow_ir: dict[str, Any],
    rows_by_node: dict[str, PerCallRow],
    declared_chunks: list[str],
    ctx: AnalysisContext,
) -> list[Diagnostic]:
    """Emit per-model prompt-cache fragmentation and write-penalty diagnostics.

    Provider caches are keyed by exact model. Two nodes that declare the same
    cached bytes but call different exact models each pay their own cache write;
    the cache is not shared across model namespaces. This detector is root-only
    like the other edit-scope advisories in ``analyze()``.
    """
    if not declared_chunks:
        return []
    rows = [
        row
        for row in rows_by_node.values()
        if row.declared_prompt_cache
        and row.model
        and not row.model_is_heterogeneous
        and not row.did_not_execute_in_trace
    ]
    if not rows:
        return []

    groups = _group_prompt_cache_rows_by_model(rows)
    node_by_id = {str(n.get("id")): n for n in workflow_ir.get("nodes", []) if isinstance(n, dict) and n.get("id")}
    diagnostics: list[Diagnostic] = []

    fragmented_groups = _model_groups_with_shared_chunks(groups)
    if len(fragmented_groups) >= 2:
        sorted_groups = sorted(fragmented_groups, key=lambda group: (-len(group["rows"]), str(group["model"])))
        shared_chunks = _chunks_shared_across_groups(sorted_groups)
        costs = _compute_model_group_costs(
            sorted_groups,
            shared_chunks,
            ttl=_extract_cache_ttl(workflow_ir.get("cache")),
            ctx=ctx,
        )
        if costs is not None:
            redundant_groups = sorted_groups[1:]
            savings_usd = sum(costs[str(group["model"])] for group in redundant_groups)
            model_groups = _model_groups_payload(sorted_groups, costs)
            diagnostics.append(
                make_diagnostic(
                    "cache.heterogeneous-models-fragment-cache",
                    node_id=None,
                    model_group_count=len(sorted_groups),
                    models_csv=", ".join(str(group["model"]) for group in sorted_groups),
                    model_groups=model_groups,
                    model_groups_lines=_format_model_groups_lines(model_groups),
                    shared_chunks=sorted(shared_chunks),
                    affected_workflow=ctx.workflow_path,
                    savings_usd=savings_usd,
                )
            )

    for group in sorted(groups.values(), key=lambda item: str(item["model"])):
        group_rows = group["rows"]
        if len(group_rows) != 1:
            continue
        row = group_rows[0]
        node = node_by_id.get(row.node_path)
        if isinstance(node, dict) and node.get("prewarm") is True:
            continue
        model = str(group["model"])
        if model.startswith("gemini/"):
            continue
        penalty = _single_call_write_penalty(row, ttl=_extract_cache_ttl(workflow_ir.get("cache")))
        if penalty is None:
            continue
        diagnostics.append(
            make_diagnostic(
                "cache.first-call-write-penalty",
                node_id=row.node_path,
                model=model,
                affected_workflow=ctx.workflow_path,
                savings_usd=penalty,
            )
        )

    return diagnostics


def _group_prompt_cache_rows_by_model(rows: list[PerCallRow]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        model = normalize_model_name(row.model)
        group = groups.setdefault(model, {"model": model, "rows": [], "chunks": set()})
        group["rows"].append(row)
        group["chunks"].update(str(chunk) for chunk in row.declared_prompt_cache or ())
    return groups


def _model_groups_with_shared_chunks(groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [group for group in groups.values() if _chunks_shared_with_other_group(group, groups.values())]


def _chunks_shared_with_other_group(group: dict[str, Any], all_groups: Iterable[dict[str, Any]]) -> set[str]:
    chunks = set(group["chunks"])
    shared: set[str] = set()
    for other in all_groups:
        if other is group:
            continue
        shared.update(chunks & set(other["chunks"]))
    return shared


def _chunks_shared_across_groups(groups: list[dict[str, Any]]) -> set[str]:
    shared: set[str] = set()
    for group in groups:
        shared.update(_chunks_shared_with_other_group(group, iter(groups)))
    return shared


def _compute_model_group_costs(
    groups: list[dict[str, Any]],
    shared_chunks: set[str],
    *,
    ttl: str | None,
    ctx: AnalysisContext,
) -> dict[str, float] | None:
    """Sum each group's redundant cache_creation cost over the SHARED chunks only.

    Honest-unmeasurable: returns ``None`` if any group lacks pricing OR any
    shared chunk has no resolvable token estimate (memo miss in greenfield).
    Mirrors ``_check_root_for_consolidation``'s "any None → skip" pattern so
    the warning never fabricates dollars when chunk-level data is unavailable.
    """
    from .cost_estimation import _write_rate_for_ttl, get_model_pricing

    costs: dict[str, float] = {}
    for group in groups:
        model = str(group["model"])
        pricing = get_model_pricing(model)
        if pricing is None:
            return None
        group_shared = group["chunks"] & shared_chunks
        chunk_tokens = [
            _estimate_ref_tokens(
                chunk,
                model=model,
                memo_cache=ctx.memo_cache,
                workflow_path=ctx.workflow_path,
                ctx=ctx,
            )
            for chunk in group_shared
        ]
        if any(tokens is None for tokens in chunk_tokens):
            return None
        total_tokens = sum(tokens for tokens in chunk_tokens if tokens is not None)
        costs[model] = total_tokens * _write_rate_for_ttl(pricing, ttl, model)
    return costs


def _model_groups_payload(groups: list[dict[str, Any]], costs: dict[str, float]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for group in groups:
        rows = sorted(group["rows"], key=lambda row: row.node_path)
        model = str(group["model"])
        payload.append({
            "model": model,
            "node_paths": [row.node_path for row in rows],
            "node_count": len(rows),
            "cache_creation_cost_usd": costs[model],
        })
    return payload


def _format_model_groups_lines(groups: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for group in groups:
        node_paths = ", ".join(str(path) for path in group["node_paths"])
        noun = "node" if group["node_count"] == 1 else "nodes"
        lines.append(f"  - {group['model']} ({group['node_count']} {noun}): {node_paths}")
    return "\n".join(lines)


def _single_call_write_penalty(row: PerCallRow, *, ttl: str | None) -> float | None:
    """Return the savings (write premium - input cost) from removing the cache declaration.

    ``None`` when pricing or token data is unavailable (honest-unmeasurable).
    Positive value = removing the declaration saves money. Mirrors the catalog's
    ``savings_usd`` semantics ("savings from fixing it").
    """
    from .cost_estimation import _write_rate_for_ttl, get_model_pricing

    tokens = row.cacheable_tokens_estimated
    if tokens is None:
        return None
    pricing = get_model_pricing(row.model)
    if pricing is None:
        return None
    input_rate = _input_rate(row.model)
    if input_rate is None:
        return None
    return tokens * _write_rate_for_ttl(pricing, ttl, row.model) - tokens * input_rate


def _batch_aliases(node: dict[str, Any]) -> set[str]:
    batch = node.get("batch")
    if not isinstance(batch, dict):
        return set()
    return {str(batch.get("as", "item"))}


def _compute_prompt_body_cleanup(
    workflow_ir: dict[str, Any],
    chunks: list[SuggestedBlockChunk],
    assignments: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Per-node prompt-body cleanup hint for greenfield SuggestedBlock.

    For each node being assigned cached chunks, lists the inline ``${...}``
    references that would overlap and need to be removed from the prompt
    body so agents following the analyzer's recommendation don't silently
    keep the inline refs and cancel out the cache savings.

    Returns ``{node_id: sorted unique body refs}``. Nodes without overlap
    don't appear in the dict.
    """
    from pflow.core.cache_overlap import compute_overlaps

    nodes_by_id_local = {n["id"]: n for n in workflow_ir.get("nodes", []) if isinstance(n, dict) and n.get("id")}
    chunk_name_set = {chunk.name for chunk in chunks}
    cleanup: dict[str, list[str]] = {}
    for node_id, assigned_chunk_names in assignments.items():
        node = nodes_by_id_local.get(node_id)
        if node is None:
            continue
        prompt_text = node.get("params", {}).get("prompt", "") or ""
        if not isinstance(prompt_text, str):
            continue
        overlaps = compute_overlaps(
            prompt_text=prompt_text,
            prompt_cache=assigned_chunk_names,
            cache_item_names=chunk_name_set,
            batch_aliases=_batch_aliases(node),
        )
        if overlaps:
            cleanup[node_id] = sorted({o.body_ref for o in overlaps})
    return cleanup


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
                workflow_path=row.workflow_path,
                current_subset=current_subset,
                suggested_subset=tuple(declared_names[:first_pos]) + current_subset,
                savings_usd=savings_usd,
            )
        )
    return compute_padding_advisories(candidates)


def _cache_validator_findings(workflow_ir: dict[str, Any], *, workflow_path: str | None) -> list[Diagnostic]:
    """Surface validator-shipped cache findings in analyze-cache output.

    Defensive: ``validate_data_flow`` can raise ``AttributeError`` and
    similar producer-bugs on malformed IR (e.g. batch config that's a
    string rather than a dict). For an analysis tool, the safer path is
    to log + skip surfacing rather than crash the entire ``analyze-cache``
    invocation. The malformed-IR cases will surface separately at
    ``pflow run`` validation; the analyzer's job is best-effort signal.

    The validator's diagnostic constructors (``_make_invalid_on_non_llm_diagnostic``,
    ``_make_order_mismatch_diagnostic`` in ``core/workflow/data_flow.py``) are
    workflow-agnostic — they don't know which workflow is being analyzed. We
    enrich each catalog finding with ``affected_workflow`` here so the
    renderer can scope per-row warnings correctly. ``replace`` rather than
    in-place mutation: the validator may cache diagnostic instances across
    calls, so mutating ``diag.context`` would leak the workflow tag.

    Filter is **catalog-membership**, not prefix match: the catalog historically
    held only ``cache.*`` IDs but now also carries one ``llm.*`` entry
    (``llm.thinking-temperature-mismatch``). Pinning to membership instead of
    prefix prevents future namespace additions from silently being dropped here.
    """
    from pflow.core.cache_analysis.warning_catalog import CACHE_WARNING_CATALOG

    try:
        diagnostics = validate_data_flow(workflow_ir, check_inputs=False)
    except Exception:
        logger.debug("validate_data_flow raised on malformed IR; skipping cache findings", exc_info=True)
        return []
    enriched: list[Diagnostic] = []
    for diag in diagnostics:
        if diag.id is None or diag.id not in CACHE_WARNING_CATALOG:
            continue
        existing = dict(diag.context or {})
        existing.setdefault("affected_workflow", workflow_path)
        enriched.append(replace(diag, context=existing))
    return enriched


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
    cw_result: Any,
    notes: list[str],
) -> tuple[CrossWorkflowFindings, list[Diagnostic]]:
    """Run the F1.3 walker and emit rename / prose-mismatch / value-flow diagnostics.

    Stage 0 (Task 159): returns ``(graph_info, findings)``. Diagnostics flow
    into the analyzer's single ``warnings`` list; the renderers categorize at
    output time by filtering on ``Diagnostic.id``. The graph_info field carries
    pure topology (``boundaries_analyzed``) for JSON consumers that need the
    edge count without inspecting individual findings.

    The walker appends notes to the supplied list when it stops descending
    a branch (max_depth or cycle) — the analyzer surfaces these via
    ``CacheAnalysis.notes`` so agents see truncation rather than silent
    incompleteness.
    """
    result = cw_result
    edges = result.edges

    rename_diags: list[Diagnostic] = []
    prose_mismatches: list[Diagnostic] = []
    value_flow_candidates: list[_ValueFlowCandidate] = []
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
        candidate = _value_flow_candidate(edge, result.cache_items_by_workflow, result.irs_by_workflow)
        if candidate is not None:
            value_flow_candidates.append(candidate)

    # Stage B.1 (Task 159): collapse per-edge candidates into per-(parent_workflow,
    # value_root) groups. Aggregation key is the root segment of parent_value_expr
    # so ``${concept}``, ``${concept.title}``, ``${concept.core_idea}`` all map
    # to one group keyed by ``concept`` — one ## Cache addition covers all
    # sub-paths simultaneously.
    value_flow_diagnostics = _emit_value_flow_groups(value_flow_candidates, result.irs_by_workflow, notes=notes)

    findings: list[Diagnostic] = [*rename_diags, *prose_mismatches, *value_flow_diagnostics]
    return (CrossWorkflowFindings(boundaries_analyzed=len(edges)), findings)


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


@dataclass(frozen=True)
class _ValueFlowCandidate:
    """One per-edge value-flow finding before group collapse (Stage B.1).

    Carries the data the walker produced + per-side LLM-consumer counts so
    ``_emit_value_flow_groups`` can build the destinations list and total
    consumer count without re-walking the IR.
    """

    parent_workflow: str
    parent_value_expr: str
    parent_node_id: str
    line_in_parent: int
    child_workflow: str
    child_input_name: str
    child_count: int


def _value_flow_candidate(
    edge: Any,
    cache_items_by_workflow: dict[str, tuple[dict[str, Any], ...]],
    irs_by_workflow: dict[str, dict[str, Any]],
) -> _ValueFlowCandidate | None:
    """Return a candidate for one boundary edge, or None if suppressed.

    Suppression rules (Stage B.1 preserves the per-edge contract):
    - ``parent_value_expr is None``: literal or multi-ref string at the
      boundary; no template to track.
    - Either side already declares the chunk in ## Cache: declaring is
      already in place, so the finding has no value to surface.

    The minimum-consumer threshold (``< 2``) does NOT apply per-edge anymore;
    Stage B.1 aggregates multiple destinations into one finding, so the
    threshold applies to ``total_consumer_count`` at group emission time.
    """
    if edge.parent_value_expr is None:
        return None
    parent_declared = set(_items_by_name(cache_items_by_workflow.get(edge.parent_workflow, ())))
    child_declared = set(_items_by_name(cache_items_by_workflow.get(edge.child_workflow, ())))
    if edge.parent_value_expr in parent_declared or edge.child_input_name in child_declared:
        return None

    # Per-destination child consumer count. Counts LLM nodes in the child IR
    # that reference ``${child_input_name}`` (or sub-paths). Exact match +
    # dotted-prefix per ``_count_llm_nodes_referencing_path``.
    child_count = _count_llm_nodes_referencing_path(
        irs_by_workflow.get(edge.child_workflow, {}),
        edge.child_input_name,
    )
    return _ValueFlowCandidate(
        parent_workflow=edge.parent_workflow,
        parent_value_expr=edge.parent_value_expr,
        parent_node_id=edge.parent_node_id,
        line_in_parent=edge.line_in_parent,
        child_workflow=edge.child_workflow,
        child_input_name=edge.child_input_name,
        child_count=child_count,
    )


def _build_destinations_for_group(
    group_candidates: list[_ValueFlowCandidate],
) -> list[dict[str, Any]]:
    """Collapse per-edge candidates within a group into per-destination entries.

    Filters destinations with no LLM consumer in the child (``child_count == 0``)
    — see ``_emit_value_flow_groups`` docstring "Destination filter" paragraph
    for the rationale and contract dependencies. Returns destinations sorted
    lex by ``child_workflow`` for deterministic output.

    Returns ``[]`` when every destination in the group filters out (caller
    treats that as the "fully filtered" signal for transparency notes).
    """
    by_child: dict[str, _ValueFlowCandidate] = {}
    for candidate in group_candidates:
        if candidate.child_count == 0:
            continue  # No LLM consumer in this child — no cross-boundary leverage.
        existing = by_child.get(candidate.child_workflow)
        if existing is None or candidate.parent_node_id < existing.parent_node_id:
            by_child[candidate.child_workflow] = candidate

    destinations: list[dict[str, Any]] = []
    for child_workflow in sorted(by_child.keys()):
        c = by_child[child_workflow]
        child_basename = c.child_workflow.rsplit("/", 1)[-1] if "/" in c.child_workflow else c.child_workflow
        destinations.append({
            "child_workflow": c.child_workflow,
            "child_workflow_basename": child_basename,
            "node_count": c.child_count,
            "parent_node_id": c.parent_node_id,
            "line_in_parent": c.line_in_parent,
        })
    return destinations


def _emit_value_flow_groups(
    candidates: list[_ValueFlowCandidate],
    irs_by_workflow: dict[str, dict[str, Any]],
    *,
    notes: list[str],
) -> list[Diagnostic]:
    """Group candidates by ``(parent_workflow, value_root)`` and emit one Diagnostic per group.

    Stage B.1 (Task 159): one ## Cache addition covers ${concept},
    ${concept.title}, ${concept.core_idea} simultaneously. Aggregating by
    root collapses N per-edge findings into the agent's "one resolution
    edit" model.

    Determinism (review-silent-failures W-A): destinations sorted lex by
    child_workflow; within a destination, the lex-smallest parent_node_id
    is the representative when the same child is reachable from multiple
    parent nodes.

    Threshold: total_consumer_count < 2 → group suppressed (declaring would
    share across at most one call — not worth declaring). Symmetric with
    the per-edge ``node_count < 2`` rule prior to Stage B.1.

    Destination filter (evidence-basis principle, symmetric with rename
    suppression #362): drop destinations whose child IR has zero LLM nodes
    template-referencing the value. Cross-boundary advice is only actionable
    when there's an actual cross-boundary cache opportunity — i.e., the
    child's LLM prompts contain ``${value_root}`` or a sub-path. When all
    destinations filter out, the group is suppressed entirely and ``notes``
    gets a transparency line so agents understand WHY no finding emitted
    for a value that visibly crosses the boundary.

    NOTE on the ``child_count`` signal: this filter depends on
    ``resolve_sub_workflow`` returning file-resolved child IRs (the
    boundary contract documented in ``sub_workflow_resolver.py``). Without
    that contract, file-ref prompts (``./*.prompt.md``) appear in the IR
    as path strings, ``_count_llm_nodes_referencing_path`` returns 0
    universally, and this filter would silently drop every cross-boundary
    finding on real workflows. The contract is locked by
    ``test_resolve_sub_workflow_cross_workflow_walker_sees_resolved_prompts``;
    if that test fails, the filter's signal is corrupt — fix the boundary,
    don't relax the filter.
    """
    # Group by (parent_workflow, value_root).
    groups: dict[tuple[str, str], list[_ValueFlowCandidate]] = {}
    for candidate in candidates:
        root = _template_root_segment(candidate.parent_value_expr)
        if not root:
            # Defensive: empty/None root signals an unparseable parent_value_expr.
            # Skip silently — a Diagnostic with no value_root would be useless.
            continue
        groups.setdefault((candidate.parent_workflow, root), []).append(candidate)

    diagnostics: list[Diagnostic] = []
    # Track values whose ENTIRE group filtered out — surfaced via notes for
    # transparency so agents don't wonder "why didn't analyze flag X crossing
    # the boundary?". Sorted lex on emission for deterministic output.
    fully_filtered_roots: list[str] = []
    # Iterate groups in lex order for stable output across runs.
    for (parent_workflow, root), group_candidates in sorted(groups.items()):
        destinations = _build_destinations_for_group(group_candidates)
        if not destinations:
            # All destinations filtered — record for the transparency note
            # below and skip emission. Without this trail, agents looking
            # at a workflow where a value visibly flows across boundaries
            # but no cross-boundary finding fires would have no signal
            # explaining the silence.
            fully_filtered_roots.append(root)
            continue

        # Parent count is computed against the ROOT (not parent_value_expr)
        # so all sub-paths in the group contribute. Otherwise sub-paths to
        # different children would each compute against their leaf, missing
        # nodes that reference other sub-paths of the same root.
        parent_count = _count_llm_nodes_referencing_path(irs_by_workflow.get(parent_workflow, {}), root)
        total_consumer_count = parent_count + sum(int(d["node_count"]) for d in destinations)

        # Group-level suppression mirrors the per-edge ``< 2`` rule: declaring
        # in ## Cache shares across at most one call when total < 2 — not
        # worth surfacing as a recommendation.
        if total_consumer_count < 2:
            continue

        diagnostics.append(
            make_diagnostic(
                "cache.shared-context-undeclared",
                # node_id=None → workflow-level action (renderer shows scope_workflow).
                # Old keys for ``_validate_required`` compat — semantics symmetric to
                # workflow scope (node_count = total consumers, shared_chunks = [root]).
                node_count=total_consumer_count,
                shared_chunks=[root],
                affected_workflow=parent_workflow,
                savings_usd=None,
                # New keys for boundary template + headline rendering (Stage B.1).
                value_root=root,
                destinations=destinations,
                destination_count=len(destinations),
                total_consumer_count=total_consumer_count,
                # Presence of ``child_workflow`` triggers the boundary-scope
                # template/headline dispatch in ``make_diagnostic``. Use the
                # first (lex-smallest) destination's path.
                child_workflow=destinations[0]["child_workflow"],
            )
        )

    # Transparency note: when entire groups filtered out (no LLM consumer in
    # any child), surface the count so agents who notice "X visibly crosses
    # a boundary but analyze didn't flag it" have an answer in the output
    # rather than silence. Names are lex-sorted for deterministic Notes.
    if fully_filtered_roots:
        unique_roots = sorted(set(fully_filtered_roots))
        names = ", ".join(f"`{n}`" for n in unique_roots)
        plural = "s" if len(unique_roots) != 1 else ""
        notes.append(
            f"Cross-boundary value-flow suppressed for {len(unique_roots)} value{plural} "
            f"({names}): no LLM consumer in any receiving sub-workflow. "
            f"Parent-side caching, if applicable, appears in workflow-internal "
            f"recommendations."
        )

    return diagnostics


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
    from pflow.core.trace_tree import TraceTree

    tree = TraceTree(events=tuple(events), format_version="2.1")
    for leaf in tree.iter_llm_leaves(descend_cached_subtrees=True):
        if leaf.tier == "sub_workflow_descendant":
            yield leaf.event_node_id, dict(leaf.event)
        else:
            yield leaf.owner_node_id, dict(leaf.event)


def _predict_cache_keys(
    cw_result: Any,
    ctx: AnalysisContext,
) -> tuple[dict[tuple[str | None, str], str], list[str]]:
    """Predict the runtime cache_key for every LLM node, scoped per workflow.

    Walks every workflow's IR independently (root + descendants from
    ``cw_result.irs_by_workflow``) and computes the byte-identical
    cache_key the runtime would compute via ``plan_node`` — the same
    canonical site the engine and the dry-run planner consume. This
    bypasses ``build_plan``'s BFS-downstream mode (which sets
    ``cache_key=None`` for child nodes whose parent took the downstream
    path), the source of Bug 5 in the verification report.

    ``compile_workflow`` + ``create_planner_shared`` are hoisted to the
    per-workflow loop — N LLM nodes in one workflow incur ONE compile, not
    N. ``plan_node`` is then invoked per LLM node against the shared
    compiled+shared scaffold.

    Per-node skip reasons replace the catch-all silent-skip count that the
    legacy implementation produced — agents see exactly which node's
    prediction failed and why.

    Returns ``(predicted_keys, notes)`` where ``predicted_keys`` keys
    ``(workflow_path, node_id) -> cache_key``. The contract matches the
    legacy implementation; only the production path changes.
    """
    notes: list[str] = []
    if ctx.memo_cache is None:
        notes.append(
            "Discrepancy detection: predicted-key matching unavailable (workflow has no run history). "
            "Observable-field attributions (TTL expiry, chunk skipped) still apply."
        )
        return {}, notes

    irs_by_workflow = getattr(cw_result, "irs_by_workflow", None) or {}
    if not irs_by_workflow:
        # Defensive fallback: no cross-workflow walker output. Use the root
        # IR alone (analyzer never calls _predict_cache_keys without the root).
        irs_by_workflow = {ctx.workflow_path: dict(ctx.workflow_ir)}

    predicted_keys: dict[tuple[str | None, str], str] = {}
    for workflow_path, ir in irs_by_workflow.items():
        _predict_one_workflow(
            workflow_path=workflow_path,
            ir=ir,
            ctx=ctx,
            predicted_keys=predicted_keys,
            notes=notes,
        )
    return predicted_keys, notes


def _predict_one_workflow(
    *,
    workflow_path: str | None,
    ir: Mapping[str, Any],
    ctx: AnalysisContext,
    predicted_keys: dict[tuple[str | None, str], str],
    notes: list[str],
) -> None:
    """Compute predictions for every LLM node in one workflow IR.

    Mutates ``predicted_keys`` and ``notes`` in place. Extracted from
    ``_predict_cache_keys`` to keep that function under the cyclomatic-complexity
    budget; the per-workflow body has its own classification branches
    (input-gate, no-LLM-shortcut, scaffold build, per-node loop) that
    naturally cluster together.
    """
    params = ctx.parameters_for_workflow(workflow_path)
    # Per-workflow input check: if THIS workflow declares inputs but no
    # parameters resolved for it, derived keys would diverge from the
    # trace's run-time values. Honest fallback is observable-only
    # attribution. (The legacy implementation only checked the root
    # workflow; child workflows silently degraded to defaults.)
    if not params and isinstance(ir.get("inputs"), dict) and ir["inputs"]:
        notes.append(
            f"Discrepancy detection: predicted-key matching skipped for "
            f"{workflow_path or '<root>'} — workflow declares inputs that weren't "
            "supplied or resolvable. Observable-field attributions still apply."
        )
        return
    if not any(_is_llm_node(node) for node in ir.get("nodes", [])):
        return
    scaffold, scaffold_error = _build_predict_scaffold(ir, params, ctx.memo_cache, workflow_path)
    if scaffold is None:
        if scaffold_error:
            notes.append(scaffold_error)
        return
    for node in ir.get("nodes", []):
        if not _is_llm_node(node):
            continue
        cache_key, skip_reason = _predict_node_with_scaffold(node, scaffold, workflow_path)
        if cache_key is not None:
            predicted_keys[(workflow_path, str(node["id"]))] = cache_key
        elif skip_reason:
            notes.append(skip_reason)


def _is_llm_node(node: Any) -> bool:
    """Return True for any LLM-typed IR node (regardless of ``prompt_cache:``).

    Discrepancy detection runs on every ``llm_call`` trace leaf — even nodes
    without a declared subset can have a memo ``cache_key`` to compare. The
    runtime cache_key is computed for ALL LLM nodes; restricting prediction
    to ``prompt_cache:``-declared nodes would silently miss memo divergence
    (and break tests that synthesize cache events for non-prompt_cache LLM
    nodes to exercise the consumption path).
    """
    return isinstance(node, dict) and node.get("type") == "llm"


@dataclass(frozen=True)
class _PredictScaffold:
    """Per-workflow scaffold reused across all LLM nodes in one workflow."""

    compiled: Any
    shared: dict[str, Any]
    bare_nodes_by_id: dict[str, Any]


def _build_predict_scaffold(
    workflow_ir: Mapping[str, Any],
    params: Mapping[str, Any],
    memo_cache: Any,
    workflow_path: str | None,
) -> tuple[_PredictScaffold | None, str | None]:
    """Compile + planner-shared once per workflow.

    Returns ``(scaffold, error_note)``. On failure the scaffold is None and
    ``error_note`` describes why (one note per workflow, not per node). Lazy
    imports keep the analyzer package import-cheap (mirrors
    ``token_estimation.py``'s LiteLLM lazy-import).
    """
    from pflow.core.exceptions import (
        CompilationError,
        MarkdownParseError,
        SchemaValidationError,
        WorkflowValidationError,
    )
    from pflow.execution.plan import create_planner_shared
    from pflow.registry import Registry
    from pflow.runtime import compile_workflow

    workflow_label = workflow_path or "<root>"
    try:
        compiled = compile_workflow(dict(workflow_ir), Registry(), dict(params))
    except (
        CompilationError,
        MarkdownParseError,
        SchemaValidationError,
        WorkflowValidationError,
        FileNotFoundError,
        ValueError,
    ) as exc:
        return None, (
            f"Discrepancy detection: predicted-key matching for {workflow_label} "
            f"unavailable ({type(exc).__name__}); compile failed. Observable-field "
            "attributions still apply."
        )
    shared = create_planner_shared(compiled, dict(params), memo_cache, workflow_path)
    bare_nodes_by_id = _enumerate_compiled_bare_nodes(compiled)
    return _PredictScaffold(compiled=compiled, shared=shared, bare_nodes_by_id=bare_nodes_by_id), None


def _predict_node_with_scaffold(
    node: dict[str, Any],
    scaffold: _PredictScaffold,
    workflow_path: str | None,
) -> tuple[str | None, str | None]:
    """Compute the cache_key for one node against a pre-built scaffold.

    Returns ``(cache_key, skip_reason)`` — same shape as ``_predict_node_cache_key``
    but doesn't recompile the workflow. Suitable for the per-workflow loop in
    ``_predict_cache_keys``; tests that want a self-contained per-node call
    use ``_predict_node_cache_key`` instead (it builds its own scaffold).
    """
    from pflow.runtime.engine.plan_node import plan_node

    node_id = str(node.get("id", "?"))
    workflow_label = workflow_path or "<root>"
    config = scaffold.compiled.node_configs.get(node_id)
    if config is None:
        return None, (
            f"Discrepancy detection: node {workflow_label}.{node_id} not found in "
            "compiled workflow (parser-injected metadata mismatch). Observable-field "
            "attributions still apply."
        )
    bare_node = scaffold.bare_nodes_by_id.get(node_id)
    if bare_node is None:
        return None, (
            f"Discrepancy detection: node {workflow_label}.{node_id} not reachable from "
            "start_node (graph-walk gap). Observable-field attributions still apply."
        )
    try:
        plan = plan_node(bare_node, config, scaffold.shared)
    except Exception as exc:
        logger.debug("plan_node raised for %s.%s", workflow_label, node_id, exc_info=True)
        return None, (
            f"Discrepancy detection: predicted-key matching for {workflow_label}.{node_id} "
            f"raised {type(exc).__name__}; skipping. Observable-field attributions still apply."
        )

    if plan.cache_key is not None:
        return plan.cache_key, None
    if plan.template_exception is not None:
        return None, (
            f"Discrepancy detection: predicted-key matching for {workflow_label}.{node_id} "
            "skipped — template resolution failed at analyzer-time (unresolvable upstream "
            "ref). Observable-field attributions still apply."
        )
    if plan.status == "cache_disabled":
        return None, (
            f"Discrepancy detection: predicted-key matching for {workflow_label}.{node_id} "
            "skipped — node has cache disabled. Observable-field attributions still apply."
        )
    return None, (
        f"Discrepancy detection: predicted-key matching for {workflow_label}.{node_id} "
        f"skipped — plan_node returned no cache_key (status={plan.status}). "
        "Observable-field attributions still apply."
    )


def _predict_node_cache_key(
    *,
    node: dict[str, Any],
    workflow_ir: Mapping[str, Any],
    params: Mapping[str, Any],
    memo_cache: Any,
    workflow_path: str | None,
) -> tuple[str | None, str | None]:
    """Self-contained per-node prediction — builds its own scaffold.

    Production callers should use ``_predict_cache_keys`` (which hoists the
    compile + shared per workflow). This helper is kept for direct test
    callers that want a single-node prediction without setting up a
    ``cw_result`` / ``AnalysisContext``.
    """
    scaffold, error_note = _build_predict_scaffold(workflow_ir, params, memo_cache, workflow_path)
    if scaffold is None:
        return None, error_note
    return _predict_node_with_scaffold(node, scaffold, workflow_path)


def _enumerate_compiled_bare_nodes(compiled: Any) -> dict[str, Any]:
    """BFS from ``compiled.start_node`` collecting node_id → bare-node."""
    bare_nodes_by_id: dict[str, Any] = {}
    start = getattr(compiled, "start_node", None)
    if start is None:
        return bare_nodes_by_id
    queue: list[Any] = [start]
    while queue:
        bare = queue.pop(0)
        bare_id = getattr(bare, "node_id", None)
        if not isinstance(bare_id, str) or bare_id in bare_nodes_by_id:
            continue
        bare_nodes_by_id[bare_id] = bare
        successors = getattr(bare, "successors", None) or {}
        for succ in successors.values():
            if succ is not None:
                queue.append(succ)
    return bare_nodes_by_id


def _emit_discrepancy_diagnostics(
    *,
    ctx: AnalysisContext,
    cw_result: Any,
    notes: list[str],
) -> list[Diagnostic]:
    workflow_ir = dict(ctx.workflow_ir)
    trace_data = ctx.trace_data
    if trace_data is None:
        return []
    workflow_path = ctx.workflow_path
    # Trace consumer rule (runtime/CLAUDE.md): gate on the major version.
    # Per-event guards below handle missing optional fields, so future
    # additive minor bumps are forward-compat.
    fv = str(trace_data.get("format_version", ""))
    if not fv.startswith("2."):
        return []

    predicted_keys, predict_notes = _predict_cache_keys(cw_result, ctx)
    notes.extend(predict_notes)

    diagnostics: list[Diagnostic] = []
    silent_skip_no_predicted_key = 0
    from pflow.core.trace_tree import TraceTree

    edge_child_paths = _edge_child_paths(cw_result)
    try:
        trace_tree = TraceTree.from_dict(trace_data)
    except ValueError:
        return []
    for leaf in trace_tree.iter_llm_leaves(edges=edge_child_paths, workflow_path=workflow_path):
        node_id = leaf.event_node_id if leaf.tier == "sub_workflow_descendant" else leaf.owner_node_id
        event = dict(leaf.event)
        leaf_workflow_path = leaf.workflow_path or workflow_path
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
        predicted_key = _predicted_key_for_event(predicted_keys, workflow_path=leaf_workflow_path, node_id=node_id)

        actual_pct = _safe_pct(cache_read, cache_read + cache_create)
        predicted_pct = 100 if predicted_key is not None else 0
        predicted_label = _compute_predicted_label(predicted_key, actual_key)

        if predicted_key is None and not (chunks_skipped or (cache_age_sec is not None and float(cache_age_sec) > 300)):
            # Cache engaged but we have no predicted_key AND no observable
            # signal. Per-node skip notes from ``_predict_cache_keys`` already
            # explain WHY prediction was unavailable for nodes in the analyzed
            # IR; this counter covers events whose nodes aren't in the IR
            # (typically batch sub-workflow per-item children with runtime-only
            # ``${item.X}`` context — the node identity exists only at runtime).
            silent_skip_no_predicted_key += 1
            continue
        if predicted_key is not None and abs(predicted_pct - actual_pct) < 5:
            continue

        # Bug 9 fix: TTL must come from the leaf event's workflow file —
        # mixed parent/child TTLs (parent ``ttl: 1h``, child ``ttl: 5m``)
        # would otherwise attribute child cache-age=600s as fresh against
        # the parent's hour-long window, missing the child's actual expiry.
        leaf_ir = (cw_result.irs_by_workflow.get(leaf_workflow_path) if leaf_workflow_path else None) or workflow_ir
        root_cause, summary, extra = _attribute_root_cause(
            cache_age_sec=cache_age_sec,
            chunks_skipped=chunks_skipped,
            predicted_key=predicted_key,
            actual_key=actual_key,
            ttl=_extract_cache_ttl(leaf_ir.get("cache")),
            provider=detect_provider(llm_call.get("model")),
            node_id=node_id,
            leaf_workflow_path=leaf_workflow_path or workflow_path,
            predicted_pct=predicted_pct,
            actual_pct=actual_pct,
        )
        context_extra = dict(extra)
        context_extra.setdefault("affected_workflow", leaf_workflow_path or "<root>")
        context_extra.setdefault("workflow_path_short", _workflow_short_name(leaf_workflow_path or "<root>"))
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
                **context_extra,
            )
        )
    if silent_skip_no_predicted_key > 0:
        notes.append(
            f"Discrepancy detection: skipped attribution for {silent_skip_no_predicted_key} "
            "trace event(s) with no predicted cache_key and no observable signal. "
            "Per-node skip reasons (above, when present) explain why prediction was "
            "unavailable for the affected nodes; this count covers events whose nodes "
            "were not in the analyzed IR (typically batch sub-workflow per-item children "
            "with runtime-only context)."
        )
    return _aggregate_and_cap_discrepancies(diagnostics, max_total=20, notes=notes)


def _predicted_key_for_event(
    predicted_keys: Mapping[tuple[str | None, str], str],
    *,
    workflow_path: str | None,
    node_id: str,
) -> str | None:
    """Return predicted key for a (workflow_path, node_id) pair.

    ``_predict_cache_keys`` emits tuple keys exclusively. The lookup
    here is direct — no fallback, no implicit re-keying. If the key is missing
    we have no prediction for that event.
    """
    return predicted_keys.get((workflow_path, node_id))


def _workflow_short_name(path: str) -> str:
    if "/" in path:
        path = path.rsplit("/", 1)[-1]
    if path.endswith(".pflow.md"):
        return path[: -len(".pflow.md")]
    return path


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
    leaf_workflow_path: str | None,
    predicted_pct: int,
    actual_pct: int,
) -> tuple[str, str, dict[str, Any]]:
    """Classify discrepancy root cause for one trace event.

    ``leaf_workflow_path`` is the workflow file the leaf event belongs to —
    parent for top-level events, child path for sub-workflow descendants.
    The ``affected_workflow`` field is set from this so agents see the
    workflow whose ``## Cache`` block actually needs editing, not the
    analyzed root. Renderer scope-suppression at ``view_helpers.py`` then
    composes correctly with Bug 1's per-node scope rendering.
    """
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
                {"affected_workflow": leaf_workflow_path or "<root>"},
            )
        if effective_ttl == "1h" and age >= 3600:
            return (
                "ttl_expiry",
                f"Cache entry was {age:.0f}s old (>= 1h TTL)",
                {"affected_workflow": leaf_workflow_path or "<root>"},
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


def _build_summary(
    rows: list[PerCallRow],
    warnings: list[Diagnostic],
    *,
    ttl: str | None = None,
    ctx: AnalysisContext | None = None,
    edge_child_paths: dict[str, str] | None = None,
) -> AnalysisSummary:
    """Aggregate per-call rows + warning counts into the spec's summary block.

    Atomic cost primitives (Phase 5):

    - ``compute_projections(rows, ...)`` produces three independent hypothetical
      figures — ``no_cache_hypothetical_usd``,
      ``first_run_with_cache_hypothetical_usd``,
      ``rerun_within_ttl_hypothetical_usd``. Each carries one meaning;
      the renderer chooses which to show based on context.
    - ``compute_actually_paid(rows, trace, ...)`` produces the trace-driven
      ``actually_paid_usd`` + ``actually_paid_tier`` (``UNAVAILABLE`` for
      greenfield).

    No field is overloaded — agents reading any single primitive know
    exactly what it means independent of greenfield/trace context.

    Absolute hypothetical figures still require output token data per the
    tri-state contract (``None`` on greenfield without memo, real after at
    least one run, partial when some priced rows have memo data and others
    don't). Aggregate savings figures are input-only (output cost cancels)
    and therefore work on greenfield even when absolutes stay ``None``.
    """
    # Lazy-import to avoid a circular when ``cost_estimation.py`` imports
    # ``PerCallRow`` from this module at module load time.
    from .cost_estimation import CostTier, compute_actually_paid, compute_projections

    total_calls = len(rows)
    # Phase 6 split: count root rows vs sub-workflow rows. Mirrors the
    # text renderer's previous inline ``sum(...)`` comprehensions in
    # ``_format_sub_workflow_breakdown_line`` so JSON consumers see the
    # same numbers without recomputing. ``ctx.workflow_path is None``
    # covers the inline-IR case where the analyzed workflow has no
    # resolved path — matches the existing ``or`` pattern in
    # ``render_text._format_sub_workflow_breakdown_line``.
    root_workflow_path = ctx.workflow_path if ctx is not None else None
    root_count = sum(1 for row in rows if root_workflow_path is None or row.workflow_path == root_workflow_path)
    sub_workflow_count = total_calls - root_count
    total_input = sum(r.input_tokens_estimated for r in rows)
    # ``cacheable_tokens_estimated`` may be ``None`` for greenfield rows
    # without memo (Option C — projection unmeasurable). Sum only the known
    # values; None rows contribute 0 to the aggregate (honest "we don't know"
    # rather than fabricated 0). Top-level summary still useful — agents
    # see the partial signal from steady-state / post-run rows.
    total_cacheable = sum(r.cacheable_tokens_estimated or 0 for r in rows)
    # Stage C.1: heterogeneous rows have ``model = ""`` AND
    # ``model_is_heterogeneous = True``. The ``if r.model`` truthy check below
    # already short-circuits empty strings — the explicit
    # ``not r.model_is_heterogeneous`` clause is defense-in-depth so future
    # contributors who change the empty-string convention don't silently leak
    # ``${item.model}`` literals back into the aggregate.
    models = sorted({r.model for r in rows if r.model and not r.model_is_heterogeneous})
    heterogeneous_paths = tuple(sorted(r.node_path for r in rows if r.model_is_heterogeneous))
    blocking_errors = sum(1 for d in warnings if d.severity == Severity.ERROR)
    warnings_count = sum(1 for d in warnings if d.severity == Severity.WARNING)
    info_count = sum(1 for d in warnings if d.severity == Severity.INFO)
    actionable = warnings_count + info_count

    output_tokens_by_node: Mapping[tuple[str | None, str] | str, int | None] = {
        (r.workflow_path, r.node_path): r.output_tokens_estimated for r in rows
    }
    projections = compute_projections(rows, output_tokens_by_node=output_tokens_by_node, ttl=ttl)
    actually_paid = compute_actually_paid(
        rows,
        trace=ctx.trace if ctx is not None else None,
        edges=edge_child_paths,
    )

    # Partial flag: actually-paid trace_partial OR projection partial. The
    # renderer uses one boolean to decide whether to mark numbers as
    # incomplete (which can happen on EITHER stream independently).
    partial_cost_usd = actually_paid.tier == CostTier.TRACE_PARTIAL or projections.partial

    # Savings percentage anchor: actually_paid when present (most accurate
    # baseline for "how much does caching save vs what we paid?"); else the
    # no-cache hypothetical (greenfield approximation). Top-10% rule: the
    # anchor for a percentage must be the most authoritative absolute we have.
    savings_anchor = (
        actually_paid.total_usd if actually_paid.total_usd is not None else projections.no_cache_hypothetical_usd
    )
    cohort_first_run_savings = (
        savings_anchor - projections.first_run_with_cache_hypothetical_usd
        if savings_anchor is not None and projections.first_run_with_cache_hypothetical_usd is not None
        else None
    )
    cohort_rerun_savings = (
        savings_anchor - projections.rerun_within_ttl_hypothetical_usd
        if savings_anchor is not None and projections.rerun_within_ttl_hypothetical_usd is not None
        else None
    )
    savings_pct_first_run = _safe_pct_or_none(cohort_first_run_savings, savings_anchor)
    savings_pct_rerun = _safe_pct_or_none(cohort_rerun_savings, savings_anchor)

    return AnalysisSummary(
        actually_paid_usd=actually_paid.total_usd,
        actually_paid_tier=actually_paid.tier,
        no_cache_hypothetical_usd=projections.no_cache_hypothetical_usd,
        first_run_with_cache_hypothetical_usd=projections.first_run_with_cache_hypothetical_usd,
        rerun_within_ttl_hypothetical_usd=projections.rerun_within_ttl_hypothetical_usd,
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
        partial_cost_usd=partial_cost_usd,
        unavailable_models=projections.unavailable_models,
        unavailable_models_by_workflow=_unavailable_models_by_workflow(rows),
        aggregate_savings_first_run_usd=projections.savings_first_run_usd,
        aggregate_savings_rerun_usd=projections.savings_rerun_usd,
        heterogeneous_model_node_count=len(heterogeneous_paths),
        heterogeneous_model_node_paths=heterogeneous_paths,
        root_llm_node_count=root_count,
        sub_workflow_llm_node_count=sub_workflow_count,
    )


def _unavailable_models_by_workflow(rows: list[PerCallRow]) -> dict[str | None, tuple[str, ...]]:
    """Return unpriced models grouped by workflow path for JSON/text attribution."""
    from .cost_estimation import get_model_pricing

    grouped: dict[str | None, set[str]] = {}
    for row in rows:
        if row.did_not_execute_in_trace or row.model_is_heterogeneous or not row.model:
            continue
        if get_model_pricing(row.model) is None:
            grouped.setdefault(row.workflow_path, set()).add(row.model)
    return {workflow_path: tuple(sorted(models)) for workflow_path, models in grouped.items()}


def _safe_pct_or_none(numerator: float | None, denominator: float | None) -> int | None:
    """Compute a percent only when both numerator and denominator are real."""
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(100 * numerator / denominator)


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
