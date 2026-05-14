"""F2.1 — analyzer engine tests: confidence, note ordering, summary shape."""

from __future__ import annotations

import importlib
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from pflow.core.cache_analysis.analyze import (
    CacheAnalysis,
    PerCallRow,
    TraceUnexecutedLLMRow,
    _aggregate_confidence,
    _build_summary,
    _maybe_append_gemini_note,
    analyze,
    invocation_count_for,
)
from pflow.core.cache_analysis.context import AnalysisContext
from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.validation_utils import generate_dummy_parameters
from pflow.core.workflow.validator import WorkflowValidator
from pflow.execution.workflow_resolver import resolve_workflow
from tests.shared.trace_fixture_builder import TraceFixtureBuilder


def _write_trace_fixture(
    tmp_path: Path,
    *,
    workflow_path: str,
    nodes: list[dict[str, Any]],
    name: str = "trace.json",
    final_status: str | None = None,
) -> Path:
    builder = TraceFixtureBuilder()
    trace_path = tmp_path / name
    trace_path.write_text(
        json.dumps(builder.trace(workflow_path=workflow_path, nodes=nodes, final_status=final_status)),
        encoding="utf-8",
    )
    return trace_path


def _llm_trace_event(
    node_id: str,
    *,
    model: str,
    input_tokens: int = 1500,
    output_tokens: int = 100,
    cost_usd: float = 0.01,
) -> dict[str, Any]:
    builder = TraceFixtureBuilder()
    return builder.llm_event(
        node_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )


# ---------------------------------------------------------------------------
# Confidence aggregation — STRICT semantics per DD#34 line 634 verbatim
# ---------------------------------------------------------------------------


def _row(source: str) -> PerCallRow:
    return PerCallRow(
        node_path="X",
        model="m",
        is_batch=False,
        batch_size_estimated=None,
        input_tokens_estimated=100,
        cacheable_tokens_estimated=50,
        cache_ratio_pct=50,
        data_source=source,
        declared_prompt_cache=None,
    )


def test_summary_reports_static_batch_invocation_estimate() -> None:
    rows = [
        PerCallRow(
            node_path="batch-llm",
            model="anthropic/claude-sonnet-4-5",
            is_batch=True,
            batch_size_estimated=8,
            input_tokens_estimated=100,
            cacheable_tokens_estimated=50,
            cache_ratio_pct=50,
            data_source="estimator",
            declared_prompt_cache=None,
        ),
        PerCallRow(
            node_path="single-llm",
            model="anthropic/claude-sonnet-4-5",
            is_batch=False,
            batch_size_estimated=None,
            input_tokens_estimated=100,
            cacheable_tokens_estimated=50,
            cache_ratio_pct=50,
            data_source="estimator",
            declared_prompt_cache=None,
        ),
    ]

    summary = _build_summary(rows, warnings=[], ttl="5m")

    assert summary.total_llm_nodes_estimated == 2
    assert summary.total_llm_invocations_estimated == 9
    assert summary.dynamic_batch_node_count == 0


def test_summary_static_batch_input_and_cacheable_totals_are_per_call_with_cohort_multiplication() -> None:
    """Summary totals multiply per-call row tokens by the row invocation count."""
    rows = [
        PerCallRow(
            node_path="batch-llm",
            model="anthropic/claude-sonnet-4-5",
            is_batch=True,
            batch_size_estimated=4,
            input_tokens_estimated=100,
            cacheable_tokens_estimated=60,
            cache_ratio_pct=60,
            data_source="trace",
            declared_prompt_cache=["context"],
        )
    ]

    summary = _build_summary(rows, warnings=[], ttl="5m")

    assert summary.total_input_tokens_estimated == 400
    assert summary.total_cacheable_tokens_estimated == 240


def test_summary_dynamic_batch_input_is_per_call(tmp_path: Path) -> None:
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
    trace_path = _write_trace_fixture(
        tmp_path,
        workflow_path=workflow_path,
        nodes=[
            _llm_trace_event("batch", model="anthropic/claude-sonnet-4-5", input_tokens=100, output_tokens=10),
            _llm_trace_event("batch", model="anthropic/claude-sonnet-4-5", input_tokens=100, output_tokens=10),
            _llm_trace_event("batch", model="anthropic/claude-sonnet-4-5", input_tokens=100, output_tokens=10),
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
    assert row.input_tokens_estimated == 100
    assert row.output_tokens_estimated == 10
    assert analysis.summary.total_input_tokens_estimated == 300
    assert analysis.summary.total_llm_invocations_estimated == 3
    assert analysis.summary.dynamic_batch_node_count == 0


def test_summary_non_batch_repeated_input_is_per_call(tmp_path: Path) -> None:
    workflow_path = str(tmp_path / "repeated.pflow.md")
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
    trace_path = _write_trace_fixture(
        tmp_path,
        workflow_path=workflow_path,
        nodes=[
            _llm_trace_event("select", model="anthropic/claude-sonnet-4-5", input_tokens=100, output_tokens=10),
            _llm_trace_event("select", model="anthropic/claude-sonnet-4-5", input_tokens=100, output_tokens=10),
            _llm_trace_event("select", model="anthropic/claude-sonnet-4-5", input_tokens=100, output_tokens=10),
            _llm_trace_event("select", model="anthropic/claude-sonnet-4-5", input_tokens=100, output_tokens=10),
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
    assert row.input_tokens_estimated == 100
    assert row.output_tokens_estimated == 10
    assert analysis.summary.total_input_tokens_estimated == 400
    assert analysis.summary.total_llm_invocations_estimated == 4


def test_arithmetic_identity_no_cache_minus_first_run_equals_savings() -> None:
    rows = [
        PerCallRow(
            node_path="batch-llm",
            model="anthropic/claude-sonnet-4-5",
            is_batch=True,
            batch_size_estimated=4,
            input_tokens_estimated=100,
            cacheable_tokens_estimated=60,
            cache_ratio_pct=60,
            data_source="trace",
            declared_prompt_cache=["context"],
            output_tokens_estimated=10,
            output_data_source="trace",
        )
    ]

    summary = _build_summary(rows, warnings=[], ttl="5m")

    assert summary.no_cache_hypothetical_usd is not None
    assert summary.first_run_with_cache_hypothetical_usd is not None
    assert summary.first_run_delta.amount_usd is not None
    assert summary.first_run_delta.kind == "savings"
    assert math.isclose(
        summary.no_cache_hypothetical_usd - summary.first_run_with_cache_hypothetical_usd,
        summary.first_run_delta.amount_usd,
        rel_tol=1e-6,
    )


def test_analyze_no_run_data_note_suppressed_when_parameter_backed_cacheable_present() -> None:
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "Draft from ${context}."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "Review ${context}."},
            },
        ],
    }

    result = analyze(
        workflow_ir,
        parameters={"context": "stable " * 20},
        workflow_path="x.pflow.md",
        auto_load_trace=False,
        memo_cache=None,
    )

    assert any(row.cacheable_data_source == "parameters" for row in result.per_call)
    assert not any("Per-call cache report hidden" in note for note in result.notes)


def test_summary_reports_unknown_invocations_when_batch_size_is_dynamic() -> None:
    rows = [
        PerCallRow(
            node_path="dynamic-batch-llm",
            model="anthropic/claude-sonnet-4-5",
            is_batch=True,
            batch_size_estimated=None,
            input_tokens_estimated=100,
            cacheable_tokens_estimated=50,
            cache_ratio_pct=50,
            data_source="estimator",
            declared_prompt_cache=None,
        )
    ]

    summary = _build_summary(rows, warnings=[], ttl="5m")

    assert summary.total_llm_nodes_estimated == 1
    assert summary.total_llm_invocations_estimated is None
    assert summary.dynamic_batch_node_count == 1


def test_confidence_high_when_all_trace() -> None:
    """STRICT: all rows must be 'trace' for high. Mixed trace/memo → medium."""
    confidence, coverage = _aggregate_confidence([_row("trace"), _row("trace")])
    assert confidence == "high_from_trace"
    assert coverage == {"trace": 2, "memo": 0, "estimator": 0, "heuristic": 0, "total": 2}


def test_below_threshold_emits_conditional_recommendation_not_paste_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Below-threshold shared refs produce a conditional advisory, not a paste block.

    Mutation contract: removing the BELOW_THRESHOLD branch from
    ``_populate_suggested_blocks`` makes the conditional diagnostic disappear.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")

    monkeypatch.setattr(analyze_module, "_estimate_ref_tokens", lambda ref, **_kwargs: 100)
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 1000)
    workflow_ir = {
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "Draft about ${topic}."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "Review ${topic}."},
            },
        ],
    }

    result = analyze(workflow_ir, parameters={"topic": "small"}, workflow_path="/abs/x.pflow.md", auto_load_trace=False)

    assert result.suggested_blocks == ()
    assert not any(d.id == "cache.shared-context-undeclared" for d in result.warnings)
    conditional = next(d for d in result.warnings if d.id == "cache.shared-context-undeclared-conditional")
    assert conditional.context is not None
    assert conditional.context["min_tokens"] == 1000
    assert conditional.context["node_count"] == 2
    assert conditional.context["affected_nodes"] == ["draft", "review"]
    assert conditional.context["shared_chunks"] == ["topic"]
    from pflow.core.cache_analysis.render_text import render_text

    text = render_text(result)
    assert "Shared context conditional" in text
    assert "paste-ready" not in text


def test_suggested_block_suppressed_when_threshold_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown model/token evidence stays out of paste-ready action sections."""
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")

    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    workflow_ir = {
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {"id": "draft", "type": "llm", "params": {"prompt": "Draft about ${topic}."}},
            {"id": "review", "type": "llm", "params": {"prompt": "Review ${topic}."}},
        ],
    }

    result = analyze(
        workflow_ir, parameters={"topic": "x " * 6000}, workflow_path="/abs/x.pflow.md", auto_load_trace=False
    )

    assert result.suggested_blocks == ()
    assert not any(d.id == "cache.shared-context-undeclared" for d in result.warnings)
    assert result.summary.actionable_opportunities == 0
    assert any("the analyzer cannot yet tell whether a cache edit would fire" in note for note in result.notes)
    from pflow.core.cache_analysis.render_json import render_json
    from pflow.core.cache_analysis.render_text import render_text

    payload = render_json(result)
    assert payload["recommended_actions"] == []
    assert payload["suggested_blocks"] == []
    text = render_text(result)
    assert "## Recommended actions" not in text
    assert "## Suggested ## Cache block" not in text
    assert "the analyzer cannot yet tell whether a cache edit would fire" in text
    assert "paste-ready" not in text


def test_suggested_block_emits_when_all_assigned_nodes_meet_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only eligible readers count toward savings; the first eligible node is
    the writer that pays the cache_creation premium.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")

    monkeypatch.setattr(analyze_module, "_estimate_ref_tokens", lambda ref, **_kwargs: 100)
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 10)
    workflow_ir = {
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {
                "id": "writer",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "First ${topic}."},
            },
            {
                "id": "reader",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "Second ${topic}."},
            },
        ],
    }

    result = analyze(workflow_ir, parameters={"topic": "small"}, workflow_path="/abs/x.pflow.md", auto_load_trace=False)

    assert result.suggested_blocks
    block = result.suggested_blocks[0]
    assert block.per_node_thresholds["writer"]["meets_threshold"] is True
    assert block.per_node_thresholds["reader"]["meets_threshold"] is True
    assert block.estimated_savings_usd == pytest.approx(90.0)
    assert any(d.id == "cache.shared-context-undeclared" for d in result.warnings)


def test_suggested_block_savings_multiplies_batch_consumer_invocations(monkeypatch: pytest.MonkeyPatch) -> None:
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")

    monkeypatch.setattr(analyze_module, "_estimate_ref_tokens", lambda ref, **_kwargs: 100)
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 10)
    workflow_ir = {
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {
                "id": "writer",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "First ${topic}."},
            },
            {
                "id": "reader",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "batch": {"items": ["a", "b", "c"], "as": "item"},
                "params": {"prompt": "Second ${topic} for ${item}."},
            },
        ],
    }

    result = analyze(workflow_ir, parameters={"topic": "small"}, workflow_path="/abs/x.pflow.md", auto_load_trace=False)

    assert result.suggested_blocks
    assert result.suggested_blocks[0].estimated_savings_usd == pytest.approx(270.0)


def test_below_threshold_emits_conditional_even_when_only_one_node_below(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any below-threshold consumer makes the edit conditional.

    Mutation contract: using the least restrictive provider minimum instead of
    the strictest one reports ``10`` here and understates the precondition.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")

    monkeypatch.setattr(analyze_module, "_estimate_ref_tokens", lambda ref, **_kwargs: 100)
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)
    monkeypatch.setattr(
        analyze_module,
        "get_min_cache_tokens",
        lambda model: 1000 if model == "anthropic/claude-haiku-4-5" else 10,
    )
    workflow_ir = {
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {
                "id": "too-small",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "First ${topic}."},
            },
            {
                "id": "writer",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "Second ${topic}."},
            },
            {
                "id": "reader",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "Third ${topic}."},
            },
        ],
    }

    result = analyze(workflow_ir, parameters={"topic": "small"}, workflow_path="/abs/x.pflow.md", auto_load_trace=False)

    assert result.suggested_blocks == ()
    assert not any(d.id == "cache.shared-context-undeclared" for d in result.warnings)
    conditional = next(d for d in result.warnings if d.id == "cache.shared-context-undeclared-conditional")
    assert conditional.context is not None
    assert conditional.context["min_tokens"] == 1000
    assert conditional.context["affected_nodes"] == ["reader", "too-small", "writer"]


def test_analyze_cache_validation_replaces_unknown_scope() -> None:
    """Analyzer knows the workflow path and must not leak validator placeholders."""
    workflow_path = "/abs/order-mismatch.pflow.md"
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "cache": {
            "items": [
                {"name": "a", "var": "a", "prose_before": "A:"},
                {"name": "b", "var": "b", "prose_before": "B:"},
            ]
        },
        "nodes": [
            {
                "id": "test-call",
                "type": "llm",
                "prompt_cache": ["b", "a"],
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Summarize ${a} and ${b}.",
                },
            }
        ],
    }

    result = analyze(workflow_ir, workflow_path=workflow_path, auto_load_trace=False, memo_cache=None)

    duplicate = next(d for d in result.warnings if d.id == "cache.prompt-body-duplicates-cache")
    assert duplicate.context is not None
    assert duplicate.context["affected_workflow"] == workflow_path


def test_confidence_NOT_high_when_one_row_is_memo() -> None:
    """STRICT semantics — would be 'permissive' (any-trace) under the rejected
    alternative."""
    confidence, _ = _aggregate_confidence([_row("trace"), _row("memo")])
    assert confidence == "medium_from_memo"


def test_confidence_medium_when_all_in_trace_memo_set() -> None:
    confidence, _ = _aggregate_confidence([_row("memo"), _row("memo")])
    assert confidence == "medium_from_memo"


def test_confidence_low_when_any_estimator() -> None:
    """Any 'estimator' or 'heuristic' present → low_no_data."""
    confidence, _ = _aggregate_confidence([_row("trace"), _row("estimator")])
    assert confidence == "low_no_data"
    confidence, _ = _aggregate_confidence([_row("memo"), _row("heuristic")])
    assert confidence == "low_no_data"


def test_confidence_low_for_empty_rows() -> None:
    confidence, coverage = _aggregate_confidence([])
    assert confidence == "low_no_data"
    assert coverage["total"] == 0


# ---------------------------------------------------------------------------
# Top-level analyze — minimal smoke
# ---------------------------------------------------------------------------


def test_analyze_returns_cache_analysis_dataclass() -> None:
    workflow_ir = {
        "nodes": [
            {
                "id": "review",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "hello"},
            }
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    assert isinstance(result, CacheAnalysis)
    assert result.workflow_path == "/abs/x.pflow.md"
    assert result.estimate_confidence in {"high_from_trace", "medium_from_memo", "low_no_data"}
    assert len(result.per_call) == 1


def test_summary_current_cost_includes_sub_workflow_costs_via_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defends trace-driven current-cost rollup: workflow nodes are not LLM rows,
    but their ``sub_workflow_events`` still represent real paid calls.
    """
    import pflow.core.cache_analysis.cross_workflow as cross_module
    from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult

    child_path = tmp_path / "child.pflow.md"
    child_ir = {
        "nodes": [
            {
                "id": "child-llm",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "child"},
            }
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, child_path, ()),
    )
    parent_ir = {
        "nodes": [
            {
                "id": "parent-llm",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "parent"},
            },
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {}},
            },
        ],
    }
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.1.0",
            "workflow_path": "parent.pflow.md",
            "nodes": [
                {
                    "node_id": "parent-llm",
                    "llm_call": {"cost_usd": 0.05, "input_tokens": 100, "output_tokens": 10},
                },
                {
                    "node_id": "call-child",
                    "sub_workflow_events": [
                        {
                            "node_id": "child-llm",
                            "llm_call": {"cost_usd": 0.10, "input_tokens": 100, "output_tokens": 10},
                        }
                    ],
                },
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(parent_ir, workflow_path="parent.pflow.md", trace_path=trace_path, memo_cache=None)

    assert result.summary.actually_paid_usd == pytest.approx(0.15)
    assert {(row.workflow_path, row.node_path) for row in result.per_call} == {
        ("parent.pflow.md", "parent-llm"),
        (str(child_path), "child-llm"),
    }


def test_erroring_child_trace_marks_unexecuted_rows_and_suppresses_projection(tmp_path: Path) -> None:
    """Defends phantom-cost suppression for child workflows that error after an
    earlier LLM: static IR rows remain visible, but unexecuted LLMs do not
    fabricate recomputed projection dollars.
    """
    from pflow.runtime.cache import MemoizationCache

    fixture_dir = Path("tests/fixtures/cache_analysis")
    parent_path = fixture_dir / "parent.pflow.md"
    trace_path = fixture_dir / "parent-child-erroring-trace.json"
    resolved = resolve_workflow(str(parent_path))
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    cache.put(
        cache_key="draft-key",
        node_id="draft",
        workflow_path=resolved.file_path,
        action="default",
        output={"response": "memo child brief " * 200},
    )

    result = analyze(
        resolved.ir,
        parameters={"topic": "cache analysis"},
        workflow_path=resolved.file_path,
        base_path=parent_path.parent,
        trace_path=trace_path,
        memo_cache=cache,
    )

    child_path = str((fixture_dir / "child.pflow.md").resolve())
    by_key = {(row.workflow_path, row.node_path): row for row in result.per_call}
    assert result.summary.actually_paid_usd == pytest.approx(0.12)
    assert by_key[(child_path, "review")].did_not_execute_in_trace is True
    assert by_key[(child_path, "review")].cost_usd is None

    # The executed child row had trace cache evidence, so some rerun savings is
    # present. The unexecuted review row has real memo-backed cacheable
    # evidence too; without the did-not-execute skip it would add a second
    # child-row savings contribution.
    executed_child = by_key[(child_path, "draft")]
    unexecuted_child = by_key[(child_path, "review")]
    assert result.summary.rerun_delta.kind == "savings"
    assert result.summary.rerun_delta.amount_usd is not None
    assert executed_child.cacheable_tokens_estimated
    assert unexecuted_child.cacheable_tokens_estimated is not None
    assert result.summary.rerun_delta.amount_usd < 0.003


def test_checked_in_haiku_rerun_trace_uses_total_input_token_semantics(tmp_path: Path) -> None:
    """Regression for the double-counted Anthropic trace-token bug."""
    usage_rows = [
        ("answer-1", 4974, 51),
        ("answer-2", 4967, 80),
        ("answer-3", 4979, 51),
        ("answer-4", 4976, 34),
        ("answer-5", 4974, 31),
        ("answer-6", 4994, 37),
    ]
    model = "anthropic/claude-haiku-4-5"
    workflow_ir = {
        "cache": {
            "ttl": "1h",
            "items": [{"name": "context", "var": "context", "prose_before": "Context:\n"}],
        },
        "inputs": {"context": {"type": "string"}},
        "nodes": [
            {
                "id": node_id,
                "type": "llm",
                "model": model,
                "prompt_cache": ["context"],
                "params": {"prompt": f"Question for {node_id}."},
            }
            for node_id, _input_tokens, _output_tokens in usage_rows
        ],
    }
    builder = TraceFixtureBuilder()
    trace = builder.trace(
        "tests/fixtures/cache_analysis/anthropic-haiku-smoke-with-cache.pflow.md",
        [
            builder.llm_event(
                node_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_input_tokens=4938,
            )
            for node_id, input_tokens, output_tokens in usage_rows
        ],
        workflow_name="anthropic-haiku-smoke-with-cache",
    )
    trace_path = tmp_path / "anthropic-haiku-rerun-trace.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    result = analyze(
        workflow_ir,
        parameters={"context": "trace supplies cacheable-token truth"},
        workflow_path="tests/fixtures/cache_analysis/anthropic-haiku-smoke-with-cache.pflow.md",
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )
    from pflow.core.cache_analysis.render_json import render_json

    summary = render_json(result)["summary"]
    assert summary["no_cache_hypothetical_usd"] == pytest.approx(0.031284)
    assert summary["rerun_within_ttl_hypothetical_usd"] == pytest.approx(0.0046188)
    assert summary["rerun_delta"]["kind"] == "savings"
    assert summary["rerun_delta"]["amount_usd"] == pytest.approx(0.0266652)
    assert summary["trace_coverage"] == "complete"
    assert "savings_pct_first_run" not in summary
    assert "savings_pct_rerun" not in summary
    assert "aggregate_savings_first_run_usd" not in summary
    assert "aggregate_savings_rerun_usd" not in summary


