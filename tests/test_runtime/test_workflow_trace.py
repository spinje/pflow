"""Comprehensive unit tests for WorkflowTraceCollector."""

import json
import uuid
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from src.pflow.runtime.workflow_trace import WorkflowTraceCollector


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
        shared_before = {"input": "test"}
        shared_after = {"input": "test", "output": "result"}

        collector.record_node_execution(
            node_id="node-1",
            node_type="TestNode",
            duration_ms=123.456,
            shared_before=shared_before,
            shared_after=shared_after,
            success=True,
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

        # Verify shared store data
        assert event["shared_before"] == {"input": "test"}
        assert event["shared_after"] == {"input": "test", "output": "result"}

    def test_record_node_execution_failure(self, collector):
        """Test recording a failed node execution."""
        shared_before = {"input": "test"}
        shared_after = {"input": "test"}

        collector.record_node_execution(
            node_id="node-2",
            node_type="FailingNode",
            duration_ms=50.0,
            shared_before=shared_before,
            shared_after=shared_after,
            success=False,
            error="Division by zero",
        )

        event = collector.events[0]
        assert event["success"] is False
        assert event["error"] == "Division by zero"

    def test_mutation_calculation(self, collector):
        """Test that mutations between shared states are calculated correctly."""
        shared_before = {
            "keep": "unchanged",
            "modify": "old_value",
            "remove": "will_be_removed",
        }
        shared_after = {
            "keep": "unchanged",
            "modify": "new_value",
            "added": "new_key",
        }

        collector.record_node_execution(
            node_id="node-3",
            node_type="MutationNode",
            duration_ms=10.0,
            shared_before=shared_before,
            shared_after=shared_after,
            success=True,
        )

        mutations = collector.events[0]["mutations"]
        assert mutations["added"] == ["added"]
        assert mutations["removed"] == ["remove"]
        assert mutations["modified"] == ["modify"]

    def test_shared_store_filtering_large_strings(self, collector):
        """Test that large strings in shared store are truncated."""
        large_string = "x" * 2000  # String longer than 1000 chars
        shared_before = {}
        shared_after = {"large_data": large_string}

        collector.record_node_execution(
            node_id="node-4",
            node_type="LargeDataNode",
            duration_ms=5.0,
            shared_before=shared_before,
            shared_after=shared_after,
            success=True,
        )

        filtered_value = collector.events[0]["shared_after"]["large_data"]
        assert filtered_value.endswith("... [truncated]")
        assert len(filtered_value) == 1000 + len("... [truncated]")

    def test_shared_store_filtering_binary_data(self, collector):
        """Test that binary data is replaced with placeholder."""
        shared_before = {}
        shared_after = {"binary": b"some binary content"}

        collector.record_node_execution(
            node_id="node-5",
            node_type="BinaryNode",
            duration_ms=5.0,
            shared_before=shared_before,
            shared_after=shared_after,
            success=True,
        )

        filtered_value = collector.events[0]["shared_after"]["binary"]
        assert filtered_value == "<binary data: 19 bytes>"

    def test_shared_store_filtering_system_keys(self, collector):
        """Test that system keys are filtered except allowed ones."""
        shared_before = {}
        shared_after = {
            "__private__": "should_be_filtered",
            "__llm_calls__": ["call1", "call2"],
            "__metrics__": {"key": "value"},
            "__is_planner__": True,
            "normal_key": "keep_this",
        }

        collector.record_node_execution(
            node_id="node-6",
            node_type="SystemKeyNode",
            duration_ms=5.0,
            shared_before=shared_before,
            shared_after=shared_after,
            success=True,
        )

        filtered_after = collector.events[0]["shared_after"]
        assert "__private__" not in filtered_after
        assert "__llm_calls__" in filtered_after
        assert "__metrics__" in filtered_after
        assert "__is_planner__" in filtered_after
        assert filtered_after["normal_key"] == "keep_this"

    def test_shared_store_filtering_internal_keys(self, collector):
        """Test that internal trace/debug keys are filtered."""
        shared_before = {}
        shared_after = {
            "_trace_collector": "internal",
            "_debug_context": "internal",
            "user_data": "keep_this",
        }

        collector.record_node_execution(
            node_id="node-7",
            node_type="InternalKeyNode",
            duration_ms=5.0,
            shared_before=shared_before,
            shared_after=shared_after,
            success=True,
        )

        filtered_after = collector.events[0]["shared_after"]
        assert "_trace_collector" not in filtered_after
        assert "_debug_context" not in filtered_after
        assert filtered_after["user_data"] == "keep_this"

    def test_llm_call_capture(self, collector):
        """Test that LLM usage data is captured from shared_after."""
        shared_before = {}
        shared_after = {
            "llm_usage": {
                "model": "gpt-4",
                "total_tokens": 150,
                "prompt_tokens": 100,
                "completion_tokens": 50,
            }
        }

        collector.record_node_execution(
            node_id="node-8",
            node_type="LLMNode",
            duration_ms=1000.0,
            shared_before=shared_before,
            shared_after=shared_after,
            success=True,
        )

        event = collector.events[0]
        assert "llm_call" in event
        assert event["llm_call"]["model"] == "gpt-4"
        assert event["llm_call"]["total_tokens"] == 150

    def test_llm_response_capture(self, collector):
        """Test that LLM responses are captured and truncated if too long."""
        # Test short response
        shared_before = {}
        shared_after = {"response": "Short LLM response"}

        collector.record_node_execution(
            node_id="node-9a",
            node_type="LLMNode",
            duration_ms=100.0,
            shared_before=shared_before,
            shared_after=shared_after,
            success=True,
        )

        event = collector.events[0]
        assert event["llm_response"] == "Short LLM response"

        # Test long response (should be truncated)
        long_response = "x" * 3000
        shared_after_long = {"response": long_response}

        collector.record_node_execution(
            node_id="node-9b",
            node_type="LLMNode",
            duration_ms=100.0,
            shared_before={},
            shared_after=shared_after_long,
            success=True,
        )

        event = collector.events[1]
        assert "llm_response_truncated" in event
        assert event["llm_response_truncated"].endswith("... [truncated]")
        assert len(event["llm_response_truncated"]) == 2000 + len("... [truncated]")

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
            shared_before={},
            shared_after={"result": "done"},
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
            patch("src.pflow.runtime.workflow_trace.datetime") as mock_datetime,
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
                shared_before={},
                shared_after={"result": "success"},
                success=True,
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
                shared_before={},
                shared_after={"status": "ok"},
                success=True,
            )

            collector.record_node_execution(
                node_id="fail-node",
                node_type="FailNode",
                duration_ms=50.0,
                shared_before={"status": "ok"},
                shared_after={"status": "ok"},
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
                    shared_before={},
                    shared_after={},
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
                shared_before={},
                shared_after={},
                success=True,
            )

            collector.record_node_execution(
                node_id="node-2",
                node_type="TestNode",
                duration_ms=10.0,
                shared_before={},
                shared_after={},
                success=False,
                error="Failed",
            )

            filepath = collector.save_to_file()

            with open(filepath) as f:
                trace_data = json.load(f)

            assert trace_data["final_status"] == "failed"
            assert trace_data["nodes_failed"] == 1

    def test_llm_summary_in_trace(self, collector, temp_home):
        """Test that LLM summary is included when LLM calls are present."""
        with patch("pathlib.Path.home", return_value=temp_home):
            # Add nodes with LLM calls
            collector.record_node_execution(
                node_id="llm-1",
                node_type="LLMNode",
                duration_ms=1000.0,
                shared_before={},
                shared_after={
                    "llm_usage": {
                        "model": "gpt-4",
                        "total_tokens": 100,
                    }
                },
                success=True,
            )

            collector.record_node_execution(
                node_id="llm-2",
                node_type="LLMNode",
                duration_ms=1500.0,
                shared_before={},
                shared_after={
                    "llm_usage": {
                        "model": "gpt-3.5-turbo",
                        "total_tokens": 50,
                    }
                },
                success=True,
            )

            # Add non-LLM node
            collector.record_node_execution(
                node_id="normal",
                node_type="NormalNode",
                duration_ms=10.0,
                shared_before={},
                shared_after={},
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
                shared_before={},
                shared_after={},
                success=True,
            )

            filepath = collector.save_to_file()

            with open(filepath) as f:
                trace_data = json.load(f)

            assert "llm_summary" not in trace_data

    def test_large_dict_truncation(self, collector):
        """Test that large dicts in shared store are truncated."""
        # Create a large dict
        large_dict = {f"key_{i}": f"value_{i}" * 100 for i in range(100)}
        assert len(str(large_dict)) > 5000

        shared_before = {}
        shared_after = {"large_nested": large_dict}

        collector.record_node_execution(
            node_id="node-12",
            node_type="LargeDictNode",
            duration_ms=5.0,
            shared_before=shared_before,
            shared_after=shared_after,
            success=True,
        )

        filtered_value = collector.events[0]["shared_after"]["large_nested"]
        assert filtered_value == "<large dict truncated>"

    def test_llm_calls_list_truncation(self, collector):
        """Test that __llm_calls__ list is truncated to 10 items."""
        # Create a list with more than 10 items
        llm_calls = [f"call_{i}" for i in range(20)]

        shared_before = {}
        shared_after = {"__llm_calls__": llm_calls}

        collector.record_node_execution(
            node_id="node-13",
            node_type="ManyLLMCallsNode",
            duration_ms=5.0,
            shared_before=shared_before,
            shared_after=shared_after,
            success=True,
        )

        filtered_calls = collector.events[0]["shared_after"]["__llm_calls__"]
        assert len(filtered_calls) == 10
        assert filtered_calls == [f"call_{i}" for i in range(10)]

    def test_unhashable_type_mutation_detection(self, collector):
        """Test mutation detection with unhashable types like lists."""
        shared_before = {
            "list_unchanged": [1, 2, 3],
            "list_modified": [1, 2, 3],
            "dict_unchanged": {"a": 1},
            "dict_modified": {"a": 1},
        }
        shared_after = {
            "list_unchanged": [1, 2, 3],
            "list_modified": [1, 2, 4],  # Changed
            "dict_unchanged": {"a": 1},
            "dict_modified": {"a": 2},  # Changed
        }

        collector.record_node_execution(
            node_id="node-14",
            node_type="UnhashableNode",
            duration_ms=10.0,
            shared_before=shared_before,
            shared_after=shared_after,
            success=True,
        )

        mutations = collector.events[0]["mutations"]
        assert "list_modified" in mutations["modified"]
        assert "dict_modified" in mutations["modified"]
        assert "list_unchanged" not in mutations["modified"]
        assert "dict_unchanged" not in mutations["modified"]

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
                shared_before={},
                shared_after={f"result_{i}": i},
                success=True,
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
            shared_before={},
            shared_after={},
            success=True,
        )

        timestamp = collector.events[0]["timestamp"]
        # Should be parseable as ISO format
        parsed = datetime.fromisoformat(timestamp)
        assert isinstance(parsed, datetime)
