"""Comprehensive unit tests for WorkflowTraceCollector (trace format 2.0.0)."""

import json
import uuid
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.runtime.workflow_trace import WorkflowTraceCollector, final_events_by_node


class TestWorkflowTraceCollector:
    """Test suite for WorkflowTraceCollector."""

    @pytest.fixture
    def collector(self):
        """Create a WorkflowTraceCollector instance for testing."""
        return WorkflowTraceCollector("test-workflow")

    @pytest.fixture
    def temp_home(self, tmp_path):
        """Create a temporary home directory for testing."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        return home_dir

    def test_initialization(self, collector):
        """Test that collector initializes with correct defaults."""
        assert collector.workflow_name == "test-workflow"
        assert isinstance(collector.execution_id, str)
        # Verify it's a valid UUID
        uuid.UUID(collector.execution_id)
        assert isinstance(collector.start_time, datetime)
        assert collector.events == []

    def test_record_node_execution_success(self, collector):
        """Test recording a successful node execution."""
        collector.record_node_execution(
            node_id="node-1",
            node_type="TestNode",
            duration_ms=123.456,
            success=True,
            node_output={"output": "result"},
        )

        assert len(collector.events) == 1
        event = collector.events[0]

        # Verify all required fields
        assert event["node_id"] == "node-1"
        assert event["node_type"] == "TestNode"
        assert event["duration_ms"] == 123.46  # Rounded to 2 decimal places
        assert event["success"] is True
        assert "timestamp" in event
        assert "error" not in event

        # Verify node_output is stored (no shared_before/shared_after)
        assert event["node_output"] == {"output": "result"}
        assert "shared_before" not in event
        assert "shared_after" not in event

    def test_record_node_execution_failure(self, collector):
        """Test recording a failed node execution."""
        collector.record_node_execution(
            node_id="node-2",
            node_type="FailingNode",
            duration_ms=50.0,
            success=False,
            error="Division by zero",
        )

        event = collector.events[0]
        assert event["success"] is False
        assert event["error"] == "Division by zero"

    def test_mutation_calculation(self, collector):
        """Test that mutations are stored when provided directly.

        In format 2.0.0, mutations are computed by InstrumentedNodeWrapper
        and passed to record_node_execution, not calculated by the collector.
        """
        mutations = {
            "added": ["added"],
            "removed": ["remove"],
            "modified": ["modify"],
        }

        collector.record_node_execution(
            node_id="node-3",
            node_type="MutationNode",
            duration_ms=10.0,
            success=True,
            mutations=mutations,
        )

        recorded_mutations = collector.events[0]["mutations"]
        assert recorded_mutations["added"] == ["added"]
        assert recorded_mutations["removed"] == ["remove"]
        assert recorded_mutations["modified"] == ["modify"]

    def test_sanitize_for_json_no_truncation(self, collector):
        """Test that large strings are NOT truncated in format 2.0.0.

        Unlike format 1.x, there is no string length truncation.
        Sanitization only filters internal keys and replaces binary data.
        """
        large_string = "x" * 11000  # String longer than 10000 chars

        collector.record_node_execution(
            node_id="node-4",
            node_type="LargeDataNode",
            duration_ms=5.0,
            success=True,
            node_output={"large_data": large_string},
        )

        # In 2.0.0, no truncation — the full string is preserved
        output_value = collector.events[0]["node_output"]["large_data"]
        assert output_value == large_string
        assert len(output_value) == 11000

    def test_sanitize_for_json_binary_data(self, collector):
        """Test that binary data is replaced with a placeholder."""
        collector.record_node_execution(
            node_id="node-5",
            node_type="BinaryNode",
            duration_ms=5.0,
            success=True,
            node_output={"binary": b"some binary content"},
        )

        filtered_value = collector.events[0]["node_output"]["binary"]
        assert filtered_value == "<binary data: 19 bytes>"

    def test_sanitize_for_json_system_keys(self, collector):
        """Test that __dunder__ keys are filtered except __metrics__."""
        collector.record_node_execution(
            node_id="node-6",
            node_type="SystemKeyNode",
            duration_ms=5.0,
            success=True,
            node_output={
                "__private__": "should_be_filtered",
                "__llm_calls__": ["call1", "call2"],
                "__metrics__": {"key": "value"},
                "normal_key": "keep_this",
            },
        )

        filtered_output = collector.events[0]["node_output"]
        assert "__private__" not in filtered_output
        assert "__llm_calls__" not in filtered_output  # No longer in allowlist
        assert "__metrics__" in filtered_output
        assert filtered_output["normal_key"] == "keep_this"

    def test_sanitize_for_json_internal_keys(self, collector):
        """Test that internal trace/debug keys are filtered."""
        collector.record_node_execution(
            node_id="node-7",
            node_type="InternalKeyNode",
            duration_ms=5.0,
            success=True,
            node_output={
                "__trace_collector__": "internal",
                "_debug_context": "internal",
                "_batch_trace": "internal",
                "user_data": "keep_this",
            },
        )

        filtered_output = collector.events[0]["node_output"]
        assert "__trace_collector__" not in filtered_output
        assert "_debug_context" not in filtered_output
        assert "_batch_trace" not in filtered_output
        assert filtered_output["user_data"] == "keep_this"

    def test_llm_call_capture(self, collector):
        """Test that LLM usage data is captured from node_output."""
        collector.record_node_execution(
            node_id="node-8",
            node_type="LLMNode",
            duration_ms=1000.0,
            success=True,
            node_output={
                "llm_usage": {
                    "model": "gpt-4",
                    "total_tokens": 150,
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                }
            },
        )

        event = collector.events[0]
        assert "llm_call" in event
        assert event["llm_call"]["model"] == "gpt-4"
        assert event["llm_call"]["total_tokens"] == 150

    def test_llm_response_capture(self, collector):
        """Test that LLM responses are captured from node_output without truncation.

        In format 2.0.0, there is no response truncation — both short and long
        responses are stored as-is.
        """
        # Test short response
        collector.record_node_execution(
            node_id="node-9a",
            node_type="LLMNode",
            duration_ms=100.0,
            success=True,
            node_output={"response": "Short LLM response"},
        )

        event = collector.events[0]
        assert event["llm_response"] == "Short LLM response"

        # Test long response — NOT truncated in 2.0.0
        long_response = "x" * 21000
        collector.record_node_execution(
            node_id="node-9b",
            node_type="LLMNode",
            duration_ms=100.0,
            success=True,
            node_output={"response": long_response},
        )

        event = collector.events[1]
        assert event["llm_response"] == long_response
        assert len(event["llm_response"]) == 21000
        # No truncated variant should exist
        assert "llm_response_truncated" not in event

    def test_template_resolutions_parameter(self, collector):
        """Test that template_resolutions are stored when provided."""
        template_resolutions = {
            "input_file": "/path/to/input.txt",
            "output_dir": "/path/to/output",
        }

        collector.record_node_execution(
            node_id="node-10",
            node_type="TemplateNode",
            duration_ms=10.0,
            success=True,
            template_resolutions=template_resolutions,
        )

        event = collector.events[0]
        assert "template_resolutions" in event
        assert event["template_resolutions"] == template_resolutions

    def test_filename_format(self, collector, temp_home):
        """Test that trace files are saved with correct filename format."""
        with (
            patch("pathlib.Path.home", return_value=temp_home),
            patch("pflow.runtime.workflow_trace.datetime") as mock_datetime,
        ):
            # Set up mock datetime
            mock_now = Mock()
            mock_now.strftime.return_value = "20240115-143022"
            mock_now.isoformat.return_value = "2024-01-15T14:30:22"
            mock_datetime.now.return_value = mock_now
            mock_datetime.now().total_seconds = Mock(return_value=1000)

            # Subtract method for duration calculation
            mock_now.__sub__ = Mock()
            mock_now.__sub__().total_seconds = Mock(return_value=1.5)

            filepath = collector.save_to_file()

            # The filename now includes the workflow name
            expected_path = temp_home / ".pflow" / "debug" / "workflow-trace-test-workflow-20240115-143022.json"
            assert filepath == expected_path
            assert filepath.exists()

    def test_file_saving_location(self, collector, temp_home):
        """Test that trace files are saved to ~/.pflow/debug/."""
        with patch("pathlib.Path.home", return_value=temp_home):
            # Add some test events
            collector.record_node_execution(
                node_id="node-11",
                node_type="TestNode",
                duration_ms=100.0,
                success=True,
                node_output={"result": "success"},
            )

            filepath = collector.save_to_file()

            # Verify directory structure
            debug_dir = temp_home / ".pflow" / "debug"
            assert debug_dir.exists()
            assert debug_dir.is_dir()

            # Verify file exists
            assert filepath.exists()
            assert filepath.parent == debug_dir

    def test_save_to_file_content(self, collector, temp_home):
        """Test the content of saved trace file."""
        with patch("pathlib.Path.home", return_value=temp_home):
            # Add successful and failed nodes
            collector.record_node_execution(
                node_id="success-node",
                node_type="SuccessNode",
                duration_ms=100.0,
                success=True,
                node_output={"status": "ok"},
            )

            collector.record_node_execution(
                node_id="fail-node",
                node_type="FailNode",
                duration_ms=50.0,
                success=False,
                error="Something went wrong",
            )

            filepath = collector.save_to_file()

            # Read and verify content
            with open(filepath) as f:
                trace_data = json.load(f)

            # Verify metadata
            assert trace_data["workflow_name"] == "test-workflow"
            assert trace_data["execution_id"] == collector.execution_id
            assert "start_time" in trace_data
            assert "end_time" in trace_data
            assert "duration_ms" in trace_data

            # Verify format version
            assert trace_data["format_version"] == "2.0.0"

            # Verify node counts
            assert trace_data["nodes_executed"] == 2
            assert trace_data["nodes_failed"] == 1
            assert trace_data["final_status"] == "failed"  # Has failed nodes

            # Verify events
            assert len(trace_data["nodes"]) == 2
            assert trace_data["nodes"][0]["node_id"] == "success-node"
            assert trace_data["nodes"][1]["node_id"] == "fail-node"

    def test_execution_id_is_valid_uuid(self, collector):
        """Test that execution_id is a valid UUID."""
        # The execution_id should be a valid UUID string
        try:
            uuid_obj = uuid.UUID(collector.execution_id)
            # Verify it's a version 4 UUID (random)
            assert uuid_obj.version == 4
        except ValueError:
            pytest.fail("execution_id is not a valid UUID")

    def test_execution_id_in_saved_file(self, collector, temp_home):
        """Test that execution_id is stored inside the JSON, not in filename."""
        with patch("pathlib.Path.home", return_value=temp_home):
            filepath = collector.save_to_file()

            # Verify execution_id is NOT in filename
            assert collector.execution_id not in str(filepath)

            # Verify execution_id IS in the JSON content
            with open(filepath) as f:
                trace_data = json.load(f)
            assert trace_data["execution_id"] == collector.execution_id

    def test_final_status_success(self, collector, temp_home):
        """Test that final_status is 'success' when all nodes succeed."""
        with patch("pathlib.Path.home", return_value=temp_home):
            # Add only successful nodes
            for i in range(3):
                collector.record_node_execution(
                    node_id=f"node-{i}",
                    node_type="TestNode",
                    duration_ms=10.0,
                    success=True,
                )

            filepath = collector.save_to_file()

            with open(filepath) as f:
                trace_data = json.load(f)

            assert trace_data["final_status"] == "success"
            assert trace_data["nodes_failed"] == 0

    def test_final_status_failed(self, collector, temp_home):
        """Test that final_status is 'failed' when any node fails."""
        with patch("pathlib.Path.home", return_value=temp_home):
            # Mix of successful and failed nodes
            collector.record_node_execution(
                node_id="node-1",
                node_type="TestNode",
                duration_ms=10.0,
                success=True,
            )

            collector.record_node_execution(
                node_id="node-2",
                node_type="TestNode",
                duration_ms=10.0,
                success=False,
                error="Failed",
            )

            filepath = collector.save_to_file()

            with open(filepath) as f:
                trace_data = json.load(f)

            assert trace_data["final_status"] == "failed"
            assert trace_data["nodes_failed"] == 1

    def test_final_status_success_with_parser_warning(self, collector, temp_home):
        """Parser warnings should be recorded but should not mark the trace as degraded."""
        with patch("pathlib.Path.home", return_value=temp_home):
            collector.record_node_execution(
                node_id="node-1",
                node_type="TestNode",
                duration_ms=10.0,
                success=True,
            )
            collector.set_warnings([
                Diagnostic(
                    severity=Severity.WARNING,
                    message="Line 3: '## Input' looks like a typo for '## Inputs'.",
                    source="parser",
                    suggestions=["Rename to '## Inputs'."],
                )
            ])

            filepath = collector.save_to_file()

            with open(filepath) as f:
                trace_data = json.load(f)

            assert trace_data["final_status"] == "success"
            assert trace_data["warnings"][0]["source"] == "parser"

    def test_final_status_degraded_with_runtime_warning(self, collector, temp_home):
        """Runtime warnings should still mark the trace as degraded."""
        with patch("pathlib.Path.home", return_value=temp_home):
            collector.record_node_execution(
                node_id="node-1",
                node_type="TestNode",
                duration_ms=10.0,
                success=True,
            )
            collector.set_warnings([
                Diagnostic(
                    severity=Severity.WARNING,
                    message="Template resolution failed for ${fetch.response}",
                    node_id="node-1",
                    source="runtime",
                    suggestions=["Fix the template reference."],
                )
            ])

            filepath = collector.save_to_file()

            with open(filepath) as f:
                trace_data = json.load(f)

            assert trace_data["final_status"] == "degraded"
            assert trace_data["warnings"][0]["source"] == "runtime"

    def test_llm_summary_in_trace(self, collector, temp_home):
        """Test that LLM summary is included when LLM calls are present in events.

        In format 2.0.0, llm_summary is built by _collect_llm_summary() which
        recursively scans events for llm_call data — not from a separate parameter.
        """
        with patch("pathlib.Path.home", return_value=temp_home):
            # Add nodes with LLM calls via node_output
            collector.record_node_execution(
                node_id="llm-1",
                node_type="LLMNode",
                duration_ms=1000.0,
                success=True,
                node_output={
                    "llm_usage": {
                        "model": "gpt-4",
                        "total_tokens": 100,
                    }
                },
            )

            collector.record_node_execution(
                node_id="llm-2",
                node_type="LLMNode",
                duration_ms=1500.0,
                success=True,
                node_output={
                    "llm_usage": {
                        "model": "gpt-3.5-turbo",
                        "total_tokens": 50,
                    }
                },
            )

            # Add non-LLM node
            collector.record_node_execution(
                node_id="normal",
                node_type="NormalNode",
                duration_ms=10.0,
                success=True,
            )

            filepath = collector.save_to_file()

            with open(filepath) as f:
                trace_data = json.load(f)

            assert "llm_summary" in trace_data
            summary = trace_data["llm_summary"]
            assert summary["total_calls"] == 2
            assert summary["total_tokens"] == 150
            assert set(summary["models_used"]) == {"gpt-4", "gpt-3.5-turbo"}

    def test_no_llm_summary_without_llm_calls(self, collector, temp_home):
        """Test that LLM summary is not included when no LLM calls are present."""
        with patch("pathlib.Path.home", return_value=temp_home):
            # Add only non-LLM nodes
            collector.record_node_execution(
                node_id="node-1",
                node_type="NormalNode",
                duration_ms=10.0,
                success=True,
            )

            filepath = collector.save_to_file()

            with open(filepath) as f:
                trace_data = json.load(f)

            assert "llm_summary" not in trace_data

    def test_directory_creation(self, temp_home):
        """Test that ~/.pflow/debug/ directory is created if it doesn't exist."""
        with patch("pathlib.Path.home", return_value=temp_home):
            debug_dir = temp_home / ".pflow" / "debug"
            assert not debug_dir.exists()

            collector = WorkflowTraceCollector("test-workflow")
            collector.save_to_file()

            assert debug_dir.exists()
            assert debug_dir.is_dir()

    def test_multiple_events_order_preserved(self, collector):
        """Test that multiple events are recorded in order."""
        for i in range(5):
            collector.record_node_execution(
                node_id=f"node-{i}",
                node_type=f"Node{i}",
                duration_ms=float(i * 10),
                success=True,
                node_output={f"result_{i}": i},
            )

        assert len(collector.events) == 5
        for i, event in enumerate(collector.events):
            assert event["node_id"] == f"node-{i}"
            assert event["node_type"] == f"Node{i}"
            assert event["duration_ms"] == float(i * 10)

    def test_timestamp_format(self, collector):
        """Test that timestamps are in ISO format."""
        collector.record_node_execution(
            node_id="node-15",
            node_type="TimestampNode",
            duration_ms=10.0,
            success=True,
        )

        timestamp = collector.events[0]["timestamp"]
        # Should be parseable as ISO format
        parsed = datetime.fromisoformat(timestamp)
        assert isinstance(parsed, datetime)

    def test_llm_summary_from_events(self, collector, temp_home):
        """Test that llm_summary is built by scanning events for llm_call data.

        In format 2.0.0, save_to_file() uses _collect_llm_summary() which
        recursively scans tree-structured events — there is no llm_calls parameter.
        """
        with patch("pathlib.Path.home", return_value=temp_home):
            # Record events with LLM data in node_output
            collector.record_node_execution(
                node_id="parent-llm",
                node_type="LLMNode",
                duration_ms=500.0,
                success=True,
                node_output={
                    "llm_usage": {
                        "model": "gpt-4",
                        "total_tokens": 150,
                    }
                },
            )

            collector.record_node_execution(
                node_id="child-llm",
                node_type="LLMNode",
                duration_ms=300.0,
                success=True,
                node_output={
                    "llm_usage": {
                        "model": "gpt-4",
                        "total_tokens": 300,
                    }
                },
            )

            collector.record_node_execution(
                node_id="child-llm-2",
                node_type="LLMNode",
                duration_ms=200.0,
                success=True,
                node_output={
                    "llm_usage": {
                        "model": "claude-sonnet",
                        "total_tokens": 75,
                    }
                },
            )

            filepath = collector.save_to_file()

            with open(filepath) as f:
                trace_data = json.load(f)

            assert "llm_summary" in trace_data
            summary = trace_data["llm_summary"]
            assert summary["total_calls"] == 3
            assert summary["total_tokens"] == 525
            assert set(summary["models_used"]) == {"gpt-4", "claude-sonnet"}

    def test_llm_summary_scans_events_only(self, collector, temp_home):
        """Test that llm_summary is built from events (the only path in 2.0.0).

        save_to_file() no longer takes a llm_calls parameter. LLM data
        is extracted from llm_call fields in events via _collect_llm_summary().
        """
        with patch("pathlib.Path.home", return_value=temp_home):
            collector.record_node_execution(
                node_id="llm-node",
                node_type="LLMNode",
                duration_ms=1000.0,
                success=True,
                node_output={
                    "llm_usage": {"model": "gpt-4", "total_tokens": 200},
                },
            )

            filepath = collector.save_to_file()

            with open(filepath) as f:
                trace_data = json.load(f)

            assert "llm_summary" in trace_data
            assert trace_data["llm_summary"]["total_calls"] == 1
            assert trace_data["llm_summary"]["total_tokens"] == 200

    def test_no_llm_summary_when_events_have_no_llm_data(self, collector, temp_home):
        """Test that no llm_summary is generated when events lack llm_call data.

        Even if events exist, if none contain llm_call, no summary should appear.
        """
        with patch("pathlib.Path.home", return_value=temp_home):
            # Node with output but no LLM data
            collector.record_node_execution(
                node_id="shell-node",
                node_type="ShellNode",
                duration_ms=100.0,
                success=True,
                node_output={"stdout": "hello world"},
            )

            filepath = collector.save_to_file()

            with open(filepath) as f:
                trace_data = json.load(f)

            assert "llm_summary" not in trace_data

    def test_node_params_stored(self, collector):
        """Test that node_params are stored in the event when provided."""
        params = {"file_path": "/home/user/test.txt", "encoding": "utf-8"}

        collector.record_node_execution(
            node_id="read-node",
            node_type="ReadFileNode",
            duration_ms=5.0,
            success=True,
            node_params=params,
        )

        event = collector.events[0]
        assert "node_params" in event
        assert event["node_params"] == params

    def test_batch_items_stored(self, collector):
        """Test that batch_items are stored in the event when provided."""
        batch_items = [
            {"node_id": "item-0", "success": True, "duration_ms": 5.0},
            {"node_id": "item-1", "success": True, "duration_ms": 3.0},
        ]

        collector.record_node_execution(
            node_id="batch-node",
            node_type="BatchNode",
            duration_ms=10.0,
            success=True,
            batch_items=batch_items,
        )

        event = collector.events[0]
        assert "batch_items" in event
        assert len(event["batch_items"]) == 2

    def test_sub_workflow_events_stored(self, collector):
        """Test that sub_workflow_events are stored in the event when provided."""
        sub_events = [
            {"node_id": "child-1", "node_type": "ShellNode", "success": True, "duration_ms": 10.0},
            {"node_id": "child-2", "node_type": "ShellNode", "success": True, "duration_ms": 20.0},
        ]

        collector.record_node_execution(
            node_id="workflow-node",
            node_type="WorkflowExecutor",
            duration_ms=50.0,
            success=True,
            sub_workflow_events=sub_events,
        )

        event = collector.events[0]
        assert "sub_workflow_events" in event
        assert len(event["sub_workflow_events"]) == 2

    def test_llm_summary_recurses_into_sub_workflow_events(self, collector, temp_home):
        """Test that _collect_llm_summary recurses into sub_workflow_events."""
        with patch("pathlib.Path.home", return_value=temp_home):
            # Top-level LLM call
            collector.record_node_execution(
                node_id="top-llm",
                node_type="LLMNode",
                duration_ms=100.0,
                success=True,
                node_output={
                    "llm_usage": {"model": "gpt-4", "total_tokens": 100},
                },
            )

            # Nested workflow node with LLM calls in sub-events
            collector.record_node_execution(
                node_id="workflow-node",
                node_type="WorkflowExecutor",
                duration_ms=200.0,
                success=True,
                sub_workflow_events=[
                    {
                        "node_id": "child-llm",
                        "llm_call": {"model": "claude-sonnet", "total_tokens": 75},
                    },
                ],
            )

            filepath = collector.save_to_file()

            with open(filepath) as f:
                trace_data = json.load(f)

            summary = trace_data["llm_summary"]
            assert summary["total_calls"] == 2
            assert summary["total_tokens"] == 175
            assert set(summary["models_used"]) == {"gpt-4", "claude-sonnet"}

    def test_llm_summary_includes_cost(self, collector, temp_home):
        """Test that _collect_llm_summary accumulates total_cost_usd from llm_call events."""
        with patch("pathlib.Path.home", return_value=temp_home):
            collector.record_node_execution(
                node_id="llm-1",
                node_type="LLMNode",
                duration_ms=100.0,
                success=True,
                node_output={
                    "llm_usage": {"model": "gpt-4", "total_tokens": 100, "cost_usd": 0.05},
                },
            )
            collector.record_node_execution(
                node_id="llm-2",
                node_type="LLMNode",
                duration_ms=50.0,
                success=True,
                node_output={
                    "llm_usage": {"model": "claude", "total_tokens": 50, "cost_usd": 0.03},
                },
            )

            filepath = collector.save_to_file()

            with open(filepath) as f:
                trace_data = json.load(f)

            summary = trace_data["llm_summary"]
            assert summary["total_calls"] == 2
            assert summary["total_tokens"] == 150
            assert summary["total_cost_usd"] == pytest.approx(0.08)
            assert summary["pricing_available"] is True

    def test_llm_summary_unpriced_call_surfaces_as_none(self, collector, temp_home):
        """Regression: when any call has cost_usd=None (unknown-pricing model),
        total_cost_usd is None and partial_cost_usd carries the priced subset.

        Mirrors MetricsCollector.calculate_costs semantics. Pre-fix the unpriced
        cost silently collapsed to 0 and was summed away.
        """
        with patch("pathlib.Path.home", return_value=temp_home):
            collector.record_node_execution(
                node_id="llm-priced",
                node_type="LLMNode",
                duration_ms=100.0,
                success=True,
                node_output={
                    "llm_usage": {"model": "gpt-4", "total_tokens": 100, "cost_usd": 0.05},
                },
            )
            collector.record_node_execution(
                node_id="llm-unpriced",
                node_type="LLMNode",
                duration_ms=50.0,
                success=True,
                node_output={
                    "llm_usage": {"model": "ollama/llama3.2", "total_tokens": 50, "cost_usd": None},
                },
            )

            filepath = collector.save_to_file()
            with open(filepath) as f:
                trace_data = json.load(f)

            summary = trace_data["llm_summary"]
            assert summary["total_calls"] == 2
            assert summary["total_cost_usd"] is None
            assert summary["pricing_available"] is False
            assert summary["partial_cost_usd"] == pytest.approx(0.05)
            assert summary["unavailable_models"] == ["ollama/llama3.2"]

    def test_llm_summary_all_unpriced_no_partial(self, collector, temp_home):
        """When every call is unpriced, partial_cost_usd is None (not 0.0)."""
        with patch("pathlib.Path.home", return_value=temp_home):
            collector.record_node_execution(
                node_id="llm-1",
                node_type="LLMNode",
                duration_ms=100.0,
                success=True,
                node_output={
                    "llm_usage": {"model": "ollama/llama3.2", "total_tokens": 50, "cost_usd": None},
                },
            )

            filepath = collector.save_to_file()
            with open(filepath) as f:
                trace_data = json.load(f)

            summary = trace_data["llm_summary"]
            assert summary["total_cost_usd"] is None
            assert summary["partial_cost_usd"] is None
            assert summary["pricing_available"] is False
            assert summary["unavailable_models"] == ["ollama/llama3.2"]

    def test_llm_summary_includes_input_output_tokens(self, collector, temp_home):
        """Test that _collect_llm_summary accumulates input/output token breakdown."""
        with patch("pathlib.Path.home", return_value=temp_home):
            collector.record_node_execution(
                node_id="llm-1",
                node_type="LLMNode",
                duration_ms=100.0,
                success=True,
                node_output={
                    "llm_usage": {
                        "model": "gpt-4",
                        "input_tokens": 500,
                        "output_tokens": 200,
                        "total_tokens": 700,
                    },
                },
            )
            collector.record_node_execution(
                node_id="llm-2",
                node_type="LLMNode",
                duration_ms=50.0,
                success=True,
                node_output={
                    "llm_usage": {
                        "model": "claude",
                        "input_tokens": 300,
                        "output_tokens": 150,
                        "total_tokens": 450,
                    },
                },
            )

            filepath = collector.save_to_file()

            with open(filepath) as f:
                trace_data = json.load(f)

            summary = trace_data["llm_summary"]
            assert summary["total_input_tokens"] == 800
            assert summary["total_output_tokens"] == 350
            assert summary["total_tokens"] == 1150

    def test_optional_fields_omitted_when_none(self, collector):
        """Test that optional fields (node_params, mutations, etc.) are omitted when not provided."""
        collector.record_node_execution(
            node_id="minimal-node",
            node_type="TestNode",
            duration_ms=5.0,
            success=True,
        )

        event = collector.events[0]
        assert "node_params" not in event
        assert "template_resolutions" not in event
        assert "node_output" not in event
        assert "mutations" not in event
        assert "batch_items" not in event
        assert "sub_workflow_events" not in event
        assert "error" not in event


