"""F2.1 — analyzer engine tests: confidence, note ordering, summary shape."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from pflow.core.cache_analysis.analyze import (
    CacheAnalysis,
    PerCallRow,
    _aggregate_confidence,
    _build_summary,
    _maybe_append_gemini_note,
    analyze,
)
from pflow.core.diagnostic import Diagnostic, Severity
from pflow.execution.workflow_resolver import resolve_workflow

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


def test_confidence_high_when_all_trace() -> None:
    """STRICT: all rows must be 'trace' for high. Mixed trace/memo → medium."""
    confidence, coverage = _aggregate_confidence([_row("trace"), _row("trace")])
    assert confidence == "high_from_trace"
    assert coverage == {"trace": 2, "memo": 0, "estimator": 0, "heuristic": 0, "total": 2}


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


def test_erroring_child_trace_marks_unexecuted_rows_and_suppresses_projection() -> None:
    """Defends phantom-cost suppression for child workflows that error after an
    earlier LLM: static IR rows remain visible, but unexecuted LLMs do not
    fabricate recomputed projection dollars.
    """
    fixture_dir = Path("tests/fixtures/cache_analysis")
    parent_path = fixture_dir / "parent.pflow.md"
    trace_path = fixture_dir / "parent-child-erroring-trace.json"
    resolved = resolve_workflow(str(parent_path))

    result = analyze(
        resolved.ir,
        parameters={"topic": "cache analysis"},
        workflow_path=resolved.file_path,
        base_path=parent_path.parent,
        trace_path=trace_path,
        memo_cache=None,
    )

    child_path = str((fixture_dir / "child.pflow.md").resolve())
    by_key = {(row.workflow_path, row.node_path): row for row in result.per_call}
    assert result.summary.actually_paid_usd == pytest.approx(0.12)
    assert by_key[(child_path, "review")].did_not_execute_in_trace is True
    assert by_key[(child_path, "review")].cost_usd is None

    # The executed child row had trace cache evidence, so some rerun savings is
    # present. The unexecuted review row has a declared cache too; without the
    # did-not-execute skip it would add a second child-row savings contribution.
    executed_child = by_key[(child_path, "draft")]
    unexecuted_child = by_key[(child_path, "review")]
    assert result.summary.aggregate_savings_rerun_usd is not None
    assert executed_child.cacheable_tokens_estimated
    assert unexecuted_child.cacheable_tokens_estimated is not None
    assert result.summary.aggregate_savings_rerun_usd < 0.003


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
    coerced to a tokenizable literal; they fall back to estimator-partial.
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
    assert row.cacheable_data_source == "estimator"
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


def test_per_call_cache_ratio_never_exceeds_100_pct() -> None:
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
    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False, memo_cache=None)
    for row in result.per_call:
        assert row.cache_ratio_pct <= 100, f"row {row.node_path} has nonsense ratio {row.cache_ratio_pct}%"
        assert row.cacheable_tokens_estimated <= row.input_tokens_estimated, (
            f"cacheable={row.cacheable_tokens_estimated} > input={row.input_tokens_estimated} "
            "violates the 'cache cannot exceed total' invariant"
        )


def test_cacheable_tokens_includes_cache_content_when_chunks_only_in_cache_block() -> None:
    """Bug 4 reproducer — declared chunks referenced by name only in
    ``prompt_cache:`` (not inlined in the prompt body) must contribute their
    resolved token count to ``input_tokens_estimated``. Without this the
    ``min(cacheable, input)`` clamp truncated correct cacheable values to
    the prompt-body-only size and ``cache.below-min-tokens`` falsely fired.
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
    assert "cache.below-min-tokens" not in {d.id for d in result.warnings}


