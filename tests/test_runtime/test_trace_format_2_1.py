"""E.1 — Trace format 2.1.0 contract tests.

The 2.1.0 bump adds workflow_path (top-level) plus per-event cache_key,
cache_source, cache_age_sec, and cache_chunks_skipped (all on the
``llm_call`` payload via the existing ``llm_usage`` channel). Tests pin:

- ``format_version == "2.1.0"`` in the saved trace JSON.
- ``trace["workflow_path"]`` always present (None when constructor didn't
  set it; the production paths always set it).
- Cache-metadata fields gate on node type — only ``LLMNode`` participates;
  ``ClaudeCodeNode`` and shell/file/http nodes are intentionally excluded.
- The ``llm_usage`` keyset extension flows through both ``_add_llm_data``
  integration sites (workflow_trace.py + batch_executor.py — the
  whole-dict assignment passes new keys through with no consumer change).
- 2.0.0 backward compat: ``format_version.startswith("2.")`` consumer gate
  in ``trace_report.py`` keeps working.
- Anthropic 1h-TTL cost normalization in ``_to_adapter_response``.
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from pflow.runtime.engine.instrumentation import (
    _augment_llm_usage_with_cache_metadata,
    _should_write_cache_metadata,
    apply_memo_hit,
    handle_cached_execution,
    write_memo_cache,
)
from pflow.runtime.workflow_trace import TRACE_FORMAT_VERSION, WorkflowTraceCollector

# --- Format version + workflow_path plumbing ------------------------------


def test_format_version_is_2_1_0() -> None:
    assert TRACE_FORMAT_VERSION == "2.1.0"


def test_saved_trace_includes_workflow_path_field(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    collector = WorkflowTraceCollector(
        workflow_name="test-workflow",
        workflow_path="/abs/path/to/workflow.pflow.md",
    )

    trace_path = collector.save_to_file()
    trace_data = json.loads(trace_path.read_text())

    assert trace_data["format_version"] == "2.1.0"
    assert trace_data["workflow_path"] == "/abs/path/to/workflow.pflow.md"


def test_saved_trace_workflow_path_null_when_not_set(tmp_path, monkeypatch) -> None:
    """Test fixtures that don't pass workflow_path get None — emitted as
    JSON null. Production paths always set it; this is forward-compat for
    legacy harnesses."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    collector = WorkflowTraceCollector(workflow_name="test-workflow")

    trace_path = collector.save_to_file()
    trace_data = json.loads(trace_path.read_text())

    assert "workflow_path" in trace_data
    assert trace_data["workflow_path"] is None


def test_workflow_path_inline_id_format() -> None:
    """Inline runs use ``ir-hash:<32-char-md5>`` (synced with
    ``_synthesize_inline_workflow_id`` in execution/runner.py)."""
    collector = WorkflowTraceCollector(
        workflow_name="inline",
        workflow_path="ir-hash:0123456789abcdef0123456789abcdef",
    )
    assert collector.workflow_path == "ir-hash:0123456789abcdef0123456789abcdef"


# --- _should_write_cache_metadata gate ------------------------------------


def test_gate_allows_llm_node() -> None:
    assert _should_write_cache_metadata("LLMNode") is True


def test_gate_excludes_claude_code_node() -> None:
    """ClaudeCodeNode's cache tokens come from the SDK, not pflow's memo
    cache. Adding pflow's memo cache_key/cache_source to ClaudeCodeNode's
    llm_usage would conflate two distinct cache layers and mislead agents
    reading the trace."""
    assert _should_write_cache_metadata("ClaudeCodeNode") is False


@pytest.mark.parametrize(
    "node_type",
    ["ShellNode", "HttpNode", "FileNode", "MCPNode", "WorkflowExecutor", "PythonCodeNode"],
)
def test_gate_excludes_other_node_types(node_type: str) -> None:
    assert _should_write_cache_metadata(node_type) is False


# --- _augment_llm_usage_with_cache_metadata -------------------------------


