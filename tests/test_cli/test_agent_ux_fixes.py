"""Tests for agent UX fixes — five targeted behavioral changes.

Fix 1: Shell stderr always visible (no verbose gate)
Fix 2a: Trace file "degraded" status when warnings present
Fix 2b: CLI exit code 2 for degraded workflows
Fix 3: Nested workflow child node ID in error message
Fix 4: Error category uses _determine_error_category (not hardcoded)
"""

from typing import Any
from unittest.mock import patch

from pflow.cli.workflow_errors import _display_single_error
from pflow.core.workflow.status import WorkflowStatus
from pflow.execution.executor_service import WorkflowExecutorService
from pflow.execution.null_output import NullOutput
from pflow.execution.result import ExecutionResult
from pflow.runtime.workflow_executor import WorkflowExecutor
from pflow.runtime.workflow_trace import WorkflowTraceCollector

# ---------------------------------------------------------------------------
# Fix 1: Shell stderr always visible (no verbose gate)
# ---------------------------------------------------------------------------


def test_shell_stderr_shown_without_verbose() -> None:
    """Shell command and stderr are displayed even when verbose=False.

    Previously, shell details were gated behind the verbose flag.
    Now they are always shown when shell_command is present in the error dict,
    because agents need stderr for diagnosis regardless of verbose mode.
    """
    error: dict[str, Any] = {
        "node_id": "run-build",
        "category": "execution_failure",
        "message": "Shell command failed with exit code 1",
        "shell_command": "npm run build",
        "shell_stderr": "Error: Cannot find module 'react'",
    }

    # Capture all click.echo calls to stderr
    captured: list[str] = []

    def capture_echo(message: Any = "", err: bool = False, **kwargs: Any) -> None:
        if err:
            captured.append(str(message))

    with patch("pflow.cli.workflow_errors.click.echo", side_effect=capture_echo):
        _display_single_error(error, error_number=1, verbose=False)

    output = "\n".join(captured)

    # Shell details must appear even with verbose=False
    assert "Shell details:" in output
    assert "npm run build" in output
    assert "Cannot find module 'react'" in output


def test_shell_stdout_also_shown_without_verbose() -> None:
    """When shell_stdout is present alongside stderr, both are shown."""
    error: dict[str, Any] = {
        "node_id": "run-tests",
        "category": "execution_failure",
        "message": "Shell command failed",
        "shell_command": "pytest tests/",
        "shell_stdout": "FAILED tests/test_foo.py::test_bar",
        "shell_stderr": "1 failed, 5 passed",
    }

    captured: list[str] = []

    def capture_echo(message: Any = "", err: bool = False, **kwargs: Any) -> None:
        if err:
            captured.append(str(message))

    with patch("pflow.cli.workflow_errors.click.echo", side_effect=capture_echo):
        _display_single_error(error, error_number=1, verbose=False)

    output = "\n".join(captured)

    assert "Stdout:" in output
    assert "FAILED tests/test_foo.py::test_bar" in output
    assert "Stderr:" in output
    assert "1 failed, 5 passed" in output


# ---------------------------------------------------------------------------
# Fix 2a: Trace file "degraded" status
# ---------------------------------------------------------------------------


def test_trace_status_degraded_when_warnings_present() -> None:
    """Trace status is 'degraded' when execution_warnings is non-empty.

    All events succeed but the workflow had warnings (e.g., partial batch failure),
    so the trace should reflect 'degraded' rather than 'success'.
    """
    collector = WorkflowTraceCollector(workflow_name="test")

    # Add a successful event
    collector.record_node_execution(
        node_id="step1",
        node_type="shell",
        duration_ms=100.0,
        success=True,
    )

    # Set warnings (e.g., from a batch with partial failures)
    collector.set_warnings([{"node_id": "step1", "type": "batch_partial", "message": "2 of 5 items failed"}])

    status = collector._determine_trace_status()
    assert status == "degraded"


