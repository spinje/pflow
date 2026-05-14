"""F2 cost wiring — pricing lookup, projection / actually-paid split, tri-state contract.

Phase 4 split:

- ``compute_projections`` — IR-driven hypothetical cost projections. Pure
  ``tokens * rate`` math; never reads ``row.cost_usd``. Greenfield-safe
  savings figures.
- ``compute_actually_paid`` — Trace-driven recorded cost. Prefers
  ``TraceTree.total_cost``; falls back to summing ``row.cost_usd`` for
  callers without a TraceTree handle.

These tests lock:

- Output cost is required for absolute no_cache/cost_without_caching/rerun
  projection figures.
- Caching savings (input-only — output cancels) work greenfield.
- Tri-state (priced / partial / unavailable) renders correctly on mixed
  pricing data.
- Heterogeneous-batch rows are excluded from projections; their actually-paid
  cost surfaces via :func:`compute_actually_paid`.
- Anthropic 1h-TTL multiplier mirrors the runtime override at
  ``llm_client.py:1047``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import pflow.core.cache_analysis.cost_estimation as cost_estimation_module
from pflow.core.cache_analysis.analyze import PerCallRow, ProjectionExclusion, analyze
from pflow.core.cache_analysis.cost_estimation import (
    ModelPricing,
    _aggregate_with_cache_projection,
    _pricing_from_dict,
    _row_body_only_cost,
    _row_first_run_with_cache_cost,
    compute_actually_paid,
    compute_projections,
    get_model_pricing,
)
from tests.shared.trace_fixture_builder import TraceFixtureBuilder


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


def test_row_body_only_cost_excludes_chunks() -> None:
    row = PerCallRow(**{
        **_row(input_tokens=1_200).__dict__,
        "chunk_tokens_estimated": 1_000,
    })
    pricing = ModelPricing(input_rate=0.01, output_rate=0.10, cache_creation_rate=0.02, cache_read_rate=0.001)

    assert _row_body_only_cost(row, pricing, output_tokens=3) == pytest.approx(2.3)


def test_row_first_run_with_cache_cost_matches_single_row_projection() -> None:
    row = PerCallRow(**{
        **_row(
            input_tokens=1_200,
            cacheable_tokens=1_000,
            declared_prompt_cache=["bundle"],
            is_batch=True,
            batch_size=3,
        ).__dict__,
        "chunk_tokens_estimated": 1_000,
    })
    pricing = ModelPricing(input_rate=0.01, output_rate=0.10, cache_creation_rate=0.02, cache_read_rate=0.001)

    row_cost = _row_first_run_with_cache_cost(row, pricing, output_tokens=3, ttl="5m")
    projection = _aggregate_with_cache_projection([(row, pricing, 3)], ttl="5m")

    assert projection == pytest.approx(row_cost)


def _write_trace(tmp_path: Path, workflow_path: str, nodes: list[dict[str, Any]]) -> Path:
    path = tmp_path / "trace.json"
    path.write_text(
        json.dumps(TraceFixtureBuilder().trace(workflow_path=workflow_path, nodes=nodes)),
        encoding="utf-8",
    )
    return path


def _static_batch_ir(*, declared: bool = False, batch_items: list[str] | None = None) -> dict:
    node: dict = {
        "id": "batch",
        "type": "llm",
        "model": "test/model",
        "batch": {"items": batch_items or ["a", "b", "c"], "as": "item"},
        "params": {"prompt": "${context} ${item}"},
    }
    cache = None
    if declared:
        cache = {"items": [{"name": "context", "var": "context", "prose_before": ""}]}
        node["prompt_cache"] = ["context"]
    workflow = {"nodes": [node]}
    if cache is not None:
        workflow["cache"] = cache
    return workflow


# ---------------------------------------------------------------------------
# Pricing lookup
# ---------------------------------------------------------------------------


def test_pricing_lookup_returns_model_pricing_for_known_model() -> None:
    pricing = get_model_pricing("claude-sonnet-4-5")
    assert pricing is not None
    assert pricing.input_rate > 0
    assert pricing.output_rate > pricing.input_rate  # Output is always pricier than input.
    assert pricing.cache_read_rate < pricing.input_rate  # Reads are cheaper than full input.


def test_static_batch_no_cache_cost_matches_per_call_trace_total(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cost_estimation_module,
        "get_model_pricing",
        lambda _model: ModelPricing(
            input_rate=3e-6,
            output_rate=0.0,
            cache_creation_rate=3.75e-6,
            cache_read_rate=0.3e-6,
        ),
    )
    workflow_path = str(tmp_path / "static-batch.pflow.md")
    builder = TraceFixtureBuilder()
    trace_path = _write_trace(
        tmp_path,
        workflow_path,
        [
            builder.llm_event("batch", model="test/model", input_tokens=1000, output_tokens=0),
            builder.llm_event("batch", model="test/model", input_tokens=1000, output_tokens=0),
            builder.llm_event("batch", model="test/model", input_tokens=1000, output_tokens=0),
        ],
    )

    analysis = analyze(
        _static_batch_ir(),
        workflow_path=workflow_path,
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )
    row = analysis.per_call[0]
    projections = compute_projections(
        list(analysis.per_call),
        output_tokens_by_node={(row.workflow_path, row.node_path): row.output_tokens_estimated},
    )

    assert row.input_tokens_estimated == 1000
    assert projections.no_cache_hypothetical_usd is not None
    assert projections.no_cache_hypothetical_usd < 0.010
    assert projections.no_cache_hypothetical_usd == pytest.approx(0.009)


def test_static_batch_no_cache_cost_includes_output_tokens_once_per_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cost_estimation_module,
        "get_model_pricing",
        lambda _model: ModelPricing(
            input_rate=1e-6,
            output_rate=10e-6,
            cache_creation_rate=1.25e-6,
            cache_read_rate=0.1e-6,
        ),
    )
    workflow_path = str(tmp_path / "static-batch-output.pflow.md")
    builder = TraceFixtureBuilder()
    trace_path = _write_trace(
        tmp_path,
        workflow_path,
        [
            builder.llm_event("batch", model="test/model", input_tokens=1000, output_tokens=500),
            builder.llm_event("batch", model="test/model", input_tokens=1000, output_tokens=500),
            builder.llm_event("batch", model="test/model", input_tokens=1000, output_tokens=500),
        ],
    )

    analysis = analyze(
        _static_batch_ir(),
        workflow_path=workflow_path,
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )
    row = analysis.per_call[0]
    projections = compute_projections(
        list(analysis.per_call),
        output_tokens_by_node={(row.workflow_path, row.node_path): row.output_tokens_estimated},
    )

    assert row.output_tokens_estimated == 500
    assert projections.no_cache_hypothetical_usd == pytest.approx(0.018)


def test_static_batch_rerun_cost_with_cache_uses_per_call_trace_cacheable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cost_estimation_module,
        "get_model_pricing",
        lambda _model: ModelPricing(
            input_rate=1e-6,
            output_rate=0.0,
            cache_creation_rate=1.25e-6,
            cache_read_rate=0.1e-6,
        ),
    )
    workflow_path = str(tmp_path / "static-batch-cache.pflow.md")
    builder = TraceFixtureBuilder()
    trace_path = _write_trace(
        tmp_path,
        workflow_path,
        [
            builder.llm_event(
                "batch",
                model="test/model",
                input_tokens=1000,
                output_tokens=0,
                cache_creation_input_tokens=300,
            ),
            builder.llm_event(
                "batch",
                model="test/model",
                input_tokens=1000,
                output_tokens=0,
                cache_read_input_tokens=300,
            ),
            builder.llm_event(
                "batch",
                model="test/model",
                input_tokens=1000,
                output_tokens=0,
                cache_read_input_tokens=300,
            ),
        ],
    )

    analysis = analyze(
        _static_batch_ir(declared=True),
        workflow_path=workflow_path,
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )
    row = analysis.per_call[0]
    projections = compute_projections(
        list(analysis.per_call),
        output_tokens_by_node={(row.workflow_path, row.node_path): row.output_tokens_estimated},
    )

    assert row.cacheable_tokens_estimated == 300
    assert projections.rerun_within_ttl_hypothetical_usd == pytest.approx(0.00219)


def test_dynamic_batch_no_cache_cost_unchanged_after_static_batch_fix(tmp_path: Path) -> None:
    workflow_path = str(tmp_path / "dynamic-batch.pflow.md")
    workflow_ir = {
        "inputs": {"items": {"type": "array"}},
        "nodes": [
            {
                "id": "batch",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "batch": {"items": "${items}", "as": "item"},
                "params": {"prompt": "${item}"},
            }
        ],
    }
    builder = TraceFixtureBuilder()
    trace_path = _write_trace(
        tmp_path,
        workflow_path,
        [
            builder.llm_event("batch", input_tokens=1000, output_tokens=10),
            builder.llm_event("batch", input_tokens=1000, output_tokens=10),
            builder.llm_event("batch", input_tokens=1000, output_tokens=10),
        ],
    )

    analysis = analyze(
        workflow_ir,
        parameters={"items": ["a", "b", "c"]},
        workflow_path=workflow_path,
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )

    row = analysis.per_call[0]
    assert row.batch_size_estimated is None
    assert row.input_tokens_estimated == 1000
    assert row.output_tokens_estimated == 10
    pricing = get_model_pricing(row.model)
    assert pricing is not None
    expected_no_cache = row.observed_call_count * (
        row.input_tokens_estimated * pricing.input_rate + row.output_tokens_estimated * pricing.output_rate
    )
    assert analysis.summary.no_cache_hypothetical_usd == pytest.approx(expected_no_cache)


def test_non_batch_repeated_calls_yield_per_call_rows(tmp_path: Path) -> None:
    workflow_path = str(tmp_path / "parent-repeated.pflow.md")
    workflow_ir = {
        "nodes": [
            {
                "id": "select",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "Select"},
            }
        ],
    }
    builder = TraceFixtureBuilder()
    trace_path = _write_trace(
        tmp_path,
        workflow_path,
        [
            builder.llm_event("select", input_tokens=1000, output_tokens=20),
            builder.llm_event("select", input_tokens=1000, output_tokens=20),
            builder.llm_event("select", input_tokens=1000, output_tokens=20),
            builder.llm_event("select", input_tokens=1000, output_tokens=20),
        ],
    )

    analysis = analyze(
        workflow_ir,
        workflow_path=workflow_path,
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )

    row = analysis.per_call[0]
    assert row.is_batch is False
    assert row.observed_call_count == 4
    assert row.input_tokens_estimated == 1000
    assert row.output_tokens_estimated == 20
    pricing = get_model_pricing(row.model)
    assert pricing is not None
    expected_no_cache = row.observed_call_count * (
        row.input_tokens_estimated * pricing.input_rate + row.output_tokens_estimated * pricing.output_rate
    )
    assert analysis.summary.no_cache_hypothetical_usd == pytest.approx(expected_no_cache)


def test_static_batch_conditional_dispatch_divisor_uses_observed_count(tmp_path: Path) -> None:
    workflow_path = str(tmp_path / "static-batch-conditional.pflow.md")
    builder = TraceFixtureBuilder()
    trace_path = _write_trace(
        tmp_path,
        workflow_path,
        [
            builder.llm_event("batch", model="anthropic/claude-sonnet-4-5", input_tokens=1000, output_tokens=100),
            builder.llm_event("batch", model="anthropic/claude-sonnet-4-5", input_tokens=1000, output_tokens=100),
            builder.llm_event("batch", model="anthropic/claude-sonnet-4-5", input_tokens=1000, output_tokens=100),
        ],
    )

    analysis = analyze(
        _static_batch_ir(batch_items=["a", "b", "c", "d"]),
        workflow_path=workflow_path,
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )

    row = analysis.per_call[0]
    assert row.batch_size_estimated == 4
    assert row.observed_call_count == 3
    assert row.input_tokens_estimated == 1000
    assert row.output_tokens_estimated == 100
    assert analysis.summary.total_input_tokens_estimated == 4000


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
    projections = compute_projections(
        rows,
        output_tokens_by_node={"A": None, "B": None},  # greenfield — no memo.
    )
    assert projections.no_cache_hypothetical_usd is None
    assert projections.first_run_with_cache_hypothetical_usd is None
    assert projections.rerun_within_ttl_hypothetical_usd is None
    # Savings ARE computable on greenfield because output cancels.
    assert projections.savings_first_run_usd is not None
    assert projections.savings_rerun_usd is not None
    assert projections.savings_first_run_usd > 0
    assert projections.savings_rerun_usd > 0
    assert projections.partial is False  # No mixed state — every priced row is consistent.


def test_single_call_first_run_savings_is_negative_below_break_even() -> None:
    """Anthropic 5m-TTL break-even is 1 read = 2 total uses. A single call
    with declared cache pays 1.25x for the write with no reads to amortize:
    first-run savings is NEGATIVE. Correct math; summary/rendering must expose
    this as a cost-increase delta, not negative savings.

    Rerun savings stays positive (all reads, no writes)."""
    row = _row(
        input_tokens=10_000,
        cacheable_tokens=8_000,
        declared_prompt_cache=["topic"],
    )
    projections = compute_projections([row], output_tokens_by_node={"X": None})
    assert projections.savings_first_run_usd is not None
    assert projections.savings_first_run_usd < 0  # 1 write, 0 reads => write cost > save.
    assert projections.savings_rerun_usd is not None
    assert projections.savings_rerun_usd > 0  # All reads => always positive.


def test_after_run_returns_real_absolute_costs() -> None:
    row = _row(
        input_tokens=10_000,
        cacheable_tokens=8_000,
        declared_prompt_cache=["topic", "context"],
    )
    projections = compute_projections(
        [row],
        output_tokens_by_node={"X": 500},
    )
    assert projections.no_cache_hypothetical_usd is not None
    assert projections.first_run_with_cache_hypothetical_usd is not None
    assert projections.rerun_within_ttl_hypothetical_usd is not None
    # rerun < no-cache always (all-reads cheaper than full input). For a SINGLE
    # call, cost_without_caching includes a write at 1.25x — MORE expensive than
    # the 1.0x input rate — so it does NOT beat no-cache for a single call.
    # Multi-call (see test_with_cache_projection_amortizes_writes_across_subset_group)
    # is where with-cache wins.
    assert projections.rerun_within_ttl_hypothetical_usd < projections.no_cache_hypothetical_usd


def test_with_cache_projection_amortizes_writes_across_subset_group() -> None:
    """Two calls sharing a subset: 1 write + 1 read on the cacheable portion.
    With-cache first-run aggregate < no-cache aggregate even when each call has output."""
    rows = [
        _row(node_path="A", input_tokens=10_000, cacheable_tokens=8_000, declared_prompt_cache=["x"]),
        _row(node_path="B", input_tokens=10_000, cacheable_tokens=8_000, declared_prompt_cache=["x"]),
    ]
    projections = compute_projections(rows, output_tokens_by_node={"A": 500, "B": 500})
    assert projections.no_cache_hypothetical_usd is not None
    assert projections.first_run_with_cache_hypothetical_usd is not None
    assert projections.first_run_with_cache_hypothetical_usd < projections.no_cache_hypothetical_usd
    # Rerun: both calls are reads, so even cheaper than first-run with-cache.
    assert projections.rerun_within_ttl_hypothetical_usd is not None
    assert projections.rerun_within_ttl_hypothetical_usd < projections.first_run_with_cache_hypothetical_usd


def test_with_cache_projection_does_not_cross_pollinate_workflow_scopes() -> None:
    """Defends: subset grouping must include ``workflow_path``; bare subset
    grouping would let a child workflow pay a cache READ when it should
    pay a cache WRITE.
    """
    parent = PerCallRow(**{
        **_row(node_path="draft", input_tokens=10_000, cacheable_tokens=8_000, declared_prompt_cache=["x"]).__dict__,
        "workflow_path": "parent.pflow.md",
    })
    child = PerCallRow(**{
        **_row(node_path="draft", input_tokens=10_000, cacheable_tokens=8_000, declared_prompt_cache=["x"]).__dict__,
        "workflow_path": "child.pflow.md",
    })

    scoped = compute_projections(
        [parent, child],
        output_tokens_by_node={
            ("parent.pflow.md", "draft"): 500,
            ("child.pflow.md", "draft"): 500,
        },
    )
    single_scope = compute_projections(
        [
            PerCallRow(**{**parent.__dict__, "workflow_path": "parent.pflow.md"}),
            PerCallRow(**{**child.__dict__, "workflow_path": "parent.pflow.md"}),
        ],
        output_tokens_by_node={
            ("parent.pflow.md", "draft"): 500,
        },
    )

    assert scoped.first_run_with_cache_hypothetical_usd is not None
    assert single_scope.first_run_with_cache_hypothetical_usd is not None
    assert scoped.first_run_with_cache_hypothetical_usd > single_scope.first_run_with_cache_hypothetical_usd


def test_with_cache_projection_separates_cohorts_by_model() -> None:
    """Defends: subset grouping must include ``row.model`` because provider caches
    are model-keyed.

    Two rows on different models (Sonnet + Haiku) sharing identical
    ``prompt_cache:`` must pay TWO writes, not one write + one read. Pre-fix the
    cohort key was ``(workflow_path, declared_prompt_cache)`` only — both rows
    landed in the same cohort, the second model silently got ``cache_read_rate``,
    and ``savings_first_run_usd`` over-counted in exactly the scenario
    ``cache.heterogeneous-models-fragment-cache`` warns about.

    Load-bearing contract: when models differ across rows, the mixed projection
    MUST equal the sum of solo projections (no cross-model amortization).

    Mutation contract: removing ``row.model`` from the cohort key in
    ``cost_estimation.py::_aggregate_with_cache_projection`` would let the
    second model's row apply at ``cache_read_rate`` instead of ``write_rate``,
    breaking the additivity.
    """
    sonnet_pricing = get_model_pricing("anthropic/claude-sonnet-4-5")
    haiku_pricing = get_model_pricing("anthropic/claude-haiku-4-5")
    if sonnet_pricing is None or haiku_pricing is None:
        pytest.skip("LiteLLM pricing data missing for one of the test models")

    sonnet = _row(
        node_path="sonnet-call",
        model="anthropic/claude-sonnet-4-5",
        input_tokens=10_000,
        cacheable_tokens=8_000,
        declared_prompt_cache=["x"],
    )
    haiku = _row(
        node_path="haiku-call",
        model="anthropic/claude-haiku-4-5",
        input_tokens=10_000,
        cacheable_tokens=8_000,
        declared_prompt_cache=["x"],
    )

    sonnet_solo = compute_projections([sonnet], output_tokens_by_node={"sonnet-call": 500})
    haiku_solo = compute_projections([haiku], output_tokens_by_node={"haiku-call": 500})
    mixed = compute_projections(
        [sonnet, haiku],
        output_tokens_by_node={"sonnet-call": 500, "haiku-call": 500},
    )

    assert sonnet_solo.first_run_with_cache_hypothetical_usd is not None
    assert haiku_solo.first_run_with_cache_hypothetical_usd is not None
    assert mixed.first_run_with_cache_hypothetical_usd is not None
    # Cross-model independence: mixed equals the sum of solo projections because
    # each model gets its own cohort + own write. Pre-fix, the second model's
    # row would land in the first model's cohort and silently apply
    # cache_read_rate, making mixed strictly LESS than the sum.
    assert mixed.first_run_with_cache_hypothetical_usd == pytest.approx(
        sonnet_solo.first_run_with_cache_hypothetical_usd + haiku_solo.first_run_with_cache_hypothetical_usd,
        rel=1e-9,
    )


def test_first_run_savings_separates_cohorts_by_model() -> None:
    """Symmetric to ``test_with_cache_projection_separates_cohorts_by_model`` —
    locks ``_aggregate_first_run_savings`` cohort key.

    The two functions must change in lockstep to preserve the arithmetic
    identity (see ``test_cohort_arithmetic_identity_preserved_across_models``).

    Load-bearing contract: when models differ, mixed savings == sum of solo
    savings (no cross-model amortization).

    Mutation contract: dropping ``row.model`` from the cohort key in
    ``_aggregate_first_run_savings`` lets the second model's cacheable tokens
    apply at ``cache_read_rate`` instead of ``write_rate``, inflating
    ``savings_first_run_usd``.
    """
    sonnet_pricing = get_model_pricing("anthropic/claude-sonnet-4-5")
    haiku_pricing = get_model_pricing("anthropic/claude-haiku-4-5")
    if sonnet_pricing is None or haiku_pricing is None:
        pytest.skip("LiteLLM pricing data missing for one of the test models")

    sonnet = _row(
        node_path="sonnet-call",
        model="anthropic/claude-sonnet-4-5",
        input_tokens=10_000,
        cacheable_tokens=8_000,
        declared_prompt_cache=["x"],
    )
    haiku = _row(
        node_path="haiku-call",
        model="anthropic/claude-haiku-4-5",
        input_tokens=10_000,
        cacheable_tokens=8_000,
        declared_prompt_cache=["x"],
    )

    sonnet_solo = compute_projections([sonnet], output_tokens_by_node={"sonnet-call": 500})
    haiku_solo = compute_projections([haiku], output_tokens_by_node={"haiku-call": 500})
    mixed = compute_projections(
        [sonnet, haiku],
        output_tokens_by_node={"sonnet-call": 500, "haiku-call": 500},
    )

    assert sonnet_solo.savings_first_run_usd is not None
    assert haiku_solo.savings_first_run_usd is not None
    assert mixed.savings_first_run_usd is not None
    # Cross-model independence: solo savings on first-run are NEGATIVE for each
    # model (single-call write costs more than the input rate it replaces — see
    # ``test_single_call_first_run_savings_is_negative_below_break_even``).
    # Mixed savings must equal the sum (no spurious amortization across models).
    assert mixed.savings_first_run_usd == pytest.approx(
        sonnet_solo.savings_first_run_usd + haiku_solo.savings_first_run_usd,
        rel=1e-9,
    )


def test_cohort_arithmetic_identity_preserved_across_models() -> None:
    """Locks the lockstep invariant: ``_aggregate_with_cache_projection`` and
    ``_aggregate_first_run_savings`` MUST group identically.

    Identity (input-side only — output cancels per the savings docstring):
        no_cache_input - first_run_with_cache_input == savings_first_run

    If only one of the two functions includes ``row.model`` in the cohort key,
    the identity breaks and summary numbers diverge from each other. This test
    fails loudly under that mutation.
    """
    sonnet_pricing = get_model_pricing("anthropic/claude-sonnet-4-5")
    haiku_pricing = get_model_pricing("anthropic/claude-haiku-4-5")
    if sonnet_pricing is None or haiku_pricing is None:
        pytest.skip("LiteLLM pricing data missing for one of the test models")

    rows = [
        _row(
            node_path="A",
            model="anthropic/claude-sonnet-4-5",
            input_tokens=10_000,
            cacheable_tokens=8_000,
            declared_prompt_cache=["x"],
        ),
        _row(
            node_path="B",
            model="anthropic/claude-haiku-4-5",
            input_tokens=10_000,
            cacheable_tokens=8_000,
            declared_prompt_cache=["x"],
        ),
        _row(
            node_path="C",
            model="anthropic/claude-sonnet-4-5",
            input_tokens=10_000,
            cacheable_tokens=8_000,
            declared_prompt_cache=["x"],
        ),
    ]
    projections = compute_projections(
        rows,
        output_tokens_by_node={"A": 500, "B": 500, "C": 500},
    )

    # The lockstep invariant: output cost is the same in both projections
    # (caching doesn't change output tokens or rate), so the difference between
    # ``no_cache_hypothetical_usd`` and ``first_run_with_cache_hypothetical_usd``
    # MUST equal ``savings_first_run_usd`` (which is input-only by construction).
    # If only one of the two functions includes ``row.model`` in the cohort key,
    # the cohort math diverges and this identity breaks.
    assert projections.first_run_with_cache_hypothetical_usd is not None
    assert projections.no_cache_hypothetical_usd is not None
    assert projections.savings_first_run_usd is not None
    input_side_delta = projections.no_cache_hypothetical_usd - projections.first_run_with_cache_hypothetical_usd
    assert input_side_delta == pytest.approx(projections.savings_first_run_usd, rel=1e-9)


def test_did_not_execute_rows_do_not_contribute_to_projection_costs() -> None:
    """Defends: phantom (did-not-execute) rows must be partitioned out
    before projection — otherwise they inflate ``no_cache_hypothetical``
    and rerun aggregates.
    """
    fired = _row(
        node_path="fired",
        input_tokens=10_000,
        cacheable_tokens=8_000,
        declared_prompt_cache=["x"],
    )
    phantom = PerCallRow(**{
        **_row(
            node_path="phantom",
            input_tokens=10_000,
            cacheable_tokens=8_000,
            declared_prompt_cache=["x"],
        ).__dict__,
        "did_not_execute_in_trace": True,
    })

    with_phantom = compute_projections(
        [fired, phantom],
        output_tokens_by_node={"fired": 500, "phantom": 500},
    )
    without_phantom = compute_projections([fired], output_tokens_by_node={"fired": 500})

    assert with_phantom == without_phantom


def test_savings_zero_when_no_subset_declared() -> None:
    """No ``prompt_cache:`` declared anywhere → zero caching savings.

    The renderer hides the savings line when 0; this test pins the contract."""
    row = _row(input_tokens=10_000, cacheable_tokens=0, declared_prompt_cache=None)
    projections = compute_projections([row], output_tokens_by_node={"X": 500})
    assert projections.savings_first_run_usd == 0.0
    assert projections.savings_rerun_usd == 0.0


def test_partial_state_when_only_some_calls_have_output_data() -> None:
    """Mixed memo: some calls have output_tokens (memo), others don't (no
    history yet). Projection sums what it can, marks partial."""
    rows = [
        _row(node_path="A", input_tokens=10_000, cacheable_tokens=8_000, declared_prompt_cache=["x"]),
        _row(node_path="B", input_tokens=10_000, cacheable_tokens=8_000, declared_prompt_cache=["x"]),
    ]
    projections = compute_projections(
        rows,
        output_tokens_by_node={"A": 500, "B": None},
    )
    assert projections.partial is True
    assert projections.no_cache_hypothetical_usd is not None  # Has data from row A.
    assert projections.savings_first_run_usd is not None  # Both rows priced for savings.


def test_unavailable_models_collected_when_pricing_missing() -> None:
    rows = [_row(model="ollama/llama3.2:8b")]
    projections = compute_projections(rows, output_tokens_by_node={"X": 500})
    assert projections.no_cache_hypothetical_usd is None  # No priced rows → no aggregate.
    assert "ollama/llama3.2:8b" in projections.unavailable_models


def test_mixed_priced_and_unpriced_models_marks_partial() -> None:
    rows = [
        _row(node_path="A", model="claude-sonnet-4-5", input_tokens=1000),
        _row(node_path="B", model="ollama/llama3.2:8b", input_tokens=1000),
    ]
    projections = compute_projections(
        rows,
        output_tokens_by_node={"A": 500, "B": 500},
    )
    assert projections.partial is True
    assert projections.no_cache_hypothetical_usd is not None
    assert "ollama/llama3.2:8b" in projections.unavailable_models
    assert "claude-sonnet-4-5" not in projections.unavailable_models


def test_empty_rows_produces_empty_breakdown() -> None:
    projections = compute_projections([], output_tokens_by_node={})
    assert projections.no_cache_hypothetical_usd is None
    assert projections.savings_first_run_usd is None
    assert projections.unavailable_models == ()


# ---------------------------------------------------------------------------
# 1h-TTL multiplier (Anthropic per Spike 3 / DD#37)
# ---------------------------------------------------------------------------


def test_1h_ttl_costs_more_than_5m_for_anthropic_writes() -> None:
    """1h-TTL writes are 2x base; 5m-TTL writes are 1.25x base. With-cache
    first-run projection should be HIGHER under 1h than 5m for the same workload."""
    row = _row(
        input_tokens=10_000,
        cacheable_tokens=8_000,
        declared_prompt_cache=["x"],
    )
    projections_5m = compute_projections([row], output_tokens_by_node={"X": 500}, ttl="5m")
    projections_1h = compute_projections([row], output_tokens_by_node={"X": 500}, ttl="1h")
    assert projections_5m.first_run_with_cache_hypothetical_usd is not None
    assert projections_1h.first_run_with_cache_hypothetical_usd is not None
    assert projections_1h.first_run_with_cache_hypothetical_usd > projections_5m.first_run_with_cache_hypothetical_usd


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
    projections_5m = compute_projections([row], output_tokens_by_node={"X": 500}, ttl="5m")
    projections_1h = compute_projections([row], output_tokens_by_node={"X": 500}, ttl="1h")
    assert projections_5m.first_run_with_cache_hypothetical_usd == projections_1h.first_run_with_cache_hypothetical_usd


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
    projections = compute_projections([row], output_tokens_by_node={"X": 500}, ttl="5m")
    assert projections.no_cache_hypothetical_usd is not None
    assert projections.first_run_with_cache_hypothetical_usd is not None
    # With-cache should be << no-cache because 9 of 10 calls are reads.
    assert projections.first_run_with_cache_hypothetical_usd < projections.no_cache_hypothetical_usd * 0.6


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


def test_actually_paid_sums_row_cost_usd_when_set() -> None:
    """Track A primary contract: ``compute_actually_paid`` sums ``row.cost_usd``
    via the row-fallback path (no TraceTree provided).

    Real Gemini smoke RUN1 baseline cost: $0.0021 (recorded in trace).
    Pre-Track-A the analyzer recomputed ~$0.0032 (53% over) by ignoring
    ``row.cost_usd``. The fallback path mirrors the same contract.
    """
    row = _row_with_cost(cost_usd=0.00210488, input_tokens=4709)
    actually_paid = compute_actually_paid([row])
    assert actually_paid.total_usd is not None
    # Within ±5% of the recorded value (no recompute drift).
    assert abs(actually_paid.total_usd - 0.00210488) / 0.00210488 < 0.05
    assert actually_paid.tier == "trace"


def test_heterogeneous_batch_cost_surfaces_via_actually_paid() -> None:
    """Heterogeneous batch (``model: ${item.model}``) cost surfaces through
    actually-paid, NOT projections.

    Phase 4 split: heterogeneous rows are excluded from projections (we
    can't price them as one model). Their actually-paid cost still surfaces
    via ``compute_actually_paid`` — the row's ``cost_usd`` was recorded by
    the trace at write-time, summing it via the row fallback (or via
    ``TraceTree.total_cost`` when a tree is provided) yields the correct
    figure.
    """
    het = _row_with_cost(
        node_path="batch-call",
        model="",
        cost_usd=0.0042,
        model_is_heterogeneous=True,
    )
    # Heterogeneous excluded from projections (no priced model to project).
    projections = compute_projections([het], output_tokens_by_node={"batch-call": None}, ttl=None)
    assert projections.no_cache_hypothetical_usd is None
    assert projections.unavailable_models == ()  # Empty model name doesn't count as unavailable.

    # Actually-paid surfaces the recorded cost.
    actually_paid = compute_actually_paid([het])
    assert actually_paid.total_usd == 0.0042
    assert actually_paid.tier == "trace"


def test_actually_paid_returns_unavailable_when_no_rows_have_cost_usd() -> None:
    """Greenfield (no trace) → row.cost_usd is None on every row → fallback
    reports ``(None, "unavailable")``."""
    row = _row(input_tokens=1000)  # No cost_usd — greenfield row.
    actually_paid = compute_actually_paid([row])
    assert actually_paid.total_usd is None
    assert actually_paid.tier == "unavailable"


def test_heterogeneous_rows_excluded_from_priced_projections() -> None:
    """Defensive guard: ``_partition_priced_rows`` excludes heterogeneous rows
    BEFORE the pricing lookup runs. Without the guard, ``model = ""`` flows
    into ``get_model_pricing`` which would either return None (still safe)
    or — if a future provider regression maps "" to some default — silently
    fabricate a price for a row whose model genuinely varies per batch item.
    """
    het = _row_with_cost(
        node_path="batch-call",
        model="",
        cost_usd=0.0042,
        model_is_heterogeneous=True,
    )
    homogeneous = _row(node_path="other", model="anthropic/claude-sonnet-4-5")
    projections = compute_projections(
        [het, homogeneous],
        output_tokens_by_node={"batch-call": 100, "other": 100},
    )
    # Heterogeneous excluded; only the homogeneous row contributes.
    assert projections.no_cache_hypothetical_usd is not None
    # Empty model name MUST NOT register as an "unavailable model" — the
    # heterogeneous skip fires before the pricing lookup.
    assert "" not in projections.unavailable_models


def test_heterogeneous_projection_exclusion_preserves_actual_cost() -> None:
    """Projection coverage is explicit when actual cost has a row projections skip."""
    het = _row_with_cost(
        node_path="batch-call",
        model="",
        cost_usd=0.0042,
        model_is_heterogeneous=True,
    )
    homogeneous = _row(node_path="other", model="anthropic/claude-sonnet-4-5")

    projections = compute_projections(
        [het, homogeneous],
        output_tokens_by_node={"batch-call": 100, "other": 100},
    )

    assert projections.no_cache_hypothetical_usd is not None
    assert projections.partial is True
    assert projections.absolute_exclusions == (
        ProjectionExclusion(
            workflow_path=None,
            node_path="batch-call",
            reason="heterogeneous_model",
            actual_cost_usd=0.0042,
        ),
    )


def test_missing_output_tokens_are_projection_exclusions() -> None:
    row = _row(node_path="missing-output", model="anthropic/claude-sonnet-4-5")

    projections = compute_projections([row], output_tokens_by_node={"missing-output": None})

    assert projections.no_cache_hypothetical_usd is None
    assert projections.absolute_exclusions == (
        ProjectionExclusion(
            workflow_path=None,
            node_path="missing-output",
            reason="missing_output_tokens",
            actual_cost_usd=None,
        ),
    )


def test_unpriced_models_are_projection_exclusions_and_unavailable_models() -> None:
    row = _row_with_cost(node_path="local", model="ollama/llama3.2:8b", cost_usd=0.01)

    projections = compute_projections([row], output_tokens_by_node={"local": 500})

    assert projections.no_cache_hypothetical_usd is None
    assert projections.unavailable_models == ("ollama/llama3.2:8b",)
    assert projections.absolute_exclusions == (
        ProjectionExclusion(
            workflow_path=None,
            node_path="local",
            reason="unpriced_model",
            actual_cost_usd=0.01,
        ),
    )


def test_unresolved_models_are_projection_exclusions_without_unavailable_model_name() -> None:
    row = _row_with_cost(node_path="no-model", model="", cost_usd=0.01)

    projections = compute_projections([row], output_tokens_by_node={"no-model": 500})

    assert projections.no_cache_hypothetical_usd is None
    assert projections.unavailable_models == ()
    assert projections.absolute_exclusions == (
        ProjectionExclusion(
            workflow_path=None,
            node_path="no-model",
            reason="unresolved_model",
            actual_cost_usd=0.01,
        ),
    )


# ---------------------------------------------------------------------------
# AnalysisContext.cost_usd_for_node — walker semantics (Tests 5, 6, 7).
# ---------------------------------------------------------------------------


def test_cost_usd_for_node_treats_cached_event_as_zero_not_unavailable() -> None:
    """Test 5 — Cached events contribute 0.0 (NOT unavailable).

    A workflow rerun within TTL produces a cached event (``cached: True``,
    no ``llm_call``). The agent paid $0 for that node. Returning
    ``(None, "unavailable")`` would force the recompute fallback to
    fabricate a fictional cost based on tokens x rate.
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
    ctx = AnalysisContext.build(workflow_ir={}, trace_data=trace)
    cost, source = ctx.cost_usd_for_node("cached-node")
    assert cost == 0.0
    assert source == "trace"


def test_cost_usd_for_node_does_not_descend_into_sub_workflow_events() -> None:
    """Test 6 — Sub-workflow scoping.

    Track A scopes recorded cost to the focal node — sub-workflow LLM
    nodes have their own analyze-cache invocation. Including
    sub_workflow_events in the parent's cost would double-count + leak
    sub-workflow cost into parent attribution.
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
    ctx = AnalysisContext.build(workflow_ir={}, trace_data=trace)
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
    ctx = AnalysisContext.build(workflow_ir={}, trace_data=trace)
    cost, source = ctx.cost_usd_for_node("batch-mixed")
    assert cost == 0.005  # Sum of priced leaves only.
    assert source == "trace_partial"
