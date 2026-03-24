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
    _build_output_lookup,
    _build_summary,
    _collect_errors,
    _compute_event_cost,
    _detect_anomalies,
    _detect_batch_item_anomalies,
    _format_cost,
    _suggest_template_fixes,
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
        assert "| 1 | fetch | ShellNode | 200ms | \u2014 | ok |" in md
        assert "| 2 | process | LLMNode | 500ms | \u2014 | **FAILED** |" in md


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

    def test_code_node_shows_source_and_inputs(self) -> None:
        """Code node report renders the source code and resolved input variables.

        This is the key debugging view for code nodes: see what code ran and
        what data it received. Without this, agents have to re-run the workflow
        with print statements to inspect code node behavior.
        """
        event = _make_event(
            node_id="transform",
            node_type="PythonCodeNode",
            node_params={"code": "result = len(inputs['data'])"},
            template_resolutions={
                "inputs": {
                    "template": {"data": "${fetch.result}"},
                    "resolved": {"data": [1, 2, 3]},
                }
            },
            node_output={"result": 3, "stdout": ""},
        )
        md = _build_node_file(event)
        assert "## Code" in md
        assert "result = len(inputs['data'])" in md
        assert "## Inputs" in md
        assert '"data"' in md
        assert "## Result" in md

    def test_remaining_resolutions_shown_as_catch_all(self) -> None:
        """Template resolutions not matching prompt/command/inputs get a catch-all section."""
        event = _make_event(
            node_id="fetch",
            node_type="HttpNode",
            template_resolutions={
                "url": {"template": "${config.api_url}/users", "resolved": "https://api.example.com/users"},
                "headers": {"template": {"Auth": "${config.token}"}, "resolved": {"Auth": "Bearer xyz"}},
            },
            node_output={"response": {"users": []}},
        )
        md = _build_node_file(event)
        assert "## Resolved Parameters" in md
        assert "api.example.com" in md


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
        assert "| 0 | 50ms | \u2014 | ok |" in md
        assert "| 1 | 30ms | \u2014 | **FAILED** |" in md

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
        assert "| 1 | step-1 | ShellNode | 10ms | \u2014 | ok |" in md
        assert "| 2 | step-2 | LLMNode | 500ms | \u2014 | **FAILED** |" in md


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
        assert "| 1 | write-lyrics | LLMNode | 800ms | \u2014 | ok |" in md
        assert "| 2 | review | LLMNode | 600ms | \u2014 | ok |" in md


# --- _compute_event_cost() ---


class TestComputeEventCost:
    def test_compute_event_cost_no_llm(self) -> None:
        """Event without llm_call returns None."""
        event = _make_event(node_id="shell-step", node_type="ShellNode")
        result = _compute_event_cost(event)
        assert result is None

    def test_compute_event_cost_leaf_llm(self) -> None:
        """Event with direct llm_call returns its cost_usd."""
        event = _make_event(
            node_type="LLMNode",
            llm_call={"model": "gpt-4", "cost_usd": 0.05},
        )
        result = _compute_event_cost(event)
        assert result == pytest.approx(0.05)

    def test_compute_event_cost_batch_items(self) -> None:
        """Batch items with llm_calls sum their costs."""
        event = _make_event(
            node_type="LLMNode",
            batch_items=[
                {"llm_call": {"cost_usd": 0.01}},
                {"llm_call": {"cost_usd": 0.02}},
            ],
        )
        result = _compute_event_cost(event)
        assert result == pytest.approx(0.03)

    def test_compute_event_cost_sub_workflow(self) -> None:
        """Sub-workflow events with llm_calls sum recursively."""
        event = _make_event(
            node_type="WorkflowExecutor",
            sub_workflow_events=[
                _make_event(
                    node_id="inner-llm",
                    node_type="LLMNode",
                    llm_call={"model": "claude", "cost_usd": 0.04},
                ),
            ],
        )
        result = _compute_event_cost(event)
        assert result == pytest.approx(0.04)

    def test_compute_event_cost_nested(self) -> None:
        """Batch items containing sub-workflow events with llm_calls sum correctly."""
        event = _make_event(
            node_type="WorkflowExecutor",
            batch_items=[
                {
                    "index": 0,
                    "success": True,
                    "duration_ms": 100,
                    "events": [
                        _make_event(
                            node_id="inner-llm-1",
                            node_type="LLMNode",
                            llm_call={"model": "gpt-4", "cost_usd": 0.01},
                        ),
                        _make_event(
                            node_id="inner-llm-2",
                            node_type="LLMNode",
                            llm_call={"model": "gpt-4", "cost_usd": 0.02},
                        ),
                    ],
                },
                {
                    "index": 1,
                    "success": True,
                    "duration_ms": 100,
                    "events": [
                        _make_event(
                            node_id="inner-llm-3",
                            node_type="LLMNode",
                            llm_call={"model": "gpt-4", "cost_usd": 0.03},
                        ),
                    ],
                },
            ],
        )
        result = _compute_event_cost(event)
        # 0.01 + 0.02 + 0.03 = 0.06
        assert result == pytest.approx(0.06)


