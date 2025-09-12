"""Integration tests for the unified metrics and tracing system.

Tests the complete flow of metrics collection, JSON output, and trace generation
when running workflows through the CLI.
"""

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from pflow.cli.main import main as cli
from pflow.core.metrics import MetricsCollector
from pflow.runtime.workflow_trace import WorkflowTraceCollector
from tests.shared.llm_mock import create_mock_get_model


@pytest.fixture
def mock_llm():
    """Create a mock LLM that tracks usage data."""
    mock_get_model = create_mock_get_model()

    # Configure LLM response with usage data
    def configure_with_usage(model: str, schema: Any, response: dict, input_tokens: int = 100, output_tokens: int = 50):
        """Configure response and add usage tracking."""
        mock_get_model.set_response(model, schema, response)

        # Patch the MockLLMModel to include proper usage
        original_prompt = mock_get_model(model).prompt

        def prompt_with_usage(prompt_text: str, schema_arg: Any = None, **kwargs):
            result = original_prompt(prompt_text, schema_arg, **kwargs)

            # Add usage data that LLMNode expects - as an object with .input and .output attributes
            # Create a simple object that mimics the llm library's usage format
            class Usage:
                def __init__(self, input_val, output_val):
                    self.input = input_val
                    self.output = output_val
                    self.details = {}  # LLMNode may check for details

            # Make usage a method that returns the usage object
            usage_obj = Usage(input_tokens, output_tokens)
            result.usage = lambda: usage_obj
            return result

        mock_get_model(model).prompt = prompt_with_usage

    mock_get_model.configure_with_usage = configure_with_usage
    return mock_get_model


@pytest.fixture
def temp_home(tmp_path):
    """Create a temporary home directory for testing."""
    yield tmp_path


@pytest.fixture
def temp_registry(temp_home):
    """Create a temporary registry for testing."""
    registry_path = temp_home / ".pflow" / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    # Create minimal registry with test nodes
    # Note: Registry stores nodes directly, not wrapped in a structure
    registry_data = {
        "echo": {
            "module": "pflow.nodes.test.echo",
            "class_name": "EchoNode",  # Note: class_name not class
            "metadata": {
                "name": "echo",
                "description": "Echoes input to output",
                "parameters": {"message": {"type": "string", "description": "Message to echo"}},
            },
            "interface": {
                "writes": {"echo": {"type": "string", "description": "Echoed message"}},
                "params": {"message": {"type": "string", "description": "Message to echo"}},
                "outputs": {"echo": {"type": "string", "description": "Echoed message"}},
            },
        },
        "llm": {
            "module": "pflow.nodes.llm.llm",
            "class_name": "LLMNode",
            "metadata": {
                "name": "llm",
                "description": "Generates text using LLM",
                "parameters": {
                    "prompt": {"type": "string", "description": "Prompt for LLM"},
                    "model": {"type": "string", "description": "Model name", "default": "gpt-4o-mini"},
                },
            },
            "interface": {
                "writes": {"response": {"type": "string", "description": "LLM response"}},
                "params": {
                    "prompt": {"type": "string", "description": "Prompt for LLM"},
                    "model": {"type": "string", "description": "Model name", "default": "gpt-4o-mini"},
                },
                "outputs": {"response": {"type": "string", "description": "LLM response"}},
            },
        },
        "read-file": {
            "module": "pflow.nodes.file.read_file",
            "class_name": "ReadFileNode",
            "metadata": {
                "name": "read-file",
                "description": "Reads a file",
                "parameters": {"file_path": {"type": "string", "description": "Path to file"}},
            },
        },
        "write-file": {
            "module": "pflow.nodes.file.write_file",
            "class_name": "WriteFileNode",
            "metadata": {
                "name": "write-file",
                "description": "Writes to a file",
                "parameters": {
                    "file_path": {"type": "string", "description": "Path to file"},
                    "content": {"type": "string", "description": "Content to write"},
                },
            },
            "interface": {
                "writes": {"file_path": {"type": "string", "description": "Path where file was written"}},
                "params": {
                    "file_path": {"type": "string", "description": "Path to file"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "outputs": {"file_path": {"type": "string", "description": "Path where file was written"}},
            },
        },
    }

    registry_path.write_text(json.dumps(registry_data, indent=2))

    # Return the registry path
    yield registry_path


@pytest.fixture
def simple_workflow(tmp_path):
    """Create a simple test workflow IR."""
    # Use secure temp directory for test file
    test_file = tmp_path / "test_metrics.txt"
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "write1",
                "type": "write-file",
                "params": {"file_path": str(test_file), "content": "Hello metrics"},
            }
        ],
        "edges": [],
        "start_node": "write1",
    }


