"""F3.2 — MCP ``analyze_cache`` tool parity tests.

Locks the MCP↔CLI parity invariant per Task 152: every shared formatter has
two call sites, and ``render_json(analyze(...))`` is the single formatter the
MCP tool reuses. Tests assert:
- The MCP service returns the same JSON shape as CLI ``--format=json``.
- Round-trips through json.dumps/loads cleanly (no Path/set leaking).
- The tool docstring contains every catalog ID + version policy + tri-state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pflow.core.cache_analysis.warning_catalog import CACHE_WARNING_CATALOG
from pflow.mcp_server.services.execution_service import ExecutionService
from pflow.mcp_server.tools.execution_tools import analyze_cache as analyze_cache_tool

_LLM_WORKFLOW = """\
# LLM Test

A workflow with an LLM node and a Cache block.

## Inputs

### topic

The topic to analyze.

- type: string

## Cache

```cache
The topic of the analysis:

${topic}
```

## Steps

### review

Summarize the topic.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [topic]

```prompt
Summarize ${topic}.
```
"""


def _write_workflow(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "wf.pflow.md"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Service-level parity (the production code path the tool wraps)
# ---------------------------------------------------------------------------


def test_service_returns_json_shape(tmp_path: Path) -> None:
    from pflow.core.cache_analysis import JSON_FORMAT_VERSION

    workflow_path = _write_workflow(tmp_path, _LLM_WORKFLOW)
    result = ExecutionService.analyze_cache(str(workflow_path))
    assert isinstance(result, dict)
    assert result["format_version"] == JSON_FORMAT_VERSION
    assert "summary" in result
    assert "warnings" in result
    assert "cross_workflow" in result


def test_service_json_round_trips_cleanly(tmp_path: Path) -> None:
    """JSON round-trip: catches non-serializable values (Path, set, etc.)
    leaking into the response."""
    workflow_path = _write_workflow(tmp_path, _LLM_WORKFLOW)
    result = ExecutionService.analyze_cache(str(workflow_path))
    round_tripped = json.loads(json.dumps(result))
    assert round_tripped == result


def test_service_empty_arrays_in_cross_workflow(tmp_path: Path) -> None:
    """Empty-array contract — agents treat absence as a positive signal."""
    workflow_path = _write_workflow(tmp_path, _LLM_WORKFLOW)
    result = ExecutionService.analyze_cache(str(workflow_path))
    cw = result["cross_workflow"]
    assert cw["rename_detections"] == []
    assert cw["prose_mismatches"] == []
    assert cw["value_flow_opportunities"] == []


def test_service_with_parameters(tmp_path: Path) -> None:
    from pflow.core.cache_analysis import JSON_FORMAT_VERSION

    workflow_path = _write_workflow(tmp_path, _LLM_WORKFLOW)
    # Optional parameters per DD#35.
    result = ExecutionService.analyze_cache(str(workflow_path), {"topic": "climate change"})
    assert result["format_version"] == JSON_FORMAT_VERSION


def test_service_raises_for_invalid_workflow_path() -> None:
    """Missing workflow → ValueError (same shape as plan_workflow / workflow_validate)."""
    import pytest

    with pytest.raises(ValueError):
        ExecutionService.analyze_cache("/abs/missing.pflow.md")


def test_async_tool_wrapping_returns_dict(tmp_path: Path) -> None:
    """Locks the async/sync bridge contract: ``await analyze_cache_tool(...)``
    must return the same JSON shape that ``ExecutionService.analyze_cache``
    produces synchronously. Catches a future regression where the
    ``asyncio.to_thread`` bridge is dropped or the result is wrapped in a
    ``CallToolResult`` without unwrapping."""
    import asyncio

    from pflow.core.cache_analysis import JSON_FORMAT_VERSION

    workflow_path = _write_workflow(tmp_path, _LLM_WORKFLOW)
    # FastMCP wraps the original async function in a FunctionTool; reach
    # through ``.fn`` to call the coroutine directly. Falls back to the tool
    # itself if the FastMCP shape ever changes (older versions exposed the
    # function as the tool object directly).
    fn = getattr(analyze_cache_tool, "fn", analyze_cache_tool)
    result = asyncio.run(fn(workflow=str(workflow_path)))

    sync_result = ExecutionService.analyze_cache(str(workflow_path))
    assert isinstance(result, dict)
    assert result["format_version"] == JSON_FORMAT_VERSION
    # Strip the only non-deterministic field — ``analyzed_at`` uses
    # ``datetime.now`` per analyze.py:257. Both calls land within the same
    # second in practice, but exclude defensively so a tick-boundary doesn't
    # flake the test.
    result.pop("analyzed_at", None)
    sync_result.pop("analyzed_at", None)
    # Full deep equality — sync vs async paths are byte-equivalent for the
    # same input. ``set(keys)`` would only catch top-level shape regressions;
    # this catches any per-field divergence (e.g., async path losing a list
    # ordering or stripping a nested context dict).
    assert result == sync_result


# ---------------------------------------------------------------------------
# Tool docstring contract — locks the agent-facing schema
# ---------------------------------------------------------------------------


def _docstring_text() -> str:
    """Get the analyze_cache tool's docstring (FastMCP wraps with FunctionTool)."""
    # FastMCP wraps the original function — descend through .fn / .description / __wrapped__
    candidates = [
        getattr(analyze_cache_tool, "fn", None),
        getattr(analyze_cache_tool, "__wrapped__", None),
        analyze_cache_tool,
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        doc = getattr(candidate, "__doc__", None)
        if doc:
            return doc
    desc = getattr(analyze_cache_tool, "description", "")
    return desc or ""


def test_docstring_contains_format_version() -> None:
    doc = _docstring_text()
    assert "format_version" in doc


def test_docstring_contains_version_policy() -> None:
    doc = _docstring_text()
    assert "startswith" in doc
    assert "1.x" in doc or "1.0" in doc


def test_docstring_contains_partial_cost_usd() -> None:
    """Tri-state cost contract surfaces in the agent-facing docs."""
    doc = _docstring_text()
    assert "partial_cost_usd" in doc


def test_docstring_contains_data_source() -> None:
    """Per-call data_source vocabulary surfaces in the agent-facing docs."""
    doc = _docstring_text()
    assert "data_source" in doc
    # All four values listed.
    for source in ("trace", "memo", "estimator", "heuristic"):
        assert source in doc


def test_docstring_lists_every_catalog_id() -> None:
    """Catches docstring-rot: a new catalog ID added without updating docs.

    Iterates the catalog at test time so adding entries doesn't drift the test.
    """
    doc = _docstring_text()
    for warning_id in CACHE_WARNING_CATALOG:
        assert warning_id in doc, f"docstring missing catalog ID: {warning_id}"


# ---------------------------------------------------------------------------
# Inline (dict) workflow autoload — the MCP-only path that adversarial drill
# surfaced as silently broken. CLI never reaches the inline path
# (``resolve_workflow`` always populates ``file_path`` from a string arg);
# MCP ``analyze_cache`` accepts ``dict[str, Any]`` per the tool signature
# (``execution_tools.py:355``), so it's the only surface where this matters.
# Without the lookup-path canonicalization fix in ``analyze()``, the autoload
# would compute ``md5("<inline>")`` while the trace writer stored
# ``ir-hash:<md5>`` — autoload silently misses every inline-workflow trace.
# ---------------------------------------------------------------------------


def test_inline_workflow_autoload_finds_canonical_ir_hash_trace(tmp_path: Path, monkeypatch: Any) -> None:
    """When the MCP service receives an inline (dict) workflow that was
    previously run + traced, autoload must find the trace via the same
    ``ir-hash:<md5>`` identifier the trace writer used.

    Production-shape contract:
    1. Call site (MCP service) passes ``workflow_path=resolved.file_path``
       (which is ``None`` for inline dict input).
    2. ``analyze()`` derives the canonical ``ir-hash:<md5>`` via
       ``synthesize_inline_workflow_id(ir)`` for the autoload hash + memo
       scoping (single source of truth across writer + reader).
    3. Autoload computes the filename hash prefix from that canonical
       identifier and finds the matching trace.
    """
    import json

    from pflow.core.workflow_id import synthesize_inline_workflow_id
    from pflow.runtime.workflow_trace import WorkflowTraceCollector

    # Redirect ``Path.home()`` so the autoload reads from the test's tmp dir,
    # not the user's real ``~/.pflow/debug/``. The runtime + analyzer both
    # construct the path via ``Path.home() / ".pflow" / "debug"``.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Inline workflow IR — what the MCP tool would receive as a dict arg.
    inline_ir = {
        "ir_version": "0.1.0",
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {
                "id": "review",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Summarize ${topic}.",
                },
                "prompt_cache": ["topic"],
            },
        ],
        "cache": {
            "items": [{"name": "topic", "var": "${topic}", "prose_before": "Topic: "}],
        },
    }

    # Pre-seed a 2.1.0 trace under the canonical ``ir-hash:<md5>`` identifier
    # — same path the runtime would store when this inline workflow runs.
    expected_workflow_path = synthesize_inline_workflow_id(inline_ir)
    assert expected_workflow_path.startswith("ir-hash:"), (
        "synthesize_inline_workflow_id contract changed; inline trace correlation will silently break"
    )

    collector = WorkflowTraceCollector(
        workflow_name="inline-mcp-test",
        workflow_path=expected_workflow_path,
    )
    collector.record_node_execution(
        node_id="review",
        node_type="LLMNode",
        duration_ms=1.0,
        success=True,
        node_output={
            "response": "ok",
            "llm_usage": {
                "input_tokens": 8888,
                "output_tokens": 5,
                "model": "claude-sonnet-4-5",
            },
        },
    )
    saved_path = collector.save_to_file()
    assert saved_path.exists()

    # Sanity: the saved filename encodes the same hash the autoload will glob.
    import hashlib

    expected_hash = hashlib.md5(expected_workflow_path.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    assert expected_hash in saved_path.name, (
        f"trace filename {saved_path.name!r} missing expected hash prefix {expected_hash!r}"
    )

    # Drive the MCP service with the inline dict — what the tool would receive.
    result = ExecutionService.analyze_cache(inline_ir)

    # Autoload found the trace via the canonical inline ID:
    assert result["trace_path"] == str(saved_path), (
        f"autoload missed inline-workflow trace; trace_path={result['trace_path']!r} "
        f"expected={str(saved_path)!r}. Likely cause: writer + reader diverged on the "
        f"canonical inline-workflow identifier."
    )
    # Tier-1 trace fired for the per-call row (1 LLM node):
    assert result["estimate_confidence"] == "high_from_trace", (
        f"tier-1 trace unreachable for inline workflow; confidence={result['estimate_confidence']!r}"
    )
    coverage = result["estimate_confidence_coverage"]
    assert coverage["trace"] == 1 and coverage["total"] == 1
    # The trace's input_tokens (8888) propagated into per_call:
    per_call = result["per_call"]
    assert len(per_call) == 1
    assert per_call[0]["data_source"] == "trace"
    assert per_call[0]["input_tokens_estimated"] == 8888

    # Sanity-check the displayed identifier — kept as ``"<inline>"`` for
    # human-readable rendering (separate from the canonical lookup ID).
    assert result["workflow_path"] == "<inline>"

    # Round-trip: result is JSON-serializable.
    json.dumps(result)