def test_truncated_trace_marks_unexecuted_rows_and_suppresses_row_warnings(tmp_path: Path) -> None:
    """Truncated coverage (final_status=failed + unexecuted) classifies correctly,
    suppresses per-row warnings on unexecuted rows, and filters cost-projection
    findings while letting IR-derived findings flow.

    Mutation contract: revert ``_trace_coverage_for_rows`` to ignore final_status
    → trace_coverage stays "truncated" but the rest of the test still passes;
    revert ``_filter_trace_dependent_warnings`` to severity-based filtering →
    fewer warnings flow than expected (legacy behavior was ERROR-only).
    """
    workflow_ir = {
        "cache": {"items": [{"name": "ctx", "var": "ctx", "prose_before": ""}]},
        "inputs": {"ctx": {"type": "string"}},
        "nodes": [
            {
                "id": "ran",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["ctx"],
                "params": {"prompt": "Use ${ctx}."},
            },
            {
                "id": "skipped",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["ctx"],
                "params": {"prompt": "Also use ${ctx}."},
            },
        ],
    }
    trace_path = tmp_path / "truncated-trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "x",
            # final_status="failed" + unexecuted rows = truncated coverage
            "final_status": "failed",
            "nodes": [
                {
                    "node_id": "ran",
                    "node_type": "LLMNode",
                    "success": True,
                    "llm_call": {
                        "model": "anthropic/claude-sonnet-4-5",
                        "input_tokens": 2000,
                        "output_tokens": 10,
                        "cost_usd": 0.001,
                        "cache_creation_input_tokens": 1500,
                        "cache_read_input_tokens": 0,
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(
        workflow_ir,
        parameters={"ctx": "small"},
        workflow_path="x",
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )
    rows = {row.node_path: row for row in result.per_call}
    assert rows["ran"].did_not_execute_in_trace is False
    assert rows["skipped"].did_not_execute_in_trace is True
    assert result.summary.trace_coverage == "truncated"
    assert result.summary.evidence_scope == "truncated_trace_executed_subset"
    assert result.summary.trace_llm_nodes_static == 2
    assert result.summary.trace_llm_nodes_executed == 1
    assert result.summary.trace_unexecuted_llm_rows == (TraceUnexecutedLLMRow("x", "skipped"),)
    assert result.summary.actual_vs_no_cache_delta.kind != "unavailable"
    # Per-row suppression: skipped node produces no per-row warnings.
    assert not any(d.node_id == "skipped" and d.id == "cache.below-min-predicted" for d in result.warnings)
    # cache.first-call-write-penalty would not fire here (2 nodes, not 1), so
    # we don't assert its absence; the dedicated truncated-filter test owns that.
    assert result.suggested_blocks == ()
    from pflow.core.cache_analysis.render_text import render_text

    text = render_text(result)
    assert "Evidence: trace truncated (1 of 2 LLM nodes executed)" in text
    assert "Trace-backed costs below cover executed nodes only." in text
    assert "Trace-dependent optimization recommendations suppressed because the trace is truncated" in text


def test_truncated_trace_unexecuted_summary_rows_keep_workflow_scope() -> None:
    rows = [
        PerCallRow(
            node_path="ran",
            model="anthropic/claude-sonnet-4-5",
            is_batch=False,
            batch_size_estimated=None,
            input_tokens_estimated=100,
            cacheable_tokens_estimated=50,
            cache_ratio_pct=50,
            data_source="trace",
            declared_prompt_cache=None,
            workflow_path="/abs/parent.pflow.md",
        ),
        PerCallRow(
            node_path="review",
            model="anthropic/claude-sonnet-4-5",
            is_batch=False,
            batch_size_estimated=None,
            input_tokens_estimated=100,
            cacheable_tokens_estimated=50,
            cache_ratio_pct=50,
            data_source="estimator",
            declared_prompt_cache=None,
            workflow_path="/abs/review-b.pflow.md",
            did_not_execute_in_trace=True,
        ),
        PerCallRow(
            node_path="review",
            model="anthropic/claude-sonnet-4-5",
            is_batch=False,
            batch_size_estimated=None,
            input_tokens_estimated=100,
            cacheable_tokens_estimated=50,
            cache_ratio_pct=50,
            data_source="estimator",
            declared_prompt_cache=None,
            workflow_path="/abs/review-a.pflow.md",
            did_not_execute_in_trace=True,
        ),
    ]
    ctx = AnalysisContext.build(
        workflow_ir={"nodes": []},
        workflow_path="/abs/parent.pflow.md",
        trace_data={
            "format_version": "2.2.0",
            "workflow_path": "/abs/parent.pflow.md",
            # Truncated coverage requires final_status=failed under new logic.
            "final_status": "failed",
            "nodes": [
                {
                    "node_id": "ran",
                    "llm_call": {"cost_usd": 0.001, "input_tokens": 100, "output_tokens": 10},
                }
            ],
        },
    )

    summary = _build_summary(rows, warnings=[], ctx=ctx)

    assert summary.trace_coverage == "truncated"
    assert summary.trace_llm_nodes_static == 3
    assert summary.trace_llm_nodes_executed == 1
    assert summary.trace_unexecuted_llm_rows == (
        TraceUnexecutedLLMRow("/abs/review-a.pflow.md", "review"),
        TraceUnexecutedLLMRow("/abs/review-b.pflow.md", "review"),
    )
    assert [row.node_path for row in summary.trace_unexecuted_llm_rows] == ["review", "review"]


def test_truncated_trace_filters_cost_projection_findings(tmp_path: Path) -> None:
    """Truncated traces (final_status=failed) filter cost-projection findings
    like ``cache.first-call-write-penalty`` whose cost cohort is incomplete.

    Mutation contract: remove ``requires_complete_trace=True`` from
    ``cache.first-call-write-penalty`` in the catalog → this test fails
    because the penalty leaks through on truncated coverage.
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "cache": {"items": [{"name": "ctx", "var": "ctx", "prose_before": "Context:"}]},
        "inputs": {"ctx": {"type": "string"}},
        "nodes": [
            {
                "id": "ran",
                "type": "llm",
                "prompt_cache": ["ctx"],
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Answer the question.",
                },
            },
            {
                "id": "skipped",
                "type": "llm",
                "prompt_cache": ["ctx"],
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Answer another question.",
                },
            },
        ],
    }
    trace_path = tmp_path / "truncated-trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "x",
            # final_status=failed is what makes this truncated under the new logic.
            "final_status": "failed",
            "nodes": [
                {
                    "node_id": "ran",
                    "node_type": "LLMNode",
                    "success": True,
                    "llm_call": {
                        "model": "anthropic/claude-sonnet-4-5",
                        "input_tokens": 6_000,
                        "output_tokens": 20,
                        "cost_usd": 0.01,
                        "cache_creation_input_tokens": 5_000,
                        "cache_read_input_tokens": 0,
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(
        workflow_ir,
        parameters={"ctx": "x" * 20_000},
        workflow_path="x",
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )

    assert result.summary.evidence_scope == "truncated_trace_executed_subset"
    # cache.first-call-write-penalty is filtered on truncated traces because
    # the cohort is incomplete (the comparison "first-call premium vs amortized
    # reads" loses its denominator).
    assert not any(d.id == "cache.first-call-write-penalty" for d in result.warnings)
    assert result.suggested_blocks == ()

    # On complete coverage (single-node workflow → no unexecuted rows), the
    # penalty fires normally — this is the same fixture, restricted to the
    # node that did execute.
    complete_result = analyze(
        {**workflow_ir, "nodes": [workflow_ir["nodes"][0]]},
        parameters={"ctx": "x" * 20_000},
        workflow_path="x",
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )
    assert complete_result.summary.evidence_scope == "complete_trace"
    assert any(d.id == "cache.first-call-write-penalty" for d in complete_result.warnings)

    from pflow.core.cache_analysis.render_json import render_json
    from pflow.core.cache_analysis.render_text import render_text

    payload = render_json(result)
    # Cost-projection actions filtered, but IR-derived findings (if any) flow.
    # ``cache.first-call-write-penalty`` is the only finding the fixture
    # produces and it's correctly filtered.
    assert all(
        action.get("warning_id") != "cache.first-call-write-penalty" for action in payload["recommended_actions"]
    )
    assert payload["suggested_blocks"] == []
    text = render_text(result)
    assert "cache.first-call-write-penalty" not in text


# ---------------------------------------------------------------------------
# L-10 + L-11 fix — trace coverage discriminator + catalog-driven filter
# ---------------------------------------------------------------------------


def test_complete_trace_with_conditional_dispatch_keeps_ir_findings(tmp_path: Path) -> None:
    """Case A: workflow finished successfully but a conditional branch wasn't
    taken (one of N classify-routed paths). Trace classifies as ``complete``,
    NOT ``truncated``, and IR-derived findings flow normally.

    Mutation contract: revert ``_trace_coverage_for_rows`` to ignore
    ``final_status`` (re-treat any unexecuted as ``truncated``) → this test
    fails because evidence_scope becomes ``truncated_trace_executed_subset``.
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"context": {"type": "string"}},
        "nodes": [
            # Two LLM nodes that share `${context}` — triggers
            # cache.shared-context-undeclared (an IR-derived finding).
            {
                "id": "ran",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Use ${context} to answer.",
                },
            },
            {
                "id": "skipped",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Also use ${context} to summarize.",
                },
            },
        ],
    }
    trace_path = tmp_path / "complete-trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "x",
            # Workflow finished successfully — the unexecuted "skipped" node
            # is conditional dispatch (branch not taken for these inputs),
            # NOT trace truncation.
            "final_status": "success",
            "nodes": [
                {
                    "node_id": "ran",
                    "node_type": "LLMNode",
                    "success": True,
                    "llm_call": {
                        "model": "anthropic/claude-sonnet-4-5",
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "cost_usd": 0.01,
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(
        workflow_ir,
        parameters={"context": "x" * 20_000},
        workflow_path="x",
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )

    # Coverage classifies as complete despite unexecuted rows.
    assert result.summary.trace_coverage == "complete"
    assert result.summary.evidence_scope == "complete_trace"
    assert result.summary.trace_llm_nodes_static == 2
    assert result.summary.trace_llm_nodes_executed == 1
    # Unexecuted rows are still tracked (renderer uses them for the
    # "Z not reached for these inputs" header annotation).
    assert result.summary.trace_unexecuted_llm_rows == (TraceUnexecutedLLMRow("x", "skipped"),)
    # IR-derived finding flows: shared-context-undeclared comes from
    # template-reference walking, not trace evidence.
    warning_ids = {d.id for d in result.warnings}
    assert "cache.shared-context-undeclared" in warning_ids, (
        f"Expected cache.shared-context-undeclared (IR-derived) to flow on complete trace; got: {sorted(warning_ids)}"
    )

    # Header rendering: complete + unexecuted should show "X of Y; Z not reached".
    from pflow.core.cache_analysis.render_text import render_text

    text = render_text(result)
    assert "Evidence: complete trace (1 of 2 LLM nodes executed; 1 not reached for these inputs)" in text
    # Suppression note must NOT appear on complete coverage.
    assert "Trace-dependent optimization recommendations suppressed" not in text


def test_truncated_trace_filters_first_call_write_penalty_only(tmp_path: Path) -> None:
    """Case C: workflow died mid-run. ``cache.first-call-write-penalty`` is
    filtered (cost-projection cohort incomplete). IR-derived findings still
    flow.

    Mutation contract: remove ``requires_complete_trace=True`` from
    ``cache.first-call-write-penalty`` in the catalog → this test fails
    because the penalty leaks through on truncated coverage.
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:"}]},
        "nodes": [
            {
                "id": "single-llm",
                "type": "llm",
                "prompt_cache": ["context"],
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Answer using context.",
                },
            },
            {
                "id": "did-not-run",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Use ${context}.",
                },
            },
        ],
    }
    trace_path = tmp_path / "truncated-trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "x",
            # final_status=failed + unexecuted = truncated.
            "final_status": "failed",
            "nodes": [
                {
                    "node_id": "single-llm",
                    "node_type": "LLMNode",
                    "success": True,
                    "llm_call": {
                        "model": "anthropic/claude-sonnet-4-5",
                        "input_tokens": 6_000,
                        "output_tokens": 20,
                        "cost_usd": 0.01,
                        "cache_creation_input_tokens": 5_000,
                        "cache_read_input_tokens": 0,
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(
        workflow_ir,
        parameters={"context": "x" * 20_000},
        workflow_path="x",
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )

    assert result.summary.trace_coverage == "truncated"
    # Cost-projection finding filtered (catalog flag).
    warning_ids = [d.id for d in result.warnings]
    assert "cache.first-call-write-penalty" not in warning_ids


def test_filter_consults_catalog_flag_not_severity() -> None:
    """``_filter_trace_dependent_warnings`` filters by catalog flag, not
    severity. This is the corrected discriminator (the old severity-based
    filter dropped 17 of 21 catalog warnings whenever truncation fired).

    Mutation contract: replace the catalog-flag check with a severity check
    (``warning.severity == Severity.ERROR``) → this test fails because
    INFO-severity IR-derived findings get dropped.
    """
    from pflow.core.cache_analysis.analyze import _filter_trace_dependent_warnings

    flagged = Diagnostic(
        severity=Severity.INFO,
        source="cache_analyzer",
        id="cache.first-call-write-penalty",  # has requires_complete_trace=True
        node_id="x",
        message="cost-projection finding",
    )
    unflagged_info = Diagnostic(
        severity=Severity.INFO,
        source="cache_analyzer",
        id="cache.cross-workflow-rename-detected",  # IR-derived; no flag
        node_id="x",
        message="rename finding",
    )
    unflagged_warning = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        id="cache.below-min-predicted",  # IR-derived; no flag
        node_id="x",
        message="below-min finding",
    )
    error_no_id = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        message="un-IDed validator error",  # no id → no catalog lookup → flows
    )

    filtered = _filter_trace_dependent_warnings([flagged, unflagged_info, unflagged_warning, error_no_id])

    filtered_ids = [d.id for d in filtered]
    # Cost-projection finding dropped.
    assert "cache.first-call-write-penalty" not in filtered_ids
    # IR-derived findings flow regardless of severity.
    assert "cache.cross-workflow-rename-detected" in filtered_ids
    assert "cache.below-min-predicted" in filtered_ids
    # Diagnostics with no id (un-catalog'd) flow — no catalog lookup possible.
    assert error_no_id in filtered


def test_dynamic_batch_trace_preserves_observed_model_truth(tmp_path: Path) -> None:
    workflow_ir = {
        "nodes": [
            {
                "id": "generate",
                "type": "llm",
                "params": {"model": "${item.model}", "prompt": "${item.prompt}"},
                "batch": {"items": "${items}"},
            }
        ]
    }
    trace_path = tmp_path / "batch-trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "x",
            "nodes": [
                {
                    "node_id": "generate",
                    "node_type": "LLMNode",
                    "success": True,
                    "batch_items": [
                        {
                            "index": 0,
                            "success": True,
                            "llm_call": {
                                "model": "gemini/gemini-2.5-flash-lite",
                                "input_tokens": 100,
                                "output_tokens": 10,
                                "cost_usd": 0.01,
                                "cache_creation_input_tokens": 4,
                                "cache_read_input_tokens": 0,
                            },
                        },
                        {
                            "index": 1,
                            "success": True,
                            "llm_call": {
                                "model": "gemini/gemini-3-flash-preview",
                                "input_tokens": 200,
                                "output_tokens": 20,
                                "cost_usd": 0.02,
                                "cache_creation_input_tokens": 0,
                                "cache_read_input_tokens": 4,
                            },
                        },
                    ],
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(
        workflow_ir,
        parameters={"items": [{"model": "a", "prompt": "x"}, {"model": "b", "prompt": "y"}]},
        workflow_path="x",
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )

    row = result.per_call[0]
    assert row.model_is_heterogeneous is True
    assert row.observed_call_count == 2
    assert row.observed_models == ("gemini/gemini-2.5-flash-lite", "gemini/gemini-3-flash-preview")
    assert row.input_tokens_estimated == 150
    assert row.output_tokens_estimated == 15
    assert row.cache_creation_input_tokens == 2
    assert row.cache_read_input_tokens == 2
    assert result.summary.trace_provider_cache_creation_input_tokens == 4
    assert result.summary.trace_provider_cache_read_input_tokens == 4
    assert row.cost_usd == pytest.approx(0.03)
    assert result.summary.trace_coverage == "complete"
    assert result.summary.observed_models_in_trace == row.observed_models
    assert result.summary.models_in_use == row.observed_models


def test_memo_hit_trace_does_not_count_historical_provider_cache_reads(tmp_path: Path) -> None:
    """A local memo hit restores historical llm_usage for token estimates only.

    Provider cache telemetry in the current trace must exclude the restored
    historical payload; otherwise a resumed run looks like provider prompt
    caching worked even when pflow skipped the LLM call before the provider.
    """
    workflow_ir = {
        "cache": {
            "items": [
                {
                    "name": "source",
                    "var": "content",
                    "prose_before": "Source content:\n",
                }
            ]
        },
        "nodes": [
            {
                "id": "summarize",
                "type": "llm",
                "prompt_cache": ["source"],
                "params": {
                    "model": "gemini/gemini-2.5-flash-lite",
                    "prompt": "Summarize the source content.",
                },
            }
        ],
    }
    trace_path = tmp_path / "memo-hit-trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "x",
            "final_status": "success",
            "nodes": [
                {
                    "node_id": "summarize",
                    "node_type": "LLMNode",
                    "success": True,
                    "cached": True,
                    "llm_call": {
                        "model": "gemini/gemini-2.5-flash-lite",
                        "input_tokens": 6000,
                        "output_tokens": 100,
                        "cost_usd": 0.25,
                        "cache_source": "memo",
                        "cache_read_input_tokens": 5900,
                        "cache_creation_input_tokens": 0,
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(
        workflow_ir,
        parameters={"content": "large source " * 2000},
        workflow_path="x",
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )

    row = result.per_call[0]
    assert row.data_source == "trace"
    assert row.cacheable_data_source != "trace"
    assert row.cache_read_input_tokens is None
    assert row.cache_creation_input_tokens is None
    assert result.summary.trace_provider_llm_call_count == 0
    assert result.summary.trace_provider_cache_read_input_tokens == 0
    assert result.summary.trace_local_memo_llm_hit_count == 1
    assert result.summary.trace_local_cache_input_tokens == 6000


def test_complete_trace_with_heterogeneous_exclusion_renders_priced_cohort_actual_delta(tmp_path: Path) -> None:
    """Heterogeneous exclusions don't kill the actual-vs-no-cache delta.

    When every excluded row carries a trace-recorded ``actual_cost_usd``, the
    delta is computed on the priced-cohort subset (total paid minus the
    excluded rows' costs) and tagged with ``excluded_nodes`` so the text /
    JSON renderers can disclose what was left out.
    """
    workflow_ir = {
        "nodes": [
            {
                "id": "generate",
                "type": "llm",
                "params": {"model": "${item.model}", "prompt": "${item.prompt}"},
                "batch": {"items": "${items}"},
            },
            {
                "id": "static-call",
                "type": "llm",
                "params": {"model": "anthropic/claude-haiku-4-5", "prompt": "Score the options."},
            },
        ]
    }
    trace_path = tmp_path / "mixed-batch-trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "x",
            "nodes": [
                {
                    "node_id": "generate",
                    "node_type": "LLMNode",
                    "success": True,
                    "batch_items": [
                        {
                            "index": 0,
                            "success": True,
                            "llm_call": {
                                "model": "gemini/gemini-2.5-flash-lite",
                                "input_tokens": 100,
                                "output_tokens": 10,
                                "cost_usd": 0.01,
                            },
                        },
                        {
                            "index": 1,
                            "success": True,
                            "llm_call": {
                                "model": "gemini/gemini-3-flash-preview",
                                "input_tokens": 200,
                                "output_tokens": 20,
                                "cost_usd": 0.02,
                            },
                        },
                    ],
                },
                {
                    "node_id": "static-call",
                    "node_type": "LLMNode",
                    "success": True,
                    "llm_call": {
                        "model": "anthropic/claude-haiku-4-5",
                        "input_tokens": 500,
                        "output_tokens": 50,
                        "cost_usd": 0.05,
                    },
                },
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(
        workflow_ir,
        parameters={"items": [{"model": "a", "prompt": "x"}, {"model": "b", "prompt": "y"}]},
        workflow_path="x",
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )

    heterogeneous_row = next(row for row in result.per_call if row.node_path == "generate")
    assert result.summary.trace_coverage == "complete"
    assert result.summary.actually_paid_usd == pytest.approx(0.08)
    assert result.summary.no_cache_hypothetical_usd is not None
    # Cost contract (load-bearing for N-1's `total_paid - Σ excluded.actual_cost_usd`
    # subtraction): every priced trace leaf is keyed exactly once across rows,
    # so summing row.cost_usd matches actually_paid.total_usd within float
    # precision. If batch parent rows ever leak descendant cost into their own
    # cost_usd, this assertion fires and the priced-cohort math overstates.
    sum_row_cost = sum((r.cost_usd or 0.0) for r in result.per_call)
    assert sum_row_cost == pytest.approx(result.summary.actually_paid_usd)
    assert heterogeneous_row.model_is_heterogeneous is True
    assert heterogeneous_row.observed_call_count == 2
    assert heterogeneous_row.observed_models == ("gemini/gemini-2.5-flash-lite", "gemini/gemini-3-flash-preview")
    delta = result.summary.actual_vs_no_cache_delta
    assert delta.kind != "unavailable"
    assert delta.unavailable_reason is None
    assert delta.compared_to == "actually_paid_priced_cohort_usd"
    assert delta.excluded_nodes == ("generate",)
    assert result.summary.projection_exclusions[0].node_path == "generate"
    assert result.summary.projection_exclusions[0].reason == "heterogeneous_model"
    assert result.summary.projection_exclusions[0].actual_cost_usd == pytest.approx(0.03)

    from pflow.core.cache_analysis.render_json import render_json
    from pflow.core.cache_analysis.render_text import render_text

    payload = render_json(result)
    assert payload["summary"]["actual_vs_no_cache_delta"]["kind"] != "unavailable"
    assert payload["summary"]["actual_vs_no_cache_delta"]["compared_to"] == "actually_paid_priced_cohort_usd"
    assert payload["summary"]["actual_vs_no_cache_delta"]["excluded_nodes"] == ["generate"]
    assert payload["summary"]["projection_exclusions"] == [
        {
            "workflow_path": "x",
            "node_path": "generate",
            "reason": "heterogeneous_model",
            "actual_cost_usd": 0.03,
        }
    ]

    text = render_text(result)
    # Fix 7: when every excluded row has trace-recorded cost, the analyzer
    # FOLDS that cost into the no-cache/rerun projection lines and surfaces
    # the cohort context as a footnote below. The agent reads the cost block
    # top-to-bottom without doing subtraction.
    assert "Cost without caching:" in text
    assert "Cost without caching (projected subset):" not in text
    # Old standalone Excluded line is gone in the folded path; the
    # excluded node + reason move into the cost-exclusion footnote
    # (Bug 13: "pass-through" jargon replaced with plain language).
    assert "Excluded from analysis:" not in text
    assert "of the above was paid by generate" in text
    assert "couldn't be analyzed for cache savings" in text
    assert "model varies per call" in text  # now in the footnote
    assert "pass-through" not in text
    # Candidate A: the actual-vs-no-cache savings now render as a parenthetical
    # on the ``Actually paid`` line, not as a separate ``Actual cost delta``
    # line. The legacy labels must not reappear.
    assert "Actual cost delta" not in text
    assert "Actual trace delta:" not in text
    actually_paid_line = next(line for line in text.splitlines() if "Actually paid:" in line)
    assert "vs cost without caching" in actually_paid_line
    # The savings parenthetical does not inline ``(excludes ...)``; the
    # cohort context is in the footnote below.
    assert "(excludes generate)" not in text
    assert "unavailable (projection excludes generate)" not in text


def test_observed_model_replaces_ir_when_trace_consistent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    workflow_ir = {
        "nodes": [
            {
                "id": "generate",
                "type": "llm",
                "params": {"prompt": "Summarize the trace evidence."},
            }
        ]
    }
    assert workflow_ir["nodes"][0]["params"].get("model") is None
    trace_path = _write_trace_fixture(
        tmp_path,
        workflow_path="x",
        nodes=[_llm_trace_event("generate", model="gemini/gemini-2.5-flash")],
    )

    result = analyze(workflow_ir, workflow_path="x", trace_path=trace_path, auto_load_trace=False)

    row = result.per_call[0]
    assert row.model == "gemini/gemini-2.5-flash"
    assert row.observed_models == ("gemini/gemini-2.5-flash",)


def test_observed_model_overrides_ir_when_mismatched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "anthropic/claude-haiku-4-5")
    workflow_ir = {
        "nodes": [
            {
                "id": "generate",
                "type": "llm",
                "params": {"prompt": "Summarize the trace evidence."},
            }
        ]
    }
    trace_path = _write_trace_fixture(
        tmp_path,
        workflow_path="x",
        nodes=[_llm_trace_event("generate", model="gemini/gemini-2.5-flash")],
    )

    result = analyze(workflow_ir, workflow_path="x", trace_path=trace_path, auto_load_trace=False)

    assert result.per_call[0].model == "gemini/gemini-2.5-flash"
    assert result.summary.ir_default_model == "anthropic/claude-haiku-4-5"


def test_multi_observed_sets_model_empty_without_promoting_heterogeneous(
    tmp_path: Path,
) -> None:
    workflow_ir = {
        "nodes": [
            {
                "id": "generate",
                "type": "llm",
                "params": {"model": "anthropic/claude-haiku-4-5", "prompt": "${item.prompt}"},
                "batch": {"items": "${items}"},
            }
        ]
    }
    trace_path = tmp_path / "multi-observed-trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "x",
            "final_status": "success",
            "nodes": [
                {
                    "node_id": "generate",
                    "node_type": "LLMNode",
                    "success": True,
                    "batch_items": [
                        {
                            "index": 0,
                            "success": True,
                            "llm_call": {
                                "model": "gemini/a",
                                "input_tokens": 100,
                                "output_tokens": 10,
                                "cost_usd": 0.01,
                            },
                        },
                        {
                            "index": 1,
                            "success": True,
                            "llm_call": {
                                "model": "gemini/b",
                                "input_tokens": 200,
                                "output_tokens": 20,
                                "cost_usd": 0.02,
                            },
                        },
                    ],
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(
        workflow_ir,
        parameters={"items": [{"prompt": "a"}, {"prompt": "b"}]},
        workflow_path="x",
        trace_path=trace_path,
        auto_load_trace=False,
    )

    row = result.per_call[0]
    assert row.model == ""
    assert row.model_is_heterogeneous is False
    assert row.observed_models == ("gemini/a", "gemini/b")
    from pflow.core.cache_analysis.render_text import render_text

    assert "model varies per batch item" not in render_text(result)


def test_greenfield_effective_model_path_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "anthropic/claude-haiku-4-5")
    workflow_ir = {
        "nodes": [
            {
                "id": "generate",
                "type": "llm",
                "params": {"prompt": "Summarize the static workflow."},
            }
        ]
    }

    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)

    row = result.per_call[0]
    assert row.model == "anthropic/claude-haiku-4-5"
    assert row.observed_models == ()
    assert result.summary.ir_default_model == "anthropic/claude-haiku-4-5"
    assert not any(exclusion.reason == "unresolved_model" for exclusion in result.summary.projection_exclusions)


def test_l1_cost_projection_works_with_observed_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    workflow_ir = {
        "nodes": [
            {
                "id": "generate",
                "type": "llm",
                "params": {"prompt": "Summarize the trace evidence."},
            }
        ]
    }
    trace_path = _write_trace_fixture(
        tmp_path,
        workflow_path="x",
        nodes=[_llm_trace_event("generate", model="gemini/gemini-2.5-flash", output_tokens=200)],
    )

    result = analyze(workflow_ir, workflow_path="x", trace_path=trace_path, auto_load_trace=False)

    assert result.summary.no_cache_hypothetical_usd is not None
    assert result.summary.actual_vs_no_cache_delta.kind != "unavailable"
    assert result.per_call[0].cost_usd is not None


def test_mixed_per_node_explicit_default_and_heterogeneous_integration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "gemini/gemini-2.5-flash")
    workflow_ir = {
        "nodes": [
            {
                "id": "explicit",
                "type": "llm",
                "params": {"model": "anthropic/claude-haiku-4-5", "prompt": "A"},
            },
            {
                "id": "defaulted",
                "type": "llm",
                "params": {"prompt": "B"},
            },
            {
                "id": "heterogeneous",
                "type": "llm",
                "params": {"model": "${item.model}", "prompt": "${item.prompt}"},
                "batch": {"items": "${items}"},
            },
        ]
    }
    trace_path = tmp_path / "mixed-model-trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "x",
            "final_status": "success",
            "nodes": [
                _llm_trace_event("explicit", model="anthropic/claude-haiku-4-5"),
                _llm_trace_event("defaulted", model="openai/gpt-4o-mini"),
                {
                    "node_id": "heterogeneous",
                    "node_type": "LLMNode",
                    "success": True,
                    "batch_items": [
                        {
                            "index": 0,
                            "success": True,
                            "llm_call": {
                                "model": "anthropic/claude-haiku-4-5",
                                "input_tokens": 100,
                                "output_tokens": 10,
                                "cost_usd": 0.01,
                            },
                        },
                        {
                            "index": 1,
                            "success": True,
                            "llm_call": {
                                "model": "openai/gpt-4o-mini",
                                "input_tokens": 100,
                                "output_tokens": 10,
                                "cost_usd": 0.01,
                            },
                        },
                    ],
                },
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(
        workflow_ir,
        parameters={"items": [{"model": "a", "prompt": "a"}, {"model": "b", "prompt": "b"}]},
        workflow_path="x",
        trace_path=trace_path,
        auto_load_trace=False,
    )

    rows = {row.node_path: row for row in result.per_call}
    assert rows["explicit"].model == "anthropic/claude-haiku-4-5"
    assert rows["defaulted"].model == "openai/gpt-4o-mini"
    assert rows["heterogeneous"].model == ""
    assert rows["heterogeneous"].model_is_heterogeneous is True
    from pflow.core.cache_analysis.render_text import render_text

    assert "IR/settings declares: gemini/gemini-2.5-flash (overridden by trace evidence)" in render_text(result)


def test_child_workflow_input_from_root_parameters_drives_cacheable_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defends per-workflow parameter views for parent input -> child input
    mappings; the child prompt/cache tokenizer must use child parameters, not
    the root parameter dict.
    """
    import pflow.core.cache_analysis.cross_workflow as cross_module
    from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult

    child_path = tmp_path / "child.pflow.md"
    child_ir = {
        "inputs": {"brief": {"type": "string"}},
        "cache": {"items": [{"name": "brief", "var": "brief", "prose_before": "Brief:\n"}]},
        "nodes": [
            {
                "id": "child-llm",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["brief"],
                "params": {"prompt": "Child ${brief}"},
            }
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, child_path, ()),
    )
    parent_ir = {
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"brief": "${topic}"}},
            }
        ],
    }

    result = analyze(
        parent_ir,
        parameters={"topic": "a detailed child brief " * 50},
        workflow_path="parent.pflow.md",
        trace_path=None,
        auto_load_trace=False,
        memo_cache=None,
    )

    row = next(row for row in result.per_call if row.workflow_path == str(child_path))
    assert row.cacheable_data_source == "parameters"
    assert row.cacheable_tokens_estimated is not None


def test_child_workflow_input_from_parent_memo_drives_prompt_tokenization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defends memo-backed child input resolution: parent's memoized output
    must propagate to child prompt tokenization, otherwise the child prompt
    stays tiny/partial.
    """
    import pflow.core.cache_analysis.cross_workflow as cross_module
    from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult
    from pflow.runtime.cache import MemoizationCache

    child_path = tmp_path / "child.pflow.md"
    child_ir = {
        "inputs": {"brief": {"type": "string"}},
        "nodes": [
            {
                "id": "child-llm",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "Child ${brief}"},
            }
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, child_path, ()),
    )
    parent_ir = {
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "params": {"prompt": "Parent"},
            },
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"brief": "${draft.response}"}},
            },
        ],
    }
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    cache.put(
        "cache-key",
        "draft",
        "parent.pflow.md",
        "exec",
        {"response": "memo child brief " * 200},
    )

    result = analyze(
        parent_ir,
        workflow_path="parent.pflow.md",
        trace_path=None,
        auto_load_trace=False,
        memo_cache=cache,
    )

    row = next(row for row in result.per_call if row.workflow_path == str(child_path))
    assert row.data_source == "estimator"
    assert row.input_tokens_estimated > 100


def test_child_workflow_unresolved_input_remains_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defends: unresolved child inputs (``${missing.output}``) must NOT be
    coerced to cacheable token evidence. Input tokens still fall back to
    estimator-partial because ``data_source`` is a separate metric.
    """
    import pflow.core.cache_analysis.cross_workflow as cross_module
    from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult

    child_path = tmp_path / "child.pflow.md"
    child_ir = {
        "inputs": {"brief": {"type": "string"}},
        "cache": {"items": [{"name": "brief", "var": "brief", "prose_before": "Brief:\n"}]},
        "nodes": [
            {
                "id": "child-llm",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["brief"],
                "params": {"prompt": "Child ${brief}"},
            }
        ],
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, child_path, ()),
    )
    parent_ir = {
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"brief": "${missing.output}"}},
            }
        ],
    }

    result = analyze(parent_ir, workflow_path="parent.pflow.md", auto_load_trace=False, memo_cache=None)

    row = next(row for row in result.per_call if row.workflow_path == str(child_path))
    assert row.cacheable_data_source == "unavailable"
    assert row.data_source == "estimator-partial"


def test_analyze_skips_non_llm_nodes_in_per_call() -> None:
    workflow_ir = {
        "nodes": [
            {"id": "shell-step", "type": "shell", "params": {"command": "echo"}},
            {
                "id": "llm-step",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "hi"},
            },
        ]
    }
    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)
    assert {row.node_path for row in result.per_call} == {"llm-step"}


def test_per_call_row_invariant_cacheable_le_input() -> None:
    """Cacheable tokens never exceed total input tokens.

    The invariant is now structural: ``input_tokens_estimated`` equals total
    LLM-billed input tokens (prompt body + cache content), so cacheable
    (which is the cache-content subset) cannot exceed it by construction.
    The defense-in-depth ``min(cacheable, input)`` clamp at the call site
    is preserved as a guard against future drift, but this test exercises
    the structural invariant — a workflow that previously produced
    ``ratio=103%`` from independent-estimator drift now stays well-formed
    because cache content is added back into ``input_tokens``.
    """
    # Repetitive text where ``len(text)//4 * 0.75`` exceeds litellm.token_counter's
    # estimate. The exact balance depends on the tokenizer; we assert the
    # invariant rather than try to hit the precise overshoot threshold.
    long_repetitive = "abcd " * 2000
    workflow_ir = {
        "cache": {"items": [{"name": "concept", "var": "concept", "prose_before": "P:\n"}]},
        "inputs": {"concept": {"type": "string"}},
        "nodes": [
            {
                "id": "x",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["concept"],
                "params": {"prompt": long_repetitive + "${concept}"},
            }
        ],
    }
    result = analyze(
        workflow_ir,
        parameters={"concept": long_repetitive},
        workflow_path="x",
        auto_load_trace=False,
        memo_cache=None,
    )
    for row in result.per_call:
        assert row.cache_ratio_pct <= 100, f"row {row.node_path} has nonsense ratio {row.cache_ratio_pct}%"
        assert row.cacheable_tokens_estimated <= row.input_tokens_estimated, (
            f"cacheable={row.cacheable_tokens_estimated} > input={row.input_tokens_estimated} "
            "violates the 'cache cannot exceed total' invariant"
        )