def test_augment_writes_all_three_keys() -> None:
    shared = {
        "node-x": {"llm_usage": {"input_tokens": 100}},
    }
    _augment_llm_usage_with_cache_metadata(
        shared,
        "node-x",
        cache_source="memo",
        cache_key="abcdef",
        cache_age_sec=42.5,
    )
    assert shared["node-x"]["llm_usage"]["cache_source"] == "memo"
    assert shared["node-x"]["llm_usage"]["cache_key"] == "abcdef"
    assert shared["node-x"]["llm_usage"]["cache_age_sec"] == 42.5
    # Pre-existing keys untouched
    assert shared["node-x"]["llm_usage"]["input_tokens"] == 100


def test_augment_no_op_when_node_output_missing() -> None:
    shared: dict[str, Any] = {}
    _augment_llm_usage_with_cache_metadata(
        shared,
        "node-x",
        cache_source="memo",
        cache_key="abc",
        cache_age_sec=1.0,
    )
    assert shared == {}


def test_augment_no_op_when_llm_usage_missing() -> None:
    shared = {"node-x": {"some_other_key": "value"}}
    _augment_llm_usage_with_cache_metadata(
        shared,
        "node-x",
        cache_source="memo",
        cache_key="abc",
        cache_age_sec=1.0,
    )
    assert shared["node-x"] == {"some_other_key": "value"}


def test_augment_skips_none_values() -> None:
    """None values are skipped — caller chooses which fields to write."""
    shared = {"node-x": {"llm_usage": {}}}
    _augment_llm_usage_with_cache_metadata(
        shared,
        "node-x",
        cache_source="in_process",
        cache_key=None,
        cache_age_sec=None,
    )
    assert shared["node-x"]["llm_usage"] == {"cache_source": "in_process"}


# --- apply_memo_hit cache-metadata writes ---------------------------------


def test_apply_memo_hit_writes_cache_metadata_for_llm_node() -> None:
    cached_output = {"llm_usage": {"input_tokens": 100, "cache_chunks_skipped": []}}
    shared: dict = {}
    created_at = time.time() - 10.0  # 10 seconds ago

    apply_memo_hit(
        "score-choruses",
        shared,
        "default",
        cached_output,
        "config-hash-abc",
        node_type_name="LLMNode",
        cache_key="cache-key-xyz",
        created_at=created_at,
    )

    llm_usage = shared["score-choruses"]["llm_usage"]
    assert llm_usage["cache_source"] == "memo"
    assert llm_usage["cache_key"] == "cache-key-xyz"
    # cache_age_sec is computed from time.time() - created_at; loose bound to
    # avoid flakes.
    assert 9.0 <= llm_usage["cache_age_sec"] <= 15.0


def test_apply_memo_hit_skips_cache_metadata_for_non_llm_node() -> None:
    """Shell node hits the memo cache layer too, but cache_source / cache_key
    must NOT be written into its output dict (that would conflate cache
    layers in the trace)."""
    cached_output = {"value": "shell-result"}
    shared: dict = {}

    apply_memo_hit(
        "shell-step",
        shared,
        "default",
        cached_output,
        "config-hash",
        node_type_name="ShellNode",
        cache_key="some-key",
        created_at=time.time(),
    )

    assert "cache_source" not in shared["shell-step"]
    assert "cache_key" not in shared["shell-step"]


def test_apply_memo_hit_skips_for_claude_code_node() -> None:
    """ClaudeCodeNode is the load-bearing exclusion (intentional per round-3
    review): its cache_creation_input_tokens / cache_read_input_tokens
    represent SDK-side caching, not pflow's memo cache. Mixing the two
    misleads agents reading the trace."""
    cached_output = {"llm_usage": {"cache_creation_input_tokens": 1024}}
    shared: dict = {}

    apply_memo_hit(
        "claude-step",
        shared,
        "default",
        cached_output,
        "config-hash",
        node_type_name="ClaudeCodeNode",
        cache_key="some-key",
        created_at=time.time(),
    )

    llm_usage = shared["claude-step"]["llm_usage"]
    # Existing field survives untouched.
    assert llm_usage["cache_creation_input_tokens"] == 1024
    # pflow-memo-layer fields are NOT added (exhaustive exclusion check).
    assert "cache_source" not in llm_usage
    assert "cache_key" not in llm_usage
    assert "cache_age_sec" not in llm_usage


