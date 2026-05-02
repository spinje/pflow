"""F2 cost wiring — pricing lookup, aggregate cost computation, tri-state contract.

These tests lock the load-bearing cost contract:

- Output cost is required for absolute current/optimized/rerun figures.
- Caching savings (current - optimized) are input-only — work greenfield.
- Tri-state (priced / partial / unavailable) renders correctly on mixed
  pricing data.
- Anthropic 1h-TTL multiplier mirrors the runtime override at
  ``llm_client.py:1047``.
"""

from __future__ import annotations

import pytest

from pflow.core.cache_analysis.analyze import PerCallRow
from pflow.core.cache_analysis.cost_estimation import (
    _pricing_from_dict,
    compute_aggregate_costs,
    get_model_pricing,
)


def _row(
    *,
    node_path: str = "X",
    model: str = "anthropic/claude-sonnet-4-5",
    input_tokens: int = 1000,
    cacheable_tokens: int = 0,
    declared_prompt_cache: list[str] | None = None,
    is_batch: bool = False,
    batch_size: int | None = None,
) -> PerCallRow:
    return PerCallRow(
        node_path=node_path,
        model=model,
        is_batch=is_batch,
        batch_size_estimated=batch_size,
        input_tokens_estimated=input_tokens,
        cacheable_tokens_estimated=cacheable_tokens,
        cache_ratio_pct=0,
        data_source="estimator",
        declared_prompt_cache=declared_prompt_cache,
    )


# ---------------------------------------------------------------------------
# Pricing lookup
# ---------------------------------------------------------------------------


def test_pricing_lookup_returns_model_pricing_for_known_model() -> None:
    pricing = get_model_pricing("claude-sonnet-4-5")
    assert pricing is not None
    assert pricing.input_rate > 0
    assert pricing.output_rate > pricing.input_rate  # Output is always pricier than input.
    assert pricing.cache_read_rate < pricing.input_rate  # Reads are cheaper than full input.


def test_pricing_lookup_falls_back_to_bare_name() -> None:
    """Mirrors ``llm_client.py``'s bare-name fallback.

    Some LiteLLM ``model_cost`` keys are bare (``claude-sonnet-4-5``); some
    are prefixed (``anthropic/claude-sonnet-4-5``). Either form must resolve.
    """
    bare = get_model_pricing("claude-sonnet-4-5")
    prefixed = get_model_pricing("anthropic/claude-sonnet-4-5")
    assert bare is not None
    # Whether the prefixed form has its own entry or falls back to bare, the
    # input rate must match — both refer to the same model.
    if prefixed is not None:
        assert prefixed.input_rate == bare.input_rate


def test_pricing_lookup_returns_none_for_unknown_model() -> None:
    assert get_model_pricing("brand-new-future-model-2099") is None


def test_pricing_lookup_returns_none_for_empty_model() -> None:
    assert get_model_pricing("") is None


def test_pricing_dict_synthesises_cache_rates_when_absent() -> None:
    """Older / sparse LiteLLM entries lack cache rates — fall back to the
    documented Anthropic ratios (1.25x write, 0.1x read) so an estimate
    still surfaces. Plausible-default beats refusing-to-price."""
    sparse = {"input_cost_per_token": 1e-6, "output_cost_per_token": 5e-6}
    pricing = _pricing_from_dict(sparse)
    assert pricing is not None
    assert pricing.cache_creation_rate == pytest.approx(1.25e-6)
    assert pricing.cache_read_rate == pytest.approx(1e-7)


def test_pricing_dict_returns_none_when_input_or_output_missing() -> None:
    assert _pricing_from_dict({"output_cost_per_token": 1e-6}) is None
    assert _pricing_from_dict({"input_cost_per_token": 1e-6}) is None
    assert _pricing_from_dict({}) is None


# ---------------------------------------------------------------------------
# Aggregate cost — greenfield (output_tokens=None) / after-run / partial
# ---------------------------------------------------------------------------