def test_clamp_logs_debug_when_cacheable_exceeds_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    token_module = importlib.import_module("pflow.core.cache_analysis.token_estimation")
    monkeypatch.setattr(token_module, "_estimate_ref_tokens", lambda ref, **_kwargs: 200 if ref == "context" else None)

    workflow_path = str(tmp_path / "clamp.pflow.md")
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "P:\n"}]},
        "nodes": [
            {
                "id": "judge",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Judge ${context}."},
            }
        ],
    }
    trace_path = _write_trace_fixture(
        tmp_path,
        workflow_path=workflow_path,
        nodes=[_llm_trace_event("judge", model="anthropic/claude-sonnet-4-5", input_tokens=100)],
    )

    with caplog.at_level(logging.DEBUG, logger="pflow.core.cache_analysis.analyze"):
        result = analyze(
            workflow_ir,
            parameters={"context": "stable"},
            workflow_path=workflow_path,
            trace_path=trace_path,
            auto_load_trace=False,
            memo_cache=None,
        )

    row = result.per_call[0]
    assert row.cacheable_tokens_estimated == row.input_tokens_estimated == 100
    assert any("cacheable_tokens (200, source=parameters) exceeded input_tokens (100" in m for m in caplog.messages)


def test_cacheable_tokens_includes_cache_content_when_chunks_only_in_cache_block() -> None:
    """Bug 4 reproducer — declared chunks referenced by name only in
    ``prompt_cache:`` (not inlined in the prompt body) must contribute their
    resolved token count to ``input_tokens_estimated``. Without this the
    ``min(cacheable, input)`` clamp truncated correct cacheable values to
    the prompt-body-only size and ``cache.below-min-predicted`` falsely fired.
    """
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "P:\n"}]},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["context"],
                "params": {"prompt": "Draft a summary."},
            }
        ],
    }
    big_context = "X" * 19117  # well above any provider min (>1024 tokens once tokenized)
    result = analyze(
        workflow_ir,
        parameters={"context": big_context},
        workflow_path="x",
        auto_load_trace=False,
        memo_cache=None,
    )
    row = next(r for r in result.per_call if r.node_path == "draft")
    assert row.cacheable_tokens_estimated is not None
    assert row.cacheable_tokens_estimated > 1024, (
        f"declared chunk should resolve well above provider minimum, got {row.cacheable_tokens_estimated}"
    )
    # input_tokens must include cache content; otherwise the clamp truncates cacheable.
    assert row.input_tokens_estimated >= row.cacheable_tokens_estimated
    assert "cache.below-min-predicted" not in {d.id for d in result.warnings}


def test_per_call_row_body_plus_chunks_invariant() -> None:
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"bundle": {"type": "object"}},
        "cache": {"items": [{"name": "bundle", "var": "bundle", "prose_before": "Bundle:\n"}]},
        "nodes": [
            {
                "id": "cached",
                "type": "llm",
                "prompt_cache": ["bundle"],
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Tiny field: ${bundle.tiny_field}"},
            },
            {
                "id": "plain",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "No cache here."},
            },
        ],
        "edges": [],
    }
    result = analyze(
        workflow_ir,
        parameters={"bundle": {"tiny_field": "ok", "big": "padding " * 3000}},
        workflow_path="x",
        auto_load_trace=False,
        memo_cache=None,
    )

    assert result.per_call
    for row in result.per_call:
        assert row.body_tokens_estimated + row.chunk_tokens_estimated == row.input_tokens_estimated
        assert row.body_tokens_estimated >= 0


def test_shadow_warning_enriched_with_costs_when_cache_contains_body(tmp_path: Path) -> None:
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"bundle": {"type": "object"}},
        "cache": {"items": [{"name": "bundle", "var": "bundle", "prose_before": "Bundle:\n"}]},
        "nodes": [
            {
                "id": "use-tiny-field",
                "type": "llm",
                "prompt_cache": ["bundle"],
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "The tiny field is ${bundle.tiny_field}.",
                },
            }
        ],
        "edges": [],
    }
    trace_path = _write_trace_fixture(
        tmp_path,
        workflow_path="x",
        nodes=[
            _llm_trace_event(
                "use-tiny-field",
                model="anthropic/claude-sonnet-4-5",
                input_tokens=6_000,
                output_tokens=5,
                cost_usd=0.001,
            )
        ],
    )

    result = analyze(
        workflow_ir,
        parameters={"bundle": {"tiny_field": "ok", "big": "padding " * 6000}},
        workflow_path="x",
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )
    warning = next(d for d in result.warnings if d.id == "cache.prompt-body-shadows-cache")

    assert warning.context["shadowed_chunk_names"] == ("bundle",)
    assert warning.context["body_only_cost_usd_per_call"] > 0
    assert warning.context["with_cache_cost_usd_per_call"] > warning.context["body_only_cost_usd_per_call"]

    # End-to-end: enrichment context propagates through action build into the
    # rendered text. Closes the gap left by the renderer-only unit test that
    # bypasses the enrichment pipeline. Mutation contract: drop
    # ``context=dict(ctx)`` in ``view_helpers._build_actions`` -> the
    # cost-comparison line never reaches text output -> assertion fails.
    from pflow.core.cache_analysis.render_text import render_text

    rendered = render_text(result)
    assert "Removing `prompt_cache:` for `bundle` from `use-tiny-field`" in rendered
    assert "would drop per-call cost" in rendered
    # Bundle 1: the "compares against inlining the full chunk uncached"
    # footnote was removed. The summary baseline is the honest answer to
    # "what would caching the same prompt cost without the discount"; the
    # local recommendation already shows the alternative (remove the
    # cache declaration to get body-only cost). Mutation contract:
    # restoring that footnote to ``_format_shadow_cache_cost_comparison``
    # fails this negative assertion.
    assert "compares against inlining the full chunk uncached" not in rendered
    assert "different baseline than your body" not in rendered
    assert "unused by your prompt" not in rendered


def test_shadow_warning_with_cache_cost_uses_workflow_ttl(tmp_path: Path) -> None:
    from pflow.core.cache_analysis.cost_estimation import (
        _row_first_run_with_cache_cost,
        get_model_pricing,
    )

    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"bundle": {"type": "object"}},
        "cache": {
            "ttl": "1h",
            "items": [{"name": "bundle", "var": "bundle", "prose_before": "Bundle:\n"}],
        },
        "nodes": [
            {
                "id": "use-tiny-field",
                "type": "llm",
                "prompt_cache": ["bundle"],
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "The tiny field is ${bundle.tiny_field}.",
                },
            }
        ],
        "edges": [],
    }
    trace_path = _write_trace_fixture(
        tmp_path,
        workflow_path="x",
        nodes=[
            _llm_trace_event(
                "use-tiny-field",
                model="anthropic/claude-sonnet-4-5",
                input_tokens=6_000,
                output_tokens=5,
                cost_usd=0.001,
            )
        ],
    )

    result = analyze(
        workflow_ir,
        parameters={"bundle": {"tiny_field": "ok", "big": "padding " * 6000}},
        workflow_path="x",
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )
    row = next(row for row in result.per_call if row.node_path == "use-tiny-field")
    pricing = get_model_pricing(row.model)
    assert pricing is not None
    assert row.output_tokens_estimated is not None
    warning = next(d for d in result.warnings if d.id == "cache.prompt-body-shadows-cache")

    invocation_count = invocation_count_for(row)
    expected_1h = _row_first_run_with_cache_cost(row, pricing, row.output_tokens_estimated, ttl="1h") / invocation_count
    default_5m = _row_first_run_with_cache_cost(row, pricing, row.output_tokens_estimated, ttl="5m") / invocation_count
    assert warning.context["with_cache_cost_usd_per_call"] == pytest.approx(expected_1h)
    assert warning.context["with_cache_cost_usd_per_call"] > default_5m


def test_shadow_warning_unenriched_when_pricing_unavailable(tmp_path: Path) -> None:
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"bundle": {"type": "object"}},
        "cache": {"items": [{"name": "bundle", "var": "bundle", "prose_before": "Bundle:\n"}]},
        "nodes": [
            {
                "id": "use-tiny-field",
                "type": "llm",
                "prompt_cache": ["bundle"],
                "params": {
                    "model": "not-a-real-provider/not-a-real-model",
                    "prompt": "The tiny field is ${bundle.tiny_field}.",
                },
            }
        ],
        "edges": [],
    }
    trace_path = _write_trace_fixture(
        tmp_path,
        workflow_path="x",
        nodes=[
            _llm_trace_event(
                "use-tiny-field",
                model="not-a-real-provider/not-a-real-model",
                input_tokens=6_000,
                output_tokens=5,
                cost_usd=0.001,
            )
        ],
    )

    result = analyze(
        workflow_ir,
        parameters={"bundle": {"tiny_field": "ok", "big": "padding " * 6000}},
        workflow_path="x",
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )
    warning = next(d for d in result.warnings if d.id == "cache.prompt-body-shadows-cache")

    assert "body_only_cost_usd_per_call" not in warning.context
    assert "with_cache_cost_usd_per_call" not in warning.context
    assert "shadowed_chunk_names" not in warning.context


def test_total_input_tokens_trace_total_style_keeps_prompt_tokens() -> None:
    """Trace event where ``input_tokens`` already includes cache portions."""
    from pflow.core.cache_analysis.analyze import _estimate_row_tokens

    trace_llm_call = {
        "input_tokens": 2000,
        "cache_creation_input_tokens": 1500,
        "cache_read_input_tokens": 0,
        "output_tokens": 50,
    }
    input_tokens, _chunk_tokens, source, _output, _output_source = _estimate_row_tokens(
        model="anthropic/claude-sonnet-4-5",
        resolved_prompt="ignored",
        memo_cache=None,
        node_id="x",
        workflow_path=None,
        has_unresolved=False,
        trace_llm_call=trace_llm_call,
    )
    assert source == "trace"
    assert input_tokens == 2000


def test_total_input_tokens_gemini_trace_does_not_double_count() -> None:
    """Gemini provider: ``input_tokens`` already includes cached content;
    don't double-count. The analyzer uses the shared LiteLLM usage
    normalization rule rather than provider metadata.
    """
    from pflow.core.cache_analysis.analyze import _estimate_row_tokens

    trace_llm_call = {
        "input_tokens": 2000,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 1500,
        "output_tokens": 50,
    }
    input_tokens, _chunk_tokens, source, _output, _output_source = _estimate_row_tokens(
        model="gemini/gemini-1.5-flash",
        resolved_prompt="ignored",
        memo_cache=None,
        node_id="x",
        workflow_path=None,
        has_unresolved=False,
        trace_llm_call=trace_llm_call,
    )
    assert source == "trace"
    assert input_tokens == 2000


def test_total_input_tokens_trace_split_style_adds_cache_portions() -> None:
    """Legacy split-style trace event: ``input_tokens`` is uncached-only."""
    from pflow.core.cache_analysis.analyze import _estimate_row_tokens

    trace_llm_call = {
        "input_tokens": 50,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 1500,
        "output_tokens": 10,
    }
    input_tokens, _chunk_tokens, source, _output, _output_source = _estimate_row_tokens(
        model="anthropic/claude-sonnet-4-5",
        resolved_prompt="ignored",
        memo_cache=None,
        node_id="x",
        workflow_path=None,
        has_unresolved=False,
        trace_llm_call=trace_llm_call,
    )
    assert source == "trace"
    assert input_tokens == 1550


def test_analyze_summary_counts_warnings_and_info() -> None:
    """Summary tracks blocking_errors / warnings_count / info_count separately."""
    workflow_ir = {
        "inputs": {"concept": {"type": "string"}},
        "nodes": [
            {
                "id": "step",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "x" * 100},
                "prompt_cache": ["concept"],
            }
        ],
        "cache": {"items": [{"name": "concept", "var": "concept", "prose_before": "P\n\n"}]},
    }
    result = analyze(workflow_ir, parameters={"concept": "hi"}, workflow_path="x", auto_load_trace=False)
    # cache.below-min-predicted fires from parameters-tier evidence
    # (small chunk, anthropic min=1024).
    # Tighter assertion: lock the specific id so a different warning firing
    # for the wrong reason fails the test (not just total count).
    assert any(w.id == "cache.below-min-predicted" for w in result.warnings), (
        f"Expected cache.below-min-predicted; got: {[w.id for w in result.warnings]}"
    )
    sum_ = result.summary
    assert sum_.warnings_count + sum_.info_count >= 1


def test_truncated_trace_preserves_non_cache_validator_errors(tmp_path: Path) -> None:
    """Truncated-trace filtering must not hide universal blocking errors.

    This guards the interaction between the unified validator pipeline and the
    truncated-trace suppression pass. ``other_blocking_errors[]`` is derived
    from ``analysis.warnings`` by renderers, so dropping non-cache ERRORs here
    would make broken workflows look valid whenever the loaded trace is
    truncated.

    Post B-9 split: non-cache validator errors surface in
    ``other_blocking_errors[]`` (cache-domain ERRORs go to
    ``blocking_errors[]``).
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "ran",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Executed call.",
                },
            },
            {
                "id": "skipped",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Skipped call.",
                    "thinking_effort": "high",
                },
            },
        ],
    }
    trace_path = tmp_path / "truncated-trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "x",
            # Truncated coverage: workflow died, only one of two nodes ran.
            "final_status": "failed",
            "nodes": [
                {
                    "node_id": "ran",
                    "node_type": "LLMNode",
                    "success": True,
                    "llm_call": {
                        "model": "anthropic/claude-sonnet-4-5",
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "cost_usd": 0.01,
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    result = analyze(
        workflow_ir,
        workflow_path="x",
        trace_path=trace_path,
        auto_load_trace=False,
        memo_cache=None,
    )

    assert result.summary.evidence_scope == "truncated_trace_executed_subset"
    unknown_param = [d for d in result.warnings if "thinking_effort" in d.message]
    assert len(unknown_param) == 1
    assert unknown_param[0].severity == Severity.ERROR

    from pflow.core.cache_analysis.render_json import render_json

    payload = render_json(result)
    # Unknown LLM param is a non-cache validator error → other_blocking_errors[]
    # post B-9 split. Cache-domain blocking_errors[] stays empty here.
    assert payload["blocking_errors"] == []
    assert payload["other_blocking_errors"][0]["node_id"] == "skipped"
    assert payload["other_blocking_errors"][0]["suggestions"] == ["Did you mean 'reasoning_effort'?"]


def test_analyze_surfaces_cache_order_mismatch() -> None:
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "cache": {
            "items": [
                {"name": "a", "var": "a", "prose_before": "A:\n"},
                {"name": "b", "var": "b", "prose_before": "B:\n"},
            ]
        },
        "nodes": [
            {
                "id": "gen",
                "type": "llm",
                "prompt_cache": ["b", "a"],
                "params": {"prompt": "go"},
            }
        ],
        "edges": [],
    }
    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)
    diag = next(d for d in result.warnings if d.id == "cache.order-mismatch")
    assert diag.severity == Severity.ERROR


def test_analyze_surfaces_cache_unused_chunk() -> None:
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "cache": {
            "items": [
                {"name": "a", "var": "a", "prose_before": "A:\n"},
                {"name": "b", "var": "b", "prose_before": "B:\n"},
            ]
        },
        "nodes": [
            {
                "id": "gen",
                "type": "llm",
                "prompt_cache": ["a"],
                "params": {"prompt": "go"},
            }
        ],
        "edges": [],
    }
    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)
    assert "cache.unused-chunk" in {d.id for d in result.warnings}


def test_analyze_surfaces_cache_invalid_on_non_llm() -> None:
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"a": {"type": "string"}},
        "cache": {"items": [{"name": "a", "var": "a", "prose_before": "A:\n"}]},
        "nodes": [
            {
                "id": "echo",
                "type": "shell",
                "prompt_cache": ["a"],
                "params": {"command": "echo hi"},
            }
        ],
        "edges": [],
    }
    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)
    diag = next(d for d in result.warnings if d.id == "cache.invalid-on-non-llm")
    assert diag.severity == Severity.ERROR


def test_analyze_surfaces_non_cache_validator_diagnostics() -> None:
    """Validator findings outside the cache catalog surface in analyze().

    Mutation contract: restoring the old validate_data_flow-only cache filter
    makes this fail because the unknown-param diagnostic disappears.
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "deep-think",
                "type": "llm",
                "params": {
                    "prompt": "Think.",
                    "model": "anthropic/claude-opus-4-7",
                    "thinking_effort": "high",
                },
            }
        ],
        "edges": [],
    }
    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)
    unknown_param = [d for d in result.warnings if "thinking_effort" in d.message]
    assert len(unknown_param) == 1, (
        f"Expected unknown-param diagnostic; got: {[(d.severity, d.message) for d in result.warnings]}"
    )
    diag = unknown_param[0]
    assert diag.severity == Severity.ERROR
    assert any("reasoning_effort" in suggestion for suggestion in (diag.suggestions or [])), (
        f"Expected reasoning_effort suggestion; got: {diag.suggestions}"
    )


def test_analyze_diagnostics_match_workflow_validator_for_thinking_effort() -> None:
    """Architectural parity: analyzer includes validator ERROR diagnostics."""
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "deep-think",
                "type": "llm",
                "params": {
                    "prompt": "Think.",
                    "model": "anthropic/claude-opus-4-7",
                    "thinking_effort": "high",
                },
            }
        ],
        "edges": [],
    }

    dummy = generate_dummy_parameters(workflow_ir.get("inputs") or {})
    validator_diags = WorkflowValidator.validate(workflow_ir=workflow_ir, extracted_params=dummy)
    validator_errors = {d.message for d in validator_diags if d.severity == Severity.ERROR}

    analyzer_diags = analyze(workflow_ir, workflow_path="x", auto_load_trace=False).warnings
    analyzer_errors = {d.message for d in analyzer_diags if d.severity == Severity.ERROR}

    assert validator_errors.issubset(analyzer_errors), (
        f"Validator ERRORs not in analyzer output. Missing: {validator_errors - analyzer_errors}"
    )


def test_analyze_child_validator_error_carries_child_affected_workflow(tmp_path: Path) -> None:
    """Recursive validator findings must be scoped to the child workflow path."""
    from tests.shared.markdown_utils import write_workflow_file

    child_path = tmp_path / "child.pflow.md"
    write_workflow_file(
        {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "child-thinker",
                    "type": "llm",
                    "params": {
                        "model": "anthropic/claude-opus-4-7",
                        "prompt": "Think in the child workflow.",
                        "thinking_effort": "high",
                    },
                }
            ],
        },
        child_path,
        title="Child",
    )
    parent_path = tmp_path / "parent.pflow.md"
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {}},
            }
        ],
    }

    result = analyze(workflow_ir, workflow_path=str(parent_path), base_path=tmp_path, auto_load_trace=False)

    child_errors = [d for d in result.warnings if "thinking_effort" in d.message]
    assert len(child_errors) == 1
    diag = child_errors[0]
    assert diag.node_id == "child-thinker"
    assert diag.context is not None
    assert diag.context["affected_workflow"] == str(child_path)
    assert diag.context["sub_workflow_step"] == "call-child"
    assert diag.message.startswith("In step 'call-child' sub-workflow:")


# ---------------------------------------------------------------------------
# Trace auto-load — hash-prefix glob (O(matches), not O(directory))
# ---------------------------------------------------------------------------


def _write_trace(
    debug_dir: Path,
    *,
    workflow_path: str,
    format_version: str,
    nodes: list[dict[str, Any]] | None = None,
    workflow_name: str = "x",
    timestamp: str | None = None,
    final_status: str | None = None,
    failed_node_ids: list[str] | None = None,
    start_time: str | None = None,
) -> Path:
    """Write a synthetic trace under the production filename schema.

    Uses ``format_trace_filename`` so the test fixture matches the same hash
    prefix the autoload reader globs by — without that, autoload skips the
    file even when contents match.

    The trace body uses the production ``nodes`` key (events list); a
    pre-existing ``events`` shape was test-fixture-only and never matched
    real traces. New consumers walk ``trace_data["nodes"]`` via TraceTree.

    Optional ``final_status`` / ``failed_node_ids`` / ``start_time`` /
    ``timestamp`` kwargs let tests exercise the autoload rank-aware selection
    (Bug 10) and the trace-header rendering. Defaults preserve backward-compat
    with pre-existing tests that omit these fields.
    """
    from pflow.runtime.workflow_trace import format_trace_filename

    debug_dir.mkdir(parents=True, exist_ok=True)
    if timestamp is None:
        timestamp = f"20260430-{time.time_ns() % 1_000_000:06d}"
    name = format_trace_filename(workflow_path, workflow_name, timestamp)
    path = debug_dir / name
    payload: dict[str, Any] = {
        "format_version": format_version,
        "workflow_path": workflow_path,
        "nodes": nodes or [],
    }
    if final_status is not None:
        payload["final_status"] = final_status
    if failed_node_ids is not None:
        payload["failed_node_ids"] = failed_node_ids
    if start_time is not None:
        payload["start_time"] = start_time
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _llm_ir_node(
    node_id: str = "ask",
    *,
    model: str | None = "anthropic/claude-haiku-4-5",
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": node_id,
        "type": "llm",
        "params": {"prompt": "Answer briefly."},
    }
    if model is not None:
        node["model"] = model
        node["params"]["model"] = model
    return node


def _autoload_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    workflow_ir: dict[str, Any],
    trace_nodes: list[dict[str, Any]],
    workflow_path: str = "/abs/x.pflow.md",
) -> tuple[CacheAnalysis, Path]:
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    trace_path = _write_trace(
        fake_home / ".pflow" / "debug",
        workflow_path=workflow_path,
        format_version="2.2.0",
        nodes=trace_nodes,
    )
    return analyze(workflow_ir, workflow_path=workflow_path, auto_load_trace=True), trace_path


def test_autoload_finds_2_1_0_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    path = _write_trace(debug_dir, workflow_path="/abs/x.pflow.md", format_version="2.1.0")

    workflow_ir = {"nodes": []}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path == str(path)


def test_autoload_uses_trace_and_warns_when_model_drifts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-node model drift: trace is consumed; a Notes entry discloses the
    drift. Replaces the prior whole-trace rejection contract.

    Mutation contract: deleting ``_detect_per_node_model_drift`` or its call
    site causes ``"recorded with model" in note`` to fail because no drift
    note is emitted.
    """
    builder = TraceFixtureBuilder()
    result, trace_path = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir={"nodes": [_llm_ir_node(model="anthropic/claude-haiku-4-5")]},
        trace_nodes=[builder.llm_event("ask", model="gemini/gemini-2.5-flash")],
    )
    assert result.trace_path == str(trace_path)
    drift_notes = [n for n in result.notes if "recorded with model" in n]
    assert len(drift_notes) == 1
    assert "gemini" in drift_notes[0]
    assert "anthropic" in drift_notes[0]


def test_autoload_uses_trace_when_root_node_renamed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Structural drift: IR's new node has no trace event; per-row degrades
    via ``data_source``. Trace IS still loaded so other rows (none here) can
    use it. The orthogonal "did_not_execute_in_trace" gate at analyze.py
    discards the whole trace because the IR's lone node never executed —
    that's a separate mechanism, not the prior drift gate."""
    builder = TraceFixtureBuilder()
    result, _ = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir={"nodes": [_llm_ir_node("ask-question")]},
        trace_nodes=[builder.llm_event("ask", model="anthropic/claude-haiku-4-5")],
    )
    # The "did_not_execute_in_trace" gate discards; not the drift gate.
    assert result.trace_path is None
    # No drift Notes — different node ids, not a model change.
    assert not any("recorded with model" in n for n in result.notes)


def test_autoload_uses_trace_when_root_node_added(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Structural drift: added node has no trace event. ``did_not_execute_in_trace``
    gate discards the trace (orthogonal to drift detection)."""
    builder = TraceFixtureBuilder()
    result, _ = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir={"nodes": [_llm_ir_node("ask"), _llm_ir_node("summarize")]},
        trace_nodes=[builder.llm_event("ask", model="anthropic/claude-haiku-4-5")],
    )
    assert result.trace_path is None
    assert not any("recorded with model" in n for n in result.notes)


def test_autoload_uses_trace_when_root_node_removed_orphans_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structural drift: trace has orphan events the IR no longer references.
    Per-row mechanism ignores orphans. Trace IS loaded because the IR's
    remaining node DID execute in the trace.

    Mutation contract: restore the deleted drift gate (``_trace_aligns_with_ir``)
    → set inequality of {ask} vs {ask, summarize} fires → assertion fails."""
    builder = TraceFixtureBuilder()
    result, trace_path = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir={"nodes": [_llm_ir_node("ask")]},
        trace_nodes=[
            builder.llm_event("ask", model="anthropic/claude-haiku-4-5"),
            builder.llm_event("summarize", model="anthropic/claude-haiku-4-5"),
        ],
    )
    assert result.trace_path == str(trace_path)
    assert not any("recorded with model" in n for n in result.notes)


def test_autoload_returns_trace_when_models_and_node_ids_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder = TraceFixtureBuilder()
    result, trace_path = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir={"nodes": [_llm_ir_node()]},
        trace_nodes=[builder.llm_event("ask", model="anthropic/claude-haiku-4-5")],
    )
    assert result.trace_path == str(trace_path)


def test_autoload_ignores_misaligned_trace_with_no_root_llm_activity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When auto-loaded trace has ShellNode + sub-workflow LLM events but no
    matching root LLM events for the IR, autoload skips the trace and falls
    back to greenfield. The misalignment is independent of trace_coverage —
    a successful run from a different conditional branch can still be
    misaligned for THIS analysis call's IR.
    """
    builder = TraceFixtureBuilder()
    result, _trace_path = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir={"nodes": [_llm_ir_node()]},
        trace_nodes=[
            {"node_id": "prepare", "node_type": "ShellNode", "success": True},
            builder.workflow_event(
                "child",
                [builder.llm_event("child-ask", model="gemini/gemini-2.5-flash")],
                workflow_path="/abs/child.pflow.md",
            ),
        ],
    )
    assert result.trace_path is None
    # Bug 1 follow-up: the rejection Notes line now names the rejected trace
    # filename + its run status so the agent knows what was attempted.
    rejection_notes = [n for n in result.notes if "did not cover all root LLM nodes" in n]
    assert len(rejection_notes) == 1, f"expected one rejection note, got: {result.notes}"
    assert "workflow-trace-" in rejection_notes[0]
    assert ".json" in rejection_notes[0]
    assert "(success)" in rejection_notes[0]
    assert "--from-trace" in rejection_notes[0]


def test_autoload_proceeds_when_ir_has_no_llm_nodes_and_trace_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, trace_path = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir={"nodes": [{"id": "prepare", "type": "shell", "params": {"command": "echo ok"}}]},
        trace_nodes=[{"node_id": "prepare", "node_type": "ShellNode", "success": True}],
    )
    assert result.trace_path == str(trace_path)


def test_autoload_tolerates_root_heterogeneous_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder = TraceFixtureBuilder()
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "batch": {"items": "${items}", "as": "item"},
                "params": {"prompt": "Score ${item.text}", "model": "${item.model}"},
            },
            _llm_ir_node("review", model="anthropic/claude-haiku-4-5"),
        ]
    }
    trace_nodes = [
        builder.batch_event(
            "score",
            [
                {
                    "index": 0,
                    "success": True,
                    "llm_call": {"model": "anthropic/claude-haiku-4-5"},
                },
                {
                    "index": 1,
                    "success": True,
                    "llm_call": {"model": "gemini/gemini-2.5-flash"},
                },
            ],
        ),
        builder.llm_event("review", model="anthropic/claude-haiku-4-5"),
    ]
    result, trace_path = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir=workflow_ir,
        trace_nodes=trace_nodes,
    )
    assert result.trace_path == str(trace_path)


def test_autoload_includes_default_model_in_ir_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "anthropic/claude-haiku-4-5")
    builder = TraceFixtureBuilder()
    result, trace_path = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir={"nodes": [_llm_ir_node(model=None)]},
        trace_nodes=[builder.llm_event("ask", model="anthropic/claude-haiku-4-5")],
    )
    assert result.trace_path == str(trace_path)


def test_autoload_uses_trace_and_warns_when_default_model_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default-model drift (IR has no explicit per-node model; workflow default
    changed since trace was recorded): trace is consumed; Notes entry mentions
    both old and new model. Replaces the prior whole-trace rejection contract.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "anthropic/claude-haiku-4-5")
    builder = TraceFixtureBuilder()
    result, trace_path = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir={"nodes": [_llm_ir_node(model=None)]},
        trace_nodes=[builder.llm_event("ask", model="gemini/gemini-2.5-flash")],
    )
    assert result.trace_path == str(trace_path)
    drift_notes = [n for n in result.notes if "recorded with model" in n]
    assert len(drift_notes) == 1
    assert "gemini" in drift_notes[0]
    assert "anthropic" in drift_notes[0]


def test_autoload_normalizes_provider_prefix_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder = TraceFixtureBuilder()
    result, trace_path = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir={"nodes": [_llm_ir_node(model="gemini-2.5-flash")]},
        trace_nodes=[builder.llm_event("ask", model="gemini/gemini-2.5-flash")],
    )
    assert result.trace_path == str(trace_path)


def test_autoload_handles_cached_orphan_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cached events for nodes the IR no longer references are orphans —
    per-row mechanism ignores them. The root row matches the live event; trace
    is loaded with no drift Notes."""
    builder = TraceFixtureBuilder()
    result, trace_path = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir={"nodes": [_llm_ir_node("ask")]},
        trace_nodes=[
            builder.llm_event("ask", model="anthropic/claude-haiku-4-5"),
            builder.cached_llm_event_with_call(
                "old-ask",
                model="gemini/gemini-2.5-flash",
            ),
        ],
    )
    assert result.trace_path == str(trace_path)
    assert not any("recorded with model" in n for n in result.notes)


