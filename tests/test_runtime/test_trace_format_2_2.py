"""Trace ``llm_system`` contract tests.

The ``llm_system`` field carries the effective system content seen by the
LLM (``str`` for plain system, ``list[dict]`` for cache-rendered prefixes
with provider-specific ``cache_control`` markers). Tests pin:

- ``llm_system`` is recorded on LLM events when system content is present;
  absent on non-LLM events and on LLM events without system content.
- Both string and list-of-blocks shapes survive serialization round-trip.
"""

from __future__ import annotations

from typing import Any

import pytest

from pflow.core.trace_io import load_trace_file
from pflow.runtime.workflow_trace import TRACE_FORMAT_VERSION, WorkflowTraceCollector

pytestmark = pytest.mark.trace_files

# --- Format version ---------------------------------------------------------


def test_format_version_is_2_5_0() -> None:
    assert TRACE_FORMAT_VERSION == "2.5.0"


def test_saved_trace_records_format_version(tmp_path, monkeypatch) -> None:
    """Saved trace JSON carries the current format_version constant."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    collector = WorkflowTraceCollector(workflow_name="t", workflow_path=None, is_run_scoped=True, stream_to_disk=True)

    trace_path = collector.save_to_file()
    trace_data = load_trace_file(trace_path)

    assert trace_data["format_version"] == TRACE_FORMAT_VERSION


# --- llm_system on LLM events ----------------------------------------------


def test_2_2_0_trace_includes_llm_system_string_for_llm_node() -> None:
    """Plain string system content is captured on the LLM event."""
    collector = WorkflowTraceCollector(workflow_name="t")
    hook = collector.get_trace_hook("llm-1")
    hook({"event": "before_call", "model": "anthropic/claude-sonnet-4-5", "prompt": "Hi", "system": "You are helpful."})

    collector.record_node_execution(
        node_id="llm-1",
        node_type="LLMNode",
        duration_ms=10.0,
        success=True,
        node_output={"response": "ok", "llm_usage": {"input_tokens": 5}},
    )

    event = collector.events[0]
    assert event["llm_system"] == "You are helpful."


def test_2_2_0_trace_includes_llm_system_list_for_cached_prefix() -> None:
    """Cache-rendered list[dict] (with cache_control) survives intact."""
    collector = WorkflowTraceCollector(workflow_name="t")
    system_blocks: list[dict[str, Any]] = [
        {"type": "text", "text": "User base system"},
        {"type": "text", "text": "Cached chunk", "cache_control": {"type": "ephemeral"}},
    ]
    hook = collector.get_trace_hook("llm-1")
    hook({"event": "before_call", "model": "anthropic/claude-sonnet-4-5", "prompt": "Hi", "system": system_blocks})

    collector.record_node_execution(
        node_id="llm-1",
        node_type="LLMNode",
        duration_ms=10.0,
        success=True,
        node_output={"response": "ok", "llm_usage": {"input_tokens": 5}},
    )

    event = collector.events[0]
    assert event["llm_system"] == system_blocks
    # Marker preserved end-to-end
    assert event["llm_system"][-1]["cache_control"] == {"type": "ephemeral"}


def test_2_2_0_trace_omits_llm_system_when_no_system_supplied() -> None:
    """``system=None`` (or absent) → no entry written; event has no
    ``llm_system`` key."""
    collector = WorkflowTraceCollector(workflow_name="t")
    hook = collector.get_trace_hook("llm-1")
    hook({"event": "before_call", "model": "anthropic/claude-sonnet-4-5", "prompt": "Hi", "system": None})

    collector.record_node_execution(
        node_id="llm-1",
        node_type="LLMNode",
        duration_ms=10.0,
        success=True,
        node_output={"response": "ok", "llm_usage": {"input_tokens": 5}},
    )

    assert "llm_system" not in collector.events[0]


def test_2_2_0_trace_omits_llm_system_for_non_llm_nodes() -> None:
    """Shell, code, http etc. don't fire the LLM trace_hook → no
    ``llm_system`` field on their events."""
    collector = WorkflowTraceCollector(workflow_name="t")
    collector.record_node_execution(
        node_id="shell-1",
        node_type="ShellNode",
        duration_ms=5.0,
        success=True,
        node_output={"stdout": "hi", "exit_code": 0},
    )

    assert "llm_system" not in collector.events[0]


def test_2_2_0_llm_system_serializes_through_save_roundtrip(tmp_path, monkeypatch) -> None:
    """list[dict] survives JSON serialization with cache_control intact."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    collector = WorkflowTraceCollector(workflow_name="t", is_run_scoped=True, stream_to_disk=True)
    system_blocks: list[dict[str, Any]] = [
        {"type": "text", "text": "Reference"},
        {"type": "text", "text": "Body", "cache_control": {"type": "ephemeral"}},
    ]
    hook = collector.get_trace_hook("llm-1")
    hook({"event": "before_call", "model": "anthropic/claude-sonnet-4-5", "prompt": "Hi", "system": system_blocks})
    collector.record_node_execution(
        node_id="llm-1",
        node_type="LLMNode",
        duration_ms=1.0,
        success=True,
        node_output={"response": "ok", "llm_usage": {"input_tokens": 5}},
    )

    trace_path = collector.save_to_file()
    saved = load_trace_file(trace_path)
    saved_event = saved["nodes"][0]
    assert saved_event["llm_system"] == system_blocks