def test_trace_status_failed_wins_over_degraded() -> None:
    """'failed' status takes precedence over 'degraded' when both apply.

    If a node failed AND there are warnings, the overall status should be 'failed'.
    """
    collector = WorkflowTraceCollector(workflow_name="test")

    # Add a failed event
    collector.record_node_execution(
        node_id="step1",
        node_type="shell",
        duration_ms=50.0,
        success=False,
        error="Command failed",
    )

    # Also set warnings
    collector.set_warnings([{"node_id": "step1", "type": "template_resolution", "message": "unresolved var"}])

    status = collector._determine_trace_status()
    assert status == "failed"


def test_trace_status_success_when_no_warnings_no_failures() -> None:
    """Clean execution with no warnings and no failures is 'success'."""
    collector = WorkflowTraceCollector(workflow_name="test")

    collector.record_node_execution(
        node_id="step1",
        node_type="shell",
        duration_ms=100.0,
        success=True,
    )

    status = collector._determine_trace_status()
    assert status == "success"


def test_trace_status_success_when_warnings_empty_list() -> None:
    """An empty warnings list should still be 'success'.

    set_warnings([]) sets execution_warnings to None, so it should not trigger degraded.
    """
    collector = WorkflowTraceCollector(workflow_name="test")

    collector.record_node_execution(
        node_id="step1",
        node_type="shell",
        duration_ms=100.0,
        success=True,
    )

    # Empty list -> set_warnings converts to None
    collector.set_warnings([])

    status = collector._determine_trace_status()
    assert status == "success"


# ---------------------------------------------------------------------------
# Fix 2b: CLI exit code 2 for degraded workflows
# ---------------------------------------------------------------------------


def test_degraded_workflow_exits_with_code_2(tmp_path) -> None:
    """A successful but degraded workflow should exit with code 2.

    This follows CLI conventions (0=success, 1=error, 2=degraded) similar to
    rsync and xargs, giving agents a machine-readable signal for partial failure.
    """
    from click.testing import CliRunner

    from pflow.cli.main import main
    from tests.shared.markdown_utils import write_workflow_file

    workflow = {
        "nodes": [{"id": "n1", "type": "shell", "params": {"command": "echo ok"}}],
        "edges": [],
    }
    wf_path = tmp_path / "test.pflow.md"
    write_workflow_file(workflow, wf_path)

    degraded_result = ExecutionResult(success=True, status=WorkflowStatus.DEGRADED, shared_after={"result": "ok"})

    runner = CliRunner()
    with patch(
        "pflow.execution.workflow_execution.WorkflowExecutorService.execute_workflow", return_value=degraded_result
    ):
        result = runner.invoke(main, [str(wf_path)])

    assert result.exit_code == 2


def test_successful_workflow_does_not_exit_with_code_2(tmp_path) -> None:
    """A fully successful workflow should not exit with code 2."""
    from click.testing import CliRunner

    from pflow.cli.main import main
    from tests.shared.markdown_utils import write_workflow_file

    workflow = {
        "nodes": [{"id": "n1", "type": "shell", "params": {"command": "echo ok"}}],
        "edges": [],
    }
    wf_path = tmp_path / "test.pflow.md"
    write_workflow_file(workflow, wf_path)

    success_result = ExecutionResult(success=True, status=WorkflowStatus.SUCCESS, shared_after={"result": "ok"})

    runner = CliRunner()
    with patch(
        "pflow.execution.workflow_execution.WorkflowExecutorService.execute_workflow", return_value=success_result
    ):
        result = runner.invoke(main, [str(wf_path)])

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Fix 3: Nested workflow child node ID in error message
# ---------------------------------------------------------------------------


def test_extract_child_error_includes_node_id() -> None:
    """Error message from sub-workflow failure should include the failed node ID.

    Previously the message only said 'Sub-workflow failed at <path>'. Now it
    includes the specific child node that failed, helping agents locate the issue.
    """
    child_storage: dict[str, Any] = {
        "__execution__": {"failed_node": "my-shell-node"},
        "my-shell-node": {"error": "Command failed with exit code 127"},
    }

    message = WorkflowExecutor._extract_child_error(child_storage, "./child.pflow.md")

    assert "my-shell-node" in message
    assert "Command failed with exit code 127" in message
    assert "./child.pflow.md" in message