class TestCollectLLMCalls:
    """Tests for collect_llm_calls() — single source of truth for LLM cost data."""

    @pytest.fixture
    def collector(self):
        return WorkflowTraceCollector("test-workflow")

    def test_collect_llm_calls_empty(self, collector):
        """No events → empty list."""
        assert collector.collect_llm_calls() == []

    def test_collect_llm_calls_no_llm_events(self, collector):
        """Events without llm_call → empty list."""
        collector.record_node_execution(node_id="shell-1", node_type="ShellNode", duration_ms=10.0, success=True)
        assert collector.collect_llm_calls() == []

    def test_collect_llm_calls_top_level(self, collector):
        """Top-level event with llm_call is collected."""
        collector.record_node_execution(
            node_id="llm-1",
            node_type="LLMNode",
            duration_ms=500.0,
            success=True,
            node_output={"llm_usage": {"model": "gpt-4o", "input_tokens": 100, "output_tokens": 50}},
        )
        calls = collector.collect_llm_calls()
        assert len(calls) == 1
        assert calls[0]["model"] == "gpt-4o"
        assert calls[0]["node_id"] == "llm-1"
        assert calls[0]["duration_ms"] == 500.0

    def test_collect_llm_calls_batch_items(self, collector):
        """LLM calls in batch items are collected."""
        collector.record_node_execution(
            node_id="batch-llm",
            node_type="PflowBatchNode",
            duration_ms=1000.0,
            success=True,
            batch_items=[
                {
                    "index": 0,
                    "item": "a",
                    "success": True,
                    "duration_ms": 100,
                    "llm_call": {"model": "m1", "input_tokens": 10, "output_tokens": 5},
                },
                {"index": 1, "item": "b", "success": True, "duration_ms": 100},  # no llm_call
                {
                    "index": 2,
                    "item": "c",
                    "success": True,
                    "duration_ms": 100,
                    "llm_call": {"model": "m1", "input_tokens": 20, "output_tokens": 10},
                },
            ],
        )
        calls = collector.collect_llm_calls()
        assert len(calls) == 2
        assert calls[0]["batch_item_index"] == 0
        assert calls[1]["batch_item_index"] == 2

    def test_collect_llm_calls_sub_workflow(self, collector):
        """LLM calls in sub-workflow events are collected."""
        collector.record_node_execution(
            node_id="wf-1",
            node_type="WorkflowExecutor",
            duration_ms=2000.0,
            success=True,
            sub_workflow_events=[
                {
                    "node_id": "child-llm",
                    "node_type": "LLMNode",
                    "duration_ms": 300.0,
                    "success": True,
                    "llm_call": {"model": "claude-sonnet", "input_tokens": 200, "output_tokens": 100},
                },
            ],
        )
        calls = collector.collect_llm_calls()
        assert len(calls) == 1
        assert calls[0]["model"] == "claude-sonnet"
        assert calls[0]["node_id"] == "child-llm"

    def test_collect_llm_calls_nested(self, collector):
        """LLM calls from multiple levels are flattened."""
        collector.record_node_execution(
            node_id="top-llm",
            node_type="LLMNode",
            duration_ms=100.0,
            success=True,
            node_output={"llm_usage": {"model": "top-model", "input_tokens": 10, "output_tokens": 5}},
        )
        collector.record_node_execution(
            node_id="batch-wf",
            node_type="PflowBatchNode",
            duration_ms=500.0,
            success=True,
            batch_items=[
                {
                    "index": 0,
                    "item": "x",
                    "success": True,
                    "duration_ms": 200,
                    "events": [
                        {
                            "node_id": "nested-llm",
                            "node_type": "LLMNode",
                            "duration_ms": 150.0,
                            "success": True,
                            "llm_call": {"model": "nested-model", "input_tokens": 30, "output_tokens": 15},
                        }
                    ],
                }
            ],
        )
        calls = collector.collect_llm_calls()
        assert len(calls) == 2
        models = {c["model"] for c in calls}
        assert models == {"top-model", "nested-model"}