def test_total_input_tokens_anthropic_trace_sums_cache_portions() -> None:
    """Anthropic-style trace event: ``input_tokens`` excludes cache portions;
    the analyzer must sum them back into ``input_tokens_estimated``.
    """
    from pflow.core.cache_analysis.analyze import _estimate_row_tokens

    trace_llm_call = {
        "input_tokens": 500,
        "cache_creation_input_tokens": 1500,
        "cache_read_input_tokens": 0,
        "output_tokens": 50,
    }
    input_tokens, source, _output, _output_source = _estimate_row_tokens(
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
    don't double-count. Provider discrimination is by
    ``ProviderInfo.splits_cache_from_input_tokens`` (False for Gemini), not
    by the value of ``cache_creation_input_tokens`` — cache-write vs
    cache-read events have different cache-creation values within the same
    provider.
    """
    from pflow.core.cache_analysis.analyze import _estimate_row_tokens

    trace_llm_call = {
        "input_tokens": 2000,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 1500,
        "output_tokens": 50,
    }
    input_tokens, source, _output, _output_source = _estimate_row_tokens(
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


def test_total_input_tokens_anthropic_cache_read_event_sums_cache_portions() -> None:
    """Bug 7 regression: Anthropic rerun-within-TTL events report
    ``cache_creation_input_tokens == 0`` and ``cache_read_input_tokens > 0``.
    The previous heuristic ``cache_creation > 0`` misclassified these as
    Gemini-style and truncated ``input_tokens`` to the non-cache portion.
    Detection by model-name prefix fixes this — Anthropic always splits
    cache from ``input_tokens``, regardless of which side fired."""
    from pflow.core.cache_analysis.analyze import _estimate_row_tokens

    trace_llm_call = {
        "model": "anthropic/claude-sonnet-4-5",
        "input_tokens": 50,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 1500,
        "output_tokens": 10,
    }
    input_tokens, source, _output, _output_source = _estimate_row_tokens(
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
    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)
    # cache.below-min-tokens fires (small prompt, anthropic min=1024).
    # Tighter assertion: lock the specific id so a different warning firing
    # for the wrong reason fails the test (not just total count).
    assert any(w.id == "cache.below-min-tokens" for w in result.warnings), (
        f"Expected cache.below-min-tokens; got: {[w.id for w in result.warnings]}"
    )
    sum_ = result.summary
    assert sum_.warnings_count + sum_.info_count >= 1


def test_analyze_surfaces_cache_order_mismatch() -> None:
    workflow_ir = {
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


def test_analyze_filters_non_cache_data_flow_diagnostics() -> None:
    """Negative control for A.6: validate_data_flow's non-cache diagnostics
    (here: a forward template reference to an undeclared node) MUST be
    filtered out by ``_cache_validator_findings`` so analyze() doesn't surface
    workflow-health concerns under the cache-analyzer label.

    Defends: ``_cache_validator_findings`` filters on
    ``d.id and d.id.startswith("cache.")``; without that filter, non-cache
    diagnostics leak through and contaminate cache-analyzer output.
    """
    from pflow.core.workflow.data_flow import validate_data_flow

    # Forward-reference shape: shell node 'a' references 'b' which appears
    # after it in document order. validate_data_flow(check_inputs=False)
    # still emits this ERROR (it's an order-of-execution problem, not an
    # input-dependent check), and the diagnostic has id=None — which is
    # exactly what the cache-namespaced filter is designed to drop.
    workflow_ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": "echo ${b.stdout}"}},
            {"id": "b", "type": "shell", "params": {"command": "echo hi"}},
        ],
        "edges": [],
    }
    # Sanity-check the fixture: the validator MUST emit at least one
    # non-cache diagnostic, otherwise the assertion below is vacuous.
    raw = validate_data_flow(workflow_ir, check_inputs=False)
    has_non_cache = any((d.id is None) or not d.id.startswith("cache.") for d in raw)
    assert has_non_cache, "Test fixture must produce at least one non-cache diagnostic to be a valid negative control."

    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)
    # The actual A.6 contract: analyze.warnings carries ONLY cache.* IDs.
    assert all(d.id and d.id.startswith("cache.") for d in result.warnings)


# ---------------------------------------------------------------------------
# Trace auto-load — hash-prefix glob (O(matches), not O(directory))
# ---------------------------------------------------------------------------


def _write_trace(
    debug_dir: Path,
    *,
    workflow_path: str,
    format_version: str,
    workflow_name: str = "x",
) -> Path:
    """Write a synthetic trace under the production filename schema.

    Uses ``format_trace_filename`` so the test fixture matches the same hash
    prefix the autoload reader globs by — without that, autoload skips the
    file even when contents match.
    """
    from pflow.runtime.workflow_trace import format_trace_filename

    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = f"20260430-{time.time_ns() % 1_000_000:06d}"
    name = format_trace_filename(workflow_path, workflow_name, timestamp)
    path = debug_dir / name
    path.write_text(
        json.dumps({"format_version": format_version, "workflow_path": workflow_path, "events": []}),
        encoding="utf-8",
    )
    return path


def test_autoload_finds_2_1_0_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    path = _write_trace(debug_dir, workflow_path="/abs/x.pflow.md", format_version="2.1.0")

    workflow_ir = {"nodes": []}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path == str(path)


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
    assert any("Gemini telemetry" in n for n in notes)


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


def test_savings_pct_uses_cohort_consistent_denominator_not_input_only_superset() -> None:
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
    ``savings_first_run_usd`` but ZERO to ``no_cache_hypothetical_usd``. The
    fixture's structural assertion (``aggregate_savings > current``) confirms
    the bug scenario IS exercised before the percentage check fires.
    """
    # Row A: tiny input (100) + tiny output (50), no cache subset. This is
    # the only row contributing to ``no_cache_hypothetical_usd`` — and it's small.
    # Rows B/C/D/E/F: large cache-using rows with NO output. They populate
    # ``savings_first_run_usd`` (input-only superset) but NOT ``no_cache_hypothetical_usd``.
    # Result: savings >> current → pre-fix pct > 100% → bug.
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

    # Sanity: fixture must induce the bug scenario before assertions fire.
    # Post-Phase-5: this is post-run greenfield (no trace ctx → actually_paid
    # is None; no_cache_hypothetical is non-None for Row A which has output
    # tokens). The savings anchor falls back to no_cache_hypothetical.
    assert summary.no_cache_hypothetical_usd is not None, "Row A must populate no_cache_hypothetical_usd"
    assert summary.aggregate_savings_first_run_usd is not None, "Rows B/C/D must populate savings"
    assert summary.aggregate_savings_first_run_usd > summary.no_cache_hypothetical_usd, (
        f"Fixture must induce ``savings > no_cache`` to exercise the C2 bug: "
        f"savings={summary.aggregate_savings_first_run_usd}, "
        f"no_cache={summary.no_cache_hypothetical_usd}. Adjust token sizes."
    )

    # Post-fix: percentage is cohort-consistent (rows-with-output only).
    # Row A has no cache subset → its (anchor - first_run_with_cache) is 0 → pct == 0.
    # Pre-fix would render ``savings_first_run_usd / anchor`` over different
    # rowsets which exceeds 100% — > 100% → bug.
    pct = summary.savings_pct_first_run
    assert pct is not None, "savings anchor is non-None → pct must be computable"
    assert pct <= 100, (
        f"savings_pct_first_run = {pct} > 100 — denominator mismatch reopened. "
        f"Numerator and denominator must be over the same rowset (rows-with-output)."
    )
    assert pct >= -100, f"savings_pct_first_run = {pct} < -100 — implausible; check cohort math"


def test_aggregate_savings_field_remains_input_only_superset_for_greenfield() -> None:
    """CR-1430 C2 fix preserves the load-bearing greenfield contract: the
    ``aggregate_savings_first_run_usd`` field continues to be input-only and
    superset-of-priced-rows so greenfield workflows still surface a positive
    absolute savings opportunity even when ``current_cost_per_run_usd`` is None.

    The fix is local to ``savings_pct_first_run`` — the absolute aggregate
    savings figure is unchanged.
    """
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
    # But the aggregate savings figure IS populated (input-only, output cancels).
    assert analysis.summary.aggregate_savings_first_run_usd is not None
    assert analysis.summary.aggregate_savings_first_run_usd > 0


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


def test_blocking_errors_filters_out_warnings_and_info() -> None:
    from pflow.core.cache_analysis.view_helpers import build_blocking_errors

    actions = build_blocking_errors([
        _make_diag("cache.order-mismatch", Severity.ERROR),
        _make_diag("cache.below-min-tokens", Severity.WARNING),
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
    assert "model=<varies>" in rendered
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

    Defends: reverting to a static heuristic drops cacheable to ~187
    (heuristic value) and the source label to ``"estimator"`` instead
    of ``"memo"``.
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
    monkeypatch.setattr("litellm.token_counter", lambda model, text: 800)

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


def test_heterogeneous_batch_with_declared_cache_uses_estimator_tier(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heterogeneous batch (``model: ${item.model}``) + declared
    ``prompt_cache`` → Tier 2 short-circuits on empty model; Tier 3 fires.

    Closes Case 8a end-to-end gap: unit test #8 covers the gate; this
    verifies the full path through ``analyze()``.
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
    assert row.cacheable_tokens_estimated is not None and row.cacheable_tokens_estimated > 0
    assert row.cacheable_data_source == "estimator", (
        f"heterogeneous declared row should fall through to estimator; got {row.cacheable_data_source!r}"
    )


def test_below_min_tokens_suppressed_when_trace_evidence_shows_cache_fired(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cache.below-min-tokens`` MUST NOT fire when ``cacheable_data_source``
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
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-tokens"]
    assert not below_min, (
        f"cache.below-min-tokens fired despite trace showing cache fired (cacheable=800, "
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


def test_below_min_tokens_still_fires_when_estimator_says_below_min(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Companion to the suppression test: when source is NOT trace,
    the warning still fires correctly. Locks the inverse contract —
    suppression is keyed on ``"trace"`` specifically, not on cacheable
    > 0 alone.

    Defends: the suppression gate must be keyed on ``"trace"`` specifically;
    any other tier name (``"memo"``, ``"estimator"``) would suppress the
    warning for those sources too.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

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
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "tiny prompt"},
                "prompt_cache": ["context"],
            }
        ],
        "edges": [],
    }
    # No trace, no memo — Tier 3 estimator fires; tiny prompt → small
    # cacheable < anthropic's 1024 min → warning SHOULD fire.
    analysis = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    row = analysis.per_call[0]
    assert row.cacheable_data_source == "estimator"
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-tokens"]
    assert below_min, (
        f"cache.below-min-tokens did NOT fire for estimator-tier row below min_tokens. "
        f"Gate suppression mis-keyed. warnings: {[w.id for w in analysis.warnings]}"
    )


def test_declared_with_zero_creation_zero_read_falls_through_to_memo_e2e(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declared subset + 2.1.0 trace recording cache_creation=0, cache_read=0
    (cache declared but didn't fire — sub-threshold etc.). Tier 1 MUST fall
    through; Tier 2 fires via memo; ``cache.below-min-tokens`` MUST fire
    because the gate's ``cacheable_data_source != "trace"`` clause is now
    True.

    This is the matrix Case 9 — the case that exists specifically to
    preserve ``cache.below-min-tokens`` fidelity when cache fails to engage.
    Without Tier 1 fall-through (e.g., short-circuit returning
    ``(0, "trace")`` per the disputed review-silent-failures C1 finding),
    cacheable_data_source would be ``"trace"``, the gate would suppress the
    warning, and agents would not learn that their declared chunks are
    sub-threshold.

    Mutation contracts:
      A. Replace Tier 1 fall-through with ``return (0, "trace")`` —
         cacheable_data_source becomes ``"trace"``, the gate at
         ``analyze.py:778`` suppresses, ``cache.below-min-tokens`` fails to
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
    # 1024-token threshold so cache.below-min-tokens fires for genuine
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
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-tokens"]
    assert below_min, (
        f"cache.below-min-tokens did NOT fire for declared-but-cache-didn't-fire "
        f"sub-threshold case. Tier 1 fall-through regression. "
        f"warnings: {[w.id for w in analysis.warnings]}"
    )


def test_declared_partial_memo_falls_through_to_estimator_end_to_end(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declared subset of 2 chunks; memo populated for one only. End-to-end
    fall-through to Tier 3 estimator (preserves ``cache.below-min-tokens``
    fidelity for declared-but-incomplete-memo case).
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
    assert row.cacheable_data_source == "estimator", (
        f"declared partial-memo should fall through to estimator; got {row.cacheable_data_source!r}"
    )
    assert row.cacheable_tokens_estimated is not None and row.cacheable_tokens_estimated > 0


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
    assert child_entry.actually_paid_usd in (None, 0.0)


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
    # cache_read_input_tokens=0 keeps the fixture simple — Anthropic's
    # ``splits_cache_from_input_tokens=True`` policy would otherwise sum
    # cache portions into the row's ``input_tokens_estimated`` (verified
    # in ``test_total_input_tokens_anthropic_trace_sums_cache_portions``)
    # and conflate this regression test with that orthogonal contract.
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
    # Bug 1 invariant: cached events must NOT inflate cost. The cost
    # summation path skips them via the unchanged ``if leaf.is_cached:
    # continue`` after index population.
    assert row.cost_usd == 0.0
    assert row.cost_data_source == "trace"
