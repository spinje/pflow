"""Tests for workflow output handling in the CLI.

This module contains comprehensive tests for verifying that workflow output
handling works correctly with declared outputs, backward compatibility,
and various edge cases.
"""

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import click.testing
import pytest

from pflow.cli.main import main
from pflow.core.node import BaseNode
from tests.shared.markdown_utils import ir_to_markdown


def make_batch_shape(
    *,
    results: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
    total_items_ms: float | None = 1400.23,
    parallel: bool = True,
) -> dict[str, Any]:
    """Build a realistic batch-aggregate dict matching ``_aggregate_batch_results``.

    Source of truth: ``src/pflow/runtime/engine/batch_executor.py``. Tests that
    use this helper stay in sync as the schema evolves — single update point.
    """
    results = results or []
    error_list = errors or []
    count = len(results) + len(error_list)
    success_count = len(results)
    error_count = len(error_list)
    timing: dict[str, float] | None
    if total_items_ms is not None and count > 0:
        timing = {
            "total_items_ms": total_items_ms,
            "avg_item_ms": total_items_ms / count,
            "min_item_ms": total_items_ms,
            "max_item_ms": total_items_ms,
        }
    else:
        timing = None
    return {
        "results": results,
        "count": count,
        "success_count": success_count,
        "error_count": error_count,
        "errors": error_list if error_list else None,
        "batch_metadata": {
            "parallel": parallel,
            "max_concurrent": 10 if parallel else None,
            "max_retries": 3,
            "retry_wait": None,
            "execution_mode": "parallel" if parallel else "sequential",
            "timing": timing,
        },
    }


class MockOutputNode(BaseNode):
    """Mock node that outputs data to the shared store."""

    def __init__(self):
        self.params = {}

    def set_params(self, params):
        self.params = params

    def run(self, shared):
        """Put test data in the shared store based on params."""
        # Default behavior - put data in test_output
        if "output_key" in self.params:
            shared[self.params["output_key"]] = self.params.get("output_value", "test value")
        else:
            shared["test_output"] = "default test output"

        # If specific keys are requested, add them
        if "add_keys" in self.params:
            for key, value in self.params["add_keys"].items():
                shared[key] = value

        return "success"


@pytest.fixture
def mock_registry():
    """Create a mock registry with test nodes."""
    mock_reg = Mock()

    nodes_data = {
        "test-node": {
            "module": "tests.test_cli.test_workflow_output_handling",
            "class_name": "MockOutputNode",
            "metadata": {"interface": {"inputs": [], "outputs": []}},
        }
    }

    mock_reg.load.return_value = nodes_data
    # Create a mock path object instead of using a real Path
    mock_path = Mock()
    mock_path.exists.return_value = True
    mock_reg.registry_path = mock_path

    def get_nodes_metadata_mock(node_types):
        result = {}
        for node_type in node_types:
            if node_type in nodes_data:
                metadata = nodes_data[node_type].get("metadata", {})
                result[node_type] = {
                    "module": nodes_data[node_type]["module"],
                    "class_name": nodes_data[node_type]["class_name"],
                    "interface": metadata.get("interface", {}),
                }
        return result

    mock_reg.get_nodes_metadata = Mock(side_effect=get_nodes_metadata_mock)

    return mock_reg


@pytest.fixture
def mock_compile():
    """Mock the workflow execution to bypass validation."""
    # Patch at the Runner level to bypass all resolution/validation/compilation
    with patch("pflow.execution.runner.WorkflowRunner.run") as mock_run:
        shared_data = {"last_ir": None}

        def run_mock(workflow, params, config, **kwargs):
            # Store the IR for reference
            shared_data["last_ir"] = workflow
            workflow_ir = workflow.ir if hasattr(workflow, "ir") else workflow

            # Create result with our test node's output
            shared_storage = {}

            # Create and run our test node
            node = MockOutputNode()
            # Extract params from the IR if available
            if isinstance(workflow_ir, dict):
                node_params = workflow_ir.get("nodes", [{}])[0].get("params", {})
                node.set_params(node_params)
            node.run(shared_storage)

            # Create a successful result
            from pflow.execution.result import ExecutionResult

            return ExecutionResult(success=True, diagnostics=[], shared_after=shared_storage)

        mock_run.side_effect = run_mock
        yield mock_run


@pytest.fixture
def mock_validate_ir():
    """Mock IR validation to always pass."""
    with patch("pflow.core.workflow.validator.WorkflowValidator.validate") as mock:
        # Empty list[Diagnostic] indicates validation passed (post task 147)
        mock.return_value = []
        yield mock


@pytest.fixture
def mock_registry_instance(mock_registry):
    """Mock the Registry class instantiation."""
    # Patch Registry at the source module
    with patch("pflow.registry.Registry") as MockRegistry:
        MockRegistry.return_value = mock_registry
        yield MockRegistry


