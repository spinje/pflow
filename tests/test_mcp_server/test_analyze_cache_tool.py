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