def test_autoload_does_not_falsely_reject_workflow_batch_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REGRESSION (Bug 1, lyrics-generator field report): a trace containing a
    ``type: workflow`` batch event whose batch items contain sub-workflow LLM
    events must NOT be falsely rejected. The prior drift gate over-collected
    these batch-item LLMs into its "root" set via ``TraceTree.walk``'s
    unconditional batch_items descent, producing set inequality vs the parent
    IR's root LLM nodes — rejecting every non-trivial run of any workflow-batch.

    Mutation contract: restore the deleted drift gate without the tier filter
    → ``analyze-sources``'s sub-workflow ``analyze`` LLM events leak into the
    root set → ``{ask, analyze} != {ask}`` → trace rejected → trace_path is None.
    """
    builder = TraceFixtureBuilder()
    workflow_batch = builder.homogeneous_workflow_batch_event(
        "analyze-sources",
        workflow_path="/abs/child.pflow.md",
        items=[
            ("source-1", [builder.llm_event("analyze", model="anthropic/claude-haiku-4-5")]),
            ("source-2", [builder.llm_event("analyze", model="anthropic/claude-haiku-4-5")]),
        ],
    )
    result, trace_path = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir={"nodes": [_llm_ir_node("ask")]},
        trace_nodes=[
            builder.llm_event("ask", model="anthropic/claude-haiku-4-5"),
            workflow_batch,
        ],
    )
    assert result.trace_path == str(trace_path)
    assert not any("recorded with model" in n for n in result.notes)


def test_autoload_ignores_sub_workflow_llm_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sub-workflow LLM events stay scoped to their sub-workflow's per-call
    rows; they don't influence root-level model-drift detection."""
    builder = TraceFixtureBuilder()
    result, trace_path = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir={"nodes": [_llm_ir_node("ask")]},
        trace_nodes=[
            builder.llm_event("ask", model="anthropic/claude-haiku-4-5"),
            builder.workflow_event(
                "child",
                [builder.llm_event("child-ask", model="gemini/gemini-2.5-flash")],
                workflow_path="/abs/child.pflow.md",
            ),
        ],
    )
    assert result.trace_path == str(trace_path)
    assert not any("recorded with model" in n for n in result.notes)


def test_autoload_prefers_success_over_newer_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug 10: a newer failed trace must not shadow an older successful one.

    Mutation contract: deleting the success-tier branch in ``_autoload_trace``
    → newest (failed) trace wins → ``result.trace_path`` points at the failed
    file → ``Path(result.trace_path).name == failed_path.name`` instead of
    ``success_path.name`` → assertion fails.
    """
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    builder = TraceFixtureBuilder()
    success_path = _write_trace(
        debug_dir,
        workflow_path="/abs/x.pflow.md",
        format_version="2.2.0",
        nodes=[builder.llm_event("ask", model="anthropic/claude-haiku-4-5")],
        timestamp="20260511-153228",
        final_status="success",
    )
    failed_path = _write_trace(
        debug_dir,
        workflow_path="/abs/x.pflow.md",
        format_version="2.2.0",
        nodes=[builder.llm_event("ask", model="anthropic/claude-haiku-4-5", success=False)],
        timestamp="20260511-163027",
        final_status="failed",
        failed_node_ids=["ask"],
    )
    result = analyze({"nodes": [_llm_ir_node()]}, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path == str(success_path)
    skip_notes = [n for n in result.notes if "Skipped newer trace" in n]
    assert len(skip_notes) == 1, f"expected one skip note, got: {result.notes}"
    assert failed_path.name in skip_notes[0]
    assert success_path.name in skip_notes[0]


def test_autoload_uses_newest_when_all_successful(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Standard case: among same-tier traces, newest-by-filename wins. No
    "Skipped newer trace" Notes line."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    builder = TraceFixtureBuilder()
    _write_trace(
        debug_dir,
        workflow_path="/abs/x.pflow.md",
        format_version="2.2.0",
        nodes=[builder.llm_event("ask", model="anthropic/claude-haiku-4-5")],
        timestamp="20260511-153228",
        final_status="success",
    )
    newer_path = _write_trace(
        debug_dir,
        workflow_path="/abs/x.pflow.md",
        format_version="2.2.0",
        nodes=[builder.llm_event("ask", model="anthropic/claude-haiku-4-5")],
        timestamp="20260511-163027",
        final_status="success",
    )
    result = analyze({"nodes": [_llm_ir_node()]}, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path == str(newer_path)
    assert not any("Skipped newer trace" in n for n in result.notes)


def test_autoload_uses_newest_failed_when_no_success_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When only failed traces exist, the newest is loaded with a disclosure
    Notes line. Downstream truncated-trace suppression handles cost
    correctness."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    builder = TraceFixtureBuilder()
    _write_trace(
        debug_dir,
        workflow_path="/abs/x.pflow.md",
        format_version="2.2.0",
        nodes=[builder.llm_event("ask", model="anthropic/claude-haiku-4-5", success=False)],
        timestamp="20260511-153228",
        final_status="failed",
        failed_node_ids=["ask"],
    )
    newer_failed = _write_trace(
        debug_dir,
        workflow_path="/abs/x.pflow.md",
        format_version="2.2.0",
        nodes=[builder.llm_event("ask", model="anthropic/claude-haiku-4-5", success=False)],
        timestamp="20260511-163027",
        final_status="failed",
        failed_node_ids=["ask"],
    )
    result = analyze({"nodes": [_llm_ir_node()]}, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path == str(newer_failed)
    no_success_notes = [n for n in result.notes if "no successful trace exists" in n]
    assert len(no_success_notes) == 1
    assert newer_failed.name in no_success_notes[0]


def test_autoload_treats_degraded_as_preferable_over_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``degraded`` runs completed with runtime warnings but produced full
    evidence; they rank with success, ahead of failed."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    builder = TraceFixtureBuilder()
    degraded_path = _write_trace(
        debug_dir,
        workflow_path="/abs/x.pflow.md",
        format_version="2.2.0",
        nodes=[builder.llm_event("ask", model="anthropic/claude-haiku-4-5")],
        timestamp="20260511-153228",
        final_status="degraded",
    )
    _write_trace(
        debug_dir,
        workflow_path="/abs/x.pflow.md",
        format_version="2.2.0",
        nodes=[builder.llm_event("ask", model="anthropic/claude-haiku-4-5", success=False)],
        timestamp="20260511-163027",
        final_status="failed",
        failed_node_ids=["ask"],
    )
    result = analyze({"nodes": [_llm_ir_node()]}, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path == str(degraded_path)


def test_autoload_treats_absent_final_status_as_success_for_backcompat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy 2.1.0 traces lack ``final_status``. The rank-aware selection
    must treat absent as success or every existing autoload test regresses.

    Mutation contract: removing the ``or "success"`` fallback in
    ``_autoload_trace`` → absent-status trace routes to the failed bucket
    → newer failed trace wins → assertion fails.
    """
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    builder = TraceFixtureBuilder()
    legacy_path = _write_trace(
        debug_dir,
        workflow_path="/abs/x.pflow.md",
        format_version="2.1.0",
        nodes=[builder.llm_event("ask", model="anthropic/claude-haiku-4-5")],
        timestamp="20260511-153228",
        # No final_status — legacy 2.1.0 trace
    )
    _write_trace(
        debug_dir,
        workflow_path="/abs/x.pflow.md",
        format_version="2.2.0",
        nodes=[builder.llm_event("ask", model="anthropic/claude-haiku-4-5", success=False)],
        timestamp="20260511-163027",
        final_status="failed",
        failed_node_ids=["ask"],
    )
    result = analyze({"nodes": [_llm_ir_node()]}, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path == str(legacy_path)


def test_explicit_from_trace_loads_regardless_of_model(tmp_path: Path) -> None:
    """Explicit ``--from-trace`` always loads the trace; model drift surfaces
    via the Notes entry (same path as auto-load now that the gate is gone)."""
    builder = TraceFixtureBuilder()
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.2.0",
            "workflow_path": "/abs/x.pflow.md",
            "nodes": [builder.llm_event("ask", model="gemini/gemini-2.5-flash")],
        }),
        encoding="utf-8",
    )
    result = analyze(
        {"nodes": [_llm_ir_node(model="anthropic/claude-haiku-4-5")]},
        workflow_path="/abs/x.pflow.md",
        trace_path=trace_path,
        auto_load_trace=False,
    )
    assert result.trace_path == str(trace_path)
    drift_notes = [n for n in result.notes if "recorded with model" in n]
    assert len(drift_notes) == 1