def test_greenfield_returns_none_absolutes_but_real_savings() -> None:
    """The load-bearing greenfield contract: absolute costs are None, savings
    are computable (input-only math, output cancels).

    Uses two calls sharing a subset — past the 5m-TTL break-even (1 read, ie.
    2 total uses) so the first-run savings figure is positive. A single call
    has NEGATIVE first-run savings (write costs 1.25x with no reads to
    amortize) which is correct math; see the dedicated test below.
    """
    rows = [
        _row(node_path="A", input_tokens=10_000, cacheable_tokens=8_000, declared_prompt_cache=["topic"]),
        _row(node_path="B", input_tokens=10_000, cacheable_tokens=8_000, declared_prompt_cache=["topic"]),
    ]
    breakdown = compute_aggregate_costs(
        rows,
        output_tokens_by_node={"A": None, "B": None},  # greenfield — no memo.
    )
    assert breakdown.current_usd is None
    assert breakdown.optimized_usd is None
    assert breakdown.rerun_usd is None
    # Savings ARE computable on greenfield because output cancels.
    assert breakdown.savings_first_run_usd is not None
    assert breakdown.savings_rerun_usd is not None
    assert breakdown.savings_first_run_usd > 0
    assert breakdown.savings_rerun_usd > 0
    assert breakdown.partial is False  # No mixed state — every priced row is consistent.


def test_single_call_first_run_savings_is_negative_below_break_even() -> None:
    """Anthropic 5m-TTL break-even is 1 read = 2 total uses. A single call
    with declared cache pays 1.25x for the write with no reads to amortize:
    first-run savings is NEGATIVE. Correct math; the renderer hides the line
    when ``aggregate_savings_first_run_usd <= 0``.

    Rerun savings stays positive (all reads, no writes)."""
    row = _row(
        input_tokens=10_000,
        cacheable_tokens=8_000,
        declared_prompt_cache=["topic"],
    )
    breakdown = compute_aggregate_costs([row], output_tokens_by_node={"X": None})
    assert breakdown.savings_first_run_usd is not None
    assert breakdown.savings_first_run_usd < 0  # 1 write, 0 reads => write cost > save.
    assert breakdown.savings_rerun_usd is not None
    assert breakdown.savings_rerun_usd > 0  # All reads => always positive.


def test_after_run_returns_real_absolute_costs() -> None:
    row = _row(
        input_tokens=10_000,
        cacheable_tokens=8_000,
        declared_prompt_cache=["topic", "context"],
    )
    breakdown = compute_aggregate_costs(
        [row],
        output_tokens_by_node={"X": 500},
    )
    assert breakdown.current_usd is not None
    assert breakdown.optimized_usd is not None
    assert breakdown.rerun_usd is not None
    # Optimized < Current (caching reduces input cost on first call too via 1.25x write < something? Actually
    # for a single call the optimized_cost includes a write at 1.25x — which is MORE expensive than 1.0x
    # input rate. So a SINGLE-call workflow doesn't save on optimized. Verify the right invariant.
    assert breakdown.rerun_usd < breakdown.current_usd  # All-reads always saves.


def test_optimized_cost_amortizes_writes_across_subset_group() -> None:
    """Two calls sharing a subset: 1 write + 1 read on the cacheable portion.
    Optimized aggregate < Current aggregate even when each call has output."""
    rows = [
        _row(node_path="A", input_tokens=10_000, cacheable_tokens=8_000, declared_prompt_cache=["x"]),
        _row(node_path="B", input_tokens=10_000, cacheable_tokens=8_000, declared_prompt_cache=["x"]),
    ]
    breakdown = compute_aggregate_costs(rows, output_tokens_by_node={"A": 500, "B": 500})
    assert breakdown.current_usd is not None
    assert breakdown.optimized_usd is not None
    assert breakdown.optimized_usd < breakdown.current_usd
    # Rerun: both calls are reads, so even cheaper than optimized first-run.
    assert breakdown.rerun_usd is not None
    assert breakdown.rerun_usd < breakdown.optimized_usd


def test_savings_zero_when_no_subset_declared() -> None:
    """No ``prompt_cache:`` declared anywhere → zero caching savings.

    The renderer hides the savings line when 0; this test pins the contract."""
    row = _row(input_tokens=10_000, cacheable_tokens=0, declared_prompt_cache=None)
    breakdown = compute_aggregate_costs([row], output_tokens_by_node={"X": 500})
    assert breakdown.savings_first_run_usd == 0.0
    assert breakdown.savings_rerun_usd == 0.0


