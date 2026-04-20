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
    _compute_outlier_threshold,
    _detect_anomalies,
    _detect_batch_item_anomalies,
    _extract_item_label,
    _find_notable_items,
    _format_cost,
    _item_filename,
    _slugify_label,
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
        assert (report_dir / "01-process" / "item-0-a.md").exists()
        assert (report_dir / "01-process" / "item-1-b.md").exists()

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
        item_dir = report_dir / "01-create-songs" / "item-0-song-a"
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
                "total_input_tokens": 3200,
                "total_output_tokens": 9145,
                "models_used": ["gpt-4", "claude"],
            }
        )
        md = _build_summary(trace, source_path="/home/user/.pflow/debug/trace.json")
        assert "- LLM calls: 5" in md
        assert "- Tokens: 3,200 in / 9,145 out" in md
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

    def test_llm_summary_fallback_total_tokens(self) -> None:
        """Old traces without input/output breakdown fall back to total_tokens."""
        trace = _make_trace(
            llm_summary={
                "total_calls": 2,
                "total_tokens": 500,
                "models_used": ["gpt-4"],
            }
        )
        md = _build_summary(trace, source_path="test")
        assert "- Tokens: 500" in md
        assert "in /" not in md

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
    def test_batch_summary_compact(self) -> None:
        """Compact summary: only the failed item in the table, others hidden."""
        event = _make_event(
            node_id="batch-process",
            node_type="ShellNode",
            batch_items=[
                {"index": 0, "success": True, "duration_ms": 50, "node_output": {"stdout": "ok", "exit_code": 0}},
                {"index": 1, "success": False, "duration_ms": 30},
                {"index": 2, "success": True, "duration_ms": 40, "node_output": {"stdout": "ok", "exit_code": 0}},
            ],
        )
        md = _build_node_summary(event)
        assert "# batch-process" in md
        assert "- Items: 3 (2/3 succeeded)" in md
        # Only the failed item appears in the table
        assert "| 1 | 30ms | \u2014 | **FAILED** |" in md
        # Successful items hidden behind count
        assert "| 0 |" not in md
        assert "... and 2 more succeeded" in md

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
        assert "# summarize — doc-c" in md
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

    def test_item_with_llm_tokens(self) -> None:
        """Batch item file shows input/output token breakdown."""
        parent = _make_event(node_id="summarize")
        item = {
            "index": 0,
            "item": "doc",
            "success": True,
            "duration_ms": 300,
            "llm_call": {"model": "gpt-4", "input_tokens": 800, "output_tokens": 150, "cost_usd": 0.01},
        }
        md = _build_batch_item_file(item, parent)
        assert "- Tokens: 800 in / 150 out" in md
        assert "- Cost: $0.0100" in md

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

    def test_compute_event_cost_on_batch_item_directly(self) -> None:
        """Cost computed on a batch item dict (not parent event).

        This is the path used by _build_node_summary's items table.
        Batch items store child events under "events", not "sub_workflow_events".
        """
        batch_item = {
            "index": 0,
            "success": True,
            "duration_ms": 5000,
            "events": [
                _make_event(
                    node_id="write-lyrics",
                    node_type="LLMNode",
                    llm_call={"model": "gpt-4", "cost_usd": 0.15},
                ),
                _make_event(
                    node_id="review",
                    node_type="LLMNode",
                    llm_call={"model": "gpt-4", "cost_usd": 0.24},
                ),
            ],
        }
        result = _compute_event_cost(batch_item)
        assert result == pytest.approx(0.39)


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

    def test_reads_failed_node_ids_when_present(self) -> None:
        """When failed_node_ids is supplied, use it as the authoritative set.

        Ignores per-event success flag for inclusion decision — the list drives it.
        """
        events = [
            _make_event(node_id="x", success=True),  # flag says ok — not in list → excluded
            _make_event(node_id="y", success=False, error="Y-err"),  # in list → included
        ]
        errors = _collect_errors(events, failed_node_ids=["y"])
        assert len(errors) == 1
        assert errors[0]["node_id"] == "y"

    def test_loop_recovery_omits_recovered_node(self) -> None:
        """Node failed on visit 1, succeeded on visit 2 → not in failed_node_ids → omitted.

        Motivating case for GH #240.
        """
        events = [
            _make_event(node_id="maybe-fail", success=False, error="visit 1"),
            _make_event(node_id="maybe-fail", success=True),
        ]
        errors = _collect_errors(events, failed_node_ids=[])
        assert errors == []

    def test_returns_latest_event_per_failed_node(self) -> None:
        """When a node fails on both visits, only the latest event is returned."""
        events = [
            _make_event(node_id="n", success=False, error="visit 1 error"),
            _make_event(node_id="n", success=False, error="visit 2 error"),
        ]
        errors = _collect_errors(events, failed_node_ids=["n"])
        assert len(errors) == 1
        assert errors[0]["error"] == "visit 2 error"

    def test_fallback_per_node_when_list_absent(self) -> None:
        """No failed_node_ids supplied → derive per-node final state from events.

        Back-compat path for traces generated before the #240 fix.
        """
        events = [
            _make_event(node_id="maybe-fail", success=False, error="visit 1"),
            _make_event(node_id="maybe-fail", success=True),  # recovered
        ]
        errors = _collect_errors(events, failed_node_ids=None)
        assert errors == []

    def test_fallback_still_returns_latest_if_node_truly_failed(self) -> None:
        events = [
            _make_event(node_id="n", success=False, error="visit 1 error"),
            _make_event(node_id="n", success=False, error="visit 2 error"),
        ]
        errors = _collect_errors(events, failed_node_ids=None)
        assert len(errors) == 1
        assert errors[0]["error"] == "visit 2 error"