class TestCachedCostExclusion:
    """Cached events should not contribute to LLM cost aggregation."""

    @pytest.fixture
    def collector(self):
        return WorkflowTraceCollector("test-workflow")

    def test_collect_llm_calls_excludes_cached_events(self, collector):
        """Cached LLM events should not appear in collect_llm_calls()."""
        collector.record_node_execution(
            node_id="cached-llm",
            node_type="LLMNode",
            duration_ms=0.0,
            success=True,
            node_output={"llm_usage": {"model": "gpt-4o", "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.05}},
            cached=True,
        )
        collector.record_node_execution(
            node_id="fresh-llm",
            node_type="LLMNode",
            duration_ms=500.0,
            success=True,
            node_output={"llm_usage": {"model": "gpt-4o", "input_tokens": 200, "output_tokens": 100, "cost_usd": 0.10}},
        )
        calls = collector.collect_llm_calls()
        assert len(calls) == 1
        assert calls[0]["node_id"] == "fresh-llm"

    def test_collect_llm_summary_excludes_cached_cost(self, collector):
        """Cost summary should only reflect nodes that actually executed."""
        collector.record_node_execution(
            node_id="cached-llm",
            node_type="LLMNode",
            duration_ms=0.0,
            success=True,
            node_output={"llm_usage": {"model": "gpt-4o", "total_tokens": 150, "cost_usd": 0.05}},
            cached=True,
        )
        collector.record_node_execution(
            node_id="fresh-llm",
            node_type="LLMNode",
            duration_ms=500.0,
            success=True,
            node_output={"llm_usage": {"model": "gpt-4o", "total_tokens": 300, "cost_usd": 0.10}},
        )
        summary = collector._collect_llm_summary(collector.events)
        assert summary["total_calls"] == 1
        assert summary["total_cost_usd"] == pytest.approx(0.10)
        assert summary["total_tokens"] == 300

    def test_cached_sub_workflow_event_excluded_from_cost(self, collector):
        """A cached sub-workflow event's children should not be counted."""
        collector.record_node_execution(
            node_id="cached-wf",
            node_type="WorkflowExecutor",
            duration_ms=0.0,
            success=True,
            cached=True,
            sub_workflow_events=[
                {
                    "node_id": "child-llm",
                    "node_type": "LLMNode",
                    "duration_ms": 300.0,
                    "success": True,
                    "llm_call": {"model": "claude-sonnet", "input_tokens": 200, "output_tokens": 100, "cost_usd": 0.08},
                },
            ],
        )
        assert collector.collect_llm_calls() == []
        summary = collector._collect_llm_summary(collector.events)
        assert summary["total_calls"] == 0
        assert summary["total_cost_usd"] == 0.0

    def test_cached_batch_event_excluded_from_cost(self, collector):
        """A cached batch event's items should not be counted."""
        collector.record_node_execution(
            node_id="cached-batch",
            node_type="PflowBatchNode",
            duration_ms=0.0,
            success=True,
            cached=True,
            batch_items=[
                {
                    "index": 0,
                    "item": "a",
                    "success": True,
                    "duration_ms": 100,
                    "llm_call": {"model": "m1", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.01},
                },
                {
                    "index": 1,
                    "item": "b",
                    "success": True,
                    "duration_ms": 100,
                    "llm_call": {"model": "m1", "input_tokens": 20, "output_tokens": 10, "cost_usd": 0.02},
                },
            ],
        )
        assert collector.collect_llm_calls() == []
        summary = collector._collect_llm_summary(collector.events)
        assert summary["total_calls"] == 0
        assert summary["total_cost_usd"] == 0.0

    def test_mixed_cached_and_fresh_cost(self, collector):
        """Only fresh nodes contribute to total cost in a mixed scenario."""
        # Two cached LLM nodes with different costs
        collector.record_node_execution(
            node_id="cached-1",
            node_type="LLMNode",
            duration_ms=0.0,
            success=True,
            node_output={"llm_usage": {"model": "gpt-4o", "total_tokens": 100, "cost_usd": 0.05}},
            cached=True,
        )
        collector.record_node_execution(
            node_id="cached-2",
            node_type="LLMNode",
            duration_ms=0.0,
            success=True,
            node_output={"llm_usage": {"model": "gpt-4o", "total_tokens": 200, "cost_usd": 0.10}},
            cached=True,
        )
        # One fresh node
        collector.record_node_execution(
            node_id="fresh-1",
            node_type="LLMNode",
            duration_ms=800.0,
            success=True,
            node_output={"llm_usage": {"model": "gpt-4o", "total_tokens": 300, "cost_usd": 0.15}},
        )
        calls = collector.collect_llm_calls()
        assert len(calls) == 1
        assert calls[0]["node_id"] == "fresh-1"

        summary = collector._collect_llm_summary(collector.events)
        assert summary["total_calls"] == 1
        assert summary["total_cost_usd"] == pytest.approx(0.15)
        assert summary["total_tokens"] == 300

    def test_non_cached_workflow_with_mixed_inner_nodes(self, collector):
        """Real-world scenario: workflow node re-executes (not cached), but its
        sub_workflow_events contain a mix of cached and fresh inner nodes.

        This is the exact interaction of both bug fixes:
        - Bug 1 fix: workflow node skips memoization, so it re-executes
        - Bug 2 fix: cached inner nodes don't contribute to cost

        Only the fresh inner node's cost should be counted.
        """
        collector.record_node_execution(
            node_id="greet",
            node_type="WorkflowExecutor",
            duration_ms=50.0,
            success=True,
            # Not cached — workflow nodes skip memoization (Bug 1 fix)
            sub_workflow_events=[
                {
                    "node_id": "say-hello",
                    "node_type": "LLMNode",
                    "duration_ms": 0.0,
                    "success": True,
                    "cached": True,  # Unchanged inner node served from cache
                    "llm_call": {"model": "gpt-4o", "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.05},
                },
                {
                    "node_id": "format-output",
                    "node_type": "LLMNode",
                    "duration_ms": 800.0,
                    "success": True,
                    # No cached flag — this node actually executed
                    "llm_call": {"model": "gpt-4o", "input_tokens": 200, "output_tokens": 100, "cost_usd": 0.10},
                },
            ],
        )
        calls = collector.collect_llm_calls()
        assert len(calls) == 1
        assert calls[0]["node_id"] == "format-output"

        summary = collector._collect_llm_summary(collector.events)
        assert summary["total_calls"] == 1
        assert summary["total_cost_usd"] == pytest.approx(0.10)


class TestCachedNodeEvent:
    """D5: Verify cached=True flag appears in trace events."""

    def test_cached_flag_in_event(self) -> None:
        collector = WorkflowTraceCollector("test")
        collector.record_node_execution(
            node_id="cached-step",
            node_type="ShellNode",
            duration_ms=0.0,
            success=True,
            cached=True,
        )
        assert len(collector.events) == 1
        assert collector.events[0]["cached"] is True

    def test_non_cached_has_no_flag(self) -> None:
        collector = WorkflowTraceCollector("test")
        collector.record_node_execution(
            node_id="normal-step",
            node_type="ShellNode",
            duration_ms=100.0,
            success=True,
        )
        assert "cached" not in collector.events[0]


class TestFinalEventsByNode:
    """Aggregation rule: last event per node_id = final state.

    Motivating issue: GH #240 — loop recovery records two events for the same
    node_id (visit 1 fail, visit 2 success); aggregation must report success.
    """

    @pytest.fixture
    def collector(self):
        return WorkflowTraceCollector("test")

    def test_single_visit_per_node(self, collector):
        collector.record_node_execution(node_id="a", node_type="T", duration_ms=1.0, success=True)
        collector.record_node_execution(node_id="b", node_type="T", duration_ms=1.0, success=False, error="boom")

        final = final_events_by_node(collector.events)

        assert set(final.keys()) == {"a", "b"}
        assert final["a"]["success"] is True
        assert final["b"]["success"] is False

    def test_loop_recovery_returns_latest(self, collector):
        collector.record_node_execution(
            node_id="maybe-fail", node_type="T", duration_ms=1.0, success=False, error="exit 9"
        )
        collector.record_node_execution(node_id="retry", node_type="T", duration_ms=1.0, success=True)
        collector.record_node_execution(node_id="maybe-fail", node_type="T", duration_ms=1.0, success=True)

        final = final_events_by_node(collector.events)

        assert final["maybe-fail"]["success"] is True
        # Error from the first visit must NOT bleed into the final state
        assert final["maybe-fail"].get("error") is None

    def test_event_without_node_id_ignored(self, collector):
        """Defensive: events missing node_id (shouldn't happen today) are skipped."""
        collector.events.append({"node_type": "T", "duration_ms": 1.0, "success": False})  # no node_id
        collector.record_node_execution(node_id="a", node_type="T", duration_ms=1.0, success=True)

        final = final_events_by_node(collector.events)

        assert set(final.keys()) == {"a"}


class TestDetermineTraceStatusAggregation:
    """_determine_trace_status uses the per-node-last-event rule."""

    @pytest.fixture
    def collector(self):
        return WorkflowTraceCollector("test")

    def test_loop_recovery_reports_success(self, collector):
        """Visit 1 fail + visit 2 success → success (GH #240)."""
        collector.record_node_execution(
            node_id="maybe-fail", node_type="T", duration_ms=1.0, success=False, error="exit 9"
        )
        collector.record_node_execution(node_id="maybe-fail", node_type="T", duration_ms=1.0, success=True)

        assert collector._determine_trace_status() == "success"

    def test_loop_both_visits_fail_reports_failed(self, collector):
        """Both visits fail → failed (recovery did not happen)."""
        collector.record_node_execution(
            node_id="maybe-fail", node_type="T", duration_ms=1.0, success=False, error="boom1"
        )
        collector.record_node_execution(
            node_id="maybe-fail", node_type="T", duration_ms=1.0, success=False, error="boom2"
        )

        assert collector._determine_trace_status() == "failed"

    def test_cached_after_fail_reports_success(self, collector):
        """Visit 1 fail, visit 2 cached+success → success.

        Locks the cached+loop invariant: when a cached hit follows a failure
        in the same node, aggregation treats the cached hit as the final state.
        The ``cached=True`` flag is preserved on the event (audit view) but does
        NOT exclude it from aggregation — it participates like any other
        success=True event.
        """
        collector.record_node_execution(node_id="n", node_type="T", duration_ms=1.0, success=False, error="boom")
        collector.record_node_execution(node_id="n", node_type="T", duration_ms=0.0, success=True, cached=True)

        assert collector._determine_trace_status() == "success"
        # Verify the final event actually IS the cached one — guards against
        # a future "exclude cached from aggregation" rule silently flipping behavior.
        final = final_events_by_node(collector.events)
        assert final["n"].get("cached") is True
        assert final["n"]["success"] is True

    def test_cached_hit_does_not_mask_failure_on_other_node(self, collector):
        """Negative variant: a cached success on node A does NOT mask a
        failure on node B. Aggregation is per-node, not global.
        """
        collector.record_node_execution(node_id="a", node_type="T", duration_ms=0.0, success=True, cached=True)
        collector.record_node_execution(node_id="b", node_type="T", duration_ms=1.0, success=False, error="boom")

        assert collector._determine_trace_status() == "failed"


class TestMarkLastEventFailed:
    """Mutation API for GH #250 — routing failures detected after step 16 trace."""

    @pytest.fixture
    def collector(self):
        return WorkflowTraceCollector("test")

    def test_flips_most_recent_event_for_node(self, collector):
        collector.record_node_execution(node_id="a", node_type="T", duration_ms=1.0, success=True)
        collector.record_node_execution(node_id="b", node_type="T", duration_ms=1.0, success=True)

        collector.mark_last_event_failed("a", error="routing failed: action 'x' not in successors")

        # Only 'a' flipped; 'b' untouched
        flipped = next(e for e in collector.events if e["node_id"] == "a")
        untouched = next(e for e in collector.events if e["node_id"] == "b")
        assert flipped["success"] is False
        assert flipped["error"] == "routing failed: action 'x' not in successors"
        assert untouched["success"] is True
        assert "error" not in untouched

    def test_flips_most_recent_when_multiple_events_for_node(self, collector):
        """When a node has multiple events (loop), only the LAST one is flipped."""
        collector.record_node_execution(node_id="n", node_type="T", duration_ms=1.0, success=False, error="visit1")
        collector.record_node_execution(node_id="n", node_type="T", duration_ms=1.0, success=True)

        collector.mark_last_event_failed("n", error="routing boom")

        # Visit 1 event retains its original error
        assert collector.events[0]["success"] is False
        assert collector.events[0]["error"] == "visit1"
        # Visit 2 event is now flipped with the new error
        assert collector.events[1]["success"] is False
        assert collector.events[1]["error"] == "routing boom"

    def test_no_op_for_unknown_node(self, collector):
        """No event matching node_id → no mutation, no exception."""
        collector.record_node_execution(node_id="a", node_type="T", duration_ms=1.0, success=True)

        collector.mark_last_event_failed("does-not-exist", error="ignored")

        # 'a' untouched
        assert collector.events[0]["success"] is True

    def test_preserves_node_output(self, collector):
        """Flipped event retains node_output from the successful execution.

        Semantically correct: the node produced output, then routing failed.
        Per-node report files show both the output and the failed status.
        """
        collector.record_node_execution(
            node_id="router",
            node_type="T",
            duration_ms=1.0,
            success=True,
            node_output={"result": "custom_route"},
        )

        collector.mark_last_event_failed("router", error="routing boom")

        event = collector.events[0]
        assert event["success"] is False
        assert event["error"] == "routing boom"
        assert event["node_output"] == {"result": "custom_route"}

    def test_does_not_touch_batch_items(self, collector):
        """Flipping a batch node's event must NOT mutate per-item batch_items.

        ``mark_last_event_failed`` walks ``self.events`` (top-level only). Batch
        items live inside ``event["batch_items"]`` with their own per-item success
        flags (audit view). If the helper recursed, a routing failure on a batch
        with all-successful items would silently change their reported status.
        """
        collector.record_node_execution(
            node_id="my-batch",
            node_type="BatchNode",
            duration_ms=1.0,
            success=True,
            batch_items=[
                {"index": 0, "success": True, "duration_ms": 0.5},
                {"index": 1, "success": True, "duration_ms": 0.5},
            ],
        )

        collector.mark_last_event_failed("my-batch", error="routing boom")

        event = collector.events[0]
        # Top-level flipped
        assert event["success"] is False
        assert event["error"] == "routing boom"
        # Per-item status untouched — audit view preserved
        assert event["batch_items"][0]["success"] is True
        assert event["batch_items"][1]["success"] is True


class TestSaveToFileFailedNodeIds:
    """Trace file must carry failed_node_ids as the authoritative failed-node list."""

    @pytest.fixture
    def collector(self):
        return WorkflowTraceCollector("test")

    @pytest.fixture
    def temp_home(self, tmp_path):
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        return home_dir

    def _read_trace(self, filepath):
        with open(filepath) as f:
            return json.load(f)

    def test_writes_failed_node_ids_key(self, collector, temp_home):
        with patch("pathlib.Path.home", return_value=temp_home):
            collector.record_node_execution(node_id="ok", node_type="T", duration_ms=1.0, success=True)
            collector.record_node_execution(node_id="bad", node_type="T", duration_ms=1.0, success=False, error="boom")
            trace_data = self._read_trace(collector.save_to_file())

            assert "failed_node_ids" in trace_data
            assert trace_data["failed_node_ids"] == ["bad"]

    def test_invariants_hold(self, collector, temp_home):
        """nodes_failed == len(failed_node_ids); final_status=='failed' iff list non-empty.

        This invariant is the architectural guarantee the #240 fix creates;
        pin it explicitly so a future refactor can't silently break it.
        """
        with patch("pathlib.Path.home", return_value=temp_home):
            collector.record_node_execution(node_id="a", node_type="T", duration_ms=1.0, success=False, error="x")
            collector.record_node_execution(node_id="b", node_type="T", duration_ms=1.0, success=False, error="y")
            trace_data = self._read_trace(collector.save_to_file())

            assert trace_data["nodes_failed"] == len(trace_data["failed_node_ids"])
            assert (trace_data["final_status"] == "failed") == (len(trace_data["failed_node_ids"]) > 0)

    def test_loop_recovery_reports_zero_failed_nodes(self, collector, temp_home):
        """Loop recovery: 2 visits, 0 failed nodes. nodes_executed (per-visit) != nodes_failed (per-node).

        Documents the semantic shift — GH #240.
        """
        with patch("pathlib.Path.home", return_value=temp_home):
            collector.record_node_execution(
                node_id="maybe-fail", node_type="T", duration_ms=1.0, success=False, error="exit 9"
            )
            collector.record_node_execution(node_id="maybe-fail", node_type="T", duration_ms=1.0, success=True)
            trace_data = self._read_trace(collector.save_to_file())

            assert trace_data["nodes_executed"] == 2  # per-visit
            assert trace_data["nodes_failed"] == 0  # per-node (unique failed)
            assert trace_data["failed_node_ids"] == []
            assert trace_data["final_status"] == "success"

    def test_failed_node_ids_sorted(self, collector, temp_home):
        """Sorted alphabetically for deterministic JSON output."""
        with patch("pathlib.Path.home", return_value=temp_home):
            collector.record_node_execution(node_id="zebra", node_type="T", duration_ms=1.0, success=False, error="z")
            collector.record_node_execution(node_id="alpha", node_type="T", duration_ms=1.0, success=False, error="a")
            trace_data = self._read_trace(collector.save_to_file())

            assert trace_data["failed_node_ids"] == ["alpha", "zebra"]