def test_partial_state_when_only_some_calls_have_output_data() -> None:
    """Mixed memo: some calls have output_tokens (memo), others don't (no
    history yet). Aggregate sums what it can, marks partial."""
    rows = [
        _row(node_path="A", input_tokens=10_000, cacheable_tokens=8_000, declared_prompt_cache=["x"]),
        _row(node_path="B", input_tokens=10_000, cacheable_tokens=8_000, declared_prompt_cache=["x"]),
    ]
    breakdown = compute_aggregate_costs(
        rows,
        output_tokens_by_node={"A": 500, "B": None},
    )
    assert breakdown.partial is True
    assert breakdown.current_usd is not None  # Has data from row A.
    assert breakdown.savings_first_run_usd is not None  # Both rows priced for savings.


def test_unavailable_models_collected_when_pricing_missing() -> None:
    rows = [_row(model="ollama/llama3.2:8b")]
    breakdown = compute_aggregate_costs(rows, output_tokens_by_node={"X": 500})
    assert breakdown.current_usd is None  # No priced rows → no aggregate.
    assert "ollama/llama3.2:8b" in breakdown.unavailable_models


def test_mixed_priced_and_unpriced_models_marks_partial() -> None:
    rows = [
        _row(node_path="A", model="claude-sonnet-4-5", input_tokens=1000),
        _row(node_path="B", model="ollama/llama3.2:8b", input_tokens=1000),
    ]
    breakdown = compute_aggregate_costs(
        rows,
        output_tokens_by_node={"A": 500, "B": 500},
    )
    assert breakdown.partial is True
    assert breakdown.current_usd is not None
    assert "ollama/llama3.2:8b" in breakdown.unavailable_models
    assert "claude-sonnet-4-5" not in breakdown.unavailable_models


def test_empty_rows_produces_empty_breakdown() -> None:
    breakdown = compute_aggregate_costs([], output_tokens_by_node={})
    assert breakdown.current_usd is None
    assert breakdown.savings_first_run_usd is None
    assert breakdown.unavailable_models == ()


# ---------------------------------------------------------------------------
# 1h-TTL multiplier (Anthropic per Spike 3 / DD#37)
# ---------------------------------------------------------------------------


def test_1h_ttl_costs_more_than_5m_for_anthropic_writes() -> None:
    """1h-TTL writes are 2x base; 5m-TTL writes are 1.25x base. Optimized cost
    on first run should be HIGHER under 1h than 5m for the same workload."""
    row = _row(
        input_tokens=10_000,
        cacheable_tokens=8_000,
        declared_prompt_cache=["x"],
    )
    breakdown_5m = compute_aggregate_costs([row], output_tokens_by_node={"X": 500}, ttl="5m")
    breakdown_1h = compute_aggregate_costs([row], output_tokens_by_node={"X": 500}, ttl="1h")
    assert breakdown_5m.optimized_usd is not None
    assert breakdown_1h.optimized_usd is not None
    assert breakdown_1h.optimized_usd > breakdown_5m.optimized_usd


def test_1h_ttl_does_not_affect_non_anthropic_providers() -> None:
    """The 2x multiplier is Anthropic-specific. OpenAI / Gemini paths use
    LiteLLM's reported cache_creation_rate regardless of the workflow's
    declared TTL."""
    pricing = get_model_pricing("gpt-4o")
    if pricing is None:
        pytest.skip("gpt-4o not in litellm.model_cost on this version")

    row = _row(
        model="gpt-4o",
        input_tokens=10_000,
        cacheable_tokens=8_000,
        declared_prompt_cache=["x"],
    )
    breakdown_5m = compute_aggregate_costs([row], output_tokens_by_node={"X": 500}, ttl="5m")
    breakdown_1h = compute_aggregate_costs([row], output_tokens_by_node={"X": 500}, ttl="1h")
    assert breakdown_5m.optimized_usd == breakdown_1h.optimized_usd


# ---------------------------------------------------------------------------
# Batch invocations
# ---------------------------------------------------------------------------


