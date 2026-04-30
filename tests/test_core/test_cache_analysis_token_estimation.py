"""F1.2 — token-estimation tier order (trace → memo → estimator → heuristic)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from pflow.core.cache_analysis.token_estimation import (
    estimate_tokens,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeMemoCache:
    """Minimal stand-in for MemoizationCache.get_latest_for_node."""

    def __init__(self, payload: dict[str, Any] | None) -> None:
        self._payload = payload

    def get_latest_for_node(
        self, node_id: str, *, workflow_path: str | None = None
    ) -> tuple[dict[str, Any], float] | None:
        if self._payload is None:
            return None
        import time

        return (self._payload, time.time())


def _trace_with_node(node_id: str, input_tokens: int) -> dict[str, Any]:
    """Build a synthetic trace dict shaped like what
    ``runtime/workflow_trace.WorkflowTraceCollector.save_to_file`` writes.

    The top-level events key is ``"nodes"`` — NOT ``"events"``. Earlier
    versions of this helper used ``"events"``, which made ALL `estimate_tokens`
    tests pass while production tier-1 trace lookups silently failed (the
    Pitfall #19 anti-pattern from ``tests/CLAUDE.md``: synthetic fixtures
    matching a buggy reader rather than production shape).
    """
    return {
        "format_version": "2.1.0",
        "nodes": [
            {
                "node_id": node_id,
                "llm_call": {"input_tokens": input_tokens},
            }
        ],
    }


# ---------------------------------------------------------------------------
# Tier ordering — DD#34 / DD#31
# ---------------------------------------------------------------------------


def test_trace_wins_when_both_trace_and_memo_present() -> None:
    """Catches tier-inversion bugs: trace must win when both sources exist."""
    trace = _trace_with_node("X", input_tokens=4000)
    memo = _FakeMemoCache({"llm_usage": {"input_tokens": 999}})
    count, source = estimate_tokens("claude-sonnet-4-5", "irrelevant", trace=trace, memo_cache=memo, node_id="X")
    assert source == "trace"
    assert count == 4000


def test_memo_wins_when_no_trace_match() -> None:
    """When trace ABSENT, memo present → source = memo."""
    memo = _FakeMemoCache({"llm_usage": {"input_tokens": 2500}})
    count, source = estimate_tokens("claude-sonnet-4-5", "hello world", memo_cache=memo, node_id="X")
    assert source == "memo"
    assert count == 2500


def test_estimator_wins_when_no_trace_no_memo() -> None:
    """token_counter is the next tier."""
    count, source = estimate_tokens("claude-sonnet-4-5", "hello world test")
    assert source == "estimator"
    assert count > 0


def test_heuristic_when_text_is_none_and_warning_emitted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """text=None must NOT crash — falls through to heuristic with logger.warning
    (review-silent-failures W2: a model-name typo deserves visibility)."""
    caplog.set_level(logging.WARNING, logger="pflow.core.cache_analysis.token_estimation")
    count, source = estimate_tokens("claude-sonnet-4-5", None)  # type: ignore[arg-type]
    assert source == "heuristic"
    assert count == 0  # heuristic on None falls back to len("") // 4
    assert any(rec.levelname == "WARNING" for rec in caplog.records)


def test_heuristic_for_empty_string() -> None:
    count, source = estimate_tokens("claude-sonnet-4-5", "")
    # Empty string passes through token_counter cleanly → 0, source = estimator.
    assert count == 0
    assert source in {"estimator", "heuristic"}


def test_unknown_model_falls_back_to_estimator_with_default_tokenizer() -> None:
    """LiteLLM's token_counter does NOT raise on unknown models — falls back to
    a default tokenizer. Verified empirically (progress-log §35).
    Source label is `estimator` (slightly inaccurate), not `heuristic`."""
    count, source = estimate_tokens("brand-new-future-model-2099", "hello world test")
    assert count > 0
    assert source == "estimator"


def test_heuristic_returns_chars_div_4_when_estimator_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If token_counter raises (future regression), fall through to heuristic."""

    def _boom(*_args: Any, **_kwargs: Any) -> int:
        raise RuntimeError("synthetic estimator failure")

    monkeypatch.setattr("litellm.token_counter", _boom)
    text = "x" * 100
    count, source = estimate_tokens("claude-sonnet-4-5", text)
    assert source == "heuristic"
    assert count == 25  # len(text) // 4


def test_trace_with_no_matching_event_falls_back_to_memo() -> None:
    """A trace that exists but doesn't carry a per-event entry for this node_id
    must NOT misroute as `trace` source."""
    trace = _trace_with_node("OTHER", input_tokens=4000)
    memo = _FakeMemoCache({"llm_usage": {"input_tokens": 2500}})
    count, source = estimate_tokens("claude-sonnet-4-5", "hello", trace=trace, memo_cache=memo, node_id="X")
    assert source == "memo"
    assert count == 2500


def test_memo_without_input_tokens_falls_through_to_estimator() -> None:
    """A memo entry that lacks llm_usage.input_tokens (e.g., a non-LLM node's
    output) must NOT be claimed as `memo` source."""
    memo = _FakeMemoCache({"some_other_field": "value"})  # no llm_usage
    count, source = estimate_tokens("claude-sonnet-4-5", "hello world", memo_cache=memo, node_id="X")
    assert source == "estimator"
    assert count > 0


# ---------------------------------------------------------------------------
# Production-shape regression — defends against Pitfall #19 reoccurring
# ---------------------------------------------------------------------------


def test_tier_1_trace_works_with_real_collector_round_trip(tmp_path: Any, monkeypatch: Any) -> None:
    """Production-shape contract: a trace produced by ``WorkflowTraceCollector``
    and saved via ``save_to_file`` must be readable by ``estimate_tokens`` for
    tier-1 ``trace`` source.

    Earlier versions of ``_llm_call_field_from_trace`` read
    ``trace.get("events")`` while the collector writes the top-level events
    list under the key ``"nodes"``. ALL synthetic-fixture tests passed because
    they matched the buggy reader; production users got estimator/heuristic
    instead of trace tier silently. This is the Pitfall #19 anti-pattern from
    ``tests/CLAUDE.md``: every consumer that walks production data structures
    needs at least one test that drives a real producer end-to-end.
    """
    import json

    from pflow.runtime.workflow_trace import WorkflowTraceCollector

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    collector = WorkflowTraceCollector(
        workflow_name="test-roundtrip",
        workflow_path="/some/path/test.pflow.md",
    )
    collector.record_node_execution(
        node_id="emit",
        node_type="LLMNode",
        duration_ms=1.0,
        success=True,
        node_output={
            "response": "ok",
            "llm_usage": {
                "input_tokens": 1234,
                "output_tokens": 7,
                "model": "claude-haiku-4-5",
            },
        },
    )

    saved_path = collector.save_to_file()
    trace_data = json.loads(saved_path.read_text())

    # Sanity: the collector wrote the events under the canonical "nodes" key.
    assert "nodes" in trace_data, "Producer contract drifted — events key changed"
    assert len(trace_data["nodes"]) == 1
    assert trace_data["nodes"][0]["node_id"] == "emit"

    # Tier-1 reader finds the input_tokens via the production-shaped trace.
    count, source = estimate_tokens(
        "claude-haiku-4-5",
        "irrelevant-prompt",
        trace=trace_data,
        node_id="emit",
    )
    assert source == "trace", f"Tier-1 unreachable in production shape: source={source!r}"
    assert count == 1234
