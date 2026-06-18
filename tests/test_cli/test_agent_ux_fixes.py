"""Tests for agent UX fixes — five targeted behavioral changes.

Fix 1: Shell stderr always visible (no verbose gate)
Fix 2a: Trace file "degraded" status when warnings present
Fix 2b: CLI exit code 0 for degraded workflows
Fix 3: Nested workflow child node ID in error message
Fix 4: Error category uses _determine_error_category (not hardcoded)
"""

from typing import Any
from unittest.mock import patch

from pflow.cli.workflow_errors import _display_single_error
from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.workflow.status import WorkflowStatus
from pflow.execution.executor_service import determine_error_category
from pflow.execution.result import ExecutionResult
from pflow.runtime.workflow_executor import WorkflowExecutor
from pflow.runtime.workflow_trace import WorkflowTraceCollector

# ---------------------------------------------------------------------------
# Fix 1: Shell stderr always visible (no verbose gate)
# ---------------------------------------------------------------------------


def test_shell_stderr_shown_without_verbose() -> None:
    """Shell command and stderr are displayed even when verbose=False.

    Previously, shell details were gated behind the verbose flag.
    Now they are always shown when shell_command is present in the error,
    because agents need stderr for diagnosis regardless of verbose mode.
    """
    error = Diagnostic(
        severity=Severity.ERROR,
        message="Shell command failed with exit code 1",
        node_id="run-build",
        source="runtime",
        context={
            "category": "execution_failure",
            "shell_command": "npm run build",
            "shell_stderr": "Error: Cannot find module 'react'",
        },
    )

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
    error = Diagnostic(
        severity=Severity.ERROR,
        message="Shell command failed",
        node_id="run-tests",
        source="runtime",
        context={
            "category": "execution_failure",
            "shell_command": "pytest tests/",
            "shell_stdout": "FAILED tests/test_foo.py::test_bar",
            "shell_stderr": "1 failed, 5 passed",
        },
    )

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


def test_single_cli_error_is_not_numbered() -> None:
    """Single-error display should omit the redundant "Error 1" label.

    The unified titled format renders "Error: <title>" for a single error
    (error_number=None) and "Error N: <title>" for multiple errors.
    """
    error = Diagnostic(
        severity=Severity.ERROR,
        message="Shell command failed with exit code 1",
        title="Execution Failed",
        node_id="run-build",
        source="runtime",
        context={
            "category": "execution_failure",
            "shell_command": "npm run build",
        },
    )

    captured: list[str] = []

    def capture_echo(message: Any = "", err: bool = False, **kwargs: Any) -> None:
        if err:
            captured.append(str(message))

    with patch("pflow.cli.workflow_errors.click.echo", side_effect=capture_echo):
        _display_single_error(error, error_number=None, verbose=False)

    output = "\n".join(captured)
    # Unified titled format: "Error: Execution Failed" (no number for single error)
    assert "Error: Execution Failed" in output
    assert "Error 1:" not in output


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
# Fix 2b: CLI exit code 0 for degraded workflows
# ---------------------------------------------------------------------------


