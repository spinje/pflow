"""Public data model for prompt cache analysis.

This module owns the analyzer result vocabulary. Keep behavior in stage
modules and rendering modules; types here should remain lightweight and
safe to import from any analyzer consumer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from pflow.core.diagnostic import Diagnostic
from pflow.core.llm_capabilities import get_min_cache_tokens

from .below_min_tokens_detector import is_likely_below_min_cache

if TYPE_CHECKING:
    from .cost_estimation import CostTier


_PROJECTION_NOT_APPLICABLE = "not_applicable"


_PROJECTION_UNAVAILABLE = "unavailable"


_BLOCK_BELOW_PROVIDER_MIN = "below_provider_min"


_BLOCK_PREWARM_IMAGES = "prewarm_images"


_BLOCK_ABSENT_BRANCH = "absent_branch"


_BLOCK_RUNTIME_STRIPPED = "runtime_stripped"


@dataclass(frozen=True)
class CacheProjectionComponent:
    """One independently sourced cache projection component."""

    tokens_estimated: int | None
    data_source: str
    ratio_pct: int | None
    action: str = "none"
    actionability: str = _PROJECTION_NOT_APPLICABLE
    confidence: str = "exact"
    meets_provider_min: bool | None = None
    provider_min_tokens: int | None = None
    blocked_reason: str = ""
    affects_cost_projection: bool = False
    diagnostic_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CacheProjection:
    """Aggregated cache projection for one purpose.

    ``components`` are IR-derived estimates. Provider trace telemetry remains
    an aggregate per call and is exposed separately as
    ``cached_now_tokens_estimated``; do not try to decompose provider-reported
    cache reads across components because providers do not return that split.
    """

    tokens_estimated: int | None
    data_source: str
    ratio_pct: int | None
    action: str = "none"
    actionability: str = _PROJECTION_NOT_APPLICABLE
    confidence: str = "unknown"
    meets_provider_min: bool | None = None
    provider_min_tokens: int | None = None
    blocked_reason: str = ""
    affects_cost_projection: bool = False
    diagnostic_ids: tuple[str, ...] = ()
    components: tuple[CacheProjectionComponent, ...] = ()


def unavailable_projection() -> CacheProjection:
    return CacheProjection(None, _PROJECTION_UNAVAILABLE, None, action="none", confidence="unknown")


def not_applicable_projection() -> CacheProjection:
    return CacheProjection(None, _PROJECTION_NOT_APPLICABLE, None, action="none", confidence="unknown")


def component_tokens(component: CacheProjectionComponent) -> int:
    return component.tokens_estimated or 0


def _projection_component(
    *,
    tokens: int | None,
    input_tokens: int | None,
    data_source: str,
    action: str,
    actionability: str,
    confidence: str = "exact",
    meets_provider_min: bool | None = None,
    provider_min_tokens: int | None = None,
    blocked_reason: str = "",
    affects_cost_projection: bool = False,
    diagnostic_ids: tuple[str, ...] = (),
) -> CacheProjectionComponent:
    capped_tokens = _cap_projection_tokens(tokens, input_tokens)
    return CacheProjectionComponent(
        tokens_estimated=capped_tokens,
        data_source=data_source,
        ratio_pct=_safe_pct(capped_tokens, input_tokens) if capped_tokens is not None and input_tokens else None,
        action=action,
        actionability=actionability,
        confidence=confidence,
        meets_provider_min=meets_provider_min,
        provider_min_tokens=provider_min_tokens,
        blocked_reason=blocked_reason,
        affects_cost_projection=affects_cost_projection,
        diagnostic_ids=diagnostic_ids,
    )


def _cap_projection_tokens(tokens: int | None, input_tokens: int | None) -> int | None:
    if tokens is None:
        return None
    if input_tokens is None:
        return max(0, tokens)
    return min(max(0, tokens), max(0, input_tokens))


def aggregate_projection(
    components: Iterable[CacheProjectionComponent],
    *,
    purpose: str,
    input_tokens: int | None,
) -> CacheProjection:
    """Aggregate projection components by purpose.

    Configured/active components are additive. Ready/opportunity are winner
    projections unless components are known additive elsewhere; this keeps the
    row number from double-counting overlapping edit paths.
    """
    items = tuple(components)
    if not items:
        return not_applicable_projection()

    if purpose in {"configured", "active"}:
        known = [component for component in items if component.tokens_estimated is not None]
        if not known:
            return CacheProjection(
                None,
                items[0].data_source,
                None,
                action=items[0].action,
                actionability=items[0].actionability,
                confidence=_aggregate_component_confidence(items),
                meets_provider_min=items[0].meets_provider_min,
                provider_min_tokens=items[0].provider_min_tokens,
                blocked_reason=items[0].blocked_reason,
                affects_cost_projection=any(component.affects_cost_projection for component in items),
                diagnostic_ids=_merge_diagnostic_ids(items),
                components=items,
            )
        total = _cap_projection_tokens(sum(component.tokens_estimated or 0 for component in known), input_tokens)
        representative = _best_component(items)
        return CacheProjection(
            total,
            representative.data_source if len({c.data_source for c in known}) == 1 else "mixed",
            _safe_pct(total, input_tokens) if total is not None and input_tokens else None,
            action=representative.action,
            actionability=representative.actionability,
            confidence=_aggregate_component_confidence(items),
            meets_provider_min=representative.meets_provider_min,
            provider_min_tokens=representative.provider_min_tokens,
            blocked_reason=representative.blocked_reason,
            affects_cost_projection=any(component.affects_cost_projection for component in known),
            diagnostic_ids=_merge_diagnostic_ids(items),
            components=items,
        )

    winner = _best_component(items)
    return CacheProjection(
        winner.tokens_estimated,
        winner.data_source,
        winner.ratio_pct,
        action=winner.action,
        actionability=winner.actionability,
        confidence=winner.confidence,
        meets_provider_min=winner.meets_provider_min,
        provider_min_tokens=winner.provider_min_tokens,
        blocked_reason=winner.blocked_reason,
        affects_cost_projection=winner.affects_cost_projection,
        diagnostic_ids=winner.diagnostic_ids,
        components=(winner,),
    )


def _best_component(components: Iterable[CacheProjectionComponent]) -> CacheProjectionComponent:
    actionability_rank = {
        "active": 0,
        "direct_edit": 1,
        "configured_blocked": 2,
        "direct_edit_blocked": 3,
        "structural_edit": 4,
        "structural_edit_blocked": 5,
        "observed": 6,
        "blocked": 7,
        _PROJECTION_NOT_APPLICABLE: 8,
    }
    confidence_rank = {"observed": 0, "exact": 1, "lower_bound": 2, "unknown": 3}
    return sorted(
        components,
        key=lambda component: (
            -(component.tokens_estimated if component.tokens_estimated is not None else -1),
            actionability_rank.get(component.actionability, 9),
            confidence_rank.get(component.confidence, 4),
            component.data_source,
            component.action,
        ),
    )[0]


def _aggregate_component_confidence(components: Iterable[CacheProjectionComponent]) -> str:
    values = {component.confidence for component in components}
    if "unknown" in values:
        return "unknown"
    if "lower_bound" in values:
        return "lower_bound"
    if "observed" in values and len(values) == 1:
        return "observed"
    return "exact"


def _merge_diagnostic_ids(components: Iterable[CacheProjectionComponent]) -> tuple[str, ...]:
    merged: list[str] = []
    for component in components:
        for diagnostic_id in component.diagnostic_ids:
            if diagnostic_id not in merged:
                merged.append(diagnostic_id)
    return tuple(merged)


@dataclass(frozen=True)
class CrossWorkflowInputContribution:
    """One cross-workflow value contributing to a per-call row projection.

    Carries both the child-side cache ref (what the agent declares in the
    child's ``## Cache``) and the boundary input name (where that ref entered
    the child workflow). Renderers use ``child_cache_ref`` for action text and
    keep ``child_input_name`` as data-flow metadata.
    """

    child_input_name: str
    tokens_per_call: int | None
    model: str
    parent_value_expr: str | None = None
    child_cache_ref: str | None = None
    parent_cache_ref: str | None = None
    parent_prose: str | None = None

    def __post_init__(self) -> None:
        if self.child_cache_ref is None:
            object.__setattr__(self, "child_cache_ref", self.child_input_name)
        if self.parent_cache_ref is None:
            object.__setattr__(self, "parent_cache_ref", self.parent_value_expr)


@dataclass(frozen=True)
class PerCallRow:
    """One row of the per-call cache report.

    Token-field units (load-bearing contract):

    - All ``*_tokens_estimated`` fields are per-call by contract.
      ``input_tokens_estimated``, the projection ``*_tokens_estimated``
      fields, ``output_tokens_estimated``, ``chunk_tokens_estimated``, and
      the ``body_tokens_estimated`` property represent one invocation of this
      node. ``cache_creation_input_tokens`` and ``cache_read_input_tokens``
      are also per-call, sourced via ``_aggregate_trace_llm_calls``.
    - ``cost_usd`` is cohort by design: it represents actually-paid
      workflow-level cost sourced through ``ctx.cost_usd_for_node`` and
      ``TraceTree.total_cost``, not through ``_aggregate_trace_llm_calls``.
      ``compute_actually_paid`` sums this directly for the workflow total.
    - Cohort consumers (workflow totals, cost summaries) must multiply token
      fields by ``invocation_count_for(row)`` at the use site.
    - Projection fields are capped at ``input_tokens_estimated`` row-wise.
      New code must read ``cache_configured``, ``cache_active``,
      ``cache_ready``, or ``cache_opportunity``. The legacy ``cacheable_*``
      fields remain only as an internal bridge while older helper tests and
      local consumers are migrated.

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
    # Sources: ``"trace"``, ``"memo"``, ``"parameters"``,
    # ``"batch_prefix"``, ``"cross_workflow_projection"``,
    # ``"unavailable"``. ``"parameters"`` covers workflow-input refs resolved
    # via positional ``key=value`` params; ``"batch_prefix"`` covers the
    # batch-node per-call static-prefix projection (repeated bytes before the first
    # ``${alias.X}`` ref). ``"cross_workflow_projection"``
    # covers a parent-declared value flowing into a child workflow that has not
    # declared that receiving input in its own ``## Cache``. Projection tiers
    # fire when the agent has not declared ``prompt_cache:`` but a stable
    # reusable prefix is detectable. Confidence is heuristic — agents see a
    # footer flagging the projection.
    cacheable_data_source: str = "unavailable"
    # Parent-side values that contributed to a ``cross_workflow_projection``
    # row. Empty for all other tiers. Text rendering uses this to add compact
    # notes on rows whose ``could_cache`` value is a sum across multiple
    # cross-workflow inputs.
    cross_workflow_inputs: tuple[CrossWorkflowInputContribution, ...] = ()
    # Raw per-call provider cache token splits from the trace event's
    # ``llm_call`` dict. ``None`` when no trace row matched; ``int`` (including
    # 0) when trace data exists. Independent of ``cacheable_tokens_estimated``,
    # which is an analyzer projection of cacheable input bytes.
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cached_now_tokens_estimated: int | None = None
    cache_configured: CacheProjection = field(default_factory=not_applicable_projection)
    cache_active: CacheProjection = field(default_factory=not_applicable_projection)
    cache_ready: CacheProjection = field(default_factory=not_applicable_projection)
    cache_opportunity: CacheProjection = field(default_factory=not_applicable_projection)
    # Track A (Phase A): cohort recorded cost from the trace (sum of
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
    # Concrete model set observed in trace LLM calls for this static row.
    # Dynamic batches can execute many item-level calls under one node id; the
    # row stays node-scoped while these fields preserve exact-model truth.
    observed_models: tuple[str, ...] = ()
    observed_call_count: int = 0
    # Current-run provider calls for this row, excluding pflow memo/in-process
    # replays. Trace-only mixed-size detectors must read this instead of
    # historical cached-event payloads.
    provider_trace_llm_calls: tuple[dict[str, Any], ...] = ()
    # Resolved declared ``## Cache`` chunk content included in
    # ``input_tokens_estimated``. Consumers that need prompt-body-only costs
    # derive them from the total instead of maintaining a second total.
    chunk_tokens_estimated: int = 0
    # Stage 0.3 (Task 159): the inline ``warnings: tuple[str, ...]`` field was
    # vestigial — single production producer never populated it; renderer
    # fallbacks in ``rendering/text.py`` and the JSON ``per_call.warnings``
    # key were dead. Per-row inline warning markers are derived at render time
    # from ``analysis.warnings`` filtered by node_id (see
    # ``rendering.text._render_per_call``).

    def __post_init__(self) -> None:
        """Bridge legacy direct test constructors to explicit projections.

        Production row construction populates the projection fields directly.
        A large helper-test surface still instantiates ``PerCallRow`` with the
        old cacheable scalar; synthesize active/ready/opportunity projections
        only when callers left the new fields at their defaults.
        """
        if self.cached_now_tokens_estimated is None and (
            self.cache_creation_input_tokens is not None or self.cache_read_input_tokens is not None
        ):
            object.__setattr__(
                self,
                "cached_now_tokens_estimated",
                int(self.cache_creation_input_tokens or 0) + int(self.cache_read_input_tokens or 0),
            )
        projection_already_specific = self.cache_ready.data_source not in {
            _PROJECTION_NOT_APPLICABLE,
            _PROJECTION_UNAVAILABLE,
        } or self.cache_active.data_source not in {_PROJECTION_NOT_APPLICABLE, _PROJECTION_UNAVAILABLE}
        if self.cacheable_tokens_estimated is None or projection_already_specific:
            if (
                self.cacheable_data_source == "trace"
                and self.declared_prompt_cache
                and self.cached_now_tokens_estimated is None
            ):
                object.__setattr__(self, "cached_now_tokens_estimated", self.cacheable_tokens_estimated)
            return
        if not self.declared_prompt_cache and (
            self.cacheable_tokens_estimated <= 0 or self.cacheable_data_source == "trace"
        ):
            return
        source = "declared_chunks" if self.declared_prompt_cache else self.cacheable_data_source
        action = "none" if self.declared_prompt_cache else "declare_prompt_cache"
        if source == "batch_prefix":
            action = "add_prewarm"
        elif source == "cross_workflow_projection":
            action = "declare_child_cache"
        actionability = "active" if self.declared_prompt_cache else "direct_edit"
        meets_min, provider_min, blocked = _provider_min_state(self.model, self.cacheable_tokens_estimated)
        if self.cacheable_data_source == "trace" and self.declared_prompt_cache:
            meets_min = True
            blocked = ""
        component = _projection_component(
            tokens=self.cacheable_tokens_estimated,
            input_tokens=self.input_tokens_estimated,
            data_source=source,
            action=action,
            actionability=(actionability if self.declared_prompt_cache or not blocked else "direct_edit_blocked"),
            confidence=_projection_source_confidence(self.cacheable_data_source),
            meets_provider_min=meets_min,
            provider_min_tokens=provider_min,
            blocked_reason=blocked,
            affects_cost_projection=bool(self.declared_prompt_cache),
        )
        if (
            self.cacheable_data_source == "trace"
            and self.declared_prompt_cache
            and self.cached_now_tokens_estimated is None
        ):
            object.__setattr__(self, "cached_now_tokens_estimated", self.cacheable_tokens_estimated)
        object.__setattr__(
            self,
            "cache_ready",
            aggregate_projection((component,), purpose="ready", input_tokens=self.input_tokens_estimated),
        )
        if self.declared_prompt_cache:
            object.__setattr__(
                self,
                "cache_configured",
                aggregate_projection((component,), purpose="configured", input_tokens=self.input_tokens_estimated),
            )
            object.__setattr__(
                self,
                "cache_active",
                aggregate_projection((component,), purpose="active", input_tokens=self.input_tokens_estimated),
            )
        else:
            object.__setattr__(
                self,
                "cache_opportunity",
                aggregate_projection((component,), purpose="opportunity", input_tokens=self.input_tokens_estimated),
            )

    @property
    def body_tokens_estimated(self) -> int:
        """Resolved prompt-body tokens, excluding declared cache chunk content."""
        return self.input_tokens_estimated - self.chunk_tokens_estimated