# --- _format_cost() ---
# (Tested indirectly through table tests, but _build_output_lookup also needs direct use)


# --- Cost in tables ---


class TestCostInTables:
    def test_summary_pipeline_table_has_cost_column(self) -> None:
        """Pipeline table in summary includes Cost column with formatted values."""
        trace = _make_trace(
            nodes=[
                _make_event(
                    node_id="ask-llm",
                    node_type="LLMNode",
                    duration_ms=300,
                    llm_call={"model": "gpt-4", "cost_usd": 0.05},
                ),
            ]
        )
        md = _build_summary(trace, source_path="test")
        assert "| Cost |" in md
        assert "$0.0500" in md

    def test_node_summary_batch_table_has_cost_column(self) -> None:
        """Batch items table includes Cost column."""
        event = _make_event(
            node_id="batch-llm",
            node_type="LLMNode",
            batch_items=[
                {
                    "index": 0,
                    "success": True,
                    "duration_ms": 50,
                    "llm_call": {"model": "gpt-4", "cost_usd": 0.01},
                },
                {
                    "index": 1,
                    "success": True,
                    "duration_ms": 60,
                    "llm_call": {"model": "gpt-4", "cost_usd": 0.02},
                },
            ],
        )
        md = _build_node_summary(event)
        assert "| Cost |" in md
        assert "$0.0100" in md

    def test_summary_header_shows_total_cost(self) -> None:
        """Summary header includes total cost from llm_summary."""
        trace = _make_trace(
            llm_summary={
                "total_calls": 3,
                "total_tokens": 5000,
                "total_cost_usd": 0.0847,
                "models_used": ["gpt-4"],
            }
        )
        md = _build_summary(trace, source_path="test")
        assert "Total cost: $0.0847" in md


# --- Error summary ---


class TestErrorSummary:
    def test_summary_shows_error_section(self) -> None:
        """Trace with failed nodes produces an Errors section."""
        trace = _make_trace(
            nodes=[
                _make_event(
                    node_id="fetch",
                    node_type="HttpNode",
                    success=False,
                    error="Connection refused",
                ),
            ]
        )
        md = _build_summary(trace, source_path="test")
        assert "## Errors" in md
        assert "Connection refused" in md

    def test_summary_no_error_section_on_success(self) -> None:
        """Trace with all successful nodes has no Errors section."""
        trace = _make_trace(
            nodes=[
                _make_event(
                    node_id="step-1",
                    success=True,
                    node_output={"result": "ok"},
                ),
                _make_event(
                    node_id="step-2",
                    success=True,
                    node_output={"result": "done"},
                ),
            ]
        )
        md = _build_summary(trace, source_path="test")
        assert "## Errors" not in md

    def test_summary_truncates_long_error(self) -> None:
        """Error messages longer than 200 chars are truncated in summary."""
        long_error = "x" * 300
        trace = _make_trace(
            nodes=[
                _make_event(node_id="fail", success=False, error=long_error),
            ]
        )
        md = _build_summary(trace, source_path="test")
        assert "## Errors" in md
        assert "..." in md
        # Full 300-char error should NOT appear — it's truncated to 200 + "..."
        assert long_error not in md


# --- _detect_anomalies() ---