def test_batch_invocations_amortize_one_write_across_n_items() -> None:
    """A batch row of N items pays 1 write + (N-1) reads on the cacheable
    portion. Per-item cost approaches the read rate as N grows."""
    row = _row(
        input_tokens=10_000,
        cacheable_tokens=8_000,
        declared_prompt_cache=["x"],
        is_batch=True,
        batch_size=10,
    )
    breakdown = compute_aggregate_costs([row], output_tokens_by_node={"X": 500}, ttl="5m")
    assert breakdown.current_usd is not None
    assert breakdown.optimized_usd is not None
    # Optimized should be << current because 9 of 10 calls are reads.
    assert breakdown.optimized_usd < breakdown.current_usd * 0.6


# ---------------------------------------------------------------------------
# Track A — per-call cost honors the trace's recorded ``cost_usd``.
#
# These tests lock the load-bearing fix for the over-estimation bug
# documented in the v2 plan: pre-fix the analyzer recomputed cost from
# ``tokens x full_rate`` even when the trace recorded a real (post-cache)
# cost. Reverting any of the production branches should make these
# tests fail with the documented numbers.
# ---------------------------------------------------------------------------


def _row_with_cost(
    *,
    cost_usd: float | None = None,
    cost_data_source: str = "trace",
    model_is_heterogeneous: bool = False,
    **kwargs,  # type: ignore[no-untyped-def]
) -> PerCallRow:
    base = _row(**kwargs)
    return PerCallRow(
        node_path=base.node_path,
        model=base.model,
        is_batch=base.is_batch,
        batch_size_estimated=base.batch_size_estimated,
        input_tokens_estimated=base.input_tokens_estimated,
        cacheable_tokens_estimated=base.cacheable_tokens_estimated,
        cache_ratio_pct=base.cache_ratio_pct,
        data_source=base.data_source,
        declared_prompt_cache=base.declared_prompt_cache,
        output_tokens_estimated=base.output_tokens_estimated,
        output_data_source=base.output_data_source,
        model_is_heterogeneous=model_is_heterogeneous,
        cacheable_data_source=base.cacheable_data_source,
        cost_usd=cost_usd,
        cost_data_source=cost_data_source,
    )


def test_current_cost_returns_recorded_cost_when_set() -> None:
    """Test 1 — Cost from trace matches recorded cost (Track A primary contract).

    Mutation contract: revert the ``if row.cost_usd is not None: return row.cost_usd``
    branch in ``_per_call_current_cost`` → this test fails because the
    aggregate falls back to the pre-fix recompute path which produces a
    much larger number on cached runs.
    """
    # Real Gemini smoke RUN1 baseline cost: $0.0021 (recorded in trace).
    # Without the fix, the analyzer recomputed ~$0.0032 (53% over).
    row = _row_with_cost(cost_usd=0.00210488, input_tokens=4709)
    breakdown = compute_aggregate_costs([row], output_tokens_by_node={"X": 76}, ttl=None)
    assert breakdown.current_usd is not None
    # Within ±5% of the recorded value (no recompute drift).
    assert abs(breakdown.current_usd - 0.00210488) / 0.00210488 < 0.05


def test_heterogeneous_batch_cost_surfaces_in_current_usd() -> None:
    """Test 8 — Heterogeneous batch + recorded cost.

    Heterogeneous batch sub-workflows (``model: ${item.model}``) can't be
    priced as one model; pre-fix they were entirely excluded from
    ``current_usd``. Track A surfaces their recorded cost separately.

    Mutation contract: drop the ``has_heterogeneous_recorded`` accumulation
    in ``_partition_rows`` → ``current_usd`` becomes None and the assertion
    fails.
    """
    het = _row_with_cost(
        node_path="batch-call",
        model="",
        cost_usd=0.0042,
        model_is_heterogeneous=True,
    )
    breakdown = compute_aggregate_costs([het], output_tokens_by_node={"batch-call": None}, ttl=None)
    # Heterogeneous-only workflow: current_usd reflects what was paid; partial
    # is True (no projection math possible on a heterogeneous model).
    assert breakdown.current_usd == 0.0042
    assert breakdown.partial is True