@dataclass(frozen=True)
class ProjectionExclusion:
    """One row deliberately excluded from absolute cost projections."""

    workflow_path: str | None
    node_path: str
    reason: str
    actual_cost_usd: float | None = None


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
    suggestions: tuple[str, ...] = ()
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SuggestedBlockChunk:
    name: str
    var: str
    size_tokens_est: int
    prose_placeholder: str


class PerNodeThresholdEntry(TypedDict):
    """Per-node threshold check for a SuggestedBlock recommendation.

    ``model_state`` discriminator added per Task 159 PR #378 review (#4):
    JSON consumers should dispatch on the typed field, not magic strings.
    Value semantics:

    - ``"resolved"``  — node has a concrete model; ``model`` carries the
      provider-prefixed identifier (e.g. ``"anthropic/claude-sonnet-4-5"``).
    - ``"heterogeneous"`` — IR ``params.model`` was an unresolved ``${...}``
      template (model varies per batch item); ``model`` is ``None``.
    - ``"unknown"`` — model could not be resolved (no row, empty model
      field, etc.); ``model`` is ``None``. ``min_tokens``/``total_tokens``/
      ``meets_threshold`` all ``None``.

    Text rendering still surfaces human-readable labels (``<varies>``,
    ``<unknown>``) — the sentinel-string-in-JSON anti-pattern is closed.
    """

    model: str | None
    model_state: str
    min_tokens: int | None
    total_tokens: int | None
    meets_threshold: bool | None


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
    per_node_thresholds: dict[str, PerNodeThresholdEntry] = field(default_factory=dict)


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
    llm_call_lists_by_key: dict[tuple[str | None, str], tuple[dict[str, Any], ...]]
    provider_llm_calls_by_key: dict[tuple[str | None, str], dict[str, Any]]
    provider_llm_call_lists_by_key: dict[tuple[str | None, str], tuple[dict[str, Any], ...]]
    outputs_by_key: dict[tuple[str | None, str], Any]
    executed_keys: set[tuple[str | None, str]]
    workflows_with_trace: set[str | None]
    current_cost_by_workflow: dict[str | None, float | None]
    provider_llm_call_count: int = 0
    local_memo_llm_hit_count: int = 0
    local_in_process_llm_hit_count: int = 0
    local_cache_input_tokens: int = 0
    provider_cache_creation_input_tokens: int = 0
    provider_cache_read_input_tokens: int = 0
    trace_loaded: bool = False