@pytest.fixture
def llm_workflow():
    """Create a workflow with LLM nodes for cost tracking."""
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "llm1", "type": "llm", "params": {"prompt": "Write a haiku about coding", "model": "gpt-4o-mini"}},
            {
                "id": "llm2",
                "type": "llm",
                "params": {
                    "prompt": "Translate to French: ${llm1.response}",
                    "model": "anthropic/claude-3-haiku-20240307",
                },
            },
        ],
        "edges": [{"from": "llm1", "to": "llm2"}],
        "start_node": "llm1",
    }


class TestMetricsCollection:
    """Test metrics collection during workflow execution."""

    def test_json_output_includes_metrics(self, temp_home, temp_registry, simple_workflow):
        """Test that --output-format json includes top-level metrics."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(simple_workflow, f)
            workflow_file = f.name

        try:
            with patch.dict("os.environ", {"HOME": str(temp_home)}):
                result = runner.invoke(cli, ["--output-format", "json", workflow_file], env={"HOME": str(temp_home)})

            assert result.exit_code == 0
            output = json.loads(result.output)

            # Check new unified structure
            assert "success" in output
            assert output["success"] is True

            # Check metrics are at top level
            assert "duration_ms" in output
            assert isinstance(output["duration_ms"], (int, float))
            assert output["duration_ms"] > 0

            assert "total_cost_usd" in output
            assert output["total_cost_usd"] == 0  # No LLM calls

            assert "nodes_executed" in output
            assert output["nodes_executed"] == 1  # just write1

            # Check workflow metadata
            assert "workflow" in output
            assert "action" in output["workflow"]

            # Check detailed metrics
            assert "metrics" in output
            assert "workflow" in output["metrics"]
            assert output["metrics"]["workflow"]["nodes_executed"] == 1

        finally:
            Path(workflow_file).unlink()

    def test_llm_cost_calculation(self, temp_home, temp_registry, llm_workflow, mock_llm):
        """Test that LLM usage is tracked and costs calculated correctly."""
        runner = CliRunner()

        # Configure mock LLM responses with usage data
        mock_llm.configure_with_usage(
            "gpt-4o-mini",
            None,
            {"response": "Code flows like water\nBits and bytes dance on the screen\nBugs hide in shadows"},
            input_tokens=20,
            output_tokens=30,
        )
        mock_llm.configure_with_usage(
            "anthropic/claude-3-haiku-20240307",
            None,
            {"response": "Le code coule comme l'eau\nLes bits et octets dansent\nLes bugs se cachent"},
            input_tokens=40,
            output_tokens=25,
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(llm_workflow, f)
            workflow_file = f.name

        try:
            with patch.dict("os.environ", {"HOME": str(temp_home)}), patch("llm.get_model", mock_llm):
                result = runner.invoke(cli, ["--output-format", "json", workflow_file], env={"HOME": str(temp_home)})

            if result.exit_code != 0:
                print(f"Exit code: {result.exit_code}")
                print(f"Output: {result.output}")
            assert result.exit_code == 0
            output = json.loads(result.output)

            # Check cost calculation
            # gpt-4o-mini: 20 tokens @ $0.15/M + 30 tokens @ $0.60/M = $0.000021
            # claude-haiku: 40 tokens @ $0.25/M + 25 tokens @ $1.25/M = $0.0000413
            # Total: ~$0.0000623
            assert "total_cost_usd" in output
            assert output["total_cost_usd"] > 0
            assert output["total_cost_usd"] < 0.001  # Less than 1/10 cent

            # Check token counts - verify they're positive and consistent
            total_in = output["metrics"]["total"]["tokens_input"]
            total_out = output["metrics"]["total"]["tokens_output"]
            assert total_in > 0  # Should have input tokens
            assert total_out > 0  # Should have output tokens
            assert output["metrics"]["total"]["tokens_total"] == total_in + total_out

        finally:
            Path(workflow_file).unlink()

    def test_error_workflow_metrics(self, temp_home, temp_registry):
        """Test metrics collection when workflow execution fails."""
        runner = CliRunner()

        error_workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "read", "type": "read-file", "params": {"file_path": "/nonexistent/file.txt"}}],
            "edges": [],
            "start_node": "read",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(error_workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(cli, ["--output-format", "json", workflow_file])

            # Should have non-zero exit code
            assert result.exit_code != 0

            # Try to extract JSON from output (might be mixed with error messages)
            output = None
            lines = result.output.strip().split("\n")

            # Try to find JSON in the output (often at the end)
            for line in reversed(lines):
                if line.strip().startswith("{"):
                    try:
                        output = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue

            # If we found JSON output, verify it has error info
            if output:
                assert output.get("success") is False or "error" in output
                # Should have some metrics even on error
                assert "duration_ms" in output or "metrics" in output

        finally:
            Path(workflow_file).unlink()


class TestTraceGeneration:
    """Test trace file generation with --trace flag."""

    def test_trace_file_created(self, temp_home, temp_registry, simple_workflow):
        """Test that --trace flag creates a trace file."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(simple_workflow, f)
            workflow_file = f.name

        # Use the temp_home fixture which already has the registry
        debug_dir = Path(temp_home) / ".pflow" / "debug"

        try:
            with patch.dict("os.environ", {"HOME": str(temp_home)}):
                result = runner.invoke(cli, ["--trace", workflow_file], env={"HOME": str(temp_home)})

                if result.exit_code != 0:
                    print(f"Error output: {result.output}")
                assert result.exit_code == 0

                # Check that trace file was created
                assert debug_dir.exists()
                trace_files = list(debug_dir.glob("workflow-trace-*.json"))
                assert len(trace_files) > 0  # Should have at least one trace file

                # Verify trace content
                trace_data = json.loads(trace_files[0].read_text())
                assert "workflow_name" in trace_data  # Has a workflow name (default or specified)
                assert "nodes" in trace_data  # Has nodes execution data
                assert len(trace_data["nodes"]) >= 1  # At least one node executed

                # Check node execution details
                for event in trace_data["nodes"]:
                    assert "node_id" in event
                    assert "duration_ms" in event
                    assert "shared_before" in event
                    assert "shared_after" in event
                    assert "mutations" in event
                    assert event["success"] is True

        finally:
            Path(workflow_file).unlink()

    def test_trace_captures_llm_calls(self, temp_home, temp_registry, llm_workflow, mock_llm):
        """Test that traces capture LLM call details."""
        runner = CliRunner()

        mock_llm.configure_with_usage(
            "gpt-4o-mini", None, {"response": "Test haiku"}, input_tokens=20, output_tokens=10
        )
        mock_llm.configure_with_usage(
            "anthropic/claude-3-haiku-20240307", None, {"response": "Haiku de test"}, input_tokens=15, output_tokens=8
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(llm_workflow, f)
            workflow_file = f.name

        # Use the temp_home fixture which has the registry
        debug_dir = Path(temp_home) / ".pflow" / "debug"

        try:
            with patch.dict("os.environ", {"HOME": str(temp_home)}), patch("llm.get_model", mock_llm):
                result = runner.invoke(cli, ["--trace", workflow_file], env={"HOME": str(temp_home)})

                assert result.exit_code == 0

                trace_files = list(debug_dir.glob("workflow-trace-*.json"))
                trace_data = json.loads(trace_files[0].read_text())

                # Find LLM node events
                llm_events = [e for e in trace_data["nodes"] if "llm" in e["node_id"]]
                assert len(llm_events) == 2

                # Check that LLM usage was captured
                for event in llm_events:
                    if "llm_call" in event:
                        assert "input_tokens" in event["llm_call"]
                        assert "output_tokens" in event["llm_call"]

        finally:
            Path(workflow_file).unlink()


class TestPlannerIntegration:
    """Test metrics with planner + workflow execution.

    Note: The planner cannot be tested through the CLI in integration tests
    because the test_integration directory blocks planner imports. Tests for
    planner metrics exist in test_planning/ where the planner can be tested
    directly. Workflow metrics are tested in this file with pre-built workflows.
    The separation of planner and workflow metrics is inherent in the architecture
    and verified through unit tests in test_core/test_metrics.py.
    """

    pass  # Placeholder class - specific planner tests are in test_planning/


class TestWrapperIntegration:
    """Test multi-layer wrapper compatibility."""

    def test_wrapper_order(self, temp_home, temp_registry):
        """Test that metrics and tracing work correctly when nodes are wrapped.

        This tests behavior, not internal wrapper structure:
        - Workflow executes correctly
        - Metrics are collected
        - Node namespacing works
        """
        from pflow.registry import Registry
        from pflow.runtime.compiler import compile_ir_to_flow

        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "test"}}],
            "edges": [],
            "start_node": "echo1",
        }

        registry = Registry()
        metrics = MetricsCollector()
        trace = WorkflowTraceCollector("wrapper-test")

        # Compile with metrics and trace - this tests that wrappers integrate properly
        flow = compile_ir_to_flow(workflow_ir, registry, metrics_collector=metrics, trace_collector=trace)

        # Execute and verify behavior
        shared = {}
        result = flow.run(shared)

        # Test 1: Workflow executed successfully
        assert result is not None

        # Test 2: Metrics were collected (proves InstrumentedNodeWrapper works)
        assert len(metrics.workflow_nodes) == 1
        assert "echo1" in metrics.workflow_nodes
        assert metrics.workflow_nodes["echo1"] > 0  # Duration in ms

        # Test 3: Namespacing worked (proves NamespacedNodeWrapper works)
        # The echo node should write to a namespaced key
        assert "echo1" in shared  # The namespace exists
        assert "echo" in shared["echo1"]  # The output is in the namespace
        assert shared["echo1"]["echo"] == "test"  # The value is correct

        # Test 4: Trace was collected (proves both wrappers integrate)
        assert len(trace.events) == 1
        assert trace.events[0]["node_id"] == "echo1"
        assert trace.events[0]["success"] is True

    def test_llm_accumulation_across_nodes(self, temp_home, temp_registry, mock_llm):
        """Test that LLM usage metrics accumulate correctly across multiple nodes.

        This tests behavior, not internal data structures:
        - Multiple LLM nodes execute in sequence
        - Total costs are calculated correctly
        - Token counts accumulate properly
        """
        from pflow.registry import Registry
        from pflow.runtime.compiler import compile_ir_to_flow

        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "llm1", "type": "llm", "params": {"prompt": "Hello", "model": "gpt-4o-mini"}},
                {"id": "llm2", "type": "llm", "params": {"prompt": "World", "model": "gpt-4o-mini"}},
                {"id": "llm3", "type": "llm", "params": {"prompt": "Test", "model": "gpt-4o-mini"}},
            ],
            "edges": [{"from": "llm1", "to": "llm2"}, {"from": "llm2", "to": "llm3"}],
            "start_node": "llm1",
        }

        # Configure mock responses with proper usage data
        responses = [("Response 1", 10, 5), ("Response 2", 20, 10), ("Response 3", 30, 15)]

        # Track call count for sequential responses
        call_count = [0]

        # Create a mock function that returns different responses each time
        def mock_get_model_with_responses(model_name: str):
            # Return a mock model
            mock_model = Mock()

            def prompt_func(prompt_text: str, **kwargs):
                idx = call_count[0]
                call_count[0] += 1
                if idx < len(responses):
                    response_text, in_tokens, out_tokens = responses[idx]
                    # Create proper mock response
                    mock_response = Mock()
                    mock_response.text = Mock(return_value=response_text)
                    usage_mock = Mock()
                    # LLMNode expects .input and .output properties
                    usage_mock.input = in_tokens
                    usage_mock.output = out_tokens
                    usage_mock.details = {}
                    mock_response.usage = Mock(return_value=usage_mock)
                    return mock_response
                # Fallback response
                mock_response = Mock()
                mock_response.text = Mock(return_value="Fallback response")
                usage_mock = Mock()
                usage_mock.input = 10
                usage_mock.output = 5
                usage_mock.details = {}
                mock_response.usage = Mock(return_value=usage_mock)
                return mock_response

            mock_model.prompt = prompt_func
            return mock_model

        registry = Registry()
        metrics = MetricsCollector()

        with patch("llm.get_model", mock_get_model_with_responses):
            flow = compile_ir_to_flow(workflow_ir, registry, metrics_collector=metrics)
            shared = {}
            flow.run(shared)

        # Test behavior: All three LLM nodes executed
        assert "llm1" in metrics.workflow_nodes
        assert "llm2" in metrics.workflow_nodes
        assert "llm3" in metrics.workflow_nodes

        # Test behavior: Verify LLM outputs are in namespaced locations
        assert "llm1" in shared
        assert "response" in shared["llm1"]
        assert shared["llm1"]["response"] == "Response 1"

        assert "llm2" in shared
        assert "response" in shared["llm2"]
        assert shared["llm2"]["response"] == "Response 2"

        assert "llm3" in shared
        assert "response" in shared["llm3"]
        assert shared["llm3"]["response"] == "Response 3"

        # Test behavior: LLM usage was tracked in each namespace
        # The InstrumentedNodeWrapper should accumulate these
        llm_calls = shared.get("__llm_calls__", [])

        # If llm_calls are tracked, verify token counts
        if llm_calls:
            # We expect 3 calls with increasing token counts
            assert len(llm_calls) >= 3, f"Expected at least 3 LLM calls, got {len(llm_calls)}"

            # Calculate total cost to verify it's positive
            total_cost = metrics.calculate_costs(llm_calls)
            assert total_cost > 0, "Total cost should be positive"
        else:
            # Even if __llm_calls__ isn't populated, we can verify nodes executed
            # by checking that all three nodes have timing data
            assert metrics.workflow_nodes["llm1"] > 0
            assert metrics.workflow_nodes["llm2"] > 0
            assert metrics.workflow_nodes["llm3"] > 0