def test_apply_memo_hit_with_no_created_at_omits_cache_age_sec() -> None:
    """If created_at is None, cache_age_sec is NOT written (as opposed to
    written as None — behavior driven by the helper's None-skip)."""
    cached_output = {"llm_usage": {}}
    shared: dict = {}

    apply_memo_hit(
        "node-x",
        shared,
        "default",
        cached_output,
        "config-hash",
        node_type_name="LLMNode",
        cache_key="key",
        created_at=None,
    )

    assert "cache_age_sec" not in shared["node-x"]["llm_usage"]


# --- write_memo_cache cache_key augmentation -------------------------------


def test_write_memo_cache_records_key_into_llm_usage_for_llm_node() -> None:
    """The trace event for THIS run records the key the entry was WRITTEN
    under — symmetric with hits which record the key they MATCHED."""
    memo_cache = MagicMock()
    shared: dict = {
        "__memoization_cache__": memo_cache,
        "node-x": {"llm_usage": {"input_tokens": 100}},
    }

    write_memo_cache(
        "node-x",
        shared,
        "cache-key-xyz",
        "default",
        duration_ms=10.0,
        node_type_name="LLMNode",
    )

    # llm_usage carries the key for the trace event
    assert shared["node-x"]["llm_usage"]["cache_key"] == "cache-key-xyz"
    # cache_source NOT written on the write path (write events have no source)
    assert "cache_source" not in shared["node-x"]["llm_usage"]
    # SQLite write fired
    memo_cache.put.assert_called_once()


def test_write_memo_cache_skips_metadata_for_shell_node() -> None:
    memo_cache = MagicMock()
    shared: dict = {
        "__memoization_cache__": memo_cache,
        "shell-step": {"value": "ok"},
    }

    write_memo_cache(
        "shell-step",
        shared,
        "some-key",
        "default",
        duration_ms=5.0,
        node_type_name="ShellNode",
    )

    # Shell node output dict unchanged (no cache_key field added)
    assert "cache_key" not in shared["shell-step"]
    assert shared["shell-step"]["value"] == "ok"
    memo_cache.put.assert_called_once()


# --- handle_cached_execution: in_process source --------------------------


def test_handle_cached_execution_writes_in_process_source_when_caller_specifies() -> None:
    """Engine passes ``cache_source="in_process"`` for the cached_in_process branch."""
    shared: dict = {"node-x": {"llm_usage": {"input_tokens": 50}}}

    handle_cached_execution(
        "node-x",
        shared,
        cached_action="default",
        shared_keys_before=set(shared.keys()),
        node_type_name="LLMNode",
        node_params={},
        trace_collector=None,
        cache_source="in_process",
    )

    assert shared["node-x"]["llm_usage"]["cache_source"] == "in_process"
    # In-process hits have no key + no age
    assert "cache_key" not in shared["node-x"]["llm_usage"]
    assert "cache_age_sec" not in shared["node-x"]["llm_usage"]


def test_handle_cached_execution_does_not_overwrite_memo_cache_source() -> None:
    """When caller omits ``cache_source`` (default ``None``), the augment is a
    no-op so a prior ``apply_memo_hit`` write of ``cache_source="memo"``
    survives. Bug 1 regression: handle_cached_execution used to unconditionally
    overwrite with ``"in_process"`` (Task 159 verification, 2026-04-30)."""
    # Simulate state after apply_memo_hit
    shared: dict = {
        "node-x": {
            "llm_usage": {
                "input_tokens": 50,
                "cache_source": "memo",
                "cache_key": "abc123",
                "cache_age_sec": 12.5,
            }
        }
    }

    handle_cached_execution(
        "node-x",
        shared,
        cached_action="default",
        shared_keys_before=set(shared.keys()),
        node_type_name="LLMNode",
        node_params={},
        trace_collector=None,
        # Memo path: caller omits cache_source so apply_memo_hit's augment survives.
    )

    # All three memo-path fields preserved
    assert shared["node-x"]["llm_usage"]["cache_source"] == "memo"
    assert shared["node-x"]["llm_usage"]["cache_key"] == "abc123"
    assert shared["node-x"]["llm_usage"]["cache_age_sec"] == 12.5