class TestBuildSummaryLoopRecovery:
    """Summary rendering under loop recovery — GH #240 acceptance criteria."""

    def test_loop_recovery_shows_status_success(self) -> None:
        """Trace with visit-1-fail + visit-2-success renders Status: success."""
        events = [
            _make_event(node_id="setup", success=True),
            _make_event(node_id="maybe-fail", success=False, error="exit 9"),
            _make_event(node_id="retry", success=True),
            _make_event(node_id="maybe-fail", success=True),
        ]
        trace = _make_trace(
            nodes=events,
            final_status="success",
            nodes_executed=4,
            nodes_failed=0,
            failed_node_ids=[],
        )
        md = _build_summary(trace, source_path="test")

        assert "- Status: success" in md
        # Errors section must NOT be present for recovered node
        assert "## Errors" not in md

    def test_loop_recovery_pipeline_table_shows_both_visits(self) -> None:
        """Pipeline table is per-visit — both visits of maybe-fail must appear."""
        events = [
            _make_event(node_id="maybe-fail", success=False, error="exit 9"),
            _make_event(node_id="maybe-fail", success=True),
        ]
        trace = _make_trace(
            nodes=events,
            final_status="success",
            nodes_executed=2,
            nodes_failed=0,
            failed_node_ids=[],
        )
        md = _build_summary(trace, source_path="test")

        # Table has two rows for maybe-fail — one FAILED, one ok
        assert md.count("maybe-fail") >= 2
        assert "**FAILED**" in md
        assert " ok " in md  # the succeeded visit's status column

    def test_single_failure_still_renders_errors_section(self) -> None:
        """Non-loop single failure — Errors section must still render."""
        events = [
            _make_event(node_id="bad", node_type="ShellNode", success=False, error="exit 1"),
        ]
        trace = _make_trace(
            nodes=events,
            final_status="failed",
            nodes_executed=1,
            nodes_failed=1,
            failed_node_ids=["bad"],
        )
        md = _build_summary(trace, source_path="test")

        assert "- Status: failed" in md
        assert "## Errors" in md
        assert "**bad**" in md