def test_extract_child_error_fallback_without_failed_node() -> None:
    """Without a failed_node, the error message should use the generic fallback."""
    child_storage: dict[str, Any] = {
        "__execution__": {},
    }

    message = WorkflowExecutor._extract_child_error(child_storage, "./child.pflow.md")

    assert "./child.pflow.md" in message
    assert "returned error action" in message


def test_extract_child_error_fallback_no_error_in_node_data() -> None:
    """If the failed node's data has no 'error' key, use the generic fallback."""
    child_storage: dict[str, Any] = {
        "__execution__": {"failed_node": "some-node"},
        "some-node": {"stdout": "some output but no error key"},
    }

    message = WorkflowExecutor._extract_child_error(child_storage, "./workflow.pflow.md")

    assert "returned error action" in message


# ---------------------------------------------------------------------------
# Fix 4: Error category uses _determine_error_category (not hardcoded)
# ---------------------------------------------------------------------------


def test_handle_execution_exception_categorizes_template_error() -> None:
    """ValueError containing '${' should be categorized as template_error.

    Previously, _handle_execution_exception hardcoded category as 'exception'.
    Now it delegates to _determine_error_category for proper classification.
    """
    service = WorkflowExecutorService(output_interface=NullOutput())

    # ValueError with template reference in message
    exception = ValueError("Failed to resolve template ${node.output} in params")

    result = service._handle_execution_exception(exception)

    assert result["success"] is False
    assert len(result["errors"]) == 1
    assert result["errors"][0]["category"] == "template_error"


def test_handle_execution_exception_categorizes_generic_error() -> None:
    """A generic ValueError without template references should be execution_failure."""
    service = WorkflowExecutorService(output_interface=NullOutput())

    exception = ValueError("Something went wrong during processing")

    result = service._handle_execution_exception(exception)

    assert result["success"] is False
    assert result["errors"][0]["category"] == "execution_failure"


def test_handle_execution_exception_categorizes_api_validation() -> None:
    """ValueError with API validation patterns should be categorized as api_validation."""
    service = WorkflowExecutorService(output_interface=NullOutput())

    exception = ValueError("Invalid request data: field required for 'title'")

    result = service._handle_execution_exception(exception)

    assert result["errors"][0]["category"] == "api_validation"


def test_handle_execution_exception_includes_failed_node() -> None:
    """When shared_store has a failed_node, it should appear in the error dict."""
    service = WorkflowExecutorService(output_interface=NullOutput())

    exception = ValueError("Template ${step1.output} could not be resolved")
    shared_store: dict[str, Any] = {
        "__execution__": {"failed_node": "step2"},
    }

    result = service._handle_execution_exception(exception, shared_store=shared_store)

    assert result["errors"][0]["node_id"] == "step2"
    assert result["errors"][0]["category"] == "template_error"


# ---------------------------------------------------------------------------
# Fix 5: MCP _build_error_text includes shell details
# ---------------------------------------------------------------------------


def test_mcp_build_error_text_includes_shell_details(tmp_path: Any) -> None:
    """MCP error text should include shell command and stderr for agent diagnosis."""
    from pathlib import Path

    from pflow.mcp_server.services.execution_service import _build_error_text

    trace_path = Path(tmp_path / "trace.json")
    error_dict = {
        "error": {"message": "Shell command failed"},
        "errors": [
            {
                "node_id": "build",
                "message": "exit 1",
                "shell_command": "npm run build",
                "shell_stderr": "Error: Cannot find module 'webpack'",
            }
        ],
    }
    text = _build_error_text(error_dict, trace_path)
    assert "npm run build" in text
    assert "Cannot find module" in text
    assert "build" in text


def test_mcp_build_error_text_truncates_long_values(tmp_path: Any) -> None:
    """MCP error text truncates long commands and stderr."""
    from pathlib import Path

    from pflow.mcp_server.services.execution_service import _build_error_text

    trace_path = Path(tmp_path / "trace.json")
    error_dict = {
        "error": {"message": "Failed"},
        "errors": [
            {
                "node_id": "run",
                "message": "exit 1",
                "shell_command": "x" * 250,
                "shell_stderr": "y" * 350,
            }
        ],
    }
    text = _build_error_text(error_dict, trace_path)
    assert "..." in text  # Truncation happened