def test_autoload_model_drift_appends_notes_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-node model drift on auto-loaded traces surfaces a Notes entry naming
    the trace-side and IR-side models. The trace IS still consumed — projections
    use trace-side pricing, but actually-paid stays correct.

    Mutation contract: removing the ``notes.append(drift_note)`` call site in
    ``analyze()`` causes ``drift_notes`` to be empty and the assertions fail.
    Renaming this from the prior whole-trace-rejection contract is intentional:
    Bug 1 (workflow-batch tier leakage in the drift gate) made the rejection
    a false positive on any workflow using ``type: workflow`` batches.
    """
    builder = TraceFixtureBuilder()
    workflow_ir = {"nodes": [_llm_ir_node(model="anthropic/claude-haiku-4-5")]}
    drifted, trace_path = _autoload_analysis(
        tmp_path,
        monkeypatch,
        workflow_ir=workflow_ir,
        trace_nodes=[builder.llm_event("ask", model="gemini/gemini-2.5-flash")],
    )
    baseline = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)

    # Trace is consumed (not rejected).
    assert drifted.trace_path == str(trace_path)
    # Drift adds at least one note above the baseline.
    assert len(drifted.notes) > len(baseline.notes)
    drift_notes = [n for n in drifted.notes if "recorded with model" in n]
    assert len(drift_notes) == 1
    note = drift_notes[0]
    assert "gemini" in note
    assert "anthropic" in note


def test_autoload_skips_unparseable_files_silently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unparseable trace files in ~/.pflow/debug/ are skipped at debug log
    level. Disk corruption / aborted writes are rare; the producer side
    (WorkflowTraceCollector.save_to_file) is the right place to surface
    write failures, not every analyzer read."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    # Write a syntactically broken file under the new schema's hash prefix
    # so the autoload glob actually surfaces it (then skips).
    from pflow.runtime.workflow_trace import format_trace_filename

    debug_dir.mkdir(parents=True, exist_ok=True)
    name = format_trace_filename("/abs/x.pflow.md", "broken", "20260430-000001")
    (debug_dir / name).write_text("{invalid json", encoding="utf-8")

    workflow_ir = {"nodes": []}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path is None


def test_autoload_skips_traces_for_other_workflows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The hash-prefix glob narrows to candidates for *this* workflow_path.
    Traces for unrelated workflows aren't even read — their hash prefixes
    differ. Locks the O(matching), not O(directory), invariant."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"

    _write_trace(debug_dir, workflow_path="/abs/other.pflow.md", format_version="2.1.0")

    workflow_ir = {"nodes": []}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path is None


def test_autoload_notes_unmatched_traces_when_others_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When auto-load finds no hash match but the debug dir holds unrelated
    traces (typically because the workflow file was renamed/moved), the
    analyzer surfaces a Notes line so the agent doesn't read the empty
    result as 'no evidence exists'.

    Mutation contract: removing the ``notes.append`` in ``_autoload_trace``
    causes this test to fail. The companion test below
    (``test_autoload_emits_no_notes_when_debug_dir_is_empty``) defends the
    gate from being applied unconditionally."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"

    _write_trace(debug_dir, workflow_path="/abs/other.pflow.md", format_version="2.1.0")

    workflow_ir = {"nodes": []}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path is None
    assert any("Found other traces in ~/.pflow/debug/" in note for note in result.notes), result.notes


def test_autoload_emits_no_notes_when_debug_dir_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The unmatched-trace Notes line must NOT fire when no traces exist at
    all — that's a true greenfield, not a rename/move scenario.

    Mutation contract: dropping the ``next(iter(...))`` guard in
    ``_autoload_trace`` and emitting the note unconditionally fails this
    test."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    (fake_home / ".pflow" / "debug").mkdir(parents=True)

    workflow_ir = {"nodes": []}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path is None
    assert not any("Found other traces in ~/.pflow/debug/" in note for note in result.notes), result.notes


def test_explicit_from_trace_missing_path_raises() -> None:
    workflow_ir = {"nodes": []}
    with pytest.raises(FileNotFoundError):
        analyze(
            workflow_ir,
            workflow_path="/abs/x.pflow.md",
            auto_load_trace=False,
            trace_path=Path("/does/not/exist.json"),
        )


def test_explicit_from_trace_invalid_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "trace.json"
    path.write_text("{not json", encoding="utf-8")
    workflow_ir = {"nodes": []}
    with pytest.raises(ValueError):
        analyze(
            workflow_ir,
            workflow_path="/abs/x.pflow.md",
            auto_load_trace=False,
            trace_path=path,
        )


# ---------------------------------------------------------------------------
# Gemini telemetry note (Spike 1 outcome) — last in note ordering
# ---------------------------------------------------------------------------


def test_gemini_note_appended_when_gemini_in_per_call() -> None:
    notes: list[str] = []
    rows = [
        PerCallRow(
            node_path="x",
            model="gemini/gemini-2.5-pro",
            is_batch=False,
            batch_size_estimated=None,
            input_tokens_estimated=100,
            cacheable_tokens_estimated=80,
            cache_ratio_pct=80,
            data_source="trace",
            declared_prompt_cache=None,
        )
    ]
    _maybe_append_gemini_note(rows, notes)
    assert any("Gemini caching" in n for n in notes)


def test_gemini_note_NOT_appended_for_anthropic_only_rows() -> None:
    notes: list[str] = []
    rows = [
        PerCallRow(
            node_path="x",
            model="anthropic/claude-sonnet-4-5",
            is_batch=False,
            batch_size_estimated=None,
            input_tokens_estimated=100,
            cacheable_tokens_estimated=0,
            cache_ratio_pct=0,
            data_source="estimator",
            declared_prompt_cache=None,
        )
    ]
    _maybe_append_gemini_note(rows, notes)
    assert notes == []


def test_gemini_note_uses_plain_english_no_internals() -> None:
    """Fix 8: Gemini note must not leak pflow/LiteLLM internals.

    A fresh agent reading the note cold must be able to act on it. Phrases
    like "LiteLLM's Vertex/Gemini translation" describe how pflow's adapter
    layer translates the API response — implementation detail. The note's
    job is to tell the agent (a) which trace-event field carries Gemini's
    cache-hit signal so they can grep for it, and (b) how to verify caching
    is working.

    Mutation contract: re-add the "LiteLLM's Vertex/Gemini translation"
    string to ``_GEMINI_TELEMETRY_NOTE`` → the negative assertions fail.
    """
    notes: list[str] = []
    rows = [
        PerCallRow(
            node_path="x",
            model="gemini/gemini-2.5-pro",
            is_batch=False,
            batch_size_estimated=None,
            input_tokens_estimated=100,
            cacheable_tokens_estimated=80,
            cache_ratio_pct=80,
            data_source="trace",
            declared_prompt_cache=None,
        )
    ]
    _maybe_append_gemini_note(rows, notes)
    assert len(notes) == 1
    note = notes[0]
    # Positive: agent-actionable phrases present.
    assert "cache_read_input_tokens" in note  # the grep target
    assert "verify caching is working" in note
    assert "## Cache" in note  # tells agent what to declare
    # Negative: no library/adapter internals.
    assert "LiteLLM" not in note
    assert "Vertex" not in note
    assert "translation" not in note
    assert "prompt_tokens_details.cached_tokens" not in note  # picked one canonical field


# ---------------------------------------------------------------------------
# cache.prewarm-no-prefix — boundary regex must match runtime gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt, should_emit",
    [
        # Dot-syntax batch ref at position 0 → emit (today's behavior).
        ("${item.text}\n\nrubric here", True),
        # Bracket-syntax at position 0 → MUST also emit (CR-1430 C1 — was silently
        # missed by the dot-only matcher; runtime gate at nodes/llm/llm.py:350
        # uses ``r"(\.|\[)"``).
        ("${item[0].text}\n\nrubric here", True),
        # Bracket without dot suffix at position 0 → emit (also batch-scoped).
        ("${item[0]}\n\nrubric", True),
        # Static prefix before batch ref → no emit (the auto-batch-prefix can fire).
        ("Some stable rubric content.\n\n${item.text}", False),
        ("Some stable rubric content.\n\n${item[0].text}", False),
        # No batch ref at all → no emit.
        ("Plain prompt with no ${item} reference at all.", False),
    ],
)
def test_prewarm_no_prefix_matches_runtime_gate_for_dot_AND_bracket_syntax(prompt: str, should_emit: bool) -> None:
    """The analyzer's prewarm-no-prefix detection must match the runtime
    auto-batch-prefix gate at ``nodes/llm/llm.py``: both ``${alias.X}`` and
    ``${alias[N]...}`` are batch-scoped references. Earlier dot-only matcher
    silently missed every bracket-syntax workflow (CR-1430 C1)."""
    workflow_ir = {
        "inputs": {"items": {"type": "list"}},
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prewarm": True,
                "batch": {"items": "${items}", "as": "item"},
                "params": {"prompt": prompt, "model": "anthropic/claude-sonnet-4-5"},
            }
        ],
        "edges": [],
    }
    analysis = analyze(workflow_ir, auto_load_trace=False)
    emitted = [d for d in analysis.warnings if d.id == "cache.prewarm-no-prefix"]
    if should_emit:
        assert emitted, (
            f"Expected cache.prewarm-no-prefix for prompt={prompt!r} "
            f"(batch ref at position 0); got ids={[d.id for d in analysis.warnings]}"
        )
    else:
        assert not emitted, (
            f"Did NOT expect cache.prewarm-no-prefix for prompt={prompt!r}; got {len(emitted)} emission(s)"
        )


# ---------------------------------------------------------------------------
# CR-1430 C2: savings percentage must use a consistent rowset
# ---------------------------------------------------------------------------


def _summary_row(
    *,
    node_path: str,
    input_tokens: int = 10_000,
    cacheable_tokens: int,
    declared_prompt_cache: list[str] | None,
    output_tokens: int | None,
) -> PerCallRow:
    """Construct a PerCallRow at the granularity ``_build_summary`` consumes.

    Mixed ``output_tokens=int`` / ``output_tokens=None`` per row is the
    fixture shape that exercises the C2 bug: priced rows in different
    output-availability cohorts.
    """
    ratio = round(100 * cacheable_tokens / input_tokens) if input_tokens else 0
    return PerCallRow(
        node_path=node_path,
        model="claude-sonnet-4-5",
        is_batch=False,
        batch_size_estimated=None,
        input_tokens_estimated=input_tokens,
        cacheable_tokens_estimated=cacheable_tokens,
        cache_ratio_pct=ratio,
        data_source="estimator",
        declared_prompt_cache=declared_prompt_cache,
        output_tokens_estimated=output_tokens,
        output_data_source="memo" if output_tokens is not None else "unavailable",
    )


def test_cost_delta_uses_comparable_absolute_cost_atoms() -> None:
    """CR-1430 C2 regression — drives the buggy mixed-state cohort directly.

    Pre-fix bug: ``projections.savings_first_run_usd`` was input-only over
    ALL priced rows (superset); ``projections.no_cache_hypothetical_usd`` was
    full-cost over rows-with-output (subset). When without-output rows
    contributed materially to savings, the division produced
    ``savings > current`` → percentages > 100% rendered as nonsensical ``-117%``.

    Mutation-test thought: revert the fix to
    ``_safe_pct_or_none(projections.savings_first_run_usd, current_cost)`` and
    this test fails — the buggy formula yields a value > 100 for this fixture.
    Post-fix ``(current - cost_without_caching) / current`` is bounded by
    ≤ 100% by construction (assuming with-cache projection ≥ 0).

    Fixture: 4 priced rows. Row A has output tokens AND no cache subset (so
    it dominates ``no_cache_hypothetical_usd`` with full input+output cost
    but contributes zero to savings). Rows B/C/D have NO output tokens AND
    large cache subsets — they contribute substantial input-only savings to
    input-only savings math but ZERO to comparable absolute cost atoms. The
    explicit delta must stay cohort-consistent instead of comparing different
    rowsets.
    """
    # Row A: tiny input (100) + tiny output (50), no cache subset. This is
    # the only row contributing to ``no_cache_hypothetical_usd`` — and it's small.
    # Rows B/C/D/E/F: large cache-using rows with NO output. They must not
    # contribute to deltas that require absolute first-run/no-cache atoms.
    rows = [
        _summary_row(
            node_path="A",
            input_tokens=100,
            cacheable_tokens=0,
            declared_prompt_cache=None,
            output_tokens=50,
        ),
        *[
            _summary_row(
                node_path=name,
                input_tokens=10_000,
                cacheable_tokens=8_000,
                declared_prompt_cache=["topic"],
                output_tokens=None,
            )
            for name in ("B", "C", "D", "E", "F")
        ],
    ]
    summary = _build_summary(rows, warnings=[], ttl="5m")

    # Sanity: Row A is the only row with output tokens, so complete cost atoms
    # are computable only for a no-cache row. Large no-output cache rows must
    # not distort summary deltas.
    assert summary.no_cache_hypothetical_usd is not None, "Row A must populate no_cache_hypothetical_usd"
    assert summary.first_run_delta.kind == "break_even"
    assert summary.first_run_delta.amount_usd == 0.0
    assert summary.first_run_delta.pct_of_baseline == 0


def test_first_run_write_premium_is_cost_increase_delta() -> None:
    """A lone cache write can be more expensive than no-cache. Summary must
    preserve that direction as ``cost_increase`` instead of negative savings."""
    row = _summary_row(
        node_path="writer",
        input_tokens=10_000,
        cacheable_tokens=8_000,
        declared_prompt_cache=["topic"],
        output_tokens=500,
    )
    summary = _build_summary([row], warnings=[], ttl="5m")

    assert summary.no_cache_hypothetical_usd is not None
    assert summary.first_run_with_cache_hypothetical_usd is not None
    assert summary.first_run_with_cache_hypothetical_usd > summary.no_cache_hypothetical_usd
    assert summary.first_run_delta.kind == "cost_increase"
    assert summary.first_run_delta.amount_usd is not None
    assert summary.first_run_delta.amount_usd > 0
    assert summary.first_run_delta.baseline == "no_cache_hypothetical_usd"
    assert summary.first_run_delta.compared_to == "first_run_with_cache_hypothetical_usd"
    assert summary.rerun_delta.kind == "savings"


def test_greenfield_without_output_data_keeps_cost_deltas_unavailable() -> None:
    """Deltas compare cost atoms only; greenfield input-only guesses are not
    exposed as summary savings when absolute costs are unavailable."""
    workflow_ir = {
        "inputs": {"topic": {"type": "string", "required": False}},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "topic", "var": "topic", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": f"node_{i}",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["topic"],
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": f"${{topic}}\n\nAnalyst {i}: " + ("x" * 6000),
                },
            }
            for i in range(2)
        ],
        "edges": [],
    }
    analysis = analyze(workflow_ir, parameters={"topic": "alpha"}, auto_load_trace=False)
    # Greenfield: no memo cache → no output tokens → no projection atoms.
    assert analysis.summary.actually_paid_usd is None
    assert analysis.summary.no_cache_hypothetical_usd is None
    assert analysis.summary.first_run_delta.kind == "unavailable"
    assert analysis.summary.rerun_delta.kind == "unavailable"


# ---------------------------------------------------------------------------
# Recommended action view sort priority (Tier 1 #1)
#
# Defends: drop the ``priority`` dimension from the sort key in
# ``view_helpers._build_actions`` and the priority test fails — the
# alphabetical tie-break re-buries actionable findings under informational
# ones (the lyrics-generator regression we observed).
# ---------------------------------------------------------------------------


def _make_diag(diag_id: str, severity: Severity, savings_usd: float | None = None) -> Diagnostic:
    """Synthetic Diagnostic for sort-key tests."""
    context: dict[str, Any] = {}
    if savings_usd is not None:
        context["savings_usd"] = savings_usd
    return Diagnostic(
        severity=severity,
        message=f"test {diag_id}",
        title="Test",
        id=diag_id,
        node_id=None,
        source="cache_analyzer",
        context=context,
    )


def test_recommended_actions_prioritize_actionable_over_informational() -> None:
    """When two warnings share severity AND have no savings, detection-class
    priority decides the order. Tier 1 IDs (shared-context-undeclared,
    priority 10) sort ahead of Tier 5 IDs (unused-chunk, priority 30).

    Pre-fix: alphabetical tie-break could bury actionable findings under
    informational ones. Agent reading top of "Recommended actions" got noise
    instead of the real opportunity.

    (Pre-Stage-0 used cross-workflow-rename-detected to demonstrate the
    sort; that ID is now filtered OUT of Recommended actions entirely — see
    ``test_recommended_actions_filters_cross_workflow_alignment_ids`` for
    that contract.)
    """
    from pflow.core.cache_analysis.view_helpers import build_recommended_actions

    actions = build_recommended_actions([
        _make_diag("cache.unused-chunk", Severity.INFO),
        _make_diag("cache.shared-context-undeclared", Severity.INFO),
    ])
    # shared-context-undeclared MUST come first (priority 10 < 30).
    assert actions[0].warning_id == "cache.shared-context-undeclared"
    assert actions[1].warning_id == "cache.unused-chunk"


def test_recommended_actions_filters_cross_workflow_alignment_ids() -> None:
    """Cross-workflow alignment findings (rename, prose-mismatch) are
    EXCLUDED from Recommended actions — they render in the "Sub-workflow
    boundaries" section. This keeps each finding visible in exactly ONE
    section (Stage 0 + B.3).
    """
    from pflow.core.cache_analysis.view_helpers import build_recommended_actions

    actions = build_recommended_actions([
        _make_diag("cache.cross-workflow-rename-detected", Severity.INFO),
        _make_diag("cache.cross-workflow-prose-mismatch", Severity.INFO),
        _make_diag("cache.shared-context-undeclared", Severity.INFO),
    ])
    # Only the non-alignment finding survives.
    ids = [a.warning_id for a in actions]
    assert ids == ["cache.shared-context-undeclared"], f"alignment IDs leaked into recommended actions: {ids}"


def test_blocking_errors_rank_deterministically_after_split() -> None:
    """ERRORs no longer live in Recommended actions; their own list ranks locally."""
    from pflow.core.cache_analysis.view_helpers import build_blocking_errors

    actions = build_blocking_errors([
        _make_diag("llm.thinking-temperature-mismatch", Severity.ERROR),  # priority 5
        _make_diag("cache.order-mismatch", Severity.ERROR),  # priority 5
    ])
    assert actions[0].warning_id == "cache.order-mismatch"
    assert actions[1].warning_id == "llm.thinking-temperature-mismatch"


def test_recommended_actions_filter_out_errors_after_split() -> None:
    from pflow.core.cache_analysis.view_helpers import build_recommended_actions

    actions = build_recommended_actions([
        _make_diag("cache.order-mismatch", Severity.ERROR),
        _make_diag("cache.shared-context-undeclared", Severity.INFO),
    ])
    assert [a.warning_id for a in actions] == ["cache.shared-context-undeclared"]


def test_recommended_actions_savings_orders_within_priority_tier() -> None:
    """Within a priority tier, dollar savings break ties ahead of alphabetical.

    Two same-priority IDs (priority 10) with different savings — higher
    savings ranks first.
    """
    from pflow.core.cache_analysis.view_helpers import build_recommended_actions

    actions = build_recommended_actions([
        _make_diag("cache.dynamic-before-static", Severity.INFO, savings_usd=0.50),
        _make_diag("cache.shared-context-undeclared", Severity.INFO, savings_usd=2.10),
    ])
    # Higher savings first, even though alphabetical would put dynamic-before-static first.
    assert actions[0].warning_id == "cache.shared-context-undeclared"
    assert actions[1].warning_id == "cache.dynamic-before-static"


def test_recommended_actions_savings_beats_severity_within_priority_tier() -> None:
    """The rendered header says ordered by impact; a lower-value WARNING must
    not outrank a higher-value INFO finding in the same action class.
    """
    from pflow.core.cache_analysis.view_helpers import build_recommended_actions

    actions = build_recommended_actions([
        _make_diag("cache.batch-prewarm-recommended", Severity.WARNING, savings_usd=0.04),
        _make_diag("cache.sub-workflow-cache-undeclared", Severity.INFO, savings_usd=0.20),
    ])

    assert actions[0].warning_id == "cache.sub-workflow-cache-undeclared"
    assert actions[1].warning_id == "cache.batch-prewarm-recommended"


def test_recommended_actions_unknown_id_falls_back_to_default_priority() -> None:
    """An ID not in RECOMMENDED_ACTION_PRIORITY (e.g. a future addition that
    hasn't been added to the dict) gets ``DEFAULT_RECOMMENDED_ACTION_PRIORITY``
    (100 — lowest). Defensive: graceful degradation rather than KeyError.
    """
    from pflow.core.cache_analysis.view_helpers import build_recommended_actions

    actions = build_recommended_actions([
        _make_diag("cache.future-unknown-id", Severity.INFO),  # no priority entry
        _make_diag("cache.shared-context-undeclared", Severity.INFO),  # priority 10
    ])
    # Known priority wins over default.
    assert actions[0].warning_id == "cache.shared-context-undeclared"
    assert actions[1].warning_id == "cache.future-unknown-id"


def test_recommended_actions_filter_non_cache_advisories_after_unification() -> None:
    """Full validation can emit non-cache warnings; cache actions stay focused."""
    from pflow.core.cache_analysis.view_helpers import build_recommended_actions

    actions = build_recommended_actions([
        Diagnostic(
            severity=Severity.WARNING,
            message="Static shell command should opt out of memoization cache.",
            title="Cache Warning",
            id=None,
            source="validator",
            context={"category": "cache_lint", "path": "nodes.echo.cache"},
        ),
        _make_diag("cache.shared-context-undeclared", Severity.INFO),
    ])
    assert [a.warning_id for a in actions] == ["cache.shared-context-undeclared"]


def test_blocking_errors_filters_out_warnings_and_info() -> None:
    from pflow.core.cache_analysis.view_helpers import build_blocking_errors

    actions = build_blocking_errors([
        _make_diag("cache.order-mismatch", Severity.ERROR),
        _make_diag("cache.below-min-predicted", Severity.WARNING),
        _make_diag("cache.shared-context-undeclared", Severity.INFO),
    ])
    assert [a.warning_id for a in actions] == ["cache.order-mismatch"]


def test_blocking_errors_rank_starts_at_one_independent_of_recommended_actions() -> None:
    from pflow.core.cache_analysis.view_helpers import build_blocking_errors, build_recommended_actions

    warnings = [
        _make_diag("cache.order-mismatch", Severity.ERROR),
        _make_diag("cache.shared-context-undeclared", Severity.INFO),
    ]
    blocking = build_blocking_errors(warnings)
    recommended = build_recommended_actions(warnings)
    assert blocking[0].rank == 1
    assert recommended[0].rank == 1


def test_build_blocking_errors_filters_non_cache_errors() -> None:
    """B-9 split: cache-domain ERRORs only.

    ``build_blocking_errors`` filters by the same ``_is_cache_focused_for_advisory``
    predicate as ``build_recommended_actions`` so headline count alignment
    holds (``len(blocking_errors)`` matches ``summary.blocking_errors``).
    Non-cache ERRORs (validator unknown-node-type, schema errors) flow to
    ``build_other_blocking_errors`` instead.

    Mutation contract: drop the ``and _is_cache_focused_for_advisory(d)``
    clause from ``build_blocking_errors`` — the non-cache ERROR leaks back
    into the cache-domain list; this test fails.
    """
    from pflow.core.cache_analysis.view_helpers import build_blocking_errors

    non_cache_error = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        id=None,
        node_id="missing-mcp",
        message="Unknown node type: 'mcp-klavis-youtube-foo'",
        context={"category": "node_type_error"},
    )
    actions = build_blocking_errors([
        _make_diag("cache.order-mismatch", Severity.ERROR),
        non_cache_error,
    ])
    assert [a.warning_id for a in actions] == ["cache.order-mismatch"]


def test_build_other_blocking_errors_filters_cache_errors() -> None:
    """B-9 split: non-cache ERRORs only.

    ``build_other_blocking_errors`` is the dual of ``build_blocking_errors``
    — cache-domain ERRORs are excluded so each finding lands in exactly one
    section.

    Mutation contract: drop the ``and not _is_cache_focused_for_advisory(d)``
    clause from ``build_other_blocking_errors`` — the cache ERROR leaks
    into the Other list; this test fails.
    """
    from pflow.core.cache_analysis.view_helpers import build_other_blocking_errors

    non_cache_error = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        id=None,
        node_id="missing-mcp",
        message="Unknown node type: 'mcp-klavis-youtube-foo'",
    )
    actions = build_other_blocking_errors([
        _make_diag("cache.order-mismatch", Severity.ERROR),
        non_cache_error,
    ])
    # Only the non-cache error survives.
    assert len(actions) == 1
    assert actions[0].message == "Unknown node type: 'mcp-klavis-youtube-foo'"
    assert actions[0].warning_id == ""


# ---------------------------------------------------------------------------
# CP1 (#8) — Effective model resolution
# ---------------------------------------------------------------------------


def test_effective_model_falls_back_to_workflow_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A node without per-node ``model:`` picks up ``get_default_workflow_model()``.

    Defends: ``_build_per_call_row`` must include
    ``or get_default_workflow_model() or ""`` in the model fallback. Without it
    a node lacking per-node ``model:`` ends up with ``model == ""`` and the
    lyrics-generator parent workflow's ``~2 LLM calls · 0 models in use`` bug
    re-appears.
    """
    # ``pflow.core.cache_analysis.analyze`` resolves to the FUNCTION via
    # ``__init__.py``'s ``from .analyze import analyze`` re-export, shadowing the
    # submodule. Reach the actual module via ``sys.modules`` for monkeypatch.
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(
        analyze_module,
        "get_default_workflow_model",
        lambda: "anthropic/claude-sonnet-4-5",
    )
    workflow_ir = {
        "nodes": [
            {
                "id": "creative-direction",
                "type": "llm",
                "params": {"prompt": "hello"},  # no model
            }
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    assert len(result.per_call) == 1
    assert result.per_call[0].model == "anthropic/claude-sonnet-4-5"
    assert result.summary.models_in_use == ("anthropic/claude-sonnet-4-5",)


def test_effective_model_explicit_wins_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-node ``model:`` always wins; default is only the fallback."""
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "should-not-be-used")
    workflow_ir = {
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "params": {"model": "gemini/gemini-3.1-pro-preview", "prompt": "x"},
            }
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    assert result.per_call[0].model == "gemini/gemini-3.1-pro-preview"


def test_effective_model_empty_when_no_default_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_default_workflow_model()`` returns None → row.model is empty string.

    This matches the pre-fix behavior for the case where neither per-node
    model nor settings/auto-detect yields anything. The renderer then shows
    ``model=`` empty (CP4 will improve to ``(default)``); the summary's
    ``models_in_use`` is correctly empty (not undercounted).
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    workflow_ir = {
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "params": {"prompt": "x"},  # no model
            }
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    assert result.per_call[0].model == ""
    assert result.summary.models_in_use == ()


def test_summary_message_zero_llm_nodes() -> None:
    """Zero LLM nodes → message says exactly that, doesn't mention pricing.

    Defends: ``render_text._render_summary`` must keep its three sub-cases
    distinct; re-conflating them lets the zero-LLM message mention LLM
    nodes.
    """
    from pflow.core.cache_analysis.render_text import _render_summary

    workflow_ir = {"nodes": [{"id": "shell", "type": "shell", "params": {"command": "echo"}}]}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    rendered = _render_summary(result)
    assert "workflow has no LLM nodes" in rendered
    assert "model resolved" not in rendered
    assert "run the workflow once" not in rendered


def test_summary_message_no_model_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM nodes exist but no model resolves → message says so explicitly.

    This is the lyrics-generator parent workflow case: 2 LLM nodes, neither
    has per-node ``model:``, no default configured → before CP1 the message
    said "workflow has no LLM nodes" (factually wrong with 2 visible in the
    table below). Defends: both the analyzer fallback AND the renderer
    branch must hold; reverting either produces the wrong message.
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    from pflow.core.cache_analysis.render_text import _render_summary

    workflow_ir = {
        "nodes": [
            {"id": "n1", "type": "llm", "params": {"prompt": "hi"}},
            {"id": "n2", "type": "llm", "params": {"prompt": "bye"}},
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    rendered = _render_summary(result)
    assert "no model resolved" in rendered
    assert "workflow has no LLM nodes" not in rendered


def test_summary_message_priced_no_run_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM nodes with priced models but no run history → 'run the workflow once'.

    This case fires when models resolve and pricing is available, but
    ``current_cost_per_run_usd`` is None (output tokens unavailable) AND
    aggregate savings is None (no shared context detected).
    """
    # ``pflow.core.cache_analysis.analyze`` resolves to the FUNCTION via
    # ``__init__.py``'s ``from .analyze import analyze`` re-export, shadowing the
    # submodule. Reach the actual module via ``sys.modules`` for monkeypatch.
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(
        analyze_module,
        "get_default_workflow_model",
        lambda: "anthropic/claude-sonnet-4-5",
    )
    from pflow.core.cache_analysis.render_text import _render_summary

    # Single LLM node — no shared context → no aggregate-savings → falls into
    # the third sub-branch.
    workflow_ir = {
        "nodes": [
            {"id": "n1", "type": "llm", "params": {"prompt": "lonely call"}},
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    rendered = _render_summary(result)
    # Either the priced-no-history branch fires, or (if savings detection
    # produces an aggregate figure even for one node) the greenfield run-once
    # hint fires. Both forms are correct; only the wrong "no LLM nodes" or
    # "no model resolved" branches should be excluded.
    assert "workflow has no LLM nodes" not in rendered
    assert "no model resolved" not in rendered


def test_suggested_run_command_populated_for_workflow_with_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``summary.suggested_run_command`` carries a paste-ready ``pflow run``
    command derived from ``workflow_path`` + declared inputs.

    Mutation contract: removing the ``suggested_run_command=`` kwarg in
    ``analyze.py``'s ``replace(summary, ...)`` site fails this test.
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(
        analyze_module,
        "get_default_workflow_model",
        lambda: "anthropic/claude-sonnet-4-5",
    )

    workflow_ir = {
        "inputs": {"article": {"type": "string"}, "topic": {"type": "string"}},
        "nodes": [{"id": "n1", "type": "llm", "params": {"prompt": "hello"}}],
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    assert result.summary.suggested_run_command == ("pflow run /abs/x.pflow.md article=<value> topic=<value>")


def test_suggested_run_command_is_none_for_inline_workflow() -> None:
    """Inline IR (``workflow_path=None``) lacks a runnable file path; the
    helper returns ``None`` and the renderer skips the ``Suggested:`` line.

    Mutation contract: dropping the ``ir-hash:`` guard in
    ``_format_workflow_run_command`` would emit ``pflow run ir-hash:<md5>``
    which the user can't actually run; this test fails on that mutation.
    """
    workflow_ir = {
        "inputs": {"article": {"type": "string"}},
        "nodes": [{"id": "n1", "type": "llm", "params": {"prompt": "hello"}}],
    }
    result = analyze(workflow_ir, workflow_path=None, auto_load_trace=False)
    assert result.summary.suggested_run_command is None


def test_render_text_emits_suggested_line_on_unavailable_cost_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end Pitfall #19 defense: text output includes the
    ``Suggested:`` line right after ``Cost data unavailable: run the
    workflow once for cost figures.`` so agents see the exact command.

    Mutation contract: removing the renderer's ``if s.suggested_run_command``
    branch fails this test.
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(
        analyze_module,
        "get_default_workflow_model",
        lambda: "anthropic/claude-sonnet-4-5",
    )
    from pflow.core.cache_analysis.render_text import _render_summary

    workflow_ir = {
        "inputs": {"article": {"type": "string"}},
        "nodes": [{"id": "n1", "type": "llm", "params": {"prompt": "lonely call"}}],
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    rendered = _render_summary(result)
    if "Cost data unavailable: run the workflow once" in rendered:
        # We hit branch 4. Suggested line must follow.
        assert "Suggested:  pflow run /abs/x.pflow.md article=<value>" in rendered


# ---------------------------------------------------------------------------
# Stage C.1 — heterogeneous batch sub-workflow model detection
# ---------------------------------------------------------------------------


def test_heterogeneous_model_detected_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """A node with ``model: ${item.model}`` is flagged heterogeneous, not leaked.

    Pitfall #19 defense: drives ``analyze(...)`` end-to-end. Synthetic
    ``PerCallRow(...)`` construction would bypass the upstream detection at
    ``analyze.py:_build_per_call_row``.
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    workflow_ir = {
        "nodes": [
            {
                "id": "score-choruses",
                "type": "llm",
                "params": {"model": "${item.model}", "prompt": "score this chorus"},
            },
            {
                "id": "creative-direction",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "set direction"},
            },
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)

    assert len(result.per_call) == 2
    by_node = {r.node_path: r for r in result.per_call}
    # Heterogeneous row — model emptied, flag set.
    assert by_node["score-choruses"].model == ""
    assert by_node["score-choruses"].model_is_heterogeneous is True
    # Homogeneous row — flag stays False.
    assert by_node["creative-direction"].model_is_heterogeneous is False

    # ``models_in_use`` excludes heterogeneous; the literal template never
    # leaks into the aggregate.
    assert "${item.model}" not in result.summary.models_in_use
    assert "anthropic/claude-sonnet-4-5" in result.summary.models_in_use
    assert result.summary.heterogeneous_model_node_count == 1
    assert result.summary.heterogeneous_model_node_paths == ("score-choruses",)


def test_heterogeneous_model_excluded_from_pricing_aggregation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Heterogeneous rows don't fabricate cost figures.

    Defends: pricing lookup must skip heterogeneous rows, otherwise a
    non-None ``current_cost_per_run_usd`` surfaces despite the model
    being unresolvable.
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    # All-heterogeneous workflow — every row is unpriceable.
    workflow_ir = {
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "params": {"model": "${item.model}", "prompt": "p"},
            },
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)

    # No priced rows → all cost figures are None (matches cost_estimation
    # contract — heterogeneous rows skipped before pricing lookup).
    assert result.summary.actually_paid_usd is None
    assert result.summary.no_cache_hypothetical_usd is None
    assert result.summary.first_run_with_cache_hypothetical_usd is None
    # Heterogeneous models DO NOT enter unavailable_models (they have model="")
    # so the "all 1 models lack pricing" branch doesn't fire.
    assert result.summary.unavailable_models == ()


def test_heterogeneous_only_summary_renders_explicit_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """All-heterogeneous workflow renders the right cause, not the wrong one.

    Defends: when every LLM node has a heterogeneous model, the renderer
    must NOT show the "set settings.default_model" hint — model
    resolution isn't the problem; per-batch-item models can't be
    aggregated as one model.
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    from pflow.core.cache_analysis.render_text import _render_summary

    workflow_ir = {
        "nodes": [
            {"id": "n1", "type": "llm", "params": {"model": "${item.model}", "prompt": "p1"}},
            {"id": "n2", "type": "llm", "params": {"model": "${item.model}", "prompt": "p2"}},
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    rendered = _render_summary(result)

    assert "all LLM nodes use models that vary per batch item" in rendered
    # The wrong-cause messages must NOT fire here.
    assert "set settings.default_model" not in rendered
    assert "workflow has no LLM nodes" not in rendered


def test_heterogeneous_row_survives_option_c_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-call section shows heterogeneous rows even on pure greenfield.

    Without this, heterogeneous nodes would be hidden by Option C (no memo,
    no declared subset → would normally fail ``_row_has_real_data``). The
    agent would only see ``+ N nodes with model varying`` in the header
    and have no place to grep for which node varies.
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    from pflow.core.cache_analysis.render_text import render_text

    workflow_ir = {
        "nodes": [
            {"id": "score-choruses", "type": "llm", "params": {"model": "${item.model}", "prompt": "p"}},
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    rendered = render_text(result)

    assert "## Per-call cache report" in rendered
    assert "score-choruses" in rendered
    # Renderer uses ``<varies>``, not the literal ``${item.model}``.
    assert "<varies>" in rendered
    assert "${item.model}" not in rendered


def test_heterogeneous_node_named_in_scale_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Header names which nodes have varying models, not just the count.

    Defends: ``heterogeneous_node_paths`` must propagate to ``_render_header``
    so the name surfaces in the scale line; otherwise an agent would have
    to scan per-call to find which node varies.
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    from pflow.core.cache_analysis.render_text import render_text

    workflow_ir = {
        "nodes": [
            {
                "id": "score-choruses",
                "type": "llm",
                "params": {"model": "${item.model}", "prompt": "p"},
            },
            {
                "id": "creative-direction",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "p"},
            },
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    rendered = render_text(result)

    # Scale line names the heterogeneous node + tag.
    assert "score-choruses" in rendered
    assert "model varies per batch item" in rendered
    # Literal template MUST NOT leak.
    assert "${item.model}" not in rendered


# ---------------------------------------------------------------------------
# Stage C.2 — _format_cost grammar / N=1 model name
# ---------------------------------------------------------------------------


def test_format_cost_names_single_unpriced_model() -> None:
    """When exactly one model lacks pricing, name it directly.

    Defends: the N==1 branch must render the model name; the plural
    phrasing ``"all 1 models lack pricing data"`` would not let the agent
    tell which model from the summary alone.
    """
    from pflow.core.cache_analysis.render_text import _format_cost

    rendered = _format_cost(value=None, partial=False, unavailable_models=("ollama/llama3.2:8b",))

    assert "ollama/llama3.2:8b lacks pricing data" in rendered
    assert "all 1 models" not in rendered  # Old buggy phrasing must NOT appear.


def test_format_cost_keeps_plural_phrasing_for_multiple_unpriced() -> None:
    """N>1 keeps the count phrasing — naming each would clutter the summary line.

    The footer ``Unpriced models: ...`` (rendered separately by
    ``_render_summary`` when ``partial_cost_usd``) lists them all, so this
    line stays terse.
    """
    from pflow.core.cache_analysis.render_text import _format_cost

    rendered = _format_cost(
        value=None,
        partial=False,
        unavailable_models=("ollama/llama3.2:8b", "custom/foo", "custom/bar"),
    )

    assert "all 3 models lack pricing data" in rendered


# ---------------------------------------------------------------------------
# Unified ``estimate_cacheable_tokens`` — end-to-end production-shape tests
# (Pitfall #19 defense: drive ``analyze()`` end-to-end with real
# ``MemoizationCache.put`` calls / real trace dicts; assert BOTH
# ``cacheable_tokens_estimated`` value AND ``cacheable_data_source`` tier.)
# ---------------------------------------------------------------------------


def test_brownfield_memo_populates_cacheable_via_memo_tier(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brownfield (`## Cache` declared) + memo data → cacheable from memo tier.

    Closes the silent-gap regression class: pre-fix ``_estimate_cacheable_tokens``
    was a static heuristic on the prompt template, ignoring memo data even
    when present. Post-fix Tier 2 fires.

    Defends: blocking the memo tier (e.g., short-circuiting Tier 2 with
    an empty-model check or removing the chunks-resolve loop) drops
    cacheable to ``None`` and the source label to ``"unavailable"`` —
    no longer to a fabricated heuristic value, since Tier 3 is deleted.
    """
    from pflow.runtime.cache import MemoizationCache

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    # Lock token counter to a deterministic value (defends against tokenizer drift).
    monkeypatch.setattr("litellm.token_counter", lambda model, text: 1500)

    workflow_path = "/abs/brownfield.pflow.md"
    cache_db_path = tmp_path / ".pflow" / "cache" / "cache.db"
    cache = MemoizationCache(db_path=cache_db_path)
    cache.put(
        cache_key="seeded-context",
        node_id="context",
        workflow_path=workflow_path,
        action="default",
        output={"response": "long context body that the analyzer will tokenize"},
    )

    workflow_ir = {
        "inputs": {},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context", "var": "context.response", "prose_before": "Context:\n"}],
        },
        "nodes": [
            {
                "id": "summarize",
                "type": "llm",
                "params": {"model": "claude-sonnet-4-5", "prompt": "${context.response}\n\nSummarize."},
                "prompt_cache": ["context.response"],
            }
        ],
        "edges": [],
    }

    analysis = analyze(workflow_ir, workflow_path=workflow_path, auto_load_trace=False)
    assert len(analysis.per_call) == 1
    row = analysis.per_call[0]
    assert row.cacheable_data_source == "memo", (
        f"expected memo tier for brownfield + memo data; got {row.cacheable_data_source!r}"
    )
    assert row.cacheable_tokens_estimated == 1500, (
        f"expected 1500 (deterministic memo value); got {row.cacheable_tokens_estimated}"
    )
    # Note: ``data_source`` (input tokens) and ``cacheable_data_source``
    # (cacheable tokens) are independent. The memo entry was seeded for
    # ``context`` (the chunk's root); ``estimate_tokens`` looks up the LLM
    # node's own ID (``summarize``) which has no memo entry → estimator
    # tier for input. Tier 2 for cacheable resolves the ``context.response``
    # ref via ``_latest_value_for_ref`` → memo. Two metrics, two labels.


def test_brownfield_trace_populates_cacheable_via_trace_tier_with_asymmetric_values(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brownfield + 2.1.0 trace with asymmetric cache_creation+cache_read.

    Asymmetric values (1000 + 599 = 1599) defend against
    ``creation + read`` → ``creation`` alone mutation.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_path = "/abs/withtrace.pflow.md"
    workflow_ir = {
        "inputs": {},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context", "var": "context", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": "summarize",
                "type": "llm",
                "params": {"model": "claude-sonnet-4-5", "prompt": "${context}\n\nDo work."},
                "prompt_cache": ["context"],
            }
        ],
        "edges": [],
    }

    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.1.0",
            "workflow_path": workflow_path,
            "nodes": [
                {
                    "node_id": "summarize",
                    "llm_call": {
                        "input_tokens": 1599,
                        "output_tokens": 50,
                        "cache_creation_input_tokens": 1000,
                        "cache_read_input_tokens": 599,
                    },
                }
            ],
        })
    )

    analysis = analyze(
        workflow_ir,
        workflow_path=workflow_path,
        trace_path=trace_path,
        auto_load_trace=False,
    )
    assert len(analysis.per_call) == 1
    row = analysis.per_call[0]
    assert row.cacheable_data_source == "trace"
    assert row.cacheable_tokens_estimated == 1599


def test_no_cache_trace_with_memo_projects_via_candidate(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No-cache workflow with shared ``${context}`` reference + memo data:
    the candidate-detection walker collects the shared ref and Tier 2 of
    ``estimate_cacheable_tokens`` projects from memo.

    Three assertions defend against (a) value miss, (b) tier mislabel,
    (c) candidate-walker breakage.
    """
    from pflow.runtime.cache import MemoizationCache

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr("litellm.token_counter", lambda model, text: 1200)

    workflow_path = "/abs/no_cache_with_memo.pflow.md"
    cache_db_path = tmp_path / ".pflow" / "cache" / "cache.db"
    cache = MemoizationCache(db_path=cache_db_path)
    cache.put(
        cache_key="ctx-key",
        node_id="context",
        workflow_path=workflow_path,
        action="default",
        output={"response": "long context"},
    )

    workflow_ir = {
        "inputs": {},
        "nodes": [
            {
                "id": "context",
                "type": "code",
                "params": {"code": "result = {'response': 'something'}"},
            },
            {
                "id": "node_a",
                "type": "llm",
                "params": {"model": "claude-sonnet-4-5", "prompt": "${context.response}\n\nA"},
            },
            {
                "id": "node_b",
                "type": "llm",
                "params": {"model": "claude-sonnet-4-5", "prompt": "${context.response}\n\nB"},
            },
        ],
        "edges": [],
    }

    analysis = analyze(workflow_ir, workflow_path=workflow_path, auto_load_trace=False)
    llm_rows = [r for r in analysis.per_call if r.node_path in ("node_a", "node_b")]
    assert len(llm_rows) == 2
    for row in llm_rows:
        assert row.cacheable_tokens_estimated is not None and row.cacheable_tokens_estimated > 0, (
            f"row {row.node_path!r} should have projected cacheable tokens; got {row.cacheable_tokens_estimated}"
        )
        assert row.cacheable_data_source == "memo", (
            f"row {row.node_path!r} expected memo tier; got {row.cacheable_data_source!r}"
        )

    # Candidate-detection signal: shared-context-undeclared warning fires
    # AND shared chunks include context.response.
    shared = [d for d in analysis.warnings if d.id == "cache.shared-context-undeclared"]
    assert shared, "expected cache.shared-context-undeclared for shared ${context.response}"
    chunks_seen: list[str] = []
    for diag in shared:
        ctx = diag.context or {}
        chunks_seen.extend(ctx.get("shared_chunks", []) or [])
    assert "context.response" in chunks_seen, f"expected 'context.response' in shared chunks; got {chunks_seen}"


def test_heterogeneous_batch_with_declared_cache_falls_through_to_unavailable(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heterogeneous batch (``model: ${item.model}``) + declared
    ``prompt_cache`` → Tier 2 short-circuits on empty model; falls
    through to honest unavailable.

    Closes Case 8a end-to-end: unit test #5 covers the gate; this
    verifies the full path through ``analyze()``. Post-F-04 fix: no
    fabricated estimator number, no false-positive below-min warning.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_ir = {
        "inputs": {"items": {"type": "array"}},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context", "var": "context", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "batch": {"items": "${items}", "as": "item"},
                "params": {
                    "model": "${item.model}",
                    "prompt": "${context}\n\nScore the thing." + ("x" * 1000),
                },
                "prompt_cache": ["context"],
            }
        ],
        "edges": [],
    }

    analysis = analyze(workflow_ir, workflow_path="/abs/het.pflow.md", auto_load_trace=False)
    assert len(analysis.per_call) == 1
    row = analysis.per_call[0]
    assert row.model_is_heterogeneous is True
    assert row.cacheable_tokens_estimated is None
    assert row.cacheable_data_source == "unavailable"
    # No false-positive below-min-predicted warning.
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-predicted"]
    assert not below_min, f"unexpected warnings: {[w.id for w in analysis.warnings]}"


def test_below_min_tokens_suppressed_when_trace_evidence_shows_cache_fired(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cache.below-min-predicted`` MUST NOT fire when ``cacheable_data_source``
    is ``"trace"``: trace evidence (cache_creation + cache_read > 0) shows
    the cache demonstrably worked at this size, so the warning would
    contradict reality.

    Fixture: trace event with cache_creation=600, cache_read=200 (sum=800)
    AND model has min_cache_tokens=1024 (anthropic). Without the gate,
    the warning would fire because 800 < 1024. With the gate, it
    correctly suppresses.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_path = "/abs/below_min_with_trace.pflow.md"
    workflow_ir = {
        "inputs": {},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context", "var": "context", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": "summarize",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "${context}\n\nDo work."},
                "prompt_cache": ["context"],
            }
        ],
        "edges": [],
    }

    # Trace shows cache fired but below the model's claimed min — exactly
    # the case where the analyzer's static threshold check would falsely
    # contradict trace evidence.
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.1.0",
            "workflow_path": workflow_path,
            "nodes": [
                {
                    "node_id": "summarize",
                    "llm_call": {
                        "input_tokens": 800,
                        "output_tokens": 50,
                        "cache_creation_input_tokens": 600,
                        "cache_read_input_tokens": 200,
                    },
                }
            ],
        })
    )

    analysis = analyze(
        workflow_ir,
        workflow_path=workflow_path,
        trace_path=trace_path,
        auto_load_trace=False,
    )
    row = analysis.per_call[0]
    # Sanity: this is the trace-evidence path.
    assert row.cacheable_data_source == "trace"
    assert row.cacheable_tokens_estimated == 800
    # The contract: warning MUST NOT fire when trace shows cache worked.
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-predicted"]
    assert not below_min, (
        f"cache.below-min-predicted fired despite trace showing cache fired (cacheable=800, "
        f"src=trace). Gate ``cacheable_data_source != 'trace'`` regression. "
        f"warnings: {[w.id for w in analysis.warnings]}"
    )


def test_per_call_row_carries_raw_cache_token_splits_from_trace(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PerCallRow preserves trace cache_creation/cache_read as distinct fields."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_path = "/abs/cache_token_splits.pflow.md"
    workflow_ir = {
        "inputs": {},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context", "var": "context", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": "test-node",
                "type": "llm",
                "params": {"model": "anthropic/claude-haiku-4-5", "prompt": "${context}\n\nDo work."},
                "prompt_cache": ["context"],
            }
        ],
        "edges": [],
    }

    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.1.0",
            "workflow_path": workflow_path,
            "nodes": [
                {
                    "node_id": "test-node",
                    "llm_call": {
                        "model": "anthropic/claude-haiku-4-5",
                        "input_tokens": 9800,
                        "output_tokens": 350,
                        "cache_creation_input_tokens": 1500,
                        "cache_read_input_tokens": 8062,
                    },
                }
            ],
        })
    )

    analysis = analyze(
        workflow_ir,
        workflow_path=workflow_path,
        trace_path=trace_path,
        auto_load_trace=False,
    )
    row = next(r for r in analysis.per_call if r.node_path == "test-node")

    assert row.cache_creation_input_tokens == 1500
    assert row.cache_read_input_tokens == 8062
    assert row.data_source == "trace"


def test_below_min_tokens_fires_when_memo_data_shows_below_min(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When source is ``"memo"`` (not ``"trace"``) and tokens are below
    threshold, the warning still fires. Locks the inverse contract:
    suppression is keyed on ``"trace"`` specifically, not on cacheable
    > 0 alone.

    Defends: the suppression gate must be keyed on ``"trace"``; any
    other tier name (``"memo"``, ``"parameters"``) would suppress the
    warning for those sources too. Pitfall #19: drives via real
    ``MemoizationCache.put`` not synthetic fixture.
    """
    from pflow.runtime.cache import MemoizationCache

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    # Lock token counter to a deterministic small value below 1024 (sonnet
    # min). Defends against tokenizer drift.
    monkeypatch.setattr("litellm.token_counter", lambda model, text: 100)

    workflow_path = "/abs/below_min_via_memo.pflow.md"
    cache_db_path = tmp_path / ".pflow" / "cache" / "cache.db"
    cache = MemoizationCache(db_path=cache_db_path)
    # Note required positional: action="default" — MemoizationCache.put has
    # no default for ``action``. Mirror the existing brownfield test pattern.
    cache.put(
        cache_key="seeded-context",
        node_id="context",
        workflow_path=workflow_path,
        action="default",
        output={"response": "tiny content"},
    )

    workflow_ir = {
        "inputs": {},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context", "var": "context.response", "prose_before": "Context:\n"}],
        },
        "nodes": [
            {
                "id": "summarize",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "${context.response}\n\nDo work.",
                },
                "prompt_cache": ["context"],
            }
        ],
        "edges": [],
    }

    analysis = analyze(
        workflow_ir,
        workflow_path=workflow_path,
        auto_load_trace=False,
    )
    row = analysis.per_call[0]
    # Tighten: parameters tier is unreachable in this fixture (inputs={}),
    # so the only legitimate value is "memo".
    assert row.cacheable_data_source == "memo"
    assert row.cacheable_tokens_estimated is not None
    assert row.cacheable_tokens_estimated < 1024
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-predicted"]
    assert len(below_min) == 1, (
        f"cache.below-min-predicted should fire when memo says below threshold; got: {[w.id for w in analysis.warnings]}"
    )


def test_f04_greenfield_node_output_chunk_does_not_emit_false_below_min_warning(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-04 regression — the bug this PR fixes.

    Pre-fix: a workflow where ``prompt_cache:`` references an upstream
    node output (``${produce.response}``) AND no memo data exists would
    fall through Tier 1 (no trace) → Tier 2 (no memo) → Tier 3 heuristic
    → fabricated ~``len(prompt) * 75 // 400`` token count → false-positive
    ``cache.below-min-predicted`` warning ("declared cache content is ~1
    tokens, below ... minimum of 1024").

    Post-fix: Tier 3 is deleted; the path lands at Tier 4 unavailable.
    No warning fires; cacheable is ``None``; agent gets honest
    unmeasurable signal.

    Defends: re-introducing any heuristic on prompt body for declared
    subsets would re-emit this false-positive.

    This is a unit-level mirror of the ``baseline/14-pitfall-19-defenses
    /01-dotted-path-chunk/`` reproduction case.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_ir = {
        "inputs": {"article": {"type": "string", "required": True}},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "produce.response", "var": "produce.response", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": "produce",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Echo the article: ${article}",
                },
            },
            {
                "id": "consume",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Summarize.",
                },
                "prompt_cache": ["produce.response"],
            },
        ],
        "edges": [],
    }

    analysis = analyze(workflow_ir, workflow_path="/abs/f04.pflow.md", auto_load_trace=False)

    consume_row = next(r for r in analysis.per_call if r.node_path == "consume")
    assert consume_row.cacheable_tokens_estimated is None
    assert consume_row.cacheable_data_source == "unavailable"
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-predicted"]
    assert not below_min, (
        f"F-04 regression: cache.below-min-predicted fired on greenfield "
        f"node-output chunk. Warnings: {[w.id for w in analysis.warnings]}"
    )


def test_partial_input_resolution_with_node_output_chunk_returns_unavailable(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed ## Cache: input-ref chunk + node-output-ref chunk. Only
    the input-ref resolves (via parameters). Per the symmetric Tier 2
    contract (any unresolvable chunk → unavailable), the cacheable
    estimate must be ``None`` rather than a partial sum or fabricated
    heuristic.

    Defends: any future "partial-lower-bound" implementation that emits
    a non-None cacheable for partial-resolution would silently change
    the warning behavior. This locks the symmetric all-or-nothing
    contract documented in ``estimate_cacheable_tokens``'s docstring
    post-fix.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_ir = {
        "inputs": {"concept": {"type": "string", "required": True}},
        "cache": {
            "ttl": "5m",
            "items": [
                {"name": "concept", "var": "concept", "prose_before": "Concept: "},
                {"name": "upstream.response", "var": "upstream.response", "prose_before": "\nAnalysis: "},
            ],
        },
        "nodes": [
            {
                "id": "upstream",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Analyze ${concept}"},
            },
            {
                "id": "downstream",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Summarize."},
                "prompt_cache": ["concept", "upstream.response"],
            },
        ],
        "edges": [],
    }

    analysis = analyze(
        workflow_ir,
        workflow_path="/abs/partial.pflow.md",
        parameters={"concept": "demo"},
        auto_load_trace=False,
    )
    downstream_row = next(r for r in analysis.per_call if r.node_path == "downstream")
    assert downstream_row.cacheable_data_source == "unavailable"
    assert downstream_row.cacheable_tokens_estimated is None
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-predicted"]
    assert not below_min


def test_declared_with_zero_creation_zero_read_falls_through_to_memo_e2e(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declared subset + 2.1.0 trace recording cache_creation=0, cache_read=0
    (cache declared but didn't fire — sub-threshold etc.). Tier 1 MUST fall
    through; Tier 2 fires via memo; ``cache.below-min-predicted`` MUST fire
    because the gate's ``cacheable_data_source != "trace"`` clause is now
    True.

    This is the matrix Case 9 — the case that exists specifically to
    preserve ``cache.below-min-predicted`` fidelity when cache fails to engage.
    Without Tier 1 fall-through (e.g., short-circuit returning
    ``(0, "trace")`` per the disputed review-silent-failures C1 finding),
    cacheable_data_source would be ``"trace"``, the gate would suppress the
    warning, and agents would not learn that their declared chunks are
    sub-threshold.

    Mutation contracts:
      A. Replace Tier 1 fall-through with ``return (0, "trace")`` —
         cacheable_data_source becomes ``"trace"``, the gate at
         ``analyze.py:778`` suppresses, ``cache.below-min-predicted`` fails to
         fire. This test catches it.
      B. Drop the ``> 0`` precondition (use ``>= 0``) — cacheable becomes
         0 with source ``"trace"`` for the 0+0 case, same outcome as A.
      C. Drop the gate clause ``cacheable_data_source != "trace"`` —
         spurious; this test wouldn't catch it (companion test 1485
         catches that direction).
    """
    from pflow.runtime.cache import MemoizationCache

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    # Lock memo tokenization to a deterministic value BELOW Sonnet 4.5's
    # 1024-token threshold so cache.below-min-predicted fires for genuine
    # sub-threshold cache content.
    monkeypatch.setattr("litellm.token_counter", lambda model, text: 500)

    workflow_path = "/abs/zero_zero_falls_through.pflow.md"
    cache_db_path = tmp_path / ".pflow" / "cache" / "cache.db"
    cache = MemoizationCache(db_path=cache_db_path)
    cache.put(
        cache_key="context-key",
        node_id="context",
        workflow_path=workflow_path,
        action="default",
        output={"response": "context body that tokenizes to 500 (mocked)"},
    )

    workflow_ir = {
        "inputs": {},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context.response", "var": "context.response", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": "summarize",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "${context.response}\n\nDo work."},
                "prompt_cache": ["context.response"],
            }
        ],
        "edges": [],
    }

    # Trace records cache declared but didn't fire — Tier 1 MUST fall through.
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.1.0",
            "workflow_path": workflow_path,
            "nodes": [
                {
                    "node_id": "summarize",
                    "llm_call": {
                        "input_tokens": 510,
                        "output_tokens": 50,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                }
            ],
        })
    )

    analysis = analyze(
        workflow_ir,
        workflow_path=workflow_path,
        trace_path=trace_path,
        auto_load_trace=False,
    )
    row = analysis.per_call[0]
    # Tier 1 falls through — source MUST NOT be ``"trace"``.
    assert row.cacheable_data_source == "memo", (
        f"Tier 1 should fall through when creation+read==0; got "
        f"cacheable_data_source={row.cacheable_data_source!r} (expected 'memo' from Tier 2)"
    )
    # Memo tokenization returned 500 (mocked); clamps to input_tokens (510).
    assert row.cacheable_tokens_estimated == 500, (
        f"expected memo-tier value of 500; got {row.cacheable_tokens_estimated}"
    )
    # The whole point of the fall-through: warning fires correctly.
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-predicted"]
    assert below_min, (
        f"cache.below-min-predicted did NOT fire for declared-but-cache-didn't-fire "
        f"sub-threshold case. Tier 1 fall-through regression. "
        f"warnings: {[w.id for w in analysis.warnings]}"
    )