class TestFormatCost:
    def test_format_cost_none(self) -> None:
        """None cost returns em dash."""
        assert _format_cost(None) == "\u2014"

    def test_format_cost_value(self) -> None:
        """Numeric cost formatted to 4 decimal places with dollar sign."""
        assert _format_cost(0.05) == "$0.0500"
        assert _format_cost(0.0) == "$0.0000"


# --- _extract_item_label() ---


class TestExtractItemLabel:
    def test_string_item(self) -> None:
        assert _extract_item_label({"item": "emotional-depth"}) == "emotional-depth"

    def test_dict_with_name(self) -> None:
        assert _extract_item_label({"item": {"name": "Chorus A", "weight": 3}}) == "Chorus A"

    def test_dict_with_title(self) -> None:
        assert _extract_item_label({"item": {"title": "My Song", "id": 42}}) == "My Song"

    def test_dict_with_label(self) -> None:
        assert _extract_item_label({"item": {"label": "verse-1", "data": "..."}}) == "verse-1"

    def test_dict_priority_name_over_title(self) -> None:
        """name takes priority over title."""
        assert _extract_item_label({"item": {"name": "A", "title": "B"}}) == "A"

    def test_dict_fallback_first_short_string(self) -> None:
        """Falls back to first short string value when no priority key."""
        assert _extract_item_label({"item": {"concept": "Space Travel", "id": 42}}) == "Space Travel"

    def test_dict_skips_urls(self) -> None:
        """URLs are skipped in fallback search."""
        result = _extract_item_label({"item": {"url": "https://example.com", "id": 42}})
        assert result is None

    def test_dict_skips_paths(self) -> None:
        """Absolute paths are skipped in fallback search."""
        result = _extract_item_label({"item": {"path": "/usr/local/bin", "id": 42}})
        assert result is None

    def test_dict_skips_long_strings(self) -> None:
        """Strings >= 80 chars are skipped in fallback search."""
        result = _extract_item_label({"item": {"description": "x" * 80, "id": 42}})
        assert result is None

    def test_no_item_key(self) -> None:
        assert _extract_item_label({"index": 0, "success": True}) is None

    def test_int_item(self) -> None:
        assert _extract_item_label({"item": 42}) is None

    def test_list_item(self) -> None:
        assert _extract_item_label({"item": [1, 2, 3]}) is None

    def test_empty_string(self) -> None:
        assert _extract_item_label({"item": "   "}) is None


# --- _slugify_label() ---


class TestSlugifyLabel:
    def test_basic(self) -> None:
        assert _slugify_label("Emotional Depth") == "emotional-depth"

    def test_special_chars(self) -> None:
        assert _slugify_label("Song #1 (remix)") == "song-1-remix"

    def test_truncation(self) -> None:
        slug = _slugify_label("a" * 50, max_len=40)
        assert len(slug) <= 40

    def test_truncation_at_word_boundary(self) -> None:
        slug = _slugify_label("the-quick-brown-fox-jumps-over-the-lazy-dog-again", max_len=40)
        assert len(slug) <= 40
        assert not slug.endswith("-")

    def test_empty_after_slug(self) -> None:
        assert _slugify_label("!!!") == "unnamed"

    def test_preserves_hyphens_and_numbers(self) -> None:
        assert _slugify_label("item-42-v2") == "item-42-v2"


# --- _item_filename() ---


class TestItemFilename:
    def test_with_string_label(self) -> None:
        assert _item_filename({"index": 0, "item": "chorus"}) == "item-0-chorus.md"

    def test_with_dict_label(self) -> None:
        assert _item_filename({"index": 3, "item": {"name": "My Song!"}}) == "item-3-my-song.md"

    def test_no_label(self) -> None:
        assert _item_filename({"index": 5}) == "item-5.md"

    def test_directory_suffix(self) -> None:
        assert _item_filename({"index": 0, "item": "verse"}, suffix="") == "item-0-verse"


