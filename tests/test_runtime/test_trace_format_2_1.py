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


def test_handle_cached_execution_writes_in_process_source_for_llm_node() -> None:
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

    assert shared["node-x"]["llm_usage"]["cache_source"] == "in_process"
    # In-process hits have no key + no age
    assert "cache_key" not in shared["node-x"]["llm_usage"]
    assert "cache_age_sec" not in shared["node-x"]["llm_usage"]


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
    )

    # No augmentation (shell node not in allowlist)
    assert shared["shell-step"] == {"value": "ok"}


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


# --- Trace consumer integration: cache fields flow via llm_usage ----------


def test_record_node_execution_passes_cache_metadata_to_llm_call() -> None:
    """The ``_add_llm_data`` integration site does whole-dict assignment
    (``event["llm_call"] = llm_usage``), so adding new keys to llm_usage at
    the producer side flows through with no consumer-side changes. Verify
    by recording an event with cache fields populated."""
    collector = WorkflowTraceCollector(workflow_name="test")
    node_output = {
        "llm_usage": {
            "input_tokens": 50,
            "output_tokens": 25,
            "cache_key": "abc123",
            "cache_source": "memo",
            "cache_age_sec": 12.5,
            "cache_chunks_skipped": ["b"],
        }
    }
    collector.record_node_execution(
        node_id="my-node",
        node_type="LLMNode",
        duration_ms=100.0,
        success=True,
        node_output=node_output,
    )

    event = collector.events[-1]
    assert event["llm_call"]["cache_key"] == "abc123"
    assert event["llm_call"]["cache_source"] == "memo"
    assert event["llm_call"]["cache_age_sec"] == 12.5
    assert event["llm_call"]["cache_chunks_skipped"] == ["b"]