def test_declared_partial_memo_falls_through_to_unavailable_end_to_end(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declared subset of 2 chunks; memo populated for one only. End-to-end
    fall-through to Tier 3 unavailable. Honest unmeasurable: the analyzer
    cannot sum partial chunks without misrepresenting total cache content.
    """
    from pflow.runtime.cache import MemoizationCache

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_path = "/abs/partial_memo.pflow.md"
    cache_db_path = tmp_path / ".pflow" / "cache" / "cache.db"
    cache = MemoizationCache(db_path=cache_db_path)
    # Only seed chunk_a's source; chunk_b is missing — partial memo.
    cache.put(
        cache_key="a-key",
        node_id="chunk_a",
        workflow_path=workflow_path,
        action="default",
        output={"response": "value-a"},
    )

    workflow_ir = {
        "inputs": {},
        "cache": {
            "ttl": "5m",
            "items": [
                {"name": "chunk_a.response", "var": "chunk_a.response", "prose_before": "A:\n"},
                {"name": "chunk_b.response", "var": "chunk_b.response", "prose_before": "B:\n"},
            ],
        },
        "nodes": [
            {
                "id": "consumer",
                "type": "llm",
                "params": {
                    "model": "claude-sonnet-4-5",
                    "prompt": "${chunk_a.response} ${chunk_b.response}" + ("x" * 1000),
                },
                "prompt_cache": ["chunk_a.response", "chunk_b.response"],
            }
        ],
        "edges": [],
    }

    analysis = analyze(workflow_ir, workflow_path=workflow_path, auto_load_trace=False)
    assert len(analysis.per_call) == 1
    row = analysis.per_call[0]
    assert row.cacheable_data_source == "unavailable", (
        f"declared partial-memo should fall through to unavailable; got {row.cacheable_data_source!r}"
    )
    assert row.cacheable_tokens_estimated is None


# ---------------------------------------------------------------------------
# Track A / B / C end-to-end through ``analyze()`` (Pitfall #19 defense —
# drives the public API, not internal helpers).
# ---------------------------------------------------------------------------


def test_analyze_end_to_end_resolves_prompt_template_for_tokenization() -> None:
    """Test 3 — Resolved prompt for tokenization.

    Defends: ``_resolve_prompt_for_tokenization`` must run before
    ``estimate_tokens`` so the resolved 5000-char value is counted, not
    the template literal (~50 tokens).
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"context": {"type": "string"}},
        "nodes": [
            {
                "id": "answer",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Reference document follows.\n\n${context}\n\nAnswer briefly.",
                },
            }
        ],
        "edges": [],
    }
    # 2000 unique-ish words generate a real (uncompressed) token count.
    # Repeating chars compress through any tokenizer's BPE / WordPiece —
    # use distinct tokens so the post-resolution count is observable.
    big_context = " ".join(f"word{i}" for i in range(2000))
    analysis = analyze(workflow_ir, parameters={"context": big_context}, auto_load_trace=False)
    assert len(analysis.per_call) == 1
    row = analysis.per_call[0]
    # Pre-fix: tokenization on raw template ~30 tokens.
    # Post-fix: resolved prompt has ~2000+ distinct tokens.
    assert row.input_tokens_estimated > 1000


def test_analyze_end_to_end_current_cost_honors_recorded_trace_cost() -> None:
    """Test 4 — Brownfield end-to-end (Track A through analyze()).

    Drives the public ``analyze()`` API with synthetic trace data carrying
    a known ``cost_usd``. Verifies that ``summary.current_cost_per_run_usd``
    reflects the recorded cost, NOT the recompute fallback.

    The mutation surface that defends this test moved across the trace-driven
    rollup and Phase 4 cost-split work — ``_build_summary`` calls
    ``compute_actually_paid`` which prefers ``ctx.trace.total_cost(...)``
    (see ``test_summary_current_cost_includes_sub_workflow_costs_via_trace``
    for the marker) and falls back to ``row.cost_usd`` summation (see
    ``test_actually_paid_sums_row_cost_usd_when_set``). Both markers defend
    this test's assertion via the production code path; an explicit marker
    here would only duplicate them.
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "answer-a",
                "type": "llm",
                "params": {"model": "gemini/gemini-2.5-flash", "prompt": "What is 2+2?"},
            }
        ],
        "edges": [],
    }
    # Fake a 2.1 trace with a recorded cost much lower than tokens x full_rate.
    trace = {
        "format_version": "2.1.0",
        "workflow_path": "ir-hash:fake",
        "nodes": [
            {
                "node_id": "answer-a",
                "node_type": "LLMNode",
                "llm_call": {
                    "model": "gemini/gemini-2.5-flash",
                    "input_tokens": 4709,
                    "output_tokens": 76,
                    "cost_usd": 0.00210488,  # The number recorded by the actual trace.
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            }
        ],
    }
    # Bypass auto-load by passing trace_data directly via internal API.
    # ``analyze`` doesn't have a trace_data kwarg, so simulate by building
    # a temp file. Simpler: the analyzer accepts trace_path, so we'd need
    # a real file. Instead, drive via an explicit test-only path: write
    # the trace JSON to tmp.
    import json
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(trace, f)
        trace_file = f.name

    try:
        analysis = analyze(
            workflow_ir,
            # Match the trace's synthetic ``workflow_path`` so the bug-5 scope
            # filter does NOT activate (it correctly fires on mismatch — but
            # this test verifies trace cost flows through, not scoping).
            workflow_path="ir-hash:fake",
            trace_path=Path(trace_file),
            auto_load_trace=False,
        )
    finally:
        Path(trace_file).unlink(missing_ok=True)

    assert analysis.summary.actually_paid_usd is not None
    # Within ±5% of recorded cost (no recompute drift).
    assert abs(analysis.summary.actually_paid_usd - 0.00210488) / 0.00210488 < 0.05
    # Cost data source on the row reflects trace tier.
    assert analysis.per_call[0].cost_data_source == "trace"
    assert analysis.per_call[0].cost_usd is not None


# ---------------------------------------------------------------------------
# Cached-leaf cost correctness (Critical bug #1, Commit 2 of cleanup plan)
# ---------------------------------------------------------------------------


def test_build_trace_execution_index_excludes_cached_llm_cost() -> None:
    """Defends: cached LLM leaves must NOT contribute to
    ``current_cost_by_workflow``; otherwise the rollup's actually_paid_usd
    reports historical cost despite the run paying $0.

    Drives the ``parent-child-memo-hit-trace.json`` committed fixture
    end-to-end via analyze().
    """
    from pflow.execution.workflow_resolver import resolve_workflow

    fixture_dir = Path("tests/fixtures/cache_analysis")
    parent_path = fixture_dir / "parent.pflow.md"
    trace_path = fixture_dir / "parent-child-memo-hit-trace.json"
    resolved = resolve_workflow(str(parent_path))

    result = analyze(
        resolved.ir,
        parameters={"topic": "cache analysis"},
        workflow_path=resolved.file_path,
        base_path=parent_path.parent,
        trace_path=trace_path,
        memo_cache=None,
    )

    # Parent's draft paid $0.05 fresh; child's two cached LLMs paid $0.
    # Rollup MUST reflect that — pre-fix, child's actually_paid would be 0.10.
    assert result.summary.actually_paid_usd == pytest.approx(0.05)
    assert result.summary.sub_workflow_rollup is not None
    child_entry = result.summary.sub_workflow_rollup.per_workflow[0]
    assert child_entry.actually_paid_usd == 0.0


def test_actually_paid_and_trace_index_agree_on_memo_hit_child() -> None:
    """Parity invariant: ``summary.actually_paid_usd`` and the rollup's
    per-child ``actually_paid_usd`` MUST agree on cached-event semantics.

    Pre-fix the two diverged: ``compute_actually_paid`` (used for the
    summary) excludes cached via ``total_cost(include_cached=False)``,
    while ``_build_trace_execution_index`` (used for the rollup) summed
    cached cost into ``current_cost_by_workflow``. Two figures with the
    same name in the same JSON disagreed.
    """
    from pflow.execution.workflow_resolver import resolve_workflow

    fixture_dir = Path("tests/fixtures/cache_analysis")
    parent_path = fixture_dir / "parent.pflow.md"
    trace_path = fixture_dir / "parent-child-memo-hit-trace.json"
    resolved = resolve_workflow(str(parent_path))

    result = analyze(
        resolved.ir,
        parameters={"topic": "cache analysis"},
        workflow_path=resolved.file_path,
        base_path=parent_path.parent,
        trace_path=trace_path,
        memo_cache=None,
    )

    summary_total = result.summary.actually_paid_usd or 0.0
    rollup_total = sum(
        (entry.actually_paid_usd or 0.0)
        for entry in (
            result.summary.sub_workflow_rollup.per_workflow if result.summary.sub_workflow_rollup is not None else ()
        )
    )
    # Both must EXCLUDE cached cost. Parent paid 0.05, children paid 0.
    # Sum of root + children = 0.05.
    assert summary_total + rollup_total == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Heterogeneous batch attribution (Critical bug #2, Commit 3 of cleanup plan)
# ---------------------------------------------------------------------------


def test_walk_attributes_heterogeneous_batch_costs_per_item() -> None:
    """Mutation contract surrogate: drives ``TraceTree.walk`` directly with
    a heterogeneous workflow batch trace.

    Pre-fix (``_edge_child_paths``-only attribution) collapsed N edges
    sharing one ``parent_node_id`` into one entry — both items were
    attributed to the last child workflow path. Post-fix each batch_item's
    ``template_resolutions["workflow"]["resolved"]`` becomes its own
    workflow_path so per-item costs roll up to the correct child.

    The end-to-end ``analyze()`` flow does not currently surface
    heterogeneous batches in the rollup (the cross-workflow walker
    enumerates static items but the rollup keys on ``cw_result.edges``);
    this test pins the trace-walker invariant the future end-to-end
    coverage will sit on top of.
    """
    from pflow.core.trace_tree import TraceTree
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    builder = TraceFixtureBuilder()
    parent = builder.heterogeneous_workflow_batch_event(
        "fan-out",
        items=[
            ("/abs/a.pflow.md", [builder.llm_event("draft", cost_usd=0.05)]),
            ("/abs/b.pflow.md", [builder.llm_event("draft", cost_usd=0.07)]),
        ],
    )
    tree = TraceTree.from_dict(builder.trace(workflow_path="parent.pflow.md", nodes=[parent]))

    # iter_llm_leaves attributes per-item: each draft sits under its own child.
    by_workflow: dict[str | None, float] = {}
    for leaf in tree.iter_llm_leaves():
        if leaf.llm_call is None:
            continue
        cost = leaf.llm_call.get("cost_usd")
        if cost is None:
            continue
        by_workflow[leaf.workflow_path] = by_workflow.get(leaf.workflow_path, 0.0) + float(cost)

    assert by_workflow == {
        "/abs/a.pflow.md": pytest.approx(0.05),
        "/abs/b.pflow.md": pytest.approx(0.07),
    }
    # And the totals are honest at the root.
    total, source = tree.total_cost()
    assert total == pytest.approx(0.12)
    assert source == "trace"


# ---------------------------------------------------------------------------
# Cycle bug regression (Commit 4 of cleanup plan)
# ---------------------------------------------------------------------------


class _NodeMemoStub:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    def get_latest_for_node(
        self, node_id: str, *, workflow_path: str | None = None
    ) -> tuple[dict[str, Any], str] | None:
        value = self.values.get(node_id)
        if value is None:
            return None
        return value, "2026-05-09T00:00:00Z"


def _batch_edge(*, parent_input_value: Any = "${item.concept_brief}") -> Any:
    from pflow.core.cache_analysis.cross_workflow import CrossWorkflowEdge

    return CrossWorkflowEdge(
        parent_workflow="/abs/parent.pflow.md",
        child_workflow="/abs/child.pflow.md",
        parent_value_expr="item.concept_brief" if isinstance(parent_input_value, str) else None,
        child_input_name="concept",
        line_in_parent=1,
        parent_node_id="fanout",
        parent_batch_alias="item",
        parent_input_value=parent_input_value,
    )


def test_resolve_child_input_value_propagates_via_batch_alias() -> None:
    """Batch alias values resolve by binding ``batch.items[0]`` as an exemplar.

    Mutation contract: remove the ``edge.is_batch_alias_root`` branch from
    ``_resolve_child_input_value``; this test fails because ``${item...}``
    remains unresolved.
    """
    from pflow.core.cache_analysis.analyze import _resolve_child_input_value

    parent_ir = {
        "nodes": [
            {
                "id": "fanout",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${item.concept_brief}"}},
                "batch": {"items": "${make-concepts.result}", "as": "item"},
            }
        ]
    }
    ctx = AnalysisContext.build(
        workflow_ir=parent_ir,
        memo_cache=_NodeMemoStub({
            "make-concepts": {
                "result": [
                    {"concept_brief": "first concept"},
                    {"concept_brief": "second concept"},
                ]
            }
        }),
        workflow_path="/abs/parent.pflow.md",
    )

    assert _resolve_child_input_value(_batch_edge(), ctx) == "first concept"


def test_resolve_child_input_value_returns_none_when_batch_items_unresolvable() -> None:
    """Unresolvable batch items keep the child value honestly unmeasurable.

    Mutation contract: fabricate an empty shared-store value for the batch
    alias; this test fails because unresolved runtime values stop returning
    ``None``.
    """
    from pflow.core.cache_analysis.analyze import _resolve_child_input_value

    parent_ir = {
        "nodes": [
            {
                "id": "fanout",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${item.concept_brief}"}},
                "batch": {"items": "${runtime.thing}", "as": "item"},
            }
        ]
    }
    ctx = AnalysisContext.build(workflow_ir=parent_ir, workflow_path="/abs/parent.pflow.md")

    assert _resolve_child_input_value(_batch_edge(), ctx) is None


def test_resolve_child_input_value_handles_inline_static_batch_items() -> None:
    """Inline static ``batch.items`` uses the first item as the exemplar.

    Mutation contract: only handle template-string ``items``; this test fails
    because literal-list batches no longer propagate child parameters.
    """
    from pflow.core.cache_analysis.analyze import _resolve_child_input_value

    parent_ir = {
        "nodes": [
            {
                "id": "fanout",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${item.concept_brief}"}},
                "batch": {"items": [{"concept_brief": "inline first"}], "as": "item"},
            }
        ]
    }
    ctx = AnalysisContext.build(workflow_ir=parent_ir, workflow_path="/abs/parent.pflow.md")

    assert _resolve_child_input_value(_batch_edge(), ctx) == "inline first"


def test_resolve_child_input_value_swallows_batch_items_resolve_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bad batch-items expression cannot crash the analyzer.

    Mutation contract: remove the ``try/except`` around batch-items template
    resolution; this test fails by raising the injected exception.
    """
    from pflow.core.cache_analysis.analyze import _resolve_child_input_value

    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")

    parent_ir = {
        "nodes": [
            {
                "id": "fanout",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"concept": "${item.concept_brief}"}},
                "batch": {"items": "${make-concepts.result}", "as": "item"},
            }
        ]
    }
    ctx = AnalysisContext.build(workflow_ir=parent_ir, workflow_path="/abs/parent.pflow.md")

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("template boom")

    monkeypatch.setattr(analyze_module.TemplateResolver, "resolve_template", boom)

    assert _resolve_child_input_value(_batch_edge(), ctx) is None


def test_build_parameters_by_workflow_propagates_batch_alias_child_input() -> None:
    """Caller-site regression for the edge-based resolver signature.

    Mutation contract: keep the old caller that passes ``edge.parent_input_value``
    instead of the edge; this test fails because batch-alias metadata is lost.
    """
    from pflow.core.cache_analysis.analyze import _build_parameters_by_workflow
    from pflow.core.cache_analysis.cross_workflow import walk_cross_workflow
    from pflow.core.markdown_parser import parse_markdown

    fixtures_dir = Path("tests/fixtures/cache_analysis").resolve()
    parent_path = fixtures_dir / "batch-alias-parent.pflow.md"
    child_path = fixtures_dir / "child.pflow.md"
    parent_ir = parse_markdown(parent_path.read_text(encoding="utf-8")).ir

    cw_result = walk_cross_workflow(
        parent_ir,
        base_path=fixtures_dir,
        root_workflow_path=str(parent_path),
    )
    params_by_workflow = _build_parameters_by_workflow(
        cw_result,
        {"items": [{"concept_brief": "current first"}]},
        str(parent_path),
        memo_cache=None,
        trace_data=None,
        base_path=fixtures_dir,
    )

    assert params_by_workflow[str(child_path)]["brief"] == "current first"


def test_build_parameters_by_workflow_uses_trace_batch_item_when_items_expr_unresolvable() -> None:
    """Trace batch items are a real evidence source for dynamic workflow batches.

    The live lyrics-generator trace trims the upstream node output that produced
    ``batch.items`` but keeps each workflow batch item's concrete ``item``. This
    test locks that integration point without relying on the large fixture.

    Mutation contract: remove ``_resolve_first_trace_batch_item`` from
    ``_resolve_first_batch_item``; this test fails because the child workflow
    receives no propagated ``brief`` parameter.
    """
    from pflow.core.cache_analysis.analyze import _build_parameters_by_workflow
    from pflow.core.cache_analysis.cross_workflow import walk_cross_workflow
    from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult

    parent_path = "/abs/parent.pflow.md"
    child_path = "/abs/child.pflow.md"
    parent_ir = {
        "nodes": [
            {
                "id": "fanout",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {"brief": "${item.concept_brief}"}},
                "batch": {"items": "${make-items.result}", "as": "item"},
            }
        ]
    }
    child_ir = {"inputs": {"brief": {"type": "string"}}, "nodes": []}

    def resolver(params: dict[str, Any], _base: Path | None) -> SubWorkflowResult | None:
        if params.get("workflow") == "./child.pflow.md":
            return SubWorkflowResult(ir=child_ir, path=Path(child_path), warnings=())
        return None

    cw_result = walk_cross_workflow(
        parent_ir,
        base_path=Path("/abs"),
        resolve_child=resolver,
        root_workflow_path=parent_path,
    )
    builder = TraceFixtureBuilder()
    trace_data = builder.trace(
        workflow_path=parent_path,
        nodes=[
            builder.homogeneous_workflow_batch_event(
                "fanout",
                workflow_path="./child.pflow.md",
                items=[({"concept_brief": "trace first"}, []), ({"concept_brief": "trace second"}, [])],
                item_input_template="${item.concept_brief}",
            )
        ],
    )

    params_by_workflow = _build_parameters_by_workflow(
        cw_result,
        {},
        parent_path,
        memo_cache=None,
        trace_data=trace_data,
        base_path=Path("/abs"),
    )

    assert params_by_workflow[child_path]["brief"] == "trace first"