# --- _compute_outlier_threshold() ---


class TestComputeOutlierThreshold:
    def test_too_few_values(self) -> None:
        """Returns None with fewer than 4 values (IQR meaningless)."""
        assert _compute_outlier_threshold([1, 2, 3]) is None

    def test_uniform_distribution(self) -> None:
        """Uniform values have IQR=0, threshold = Q3."""
        threshold = _compute_outlier_threshold([100, 100, 100, 100])
        assert threshold is not None
        assert threshold == 100.0

    def test_detects_outlier(self) -> None:
        """A clearly extreme value exceeds the threshold."""
        # [50, 60, 70, 80] → Q1=55, Q3=75, IQR=20 → threshold=75+30=105
        threshold = _compute_outlier_threshold([50, 60, 70, 80])
        assert threshold is not None
        assert threshold > 50  # normal values below
        assert threshold < 200  # extreme value above

    def test_real_world_batch_timing(self) -> None:
        """Simulates real batch: most items ~100ms, one slow at 800ms."""
        durations = [95, 100, 105, 110, 98, 102, 100, 800]
        threshold = _compute_outlier_threshold(durations)
        assert threshold is not None
        assert threshold < 800  # 800ms should be above the threshold
        assert threshold > 110  # normal values should be below


# --- _find_notable_items() ---


class TestFindNotableItems:
    def test_failed_items_always_notable(self) -> None:
        items = [
            {"index": 0, "success": True, "duration_ms": 50, "node_output": {"stdout": "ok", "exit_code": 0}},
            {"index": 1, "success": False, "duration_ms": 30},
        ]
        notable = _find_notable_items(items, _make_event(node_type="ShellNode"))
        assert len(notable) == 1
        assert notable[0]["index"] == 1

    def test_anomaly_items_notable(self) -> None:
        """Items with empty output are notable."""
        items = [
            {"index": 0, "success": True, "duration_ms": 50, "node_output": {}},
            {"index": 1, "success": True, "duration_ms": 60, "node_output": {"stdout": "data", "exit_code": 0}},
        ]
        notable = _find_notable_items(items, _make_event(node_type="ShellNode"))
        assert len(notable) == 1
        assert notable[0]["index"] == 0

    def test_all_ok_returns_empty(self) -> None:
        """All successful items with normal output → nothing notable."""
        items = [
            {"index": i, "success": True, "duration_ms": 100, "node_output": {"stdout": "ok", "exit_code": 0}}
            for i in range(5)
        ]
        notable = _find_notable_items(items, _make_event(node_type="ShellNode"))
        assert len(notable) == 0

    def test_duration_outlier_notable(self) -> None:
        """An item with extreme duration is notable via IQR detection."""
        items = [
            {"index": i, "success": True, "duration_ms": 100, "node_output": {"stdout": "ok", "exit_code": 0}}
            for i in range(7)
        ]
        # Add one slow item
        items.append({
            "index": 7,
            "success": True,
            "duration_ms": 5000,
            "node_output": {"stdout": "ok", "exit_code": 0},
        })
        notable = _find_notable_items(items, _make_event(node_type="ShellNode"))
        assert len(notable) == 1
        assert notable[0]["index"] == 7

    def test_cost_outlier_notable(self) -> None:
        """An item with extreme cost is notable via IQR detection."""
        items = [
            {
                "index": i,
                "success": True,
                "duration_ms": 100,
                "node_output": {"response": "ok"},
                "llm_call": {"model": "gpt-4", "cost_usd": 0.01},
            }
            for i in range(7)
        ]
        # Add one expensive item (10x the rest, well above 4x median)
        items.append({
            "index": 7,
            "success": True,
            "duration_ms": 100,
            "node_output": {"response": "ok"},
            "llm_call": {"model": "gpt-4", "cost_usd": 0.10},
        })
        notable = _find_notable_items(items, _make_event(node_type="LLMNode"))
        assert len(notable) == 1
        assert notable[0]["index"] == 7