class TestDetectAnomalies:
    def test_detect_anomalies_empty_llm_response(self) -> None:
        """LLM node with empty string response triggers warning."""
        event = _make_event(
            node_id="summarize",
            node_type="LLMNode",
            success=True,
            node_output={"response": ""},
        )
        warnings = _detect_anomalies([event])
        assert any("LLM response is empty" in w for w in warnings)

    def test_detect_anomalies_empty_stdout(self) -> None:
        """Shell node with empty stdout and exit_code 0 triggers warning."""
        event = _make_event(
            node_id="list-files",
            node_type="ShellNode",
            success=True,
            node_output={"stdout": "", "exit_code": 0},
        )
        warnings = _detect_anomalies([event])
        assert any("stdout is empty" in w for w in warnings)

    def test_detect_anomalies_none_result(self) -> None:
        """Python node with None result triggers warning."""
        event = _make_event(
            node_id="compute",
            node_type="PythonNode",
            success=True,
            node_output={"result": None},
        )
        warnings = _detect_anomalies([event])
        assert any("result is None" in w for w in warnings)

    def test_detect_anomalies_empty_list(self) -> None:
        """Any node with an empty list in a common output key triggers warning."""
        event = _make_event(
            node_id="fetch-items",
            node_type="HttpNode",
            success=True,
            node_output={"response": []},
        )
        warnings = _detect_anomalies([event])
        assert any("empty list" in w for w in warnings)

    def test_detect_anomalies_skips_failed_nodes(self) -> None:
        """Failed nodes should not generate anomaly warnings (shown in Errors)."""
        event = _make_event(
            node_id="broken",
            node_type="LLMNode",
            success=False,
            node_output={"response": ""},
        )
        warnings = _detect_anomalies([event])
        assert len(warnings) == 0


# --- _suggest_template_fixes() ---


class TestSuggestTemplateFixes:
    def test_suggest_template_fix_wrong_field(self) -> None:
        """Suggests correct field when template references a non-existent key."""
        upstream_event = _make_event(
            node_id="fetch",
            node_type="HttpNode",
            success=True,
            node_output={"result": {"issues": [{"id": 1}], "total_count": 5}},
        )
        failed_event = _make_event(
            node_id="process",
            node_type="LLMNode",
            success=False,
            error="Unresolved variables: ${fetch.result.messages}",
        )
        suggestions = _suggest_template_fixes(failed_event, [upstream_event, failed_event])
        assert len(suggestions) >= 1
        # Should mention the failed key
        assert any("messages" in s for s in suggestions)
        # Should list available keys
        assert any("issues" in s for s in suggestions)
        assert any("total_count" in s for s in suggestions)

    def test_suggest_template_fix_no_upstream(self) -> None:
        """No suggestions when upstream node is not found."""
        failed_event = _make_event(
            node_id="process",
            success=False,
            error="Unresolved variables: ${unknown.data}",
        )
        suggestions = _suggest_template_fixes(failed_event, [failed_event])
        assert suggestions == []

    def test_suggest_template_fix_non_template_error(self) -> None:
        """Non-template errors produce no suggestions."""
        failed_event = _make_event(
            node_id="fetch",
            success=False,
            error="Connection timeout",
        )
        suggestions = _suggest_template_fixes(failed_event, [failed_event])
        assert suggestions == []

    def test_suggest_template_fix_from_template_resolutions(self) -> None:
        """Detects unresolved variables from template_resolutions (template == resolved)."""
        upstream_event = _make_event(
            node_id="api",
            node_type="HttpNode",
            success=True,
            node_output={"result": {"data": [1, 2, 3]}},
        )
        failed_event = _make_event(
            node_id="transform",
            node_type="LLMNode",
            success=False,
            error="Unresolved variables: ${api.result.messages}",
            template_resolutions={
                "prompt": {
                    "template": "Use ${api.result.messages}",
                    "resolved": "Use ${api.result.messages}",
                },
            },
        )
        suggestions = _suggest_template_fixes(failed_event, [upstream_event, failed_event])
        assert len(suggestions) >= 1
        assert any("messages" in s for s in suggestions)
        assert any("data" in s for s in suggestions)


# --- Batch item warnings in _build_node_summary() ---