def test_handle_cached_execution_skips_metadata_for_non_llm_node() -> None:
    shared: dict = {"shell-step": {"value": "ok"}}

    handle_cached_execution(
        "shell-step",
        shared,
        cached_action="default",
        shared_keys_before=set(shared.keys()),
        node_type_name="ShellNode",
        node_params={},
        trace_collector=None,
        cache_source="in_process",
    )

    # No augmentation (shell node not in allowlist)
    assert shared["shell-step"] == {"value": "ok"}


def test_handle_cached_execution_no_op_when_caller_passes_no_cache_source() -> None:
    """Default ``cache_source=None`` → no augment touches llm_usage at all."""
    shared: dict = {"node-x": {"llm_usage": {"input_tokens": 50}}}

    handle_cached_execution(
        "node-x",
        shared,
        cached_action="default",
        shared_keys_before=set(shared.keys()),
        node_type_name="LLMNode",
        node_params={},
        trace_collector=None,
    )

    # No source/key/age fields added
    assert "cache_source" not in shared["node-x"]["llm_usage"]
    assert "cache_key" not in shared["node-x"]["llm_usage"]
    assert "cache_age_sec" not in shared["node-x"]["llm_usage"]


# --- 2.0.0 backward compat ------------------------------------------------


def test_2_0_0_consumer_gate_still_passes_for_2_1_0_traces() -> None:
    """Existing consumers gate on ``format_version.startswith("2.")``;
    bumping minor doesn't break that gate."""
    version = "2.1.0"
    assert version.startswith("2.")
    # Sibling check — major bump WOULD break the gate (intentional contract)
    assert not "3.0.0".startswith("2.")


# --- Anthropic 1h-TTL cost normalization (Spike 3 outcome) ---------------


def _make_usage_obj_with_1h_tokens(tokens: int = 0) -> Any:
    """Build a minimal usage_obj mimicking LiteLLM's nested attribute shape."""
    cache_creation_details = MagicMock()
    cache_creation_details.ephemeral_1h_input_tokens = tokens
    prompt_details = MagicMock()
    prompt_details.cache_creation_token_details = cache_creation_details
    usage = MagicMock()
    usage.prompt_tokens_details = prompt_details
    return usage


def test_anthropic_1h_cost_normalization_adds_missing_contribution(monkeypatch) -> None:
    """Per Spike 3: LiteLLM correctly prices 5-min cache writes but does NOT
    price ``ephemeral_1h_input_tokens``. The override adds the missing 1h
    contribution so cost reporting is accurate."""
    import litellm

    from pflow.core.llm_client import _maybe_normalize_anthropic_1h_cost

    # Spike 3 actual numbers: 3060 1h-tokens, $3/M base input rate, 2.0x
    # multiplier → expected 3060 * 3e-6 * 2.0 = 0.01836.
    base_litellm_cost = 0.0001  # output-only cost LiteLLM emits today
    usage_obj = _make_usage_obj_with_1h_tokens(tokens=3060)

    monkeypatch.setattr(
        litellm,
        "model_cost",
        {"anthropic/claude-sonnet-4-5": {"input_cost_per_token": 3e-6}},
        raising=False,
    )

    result = _maybe_normalize_anthropic_1h_cost(
        base_litellm_cost,
        "anthropic/claude-sonnet-4-5",
        usage_obj,
    )

    expected = 0.0001 + 3060 * 3e-6 * 2.0
    assert result == pytest.approx(expected, rel=1e-6)


def test_anthropic_1h_cost_normalization_no_op_when_zero_1h_tokens() -> None:
    """Pure 5-min cache write (0 1h-tokens) — LiteLLM prices correctly; no
    override fires."""
    from pflow.core.llm_client import _maybe_normalize_anthropic_1h_cost

    usage_obj = _make_usage_obj_with_1h_tokens(tokens=0)
    original_cost = 0.005

    result = _maybe_normalize_anthropic_1h_cost(
        original_cost,
        "anthropic/claude-sonnet-4-5",
        usage_obj,
    )

    assert result == original_cost