@dataclass(frozen=True)
class CostDelta:
    """Comparable delta between two cost atoms.

    ``amount_usd`` is a non-negative magnitude. Direction lives in ``kind`` so
    renderers cannot accidentally describe a write premium as negative savings.

    ``excluded_nodes`` carries the node paths whose cost was subtracted from
    the cohort before computing this delta — populated when the comparison
    is honest only on a subset of rows (e.g. heterogeneous batches whose
    per-item models can't be priced as one). Empty for whole-cohort deltas.
    """

    amount_usd: float | None
    pct_of_baseline: int | None
    kind: str
    baseline: str
    compared_to: str
    unavailable_reason: str | None = None
    excluded_nodes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TraceUnexecutedLLMRow:
    """Scoped identity for a static LLM row absent from a loaded trace."""

    workflow_path: str | None
    node_path: str


@dataclass(frozen=True)
class TraceListEntry:
    """One trace row for ``pflow analyze-cache --list-traces``."""

    path: Path
    final_status: str
    recorded_at: str | None
    duration_ms: float | None
    llm_call_count: int
    total_cost_usd: float | None
    models_used: tuple[str, ...]
    would_be_autoloaded: bool
    model_drift_count: int | None


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
    - ``*_delta`` — explicit comparisons between comparable cost atoms.
      ``kind`` distinguishes savings from cost increases and unavailable
      comparisons.
    """

    actually_paid_usd: float | None
    actually_paid_tier: CostTier
    no_cache_hypothetical_usd: float | None
    first_run_with_cache_hypothetical_usd: float | None
    rerun_within_ttl_hypothetical_usd: float | None
    first_run_delta: CostDelta
    rerun_delta: CostDelta
    actual_vs_no_cache_delta: CostDelta
    trace_coverage: str
    trace_llm_nodes_static: int
    trace_llm_nodes_executed: int
    trace_unexecuted_llm_rows: tuple[TraceUnexecutedLLMRow, ...]
    blocking_errors: int
    actionable_opportunities: int
    warnings_count: int
    info_count: int
    total_llm_nodes_estimated: int
    total_llm_invocations_estimated: int | None
    dynamic_batch_node_count: int
    total_input_tokens_estimated: int
    total_cacheable_tokens_estimated: int
    models_in_use: tuple[str, ...]
    partial_cost_usd: bool
    unavailable_models: tuple[str, ...]
    total_cache_active_tokens_estimated: int = 0
    total_cache_ready_tokens_estimated: int = 0
    total_cache_opportunity_tokens_estimated: int = 0
    total_cache_ready_confidence: str = "unknown"
    total_cache_opportunity_confidence: str = "unknown"
    unknown_cache_ready_row_count: int = 0
    unknown_cache_opportunity_row_count: int = 0
    lower_bound_cache_ready_row_count: int = 0
    lower_bound_cache_opportunity_row_count: int = 0
    unavailable_models_by_workflow: dict[str | None, tuple[str, ...]] | None = None
    evidence_scope: str = "static_analysis"
    observed_models_in_trace: tuple[str, ...] = ()
    # IR-resolved default model captured once per analysis run. Renderers use
    # it to disclose when trace evidence shows a different model actually ran.
    ir_default_model: str | None = None
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
    # ``root_llm_node_count`` == ``total_llm_nodes_estimated`` for
    # single-workflow analyses; ``sub_workflow_llm_node_count`` == 0 in
    # that case.
    root_llm_node_count: int = 0
    sub_workflow_llm_node_count: int = 0
    sub_workflow_rollup: SubWorkflowRollup | None = None
    projection_exclusions: tuple[ProjectionExclusion, ...] = ()
    # Paste-ready ``pflow run`` command derived from ``workflow_path`` and
    # the workflow's declared inputs. Populated when the workflow has a
    # resolvable file path (``None`` for inline IR or ``ir-hash:`` lookup
    # keys). Renderers use it on unavailable-cost branches so agents see
    # the exact command that lights up cost figures.
    suggested_run_command: str | None = None
    # Trace transparency (Bug 1 + Bug 10 follow-ups): when a trace was loaded
    # (autoload or ``--from-trace``), surface its final outcome + recording
    # timestamp so the agent can see at a glance which run produced the
    # evidence being used. ``trace_final_status`` mirrors
    # ``trace["final_status"]`` with the same back-compat fallback as
    # ``_trace_coverage_for_rows`` (absent → ``"success"``); ``trace_recorded_at``
    # is the ISO ``start_time`` from the trace JSON. Both ``None`` when no
    # trace is loaded.
    trace_final_status: str | None = None
    trace_workflow_relationship: str | None = None
    trace_model_drift_count: int = 0
    trace_recorded_at: str | None = None
    # Trace cache-layer split. Provider prompt caching and pflow's local memo
    # cache are independent layers; a resumed run can skip LLM calls before the
    # provider ever sees them. These fields keep that visible in text/JSON so
    # agents do not mistake memo reuse for provider prompt-cache savings.
    trace_provider_llm_call_count: int = 0
    trace_local_memo_llm_hit_count: int = 0
    trace_local_in_process_llm_hit_count: int = 0
    trace_local_cache_input_tokens: int = 0
    trace_provider_cache_creation_input_tokens: int = 0
    trace_provider_cache_read_input_tokens: int = 0
    stale_memo_skipped_count: int = 0
    stale_memo_uncheckable_count: int = 0


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


def _safe_pct(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round(100 * numerator / denominator)


def _provider_min_state(model: str, tokens: int | None) -> tuple[bool | None, int | None, str]:
    if tokens is None:
        return None, get_min_cache_tokens(model) if model else None, ""
    min_tokens = get_min_cache_tokens(model)
    below_min = is_likely_below_min_cache(model, tokens)
    return (not below_min, min_tokens, _BLOCK_BELOW_PROVIDER_MIN if below_min else "")


def _projection_source_confidence(source: str) -> str:
    if source == "trace":
        return "observed"
    if source in {"batch_prefix_lower_bound", "dynamic_before_static_lower_bound"}:
        return "lower_bound"
    if source == "unavailable":
        return "unknown"
    return "exact"


def invocation_count_for(row: PerCallRow) -> int:
    """Return the number of LLM calls represented by a per-call row.

    Batch rows use ``batch_size_estimated`` when available, then observed trace
    count, then 1. Non-batch rows that executed multiple times (for example a
    sub-workflow LLM under a parent batch) use ``observed_call_count``. This is
    the single per-call-to-cohort multiplier for ``PerCallRow`` token fields.
    """
    if row.is_batch:
        if row.batch_size_estimated is not None:
            return max(1, row.batch_size_estimated)
        return max(1, row.observed_call_count or 1)
    if row.observed_call_count > 1:
        return row.observed_call_count
    return 1
