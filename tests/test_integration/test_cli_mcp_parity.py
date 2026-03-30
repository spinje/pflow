"""Test that WorkflowRunner produces equivalent results with and without OutputInterface.

Guards against future divergence between CLI and MCP execution paths.
Both paths go through the same WorkflowRunner.run() method; the only
difference is whether an OutputInterface is provided (CLI) or not (MCP).
This test verifies that the structured ExecutionResult is equivalent
regardless of output interface presence.
"""

from pflow.cli.cli_output import CliOutput
from pflow.core.output_controller import OutputController
from pflow.core.workflow.status import WorkflowStatus
from pflow.execution.result import ExecutionResult, RunnerConfig
from pflow.execution.runner import WorkflowRunner


def test_runner_produces_equivalent_results_with_and_without_output() -> None:
    """When the same workflow runs with CliOutput vs no output, ExecutionResult fields match."""
    workflow_ir: dict = {
        "nodes": [
            {
                "id": "greet",
                "type": "shell",
                "params": {"command": "echo hello"},
            }
        ],
        "edges": [],
    }

    config = RunnerConfig()

    # Run without output interface (MCP path)
    result_no_output: ExecutionResult = WorkflowRunner().run(workflow_ir, {}, config)

    # Run with CliOutput (CLI path)
    controller = OutputController(
        print_flag=False,
        output_format="text",
        stdin_tty=False,
        stdout_tty=False,
    )
    cli_output = CliOutput(controller, verbose=False, output_format="text")
    result_with_output: ExecutionResult = WorkflowRunner().run(workflow_ir, {}, config, output=cli_output)

    # Both must succeed
    assert result_no_output.success is True, f"No-output run failed: {result_no_output.errors}"
    assert result_with_output.success is True, f"CLI-output run failed: {result_with_output.errors}"

    # Same status
    assert result_no_output.status == WorkflowStatus.SUCCESS
    assert result_with_output.status == WorkflowStatus.SUCCESS

    # Same output value in shared store
    assert "greet" in result_no_output.shared_after
    assert "greet" in result_with_output.shared_after
    assert "hello" in result_no_output.shared_after["greet"]["stdout"]
    assert "hello" in result_with_output.shared_after["greet"]["stdout"]

    # No errors
    assert result_no_output.errors == []
    assert result_with_output.errors == []

    # Trace collected in both cases
    assert result_no_output.trace is not None
    assert result_with_output.trace is not None