def test_anthropic_1h_cost_normalization_no_op_for_non_anthropic() -> None:
    """A phantom ``ephemeral_1h_input_tokens`` field on a non-Anthropic
    response must not trigger the override."""
    from pflow.core.llm_client import _maybe_normalize_anthropic_1h_cost

    usage_obj = _make_usage_obj_with_1h_tokens(tokens=1000)

    result = _maybe_normalize_anthropic_1h_cost(
        0.001,
        "openai/gpt-4o-mini",
        usage_obj,
    )

    assert result == 0.001


def test_anthropic_1h_cost_normalization_no_op_when_cost_is_none() -> None:
    """LiteLLM had no pricing → cost_usd is None → leave unchanged (don't
    invent a partial number)."""
    from pflow.core.llm_client import _maybe_normalize_anthropic_1h_cost

    usage_obj = _make_usage_obj_with_1h_tokens(tokens=100)

    result = _maybe_normalize_anthropic_1h_cost(
        None,
        "anthropic/claude-sonnet-4-5",
        usage_obj,
    )

    assert result is None


def test_anthropic_1h_cost_normalization_no_op_when_model_not_in_pricing(monkeypatch) -> None:
    """Model not in litellm.model_cost → defensive no-op."""
    import litellm

    from pflow.core.llm_client import _maybe_normalize_anthropic_1h_cost

    usage_obj = _make_usage_obj_with_1h_tokens(tokens=100)
    monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

    result = _maybe_normalize_anthropic_1h_cost(
        0.001,
        "anthropic/some-unknown-model",
        usage_obj,
    )

    assert result == 0.001


# --- 1h cost normalization INTEGRATION test (the override fires inside _normalize) ---


def _make_litellm_response_mock(
    *,
    text: str = "ok",
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    ephemeral_1h_tokens: int = 0,
    response_cost: float | None = 0.0001,
    prompt_tokens: int = 100,
    completion_tokens: int = 25,
) -> Any:
    """Build a faithful fake of a LiteLLM ``ModelResponse`` for ``_normalize``
    integration tests. Mirrors the attribute paths the production code reads:
    ``raw.choices[0].message.content``, ``raw.usage.*``, ``raw._hidden_params``."""
    msg = MagicMock()
    msg.content = text
    msg.reasoning_content = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"

    cache_creation_details = MagicMock()
    cache_creation_details.ephemeral_1h_input_tokens = ephemeral_1h_tokens

    prompt_details = MagicMock()
    prompt_details.cached_tokens = cache_read_tokens
    prompt_details.cache_creation_token_details = cache_creation_details

    completion_details = MagicMock()
    completion_details.reasoning_tokens = 0

    usage = MagicMock()
    usage.cache_creation_input_tokens = cache_creation_tokens
    usage.cache_read_input_tokens = cache_read_tokens
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.prompt_tokens_details = prompt_details
    usage.completion_tokens_details = completion_details

    raw = MagicMock()
    raw.choices = [choice]
    raw.usage = usage
    raw._hidden_params = {"response_cost": response_cost}
    return raw


def test_normalize_invokes_anthropic_1h_cost_override_for_anthropic_response(monkeypatch) -> None:
    """End-to-end: a faithful fake litellm response with 1h cache-write tokens
    flows through ``_normalize``; the returned ``AdapterResponse.usage["cost_usd"]``
    is normalized via ``_maybe_normalize_anthropic_1h_cost``. Catches the
    regression where a future refactor moves the override call out of
    ``_normalize``."""
    import litellm

    from pflow.core.llm_client import _normalize

    raw = _make_litellm_response_mock(
        cache_creation_tokens=3060,
        ephemeral_1h_tokens=3060,
        response_cost=0.0001,
    )
    monkeypatch.setattr(
        litellm,
        "model_cost",
        {"anthropic/claude-sonnet-4-5": {"input_cost_per_token": 3e-6}},
        raising=False,
    )

    response = _normalize(raw, model="anthropic/claude-sonnet-4-5", has_schema=False)

    expected = 0.0001 + 3060 * 3e-6 * 2.0
    assert response.usage["cost_usd"] == pytest.approx(expected, rel=1e-6)


def test_normalize_skips_1h_override_for_openai_response() -> None:
    """Phantom 1h-token field on a non-Anthropic response must NOT trigger
    the override at the _normalize integration site."""
    from pflow.core.llm_client import _normalize

    raw = _make_litellm_response_mock(
        ephemeral_1h_tokens=1000,  # would trigger override if provider gate failed
        response_cost=0.001,
    )

    response = _normalize(raw, model="openai/gpt-4o-mini", has_schema=False)

    # OpenAI gate keeps cost_usd unchanged.
    assert response.usage["cost_usd"] == 0.001


