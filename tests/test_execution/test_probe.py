"""Tests for ``execution/probe.py::probe_node`` — the one probe both `pflow probe` and MCP ``registry_run`` call.

Channel rendering is tested at each channel (tests/test_cli/test_probe.py, tests/test_mcp_server/); these pin
what the shared result carries.
"""

import sqlite3
from pathlib import Path

import pytest

from pflow.core.execution_cache import ExecutionCache
from pflow.execution.probe import probe_node
from pflow.runtime.cache import MemoizationCache


def test_success_caches_outputs_for_read_fields(tmp_path: Path) -> None:
    path = tmp_path / "in.txt"
    path.write_text("hello", encoding="utf-8")

    probe = probe_node("read-file", {"file_path": str(path)})

    assert probe.success and probe.ran
    assert probe.outputs["content"] == "hello"
    assert probe.execution_id is not None
    cached = ExecutionCache().retrieve(probe.execution_id)
    assert cached is not None
    assert cached["outputs"]["content"] == "hello"


def test_cache_keeps_the_callers_params_not_the_expanded_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``${VAR}`` is expanded for the node, but the cache records the param as the caller wrote it."""
    monkeypatch.setenv("PFLOW_PROBE_SECRET_VALUE", "s3cr3t-value")
    target = tmp_path / "out.txt"

    probe = probe_node("write-file", {"file_path": str(target), "content": "${PFLOW_PROBE_SECRET_VALUE}"})

    assert probe.success, probe.errors
    assert target.read_text(encoding="utf-8") == "s3cr3t-value"
    assert probe.execution_id is not None
    cached = ExecutionCache().retrieve(probe.execution_id)
    assert cached is not None
    assert cached["params"]["content"] == "${PFLOW_PROBE_SECRET_VALUE}"
    assert "s3cr3t-value" not in str(cached)


def test_probe_never_writes_the_workflow_memo_cache(mock_llm_client) -> None:
    """An LLM node memoizes by default; a probe must not leave an entry a later workflow run would reuse."""
    mock_llm_client.set_response("*", None, "ok")
    before = _memo_entries()

    probe = probe_node("llm", {"model": "anthropic/claude-sonnet-4-5", "prompt": "hi"})

    assert probe.success, probe.errors
    assert _memo_entries() == before


def _memo_entries() -> list[str]:
    """Memoized outputs only — the per-node duration history (`__pflow_history__:` keys) is not reused as output."""
    with sqlite3.connect(MemoizationCache().db_path) as conn:
        rows = conn.execute("SELECT cache_key FROM cache_entries").fetchall()
    return [key for (key,) in rows if not key.startswith("__pflow_history__:")]


def test_a_secret_json_encoded_into_an_output_is_scrubbed_before_decoding() -> None:
    """A secret with a quote, JSON-encoded by the node, is stored escaped — the probe's renderer and
    `read-fields` decode it, so the escaped form must be scrubbed too."""
    code = 'import json\napi_password: str\nresult: str = json.dumps({"value": api_password})'

    probe = probe_node("code", {"inputs": {"api_password": 'pa"ss-word-99'}, "code": code})

    assert probe.success, probe.errors
    assert probe.outputs["result"] == '{"value": "<REDACTED>"}'
    assert probe.execution_id is not None
    cached = ExecutionCache().retrieve(probe.execution_id)
    assert cached is not None
    assert "ss-word-99" not in str(cached)


def test_cached_params_hide_a_nested_secret() -> None:
    probe = probe_node("shell", {"command": "true", "env": {"API_TOKEN": "s3cr3t-token-value"}})

    assert probe.execution_id is not None
    cached = ExecutionCache().retrieve(probe.execution_id)
    assert cached is not None
    assert cached["params"]["env"]["API_TOKEN"] == "<REDACTED>"  # noqa: S105


def test_a_node_that_ran_and_failed_is_not_cached() -> None:
    probe = probe_node("shell", {"command": "exit 3"})

    assert not probe.success
    assert probe.ran
    assert probe.execution_id is None
    assert probe.outputs["exit_code"] == 3
    (error,) = probe.errors
    assert error.node_id == "shell"


def test_validation_failure_is_refused_before_running() -> None:
    probe = probe_node("shell", {"command": "echo hi", "bogus": 1})

    assert not probe.success
    assert not probe.ran
    assert "Unknown parameter 'bogus'" in probe.errors[0].message


def test_not_found_falls_back_to_available_nodes_when_no_fuzzy_match() -> None:
    """With no near match, the available nodes are listed so the agent has something to pick from."""
    probe = probe_node("xyzzy", {})

    assert not probe.ran
    (error,) = probe.errors
    assert error.title == "Node Not Found"
    assert "shell" in (error.context or {})["similar_names"]


def test_not_found_prefers_near_matches_over_the_full_list() -> None:
    (error,) = probe_node("read", {}).errors

    similar = (error.context or {})["similar_names"]
    assert "read-file" in similar
    assert "shell" not in similar


def test_not_found_suggestions_follow_the_node_kind() -> None:
    (mcp_error,) = probe_node("mcp-slack-send", {}).errors
    (core_error,) = probe_node("shel", {}).errors

    assert any("mcp find" in s for s in mcp_error.suggestions or [])
    assert any("Core node types" in s for s in core_error.suggestions or [])
    assert not any("mcp find" in s for s in core_error.suggestions or [])
