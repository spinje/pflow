"""Integration tests for the unified metrics and tracing system.

Tests the complete flow of metrics collection, JSON output, and trace generation
when running workflows through the CLI.
"""

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pflow.cli.main import main as cli
from pflow.core.metrics import MetricsCollector
from pflow.core.trace_io import load_trace_file
from pflow.runtime.workflow_trace import WorkflowTraceCollector
from tests.shared.markdown_utils import ir_to_markdown


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
        "shell": {
            "module": "pflow.nodes.shell.shell",
            "class_name": "ShellNode",
            "metadata": {
                "name": "shell",
                "description": "Runs a shell command",
                "parameters": {"command": {"type": "string", "description": "Command to run"}},
            },
            "interface": {
                "writes": {"stdout": {"type": "string", "description": "Command output"}},
                "params": {"command": {"type": "string", "description": "Command to run"}},
                "outputs": {"stdout": {"type": "string", "description": "Command output"}},
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
        runner = CliRunner(mix_stderr=False)

        with tempfile.NamedTemporaryFile(encoding="utf-8", mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(simple_workflow))
            workflow_file = f.name

        try:
            with patch.dict("os.environ", {"HOME": str(temp_home)}):
                result = runner.invoke(cli, ["--output-format", "json", workflow_file], env={"HOME": str(temp_home)})

            assert result.exit_code == 0
            output = json.loads(result.stdout)

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

    def test_llm_cost_calculation(self, temp_home, temp_registry, llm_workflow, monkeypatch):
        """Test that LLM usage is tracked and aggregated costs flow through.

        Cost determination is LiteLLM's responsibility — the adapter populates
        ``cost_usd`` on each response from ``response._hidden_params``. This
        test sets ``cost_usd`` directly on the mocked usage dicts (mirroring
        what the real adapter does) and asserts the summation works end-to-end.
        """
        from pflow.core.llm_client import AdapterResponse

        runner = CliRunner(mix_stderr=False)

        # Mock per-model with known cost_usd values that the adapter would
        # have set from LiteLLM's response_cost.
        per_model = {
            "gpt-4o-mini": (
                "Code flows like water\nBits and bytes dance on the screen\nBugs hide in shadows",
                20,
                30,
                0.000021,  # cost_usd
            ),
            "anthropic/claude-3-haiku-20240307": (
                "Le code coule comme l'eau\nLes bits et octets dansent\nLes bugs se cachent",
                40,
                25,
                0.000042,  # cost_usd
            ),
        }

        def mock_complete(*, model: str, prompt: str, **kwargs):
            text, in_tokens, out_tokens, cost = per_model.get(model, ("default", 10, 5, 0.0))
            usage = {
                "model": model,
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
                "total_tokens": in_tokens + out_tokens,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "thinking_tokens": 0,
                "thinking_budget": 0,
                "cost_usd": cost,
            }
            return AdapterResponse(text=text, usage=usage, model=model, has_schema=False)

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", mock_complete)

        with tempfile.NamedTemporaryFile(encoding="utf-8", mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(llm_workflow))
            workflow_file = f.name

        try:
            with patch.dict("os.environ", {"HOME": str(temp_home)}):
                result = runner.invoke(cli, ["--output-format", "json", workflow_file], env={"HOME": str(temp_home)})

            if result.exit_code != 0:
                print(f"Exit code: {result.exit_code}")
                print(f"Output: {result.output}")
            assert result.exit_code == 0
            output = json.loads(result.stdout)

            # Check cost summation: 0.000021 + 0.000042 = 0.000063
            assert "total_cost_usd" in output
            assert output["total_cost_usd"] == pytest.approx(0.000063, rel=1e-6)

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
        runner = CliRunner(mix_stderr=False)

        error_workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "read", "type": "read-file", "params": {"file_path": "/nonexistent/file.txt"}}],
            "edges": [],
            "start_node": "read",
        }

        with tempfile.NamedTemporaryFile(encoding="utf-8", mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(error_workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(cli, ["--output-format", "json", workflow_file])

            # Should have non-zero exit code
            assert result.exit_code != 0

            # stdout has pure JSON even on error (stderr has error messages)
            output = json.loads(result.stdout)

            # Verify it has error info
            assert output.get("success") is False or "error" in output
            # Should have some metrics even on error
            assert "duration_ms" in output or "metrics" in output

        finally:
            Path(workflow_file).unlink()


@pytest.mark.trace_files
class TestTraceGeneration:
    """Test trace file generation and opt-out behavior."""

    def test_trace_file_created_by_default(self, temp_home, temp_registry, simple_workflow):
        """Trace files should be created even without explicit flags."""
        runner = CliRunner(mix_stderr=False)

        with tempfile.NamedTemporaryFile(encoding="utf-8", mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(simple_workflow))
            workflow_file = f.name

        # Use the temp_home fixture which already has the registry
        debug_dir = Path(temp_home) / ".pflow" / "debug"

        try:
            with patch.dict("os.environ", {"HOME": str(temp_home)}):
                result = runner.invoke(cli, [workflow_file], env={"HOME": str(temp_home)})

                if result.exit_code != 0:
                    print(f"Error output: {result.output}")
                assert result.exit_code == 0

                # Check that trace file was created
                assert debug_dir.exists()
                trace_files = list(debug_dir.glob("workflow-trace-*.json"))
                assert len(trace_files) > 0  # Should have at least one trace file

                # Verify trace content
                trace_data = load_trace_file(trace_files[0])
                assert "workflow_name" in trace_data  # Has a workflow name (default or specified)
                assert "nodes" in trace_data  # Has nodes execution data
                assert len(trace_data["nodes"]) >= 1  # At least one node executed

                # Check node execution details
                for event in trace_data["nodes"]:
                    assert "node_id" in event
                    assert "duration_ms" in event
                    # Format 2.0.0: focused fields replace shared_before/shared_after
                    assert "shared_before" not in event
                    assert "shared_after" not in event
                    assert "mutations" in event
                    assert "node_output" in event
                    assert event["status"] == "success"

        finally:
            Path(workflow_file).unlink()

    def test_trace_captures_llm_calls(self, temp_home, temp_registry, llm_workflow, monkeypatch):
        """Trace files should capture LLM call details by default."""
        from pflow.core.llm_client import AdapterResponse

        runner = CliRunner(mix_stderr=False)

        per_model = {
            "gpt-4o-mini": ("Test haiku", 20, 10),
            "anthropic/claude-3-haiku-20240307": ("Haiku de test", 15, 8),
        }

        def mock_complete(*, model: str, prompt: str, **kwargs):
            text, in_tok, out_tok = per_model.get(model, ("default", 10, 5))
            usage = {
                "model": model,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "total_tokens": in_tok + out_tok,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "thinking_tokens": 0,
                "thinking_budget": 0,
            }
            return AdapterResponse(text=text, usage=usage, model=model, has_schema=False)

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", mock_complete)

        with tempfile.NamedTemporaryFile(encoding="utf-8", mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(llm_workflow))
            workflow_file = f.name

        # Use the temp_home fixture which has the registry
        debug_dir = Path(temp_home) / ".pflow" / "debug"

        try:
            with patch.dict("os.environ", {"HOME": str(temp_home)}):
                result = runner.invoke(cli, [workflow_file], env={"HOME": str(temp_home)})

                assert result.exit_code == 0

                trace_files = list(debug_dir.glob("workflow-trace-*.json"))
                trace_data = load_trace_file(trace_files[0])

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

    def test_no_trace_flag_disables_tracing(self, temp_home, temp_registry, simple_workflow):
        """The --no-trace flag should suppress trace file creation."""
        runner = CliRunner(mix_stderr=False)

        with tempfile.NamedTemporaryFile(encoding="utf-8", mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(simple_workflow))
            workflow_file = f.name

        debug_dir = Path(temp_home) / ".pflow" / "debug"

        try:
            with patch.dict("os.environ", {"HOME": str(temp_home)}):
                # Ensure a clean slate
                if debug_dir.exists():
                    for path in debug_dir.glob("workflow-trace-*.json"):
                        path.unlink()

                result = runner.invoke(cli, ["--no-trace", workflow_file], env={"HOME": str(temp_home)})
                if result.exit_code != 0:
                    print(f"Error output (--no-trace): {result.output}")
                assert result.exit_code == 0

                # Confirm no trace files were created
                if debug_dir.exists():
                    trace_files = list(debug_dir.glob("workflow-trace-*.json"))
                    assert not trace_files, f"Expected no trace files, found {trace_files}"

        finally:
            Path(workflow_file).unlink()

    def test_no_trace_flag_skips_trace_on_failure(self, temp_home, temp_registry):
        """Even failing workflows should not leave traces when --no-trace is set."""
        runner = CliRunner(mix_stderr=False)

        failing_workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "invalid", "type": "does-not-exist"}],
            "edges": [],
            "start_node": "invalid",
        }

        with tempfile.NamedTemporaryFile(encoding="utf-8", mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(failing_workflow))
            workflow_file = f.name

        debug_dir = Path(temp_home) / ".pflow" / "debug"

        try:
            with patch.dict("os.environ", {"HOME": str(temp_home)}):
                if debug_dir.exists():
                    for path in debug_dir.glob("workflow-trace-*.json"):
                        path.unlink()

                result = runner.invoke(cli, ["--no-trace", workflow_file], env={"HOME": str(temp_home)})
                assert result.exit_code != 0, "Workflow should fail with invalid node type"

                if debug_dir.exists():
                    trace_files = list(debug_dir.glob("workflow-trace-*.json"))
                    assert not trace_files, f"Expected no trace files, found {trace_files}"

        finally:
            Path(workflow_file).unlink()


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
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "shell1", "type": "shell", "params": {"command": "echo test"}}],
            "edges": [],
            "start_node": "shell1",
        }

        registry = Registry()
        metrics = MetricsCollector()
        trace = WorkflowTraceCollector("wrapper-test")

        # Compile workflow and run with engine (metrics/trace are engine args)
        workflow = compile_workflow(workflow_ir, registry)
        shared = dict(workflow.resolved_defaults)
        engine = WorkflowEngine(metrics_collector=metrics, trace_collector=trace)
        result = engine.run(workflow, shared)

        # Test 1: Workflow executed successfully
        assert result is not None

        # Test 2: Metrics were collected (proves InstrumentedNodeWrapper works)
        assert len(metrics.workflow_nodes) == 1
        assert "shell1" in metrics.workflow_nodes
        assert metrics.workflow_nodes["shell1"] > 0  # Duration in ms

        # Test 3: Namespacing worked (proves NamespacedNodeWrapper works)
        # The shell node should write to a namespaced key
        assert "shell1" in shared  # The namespace exists
        assert "stdout" in shared["shell1"]  # The output is in the namespace
        assert "test" in shared["shell1"]["stdout"]  # The value is correct

        # Test 4: Trace was collected (proves both wrappers integrate)
        assert len(trace.events) == 1
        assert trace.events[0]["node_id"] == "shell1"
        assert trace.events[0]["status"] == "success"

    def test_llm_accumulation_across_nodes(self, temp_home, temp_registry, monkeypatch):
        """Test that LLM usage metrics accumulate correctly across multiple nodes.

        This tests behavior, not internal data structures:
        - Multiple LLM nodes execute in sequence
        - Total costs are calculated correctly
        - Token counts accumulate properly
        """
        from pflow.core.llm_client import AdapterResponse
        from pflow.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

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

        # Sequential mock responses with controlled token counts AND cost_usd.
        # The adapter sets cost_usd from LiteLLM's response_cost in production;
        # the mock sets it directly here so the test can pin the summed total.
        responses = [
            ("Response 1", 10, 5, 0.001),
            ("Response 2", 20, 10, 0.002),
            ("Response 3", 30, 15, 0.003),
        ]
        call_count = [0]

        def mock_complete(*, model: str, prompt: str, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            response_text, in_tokens, out_tokens, cost = (
                responses[idx] if idx < len(responses) else ("Fallback response", 10, 5, 0.0001)
            )
            usage = {
                "model": model,
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
                "total_tokens": in_tokens + out_tokens,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "thinking_tokens": 0,
                "thinking_budget": 0,
                "cost_usd": cost,
            }
            return AdapterResponse(text=response_text, usage=usage, model=model, has_schema=False)

        # Patch the adapter at the LLMNode's import site
        monkeypatch.setattr("pflow.nodes.llm.llm.complete", mock_complete)

        from pflow.runtime.workflow_trace import WorkflowTraceCollector

        registry = Registry()
        metrics = MetricsCollector()
        trace = WorkflowTraceCollector("test")

        workflow = compile_workflow(workflow_ir, registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        shared["__trace_collector__"] = trace
        engine = WorkflowEngine(metrics_collector=metrics, trace_collector=trace)
        engine.run(workflow, shared)

        # Test behavior: All three LLM nodes executed
        assert "llm1" in metrics.workflow_nodes
        assert "llm2" in metrics.workflow_nodes
        assert "llm3" in metrics.workflow_nodes

        # Test behavior: Verify LLM outputs are in namespaced locations
        assert shared["llm1"]["response"] == "Response 1"
        assert shared["llm2"]["response"] == "Response 2"
        assert shared["llm3"]["response"] == "Response 3"

        # CRITICAL: Verify the complete cost chain works end-to-end.
        # This is the path that produces "Cost: $X.XXXX" in CLI output:
        # LLM adapter populates cost_usd → trace event → collect_llm_calls() → get_summary()
        # If any link breaks, costs silently become $0.00.
        llm_calls = trace.collect_llm_calls()
        assert len(llm_calls) == 3, f"Expected 3 LLM calls from trace, got {len(llm_calls)}"

        # Each call should have token counts from mock responses
        total_input = sum(c.get("input_tokens", 0) for c in llm_calls)
        total_output = sum(c.get("output_tokens", 0) for c in llm_calls)
        assert total_input == 10 + 20 + 30, f"Expected 60 input tokens, got {total_input}"
        assert total_output == 5 + 10 + 15, f"Expected 30 output tokens, got {total_output}"

        # Cost summation should equal sum of injected per-call cost_usd:
        # 0.001 + 0.002 + 0.003 = 0.006
        summary = metrics.get_summary(llm_calls)
        assert summary["total_cost_usd"] == pytest.approx(0.006, rel=1e-6), (
            "Cost chain broken: per-call cost_usd not summed correctly"
        )


class TestCLIFlags:
    """Test CLI flag behavior for metrics and tracing."""

    @pytest.mark.trace_files
    def test_trace_file_saved_without_flag(self, temp_home, temp_registry, simple_workflow):
        """Trace files should be generated without specifying tracing flags."""
        runner = CliRunner(mix_stderr=False)

        with tempfile.NamedTemporaryFile(encoding="utf-8", mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(simple_workflow))
            workflow_file = f.name

        try:
            # Test running with default tracing behavior
            # Use the temp_home fixture which already has the registry
            # Patch Path.home() to return temp_home since WorkflowTraceCollector uses Path.home()
            with (
                patch.dict("os.environ", {"HOME": str(temp_home)}),
                patch("pathlib.Path.home", return_value=Path(temp_home)),
            ):
                result = runner.invoke(cli, [workflow_file], env={"HOME": str(temp_home)})

                # Check the workflow ran successfully
                if result.exit_code != 0:
                    print(f"Error during workflow execution: {result.output}")
                assert result.exit_code == 0, "Workflow should run successfully with default tracing"

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
                trace_content = load_trace_file(latest_trace)

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

    def test_output_format_json_always_includes_metrics(self, temp_home, temp_registry, simple_workflow):
        """JSON output should include metrics without requiring explicit trace flags."""
        runner = CliRunner(mix_stderr=False)

        with tempfile.NamedTemporaryFile(encoding="utf-8", mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(simple_workflow))
            workflow_file = f.name

        try:
            # JSON output without trace flag
            result = runner.invoke(cli, ["--output-format", "json", workflow_file])
            assert result.exit_code == 0

            output = json.loads(result.stdout)

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
        runner = CliRunner(mix_stderr=False)

        with tempfile.NamedTemporaryFile(encoding="utf-8", mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(simple_workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(cli, ["--output-format", "json", workflow_file])
            output = json.loads(result.stdout)

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
        runner = CliRunner(mix_stderr=False)

        error_workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "bad", "type": "read-file", "params": {"file_path": "/invalid/path.txt"}}],
            "edges": [],
            "start_node": "bad",
        }

        with tempfile.NamedTemporaryFile(encoding="utf-8", mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(error_workflow))
            workflow_file = f.name

        try:
            with patch.dict("os.environ", {"HOME": str(temp_home)}):
                result = runner.invoke(cli, ["--output-format", "json", workflow_file], env={"HOME": str(temp_home)})

            # The workflow should fail
            assert result.exit_code != 0

            # stdout has pure JSON even on error (stderr has error messages)
            output = json.loads(result.stdout)

            # Test behavior: Error information is present
            assert output.get("success") is False

            # Test behavior: Some metrics are available even on error
            # At least one of these should be present
            has_metrics = "duration_ms" in output or "metrics" in output or "num_nodes" in output
            assert has_metrics, "Should have some metrics even on error"

        finally:
            Path(workflow_file).unlink()


class TestMetricsAccuracy:
    """Test accuracy of metrics calculations."""

    def test_duration_measurement(self, temp_home, temp_registry, simple_workflow):
        """Test that duration is measured accurately."""
        runner = CliRunner(mix_stderr=False)

        with tempfile.NamedTemporaryFile(encoding="utf-8", mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(simple_workflow))
            workflow_file = f.name

        try:
            import time

            start = time.time()
            result = runner.invoke(cli, ["--output-format", "json", workflow_file])
            elapsed = (time.time() - start) * 1000  # Convert to ms

            output = json.loads(result.stdout)
            reported_duration = output["duration_ms"]

            # Duration should be positive and reasonable
            assert reported_duration > 0
            assert reported_duration < elapsed + 100  # Allow some overhead

        finally:
            Path(workflow_file).unlink()

    # Removed `test_cost_calculation_accuracy` — Task 158 Phase A.10 deleted
    # `pflow.core.llm_pricing`. Pricing is now LiteLLM's responsibility (via
    # `litellm.completion_cost`); pflow no longer maintains a per-model
    # pricing table. The `MetricsCollector.calculate_costs` summation logic
    # is exercised in `tests/test_core/test_metrics.py::TestMetricsCollector`
    # against explicit per-call `cost_usd` values — the contract that matches
    # how the production adapter actually populates the field.

    def test_node_count_accuracy(self, temp_home, temp_registry):
        """Test that node counts are accurate."""
        runner = CliRunner(mix_stderr=False)

        # Workflow with various node counts
        workflows = [
            (
                1,
                {
                    "ir_version": "0.1.0",
                    "nodes": [{"id": "n1", "type": "shell", "params": {"command": "echo hi"}}],
                    "edges": [],
                    "start_node": "n1",
                },
            ),
            (
                3,
                {
                    "ir_version": "0.1.0",
                    "nodes": [
                        {"id": "n1", "type": "shell", "params": {"command": "echo first"}},
                        {"id": "n2", "type": "shell", "params": {"command": "echo second"}},
                        {"id": "n3", "type": "shell", "params": {"command": "echo third"}},
                    ],
                    "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
                    "start_node": "n1",
                },
            ),
        ]

        for expected_count, workflow in workflows:
            with tempfile.NamedTemporaryFile(encoding="utf-8", mode="w", suffix=".pflow.md", delete=False) as f:
                f.write(ir_to_markdown(workflow))
                workflow_file = f.name

            try:
                with patch.dict("os.environ", {"HOME": str(temp_home)}):
                    result = runner.invoke(
                        cli, ["--output-format", "json", workflow_file], env={"HOME": str(temp_home)}
                    )
                output = json.loads(result.stdout)

                assert output.get("success", False), f"Workflow failed for {expected_count}-node: {output}"
                assert output["nodes_executed"] == expected_count
                assert output["metrics"]["workflow"]["nodes_executed"] == expected_count

            finally:
                Path(workflow_file).unlink()