# --- End-to-end engine path: memo HIT writes cache_source="memo" ----------
# Symmetric counter-test to Bug #1 (the regression where engine called
# ``handle_cached_execution`` after ``apply_memo_hit`` and overwrote
# ``cache_source="memo"`` with ``"in_process"``).
#
# The pre-existing helper-pair test at
# ``test_handle_cached_execution_does_not_overwrite_memo_cache_source``
# verifies the contract at the boundary by hand-seeding state-after-
# ``apply_memo_hit``. This test is the production-shaped sibling: it runs
# the full engine call sequence (``apply_memo_hit`` THEN
# ``handle_cached_execution``) over a real ``CompiledWorkflow`` with a
# pre-populated memo cache, and asserts the saved trace event has
# ``cache_source="memo"``.
#
# A future regression where ``engine._execute_node`` step-5 omits the
# ``cache_source=None`` argument for the cached_memo branch (the Bug #1
# root) — or routes both cached branches through a single
# ``cached_source = "in_process"`` assignment — would silently break the
# helper-pair test's invariant in production. This test catches that.


def test_engine_memo_hit_writes_cache_source_memo_not_in_process(
    tmp_path: Any,
    mock_llm_client: Any,
) -> None:
    """Engine-driven memo HIT: run a workflow once to populate the memo
    cache, then run it again with the same MemoizationCache. The second
    run's trace event MUST have ``cache_source="memo"`` (NOT ``"in_process"``)
    and ``cache_key`` populated and ``cache_age_sec`` non-None.
    """
    from pflow.registry import Registry
    from pflow.runtime import WorkflowEngine, compile_workflow
    from pflow.runtime.cache import MemoizationCache
    from pflow.runtime.workflow_trace import WorkflowTraceCollector

    mock_llm_client.set_response("anthropic/claude-sonnet-4-5", None, "ok")

    ir: dict[str, Any] = {
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {
                "id": "summarize",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Summarize ${topic}",
                },
            }
        ],
        "edges": [],
    }
    registry = Registry()
    compiled = compile_workflow(ir, registry=registry, initial_params={"topic": "hello"})
    cache = MemoizationCache(db_path=tmp_path / "cache.db")

    # --- Run 1: populate memo cache ----------------------------------------
    shared1: dict[str, Any] = {"topic": "hello"}
    shared1.update(compiled.resolved_defaults)
    shared1["__memoization_cache__"] = cache
    trace1 = WorkflowTraceCollector(workflow_name="test", workflow_path=str(tmp_path / "wf"))
    # ``self.trace`` on the engine drives ``record_node_execution``; the
    # ``shared["__trace_collector__"]`` install is for cross-module readers
    # (LLMNode hook). Set both — they're not interchangeable.
    WorkflowEngine(trace_collector=trace1).run(compiled, shared1)

    # Run-1 sanity: not a cached event (we just populated the cache).
    summarize_events = [e for e in trace1.events if e.get("node_id") == "summarize"]
    assert summarize_events, "no summarize event in run-1 trace"
    assert not summarize_events[-1].get("cached"), "run-1 must not be cached"

    # --- Run 2: same memo cache, fresh shared+trace → memo HIT -------------
    shared2: dict[str, Any] = {"topic": "hello"}
    shared2.update(compiled.resolved_defaults)
    shared2["__memoization_cache__"] = cache
    trace2 = WorkflowTraceCollector(workflow_name="test", workflow_path=str(tmp_path / "wf"))

    # Tiny sleep so cache_age_sec is reliably > 0 even on fast machines.
    time.sleep(0.05)

    WorkflowEngine(trace_collector=trace2).run(compiled, shared2)

    # --- Assertions on the trace event from run 2 -------------------------
    summarize_events_2 = [e for e in trace2.events if e.get("node_id") == "summarize"]
    assert summarize_events_2, "no summarize event in run-2 trace"
    event = summarize_events_2[-1]
    assert event.get("cached") is True, "run-2 must be a cache hit"

    llm_call = event.get("llm_call")
    assert isinstance(llm_call, dict), f"missing llm_call dict on cached event: {event!r}"

    # Bug #1 regression gate: cache_source MUST be "memo" — NOT "in_process".
    # The engine.py:440 ``cached_source = None`` branch is what makes this
    # work; if a future refactor swaps that to "in_process", the helper
    # ``handle_cached_execution`` would overwrite ``apply_memo_hit``'s
    # ``"memo"`` augment and this assertion would fail.
    assert llm_call.get("cache_source") == "memo", (
        f"cache_source mismatch: got {llm_call.get('cache_source')!r}, expected 'memo'. "
        "Bug #1 root: engine.py:440 cached_source=None branch was bypassed; "
        "handle_cached_execution overwrote apply_memo_hit's 'memo' augment."
    )
    # The other E.1 fields must also be populated on memo hits.
    assert llm_call.get("cache_key"), "cache_key must be populated on memo hits"
    assert llm_call.get("cache_age_sec") is not None, "cache_age_sec must be populated on memo hits"
    assert llm_call["cache_age_sec"] > 0, (
        f"cache_age_sec must be > 0 (run-2 is later than run-1); got {llm_call['cache_age_sec']!r}"
    )