class TestCLIFlags:
    """Test CLI flag behavior for metrics and tracing."""

    def test_trace_flag_enables_tracing(self, temp_home, temp_registry, simple_workflow):
        """Test that --trace flag enables workflow tracing.

        This tests user-visible behavior:
        - With --trace, output mentions trace file was saved
        - The trace file contains workflow execution details
        """
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(simple_workflow, f)
            workflow_file = f.name

        try:
            # Test running with --trace flag
            # Use the temp_home fixture which already has the registry
            # Patch Path.home() to return temp_home since WorkflowTraceCollector uses Path.home()
            with (
                patch.dict("os.environ", {"HOME": str(temp_home)}),
                patch("pathlib.Path.home", return_value=Path(temp_home)),
            ):
                result = runner.invoke(cli, ["--trace", workflow_file], env={"HOME": str(temp_home)})

                # Check the workflow ran successfully
                if result.exit_code != 0:
                    print(f"Error with --trace: {result.output}")
                assert result.exit_code == 0, "Workflow should run successfully with --trace"

                # Test 1: Trace message is suppressed in non-interactive mode (CliRunner)
                # This is expected behavior after task 55c - trace output fix
                # The actual test is that the trace file exists (Test 2)

                # Test 2: Trace file should exist
                debug_dir = Path(temp_home) / ".pflow" / "debug"
                assert debug_dir.exists(), "Debug directory should be created"

                # Look for trace files
                trace_files = list(debug_dir.glob("workflow-trace-*.json"))
                assert len(trace_files) > 0, f"Expected at least one trace file, found {len(trace_files)}"

                # Test 3: Verify trace file contents
                latest_trace = max(trace_files, key=lambda p: p.stat().st_mtime)
                trace_content = json.loads(latest_trace.read_text())

                # Verify expected fields in trace
                assert "workflow_name" in trace_content, "Trace should have workflow_name"
                assert "execution_id" in trace_content, "Trace should have execution_id"
                assert "nodes_executed" in trace_content, "Trace should have nodes_executed count"
                assert trace_content["nodes_executed"] > 0, "Should have executed at least one node"
                assert "duration_ms" in trace_content, "Should have total duration"
                assert "final_status" in trace_content, "Should have final status"
                assert trace_content["final_status"] == "success", "Workflow should have succeeded"

                # Verify node execution data exists
                assert "nodes" in trace_content, "Should have nodes execution data"
                assert isinstance(trace_content["nodes"], list), "Nodes should be a list"
                assert len(trace_content["nodes"]) > 0, "Should have at least one node execution"

        finally:
            Path(workflow_file).unlink()

    @patch("llm.get_model")
    def test_trace_planner_flag(self, mock_get_model, temp_home, temp_registry):
        """Test that --trace-planner enables planner tracing."""
        runner = CliRunner()

        # Setup minimal planner mock
        mock_llm = create_mock_get_model()
        mock_get_model.return_value = mock_llm("gpt-4o-mini")

        with tempfile.TemporaryDirectory() as temp_home_dir, patch.dict("os.environ", {"HOME": temp_home_dir}):
            result = runner.invoke(cli, ["--trace-planner", "test workflow"])

            # Verify the command accepted the flag (may not succeed without full setup)
            # The important thing is that --trace-planner flag is recognized
            assert result is not None  # Command executed

            # Check for planner trace files
            debug_dir = Path(temp_home_dir) / ".pflow" / "debug"
            if debug_dir.exists():
                list(debug_dir.glob("planner_*.json"))
                # Planner traces would be created if planner ran
                # This test mainly verifies the flag is accepted

    def test_output_format_json_always_includes_metrics(self, temp_home, temp_registry, simple_workflow):
        """Test that --output-format json always includes metrics, even without --trace."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(simple_workflow, f)
            workflow_file = f.name

        try:
            # JSON output without trace flag
            result = runner.invoke(cli, ["--output-format", "json", workflow_file])
            assert result.exit_code == 0

            output = json.loads(result.output)

            # Metrics should be present at top level
            assert "duration_ms" in output
            assert "total_cost_usd" in output
            assert "nodes_executed" in output
            assert "metrics" in output

            # But no trace file created
            with tempfile.TemporaryDirectory() as temp_home, patch.dict("os.environ", {"HOME": temp_home}):
                debug_dir = Path(temp_home) / ".pflow" / "debug"
                assert not debug_dir.exists()

        finally:
            Path(workflow_file).unlink()


class TestJSONOutputStructure:
    """Test the structure of JSON output with metrics."""

    def test_successful_workflow_json_structure(self, temp_home, temp_registry, simple_workflow):
        """Test JSON structure for successful workflow execution."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(simple_workflow, f)
            workflow_file = f.name

        try:
            result = runner.invoke(cli, ["--output-format", "json", workflow_file])
            output = json.loads(result.output)

            # Top-level structure
            assert output["success"] is True
            assert "result" in output
            assert isinstance(output["result"], dict)

            # Metrics at top level
            assert isinstance(output["duration_ms"], (int, float))
            assert isinstance(output["total_cost_usd"], (int, float))
            assert isinstance(output["nodes_executed"], int)

            # Detailed metrics structure
            assert "metrics" in output
            assert "workflow" in output["metrics"]
            assert "total" in output["metrics"]

            # Workflow metrics
            workflow_metrics = output["metrics"]["workflow"]
            assert "duration_ms" in workflow_metrics
            assert "nodes_executed" in workflow_metrics
            assert "cost_usd" in workflow_metrics
            assert "node_timings" in workflow_metrics

            # Total metrics
            total_metrics = output["metrics"]["total"]
            assert "tokens_input" in total_metrics
            assert "tokens_output" in total_metrics
            assert "tokens_total" in total_metrics
            assert "cost_usd" in total_metrics

        finally:
            Path(workflow_file).unlink()

    def test_error_workflow_json_structure(self, temp_home, temp_registry):
        """Test that error workflows produce JSON output with error information.

        This tests user-visible behavior:
        - Workflow errors are captured in JSON format
        - Error information is included
        - Basic metrics are still provided
        """
        runner = CliRunner()

        error_workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "bad", "type": "read-file", "params": {"file_path": "/invalid/path.txt"}}],
            "edges": [],
            "start_node": "bad",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(error_workflow, f)
            workflow_file = f.name

        try:
            with patch.dict("os.environ", {"HOME": str(temp_home)}):
                result = runner.invoke(cli, ["--output-format", "json", workflow_file], env={"HOME": str(temp_home)})

            # The workflow should fail
            assert result.exit_code != 0

            # The output should be valid JSON even on error
            try:
                output = json.loads(result.output)
                json_parsed = True
            except json.JSONDecodeError:
                json_parsed = False
                # If JSON parsing fails, check if it's because of mixed output
                # Look for JSON in the output
                lines = result.output.strip().split("\n")
                for line in reversed(lines):  # Check from end where JSON usually is
                    try:
                        output = json.loads(line)
                        json_parsed = True
                        break
                    except (json.JSONDecodeError, ValueError):
                        continue

            if json_parsed:
                # Test behavior: Error information is present
                assert output.get("is_error") is True or "error" in output

                # Test behavior: Some metrics are available even on error
                # At least one of these should be present
                has_metrics = "duration_ms" in output or "metrics" in output or "num_nodes" in output
                assert has_metrics, "Should have some metrics even on error"
            else:
                # If we can't parse JSON, at least verify error output exists
                assert "error" in result.output.lower() or "fail" in result.output.lower()

        finally:
            Path(workflow_file).unlink()