class TestWorkflowOutputHandling:
    """Test workflow output handling functionality."""

    def test_workflow_with_declared_outputs(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that workflow-declared outputs are printed."""
        runner = click.testing.CliRunner(mix_stderr=False)

        # Create a workflow with declared outputs
        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"analysis_result": {"description": "The analysis output", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"output_key": "analysis_result", "output_value": "Analysis complete: All tests passed"},
                }
            ],
        }

        # Save workflow to a temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            # Run the workflow (--file flag removed in Task 22)
            result = runner.invoke(main, [workflow_file])

            # Verify the declared output was printed
            assert result.exit_code == 0
            assert "Analysis complete: All tests passed" in result.output
            # Should NOT print the default success message
            assert "Workflow executed successfully" not in result.output
        finally:
            Path(workflow_file).unlink()

    def test_backward_compatibility_without_declared_outputs(
        self, mock_registry_instance, mock_compile, mock_validate_ir
    ):
        """Test that workflows without declared outputs still work with hardcoded keys."""
        runner = click.testing.CliRunner(mix_stderr=False)

        # Create a workflow WITHOUT declared outputs
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"add_keys": {"response": "This is the response", "some_other_key": "ignored"}},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            # Should fall back to hardcoded keys and find "response"
            assert result.exit_code == 0
            assert "This is the response" in result.output
            assert "Workflow executed successfully" not in result.output
        finally:
            Path(workflow_file).unlink()

    def test_workflow_data_goes_to_stdout_not_stderr_gh194(
        self, mock_registry_instance, mock_compile, mock_validate_ir
    ):
        """Regression for GH #194: workflow data must go to stdout, not stderr."""
        # mix_stderr=False: under click 8.1 (transitive pin from litellm 1.83.x),
        # CliRunner defaults to mix_stderr=True which merges stderr into stdout
        # and defeats the `... not in result.stderr` assertion below. Click 8.2
        # flipped the default; 8.3+ removed the kwarg.
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"result": {"description": "Test result", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "output_key": "result",
                        "output_value": "HELLO_STDOUT_CANARY_GH194",
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            assert result.exit_code == 0, (
                f"Workflow invocation failed.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
            )
            assert "HELLO_STDOUT_CANARY_GH194" in result.stdout
            assert "HELLO_STDOUT_CANARY_GH194" not in result.stderr
            # GH194 invariant: the DATA lives on stdout only (the two asserts
            # above). The "Workflow output (desc):" label is a stderr delimiter —
            # CliRunner captures both streams (the agent case), so under Option B
            # it IS shown on stderr; it just must never carry the data value.
        finally:
            Path(workflow_file).unlink()

    # NOTE: `test_print_mode_suppresses_progress_header_and_summary` and
    # `test_json_mode_suppresses_progress_header_and_summary` were deleted
    # as test theater — both used the `mock_compile` fixture which returns
    # `ExecutionResult(metrics=None)`, and `_emit_summary_or_only_indicator`
    # short-circuits on `if not metrics_collector: return`. The stderr
    # suppression assertions were therefore vacuous — they passed regardless
    # of whether `-p`/JSON mode suppression actually worked.
    #
    # Real coverage lives in `tests/test_cli/test_progress_streaming_subprocess.py`:
    #   - `test_print_mode_without_only_stays_silent` (real subprocess, `-p`)
    #   - `test_print_mode_with_only_emits_indicator` (real subprocess, `-p` + `--only`)
    #   - `test_json_mode_keeps_stderr_silent` (real subprocess, JSON mode)

    def test_output_key_override(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that --output-key flag overrides both declared outputs and hardcoded keys."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"declared_output": {"description": "This should be ignored", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "declared_output": "Declared value",
                            "response": "Response value",
                            "custom_key": "Custom value",
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            # Use --output-key to override and get custom_key
            result = runner.invoke(main, ["--output-key", "custom_key", workflow_file])

            assert result.exit_code == 0
            assert "Custom value" in result.output
            # Should NOT print declared or hardcoded outputs
            assert "Declared value" not in result.output
            assert "Response value" not in result.output
        finally:
            Path(workflow_file).unlink()

    def test_missing_declared_outputs_warning_in_verbose_mode(
        self, mock_registry_instance, mock_compile, mock_validate_ir
    ):
        """Test that verbose mode warns when declared outputs aren't in shared store.

        Uses a single declared output. Multi-declared workflows without a
        ``stdout: true`` marker now raise an ambiguity error BEFORE missing-
        output warnings can fire — tested separately in
        ``test_multi_output_without_marker_raises_ambiguity_error``.
        """
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "expected_output": {"description": "This output is expected but missing", "type": "string"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        # Node doesn't produce the declared output
                        "output_key": "different_key",
                        "output_value": "Some value",
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--verbose", workflow_file])

            assert result.exit_code == 0
            # Should warn about the missing declared output (warning → stderr)
            assert "expected_output" in result.stderr
            assert "but none could be resolved" in result.stderr
            # Stdout stays empty when no output is produced. The stderr
            # summary signals success; stdout is reserved for data so pipe
            # consumers receive a clean stream.
            assert result.output == ""
            assert "Workflow executed successfully" not in result.output
        finally:
            Path(workflow_file).unlink()

    def test_stdout_marked_output_wins_over_unmarked(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Multiple declared outputs + one marked ``stdout: true`` → marked wins.

        Replaces the old "first-wins" behavior, which silently dropped every
        output after the first. The marker makes the author's intent explicit
        and the routing deterministic.
        """
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "primary_output": {"description": "Primary output", "type": "string"},
                "stdout_output": {"description": "Marked for stdout", "type": "string", "stdout": True},
                "trailing_output": {"description": "Trailing output", "type": "string"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "primary_output": "PRIMARY_VALUE_SHOULD_NOT_APPEAR",
                            "stdout_output": "STDOUT_MARKED_VALUE",
                            "trailing_output": "TRAILING_VALUE_SHOULD_NOT_APPEAR",
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            assert result.exit_code == 0, f"stderr: {result.stderr!r}"
            assert "STDOUT_MARKED_VALUE" in result.stdout
            assert "PRIMARY_VALUE_SHOULD_NOT_APPEAR" not in result.stdout
            assert "TRAILING_VALUE_SHOULD_NOT_APPEAR" not in result.stdout
        finally:
            Path(workflow_file).unlink()

    def test_multi_output_without_marker_warns_and_emits_first(
        self, mock_registry_instance, mock_compile, mock_validate_ir
    ):
        """Multiple declared outputs + no ``stdout: true`` + no ``-o`` → warn + emit first.

        The warning names both outputs and the three fixes (`stdout: true`,
        `-o <name>`, `--output-format json`). The first declared output
        streams to stdout so existing callers keep working.
        """
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "alpha": {"description": "First", "type": "string"},
                "beta": {"description": "Second", "type": "string"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"add_keys": {"alpha": "ALPHA_VAL", "beta": "BETA_VAL"}},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            assert result.exit_code == 0, f"stderr: {result.stderr!r}"
            # First declared output reaches stdout
            assert "ALPHA_VAL" in result.stdout
            assert "BETA_VAL" not in result.stdout
            # Warning on stderr names both outputs and the three escape hatches
            assert "Workflow declares 2 outputs" in result.stderr
            assert "alpha" in result.stderr and "beta" in result.stderr
            assert "stdout: true" in result.stderr
            assert "-o" in result.stderr
            assert "--output-format json" in result.stderr
        finally:
            Path(workflow_file).unlink()

    @pytest.mark.trace_files
    def test_real_cli_only_node_uses_target_not_declared_outputs(self, tmp_path):
        """Real CLI regression: --only must not stream full-run declared outputs.

        This uses the parser, runner, engine output population, and CLI output
        formatter together. The shadowing `result` output is intentionally
        sourced from an upstream node; snapshot --only restores it but must still
        stream the requested target, not that root declared output.
        """
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "first_declared": {"description": "Downstream result", "source": "${downstream.stdout}"},
                "result": {"description": "Upstream shadow", "source": "${pre.stdout}"},
            },
            "nodes": [
                {"id": "pre", "type": "shell", "cache": False, "params": {"command": "printf ROOT_SHADOW_VALUE"}},
                {"id": "target", "type": "shell", "cache": False, "params": {"command": "printf TARGET_ONLY_VALUE"}},
                {"id": "downstream", "type": "shell", "cache": False, "params": {"command": "printf DOWNSTREAM_VALUE"}},
            ],
            "edges": [],
        }
        workflow_file = tmp_path / "only-output-contract.pflow.md"
        workflow_file.write_text(ir_to_markdown(workflow))

        # Snapshot --only needs a prior full run to restore upstream from. Trace
        # filenames are microsecond-granular (issue #443), so these rapid full +
        # --only writes don't collide and the seed snapshot survives.
        full = runner.invoke(main, [str(workflow_file)])
        assert full.exit_code == 0, f"full-run stderr: {full.stderr!r}"

        result = runner.invoke(main, [str(workflow_file), "--only", "target"])

        assert result.exit_code == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        assert "TARGET_ONLY_VALUE" in result.stdout
        assert "ROOT_SHADOW_VALUE" not in result.stdout
        assert "DOWNSTREAM_VALUE" not in result.stdout
        assert "Streaming 'first_declared'" not in result.stderr
        assert (
            "cli: --only active — streaming auto-detected key 'stdout' from target 'target' to stdout."
        ) in result.stderr

        explicit = runner.invoke(main, ["-o", "result", str(workflow_file), "--only", "target"])

        assert explicit.exit_code == 0, f"stdout: {explicit.stdout!r}\nstderr: {explicit.stderr!r}"
        assert "ROOT_SHADOW_VALUE" in explicit.stdout
        assert "TARGET_ONLY_VALUE" not in explicit.stdout
        assert "--only active" not in explicit.stderr

    def test_print_only_suppresses_routing_note_but_keeps_only_indicator(self, capsys):
        """-p suppresses the routing note while preserving the --only mode line."""
        from pflow.cli.workflow_output import _handle_text_output
        from pflow.core.metrics import MetricsCollector

        metrics = MetricsCollector()
        metrics.record_workflow_start()
        metrics.record_node_execution("upstream", 1.0)
        metrics.record_workflow_end()

        shared = {
            "__execution__": {"only_node": "upstream"},
            "upstream": {"stdout": "UPSTREAM_TARGET_OUTPUT"},
        }
        workflow_ir = {
            "nodes": [
                {"id": "upstream", "type": "shell", "params": {}},
                {"id": "downstream", "type": "shell", "params": {}},
            ],
        }

        _handle_text_output(
            shared,
            output_key=None,
            workflow_ir=workflow_ir,
            verbose=False,
            print_flag=True,
            metrics_collector=metrics,
        )

        # Behavior under -p + --only: data line on stdout, --only mode
        # indicator on stderr, routing note ("--only active...") suppressed.
        captured = capsys.readouterr()
        assert "UPSTREAM_TARGET_OUTPUT" in captured.out
        assert "--only active" not in captured.err
        assert "⤷ Ran only 'upstream' (--only)" in captured.err

    def test_multi_output_warning_suppressed_under_print_flag(
        self, mock_registry_instance, mock_compile, mock_validate_ir
    ):
        """``-p`` suppresses the multi-output warning, matching Task 134's auto-detect behavior."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "alpha": {"description": "First", "type": "string"},
                "beta": {"description": "Second", "type": "string"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"add_keys": {"alpha": "ALPHA_VAL", "beta": "BETA_VAL"}},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["-p", workflow_file])

            assert result.exit_code == 0
            assert "ALPHA_VAL" in result.stdout
            assert "Workflow declares" not in result.stderr
        finally:
            Path(workflow_file).unlink()

    def test_multi_output_without_marker_json_mode_succeeds(
        self, mock_registry_instance, mock_compile, mock_validate_ir
    ):
        """Regression: ambiguity error is text-mode-only; JSON emits all outputs."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "alpha": {"description": "First", "type": "string"},
                "beta": {"description": "Second", "type": "string"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"add_keys": {"alpha": "A_VAL", "beta": "B_VAL"}},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0, f"stderr: {result.stderr!r}"
            payload = json.loads(result.stdout)
            assert payload["success"] is True
            assert payload["result"]["alpha"] == "A_VAL"
            assert payload["result"]["beta"] == "B_VAL"
        finally:
            Path(workflow_file).unlink()

    def test_stdout_marker_does_not_filter_json_output(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """The ``stdout: true`` marker is text-mode routing ONLY — JSON mode must still emit all declared outputs.

        This guards the load-bearing contract that the marker picks which
        single output streams to process stdout in text mode; it does NOT
        filter the structured-output surface. A future "consistency" refactor
        that also applied the marker to JSON mode would silently drop
        outputs for MCP clients, CI pipelines, and workflow chaining — the
        exact silent-data-loss shape this feature exists to prevent.
        """
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "primary": {"description": "Marked", "type": "string", "stdout": True},
                "secondary": {"description": "Unmarked", "type": "string"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"add_keys": {"primary": "PRIMARY_VAL", "secondary": "SECONDARY_VAL"}},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0, f"stderr: {result.stderr!r}"
            payload = json.loads(result.stdout)
            assert payload["success"] is True
            # BOTH outputs must appear — the marker must not filter JSON
            assert payload["result"]["primary"] == "PRIMARY_VAL"
            assert payload["result"]["secondary"] == "SECONDARY_VAL", (
                "stdout: true marker leaked into JSON output filtering — "
                "secondary output was silently dropped. The marker is text-mode-only."
            )
        finally:
            Path(workflow_file).unlink()

    def test_tty_mode_shows_output_descriptions(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """When stdout is a TTY, the output description renders in the stderr header.

        CliRunner reports isatty()=False by default, so this test patches the
        OutputController at construction to simulate a real interactive terminal
        where the description label is useful context.
        """
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"final_result": {"description": "The final processed result", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"output_key": "final_result", "output_value": "Processing complete"},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        from pflow.core.output_controller import OutputController

        original_init = OutputController.__init__

        def force_tty_init(self, *args, **kwargs):
            kwargs.setdefault("stdout_tty", True)
            original_init(self, *args, **kwargs)

        try:
            with patch.object(OutputController, "__init__", force_tty_init):
                result = runner.invoke(main, ["--verbose", workflow_file])

            assert result.exit_code == 0
            # Header appears in TTY mode (routed to stderr)
            assert "Workflow output (The final processed result):" in result.stderr
            # And the actual output (goes to stdout)
            assert "Processing complete" in result.output
        finally:
            Path(workflow_file).unlink()

    def test_both_streams_captured_shows_header(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Both streams captured (the agent case) → the label IS shown on stderr.

        CliRunner reports isatty()=False for BOTH stdout and stderr, so this is
        the agent/merged-capture branch of Option B: the label delimits where the
        result begins. Data still goes to stdout only.
        """
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"final_result": {"description": "The final processed result", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"output_key": "final_result", "output_value": "Processing complete"},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            assert result.exit_code == 0
            assert "Workflow output (The final processed result):" in result.stderr
            assert "Processing complete" in result.stdout
            assert "Processing complete" not in result.stderr
        finally:
            Path(workflow_file).unlink()

    def test_stdout_redirected_stderr_terminal_suppresses_header(
        self, mock_registry_instance, mock_compile, mock_validate_ir
    ):
        """stdout redirected to a file WHILE stderr is a terminal → label suppressed.

        This is the only case the suppression fires in (Option B): a naked
        ``Workflow output (...)`` label on the terminal with the value in the
        redirected file reads as "empty output". Forced via ``stderr_tty=True``
        + ``stdout_tty=False`` since CliRunner reports both as non-TTY.
        """
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"final_result": {"description": "The final processed result", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"output_key": "final_result", "output_value": "Processing complete"},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        from pflow.core.output_controller import OutputController

        original_init = OutputController.__init__

        def redirect_init(self, *args, **kwargs):
            kwargs.setdefault("stdout_tty", False)
            kwargs.setdefault("stderr_tty", True)
            original_init(self, *args, **kwargs)

        try:
            with patch.object(OutputController, "__init__", redirect_init):
                result = runner.invoke(main, [workflow_file])

            assert result.exit_code == 0
            # Label suppressed because stderr is a terminal; data still on stdout.
            assert "Workflow output" not in result.stderr
            assert "Processing complete" in result.stdout
        finally:
            Path(workflow_file).unlink()

    def test_fallback_key_priority_order(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that fallback keys are checked in the correct order."""
        runner = click.testing.CliRunner(mix_stderr=False)

        # Test the priority: result > response > output > text > data > stdout
        test_cases = [
            # (keys_to_add, expected_output)
            ({"text": "Text value", "result": "Result value"}, "Result value"),
            ({"text": "Text value"}, "Text value"),
            ({"result": "Result value", "output": "Output value"}, "Result value"),
            (
                {"response": "Response value", "output": "Output value", "result": "Result", "text": "Text"},
                "Result",
            ),
        ]

        for keys_to_add, expected_output in test_cases:
            workflow = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "test", "type": "test-node", "params": {"add_keys": keys_to_add}}],
            }

            with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
                f.write(ir_to_markdown(workflow))
                workflow_file = f.name

            try:
                result = runner.invoke(main, [workflow_file])

                assert result.exit_code == 0
                assert expected_output in result.output
            finally:
                Path(workflow_file).unlink()

    def test_no_output_shows_success_message(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that workflows with no output show success message."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        # Node writes to _-prefixed key, filtered by auto-detection
                        "output_key": "_internal_key",
                        "output_value": "Internal value",
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            assert result.exit_code == 0
            # Stdout stays empty when no output is produced (auto-detect
            # filtered the ``_``-prefixed internal key). The stderr summary
            # signals success; stdout is reserved for data so pipe consumers
            # receive a clean stream.
            assert result.output == ""
            # Should not show the internal value
            assert "Internal value" not in result.output
        finally:
            Path(workflow_file).unlink()

    def test_output_key_not_found_warning(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test warning when specified --output-key is not found."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"output_key": "actual_key", "output_value": "Actual value"},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-key", "nonexistent_key", workflow_file])

            assert result.exit_code == 0
            # Should warn about missing key (warning → stderr)
            assert "Warning - output key 'nonexistent_key' not found." in result.stderr
            assert "Available top-level keys:" in result.stderr
            assert "shared store" not in result.stderr
            # Stdout stays empty on ``-o`` miss. The stderr summary signals
            # success; pipe consumers (``pflow ... -o nonexistent | jq .``)
            # receive a clean stream rather than the literal English fallback.
            assert result.output == ""
            assert "Workflow executed successfully" not in result.output
        finally:
            Path(workflow_file).unlink()

    def test_declared_outputs_override_hardcoded_keys(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that declared outputs take precedence over hardcoded fallback keys."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"custom_output": {"description": "Custom output that should be used", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "response": "This is response (fallback)",
                            "custom_output": "This is custom output (declared)",
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            assert result.exit_code == 0
            # Should use declared output, not fallback
            assert "This is custom output (declared)" in result.output
            assert "This is response (fallback)" not in result.output
        finally:
            Path(workflow_file).unlink()

    def test_empty_outputs_declaration_falls_back(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that empty outputs declaration falls back to hardcoded keys."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {},  # Empty outputs declaration
            "nodes": [{"id": "test", "type": "test-node", "params": {"add_keys": {"response": "Fallback response"}}}],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            assert result.exit_code == 0
            # Should fall back to hardcoded keys
            assert "Fallback response" in result.output
        finally:
            Path(workflow_file).unlink()

    def test_complex_output_types(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that various output types are emitted as valid JSON on stdout.

        After the GH #194 fix, `safe_output` JSON-encodes non-string values
        so that `pflow foo | jq` works for dict/list/bool/number/null outputs.
        Strings still pass through verbatim.

        Round-trips each emitted value through ``json.loads`` to verify
        the stdout is *parseable JSON*, not just substring-matchable. This
        catches subtle regressions like trailing whitespace, prefix/suffix
        corruption, or any other byte the substring check would miss.
        """
        runner = click.testing.CliRunner(mix_stderr=False)

        # Each entry: (declared output dict, the Python value we expect
        # to round-trip back from json.loads(stdout)). Strings are tested
        # separately because they pass through verbatim and aren't JSON.
        test_cases: list[tuple[dict, object]] = [
            ({"dict_output": {"key": "value", "nested": {"data": 123}}}, {"key": "value", "nested": {"data": 123}}),
            ({"list_output": ["item1", "item2", "item3"]}, ["item1", "item2", "item3"]),
            ({"number_output": 42.5}, 42.5),
            ({"bool_output": True}, True),
            ({"null_output": None}, None),
        ]

        for output_data, expected_value in test_cases:
            output_key = next(iter(output_data.keys()))
            workflow = {
                "ir_version": "0.1.0",
                "outputs": {output_key: {"description": f"Testing {output_key}", "type": "any"}},
                "nodes": [{"id": "test", "type": "test-node", "params": {"add_keys": output_data}}],
            }

            with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
                f.write(ir_to_markdown(workflow))
                workflow_file = f.name

            try:
                result = runner.invoke(main, [workflow_file])

                assert result.exit_code == 0, f"exit={result.exit_code} for {output_key}\nstderr: {result.stderr!r}"

                # Round-trip-parse the stdout to prove it's valid JSON.
                # Strip whitespace because click.echo adds a trailing newline.
                stdout_stripped = result.stdout.strip()
                try:
                    parsed = json.loads(stdout_stripped)
                except json.JSONDecodeError as e:
                    raise AssertionError(
                        f"stdout for {output_key} (value={output_data[output_key]!r}) "
                        f"is not parseable JSON: {e}\nstdout: {result.stdout!r}"
                    ) from e

                assert parsed == expected_value, (
                    f"Round-trip mismatch for {output_key}: "
                    f"expected {expected_value!r}, got {parsed!r}\nstdout: {result.stdout!r}"
                )
            finally:
                Path(workflow_file).unlink()

    # New tests for --output-format flag functionality

    def test_json_format_single_declared_output(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that JSON format correctly returns a single declared output."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"summary": {"description": "Processing summary", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"output_key": "summary", "output_value": "Task completed successfully"},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            # Parse the JSON output - it's now wrapped in a result structure
            output_data = json.loads(result.stdout)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)
            assert actual_result == {"summary": "Task completed successfully"}
        finally:
            Path(workflow_file).unlink()

    def test_json_format_multiple_declared_outputs(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that JSON format includes ALL declared outputs."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "summary": {"description": "Summary", "type": "string"},
                "count": {"description": "Count", "type": "number"},
                "tags": {"description": "Tags", "type": "array"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "summary": "Analysis complete",
                            "count": 42,
                            "tags": ["important", "reviewed", "approved"],
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            # Parse the JSON output - it's now wrapped in a result structure
            output_data = json.loads(result.stdout)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)
            # Should include ALL declared outputs
            assert actual_result == {
                "summary": "Analysis complete",
                "count": 42,
                "tags": ["important", "reviewed", "approved"],
            }
        finally:
            Path(workflow_file).unlink()

    def test_json_format_with_output_key(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that --output-key works with JSON format."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "primary": {"description": "Primary output", "type": "string"},
                "secondary": {"description": "Secondary output", "type": "string"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "primary": "Primary value",
                            "secondary": "Secondary value",
                            "custom_key": "Custom value",
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            # Request specific key with JSON format
            result = runner.invoke(main, ["--output-format", "json", "--output-key", "custom_key", workflow_file])

            assert result.exit_code == 0
            output_data = json.loads(result.stdout)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)
            # Should only return the requested key
            assert actual_result == {"custom_key": "Custom value"}
        finally:
            Path(workflow_file).unlink()

    def test_json_format_empty_result(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that no matching outputs returns empty JSON object."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"expected_output": {"description": "Expected but not found", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        # Node doesn't produce the expected output
                        "output_key": "different_key",
                        "output_value": "Some value",
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            output_data = json.loads(result.stdout)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)
            # Should return empty JSON object
            assert actual_result == {}
        finally:
            Path(workflow_file).unlink()

    def test_json_format_fallback_keys(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that JSON format uses hardcoded fallback keys when no outputs declared."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            # No outputs declared
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {"response": "Fallback response value", "other_key": "Should not be included"}
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            output_data = json.loads(result.stdout)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)
            # Should return first matching fallback key
            assert actual_result == {"response": "Fallback response value"}
        finally:
            Path(workflow_file).unlink()

    def test_json_format_complex_types(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that JSON format handles arrays, objects, numbers, booleans correctly."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "metadata": {"description": "Metadata object", "type": "object"},
                "items": {"description": "Item list", "type": "array"},
                "score": {"description": "Score", "type": "number"},
                "is_valid": {"description": "Validity flag", "type": "boolean"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "metadata": {
                                "author": "Test User",
                                "created": "2024-01-01",
                                "nested": {"level": 2, "data": [1, 2, 3]},
                            },
                            "items": ["apple", "banana", {"type": "orange", "count": 5}],
                            "score": 98.5,
                            "is_valid": True,
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            output_data = json.loads(result.stdout)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)

            # Verify all complex types are preserved correctly
            assert actual_result["metadata"]["author"] == "Test User"
            assert actual_result["metadata"]["nested"]["data"] == [1, 2, 3]
            assert actual_result["items"][2]["type"] == "orange"
            assert actual_result["score"] == 98.5
            assert actual_result["is_valid"] is True
        finally:
            Path(workflow_file).unlink()

    def test_text_format_unchanged(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that text format (default) still works as before."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"message": {"description": "Output message", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {"output_key": "message", "output_value": "Plain text output"},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            # Test with explicit --output-format text
            result = runner.invoke(main, ["--output-format", "text", workflow_file])
            assert result.exit_code == 0
            assert "Plain text output" in result.output

            # Test without format flag (default)
            result = runner.invoke(main, [workflow_file])
            assert result.exit_code == 0
            assert "Plain text output" in result.output
        finally:
            Path(workflow_file).unlink()

    def test_format_case_insensitive(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that output format is case-insensitive."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"data": {"description": "Test data", "type": "string"}},
            "nodes": [
                {"id": "test", "type": "test-node", "params": {"output_key": "data", "output_value": "Test value"}}
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            # Test "JSON" (uppercase)
            result = runner.invoke(main, ["--output-format", "JSON", workflow_file])
            assert result.exit_code == 0
            output_data = json.loads(result.stdout)
            actual_result = output_data.get("result", output_data)
            assert actual_result == {"data": "Test value"}

            # Test "Json" (mixed case)
            result = runner.invoke(main, ["--output-format", "Json", workflow_file])
            assert result.exit_code == 0
            output_data = json.loads(result.stdout)
            actual_result = output_data.get("result", output_data)
            assert actual_result == {"data": "Test value"}
        finally:
            Path(workflow_file).unlink()

    def test_json_format_with_verbose(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that verbose warnings don't break JSON output."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "expected": {"description": "Expected output", "type": "string"},
                "missing": {"description": "Missing output", "type": "string"},
            },
            "nodes": [
                {"id": "test", "type": "test-node", "params": {"output_key": "expected", "output_value": "Found value"}}
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--verbose", "--output-format", "json", workflow_file])

            assert result.exit_code == 0

            # Verbose messages go to stderr; stdout has pure JSON
            json_output = json.loads(result.stdout)

            # Extract the actual result from the wrapper
            actual_result = json_output.get("result", json_output)
            assert actual_result == {"expected": "Found value"}
        finally:
            Path(workflow_file).unlink()

    def test_json_format_binary_data(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that binary data is handled gracefully in JSON format."""
        runner = click.testing.CliRunner(mix_stderr=False)

        # Create a mock binary data
        binary_data = b"\x00\x01\x02\x03\xff\xfe\xfd"

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"binary_output": {"description": "Binary data", "type": "any"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "binary_output": binary_data.decode("latin-1")  # Store as latin-1 string
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            # Should handle binary data without crashing
            output_data = json.loads(result.stdout)
            actual_result = output_data.get("result", output_data)
            assert "binary_output" in actual_result
        finally:
            Path(workflow_file).unlink()

    def test_json_format_null_values(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test that null/None values are handled correctly in JSON format."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "nullable": {"description": "Nullable field", "type": "any"},
                "present": {"description": "Present field", "type": "string"},
            },
            "nodes": [
                {"id": "test", "type": "test-node", "params": {"add_keys": {"nullable": None, "present": "value"}}}
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            output_data = json.loads(result.stdout)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)
            # Both fields should be present
            assert "nullable" in actual_result
            assert actual_result["nullable"] is None
            assert actual_result["present"] == "value"
        finally:
            Path(workflow_file).unlink()

    def test_json_format_missing_declared_outputs_partial(self, mock_registry_instance, mock_compile, mock_validate_ir):
        """Test JSON format when some declared outputs are missing."""
        runner = click.testing.CliRunner(mix_stderr=False)

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {
                "found1": {"description": "Found output 1", "type": "string"},
                "missing": {"description": "Missing output", "type": "string"},
                "found2": {"description": "Found output 2", "type": "number"},
            },
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "add_keys": {
                            "found1": "Value 1",
                            "found2": 42,
                            # "missing" is not provided
                        }
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, ["--output-format", "json", workflow_file])

            assert result.exit_code == 0
            output_data = json.loads(result.stdout)
            # Extract the actual result from the wrapper
            actual_result = output_data.get("result", output_data)
            # Should only include found outputs
            assert actual_result == {"found1": "Value 1", "found2": 42}
            assert "missing" not in actual_result
        finally:
            Path(workflow_file).unlink()


class TestOutputKeyDottedPath:
    """Direct tests of ``_handle_text_output`` for dotted ``-o`` resolution.

    These call the function directly (capsys-based) instead of going through
    the CLI runner — fast, deterministic, and bypasses the
    ``_emit_summary_or_only_indicator`` early-return on ``metrics_collector=None``.
    """

    def test_output_key_dotted_path_resolves_nested_value(self, capsys):
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"batch-llm": make_batch_shape(results=[{"result": "a"}, {"result": "b"}])}
        _handle_text_output(shared, output_key="batch-llm.success_count", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert captured.out.strip() == "2"
        assert "Warning" not in captured.err

    def test_output_key_dotted_path_resolves_list_index(self, capsys):
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"batch-llm": make_batch_shape(results=[{"result": "alpha"}, {"result": "beta"}])}
        _handle_text_output(shared, output_key="batch-llm.results[0].result", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert captured.out.strip() == "alpha"

    def test_output_key_dotted_path_returns_null_for_none_value(self, capsys):
        """``-o node.errors`` on a successful batch emits JSON ``null``, NOT a warning.

        Pins the ``variable_exists`` + ``resolve_value`` design — a future
        refactor that uses just ``resolve_value`` and checks for None would fail
        this test.
        """
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"batch-llm": make_batch_shape(results=[{"result": "ok"}])}
        assert shared["batch-llm"]["errors"] is None
        _handle_text_output(shared, output_key="batch-llm.errors", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert captured.out.strip() == "null"
        assert "Warning" not in captured.err
        assert "not found" not in captured.err

    def test_output_key_flat_hyphenated_key_unchanged(self, capsys):
        """``-o batch-llm`` (flat lookup, hyphenated key) returns the full batch dict."""
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"batch-llm": make_batch_shape(results=[{"result": "x"}])}
        _handle_text_output(shared, output_key="batch-llm", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        out = captured.out
        assert '"success_count": 1' in out
        assert '"count": 1' in out
        assert "Warning" not in captured.err

    def test_output_key_dotted_path_crosses_sub_workflow_namespace(self, capsys):
        """``-o sub-wf.batch-llm.success_count`` traverses a sub-workflow namespace."""
        from pflow.cli.workflow_output import _handle_text_output

        shared = {
            "sub-wf": {
                "batch-llm": make_batch_shape(results=[{"r": 1}, {"r": 2}, {"r": 3}]),
            },
        }
        _handle_text_output(shared, output_key="sub-wf.batch-llm.success_count", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert captured.out.strip() == "3"


class TestOutputKeyMissHints:
    """Walk-to-failure hint generation for missing ``-o`` paths."""

    def test_output_key_miss_lists_top_level_keys(self, capsys):
        """Flat miss lists top-level keys, drops 'shared store' vocabulary."""
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"batch-llm": make_batch_shape(results=[{"r": 1}]), "result": "hi"}
        _handle_text_output(shared, output_key="nonexistent", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert "Warning - output key 'nonexistent' not found." in captured.err
        assert "Available top-level keys: batch-llm, result." in captured.err
        assert "shared store" not in captured.err

    def test_output_key_miss_lists_subkeys_at_failure_point(self, capsys):
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"batch-llm": make_batch_shape(results=[{"r": 1}])}
        _handle_text_output(shared, output_key="batch-llm.missing", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        expected_keys = "batch_metadata, count, error_count, errors, results, success_count"
        assert f"Available subkeys of 'batch-llm': {expected_keys}." in captured.err

    def test_output_key_miss_describes_list_bounds(self, capsys):
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"batch-llm": make_batch_shape(results=[{}, {}])}
        _handle_text_output(shared, output_key="batch-llm.results[99]", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert "'batch-llm.results' is a list of length 2. Valid indices: 0 to 1." in captured.err

    def test_output_key_miss_describes_list_length_one(self, capsys):
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"batch-llm": make_batch_shape(results=[{"r": 1}])}
        _handle_text_output(shared, output_key="batch-llm.results[99]", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert "'batch-llm.results' is a list of length 1. Valid index: 0." in captured.err

    def test_output_key_miss_describes_empty_list(self, capsys):
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"data": {"items": []}}
        _handle_text_output(shared, output_key="data.items[0]", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert "'data.items' is an empty list." in captured.err

    def test_output_key_miss_describes_scalar_dead_end_with_value(self, capsys):
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"batch-llm": make_batch_shape(results=[{"r": 1}, {"r": 2}])}
        _handle_text_output(shared, output_key="batch-llm.success_count.foo", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert "'batch-llm.success_count' is a number (value: 2), cannot descend." in captured.err

    def test_output_key_miss_describes_string_dead_end(self, capsys):
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"node": {"text": "hello world"}}
        _handle_text_output(shared, output_key="node.text.foo", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert "'node.text' is a string (value: 'hello world'), cannot descend." in captured.err

    def test_output_key_miss_describes_null_dead_end(self, capsys):
        """None mid-path uses 'null value' type label (likely real-world hit:
        ``node.errors.field`` where ``errors`` is None on a successful batch).
        """
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"batch-llm": make_batch_shape(results=[{"r": 1}])}
        _handle_text_output(shared, output_key="batch-llm.errors.first", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert "'batch-llm.errors' is a null value (value: None), cannot descend." in captured.err

    def test_output_key_miss_describes_boolean_dead_end(self, capsys):
        """Boolean uses its own label, not 'number' (bool subclasses int)."""
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"node": {"done": True}}
        _handle_text_output(shared, output_key="node.done.foo", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert "'node.done' is a boolean (value: True), cannot descend." in captured.err

    def test_output_key_miss_dict_with_only_internal_keys(self, capsys):
        """Dict containing only underscore-prefixed keys reports as having no subkeys."""
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"data": {"_internal": "secret", "__hidden__": 1}}
        _handle_text_output(shared, output_key="data.missing", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert "'data' has no subkeys." in captured.err
        assert "_internal" not in captured.err
        assert "__hidden__" not in captured.err

    def test_output_key_miss_suppressed_under_print_mode(self, capsys):
        """``-p`` suppresses the warning and hint entirely."""
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"batch-llm": make_batch_shape(results=[{"r": 1}])}
        _handle_text_output(
            shared,
            output_key="batch-llm.missing",
            workflow_ir=None,
            verbose=False,
            print_flag=True,
        )
        captured = capsys.readouterr()
        assert "Warning" not in captured.err
        assert "Available" not in captured.err

    def test_output_key_miss_invalid_path_syntax(self, capsys):
        """Invalid characters yield a generic syntax hint, not a misleading miss."""
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"batch-llm": make_batch_shape(results=[{"r": 1}])}
        _handle_text_output(shared, output_key="batch-llm$.count", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert "contains characters that aren't valid in a path" in captured.err
        assert "Use `<name>`, `<name>.<sub>`, or `<name>[N]` syntax." in captured.err

    def test_output_key_miss_inside_list_element_lists_element_keys(self, capsys):
        """``-o batch.results[0].typo`` — agent typo'd a field name INSIDE a
        list element. Walker must advance through three segment kinds
        (name → bracket-index → name) before reporting the miss, and the hint
        must surface the actual subkeys of ``results[0]``.

        Realistic "agent fat-fingered a field name on a per-item result"
        failure mode. Walker logic that handles dotted names but not
        bracket-index segments as ``valid_prefix`` extensions would
        false-localize this to ``'batch-llm.results'`` and tell the agent the
        path is wrong, when really the agent just typo'd a leaf.
        """
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"batch-llm": make_batch_shape(results=[{"result": "alpha", "tokens": 5}, {"result": "beta"}])}
        _handle_text_output(shared, output_key="batch-llm.results[0].typo", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        # Hint localizes to results[0] (NOT to results), proving the walker
        # advanced PAST the bracket-index segment before failing.
        assert "Available subkeys of 'batch-llm.results[0]': result, tokens." in captured.err, captured.err

    def test_output_key_miss_with_dot_notation_for_list_index_nudges_to_brackets(self, capsys):
        """``-o batch.results.0.result`` — the documented misuse from issue #400.

        The issue's text itself used dot notation for list indices (``.0``).
        The plan corrected this to bracket notation (``[0]``) to match
        ``TemplateResolver``. This test pins the load-bearing UX promise:
        when an agent makes this dot-notation mistake, the resulting hint
        must mention the correct ``[N]`` syntax somewhere.

        Two ways this could be delivered:
        1. Syntax-error hint: bare-digit segments fail the regex
           reconstruction check, producing the generic "invalid characters"
           hint that explicitly lists ``<name>[N]`` syntax. (Current path.)
        2. List-bounds hint: walker descends to ``batch-llm.results``, fails
           at ``0``, emits "Valid indices: 0 to N".

        Either is acceptable. The contract tested here is the OUTCOME
        invariant — agent sees ``[N]`` syntax in the hint — not the specific
        code path that delivers it. A future refactor that switches from
        path 1 to path 2 (e.g., extending the regex to accept bare digits as
        a recognized-but-walker-failing segment) would still pass this test
        as long as the bracket nudge survives.
        """
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"batch-llm": make_batch_shape(results=[{"result": "alpha"}, {"result": "beta"}, {"result": "gamma"}])}
        _handle_text_output(
            shared,
            output_key="batch-llm.results.0.result",
            workflow_ir=None,
            verbose=False,
        )
        captured = capsys.readouterr()
        # The miss is surfaced (not silently ignored).
        assert "Warning - output key 'batch-llm.results.0.result' not found." in captured.err
        # Whichever path delivers it, the hint MUST mention bracket syntax —
        # this is the agent's only on-screen path to discovering the correct
        # ``[N]`` notation when they typed ``.N``.
        assert "[N]" in captured.err or "Valid indices:" in captured.err, captured.err


class TestOnlyBatchCompactSummary:
    """``--only <batch-node>`` compact-summary rendering (text mode)."""

    def test_only_batch_node_emits_compact_summary(self, capsys):
        """Data line on stdout, advisory hint on stderr (stream-discipline parity
        with the rest of ``workflow_output.py``: ``-o`` miss hint, ``--only``
        no-output advisory, declared-output warnings all use stderr for advice).
        """
        from pflow.cli.workflow_output import _handle_text_output

        shared = {
            "__execution__": {"only_node": "summarize-docs"},
            "summarize-docs": make_batch_shape(
                results=[{"result": "alpha"}, {"result": "beta"}],
                total_items_ms=1400.0,
            ),
        }
        _handle_text_output(shared, output_key=None, workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        # Data line — stdout, alone.
        assert captured.out.strip() == "batch summarize-docs: 2/2 items succeeded in 1.4s"
        assert "alpha" not in captured.out
        assert "beta" not in captured.out
        # Hint line — stderr.
        assert "use `-o summarize-docs.results` for full payload" in captured.err
        # error_count == 0, so no errors hint.
        assert "for failures" not in captured.err
        # The advisory line from the non-batch path must not appear.
        assert "streaming auto-detected" not in captured.err

    def test_only_batch_node_with_errors_includes_errors_hint(self, capsys):
        from pflow.cli.workflow_output import _handle_text_output

        shared = {
            "__execution__": {"only_node": "batch-llm"},
            "batch-llm": make_batch_shape(
                results=[{"result": "ok"}],
                errors=[{"index": 0, "error": "boom"}],
                total_items_ms=1400.0,
            ),
        }
        _handle_text_output(shared, output_key=None, workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        # Data line — stdout.
        assert captured.out.strip() == "batch batch-llm: 1/2 items succeeded in 1.4s"
        # Hint line — stderr, includes the failures hint when error_count > 0.
        assert "`-o batch-llm.errors` for failures" in captured.err
        assert "use `-o batch-llm.results` for full payload" in captured.err

    def test_only_batch_node_no_timing_omits_duration(self, capsys):
        """``batch_metadata.timing`` is None → no ' in Xs' suffix (not '0.0s')."""
        from pflow.cli.workflow_output import _handle_text_output

        shared = {
            "__execution__": {"only_node": "batch-llm"},
            "batch-llm": make_batch_shape(results=[{"r": 1}], total_items_ms=None),
        }
        _handle_text_output(shared, output_key=None, workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert captured.out.split("\n")[0] == "batch batch-llm: 1/1 items succeeded"

    def test_only_batch_node_empty_batch(self, capsys):
        from pflow.cli.workflow_output import _handle_text_output

        shared = {
            "__execution__": {"only_node": "batch-llm"},
            "batch-llm": make_batch_shape(results=[], total_items_ms=None),
        }
        _handle_text_output(shared, output_key=None, workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert "batch batch-llm: ran with no items" in captured.out
        assert "0/0" not in captured.out

    def test_only_batch_node_print_mode_suppresses_hint(self, capsys):
        """``-p`` keeps the data line on stdout, suppresses the stderr hint."""
        from pflow.cli.workflow_output import _handle_text_output

        shared = {
            "__execution__": {"only_node": "batch-llm"},
            "batch-llm": make_batch_shape(results=[{"r": 1}, {"r": 2}], total_items_ms=1400.0),
        }
        _handle_text_output(
            shared,
            output_key=None,
            workflow_ir=None,
            verbose=False,
            print_flag=True,
        )
        captured = capsys.readouterr()
        assert captured.out.strip() == "batch batch-llm: 2/2 items succeeded in 1.4s"
        # Hint must be suppressed on BOTH streams under -p.
        assert "for full payload" not in captured.err
        assert "for full payload" not in captured.out

    def test_only_batch_node_with_explicit_output_key_yields_full_payload(self, capsys):
        """``--only batch -o batch.results`` opts back into the full list (escape hatch)."""
        from pflow.cli.workflow_output import _handle_text_output

        shared = {
            "__execution__": {"only_node": "batch-llm"},
            "batch-llm": make_batch_shape(results=[{"result": "alpha"}, {"result": "beta"}]),
        }
        _handle_text_output(shared, output_key="batch-llm.results", workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        out = captured.out
        assert "alpha" in out
        assert "beta" in out
        assert "items succeeded" not in out

    def test_only_dotted_into_batch_subworkflow_namespace(self, capsys):
        """``--only sub-wf.inner`` where ``shared["sub-wf"]`` IS itself a batch aggregate.

        Case A: the parent invoked the sub-workflow via batch. ``find_only_output``
        returns ``shared["sub-wf"]`` for any dotted target; if that namespace has
        ``batch_metadata``, compact summary fires.

        NOTE (issue #443): dotted --only is REJECTED at the engine layer (deferred
        nested-targeting). This hand-builds shared and drives only the formatter,
        so it stays green; it documents the display routing the deferred feature
        would reuse, not that dotted --only executes today.
        """
        from pflow.cli.workflow_output import _handle_text_output

        shared = {
            "__execution__": {"only_node": "sub-wf.inner"},
            "sub-wf": make_batch_shape(results=[{"r": 1}, {"r": 2}], total_items_ms=2300.0),
        }
        _handle_text_output(shared, output_key=None, workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        assert "batch sub-wf: 2/2 items succeeded in 2.3s" in captured.out

    def test_only_dotted_namespace_containing_batch_is_unchanged(self, capsys):
        """Case B: ``shared["sub-wf"]`` is a regular sub-workflow namespace
        CONTAINING a batch node — ``shared["sub-wf"]["inner-batch"]`` has
        ``batch_metadata``, but ``shared["sub-wf"]`` itself does NOT.

        Compact summary must NOT fire — ``find_only_output`` returns the parent
        namespace dict for dotted targets, and our shape detector keys off
        ``batch_metadata`` at the resolved value's TOP level, not recursively.
        Regression-guards against a future change that "improves" detection by
        recursing into namespaces — that would silently break the contract
        documented in plan §6.

        NOTE (issue #443): as with the Case A test above, dotted --only is
        rejected at the engine layer (deferred feature); this is a display-layer
        unit over a hand-built shared store, not end-to-end dotted execution.
        """
        from pflow.cli.workflow_output import _handle_text_output

        shared = {
            "__execution__": {"only_node": "sub-wf.inner-batch"},
            "sub-wf": {
                "inner-batch": make_batch_shape(results=[{"r": 1}, {"r": 2}], total_items_ms=2300.0),
                "other-node": {"result": "unrelated"},
            },
        }
        _handle_text_output(shared, output_key=None, workflow_ir=None, verbose=False)
        captured = capsys.readouterr()
        # Compact summary must NOT fire (no top-level batch_metadata).
        assert "items succeeded" not in captured.out
        # Full namespace payload leaks through instead — verify by inspecting
        # the raw batch shape that would be hidden if compact summary had fired.
        assert "batch_metadata" in captured.out
        assert "inner-batch" in captured.out


class TestCollectOutputsOnlyBatchUnchanged:
    """JSON-mode out-of-scope contract: ``--only batch-node`` (no ``-o``) keeps
    emitting the full batch aggregate. The compact summary is a text-mode UX;
    JSON consumers want structured data they parse programmatically.

    Locks the plan §2 out-of-scope decision so a future "let's give JSON the
    same UX" change doesn't silently break MCP consumers' structured-output
    expectations.
    """

    def test_json_mode_only_batch_returns_full_aggregate(self):
        from pflow.execution.formatters.success_formatter import _collect_outputs

        shared = {
            "__execution__": {"only_node": "batch-llm"},
            "batch-llm": make_batch_shape(results=[{"r": 1}, {"r": 2}], total_items_ms=1400.0),
        }
        outputs = _collect_outputs(shared, workflow_ir={}, output_key=None)

        # Returned under the root key, with full batch shape preserved.
        assert "batch-llm" in outputs
        value = outputs["batch-llm"]
        assert "results" in value
        assert "batch_metadata" in value
        assert value["success_count"] == 2
        assert value["count"] == 2