# --- Compact batch summary ---


class TestCompactBatchSummary:
    def test_all_ok_no_table_shows_stats(self) -> None:
        """When all items succeed normally, no table but shows median time."""
        event = _make_event(
            node_id="batch",
            node_type="ShellNode",
            batch_items=[
                {"index": i, "success": True, "duration_ms": 100, "node_output": {"stdout": "ok", "exit_code": 0}}
                for i in range(10)
            ],
        )
        md = _build_node_summary(event)
        assert "10/10 succeeded" in md
        assert "## Items" not in md
        assert "Median time: 100ms" in md

    def test_all_ok_shows_total_cost(self) -> None:
        """Compact batch with LLM costs shows total cost in stats."""
        event = _make_event(
            node_id="batch",
            node_type="LLMNode",
            batch_items=[
                {
                    "index": i,
                    "success": True,
                    "duration_ms": 5000,
                    "node_output": {"response": "ok"},
                    "llm_call": {"model": "gpt-4", "cost_usd": 0.01},
                }
                for i in range(10)
            ],
        )
        md = _build_node_summary(event)
        assert "## Items" not in md
        assert "Median time: 5.0s" in md
        assert "Total cost: $0.1000" in md

    def test_one_failure_shows_only_failure(self) -> None:
        """Only the failed item appears in the table."""
        items = [
            {"index": i, "success": True, "duration_ms": 100, "node_output": {"stdout": "ok", "exit_code": 0}}
            for i in range(5)
        ]
        items[2] = {"index": 2, "success": False, "duration_ms": 50, "error": "exit code 1"}
        event = _make_event(node_id="batch", node_type="ShellNode", batch_items=items)
        md = _build_node_summary(event)
        assert "## Items" in md
        assert "**FAILED**" in md
        assert "| 2 |" in md
        assert "... and 4 more succeeded" in md
        # Other items not in table
        assert "| 0 |" not in md

    def test_labels_in_table(self) -> None:
        """When items have labels, the Label column appears."""
        event = _make_event(
            node_id="score",
            node_type="LLMNode",
            batch_items=[
                {"index": 0, "item": "depth", "success": False, "duration_ms": 50},
                {"index": 1, "item": "clarity", "success": True, "duration_ms": 60, "node_output": {"response": "ok"}},
            ],
        )
        md = _build_node_summary(event)
        assert "| Label |" in md
        assert "depth" in md

    def test_labeled_filenames_integration(self, tmp_path: Path) -> None:
        """generate_report creates labeled filenames for batch items."""
        batch_event = _make_event(
            node_id="analyze",
            batch_items=[
                {"index": 0, "item": {"name": "Alpha"}, "success": True, "duration_ms": 50},
                {"index": 1, "item": {"name": "Beta"}, "success": True, "duration_ms": 60},
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(trace))

        report_dir = generate_report(trace_file, str(tmp_path / "report"))
        assert report_dir is not None
        assert (report_dir / "01-analyze" / "item-0-alpha.md").exists()
        assert (report_dir / "01-analyze" / "item-1-beta.md").exists()


# --- LLM params in node metadata (Issue 4) ---


class TestLLMParamsInMetadata:
    def test_temperature_shown(self) -> None:
        event = _make_event(
            node_type="LLMNode",
            node_params={"temperature": 0.4, "prompt": "Hello"},
            llm_call={"model": "gpt-4", "input_tokens": 10, "output_tokens": 5},
        )
        md = _build_node_file(event)
        assert "- temperature: 0.4" in md

    def test_reasoning_effort_shown(self) -> None:
        event = _make_event(
            node_type="LLMNode",
            node_params={"reasoning_effort": "high"},
            llm_call={"model": "gpt-4", "input_tokens": 10, "output_tokens": 5},
        )
        md = _build_node_file(event)
        assert "- reasoning_effort: high" in md

    def test_system_prompt_truncated(self) -> None:
        event = _make_event(
            node_type="LLMNode",
            node_params={"system": "x" * 100},
            llm_call={"model": "gpt-4", "input_tokens": 10, "output_tokens": 5},
        )
        md = _build_node_file(event)
        assert "- system: " in md
        assert "..." in md
        assert "x" * 100 not in md

    def test_output_schema_shown(self) -> None:
        event = _make_event(
            node_type="LLMNode",
            node_params={"output_schema": {"type": "object"}},
            llm_call={"model": "gpt-4", "input_tokens": 10, "output_tokens": 5},
        )
        md = _build_node_file(event)
        assert "- output: structured (schema)" in md

    def test_no_params_no_extra_lines(self) -> None:
        """Shell node with no LLM params shows nothing extra."""
        event = _make_event(node_type="ShellNode", node_params={"command": "echo hi"})
        md = _build_node_file(event)
        assert "temperature" not in md
        assert "reasoning" not in md


# --- Runtime warnings in summary (Issue 5) ---


class TestRuntimeWarningsInSummary:
    def test_runtime_warnings_rendered(self) -> None:
        trace = _make_trace(
            warnings=[
                {
                    "node_id": "score-choruses",
                    "type": "api_warning",
                    "message": "Batch 'score-choruses': 1 error(s) out of 34 items",
                },
            ]
        )
        md = _build_summary(trace)
        assert "## Runtime Warnings" in md
        assert "score-choruses" in md
        assert "1 error(s) out of 34 items" in md

    def test_no_runtime_warnings_no_section(self) -> None:
        trace = _make_trace()
        md = _build_summary(trace)
        assert "## Runtime Warnings" not in md

    def test_multiple_runtime_warnings(self) -> None:
        trace = _make_trace(
            warnings=[
                {"node_id": "node-a", "type": "api_warning", "message": "API error: not found"},
                {"node_id": "node-b", "type": "api_warning", "message": "Batch 'node-b': 2 error(s)"},
            ]
        )
        md = _build_summary(trace)
        assert "node-a" in md
        assert "node-b" in md


# --- Item counts in pipeline status (Issue 6) ---


class TestItemCountsInStatus:
    def test_batch_event_shows_item_counts(self) -> None:
        """Pipeline table shows item counts for batch nodes."""
        batch_event = _make_event(
            node_id="process",
            batch_items=[
                {"index": 0, "success": True, "duration_ms": 50},
                {"index": 1, "success": True, "duration_ms": 60},
                {"index": 2, "success": False, "duration_ms": 30},
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        md = _build_summary(trace)
        assert "ok (2/3)" in md

    def test_all_succeeded_batch(self) -> None:
        batch_event = _make_event(
            node_id="greet",
            batch_items=[
                {"index": 0, "success": True, "duration_ms": 50},
                {"index": 1, "success": True, "duration_ms": 60},
            ],
        )
        trace = _make_trace(nodes=[batch_event])
        md = _build_summary(trace)
        assert "ok (2/2)" in md

    def test_non_batch_no_counts(self) -> None:
        """Non-batch events just show ok/FAILED without counts."""
        event = _make_event(node_id="fetch", node_type="ShellNode")
        trace = _make_trace(nodes=[event])
        md = _build_summary(trace)
        assert "| ok |" in md
        assert "(" not in md.split("ok")[1].split("|")[0]  # no parenthesized count

    def test_sub_workflow_pipeline_table_has_counts(self) -> None:
        """_format_pipeline_table also uses item counts."""
        from pflow.core.trace_report import _format_pipeline_table

        events = [
            _make_event(
                node_id="batch-step",
                batch_items=[
                    {"index": 0, "success": True, "duration_ms": 50},
                    {"index": 1, "success": False, "duration_ms": 60},
                ],
            ),
        ]
        lines: list[str] = []
        _format_pipeline_table(events, lines)
        table = "\n".join(lines)
        assert "ok (1/2)" in table