class TestBatchItemWarnings:
    def test_node_summary_shows_item_warnings(self) -> None:
        """Batch items with empty output trigger warnings in node summary."""
        event = _make_event(
            node_id="batch-process",
            node_type="ShellNode",
            batch_items=[
                {
                    "index": 0,
                    "success": True,
                    "duration_ms": 50,
                    "node_output": {},
                },
                {
                    "index": 1,
                    "success": True,
                    "duration_ms": 60,
                    "node_output": {"result": "good data"},
                },
            ],
        )
        md = _build_node_summary(event)
        assert "## Warnings" in md
        assert "Item 0" in md

    def test_node_summary_no_warnings_when_clean(self) -> None:
        """Batch items with non-empty output produce no warnings."""
        event = _make_event(
            node_id="batch-process",
            node_type="ShellNode",
            batch_items=[
                {
                    "index": 0,
                    "success": True,
                    "duration_ms": 50,
                    "node_output": {"result": "data-a"},
                },
                {
                    "index": 1,
                    "success": True,
                    "duration_ms": 60,
                    "node_output": {"result": "data-b"},
                },
            ],
        )
        md = _build_node_summary(event)
        assert "## Warnings" not in md

    def test_llm_batch_empty_response_detected(self) -> None:
        """LLM parent type with item having empty response triggers warning."""
        batch_items = [
            {"index": 0, "success": True, "duration_ms": 50, "node_output": {"response": ""}},
            {"index": 1, "success": True, "duration_ms": 60, "node_output": {"response": "good"}},
        ]
        parent = _make_event(node_id="summarize", node_type="LLMNode")
        warnings = _detect_batch_item_anomalies(batch_items, parent)
        assert len(warnings) == 1
        assert "Item 0" in warnings[0]
        assert "LLM response is empty" in warnings[0]

    def test_skips_failed_batch_items(self) -> None:
        """Failed batch items should not generate anomaly warnings."""
        batch_items = [
            {"index": 0, "success": False, "duration_ms": 50, "node_output": {"response": ""}},
            {"index": 1, "success": True, "duration_ms": 60, "node_output": {"response": "good"}},
        ]
        parent = _make_event(node_id="summarize", node_type="LLMNode")
        warnings = _detect_batch_item_anomalies(batch_items, parent)
        assert len(warnings) == 0


class TestTopLevelBatchWarnings:
    """Tests for batch item anomalies surfacing in the top-level summary."""

    def test_top_level_summary_surfaces_batch_item_warnings(self) -> None:
        """A batch event with items producing empty output shows warnings in _build_summary."""
        batch_event = _make_event(
            node_id="batch-llm",
            node_type="LLMNode",
            success=True,
            batch_items=[
                {"index": 0, "success": True, "duration_ms": 50, "node_output": {"response": ""}},
                {"index": 1, "success": True, "duration_ms": 60, "node_output": {"response": "good data"}},
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        summary = _build_summary(trace)

        assert "## Warnings" in summary
        assert "batch-llm" in summary
        assert "LLM response is empty" in summary


# --- _build_output_lookup() and _collect_errors() direct tests ---
# These are tested indirectly through _build_summary and _suggest_template_fixes,
# but we exercise them directly here to ensure _build_output_lookup and _collect_errors
# are imported (and to validate their standalone behavior).


class TestBuildOutputLookup:
    def test_builds_lookup_from_events(self) -> None:
        """Builds node_id -> node_output mapping from events."""
        events = [
            _make_event(
                node_id="fetch",
                node_output={"result": {"data": "hello"}},
            ),
            _make_event(
                node_id="transform",
                node_output={"result": "done"},
            ),
        ]
        lookup = _build_output_lookup(events)
        assert "fetch" in lookup
        assert lookup["fetch"] == {"result": {"data": "hello"}}
        assert "transform" in lookup

    def test_includes_sub_workflow_children(self) -> None:
        """Sub-workflow child events are indexed in the lookup."""
        events = [
            _make_event(
                node_id="parent",
                node_output={"result": "parent-data"},
                sub_workflow_events=[
                    _make_event(
                        node_id="child-step",
                        node_output={"result": "child-data"},
                    ),
                ],
            ),
        ]
        lookup = _build_output_lookup(events)
        assert "parent" in lookup
        assert "child-step" in lookup
        assert lookup["child-step"] == {"result": "child-data"}


class TestCollectErrors:
    def test_collects_failed_events(self) -> None:
        """Returns only events with success=False."""
        events = [
            _make_event(node_id="ok", success=True),
            _make_event(node_id="fail-1", success=False, error="Error 1"),
            _make_event(node_id="fail-2", success=False, error="Error 2"),
        ]
        errors = _collect_errors(events)
        assert len(errors) == 2
        assert errors[0]["node_id"] == "fail-1"
        assert errors[1]["node_id"] == "fail-2"

    def test_returns_empty_on_all_success(self) -> None:
        """Returns empty list when all events succeed."""
        events = [
            _make_event(node_id="a", success=True),
            _make_event(node_id="b", success=True),
        ]
        errors = _collect_errors(events)
        assert errors == []


class TestFormatCost:
    def test_format_cost_none(self) -> None:
        """None cost returns em dash."""
        assert _format_cost(None) == "\u2014"

    def test_format_cost_value(self) -> None:
        """Numeric cost formatted to 4 decimal places with dollar sign."""
        assert _format_cost(0.05) == "$0.0500"
        assert _format_cost(0.0) == "$0.0000"