def test_degraded_workflow_exits_with_code_0(tmp_path) -> None:
    """A successful but degraded workflow should still exit with code 0.

    Warnings remain visible in status, stderr, JSON, traces, and reports. The
    process exit code distinguishes completed execution from failed execution.
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
    with patch("pflow.execution.runner.WorkflowRunner.run", return_value=degraded_result):
        result = runner.invoke(main, [str(wf_path)])

    assert result.exit_code == 0


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
    with patch("pflow.execution.runner.WorkflowRunner.run", return_value=success_result):
        result = runner.invoke(main, [str(wf_path)])

    assert result.exit_code == 0


def test_failed_workflow_exits_with_code_1(tmp_path) -> None:
    """Failed execution remains non-zero after degraded success moves to exit 0."""
    from click.testing import CliRunner

    from pflow.cli.main import main
    from tests.shared.markdown_utils import write_workflow_file

    workflow = {
        "nodes": [{"id": "n1", "type": "shell", "params": {"command": "exit 1"}}],
        "edges": [],
    }
    wf_path = tmp_path / "test.pflow.md"
    write_workflow_file(workflow, wf_path)

    failed_result = ExecutionResult(
        success=False,
        status=WorkflowStatus.FAILED,
        shared_after={},
        diagnostics=[
            Diagnostic(
                severity=Severity.ERROR,
                title="Execution Failed",
                message="Shell command failed with exit code 1",
                node_id="n1",
                source="runtime",
                context={"category": "execution_failure"},
            )
        ],
    )

    runner = CliRunner()
    with patch("pflow.execution.runner.WorkflowRunner.run", return_value=failed_result):
        result = runner.invoke(main, [str(wf_path)])

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Fix 3: Nested workflow child node ID in error message
# ---------------------------------------------------------------------------


def test_extract_child_error_includes_node_id() -> None:
    """Error message from sub-workflow failure should include the failed node ID.

    Previously the message only said 'Sub-workflow failed at <path>'. Now it
    includes the specific child node that failed, helping agents locate the issue.
    """
    from pflow.runtime.node_state import FAILURE_CATEGORY_EXCEPTION, mark_node_failed

    child_storage: dict[str, Any] = {
        "__execution__": {"failed_node": "my-shell-node"},
        "my-shell-node": {"error": "Command failed with exit code 127"},
    }
    mark_node_failed(
        child_storage,
        "my-shell-node",
        category=FAILURE_CATEGORY_EXCEPTION,
        error="Command failed with exit code 127",
    )

    message = WorkflowExecutor._extract_child_failure(child_storage, "./child.pflow.md")["error"]

    assert "my-shell-node" in message
    assert "Command failed with exit code 127" in message
    assert "./child.pflow.md" in message


def test_extract_child_error_fallback_without_failed_node() -> None:
    """Without a failed_node, the error message should use the generic fallback."""
    child_storage: dict[str, Any] = {
        "__execution__": {},
    }

    message = WorkflowExecutor._extract_child_failure(child_storage, "./child.pflow.md")["error"]

    assert "./child.pflow.md" in message
    assert "returned error action" in message


def test_extract_child_error_fallback_no_error_in_node_data() -> None:
    """If the failed node's data has no 'error' key, use the generic fallback."""
    from pflow.runtime.node_state import FAILURE_CATEGORY_EXCEPTION, mark_node_failed

    child_storage: dict[str, Any] = {
        "__execution__": {"failed_node": "some-node"},
        "some-node": {"stdout": "some output but no error key"},
    }
    mark_node_failed(child_storage, "some-node", category=FAILURE_CATEGORY_EXCEPTION)

    message = WorkflowExecutor._extract_child_failure(child_storage, "./workflow.pflow.md")["error"]

    assert "returned error action" in message


# ---------------------------------------------------------------------------
# Fix 4: Error category uses _determine_error_category (not hardcoded)
# ---------------------------------------------------------------------------


def test_determine_error_category_template_error_falls_through_to_execution_failure() -> None:
    """Regex-on-message heuristic was removed: since Task 148, template errors
    carry ``category=FAILURE_CATEGORY_TEMPLATE`` in the failure record and the
    category flows through ``_map_failure_category_to_diagnostic`` — never
    through this regex path. Messages containing ``${`` used to be guessed as
    ``template_error`` here, which mis-categorized shell commands that
    legitimately echoed ``${PATH}``. Now they fall through cleanly.
    """
    assert determine_error_category("Failed to resolve template ${node.output} in params") == "execution_failure"


def test_determine_error_category_generic_error() -> None:
    """A generic message without API validation patterns is execution_failure."""
    assert determine_error_category("Something went wrong during processing") == "execution_failure"


def test_determine_error_category_api_validation() -> None:
    """Message with API validation patterns should be categorized as api_validation."""
    assert determine_error_category("Invalid request data: field required for 'title'") == "api_validation"


def test_runner_exception_to_result_includes_category() -> None:
    """WorkflowRunner._exception_to_result preserves error categorization."""
    from pflow.execution.runner import WorkflowRunner

    runner = WorkflowRunner()
    exception = ValueError("Template ${step1.output} could not be resolved")

    result = runner._exception_to_result(exception, 0.0, None)

    assert result.success is False
    assert (result.errors[0].context or {}).get("category") == "validation"  # ValueError → validation category


# ---------------------------------------------------------------------------
# Fix 5: MCP _build_error_text includes shell details
# ---------------------------------------------------------------------------


def test_mcp_build_error_text_includes_shell_details() -> None:
    """MCP error text should include shell command and stderr for agent diagnosis."""
    from pflow.mcp_server.services.execution_service import _build_error_text

    errors = [
        Diagnostic(
            severity=Severity.ERROR,
            message="exit 1",
            node_id="build",
            source="runtime",
            context={
                "category": "execution_failure",
                "shell_command": "npm run build",
                "shell_stderr": "Error: Cannot find module 'webpack'",
            },
        )
    ]
    text = _build_error_text(errors, warnings=[], trace_path="")
    assert "npm run build" in text
    assert "Cannot find module" in text
    assert "build" in text


def test_mcp_build_error_text_truncates_long_values(tmp_path: Any) -> None:
    """MCP error text truncates long commands and stderr."""
    from pflow.mcp_server.services.execution_service import _build_error_text

    errors = [
        Diagnostic(
            severity=Severity.ERROR,
            message="exit 1",
            node_id="run",
            source="runtime",
            context={
                "category": "execution_failure",
                "shell_command": "x" * 250,
                "shell_stderr": "y" * 350,
            },
        )
    ]
    text = _build_error_text(errors, warnings=[], trace_path="")
    assert "..." in text  # Truncation happened