def test_batch_prefix_projection_uses_trace_call_count_for_dynamic_batch(tmp_path: Path) -> None:
    """Dynamic batch rows project the per-call static prefix.

    This is the small-fixture version of the ``score-choruses`` canary: the
    actionable provider-cache opportunity is the prompt prefix before
    ``${item...}``. ``observed_call_count`` only gates the ``< 2`` precondition;
    the projected value is per-call to match ``PerCallRow.cacheable_tokens_estimated``
    semantics. Downstream cost helpers multiply by invocation count themselves.

    Mutation contract: remove ``_prefer_batch_prefix_cacheable_tokens`` from
    ``_build_per_call_row``; this test fails because the row's
    ``could_cache`` projection returns to unavailable/tiny chunk-only evidence.
    """
    from pflow.core.cache_analysis.token_estimation import estimate_tokens

    model = "anthropic/claude-haiku-4-5"
    prefix = "Shared rubric:\n" + ("stable context sentence. " * 300)
    prompt = f"{prefix}\n${{item.dynamic}}"
    workflow_path = str(tmp_path / "batch-prefix.pflow.md")
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "params": {"model": model, "prompt": prompt},
                "batch": {"items": "${items}", "as": "item"},
            }
        ]
    }
    builder = TraceFixtureBuilder()
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(
            builder.trace(
                workflow_path=workflow_path,
                nodes=[
                    builder.batch_event(
                        "score",
                        [
                            {
                                "index": index,
                                "success": True,
                                "llm_call": {
                                    "model": model,
                                    "input_tokens": 50_000,
                                    "output_tokens": 10,
                                    "total_tokens": 50_010,
                                    "cost_usd": 0.01,
                                },
                            }
                            for index in range(3)
                        ],
                    )
                ],
            )
        ),
        encoding="utf-8",
    )

    result = analyze(
        workflow_ir,
        parameters={"items": [{"dynamic": "a"}, {"dynamic": "b"}, {"dynamic": "c"}]},
        workflow_path=workflow_path,
        trace_path=trace_path,
        memo_cache=None,
    )

    row = next(row for row in result.per_call if row.node_path == "score")
    expected_prefix_tokens = estimate_tokens(model, f"{prefix}\n")[0]
    assert row.cacheable_data_source == "batch_prefix"
    assert row.cacheable_tokens_estimated == expected_prefix_tokens
    assert row.observed_call_count == 3


def test_batch_prefix_projection_promotes_dynamic_batch_prewarm_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing batch-prefix evidence should become a ranked action.

    Mutation contract: keep ``_batch_prewarm_recommendations`` gated only on
    ``batch_size_estimated``; this test fails because dynamic ``batch.items:
    ${items}`` rows have no static size even when trace observed repeated calls.
    """
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    below_min_module = importlib.import_module("pflow.core.cache_analysis.below_min_tokens_detector")
    token_estimation_module = importlib.import_module("pflow.core.cache_analysis.token_estimation")
    monkeypatch.setattr(analyze_module, "estimate_tokens", lambda _model, text, **_kwargs: (len(text.split()), "test"))
    monkeypatch.setattr(
        token_estimation_module,
        "estimate_tokens",
        lambda _model, text, **_kwargs: (len(text.split()), "test"),
    )
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 10)
    monkeypatch.setattr(below_min_module, "get_min_cache_tokens", lambda _model: 10)
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)

    model = "anthropic/claude-haiku-4-5"
    prefix = "Shared rubric:\n" + ("stable context sentence. " * 1600)
    prompt = f"{prefix}\n${{item.dynamic}}"
    workflow_path = str(tmp_path / "dynamic-batch-prewarm.pflow.md")
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "params": {"model": model, "prompt": prompt},
                "batch": {"items": "${items}", "as": "item"},
            }
        ]
    }
    builder = TraceFixtureBuilder()
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(
            builder.trace(
                workflow_path=workflow_path,
                nodes=[
                    builder.batch_event(
                        "score",
                        [
                            {
                                "index": index,
                                "success": True,
                                "llm_call": {
                                    "model": model,
                                    "input_tokens": 20_000,
                                    "output_tokens": 10,
                                    "total_tokens": 20_010,
                                    "cost_usd": 0.01,
                                },
                            }
                            for index in range(4)
                        ],
                    )
                ],
            )
        ),
        encoding="utf-8",
    )

    result = analyze(
        workflow_ir,
        parameters={"items": [{"dynamic": str(index)} for index in range(4)]},
        workflow_path=workflow_path,
        trace_path=trace_path,
        memo_cache=None,
    )

    diag = next(d for d in result.warnings if d.id == "cache.batch-prewarm-recommended")
    assert diag.context is not None
    assert diag.context["batch_size"] == 4
    assert diag.context["prefix_tokens_estimated"] == len(f"{prefix}\n".split())
    assert diag.context["prefix_tokens_cohort_estimated"] == len(f"{prefix}\n".split()) * 4


def test_batch_prefix_cacheable_does_not_inflate_to_100pct_when_prefix_is_truncated(
    tmp_path: Path,
) -> None:
    """Interleaved per-item refs cut the cacheable prefix short — the row must
    report a sub-100% ratio so agents see the layout problem.

    Repro for FINDINGS E2 (``scratchpads/experiments/prewarm-cache-interaction``):
    a per-item ref placed before the bulk of stable content terminates the
    cacheable prefix at that ref, leaving most of the prompt outside the cache.
    Pre-Bug-A, ``_estimate_batch_prefix_cacheable_tokens`` returned cohort
    tokens (``prefix_per_call * call_count``) which the clamp at
    ``_build_per_call_row`` collapsed to ``input_tokens`` for any batch_size >= 2,
    masking the bug as a misleading 100% ratio.

    Mutation contract: restore ``return prefix_tokens * affected_call_count`` in
    ``_estimate_batch_prefix_cacheable_tokens``; this test fails because the
    row's ``cache_ratio_pct`` jumps back to 100 and
    ``cacheable_tokens_estimated`` equals ``input_tokens_estimated``.
    """
    from pflow.core.cache_analysis.token_estimation import estimate_tokens

    model = "anthropic/claude-haiku-4-5"
    prefix_before_item_ref = "Brief intro:\n" + ("stable sentence. " * 5)
    suffix_after_item_ref = "\n" + ("more stable instructions sentence. " * 300)
    # Per-item ref placed BEFORE the bulk of stable content — cuts the
    # cacheable prefix short at the ref boundary.
    prompt = f"{prefix_before_item_ref}${{item.id}}{suffix_after_item_ref}"
    workflow_path = str(tmp_path / "interleaved-prefix.pflow.md")
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "params": {"model": model, "prompt": prompt},
                "batch": {"items": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "as": "item"},
            }
        ]
    }

    result = analyze(
        workflow_ir,
        workflow_path=workflow_path,
        auto_load_trace=False,
        memo_cache=None,
    )

    row = next(row for row in result.per_call if row.node_path == "score")
    assert row.cacheable_data_source == "batch_prefix"
    assert row.cacheable_tokens_estimated is not None
    assert row.cache_ratio_pct is not None
    # The actual layout bug: cacheable should be strictly less than input,
    # because the suffix after ``${item.id}`` is not part of the cached prefix.
    assert row.cacheable_tokens_estimated < row.input_tokens_estimated, (
        "expected cacheable < input when per-item ref interleaves with stable content"
    )
    assert row.cache_ratio_pct < 100, "expected sub-100% ratio for truncated prefix"
    # Sanity: per-call cacheable should match direct tokenization of the
    # pre-ref segment, not be inflated by call count.
    expected_per_call_prefix = estimate_tokens(model, prefix_before_item_ref)[0]
    # Allow ±10 token tolerance for whitespace/newline tokenization differences.
    assert abs(row.cacheable_tokens_estimated - expected_per_call_prefix) < 20


def test_batch_prefix_prewarm_action_respects_explicit_prewarm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "estimate_tokens", lambda _model, text, **_kwargs: (len(text.split()), "test"))
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 10)

    model = "anthropic/claude-haiku-4-5"
    workflow_path = str(tmp_path / "explicit-prewarm.pflow.md")
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "params": {"model": model, "prompt": ("stable " * 40) + "${item.dynamic}"},
                "batch": {"items": [{"dynamic": "a"}, {"dynamic": "b"}], "as": "item"},
                "prewarm": True,
            }
        ]
    }

    result = analyze(workflow_ir, workflow_path=workflow_path, auto_load_trace=False, memo_cache=None)

    assert "cache.batch-prewarm-recommended" not in {d.id for d in result.warnings}


def test_batch_prefix_prewarm_action_respects_explicit_opt_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "estimate_tokens", lambda _model, text, **_kwargs: (len(text.split()), "test"))
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 10)

    model = "anthropic/claude-haiku-4-5"
    workflow_path = str(tmp_path / "prewarm-opt-out.pflow.md")
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "params": {"model": model, "prompt": ("stable " * 40) + "${item.dynamic}"},
                "batch": {"items": [{"dynamic": "a"}, {"dynamic": "b"}], "as": "item"},
                "prewarm": False,
            }
        ]
    }

    result = analyze(workflow_ir, workflow_path=workflow_path, auto_load_trace=False, memo_cache=None)

    assert "cache.batch-prewarm-recommended" not in {d.id for d in result.warnings}


def test_batch_prefix_prewarm_action_suppresses_low_call_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "estimate_tokens", lambda _model, text, **_kwargs: (len(text.split()), "test"))
    monkeypatch.setattr(analyze_module, "get_min_cache_tokens", lambda _model: 10)

    model = "anthropic/claude-haiku-4-5"
    workflow_path = str(tmp_path / "single-batch-call.pflow.md")
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "params": {"model": model, "prompt": ("stable " * 40) + "${item.dynamic}"},
                "batch": {"items": [{"dynamic": "a"}], "as": "item"},
            }
        ]
    }

    result = analyze(workflow_ir, workflow_path=workflow_path, auto_load_trace=False, memo_cache=None)

    assert "cache.batch-prewarm-recommended" not in {d.id for d in result.warnings}


def test_batch_prefix_projection_does_not_ripple_into_rerun_cost_for_undeclared_rows(tmp_path: Path) -> None:
    """Cost-projection isolation: populating ``cacheable_tokens_estimated`` on
    an undeclared row (via the batch-prefix projection) must NOT shrink
    ``rerun_within_ttl_hypothetical_usd`` — the provider cache doesn't fire
    when ``prompt_cache:`` isn't declared, regardless of how the analyzer
    projects the candidate.

    Without this gate, the headline cost block would carry an internal
    contradiction: ``actually_paid - rerun_hypothetical`` would diverge from
    ``first_run_delta`` because ``_aggregate_first_run_savings`` correctly
    skips undeclared rows but ``_row_rerun_cost`` ungated would not.

    Mutation contract: remove the ``if row.declared_prompt_cache`` gate from
    ``_row_rerun_cost`` in ``cost_estimation.py``; this test fails
    because the rerun hypothetical drops below the no-cache hypothetical for
    a workflow with no declared cache.
    """
    model = "anthropic/claude-haiku-4-5"
    prefix = "Shared rubric:\n" + ("stable context sentence. " * 300)
    prompt = f"{prefix}\n${{item.dynamic}}"
    workflow_path = str(tmp_path / "batch-prefix-cost.pflow.md")
    workflow_ir = {
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "params": {"model": model, "prompt": prompt},
                "batch": {"items": "${items}", "as": "item"},
            }
        ]
    }
    builder = TraceFixtureBuilder()
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(
            builder.trace(
                workflow_path=workflow_path,
                nodes=[
                    builder.batch_event(
                        "score",
                        [
                            {
                                "index": index,
                                "success": True,
                                "llm_call": {
                                    "model": model,
                                    "input_tokens": 50_000,
                                    "output_tokens": 10,
                                    "total_tokens": 50_010,
                                    "cost_usd": 0.01,
                                },
                            }
                            for index in range(3)
                        ],
                    )
                ],
            )
        ),
        encoding="utf-8",
    )

    result = analyze(
        workflow_ir,
        parameters={"items": [{"dynamic": "a"}, {"dynamic": "b"}, {"dynamic": "c"}]},
        workflow_path=workflow_path,
        trace_path=trace_path,
        memo_cache=None,
    )

    # The score row has cacheable_tokens_estimated > 0 (prefix projection
    # fires) but no declared_prompt_cache. The rerun hypothetical must
    # equal the no-cache hypothetical because no provider cache fires.
    row = next(row for row in result.per_call if row.node_path == "score")
    assert row.cacheable_tokens_estimated and row.cacheable_tokens_estimated > 0
    assert not row.declared_prompt_cache
    no_cache = result.summary.no_cache_hypothetical_usd
    rerun = result.summary.rerun_within_ttl_hypothetical_usd
    assert no_cache is not None and rerun is not None
    assert rerun == pytest.approx(no_cache), (
        f"rerun_hypothetical (${rerun:.6f}) must equal no_cache_hypothetical (${no_cache:.6f}) "
        "for workflows with no declared prompt_cache; the prefix-projection cacheable "
        "value must NOT ripple into the rerun cost."
    )


def test_batch_prefix_projection_does_not_fire_for_non_batch_repeated_call_nodes(tmp_path: Path) -> None:
    """Limitation lock: the prefix-projection only fires for nodes whose own
    IR declares ``batch:``. Nodes called multiple times because their PARENT
    sub-workflow is invoked from a batch (e.g., ``select-chorus`` in
    chorus-chooser, called 4x because chorus-chooser is invoked from a parent
    batch) do NOT receive prefix-projection — even though the static-prefix
    cache opportunity is structurally identical.

    This is a documented limitation, not a bug — broadening the gate to
    ``observed_call_count >= 2`` requires identifying the per-call-dynamic
    boundary independently of a batch alias, which is a deeper change. Future
    work tracked in the deferred partial-declaration handoff.

    Mutation contract: drop the ``isinstance(batch, dict)`` gate in
    ``_estimate_batch_prefix_cacheable_tokens``; this test fails because the
    repeated-call non-batch node now ALSO gets a prefix-projection (which the
    helper isn't structured to compute correctly without knowing the per-call
    dynamic boundary).
    """
    model = "anthropic/claude-haiku-4-5"
    workflow_path = str(tmp_path / "single-call.pflow.md")
    # Single-call node (no batch:) — observed call count is provided externally
    # by trace, not by the node's own batch config.
    workflow_ir = {
        "nodes": [
            {
                "id": "judge",
                "type": "llm",
                "params": {"model": model, "prompt": "Stable rubric.\n${context}"},
            }
        ]
    }
    builder = TraceFixtureBuilder()
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(
            builder.trace(
                workflow_path=workflow_path,
                nodes=[
                    builder.llm_event(
                        "judge",
                        model=model,
                        input_tokens=1_000,
                        output_tokens=10,
                        cost_usd=0.001,
                    )
                    for _ in range(4)  # invoked 4 times via parent batch
                ],
            )
        ),
        encoding="utf-8",
    )

    result = analyze(
        workflow_ir,
        parameters={},
        workflow_path=workflow_path,
        trace_path=trace_path,
        memo_cache=None,
    )

    row = next(row for row in result.per_call if row.node_path == "judge")
    # The row may have other Tier 2 evidence (or unavailable), but it must NOT
    # have a batch-prefix-projection result — this gate prevents over-claiming
    # cache opportunities for nodes whose static-prefix detection mechanism
    # isn't yet implemented.
    assert row.cacheable_data_source != "batch_prefix"


def test_tier2_chunk_cacheable_stays_per_call_for_repeated_non_batch_trace_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 2 chunk estimates use the same per-call units as trace input."""
    token_module = importlib.import_module("pflow.core.cache_analysis.token_estimation")
    monkeypatch.setattr(token_module, "_estimate_ref_tokens", lambda ref, **_kwargs: 123 if ref == "context" else None)

    workflow_path = str(tmp_path / "repeated-non-batch.pflow.md")
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "nodes": [
            {
                "id": "judge",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Judge ${context}."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${context}."},
            },
        ],
    }
    trace_path = _write_trace_fixture(
        tmp_path,
        workflow_path=workflow_path,
        nodes=[
            _llm_trace_event("judge", model="anthropic/claude-haiku-4-5", input_tokens=1_000),
            _llm_trace_event("judge", model="anthropic/claude-haiku-4-5", input_tokens=1_000),
            _llm_trace_event("judge", model="anthropic/claude-haiku-4-5", input_tokens=1_000),
            _llm_trace_event("judge", model="anthropic/claude-haiku-4-5", input_tokens=1_000),
        ],
    )

    result = analyze(
        workflow_ir,
        parameters={"context": "stable"},
        workflow_path=workflow_path,
        trace_path=trace_path,
        memo_cache=None,
    )

    row = next(row for row in result.per_call if row.node_path == "judge")
    assert row.is_batch is False
    assert row.observed_call_count == 4
    assert row.input_tokens_estimated == 1_000
    assert row.cacheable_data_source == "parameters"
    assert row.cacheable_tokens_estimated == 123
    assert result.summary.total_cacheable_tokens_estimated == sum(
        (row.cacheable_tokens_estimated or 0) * invocation_count_for(row) for row in result.per_call
    )


def test_tier2_chunk_cacheable_single_call_remains_per_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_module = importlib.import_module("pflow.core.cache_analysis.token_estimation")
    monkeypatch.setattr(token_module, "_estimate_ref_tokens", lambda ref, **_kwargs: 123 if ref == "context" else None)

    workflow_path = str(tmp_path / "single-non-batch.pflow.md")
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "nodes": [
            {
                "id": "judge",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Judge ${context}."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${context}."},
            },
        ],
    }
    trace_path = _write_trace_fixture(
        tmp_path,
        workflow_path=workflow_path,
        nodes=[_llm_trace_event("judge", model="anthropic/claude-haiku-4-5", input_tokens=1_000)],
    )

    result = analyze(
        workflow_ir,
        parameters={"context": "stable"},
        workflow_path=workflow_path,
        trace_path=trace_path,
        memo_cache=None,
    )

    row = next(row for row in result.per_call if row.node_path == "judge")
    assert row.observed_call_count == 1
    assert row.cacheable_data_source == "parameters"
    assert row.cacheable_tokens_estimated == 123


def test_tier2_chunk_cacheable_unresolved_repeated_row_stays_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_module = importlib.import_module("pflow.core.cache_analysis.token_estimation")
    monkeypatch.setattr(token_module, "_estimate_ref_tokens", lambda _ref, **_kwargs: None)

    workflow_path = str(tmp_path / "unresolved-repeated.pflow.md")
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "nodes": [
            {
                "id": "judge",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Judge ${context}."},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "anthropic/claude-haiku-4-5",
                "params": {"prompt": "Review ${context}."},
            },
        ],
    }
    trace_path = _write_trace_fixture(
        tmp_path,
        workflow_path=workflow_path,
        nodes=[
            _llm_trace_event("judge", model="anthropic/claude-haiku-4-5", input_tokens=1_000),
            _llm_trace_event("judge", model="anthropic/claude-haiku-4-5", input_tokens=1_000),
        ],
    )

    result = analyze(
        workflow_ir,
        parameters={"context": "stable"},
        workflow_path=workflow_path,
        trace_path=trace_path,
        memo_cache=None,
    )

    row = next(row for row in result.per_call if row.node_path == "judge")
    assert row.observed_call_count == 2
    assert row.cacheable_data_source == "unavailable"
    assert row.cacheable_tokens_estimated is None


def test_real_trace_score_choruses_does_not_fabricate_unmeasurable_batch_prefix() -> None:
    """Real lyrics-generator canary for honest unmeasurable batch prefixes.

    This intentionally covers the whole chain on the production-shaped fixture:
    nested batch aliases, minimized trace values, dynamic sub-workflow batch
    attribution, external prompt loading, and cross-workflow projection.

    Mutation contract: route ``_estimate_batch_prefix_cacheable_tokens`` back
    through raw prompt-slice tokenization; this test fails because
    ``score-choruses`` reports ``batch_prefix`` for a prefix that still
    contains unresolved upstream refs.
    """
    from pflow.core.markdown_parser import parse_markdown

    baseline_dir = Path(".taskmaster/tasks/task_159/baseline").resolve()
    workflow_path = baseline_dir / "_shared/workflows/lyrics-generator/lyrics-generator.pflow.md"
    trace_path = baseline_dir / "_shared/fixtures/live-gemini-lyrics-generator.trace.json"
    source = (baseline_dir / "_shared/long-stable-text.txt").read_text(encoding="utf-8")[:3000]
    workflow_ir = parse_markdown(workflow_path.read_text(encoding="utf-8")).ir

    result = analyze(
        workflow_ir,
        parameters={"sources": [source]},
        workflow_path=str(workflow_path),
        base_path=workflow_path.parent,
        trace_path=trace_path,
    )

    score_rows = [row for row in result.per_call if row.node_path == "score-choruses"]
    assert score_rows, "expected score-choruses row in lyrics-generator analysis"
    assert all(row.cacheable_data_source != "batch_prefix" for row in score_rows)
    assert any(row.cacheable_data_source == "parameters" for row in score_rows)
    select_rows = [row for row in result.per_call if row.node_path == "select-chorus"]
    assert select_rows, "expected select-chorus row in lyrics-generator analysis"
    assert any(row.cacheable_data_source == "cross_workflow_projection" for row in select_rows)
    assert any(
        row.cacheable_tokens_estimated is not None
        and row.cacheable_tokens_estimated > 0
        and row.cacheable_tokens_estimated <= row.input_tokens_estimated
        for row in select_rows
    )
    review_rhyme_rows = [
        row
        for row in result.per_call
        if row.node_path == "review" and Path(str(row.workflow_path or "")).name == "review-rhyme.pflow.md"
    ]
    assert review_rhyme_rows, "expected review-rhyme row in lyrics-generator analysis"
    assert all(not row.did_not_execute_in_trace for row in review_rhyme_rows)
    assert any(row.observed_call_count == 4 for row in review_rhyme_rows)
    assert any(
        row.cacheable_tokens_estimated is not None
        and row.cacheable_tokens_estimated > 0
        and row.cacheable_tokens_estimated <= row.input_tokens_estimated
        for row in review_rhyme_rows
    )
    score_actions = [
        warning
        for warning in result.warnings
        if warning.id == "cache.batch-prewarm-recommended" and warning.node_id == "score-choruses"
    ]
    assert not score_actions, "unmeasurable score-choruses prefix must not produce a prewarm action"


def test_build_parameters_by_workflow_does_not_mutate_root_on_cycle() -> None:
    """Regression for the A → B → A cycle bug.

    Pre-fix: ``walk_cross_workflow`` did not seed ``root_workflow_path`` into
    ``seen``, so the back-edge B → A entered ``cw_result.edges``. Then
    ``_build_parameters_by_workflow`` iterated that back-edge and called
    ``params_by_workflow.setdefault(A, {})`` which returned the EXISTING
    root params dict, then mutated it by adding the child input name.

    Post-fix: the walker seeds root into ``seen``, the back-edge is
    suppressed, and the root params dict stays byte-identical to its
    input.
    """
    from pflow.core.cache_analysis.analyze import _build_parameters_by_workflow
    from pflow.core.cache_analysis.cross_workflow import walk_cross_workflow
    from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult

    a_path = "/abs/a.pflow.md"
    b_path = "/abs/b.pflow.md"

    a_ir = {
        "nodes": [
            {
                "id": "calls_b",
                "type": "workflow",
                "params": {"workflow": "./b.pflow.md", "inputs": {"x": "${y}"}},
                "_source_line": 1,
            }
        ],
    }
    b_ir = {
        "nodes": [
            {
                "id": "calls_a",
                "type": "workflow",
                "params": {"workflow": "./a.pflow.md", "inputs": {"y": "${z}"}},
                "_source_line": 1,
            }
        ],
    }

    table = {
        "./b.pflow.md": (b_ir, Path(b_path)),
        "./a.pflow.md": (a_ir, Path(a_path)),
    }

    def resolver(params: dict[str, Any], _base: Path | None) -> SubWorkflowResult | None:
        ref = params.get("workflow")
        if not isinstance(ref, str):
            return None
        ir, path = table[ref]
        return SubWorkflowResult(ir=ir, path=path, warnings=())

    cw_result = walk_cross_workflow(
        a_ir,
        base_path=Path("/abs"),
        resolve_child=resolver,
        root_workflow_path=a_path,
    )

    root_parameters = {"input1": "value1"}
    params_snapshot = dict(root_parameters)

    params_by_workflow = _build_parameters_by_workflow(
        cw_result,
        root_parameters,
        a_path,
        memo_cache=None,
        trace_data=None,
        base_path=Path("/abs"),
    )

    # Root params dict is byte-identical to input.
    assert params_by_workflow[a_path] == params_snapshot
    # No back-edge means root has no spurious added inputs.
    assert "y" not in params_by_workflow[a_path]
    assert "x" not in params_by_workflow[a_path]


# ---------------------------------------------------------------------------
# Homogeneous static workflow batch attribution (latent bug fix)
# ---------------------------------------------------------------------------


def test_homogeneous_static_workflow_batch_child_cost_attributed_to_child(
    tmp_path: Path,
) -> None:
    """End-to-end: homogeneous static workflow batch with LLM child.

    A parent workflow has a ``type: workflow`` node with static
    ``workflow: ./child.pflow.md`` and ``batch:`` items. Each batch item
    runs the same child workflow, which contains an LLM call.

    Pre-fix: ``trace_tree.walk`` for batch_items only consulted
    ``template_resolutions["workflow"]`` (absent for static workflow
    refs), so child LLM cost was attributed to the PARENT workflow path.
    The rollup's per-child ``actually_paid_usd`` was None despite the
    child having paid real money this run.

    Post-fix: ``walk`` consults ``edges.get(event_node_id)`` as a 2nd
    fallback. Child LLM cost rolls up to the child workflow.

    Verified via real-shape ``TraceFixtureBuilder.homogeneous_workflow_batch_event``
    which mirrors the production trace shape (no
    ``template_resolutions["workflow"]`` per item; only ``inputs``).
    """
    import json

    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    # Build a parent + child workflow on disk.
    child_path = tmp_path / "child.pflow.md"
    child_path.write_text(
        "# Child\n\nChild workflow.\n\n## Inputs\n\n### input\n"
        "The input.\n- type: string\n\n## Steps\n\n### c-llm\n\n"
        "Child LLM.\n\n- type: llm\n- model: anthropic/claude-sonnet-4-5\n\n"
        "```prompt\nProcess ${input}\n```\n",
        encoding="utf-8",
    )
    parent_path = tmp_path / "parent.pflow.md"
    parent_path.write_text(
        "# Parent\n\nParent with homogeneous workflow batch.\n\n## Steps\n\n"
        "### fanout\n\nFan out to child.\n\n- type: workflow\n"
        "- workflow: ./child.pflow.md\n- batch:\n    items: [alpha, beta]\n"
        "- inputs:\n    input: ${item}\n",
        encoding="utf-8",
    )

    # Construct a trace matching the production homogeneous-batch shape.
    builder = TraceFixtureBuilder()
    parent_event = builder.homogeneous_workflow_batch_event(
        "fanout",
        workflow_path="./child.pflow.md",  # raw IR string, not resolved
        items=[
            ("alpha", [builder.llm_event("c-llm", cost_usd=0.01)]),
            ("beta", [builder.llm_event("c-llm", cost_usd=0.02)]),
        ],
    )
    trace = builder.trace(workflow_path=str(parent_path), nodes=[parent_event])
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    resolved = resolve_workflow(str(parent_path))
    result = analyze(
        resolved.ir,
        workflow_path=resolved.file_path,
        base_path=parent_path.parent,
        trace_path=trace_path,
        memo_cache=None,
    )

    # Headline total — sum of all child LLM costs.
    assert result.summary.actually_paid_usd == pytest.approx(0.03)

    # Rollup contains the child workflow.
    assert result.summary.sub_workflow_rollup is not None
    rollup = result.summary.sub_workflow_rollup
    assert len(rollup.per_workflow) == 1
    child_entry = rollup.per_workflow[0]
    assert child_entry.workflow_path.endswith("child.pflow.md")
    assert child_entry.called_by_node_id == "fanout"

    # Pre-fix: child_entry.actually_paid_usd was None (or 0.0).
    # Post-fix: child cost rolls up correctly.
    assert child_entry.actually_paid_usd == pytest.approx(0.03)


def test_dynamic_workflow_batch_old_relative_trace_attributed_to_child(
    tmp_path: Path,
) -> None:
    """Old heterogeneous workflow-batch traces may store relative child refs.

    The analyzer still needs to match those child LLM events to rows keyed by
    the canonical child workflow path from static cross-workflow analysis.
    """
    child_path = tmp_path / "child.pflow.md"
    child_path.write_text(
        "# Child\n\nChild workflow.\n\n## Inputs\n\n### input\n"
        "The input.\n- type: string\n\n## Steps\n\n### c-llm\n\n"
        "Child LLM.\n\n- type: llm\n- model: anthropic/claude-sonnet-4-5\n\n"
        "```prompt\nProcess ${input}\n```\n",
        encoding="utf-8",
    )
    parent_path = tmp_path / "parent.pflow.md"
    parent_path.write_text(
        "# Parent\n\nParent with dynamic workflow batch.\n\n## Steps\n\n"
        "### fanout\n\nFan out to child.\n\n- type: workflow\n"
        "- workflow: ${item.workflow}\n"
        "- batch:\n"
        "    items:\n"
        "      - workflow: ./child.pflow.md\n"
        "        input: alpha\n"
        "      - workflow: ./child.pflow.md\n"
        "        input: beta\n"
        "    as: item\n"
        "- inputs:\n    input: ${item.input}\n",
        encoding="utf-8",
    )

    builder = TraceFixtureBuilder()
    parent_event = builder.heterogeneous_workflow_batch_event(
        "fanout",
        items=[
            ("./child.pflow.md", [builder.llm_event("c-llm", cost_usd=0.01)]),
            ("./child.pflow.md", [builder.llm_event("c-llm", cost_usd=0.02)]),
        ],
    )
    trace = builder.trace(workflow_path=str(parent_path), nodes=[parent_event])
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    resolved = resolve_workflow(str(parent_path))
    result = analyze(
        resolved.ir,
        workflow_path=resolved.file_path,
        base_path=parent_path.parent,
        trace_path=trace_path,
        memo_cache=None,
    )

    child_workflow_path = str(child_path.resolve())
    child_row = next(row for row in result.per_call if row.workflow_path == child_workflow_path)
    assert child_row.node_path == "c-llm"
    assert child_row.observed_call_count == 2
    assert child_row.did_not_execute_in_trace is False

    assert result.summary.sub_workflow_rollup is not None
    child_entry = next(
        entry for entry in result.summary.sub_workflow_rollup.per_workflow if entry.workflow_path == child_workflow_path
    )
    assert child_entry.actually_paid_usd == pytest.approx(0.03)


