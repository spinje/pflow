"""Unit tests for trace report generator.

Tests the markdown generation functions and directory structure
produced from trace JSON files.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from pflow.core.trace_report import (
    _build_batch_item_file,
    _build_batch_item_summary,
    _build_node_file,
    _build_node_summary,
    _build_summary,
    generate_report,
)

# --- Fixtures ---


def _make_trace(
    nodes: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a minimal valid trace dict."""
    trace: dict[str, Any] = {
        "format_version": "2.0.0",
        "execution_id": "test-exec-id",
        "workflow_name": "test-workflow",
        "start_time": "2026-03-23T10:00:00",
        "end_time": "2026-03-23T10:00:05",
        "duration_ms": 5000.0,
        "final_status": "success",
        "nodes_executed": len(nodes) if nodes else 0,
        "nodes_failed": 0,
        "nodes": nodes or [],
    }
    trace.update(overrides)
    return trace


def _make_event(
    node_id: str = "test-node",
    node_type: str = "TestNode",
    success: bool = True,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a minimal trace event dict."""
    event: dict[str, Any] = {
        "node_id": node_id,
        "node_type": node_type,
        "duration_ms": 100.0,
        "success": success,
        "timestamp": "2026-03-23T10:00:01",
    }
    event.update(overrides)
    return event


# --- generate_report() ---


class TestGenerateReport:
    def test_nonexistent_trace_returns_none(self, tmp_path: Path) -> None:
        result = generate_report(tmp_path / "nonexistent.json")
        assert result is None

    def test_old_format_rejected(self, tmp_path: Path) -> None:
        trace_file = tmp_path / "old.json"
        trace_file.write_text(json.dumps({"format_version": "1.2.0", "nodes": []}))

        result = generate_report(trace_file, str(tmp_path / "report"))
        assert result is None

    def test_creates_report_directory(self, tmp_path: Path) -> None:
        trace = _make_trace(nodes=[_make_event()])
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, str(tmp_path / "report"))

        assert report_dir is not None
        assert report_dir.is_dir()
        assert (report_dir / "summary.md").exists()

    def test_creates_per_node_files(self, tmp_path: Path) -> None:
        trace = _make_trace(
            nodes=[
                _make_event(node_id="fetch"),
                _make_event(node_id="transform"),
            ]
        )
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, str(tmp_path / "report"))

        assert report_dir is not None
        assert (report_dir / "01-fetch.md").exists()
        assert (report_dir / "02-transform.md").exists()

    def test_batch_node_creates_directory(self, tmp_path: Path) -> None:
        batch_event = _make_event(
            node_id="process",
            batch_items=[
                {"index": 0, "item": "a", "success": True, "duration_ms": 50},
                {"index": 1, "item": "b", "success": True, "duration_ms": 60},
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, str(tmp_path / "report"))

        assert report_dir is not None
        assert (report_dir / "01-process").is_dir()
        assert (report_dir / "01-process" / "summary.md").exists()
        assert (report_dir / "01-process" / "item-0.md").exists()
        assert (report_dir / "01-process" / "item-1.md").exists()

    def test_sub_workflow_batch_creates_item_directories(self, tmp_path: Path) -> None:
        """Batch items with nested events get item directories, not files."""
        batch_event = _make_event(
            node_id="create-songs",
            batch_items=[
                {
                    "index": 0,
                    "item": {"concept": "Song A"},
                    "success": True,
                    "duration_ms": 1000,
                    "events": [
                        _make_event(node_id="write-lyrics"),
                        _make_event(node_id="review"),
                    ],
                },
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, str(tmp_path / "report"))

        assert report_dir is not None
        item_dir = report_dir / "01-create-songs" / "item-0"
        assert item_dir.is_dir()
        assert (item_dir / "summary.md").exists()
        assert (item_dir / "01-write-lyrics.md").exists()
        assert (item_dir / "02-review.md").exists()

    def test_sub_workflow_node_creates_directory(self, tmp_path: Path) -> None:
        """Non-batch sub-workflow events create a directory with child files."""
        event = _make_event(
            node_id="sub-workflow",
            sub_workflow_events=[
                _make_event(node_id="step-1"),
                _make_event(node_id="step-2"),
            ],
        )
        trace = _make_trace(nodes=[event])
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, str(tmp_path / "report"))

        assert report_dir is not None
        assert (report_dir / "01-sub-workflow").is_dir()
        assert (report_dir / "01-sub-workflow" / "summary.md").exists()
        assert (report_dir / "01-sub-workflow" / "01-step-1.md").exists()
        assert (report_dir / "01-sub-workflow" / "02-step-2.md").exists()

    def test_auto_output_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        trace = _make_trace(nodes=[_make_event()])
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, "auto")

        assert report_dir is not None
        assert report_dir == tmp_path / ".pflow" / "reports" / "test-workflow"


# --- _build_summary() ---


class TestBuildSummary:
    def test_includes_workflow_name(self) -> None:
        trace = _make_trace(workflow_name="my-pipeline")
        md = _build_summary(trace, source_path="/home/user/.pflow/debug/trace.json")
        assert "# Execution Report: my-pipeline" in md

    def test_includes_status_and_duration(self) -> None:
        trace = _make_trace(final_status="failed", duration_ms=12345.0)
        md = _build_summary(trace, source_path="/home/user/.pflow/debug/trace.json")
        assert "- Status: failed" in md
        assert "- Duration: 12.3s" in md

    def test_includes_llm_summary(self) -> None:
        trace = _make_trace(
            llm_summary={
                "total_calls": 5,
                "total_tokens": 12345,
                "models_used": ["gpt-4", "claude"],
            }
        )
        md = _build_summary(trace, source_path="/home/user/.pflow/debug/trace.json")
        assert "- LLM calls: 5" in md
        assert "- Tokens: 12,345" in md
        assert "gpt-4" in md
        assert "claude" in md

    def test_empty_llm_summary_omitted(self) -> None:
        """LLM summary with zero calls should not render models/tokens lines."""
        trace = _make_trace(
            llm_summary={
                "total_calls": 0,
                "total_tokens": 0,
                "models_used": [],
            }
        )
        md = _build_summary(trace, source_path="test")
        assert "LLM calls" not in md
        assert "Tokens" not in md
        assert "Models" not in md

    def test_llm_summary_without_tokens(self) -> None:
        """LLM summary with calls but zero tokens should omit tokens line."""
        trace = _make_trace(
            llm_summary={
                "total_calls": 1,
                "total_tokens": 0,
                "models_used": ["gpt-4"],
            }
        )
        md = _build_summary(trace, source_path="test")
        assert "- LLM calls: 1" in md
        assert "Tokens" not in md
        assert "- Models: gpt-4" in md

    def test_pipeline_table(self) -> None:
        trace = _make_trace(
            nodes=[
                _make_event(node_id="fetch", node_type="ShellNode", duration_ms=200),
                _make_event(node_id="process", node_type="LLMNode", success=False, duration_ms=500),
            ]
        )
        md = _build_summary(trace, source_path="/home/user/.pflow/debug/trace.json")
        assert "| 1 | fetch | ShellNode | 200ms | ok |" in md
        assert "| 2 | process | LLMNode | 500ms | **FAILED** |" in md


# --- _build_node_file() ---


class TestBuildNodeFile:
    def test_basic_node(self) -> None:
        event = _make_event(node_id="my-node", node_type="ShellNode", duration_ms=42.5)
        md = _build_node_file(event)
        assert "# my-node" in md
        assert "- Type: ShellNode" in md
        assert "- Time: 42ms" in md
        assert "- Status: success" in md

    def test_cached_node_shows_cached_status(self) -> None:
        event = _make_event(node_id="cached-node", cached=True, duration_ms=0)
        md = _build_node_file(event)
        assert "- Status: success [cached]" in md
        assert "- Time: 0ms" in md

    def test_failed_node_shows_error(self) -> None:
        event = _make_event(success=False, error="Connection refused")
        md = _build_node_file(event)
        assert "- Status: failed" in md
        assert "- Error: Connection refused" in md

    def test_llm_metadata(self) -> None:
        event = _make_event(
            llm_call={
                "model": "gpt-4",
                "input_tokens": 1000,
                "output_tokens": 200,
                "cost_usd": 0.042,
            }
        )
        md = _build_node_file(event)
        assert "- Model: gpt-4" in md
        assert "- Tokens: 1,000 in / 200 out" in md
        assert "- Cost: $0.0420" in md

    def test_template_resolutions_prompt(self) -> None:
        event = _make_event(
            template_resolutions={
                "prompt": {
                    "template": "Summarize ${data}",
                    "resolved": "Summarize the quarterly report...",
                },
            }
        )
        md = _build_node_file(event)
        assert "## Prompt" in md
        assert "Summarize the quarterly report..." in md

    def test_llm_prompt_fallback(self) -> None:
        """When no template_resolutions for prompt, falls back to llm_prompt."""
        event = _make_event(llm_prompt="Direct prompt text")
        md = _build_node_file(event)
        assert "## Prompt" in md
        assert "Direct prompt text" in md

    def test_shell_command_resolution(self) -> None:
        event = _make_event(
            template_resolutions={
                "command": {
                    "template": "curl ${url}",
                    "resolved": "curl https://api.example.com",
                },
            }
        )
        md = _build_node_file(event)
        assert "## Command" in md
        assert "curl https://api.example.com" in md

    def test_llm_response(self) -> None:
        event = _make_event(llm_response="Here is the summary...")
        md = _build_node_file(event)
        assert "## Response" in md
        assert "Here is the summary..." in md

    def test_shell_stdout_stderr(self) -> None:
        event = _make_event(node_output={"stdout": "output line", "stderr": "warning line"})
        md = _build_node_file(event)
        assert "## stdout" in md
        assert "output line" in md
        assert "## stderr" in md
        assert "warning line" in md

    def test_empty_stderr_omitted(self) -> None:
        """Empty stderr should not produce a section."""
        event = _make_event(node_output={"stdout": "output line", "stderr": ""})
        md = _build_node_file(event)
        assert "## stdout" in md
        assert "output line" in md
        assert "## stderr" not in md

    def test_empty_stdout_omitted(self) -> None:
        """Empty stdout should not produce a section."""
        event = _make_event(node_output={"stdout": "", "stderr": "error msg"})
        md = _build_node_file(event)
        assert "## stdout" not in md
        assert "## stderr" in md
        assert "error msg" in md

    def test_structured_result(self) -> None:
        event = _make_event(node_output={"result": {"key": "value", "count": 3}})
        md = _build_node_file(event)
        assert "## Result" in md
        assert '"key": "value"' in md

    def test_llm_response_takes_priority_over_node_output(self) -> None:
        """When llm_response exists, node_output is not shown (avoids duplication)."""
        event = _make_event(
            llm_response="LLM said this",
            node_output={"response": "LLM said this", "other": "data"},
        )
        md = _build_node_file(event)
        assert "## Response" in md
        assert "LLM said this" in md
        # node_output's stdout/stderr/result not shown because llm_response path was taken
        assert "## Output" not in md


# --- _build_node_summary() ---


class TestBuildNodeSummary:
    def test_batch_summary(self) -> None:
        event = _make_event(
            node_id="batch-process",
            batch_items=[
                {"index": 0, "success": True, "duration_ms": 50},
                {"index": 1, "success": False, "duration_ms": 30},
                {"index": 2, "success": True, "duration_ms": 40},
            ],
        )
        md = _build_node_summary(event)
        assert "# batch-process" in md
        assert "- Items: 3 (2/3 succeeded)" in md
        assert "| 0 | 50ms | ok |" in md
        assert "| 1 | 30ms | **FAILED** |" in md

    def test_sub_workflow_summary_has_pipeline_table(self) -> None:
        """Sub-workflow node summary should include a pipeline table of child nodes."""
        event = _make_event(
            node_id="process-title",
            node_type="WorkflowExecutor",
            sub_workflow_events=[
                _make_event(node_id="step-1", node_type="ShellNode", duration_ms=10),
                _make_event(node_id="step-2", node_type="LLMNode", duration_ms=500, success=False),
            ],
        )
        md = _build_node_summary(event)
        assert "## Pipeline" in md
        assert "| 1 | step-1 | ShellNode | 10ms | ok |" in md
        assert "| 2 | step-2 | LLMNode | 500ms | **FAILED** |" in md


# --- _build_batch_item_file() ---


class TestBuildBatchItemFile:
    def test_basic_item(self) -> None:
        parent = _make_event(node_id="summarize")
        item = {"index": 2, "item": "doc-c", "success": True, "duration_ms": 100}
        md = _build_batch_item_file(item, parent)
        assert "# summarize — Item 2" in md
        assert "- Status: success" in md

    def test_item_with_llm_data(self) -> None:
        parent = _make_event(node_id="analyze")
        item = {
            "index": 0,
            "item": "input",
            "success": True,
            "duration_ms": 500,
            "llm_call": {"model": "gemini-3-flash", "cost_usd": 0.005},
            "llm_prompt": "Analyze this",
            "llm_response": "The analysis shows...",
        }
        md = _build_batch_item_file(item, parent)
        assert "- Model: gemini-3-flash" in md
        assert "## Prompt" in md
        assert "Analyze this" in md
        assert "## Response" in md
        assert "The analysis shows..." in md

    def test_item_with_template_resolutions(self) -> None:
        parent = _make_event(node_id="process")
        item = {
            "index": 0,
            "item": "x",
            "success": True,
            "duration_ms": 50,
            "template_resolutions": {
                "prompt": {"template": "Process ${item}", "resolved": "Process x"},
            },
        }
        md = _build_batch_item_file(item, parent)
        assert "## Prompt" in md
        assert "Process x" in md

    def test_item_with_node_output_no_llm(self) -> None:
        parent = _make_event(node_id="transform")
        item = {
            "index": 0,
            "item": "data",
            "success": True,
            "duration_ms": 10,
            "node_output": {"result": "transformed-data"},
        }
        md = _build_batch_item_file(item, parent)
        assert "## Result" in md
        assert "transformed-data" in md

    def test_item_with_shell_output(self) -> None:
        """Shell batch items should show structured stdout/stderr, not raw JSON."""
        parent = _make_event(node_id="greet")
        item = {
            "index": 0,
            "item": {"name": "Alice"},
            "success": True,
            "duration_ms": 5,
            "template_resolutions": {
                "command": {"template": 'echo "Hello, ${user.name}"', "resolved": 'echo "Hello, Alice"'},
            },
            "node_output": {
                "stdout": "Hello, Alice",
                "stderr": "",
                "exit_code": 0,
                "command": 'echo "Hello, Alice"',
            },
        }
        md = _build_batch_item_file(item, parent)
        assert "## Command" in md
        assert 'echo "Hello, Alice"' in md
        assert "## stdout" in md
        assert "Hello, Alice" in md
        # Empty stderr should be omitted
        assert "## stderr" not in md
        # Should NOT show raw JSON dump
        assert "exit_code" not in md

    def test_failed_item(self) -> None:
        parent = _make_event(node_id="fetch")
        item = {
            "index": 1,
            "item": "bad-url",
            "success": False,
            "duration_ms": 200,
            "error": "Connection timeout",
        }
        md = _build_batch_item_file(item, parent)
        assert "- Status: failed" in md
        assert "- Error: Connection timeout" in md


# --- _build_batch_item_summary() ---


class TestBuildBatchItemSummary:
    def test_basic(self) -> None:
        item = {"index": 3, "success": True, "duration_ms": 1500}
        md = _build_batch_item_summary(item)
        assert "# Item 3" in md
        assert "- Time: 1500ms" in md
        assert "- Status: success" in md

    def test_with_pipeline_table(self) -> None:
        """Batch item with sub-workflow events should show a pipeline table."""
        item = {
            "index": 0,
            "success": True,
            "duration_ms": 2000,
            "events": [
                _make_event(node_id="write-lyrics", node_type="LLMNode", duration_ms=800),
                _make_event(node_id="review", node_type="LLMNode", duration_ms=600),
            ],
        }
        md = _build_batch_item_summary(item)
        assert "## Pipeline" in md
        assert "| 1 | write-lyrics | LLMNode | 800ms | ok |" in md
        assert "| 2 | review | LLMNode | 600ms | ok |" in md
