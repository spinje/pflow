"""Cost estimation for ``pflow analyze-cache`` summary fields.

Composes per-token rates from ``litellm.model_cost`` with token estimates
from :mod:`token_estimation` to produce the agent-facing cost figures.

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
makes greenfield cost analysis useful). ``current_cost - optimized_cost``
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
from collections.abc import Sequence
from dataclasses import dataclass

from pflow.core.llm_providers import detect_provider, model_name_without_provider

from .analyze import PerCallRow

logger = logging.getLogger(__name__)


# Anthropic 1h-TTL cache write multiplier (vs base input rate). Mirrors
# ``llm_client.py:1047`` — keep the two sites in lockstep so predicted and
# actual costs price the same byte at the same rate.
_ANTHROPIC_1H_WRITE_MULTIPLIER: float = 2.0


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
class AggregateCostBreakdown:
    """Aggregate cost figures for an entire workflow run.

    Per the tri-state contract: ``current_usd`` etc. are ``None`` on full
    unavailability; populated with partial sums when ``partial`` is True.
    Savings fields work even on greenfield (output cost cancels).
    """

    current_usd: float | None
    optimized_usd: float | None
    rerun_usd: float | None
    savings_first_run_usd: float | None
    savings_rerun_usd: float | None
    partial: bool
    unavailable_models: tuple[str, ...]


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
        import litellm
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
# Per-call cost helpers
# ---------------------------------------------------------------------------


def _write_rate_for_ttl(pricing: ModelPricing, ttl: str | None, model: str) -> float:
    """Apply the 1h-TTL Anthropic multiplier to the write rate.

    For Anthropic 1h-TTL (per Spike 3 / DD#37), writes cost 2x base instead
    of LiteLLM's 1.25x default. For all other providers / TTLs, return the
    LiteLLM-reported ``cache_creation_rate`` unchanged.
    """
    if ttl != "1h":
        return pricing.cache_creation_rate
    provider = detect_provider(model)
    if provider is not None and provider.name == "anthropic":
        return pricing.input_rate * _ANTHROPIC_1H_WRITE_MULTIPLIER
    return pricing.cache_creation_rate


def _per_call_current_cost(row: PerCallRow, pricing: ModelPricing, output_tokens: int | None) -> float | None:
    """Cost of one call without any caching: input x rate + output x rate.

    Returns ``None`` when output tokens are unavailable — refuses to fabricate
    per the tri-state contract.
    """
    if output_tokens is None:
        return None
    invocations = _invocation_count(row)
    return float(invocations) * (row.input_tokens_estimated * pricing.input_rate + output_tokens * pricing.output_rate)


def _per_call_rerun_cost(row: PerCallRow, pricing: ModelPricing, output_tokens: int | None) -> float | None:
    """Cost of one call with all cacheable tokens at read rate.

    Equivalent to: every call after the first, within TTL.
    """
    if output_tokens is None:
        return None
    invocations = _invocation_count(row)
    # Option C: cacheable may be None when greenfield-no-memo (no projection
    # data). Treat as 0 — same as "no caching" → cost reduces to all-input-rate.
    # Aggregate savings naturally → 0 for these rows (honest "we don't know").
    cacheable = row.cacheable_tokens_estimated or 0
    non_cacheable = max(0, row.input_tokens_estimated - cacheable)
    per_call_input = cacheable * pricing.cache_read_rate + non_cacheable * pricing.input_rate
    return float(invocations) * (per_call_input + output_tokens * pricing.output_rate)


def _invocation_count(row: PerCallRow) -> int:
    """Number of LLM calls one row represents (1 normally, ``batch_size`` for batches)."""
    if row.is_batch and row.batch_size_estimated is not None:
        return max(1, row.batch_size_estimated)
    return 1


# ---------------------------------------------------------------------------
# Aggregate cost computation
# ---------------------------------------------------------------------------


def compute_aggregate_costs(
    rows: list[PerCallRow],
    *,
    output_tokens_by_node: dict[str, int | None],
    ttl: str | None = None,
) -> AggregateCostBreakdown:
    """Aggregate per-call costs into the workflow-level summary figures.

    Args:
        rows: All LLM-node per-call rows from the analyzer.
        output_tokens_by_node: Map ``node_path -> output_tokens | None`` from
            ``estimate_output_tokens``. ``None`` for nodes lacking memo/trace
            data (greenfield).
        ttl: ``"5m"`` or ``"1h"`` from ``workflow_ir["cache"]["ttl"]``, or
            ``None`` for provider default.

    Math (per row):

    - ``current``: ``input x input_rate + output x output_rate``
    - ``rerun``: ``cacheable x read_rate + non_cacheable x input_rate + output x output_rate``
    - ``optimized``: per declared-subset group, 1 write + (N-1) reads. Calls
      without a declared subset behave like ``current``.

    Savings (``current - optimized`` and ``current - rerun``) are input-only
    by construction (output cancels), so they're always computable when
    pricing is available — even on greenfield (no output tokens needed).
    """
    priced_rows: list[tuple[PerCallRow, ModelPricing, int | None]] = []
    unavailable_models: list[str] = []
    seen_unavailable: set[str] = set()

    for row in rows:
        pricing = get_model_pricing(row.model) if row.model else None
        if pricing is None:
            if row.model and row.model not in seen_unavailable:
                unavailable_models.append(row.model)
                seen_unavailable.add(row.model)
            continue
        output_tokens = output_tokens_by_node.get(row.node_path)
        priced_rows.append((row, pricing, output_tokens))

    if not priced_rows:
        return AggregateCostBreakdown(
            current_usd=None,
            optimized_usd=None,
            rerun_usd=None,
            savings_first_run_usd=None,
            savings_rerun_usd=None,
            partial=False,
            unavailable_models=tuple(unavailable_models),
        )

    # --- Absolute cost figures (require output tokens) ----------------------
    rows_with_output = [(r, p, o) for r, p, o in priced_rows if o is not None]
    rows_without_output = [(r, p, o) for r, p, o in priced_rows if o is None]
    has_partial_costs = bool(rows_with_output) and (bool(rows_without_output) or bool(unavailable_models))

    if rows_with_output:
        current_usd: float | None = sum(_per_call_current_cost(r, p, o) or 0.0 for r, p, o in rows_with_output)
        rerun_usd: float | None = sum(_per_call_rerun_cost(r, p, o) or 0.0 for r, p, o in rows_with_output)
        optimized_usd: float | None = _aggregate_optimized_cost(rows_with_output, ttl)
    else:
        current_usd = None
        rerun_usd = None
        optimized_usd = None

    # --- Savings (input-only — greenfield-safe) ------------------------------
    savings_first_run_usd = _aggregate_first_run_savings(priced_rows, ttl)
    savings_rerun_usd = _aggregate_rerun_savings(priced_rows)

    return AggregateCostBreakdown(
        current_usd=current_usd,
        optimized_usd=optimized_usd,
        rerun_usd=rerun_usd,
        savings_first_run_usd=savings_first_run_usd,
        savings_rerun_usd=savings_rerun_usd,
        partial=has_partial_costs,
        unavailable_models=tuple(unavailable_models),
    )


def _aggregate_optimized_cost(
    priced_rows: Sequence[tuple[PerCallRow, ModelPricing, int | None]],
    ttl: str | None,
) -> float:
    """Compute the with-caching cost across all priced rows with output data.

    Groups calls by their declared ``prompt_cache:`` subset (a tuple of chunk
    names). Each group of N calls pays 1 write + (N-1) reads on the cacheable
    portion. Calls without a declared subset behave like ``current``.
    """
    # Group calls by subset (tuple of chunk names). ``None`` means "no subset".
    by_subset: dict[tuple[str, ...] | None, list[tuple[PerCallRow, ModelPricing, int]]] = {}
    for row, pricing, output_tokens in priced_rows:
        if output_tokens is None:
            continue
        subset = tuple(row.declared_prompt_cache) if row.declared_prompt_cache else None
        by_subset.setdefault(subset, []).append((row, pricing, output_tokens))

    total = 0.0
    for subset, group in by_subset.items():
        if subset is None:
            for row, pricing, output_tokens in group:
                cost = _per_call_current_cost(row, pricing, output_tokens)
                if cost is not None:
                    total += cost
            continue

        # First call in the group pays write rate; remaining pay read rate.
        # Applies per-invocation: a batch of N items in a single row produces
        # N invocations (1 write + (N-1) reads); subsequent rows in the same
        # subset are all reads (the cache was already written).
        first = True
        for row, pricing, output_tokens in group:
            invocations = _invocation_count(row)
            # See Option C note above — None → 0.
            cacheable = row.cacheable_tokens_estimated or 0
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
    """Compute total ``current - optimized`` savings (input-only — output cancels).

    Greenfield-safe: doesn't depend on output tokens.
    """
    by_subset: dict[tuple[str, ...] | None, list[tuple[PerCallRow, ModelPricing]]] = {}
    for row, pricing, _output in priced_rows:
        subset = tuple(row.declared_prompt_cache) if row.declared_prompt_cache else None
        by_subset.setdefault(subset, []).append((row, pricing))

    total_savings = 0.0
    for subset, group in by_subset.items():
        if subset is None:
            continue  # No caching declared; no savings possible for this group.
        first = True
        for row, pricing in group:
            invocations = _invocation_count(row)
            # See Option C note above — None → 0.
            cacheable = row.cacheable_tokens_estimated or 0
            write_rate = _write_rate_for_ttl(pricing, ttl, row.model)

            for i in range(invocations):
                # current: cacheable x input_rate ; optimized: cacheable x (write_rate or read_rate)
                if first and i == 0:
                    optimized_rate = write_rate
                    first = False
                else:
                    optimized_rate = pricing.cache_read_rate
                total_savings += cacheable * (pricing.input_rate - optimized_rate)
    return total_savings


def _aggregate_rerun_savings(
    priced_rows: list[tuple[PerCallRow, ModelPricing, int | None]],
) -> float | None:
    """Compute total ``current - rerun`` savings (all cacheable tokens at read rate).

    Greenfield-safe: doesn't depend on output tokens.
    """
    total_savings = 0.0
    for row, pricing, _output in priced_rows:
        if not row.declared_prompt_cache:
            continue
        invocations = _invocation_count(row)
        # See Option C note in `_full_cost_with_caching` — None → 0.
        cacheable = row.cacheable_tokens_estimated or 0
        # current: cacheable x input_rate ; rerun: cacheable x read_rate
        total_savings += invocations * cacheable * (pricing.input_rate - pricing.cache_read_rate)
    return total_savings


__all__ = [
    "AggregateCostBreakdown",
    "ModelPricing",
    "compute_aggregate_costs",
    "get_model_pricing",
]