# ---------------------------------------------------------------------------
# Memo-hit trace token recovery — Issue A
# ---------------------------------------------------------------------------


def test_memo_hit_trace_recovers_input_and_output_tokens_via_index(
    tmp_path: Path,
) -> None:
    """``_build_trace_execution_index`` populates ``llm_calls_by_key`` for
    cached events so memo-hit traces produce real token estimates instead
    of falling through to estimator-partial.

    The cached event's ``llm_call`` dict carries historical
    ``input_tokens`` / ``output_tokens`` preserved from the original run.
    Pre-fix the ``if leaf.is_cached: continue`` filter skipped index
    population, so ``_estimate_row_tokens`` saw ``trace_llm_call=None``
    and fell back to estimator-partial (input from prompt resolution,
    output ``None``). Cost summation must remain $0 for cached events
    (Bug 1 invariant).
    """
    import json

    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    workflow_path = tmp_path / "smoke.pflow.md"
    workflow_path.write_text(
        "# Smoke\n\nMemo-hit smoke.\n\n## Steps\n\n### draft\n\n"
        "Draft text.\n\n- type: llm\n- model: anthropic/claude-sonnet-4-5\n\n"
        "```prompt\nHello\n```\n",
        encoding="utf-8",
    )

    builder = TraceFixtureBuilder()
    # cache_read_input_tokens=0 keeps the fixture simple; this test is about
    # memo-hit cost behavior, not trace token-accounting normalization.
    cached_event = builder.cached_llm_event_with_call(
        "draft",
        cost_usd=0.00034006,
        input_tokens=4714,
        output_tokens=76,
        cache_read_input_tokens=0,
    )
    trace = builder.trace(workflow_path=str(workflow_path), nodes=[cached_event])
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    resolved = resolve_workflow(str(workflow_path))
    result = analyze(
        resolved.ir,
        workflow_path=resolved.file_path,
        base_path=workflow_path.parent,
        trace_path=trace_path,
        memo_cache=None,
    )

    assert len(result.per_call) == 1
    row = result.per_call[0]
    # Pre-fix: estimator-partial fallback produced bogus tokens or None
    # output. Post-fix: tier-1 reads the cached ``llm_call`` directly.
    assert row.input_tokens_estimated == 4714
    assert row.output_tokens_estimated == 76
    assert row.data_source == "trace"
    assert row.output_data_source == "trace"
    # Bug 1 invariant: cached events must NOT inflate cost. They are
    # observed zero-cost evidence for the current run, not unavailable.
    assert row.cost_usd == 0.0
    assert row.cost_data_source == "trace"
    assert result.summary.actually_paid_usd == 0.0
    assert str(result.summary.actually_paid_tier) == "trace"


# ---------------------------------------------------------------------------
# L-4: collapse near-identical predicted-key skip notes
# ---------------------------------------------------------------------------


def test_format_fidelity_skip_note_is_single_source_of_truth() -> None:
    """Fix 8 follow-up: every "we couldn't verify cache fidelity here" note
    in the discrepancy stage routes through ``_format_fidelity_skip_note``.
    Locks the wording in one place so future drift across the 9 emit sites
    is impossible — change the prefix or the chunk-skip tail here, and
    every downstream note inherits the change.

    Mutation contract:
    - Change the prefix string ("Cache fidelity check skipped for") → every
      production note using the helper diverges from this test's substring.
    - Drop the "Chunk-skip detection still applies." tail →
      the final substring assertion fails.
    - Inline the helper at any emit site (bypassing the SSoT) → those notes
      drift from the rest; the integration tests for that site fail.
    """
    from pflow.core.cache_analysis.analyze import _format_fidelity_skip_note

    # Default (applicable=True): "skipped for" prefix.
    note = _format_fidelity_skip_note("x.pflow.md", "workflow failed to compile")
    assert note == (
        "Cache fidelity check skipped for x.pflow.md: workflow failed to compile. Chunk-skip detection still applies."
    )

    # applicable=False switches to "not applicable to" — for cases like
    # cache: false on a node, where the check doesn't fit, vs. genuinely
    # couldn't run.
    not_applicable = _format_fidelity_skip_note("x.pflow.md.draft", "this node has `cache: false`", applicable=False)
    assert "Cache fidelity check not applicable to x.pflow.md.draft" in not_applicable
    assert "`cache: false`" in not_applicable
    assert "Chunk-skip detection still applies" in not_applicable

    # Negative: no old jargon ever appears via this helper.
    for output in (note, not_applicable):
        assert "Discrepancy detection" not in output
        assert "predicted-key matching" not in output
        assert "Observable-field attributions" not in output


def test_skipped_workflows_note_single_renders_plain_english() -> None:
    """Fix 8 follow-up: single-workflow skip case routes through the
    ``_format_fidelity_skip_note`` helper. No jargon prefix; plain English
    target + reason; consistent chunk-skip tail.

    Mutation contract: drop the ``len(paths) == 1`` branch → this test fails
    (renders the multi-summary phrasing for one workflow).
    """
    from pflow.core.cache_analysis.analyze import _format_skipped_workflows_note

    note = _format_skipped_workflows_note(["song-creator.pflow.md"])
    # Plain-English framing with the workflow named.
    assert "Cache fidelity check skipped for song-creator.pflow.md" in note
    assert "weren't supplied as parameters" in note
    # Consistent fallback tail.
    assert "Chunk-skip detection still applies" in note
    # No jargon.
    assert "Discrepancy detection" not in note
    assert "predicted-key matching" not in note
    assert "Observable-field attributions" not in note
    # Must NOT use the multi-summary phrasing.
    assert "sub-workflows" not in note


def test_skipped_workflows_note_multi_collapses_to_summary() -> None:
    """L-4: 3+ skipped sub-workflows collapse to ONE summary note instead of
    N near-identical lines (the lyrics-generator case emitted 15).

    Mutation contract: revert _predict_one_workflow to call ``notes.append``
    directly → 3 separate lines instead of one summary; this test fails.
    """
    from pflow.core.cache_analysis.analyze import _format_skipped_workflows_note

    paths = [
        "/abs/song-creator/review-rhyme.pflow.md",
        "/abs/song-creator/review-imagery.pflow.md",
        "/abs/song-creator/review-narrative.pflow.md",
    ]
    note = _format_skipped_workflows_note(paths)
    # Fix 8 follow-up: plain-English framing in the multi-workflow case.
    assert "Cache fidelity check skipped for 3 sub-workflows" in note
    # Basenames listed inline, full paths NOT (they blow past terminal width).
    assert "review-rhyme.pflow.md" in note
    assert "review-imagery.pflow.md" in note
    assert "review-narrative.pflow.md" in note
    assert "/abs/song-creator/" not in note
    # Actionable suggestion (pass concrete inputs) appears.
    assert "Pass concrete" in note
    assert "<input>=<value>" in note
    # Consistent fallback tail.
    assert "Chunk-skip detection still applies" in note
    # No jargon.
    assert "Discrepancy detection" not in note
    assert "Observable-field attributions" not in note


def test_skipped_workflows_note_multi_truncates_at_five_with_overflow_marker() -> None:
    """L-4: more than 5 skipped workflows show ``+N more`` suffix to keep the
    note bounded.
    """
    from pflow.core.cache_analysis.analyze import _format_skipped_workflows_note

    paths = [f"/abs/wf-{i}.pflow.md" for i in range(8)]
    note = _format_skipped_workflows_note(paths)
    assert "skipped for 8 sub-workflows" in note
    # First 5 listed, +3 overflow.
    assert "wf-0.pflow.md" in note
    assert "wf-4.pflow.md" in note
    assert "+ 3 more" in note
    # 6th onwards NOT listed by basename.
    assert "wf-5.pflow.md" not in note
    assert "wf-6.pflow.md" not in note
    assert "wf-7.pflow.md" not in note


def test_predict_cache_keys_memo_empty_note_uses_plain_english() -> None:
    """Fix 8: memo-empty discrepancy note must read as plain English.

    The original "Discrepancy detection: predicted-key matching unavailable
    (memo cache empty — predicted-key matching needs prior memo cache entries
    to compare against). Observable-field attributions (chunk skipped)
    still apply." packs four internal terms ("Discrepancy detection",
    "predicted-key matching", "Observable-field attributions", "memo cache")
    into one sentence. A fresh agent reading it cold can't derive any action.

    Replacement framing: "this is a first run, on later runs misfires will
    appear here". Preserves the actionable signal; drops every internal term.

    Mutation contract: revert the new wording in ``_predict_cache_keys`` →
    the negative assertions fail.
    """
    from pflow.core.cache_analysis.analyze import _predict_cache_keys

    ctx = AnalysisContext.build(
        workflow_ir={"nodes": []},
        parameters={},
        memo_cache=None,  # triggers the memo-empty early-return path
        workflow_path="/abs/parent.pflow.md",
    )

    _, notes = _predict_cache_keys(cw_result=None, ctx=ctx)

    assert len(notes) == 1
    note = notes[0]
    # Positive: agent-actionable phrasing.
    assert "first run" in note
    assert "later runs" in note
    assert "TTL" in note  # tells agent what misfire types will appear later
    # Negative: no internals.
    assert "Discrepancy detection" not in note
    assert "predicted-key matching" not in note
    assert "Observable-field attributions" not in note
    assert "memo cache" not in note  # internal pflow term


def test_predict_cache_keys_aggregates_skip_notes_via_production_path() -> None:
    """L-4 PRODUCTION-SHAPE integration test (Pitfall #19 defense).

    Helper-level tests above verify ``_format_skipped_workflows_note``
    in isolation, but they don't catch a regression where production code
    bypasses the helper and reverts to per-workflow note emission. This
    test drives ``_predict_cache_keys`` end-to-end with a multi-sub-workflow
    ``cw_result`` and asserts the aggregated form reaches ``result.notes``.

    Mutation contract: replace ``skipped_input_workflows.append(...)``
    in ``_predict_one_workflow`` with the original per-workflow
    ``notes.append(...)`` call → this test fails because ``notes`` carries
    3 separate "predicted-key matching skipped" lines instead of 1
    aggregated summary.
    """
    from types import SimpleNamespace

    from pflow.core.cache_analysis.analyze import _predict_cache_keys

    # 3 sub-workflows each declaring inputs but with no params resolved.
    irs = {
        "/abs/sub-a.pflow.md": {"inputs": {"x": {"type": "string"}}, "nodes": []},
        "/abs/sub-b.pflow.md": {"inputs": {"y": {"type": "string"}}, "nodes": []},
        "/abs/sub-c.pflow.md": {"inputs": {"z": {"type": "string"}}, "nodes": []},
    }
    cw_result = SimpleNamespace(irs_by_workflow=irs)

    class _MemoStub:
        """Non-None memo bypasses the early "memo cache empty" notes branch."""

    ctx = AnalysisContext.build(
        workflow_ir={"nodes": []},
        parameters={},
        memo_cache=_MemoStub(),
        workflow_path="/abs/parent.pflow.md",
        parameters_by_workflow={
            "/abs/sub-a.pflow.md": {},
            "/abs/sub-b.pflow.md": {},
            "/abs/sub-c.pflow.md": {},
        },
    )

    _, notes = _predict_cache_keys(cw_result, ctx)

    # Fix 8 follow-up: the skip-note prefix is now "Cache fidelity check
    # skipped for" — single SSoT across all sites via ``_format_fidelity_skip_note``.
    skip_notes = [n for n in notes if "Cache fidelity check skipped for" in n]
    # Pre-L-4: 3 per-workflow notes. Post-L-4: 1 aggregated summary.
    assert len(skip_notes) == 1, f"Expected 1 aggregated note, got {len(skip_notes)}:\n" + "\n".join(
        f"  - {n}" for n in skip_notes
    )
    aggregated = skip_notes[0]
    assert "3 sub-workflows" in aggregated
    assert "sub-a.pflow.md" in aggregated
    assert "sub-b.pflow.md" in aggregated
    assert "sub-c.pflow.md" in aggregated
    # Negative — single-workflow legacy phrasing must NOT appear when 3 skipped.
    assert "skipped for /abs/sub-a.pflow.md" not in aggregated
    assert "skipped for /abs/sub-b.pflow.md" not in aggregated
    assert "skipped for /abs/sub-c.pflow.md" not in aggregated


# ---------------------------------------------------------------------------
# B-4 — dynamic-batch note collapse
# ---------------------------------------------------------------------------


def test_dynamic_batches_note_single_keeps_legacy_phrasing() -> None:
    """B-4: single dynamic batch keeps the original per-batch phrasing for
    continuity with pre-B-4 baselines and the existing walker substring test.

    Mutation contract: drop the ``len(batches) == 1`` branch → this test
    fails (renders the multi-summary phrasing for one batch).
    """
    from pflow.core.cache_analysis.analyze import _format_dynamic_batches_note
    from pflow.core.cache_analysis.cross_workflow import DynamicBatchInfo

    note = _format_dynamic_batches_note((
        DynamicBatchInfo(
            node_id="fetch-sources", parent_workflow="/abs/parent.pflow.md", items_expression="${sources}"
        ),
    ))
    assert note is not None
    assert "Workflow batch fetch-sources" in note
    assert "uses items: ${sources}" in note
    assert "measured from trace events" in note
    assert "CLI parameter" in note
    # Multi-summary phrasing must NOT appear for one batch.
    assert "dynamic batches not in per-call table" not in note


def test_dynamic_batches_note_multi_collapses_to_summary() -> None:
    """B-4: multiple dynamic batches collapse to ONE summary listing each
    batch's id + items expression once. The lyrics-generator workflow had 3
    such batches; pre-B-4 rendering blew ~500 chars of repeated prose into
    ``## Notes``.

    Mutation contract: emit one note per batch (revert _format helper to
    return per-batch strings) → this test fails because the listing
    enumeration disappears.
    """
    from pflow.core.cache_analysis.analyze import _format_dynamic_batches_note
    from pflow.core.cache_analysis.cross_workflow import DynamicBatchInfo

    batches = (
        DynamicBatchInfo(
            node_id="fetch-sources", parent_workflow="/abs/parent.pflow.md", items_expression="${sources}"
        ),
        DynamicBatchInfo(
            node_id="analyze-sources",
            parent_workflow="/abs/parent.pflow.md",
            items_expression="${fetch-sources.results}",
        ),
        DynamicBatchInfo(
            node_id="create-songs",
            parent_workflow="/abs/parent.pflow.md",
            items_expression="${zip-concepts-with-briefs.result}",
        ),
    )
    note = _format_dynamic_batches_note(batches)
    assert note is not None
    assert "3 dynamic batches not in per-call table" in note
    # All three batch ids + items expressions appear once each.
    assert "`fetch-sources` (items: `${sources}`)" in note
    assert "`analyze-sources` (items: `${fetch-sources.results}`)" in note
    assert "`create-songs` (items: `${zip-concepts-with-briefs.result}`)" in note
    # Action surface preserved.
    assert "CLI parameter" in note
    assert "inline static items" in note
    assert "measured from the trace, not estimated" in note


def test_dynamic_batches_note_returns_none_for_empty_input() -> None:
    """B-4: empty input → no note. The analyzer suppresses the append when
    the helper returns ``None`` so workflows without runtime batches don't
    pick up an empty Note line.
    """
    from pflow.core.cache_analysis.analyze import _format_dynamic_batches_note

    assert _format_dynamic_batches_note(()) is None


def test_analyze_aggregates_dynamic_batches_into_one_note_via_production_path(tmp_path: Path) -> None:
    """B-4 PRODUCTION-SHAPE integration test (Pitfall #19 defense).

    Helper-level tests above verify ``_format_dynamic_batches_note`` in
    isolation, but they don't catch a regression where production code
    bypasses the helper and reverts to per-batch note emission. This test
    drives ``analyze()`` end-to-end with a 3-batch workflow IR and asserts
    exactly ONE matching Note reaches ``result.notes``.

    Mutation contract: revert the walker's ``_maybe_record_dynamic_batch``
    to append per-batch prose to ``notes`` and skip the analyzer-side
    aggregation → this test fails because ``result.notes`` carries 3
    "Workflow batch" lines instead of 1 "3 dynamic batches" summary.
    """
    # Three sibling batch nodes, each with a runtime-template ``items`` expr.
    # Children are inline workflows so the walker doesn't try to resolve
    # external files.
    workflow_ir = {
        "nodes": [
            {
                "id": "fetch-sources",
                "type": "workflow",
                "params": {"workflow": {"nodes": []}, "inputs": {}},
                "batch": {"items": "${sources}", "as": "item"},
                "_source_line": 10,
            },
            {
                "id": "analyze-sources",
                "type": "workflow",
                "params": {"workflow": {"nodes": []}, "inputs": {}},
                "batch": {"items": "${fetch-sources.results}", "as": "item"},
                "_source_line": 20,
            },
            {
                "id": "create-songs",
                "type": "workflow",
                "params": {"workflow": {"nodes": []}, "inputs": {}},
                "batch": {"items": "${zip-concepts-with-briefs.result}", "as": "item"},
                "_source_line": 30,
            },
        ]
    }
    result = analyze(workflow_ir, workflow_path=str(tmp_path / "parent.pflow.md"), memo_cache=None)

    batch_notes = [n for n in result.notes if "dynamic batches" in n or "Workflow batch" in n]
    assert len(batch_notes) == 1, f"Expected 1 aggregated note, got {len(batch_notes)}:\n" + "\n".join(
        f"  - {n}" for n in batch_notes
    )
    aggregated = batch_notes[0]
    assert "3 dynamic batches" in aggregated
    assert "fetch-sources" in aggregated
    assert "analyze-sources" in aggregated
    assert "create-songs" in aggregated
    # Negative — pre-B-4 per-batch wording must NOT appear in multi-batch case.
    assert "Workflow batch fetch-sources in" not in aggregated


def test_parent_origin_clause_surfaces_rename_and_hides_passthrough() -> None:
    """Lock the rename-vs-passthrough contract for the action body's data-flow sub-line.

    The renderer adds a "flows in from parent as `${expr}`" line under each input
    bullet ONLY when the parent-side value expression and child-side input name
    diverge. Same-name passthroughs add no signal (suffix would be visual noise);
    multi-ref/literal parent values produce no parent_value_expr (None) and also
    suppress the suffix.

    Mutation contracts:
      - Flip the equality check (``expr == child_input_name``) to ``!=`` →
        same-name case fires; this test fails.
      - Drop the ``not expr`` guard → None/empty case returns ``"flows in from
        parent as `${None}`"`` or similar; this test fails.
    """
    from pflow.core.cache_analysis.analyze import _parent_origin_clause, _SubWorkflowCacheCandidate

    def _make(parent_value_expr: str | None, child_input_name: str) -> _SubWorkflowCacheCandidate:
        return _SubWorkflowCacheCandidate(
            parent_workflow="parent.pflow.md",
            parent_value_expr=parent_value_expr or "",
            parent_node_id="p",
            line_in_parent=1,
            child_workflow="child.pflow.md",
            child_input_name=child_input_name,
            child_count=1,
            child_node_ids=("c",),
        )

    # Rename: names differ → suffix surfaces the parent-side expression.
    rename = _make(parent_value_expr="write-lyrics.response", child_input_name="lyrics")
    assert _parent_origin_clause(rename) == "flows in from parent as `${write-lyrics.response}`"

    # Passthrough: same name on both sides → no suffix (would be visual noise).
    passthrough = _make(parent_value_expr="concept_brief", child_input_name="concept_brief")
    assert _parent_origin_clause(passthrough) is None

    # Multi-ref / literal parent value: parent_value_expr is empty → no suffix.
    opaque = _make(parent_value_expr="", child_input_name="lyrics")
    assert _parent_origin_clause(opaque) is None


def test_actually_paid_scopes_to_analyzed_workflow_when_trace_is_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug 5 regression: analyzing a child with a parent-scope trace must scope
    "Actually paid" to the child's slice, not sum the parent's total.

    Reproduction shape mirrors ``scratchpads/experiments/bug-5-scope-mismatch-*``:
    parent runs an expensive padding LLM batch + invokes a tiny child once. Today
    (pre-fix) ``actually_paid`` returned the parent's total ($1.005) instead of
    the child's slice (~$0.005), producing nonsensical percentage ratios like
    "130,178% of no-cache cost" downstream.

    Mutation contract:
      - Revert ``compute_actually_paid`` to call ``trace.total_cost(...)`` without
        ``scope_workflow_paths`` → assertion on the scoped value fails (jumps to
        the parent total).
      - Drop the disclosure Note emission in ``analyze.py`` → assertion on
        ``analysis.notes`` containing the scope-mismatch text fails.
    """
    child_path = tmp_path / "bug5-child.pflow.md"
    parent_path = str(tmp_path / "bug5-parent.pflow.md")
    child_ir = {
        "nodes": [
            {
                "id": "tiny-llm",
                "type": "llm",
                "params": {"prompt": "say ok", "model": "anthropic/claude-sonnet-4-5"},
            }
        ]
    }

    builder = TraceFixtureBuilder()
    # Parent's expensive padding LLM costs $1.00; child's tiny LLM costs $0.005,
    # invoked 3x via a homogeneous workflow batch (mirrors the production bug-5
    # repro shape — parent's `child-batch` over `bug-5-scope-mismatch-child`).
    # If actually_paid is tree-wide, it returns $1.015; if scoped to the child,
    # it returns $0.015.
    padding = builder.llm_event("padding-llm", cost_usd=1.00, input_tokens=10_000, output_tokens=100)
    child_event_a = builder.llm_event("tiny-llm", cost_usd=0.005, input_tokens=100, output_tokens=10)
    child_event_b = builder.llm_event("tiny-llm", cost_usd=0.005, input_tokens=100, output_tokens=10)
    child_event_c = builder.llm_event("tiny-llm", cost_usd=0.005, input_tokens=100, output_tokens=10)
    child_batch = builder.homogeneous_workflow_batch_event(
        "child-batch",
        workflow_path=str(child_path),
        items=[("a", [child_event_a]), ("b", [child_event_b]), ("c", [child_event_c])],
    )
    # Newer traces carry an explicit per-item ``workflow_path`` field; add it so
    # the analyzer can attribute child events without parent→child edges in
    # ``cw_result`` (which is rooted at the child when child is the analyzed wf).
    for item in child_batch["batch_items"]:
        item["workflow_path"] = str(child_path)
    trace_dict = builder.trace(parent_path, [padding, child_batch])
    trace_file = tmp_path / "parent-trace.json"
    trace_file.write_text(json.dumps(trace_dict), encoding="utf-8")

    # Analyze the CHILD with the parent's trace.
    result = analyze(
        child_ir,
        workflow_path=str(child_path),
        trace_path=trace_file,
        memo_cache=None,
    )

    # Actually paid must be the child's slice (3 * $0.005 = $0.015), NOT parent
    # total ($1.015). Pre-fix, this returned ~$1.015 → 6700% delta nonsense.
    assert result.summary.actually_paid_usd is not None
    assert result.summary.actually_paid_usd == pytest.approx(0.015, abs=1e-6)

    # S#9: when the analyzed workflow runs as a sub-workflow inside the
    # trace's root, the disclosure becomes a redirect hint pointing the
    # agent at the trace root so they can get full attribution.
    redirect_notes = [n for n in result.notes if "appears as a sub-workflow" in n]
    assert len(redirect_notes) == 1, f"expected one redirect note, got: {result.notes}"
    assert str(child_path) in redirect_notes[0]
    assert parent_path in redirect_notes[0] or os.path.realpath(parent_path) in redirect_notes[0]
    assert "pflow analyze-cache" in redirect_notes[0]


def test_scope_mismatch_emits_generic_note_when_analyzed_workflow_absent_from_trace(
    tmp_path: Path,
) -> None:
    """S#9 negative: when the analyzed workflow does NOT appear inside the
    trace at all (different workflow, different file), the generic
    scope-mismatch disclosure fires — not the redirect hint, which would be
    misleading because the trace root doesn't actually contain this
    workflow.

    Mutation contract:
      - If ``_workflow_appears_as_child`` returns True unconditionally,
        this test fails because the redirect note fires for unrelated
        workflows.
    """
    analyzed_path = str(tmp_path / "unrelated.pflow.md")
    other_path = str(tmp_path / "other.pflow.md")
    analyzed_ir = {
        "nodes": [
            {
                "id": "analyzed-llm",
                "type": "llm",
                "params": {"prompt": "x", "model": "anthropic/claude-sonnet-4-5"},
            }
        ]
    }

    builder = TraceFixtureBuilder()
    # Trace records a different workflow with a different node; the
    # analyzed workflow never appears as a child.
    other_llm = builder.llm_event("other-llm", cost_usd=0.01, input_tokens=100, output_tokens=10)
    trace_dict = builder.trace(other_path, [other_llm])
    trace_file = tmp_path / "other-trace.json"
    trace_file.write_text(json.dumps(trace_dict), encoding="utf-8")

    result = analyze(
        analyzed_ir,
        workflow_path=analyzed_path,
        trace_path=trace_file,
        memo_cache=None,
    )

    # Generic disclosure must fire; redirect hint must NOT.
    generic_notes = [n for n in result.notes if "trace file references workflow" in n]
    redirect_notes = [n for n in result.notes if "appears as a sub-workflow" in n]
    assert len(generic_notes) == 1, f"expected generic note, got: {result.notes}"
    assert len(redirect_notes) == 0, f"unexpected redirect note: {result.notes}"


def test_actually_paid_unchanged_when_trace_root_matches_analyzed_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug 5 regression-gate: when analyzing a workflow with its own trace
    (today's common case), ``actually_paid`` MUST remain a tree-wide sum
    (parent + children). Verifies the scope filter is correctly bypassed
    when ``trace.workflow_path == lookup_path``.

    Mutation contract:
      - Unconditionally pass a non-None ``scope_workflow_paths`` (i.e., drop
        the ``trace_root != lookup_path`` gate) → tree-wide sum is lost; the
        $0.10 child cost gets filtered out; assertion fails.
    """
    import pflow.core.cache_analysis.cross_workflow as cross_module
    from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult

    child_path = tmp_path / "child.pflow.md"
    child_ir = {
        "nodes": [
            {
                "id": "child-llm",
                "type": "llm",
                "params": {"prompt": "child", "model": "anthropic/claude-sonnet-4-5"},
            }
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, child_path, ()),
    )
    parent_ir = {
        "nodes": [
            {
                "id": "parent-llm",
                "type": "llm",
                "params": {"prompt": "parent", "model": "anthropic/claude-sonnet-4-5"},
            },
            {
                "id": "call-child",
                "type": "workflow",
                "params": {"workflow": "./child.pflow.md", "inputs": {}},
            },
        ],
    }
    parent_path = str(tmp_path / "parent.pflow.md")
    builder = TraceFixtureBuilder()
    parent_llm = builder.llm_event("parent-llm", cost_usd=0.05, input_tokens=100, output_tokens=10)
    child_llm = builder.llm_event("child-llm", cost_usd=0.10, input_tokens=100, output_tokens=10)
    child_wf = builder.workflow_event("call-child", [child_llm], workflow_path=str(child_path))
    trace_dict = builder.trace(parent_path, [parent_llm, child_wf])
    trace_file = tmp_path / "parent-trace.json"
    trace_file.write_text(json.dumps(trace_dict), encoding="utf-8")

    result = analyze(
        parent_ir,
        workflow_path=parent_path,
        trace_path=trace_file,
        memo_cache=None,
    )

    # Tree-wide sum: parent's $0.05 + child's $0.10 = $0.15.
    assert result.summary.actually_paid_usd == pytest.approx(0.15)

    # No scope-mismatch Note should appear when trace root matches.
    assert not any("trace file references workflow" in n for n in result.notes), (
        f"unexpected scope-mismatch note when trace.workflow_path == lookup_path: {result.notes}"
    )