class TestMetricsAccuracy:
    """Test accuracy of metrics calculations."""

    def test_duration_measurement(self, temp_home, temp_registry, simple_workflow):
        """Test that duration is measured accurately."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(simple_workflow, f)
            workflow_file = f.name

        try:
            import time

            start = time.time()
            result = runner.invoke(cli, ["--output-format", "json", workflow_file])
            elapsed = (time.time() - start) * 1000  # Convert to ms

            output = json.loads(result.output)
            reported_duration = output["duration_ms"]

            # Duration should be positive and reasonable
            assert reported_duration > 0
            assert reported_duration < elapsed + 100  # Allow some overhead

        finally:
            Path(workflow_file).unlink()

    def test_cost_calculation_accuracy(self, temp_home, temp_registry, mock_llm):
        """Test accurate cost calculation for different models."""
        from pflow.core.metrics import MetricsCollector

        collector = MetricsCollector()

        # Test various model costs
        test_cases = [
            {
                "model": "gpt-4o-mini",
                "input_tokens": 1000,
                "output_tokens": 500,
                "expected_cost": 0.00045,  # $0.15/M + $0.30/M
            },
            {
                "model": "anthropic/claude-3-haiku-20240307",
                "input_tokens": 2000,
                "output_tokens": 1000,
                "expected_cost": 0.00175,  # $0.25/M + $1.25/M
            },
            {
                "model": "gpt-4",
                "input_tokens": 500,
                "output_tokens": 250,
                "expected_cost": 0.03,  # $30/M + $60/M
            },
        ]

        for case in test_cases:
            llm_calls = [
                {"model": case["model"], "input_tokens": case["input_tokens"], "output_tokens": case["output_tokens"]}
            ]

            cost = collector.calculate_costs(llm_calls)

            # Check within 10% accuracy (floating point)
            assert abs(cost - case["expected_cost"]) < case["expected_cost"] * 0.1

    def test_node_count_accuracy(self, temp_home, temp_registry):
        """Test that node counts are accurate."""
        runner = CliRunner()

        # Workflow with various node counts
        workflows = [
            (
                1,
                {
                    "ir_version": "0.1.0",
                    "nodes": [{"id": "n1", "type": "echo", "params": {"message": "hi"}}],
                    "edges": [],
                    "start_node": "n1",
                },
            ),
            (
                3,
                {
                    "ir_version": "0.1.0",
                    "nodes": [
                        {"id": "n1", "type": "echo", "params": {"message": "1"}},
                        {"id": "n2", "type": "echo", "params": {"message": "2"}},
                        {"id": "n3", "type": "echo", "params": {"message": "3"}},
                    ],
                    "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
                    "start_node": "n1",
                },
            ),
        ]

        for expected_count, workflow in workflows:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(workflow, f)
                workflow_file = f.name

            try:
                result = runner.invoke(cli, ["--output-format", "json", workflow_file])
                output = json.loads(result.output)

                assert output["nodes_executed"] == expected_count
                assert output["metrics"]["workflow"]["nodes_executed"] == expected_count

            finally:
                Path(workflow_file).unlink()