# ---------------------------------------------------------------------------
# AnalysisContext.cost_usd_for_node — walker semantics (Tests 5, 6, 7).
# ---------------------------------------------------------------------------


def test_cost_usd_for_node_treats_cached_event_as_zero_not_unavailable() -> None:
    """Test 5 — Cached events contribute 0.0 (NOT unavailable).

    A workflow rerun within TTL produces a cached event (``cached: True``,
    no ``llm_call``). The agent paid $0 for that node. Returning
    ``(None, "unavailable")`` would force the recompute fallback to
    fabricate a fictional cost based on tokens x rate.

    Mutation contract: drop the ``event.get("cached") and event.get("llm_call") is None``
    branch in ``cost_usd_for_node`` -> the whole node degrades to
    ``(None, "unavailable")`` -> recompute fabricates a non-zero cost.
    """
    from pflow.core.cache_analysis.context import AnalysisContext

    trace = {
        "format_version": "2.1.0",
        "nodes": [
            {
                "node_id": "cached-node",
                "node_type": "LLMNode",
                "cached": True,
                # No llm_call — cache hit skipped LLM execution.
            }
        ],
    }
    ctx = AnalysisContext(workflow_ir={}, trace_data=trace)
    cost, source = ctx.cost_usd_for_node("cached-node")
    assert cost == 0.0
    assert source == "trace"


def test_cost_usd_for_node_does_not_descend_into_sub_workflow_events() -> None:
    """Test 6 — Sub-workflow scoping.

    Track A scopes recorded cost to the focal node — sub-workflow LLM
    nodes have their own analyze-cache invocation. Including
    sub_workflow_events in the parent's cost would double-count + leak
    sub-workflow cost into parent attribution.

    Mutation contract: add a recursion into ``event.get("sub_workflow_events")``
    in ``cost_usd_for_node`` → parent reports inflated cost (sum of own
    LLM + sub-workflow LLM).
    """
    from pflow.core.cache_analysis.context import AnalysisContext

    trace = {
        "format_version": "2.1.0",
        "nodes": [
            {
                "node_id": "parent-llm",
                "node_type": "LLMNode",
                "llm_call": {"cost_usd": 0.01, "input_tokens": 100, "output_tokens": 50},
                # Synthetic sub_workflow_events — should NOT contribute to parent's cost.
                "sub_workflow_events": [
                    {
                        "node_id": "child-llm",
                        "node_type": "LLMNode",
                        "llm_call": {"cost_usd": 0.99, "input_tokens": 9999, "output_tokens": 999},
                    }
                ],
            }
        ],
    }
    ctx = AnalysisContext(workflow_ir={}, trace_data=trace)
    cost, source = ctx.cost_usd_for_node("parent-llm")
    assert cost == 0.01  # NOT 1.0 (parent + child).
    assert source == "trace"


def test_cost_usd_for_node_returns_trace_partial_when_some_leaves_unpriced() -> None:
    """Test 7 — ``cost_usd: None`` propagation (4-state trace_partial).

    A batch where some items run on a priced model (Anthropic) and others
    on an unpriced model (custom endpoint with ``cost_usd: None``) should
    surface ``"trace_partial"`` so consumers know the figure is incomplete.
    Without the 4-state distinction, agents can't tell pure trace from
    mixed.

    Mutation contract: drop the ``has_unpriced`` accumulation → unpriced
    leaves silently contribute 0 → cost reports as ``"trace"`` (looks
    fully authoritative when it isn't).
    """
    from pflow.core.cache_analysis.context import AnalysisContext

    trace = {
        "format_version": "2.1.0",
        "nodes": [
            {
                "node_id": "batch-mixed",
                "node_type": "LLMNode",
                "batch_items": [
                    {"llm_call": {"cost_usd": 0.005, "input_tokens": 100}},
                    {"llm_call": {"cost_usd": None, "input_tokens": 100}},  # Unpriced model.
                ],
            }
        ],
    }
    ctx = AnalysisContext(workflow_ir={}, trace_data=trace)
    cost, source = ctx.cost_usd_for_node("batch-mixed")
    assert cost == 0.005  # Sum of priced leaves only.
    assert source == "trace_partial"