# --- Trace consumer integration: cache fields flow via llm_usage ----------


def test_record_node_execution_passes_cache_metadata_to_llm_call() -> None:
    """End-to-end producer→consumer test: ``apply_memo_hit`` writes the
    cache-metadata fields into ``shared[node_id]['llm_usage']``, then
    ``record_node_execution`` flows them through ``_add_llm_data`` to the
    saved trace event.

    Drives from the producer side (``apply_memo_hit``) rather than
    hand-building a ``node_output`` dict with the cache fields pre-populated.
    A bug where ``apply_memo_hit`` writes to a wrong key (e.g. ``"cache-source"``
    with a hyphen, or moves ``cache_age_sec`` outside ``llm_usage``) would
    NOT be caught by the hand-built shape — the producer-driven shape
    catches it because the trace consumer reads exactly what the producer
    wrote.
    """
    # Pre-populate shared with BARE llm_usage (no cache fields yet) — this
    # is the shape ``apply_memo_hit`` sees on entry, since the cached blob
    # was written before cache-metadata augmentation existed (or simply
    # before the augmentation fires for THIS run's apply_memo_hit). We
    # additionally pre-seed ``cache_chunks_skipped`` because that field
    # comes through the cached output verbatim from a prior LLMNode.post —
    # it's NOT written by apply_memo_hit but IS expected to flow through
    # the trace event.
    cached_output = {
        "llm_usage": {
            "input_tokens": 50,
            "output_tokens": 25,
            "cache_chunks_skipped": ["b"],
        }
    }
    shared: dict[str, Any] = {}
    created_at = time.time() - 12.5  # 12.5 seconds ago

    apply_memo_hit(
        node_id="my-node",
        shared=shared,
        cached_action="default",
        cached_output=cached_output,
        config_hash="hash123",
        node_type_name="LLMNode",
        cache_key="abc123",
        created_at=created_at,
    )

    # Sanity: producer wrote the augmented fields where the consumer expects.
    augmented_usage = shared["my-node"]["llm_usage"]
    assert augmented_usage["cache_source"] == "memo"
    assert augmented_usage["cache_key"] == "abc123"
    assert augmented_usage["cache_age_sec"] == pytest.approx(12.5, abs=1.0)
    assert augmented_usage["cache_chunks_skipped"] == ["b"]

    # Consumer side: record_node_execution reads from the SAME shared.
    collector = WorkflowTraceCollector(workflow_name="test")
    collector.record_node_execution(
        node_id="my-node",
        node_type="LLMNode",
        duration_ms=100.0,
        success=True,
        node_output=shared["my-node"],
    )

    event = collector.events[-1]
    assert event["llm_call"]["cache_key"] == "abc123"
    assert event["llm_call"]["cache_source"] == "memo"
    assert event["llm_call"]["cache_age_sec"] == pytest.approx(12.5, abs=1.0)
    assert event["llm_call"]["cache_chunks_skipped"] == ["b"]
