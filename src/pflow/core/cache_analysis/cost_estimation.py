"""Cost estimation for ``pflow analyze-cache`` summary fields.

Two independent cost streams (Phase 4 split):

- :func:`compute_projections` — IR-driven hypothetical cost projections.
  Pure ``tokens × rate`` math; never reads ``row.cost_usd``. The renderer
  shows these as "what would this cost?" projections regardless of trace
  presence.
- :func:`compute_actually_paid` — Trace-driven recorded cost. Prefers
  ``TraceTree.total_cost`` when a trace is provided (canonical sum,
  includes sub-workflow descendants); falls back to summing ``row.cost_usd``
  for callers that pass rows without a trace handle.

The previous ``compute_aggregate_costs`` mixed actual-paid (``row.cost_usd``)
with projections under one ``current_usd`` field. ``_build_summary`` then
overrode ``current_usd`` with ``tree.total_cost()`` when a trace existed —
the compute-and-override pattern. The split removes that pattern: each
function does one job, and ``_build_summary`` composes them directly.

**Tri-state contract** (mirrors ``llm_client.py``'s runtime tri-state):

- ``priced``       — both input and output token counts known + model is in
                     ``litellm.model_cost``. Real numbers.
- ``partial``      — at least one priced call AND at least one call with
                     unavailable output tokens or unpriced model. Aggregate
                     sums what it can; renderer surfaces ``(partial)``.
- ``unavailable``  — no call had enough data to compute. Aggregate fields
                     stay ``None``; renderer says ``unavailable``.

**Why output tokens dominate** (load-bearing — see Task 159 progress log
Segment 4 follow-up). Anthropic Sonnet output rate is 5x input rate; on
output-heavy workflows (lyrics generation, code synthesis, structured
output), output cost is 60-85% of total. Skipping output tokens makes the
absolute cost figures wrong by 5-10x.

**Why caching savings are input-only** (the load-bearing insight that
makes greenfield cost analysis useful). ``no_cache - first_run_with_cache``
collapses to input-side terms because output cost cancels — caching does
not affect output. Aggregate savings figures therefore work on greenfield
workflows even when output token data is unavailable.

**1h-TTL multiplier** (Anthropic-only). LiteLLM's
``cache_creation_input_token_cost`` is the 5-min rate (1.25x base);
1h-TTL writes cost 2x base. Mirrors the runtime override at
``llm_client.py::_maybe_normalize_anthropic_1h_cost`` so predicted and
actual costs use the same rate.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from pflow.core.cache_ttl import parse_cache_ttl
from pflow.core.llm_providers import detect_provider, model_name_without_provider

from .analyze import PerCallRow, ProjectionExclusion, invocation_count_for

if TYPE_CHECKING:
    from pflow.core.trace_tree import TraceTree

logger = logging.getLogger(__name__)


# Anthropic 1h-TTL cache write multiplier (vs base input rate). Mirrors
# ``llm_client.py:1047`` — keep the two sites in lockstep so predicted and
# actual costs price the same byte at the same rate.
_ANTHROPIC_1H_WRITE_MULTIPLIER: float = 2.0


class CostTier(str, Enum):
    """Confidence tier for a cost figure.

    JSON serialization preserves the string value — consumers
    matching ``"trace"`` keep working. mypy type-checks assignments at
    production sites; agents reading the source see a closed catalog.
    """

    TRACE = "trace"
    TRACE_PARTIAL = "trace_partial"
    RECOMPUTED = "recomputed"
    UNAVAILABLE = "unavailable"

    def __str__(self) -> str:
        """Match ``StrEnum`` stringification while supporting Python 3.10."""
        return self.value


@dataclass(frozen=True)
class ModelPricing:
    """Per-token rates for one model.

    All rates are in USD per token (e.g. ``3e-6`` for $3/M tokens).
    """

    input_rate: float
    output_rate: float
    cache_creation_rate: float  # 5-min default per LiteLLM's table.
    cache_read_rate: float


@dataclass(frozen=True)
class ProjectionBreakdown:
    """IR-driven hypothetical cost projections. Never reads ``row.cost_usd``.

    Heterogeneous-batch rows (``model_is_heterogeneous=True``), unresolved
    models, unpriced models, missing output-token rows, and rows marked
    ``did_not_execute_in_trace=True`` are excluded from at least some absolute
    projection atoms. Exclusions are explicit so summary deltas can avoid
    comparing actual trace cost against a different projection cohort.

    Per the tri-state contract: absolute fields are ``None`` on full
    unavailability; populated with partial sums when ``partial`` is True.
    Savings fields work even on greenfield (output cost cancels).

    Each field carries one meaning. The renderer composes context-aware
    presentation by selecting which fields to display:

    - ``no_cache_hypothetical_usd`` — pure no-cache recompute over ALL
      priced rows: ``input × full_rate + output × output_rate`` per row.
      The "what would this cost without any caching?" baseline. Always
      shown when present.
    - ``first_run_with_cache_hypothetical_usd`` — first-run cost when
      declared caching is honored: undeclared rows use no-cache math;
      declared rows pay write rate on cacheable + input rate on
      non-cacheable + output rate on output. Equals
      ``no_cache_hypothetical_usd`` exactly when no row declares
      ``prompt_cache:`` (the renderer hides the redundant line in that
      case).
    - ``rerun_within_ttl_hypothetical_usd`` — all-cacheable-at-read-rate
      projection (every call after the first, within TTL).
    - ``savings_*`` — input-only deltas; greenfield-safe.
    """

    no_cache_hypothetical_usd: float | None
    first_run_with_cache_hypothetical_usd: float | None
    rerun_within_ttl_hypothetical_usd: float | None
    savings_first_run_usd: float | None
    savings_rerun_usd: float | None
    partial: bool
    unavailable_models: tuple[str, ...]
    absolute_exclusions: tuple[ProjectionExclusion, ...] = ()


@dataclass(frozen=True)
class ActuallyPaidCost:
    """Trace-driven recorded cost. Independent from projections.

    ``total_usd``:

    - ``None`` when no trace data is available (greenfield, or trace exists
      but recorded zero LLM events).
    - ``float`` when a trace contributed at least one priced leaf. Cached
      events contribute 0.0 explicitly (this run paid 0 for that leaf).

    ``tier`` (``CostTier``):

    - ``TRACE`` — every leaf was priced.
    - ``TRACE_PARTIAL`` — at least one leaf had ``cost_usd=None`` (unpriced
      model in trace); the float sums the priced subset.
    - ``UNAVAILABLE`` — no leaf carried cost data.
    """

    total_usd: float | None
    tier: CostTier


# ---------------------------------------------------------------------------
# Pricing lookup
# ---------------------------------------------------------------------------


def get_model_pricing(model: str) -> ModelPricing | None:
    """Return ``ModelPricing`` for the given model, or ``None`` if unpriced.

    Tries the prefixed model name first, then the bare name (without provider
    prefix). Mirrors ``llm_client.py::_maybe_normalize_anthropic_1h_cost``'s
    bare-name fallback — LiteLLM's ``model_cost`` keys are inconsistent across
    providers.
    """
    if not model:
        return None
    try:
        from pflow.core.litellm_runtime import import_litellm

        litellm = import_litellm()
    except ImportError:
        logger.debug("litellm import failed during pricing lookup", exc_info=True)
        return None

    model_cost = getattr(litellm, "model_cost", None)
    if not isinstance(model_cost, dict):
        return None

    pricing_dict = model_cost.get(model)
    if pricing_dict is None:
        provider = detect_provider(model)
        if provider is not None:
            bare = model_name_without_provider(model, provider)
            pricing_dict = model_cost.get(bare)
    if not isinstance(pricing_dict, dict):
        return None

    return _pricing_from_dict(pricing_dict)


def _pricing_from_dict(d: dict) -> ModelPricing | None:
    """Construct a ``ModelPricing`` from one ``litellm.model_cost`` entry.

    Returns ``None`` if the entry lacks the minimum (input + output) rates.
    Cache rates fall back to derived defaults (1.25x base / 0.1x base) when
    the entry doesn't carry them — matches the documented Anthropic ratios
    so workflows targeting models with sparse pricing data still get a
    plausible estimate rather than ``None``.
    """
    input_rate = d.get("input_cost_per_token")
    output_rate = d.get("output_cost_per_token")
    if not isinstance(input_rate, (int, float)) or not isinstance(output_rate, (int, float)):
        return None

    creation_rate = d.get("cache_creation_input_token_cost")
    if not isinstance(creation_rate, (int, float)):
        creation_rate = float(input_rate) * 1.25

    read_rate = d.get("cache_read_input_token_cost")
    if not isinstance(read_rate, (int, float)):
        read_rate = float(input_rate) * 0.1

    return ModelPricing(
        input_rate=float(input_rate),
        output_rate=float(output_rate),
        cache_creation_rate=float(creation_rate),
        cache_read_rate=float(read_rate),
    )


# ---------------------------------------------------------------------------
# Per-call projection helpers
# ---------------------------------------------------------------------------


def _write_rate_for_ttl(pricing: ModelPricing, ttl: str | None, model: str) -> float:
    """Apply the 1h-TTL Anthropic multiplier to the write rate.

    For Anthropic 1h-TTL (per Spike 3 / DD#37), writes cost 2x base instead
    of LiteLLM's 1.25x default. For all other providers / TTLs, return the
    LiteLLM-reported ``cache_creation_rate`` unchanged.
    """
    if parse_cache_ttl(ttl).seconds != 3600:
        return pricing.cache_creation_rate
    provider = detect_provider(model)
    if provider is not None and provider.name == "anthropic":
        return pricing.input_rate * _ANTHROPIC_1H_WRITE_MULTIPLIER
    return pricing.cache_creation_rate


def _row_no_cache_cost(row: PerCallRow, pricing: ModelPricing, output_tokens: int) -> float:
    """Recompute the row cohort cost without provider prompt caching.

    Multiplies the row's per-call token fields by ``invocation_count_for(row)``.
    Never reads ``row.cost_usd``.
    """
    invocations = invocation_count_for(row)
    return float(invocations) * (row.input_tokens_estimated * pricing.input_rate + output_tokens * pricing.output_rate)


def _row_body_only_cost(row: PerCallRow, pricing: ModelPricing, output_tokens: int) -> float:
    """Row cohort cost if ``## Cache`` declarations were removed from this node.

    The model receives only the resolved prompt body; declared chunks disappear
    instead of being inlined uncached. This is the body-only baseline used for
    ``cache.prompt-body-shadows-cache`` disclosure.
    """
    invocations = invocation_count_for(row)
    return float(invocations) * (row.body_tokens_estimated * pricing.input_rate + output_tokens * pricing.output_rate)


def _row_first_run_with_cache_cost(
    row: PerCallRow,
    pricing: ModelPricing,
    output_tokens: int,
    *,
    ttl: str | None,
) -> float:
    """Row cohort cost with declared cache on the first workflow run.

    Mirrors ``_aggregate_with_cache_projection`` for a one-row cohort: one
    cache write, then cache reads for additional static-batch invocations.
    """
    invocations = invocation_count_for(row)
    cacheable = row.cache_active.tokens_estimated or 0
    non_cacheable = max(0, row.input_tokens_estimated - cacheable)
    write_rate = _write_rate_for_ttl(pricing, ttl, row.model)
    total = 0.0
    for index in range(invocations):
        rate = write_rate if index == 0 else pricing.cache_read_rate
        total += cacheable * rate + non_cacheable * pricing.input_rate + output_tokens * pricing.output_rate
    return total


def _row_rerun_cost(row: PerCallRow, pricing: ModelPricing, output_tokens: int | None) -> float | None:
    """Row cohort cost with all cacheable tokens at read rate.

    Equivalent to: every call after the first, within TTL.

    Only ``cache_active`` earns the read-rate. Ready/opportunity projections
    never reduce headline cost projections.
    """
    if output_tokens is None:
        return None
    invocations = invocation_count_for(row)
    cacheable = row.cache_active.tokens_estimated or 0
    non_cacheable = max(0, row.input_tokens_estimated - cacheable)
    per_call_input = cacheable * pricing.cache_read_rate + non_cacheable * pricing.input_rate
    return float(invocations) * (per_call_input + output_tokens * pricing.output_rate)


# ---------------------------------------------------------------------------
# Projection aggregation (IR-driven)
# ---------------------------------------------------------------------------


def compute_projections(
    rows: list[PerCallRow],
    *,
    output_tokens_by_node: Mapping[tuple[str | None, str] | str, int | None],
    ttl: str | None = None,
) -> ProjectionBreakdown:
    """IR-driven projection math. No trace reads.

    Excludes heterogeneous-batch rows and ``did_not_execute_in_trace`` rows.
    Rows whose model lacks pricing in ``litellm.model_cost`` are tracked in
    ``unavailable_models`` and excluded from priced sums.

    Args:
        rows: All LLM-node per-call rows from the analyzer.
        output_tokens_by_node: Map ``(workflow_path, node_path) -> output_tokens | None``
            (or bare ``node_path -> output_tokens | None`` for legacy callers)
            from ``estimate_output_tokens``. ``None`` for nodes lacking
            memo/trace data (greenfield).
        ttl: pflow TTL syntax from ``workflow_ir["cache"]["ttl"]``, or
            ``None`` for pflow's default ``5m``.

    Math (per row):

    - ``no_cache_hypothetical``: ``input × input_rate + output × output_rate`` (over all priced rows).
    - ``rerun_within_ttl``: ``cacheable × read_rate + non_cacheable × input_rate + output × output_rate``.
    - ``first_run_with_cache``: undeclared rows use ``no_cache``; declared rows
      use the with-cache first-run projection so savings remains comparable.

    Savings (``no_cache - first_run_with_cache`` and ``no_cache - rerun_within_ttl``)
    are input-only by construction (output cancels), so they're always computable
    when pricing is available — even on greenfield (no output tokens needed).
    """
    priced_rows, unavailable_models, exclusions = _partition_priced_rows(rows, output_tokens_by_node)

    rows_with_output: list[tuple[PerCallRow, ModelPricing, int]] = [
        (r, p, o) for r, p, o in priced_rows if o is not None
    ]
    rows_without_output = [(r, p, o) for r, p, o in priced_rows if o is None]
    output_exclusions = tuple(
        ProjectionExclusion(
            workflow_path=row.workflow_path,
            node_path=row.node_path,
            reason="missing_output_tokens",
            actual_cost_usd=row.cost_usd,
        )
        for row, _pricing, _output in rows_without_output
    )
    absolute_exclusions = (*exclusions, *output_exclusions)
    partial = bool(rows_with_output) and (
        bool(rows_without_output) or bool(unavailable_models) or bool(absolute_exclusions)
    )

    no_cache_hypothetical_usd: float | None = None
    first_run_with_cache_hypothetical_usd: float | None = None
    rerun_within_ttl_hypothetical_usd: float | None = None

    if rows_with_output:
        no_cache_hypothetical_usd = sum(
            _row_no_cache_cost(row, pricing, output) for row, pricing, output in rows_with_output
        )
        rerun_within_ttl_hypothetical_usd = sum(_row_rerun_cost(r, p, o) or 0.0 for r, p, o in rows_with_output)
        no_cache_inactive = _aggregate_no_cache_cost(
            [r for r in rows_with_output if not r[0].cache_active.affects_cost_projection], ttl
        )
        with_cache_active = _aggregate_with_cache_projection(
            [r for r in rows_with_output if r[0].cache_active.affects_cost_projection], ttl
        )
        first_run_with_cache_hypothetical_usd = (
            (no_cache_inactive or 0.0) + (with_cache_active or 0.0)
            if no_cache_inactive is not None or with_cache_active is not None
            else None
        )

    savings_first_run_usd = _aggregate_first_run_savings(priced_rows, ttl) if priced_rows else None
    savings_rerun_usd = _aggregate_rerun_savings(priced_rows) if priced_rows else None

    return ProjectionBreakdown(
        no_cache_hypothetical_usd=no_cache_hypothetical_usd,
        first_run_with_cache_hypothetical_usd=first_run_with_cache_hypothetical_usd,
        rerun_within_ttl_hypothetical_usd=rerun_within_ttl_hypothetical_usd,
        savings_first_run_usd=savings_first_run_usd,
        savings_rerun_usd=savings_rerun_usd,
        partial=partial,
        unavailable_models=tuple(unavailable_models),
        absolute_exclusions=absolute_exclusions,
    )


def _partition_priced_rows(
    rows: list[PerCallRow],
    output_tokens_by_node: Mapping[tuple[str | None, str] | str, int | None],
) -> tuple[list[tuple[PerCallRow, ModelPricing, int | None]], list[str], tuple[ProjectionExclusion, ...]]:
    """Split ``rows`` into priceable + unavailable-model list.

    Excluded from priced rows:

    - ``did_not_execute_in_trace=True`` — phantom rows reachable in IR but
      absent from a workflow that has trace data. Including them would
      inflate projections with fictional cost.
    - ``model_is_heterogeneous=True`` — heterogeneous batch sub-workflows
      (``model: ${item.X}``) carry per-item models we can't price as one
      model. Their actually-paid cost surfaces via :func:`compute_actually_paid`
      (trace-driven, includes sub-workflow descendants).
    - Rows with no resolved model — tracked as a projection exclusion.
    - Rows whose model isn't in ``litellm.model_cost`` — tracked in the
      returned ``unavailable_models`` list, deduped, in declaration order.
    """
    priced_rows: list[tuple[PerCallRow, ModelPricing, int | None]] = []
    unavailable_models: list[str] = []
    exclusions: list[ProjectionExclusion] = []
    seen_unavailable: set[str] = set()

    for row in rows:
        if row.did_not_execute_in_trace:
            continue
        if row.model_is_heterogeneous:
            exclusions.append(
                ProjectionExclusion(
                    workflow_path=row.workflow_path,
                    node_path=row.node_path,
                    reason="heterogeneous_model",
                    actual_cost_usd=row.cost_usd,
                )
            )
            continue
        if not row.model:
            exclusions.append(
                ProjectionExclusion(
                    workflow_path=row.workflow_path,
                    node_path=row.node_path,
                    reason="unresolved_model",
                    actual_cost_usd=row.cost_usd,
                )
            )
            continue
        pricing = get_model_pricing(row.model)
        if pricing is None:
            if row.model and row.model not in seen_unavailable:
                unavailable_models.append(row.model)
                seen_unavailable.add(row.model)
            exclusions.append(
                ProjectionExclusion(
                    workflow_path=row.workflow_path,
                    node_path=row.node_path,
                    reason="unpriced_model",
                    actual_cost_usd=row.cost_usd,
                )
            )
            continue
        output_tokens = output_tokens_by_node.get((row.workflow_path, row.node_path))
        if output_tokens is None and row.node_path in output_tokens_by_node:
            output_tokens = output_tokens_by_node.get(row.node_path)
        priced_rows.append((row, pricing, output_tokens))

    return priced_rows, unavailable_models, tuple(exclusions)


def _aggregate_no_cache_cost(
    priced_rows: Sequence[tuple[PerCallRow, ModelPricing, int]],
    ttl: str | None,
) -> float | None:
    """Compute no-cache cost for rows with no declared subset."""
    del ttl
    if not priced_rows:
        return None
    return sum(_row_no_cache_cost(row, pricing, output) for row, pricing, output in priced_rows)


def _aggregate_with_cache_projection(
    priced_rows: Sequence[tuple[PerCallRow, ModelPricing, int]],
    ttl: str | None,
) -> float | None:
    """Compute first-run cost for rows with declared prompt-cache subsets."""
    if not priced_rows:
        return None
    # Cohort key includes ``row.model`` because provider caches are model-keyed:
    # two rows on different models with identical ``prompt_cache:`` are independent
    # cache namespaces and BOTH pay the first-call write. Without ``row.model`` the
    # second model would silently get ``cache_read_rate`` and over-count savings —
    # the exact scenario ``cache.heterogeneous-models-fragment-cache`` warns about.
    by_subset: dict[tuple[str | None, str, tuple[str, ...], str], list[tuple[PerCallRow, ModelPricing, int]]] = {}
    for row, pricing, output_tokens in priced_rows:
        subset = (
            row.workflow_path,
            row.model,
            tuple(row.declared_prompt_cache or ()),
            row.cache_active.data_source,
        )
        by_subset.setdefault(subset, []).append((row, pricing, output_tokens))

    total = 0.0
    for group in by_subset.values():
        first = True
        for row, pricing, output_tokens in group:
            invocations = invocation_count_for(row)
            cacheable = row.cache_active.tokens_estimated or 0
            non_cacheable = max(0, row.input_tokens_estimated - cacheable)
            write_rate = _write_rate_for_ttl(pricing, ttl, row.model)

            for i in range(invocations):
                if first and i == 0:
                    rate = write_rate
                    first = False
                else:
                    rate = pricing.cache_read_rate
                total += cacheable * rate + non_cacheable * pricing.input_rate + output_tokens * pricing.output_rate
    return total


def _aggregate_first_run_savings(
    priced_rows: list[tuple[PerCallRow, ModelPricing, int | None]],
    ttl: str | None,
) -> float | None:
    """Compute total ``no_cache - first_run_with_cache`` savings (input-only — output cancels).

    Greenfield-safe: doesn't depend on output tokens.
    """
    # Cohort key includes ``row.model`` for symmetry with ``_aggregate_with_cache_projection``
    # — provider caches are model-keyed; both functions must group identically to preserve
    # the ``no_cache - first_run_with_cache == savings_first_run_usd`` arithmetic identity.
    by_subset: dict[tuple[str | None, str, tuple[str, ...], str] | None, list[tuple[PerCallRow, ModelPricing]]] = {}
    for row, pricing, _output in priced_rows:
        subset = (
            (row.workflow_path, row.model, tuple(row.declared_prompt_cache or ()), row.cache_active.data_source)
            if row.cache_active.affects_cost_projection
            else None
        )
        by_subset.setdefault(subset, []).append((row, pricing))

    total_savings = 0.0
    for subset, group in by_subset.items():
        if subset is None:
            continue  # No caching declared; no savings possible for this group.
        first = True
        for row, pricing in group:
            invocations = invocation_count_for(row)
            # See Option C note above — None → 0.
            cacheable = row.cache_active.tokens_estimated or 0
            write_rate = _write_rate_for_ttl(pricing, ttl, row.model)

            for i in range(invocations):
                # no-cache: cacheable * input_rate ; with-cache: cacheable * (write_rate or read_rate)
                if first and i == 0:
                    effective_rate = write_rate
                    first = False
                else:
                    effective_rate = pricing.cache_read_rate
                total_savings += cacheable * (pricing.input_rate - effective_rate)
    return total_savings


def _aggregate_rerun_savings(
    priced_rows: list[tuple[PerCallRow, ModelPricing, int | None]],
) -> float | None:
    """Compute total ``no_cache - rerun`` savings (all cacheable tokens at read rate).

    Greenfield-safe: doesn't depend on output tokens.
    """
    total_savings = 0.0
    for row, pricing, _output in priced_rows:
        if not row.cache_active.affects_cost_projection:
            continue
        invocations = invocation_count_for(row)
        # See Option C note in ``_aggregate_with_cache_projection`` — None → 0.
        cacheable = row.cache_active.tokens_estimated or 0
        # no-cache: cacheable * input_rate ; rerun: cacheable * read_rate
        total_savings += invocations * cacheable * (pricing.input_rate - pricing.cache_read_rate)
    return total_savings


# ---------------------------------------------------------------------------
# Actually-paid aggregation (trace-driven)
# ---------------------------------------------------------------------------


def compute_actually_paid(
    rows: list[PerCallRow],
    *,
    trace: TraceTree | None = None,
    edges: Mapping[str, str] | None = None,
    scope_workflow_paths: frozenset[str] | None = None,
) -> ActuallyPaidCost:
    """Trace-driven recorded cost (the "actually paid" figure).

    Two paths:

    - **Trace path** (preferred when ``trace`` is provided):
      ``TraceTree.iter_actual_cost_events(...)`` walked and summed via
      ``TraceTree.sum_actual_cost_events`` — includes batch items and
      sub-workflow LLM descendants. Used by ``_build_summary``.
    - **Row fallback** (when ``trace=None``): sum ``row.cost_usd`` across
      ``rows``. Useful for callers that have rows but no TraceTree handle
      (mostly tests). Heterogeneous-batch rows contribute their ``cost_usd``
      since trace recorded it.

    ``scope_workflow_paths`` (Bug 5 fix): when set, only trace events whose
    threaded ``WalkEvent.workflow_path`` is in the set contribute. The set
    should be the analyzed workflow path plus its statically-known child
    workflow paths so that ``actually_paid`` addresses the same cohort as
    ``no_cache_hypothetical_usd`` (which is IR-scoped). When ``None``,
    tree-wide sum is preserved — correct for parent-trace + parent-analyze.

    Returns ``(None, "unavailable")`` when no cost data was found in either
    path. Cached events contribute 0.0 explicitly per the trace contract.
    """
    if trace is not None:
        events = trace.iter_actual_cost_events(
            descend_sub_workflows=True,
            edges=edges or {},
        )
        if scope_workflow_paths is not None:
            events = (we for we in events if we.workflow_path in scope_workflow_paths)
        total, tier_str = trace.sum_actual_cost_events(events)
        return ActuallyPaidCost(total_usd=total, tier=CostTier(tier_str))

    # Row fallback: sum row.cost_usd. Each row's cost_usd was already
    # recorded from the trace (via the analyzer's TraceExecutionIndex);
    # summing here reproduces the trace total for callers without a tree.
    total = 0.0
    found_any = False
    for row in rows:
        if row.cost_usd is not None:
            total += row.cost_usd
            found_any = True
    if not found_any:
        return ActuallyPaidCost(total_usd=None, tier=CostTier.UNAVAILABLE)
    return ActuallyPaidCost(total_usd=total, tier=CostTier.TRACE)


__all__ = [
    "ActuallyPaidCost",
    "CostTier",
    "ModelPricing",
    "ProjectionBreakdown",
    "_aggregate_no_cache_cost",
    "_aggregate_with_cache_projection",
    "_row_body_only_cost",
    "_row_first_run_with_cache_cost",
    "compute_actually_paid",
    "compute_projections",
    "get_model_pricing",
]
