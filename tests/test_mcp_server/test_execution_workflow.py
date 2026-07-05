"""Tests for ExecutionService.execute_workflow() behavioral contract.

These tests establish a baseline for the execute_workflow() method before
Task 138 rewrites the shared execution pipeline. They verify the public
contract: success returns str, validation errors raise ValueError,
execution errors raise RuntimeError.

Coverage: file workflows, library workflows, not-found, validation failure,
execution failure.
"""

import pytest

from pflow.core.workflow.manager import WorkflowManager
from pflow.mcp_server.services.execution_service import ExecutionService
from tests.shared.markdown_utils import write_workflow_file

# --- IR dicts for test workflows ---

SIMPLE_ECHO_IR = {
    "nodes": [
        {
            "id": "greet",
            "type": "shell",
            "params": {"command": "echo hello"},
            "purpose": "Echo a greeting message",
        }
    ],
}

UNKNOWN_NODE_TYPE_IR = {
    "nodes": [
        {
            "id": "bad",
            "type": "nonexistent-node-type-xyz",
            "params": {},
            "purpose": "This node type does not exist in registry",
        }
    ],
}

FAILING_COMMAND_IR = {
    "nodes": [
        {
            "id": "fail",
            "type": "shell",
            "params": {"command": "exit 1"},
            "purpose": "Command that will fail with exit code 1",
        }
    ],
}


def _large_batch_failure_ir() -> dict:
    payload = "PAYLOAD-START " + " ".join(f"token{i}" for i in range(200)) + " PAYLOAD-END"
    return {
        "nodes": [
            {
                "id": "fail-batch",
                "type": "shell",
                "params": {"command": 'echo "forced batch failure for ${item.label}" >&2; exit 1'},
                "batch": {
                    "items": [{"label": "oversized-item", "payload": payload}],
                    "error_handling": "fail_fast",
                },
            }
        ]
    }


class TestExecuteWorkflowSuccess:
    """Tests for successful workflow execution paths."""

    def test_file_workflow_returns_success_string(self, tmp_path):
        """When given a valid .pflow.md file path, execute_workflow returns
        a success string with completion text and workflow output."""
        workflow_path = tmp_path / "echo.pflow.md"
        write_workflow_file(SIMPLE_ECHO_IR, workflow_path)

        result = ExecutionService.execute_workflow(str(workflow_path))

        assert isinstance(result, str), f"Expected str, got {type(result).__name__}"
        assert "Workflow completed" in result, "Success output should contain completion text"
        assert "Workflow output:" in result, "Success output should include the workflow output header"
        assert "hello" in result, "Success output should include the workflow output value"

    def test_file_workflow_surfaces_parser_info_advisory(self, tmp_path):
        workflow_path = tmp_path / "typo.pflow.md"
        workflow_path.write_text(
            "# Typo\n\n"
            "## Input\n\n"
            "### api-key\n\n"
            "Unused typo.\n\n"
            "- type: string\n\n"
            "## Steps\n\n"
            "### echo\n\n"
            "Echo hello.\n\n"
            "- type: shell\n"
            "- cache: false\n"
            "- command: echo hello\n",
            encoding="utf-8",
        )

        result = ExecutionService.execute_workflow(str(workflow_path))

        assert "Workflow completed" in result
        assert "Advisories:" in result
        assert "## Input" in result
        assert "## Inputs" in result

    def test_library_workflow_returns_success_string(self, isolate_pflow_config):
        """When given a saved workflow name, execute_workflow resolves it
        from the library and returns a success string."""
        # Save a workflow to the isolated library
        wm = WorkflowManager()
        from tests.shared.markdown_utils import ir_to_markdown

        markdown_content = ir_to_markdown(SIMPLE_ECHO_IR, title="Test Echo")
        wm.save("test-echo-lib", markdown_content)

        result = ExecutionService.execute_workflow("test-echo-lib")

        assert isinstance(result, str), f"Expected str, got {type(result).__name__}"
        assert "Workflow completed" in result, "Success output should contain completion text"
        assert "Workflow output:" in result, "Success output should include the workflow output header"
        assert "hello" in result, "Success output should include the workflow output value"


class TestExecuteWorkflowErrors:
    """Tests for error paths: not found, validation failure, execution failure."""

    def test_nonexistent_workflow_raises_value_error(self):
        """When given a workflow name that does not exist anywhere,
        execute_workflow raises ValueError with 'not found' in the message."""
        with pytest.raises(ValueError, match=r"(?i)not found"):
            ExecutionService.execute_workflow("nonexistent-workflow-xyz")

    def test_unknown_node_type_raises_validation_error(self, tmp_path):
        """When a workflow references an unknown node type,
        execute_workflow raises an error mentioning the invalid type.

        Note: The docstring claims ValueError for validation failures, but
        the implementation wraps it as RuntimeError because the ValueError
        is raised inside a try/except that catches all non-RuntimeError
        exceptions and re-wraps them. This test documents actual behavior.
        """
        workflow_path = tmp_path / "bad-node.pflow.md"
        write_workflow_file(UNKNOWN_NODE_TYPE_IR, workflow_path)

        with pytest.raises(RuntimeError) as exc_info:
            ExecutionService.execute_workflow(str(workflow_path))

        error_text = str(exc_info.value).lower()
        assert "nonexistent-node-type-xyz" in error_text, "Validation error should mention the invalid node type"

    def test_failing_command_raises_runtime_error(self, tmp_path):
        """When a shell node command fails (exit 1), execute_workflow
        raises RuntimeError."""
        workflow_path = tmp_path / "fail.pflow.md"
        write_workflow_file(FAILING_COMMAND_IR, workflow_path)

        with pytest.raises(RuntimeError):
            ExecutionService.execute_workflow(str(workflow_path))

    def test_failure_surfaces_parser_info_advisory(self, tmp_path):
        workflow_path = tmp_path / "fail-with-typo.pflow.md"
        workflow_path.write_text(
            "# Typo Failure\n\n"
            "## Input\n\n"
            "### api-key\n\n"
            "Unused typo.\n\n"
            "- type: string\n\n"
            "## Steps\n\n"
            "### fail\n\n"
            "Fail intentionally.\n\n"
            "- type: shell\n"
            "- cache: false\n"
            "- command: exit 1\n",
            encoding="utf-8",
        )

        with pytest.raises(RuntimeError) as exc_info:
            ExecutionService.execute_workflow(str(workflow_path))

        text = str(exc_info.value)
        assert "Advisories:" in text
        assert "## Input" in text
        assert "## Inputs" in text

    def test_large_batch_failure_text_uses_compact_item_summary(self, tmp_path):
        workflow_path = tmp_path / "large-batch-fail.pflow.md"
        write_workflow_file(_large_batch_failure_ir(), workflow_path)

        with pytest.raises(RuntimeError) as exc_info:
            ExecutionService.execute_workflow(str(workflow_path))

        text = str(exc_info.value)
        assert "fail-batch" in text
        assert "[0]" in text
        assert "oversized-item" in text
        assert "forced batch failure" in text
        assert "payload=<str" in text
        assert "PAYLOAD-START" not in text
        assert "PAYLOAD-END" not in text
        assert "token199" not in text
        assert "batch_error_details" not in text
        assert "item_summary" not in text
        assert "__failures__" not in text


GATED_IR = {
    "nodes": [
        {
            "id": "prep",
            "type": "shell",
            "params": {"command": "echo ready"},
            "purpose": "Plain upstream step before the gate",
        },
        {
            "id": "guarded",
            "type": "shell",
            "params": {"command": "echo do-it"},
            "purpose": "Gated step requiring human approval",
            "approval": "required",
        },
    ],
    "edges": [{"from": "prep", "to": "guarded"}],
}


class TestExecuteWorkflowPaused:
    """Task 171 — MCP durable pause: paused is a RESULT (token + gate content),
    never a raised error; success responses gain run identity."""

    def test_paused_run_returns_token_and_gate_content(self, tmp_path):
        workflow_path = tmp_path / "gated.pflow.md"
        write_workflow_file(dict(GATED_IR), workflow_path)

        text = ExecutionService.execute_workflow(str(workflow_path))

        assert "status: paused" in text
        assert "paused_node_id: guarded" in text
        # The token is real and the resume command is kind-correct.
        exec_id = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("execution_id: "))
        assert f"resume_command: pflow resume {exec_id} --approve yes|no" in text
        # Gate content is rendered — an agent can show its human WHAT is gated.
        assert "do-it" in text

    def test_auto_approved_gate_still_succeeds(self, tmp_path):
        workflow_path = tmp_path / "gated-approved.pflow.md"
        write_workflow_file(dict(GATED_IR), workflow_path)

        text = ExecutionService.execute_workflow(str(workflow_path), auto_approve=["guarded"])

        assert "✓ Workflow completed" in text
        assert "status: paused" not in text

    def test_success_text_carries_execution_id(self, tmp_path):
        """Run identity renders even when no trace file exists (streaming is
        suppressed here by the autouse no-op) — and it is a real id, never a
        rendered "None". The identity↔trace-file cross-check lives in the
        trace_files test below."""
        import uuid

        workflow_path = tmp_path / "simple.pflow.md"
        write_workflow_file(dict(SIMPLE_ECHO_IR), workflow_path)

        text = ExecutionService.execute_workflow(str(workflow_path))

        exec_id = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("execution_id: "))
        uuid.UUID(exec_id)  # raises if the line rendered a non-id (e.g. "None")

    def test_stream_faulted_pause_raises_not_a_dead_token(self, tmp_path, monkeypatch):
        """Pause = promise, on the MCP surface too. If the trace stream dies
        mid-run there is no on-disk trailer, so the token would never resolve.
        MCP gates on ``is_durable_pause`` (the same guard the CLI applies) and
        falls through to the error path (the gate's ask-your-human remediation),
        never advertising an unanswerable token. Simulate the disk fault by
        flipping ``_stream_failed`` on the real paused run's collector."""
        from pflow.execution.runner import WorkflowRunner

        workflow_path = tmp_path / "gated-faulted.pflow.md"
        write_workflow_file(dict(GATED_IR), workflow_path)

        real_run = WorkflowRunner.run

        def faulting_run(self, *args, **kwargs):
            result = real_run(self, *args, **kwargs)
            if result.trace is not None:
                result.trace._stream_failed = True  # the stream died mid-run
            return result

        monkeypatch.setattr(WorkflowRunner, "run", faulting_run)

        with pytest.raises(RuntimeError) as exc_info:
            ExecutionService.execute_workflow(str(workflow_path))

        msg = str(exc_info.value)
        # NOT the durable-pause response — no token, no resume command advertised.
        assert "status: paused" not in msg
        assert "resume_command:" not in msg
        # IS the gate-needs-a-human remediation (parity with a --no-trace gate).
        assert "human" in msg.lower()

    @pytest.mark.trace_files
    def test_mcp_run_streams_a_real_trace(self, tmp_path, monkeypatch):
        """Task 171 flips MCP to trace streaming: the response's trace_path is a
        real, complete (finalized) file whose identity MATCHES the rendered
        execution_id — no post-171 MCP run is invisible to resume/analyze-cache,
        and the id an agent captures resolves against that exact trace."""
        import json as _json
        from pathlib import Path as _Path

        monkeypatch.setattr(_Path, "home", lambda: tmp_path)
        workflow_path = tmp_path / "simple.pflow.md"
        write_workflow_file(dict(SIMPLE_ECHO_IR), workflow_path)

        text = ExecutionService.execute_workflow(str(workflow_path))

        trace_path = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("trace_path: "))
        trace_file = _Path(trace_path)
        assert trace_file.exists()
        lines = trace_file.read_text(encoding="utf-8").splitlines()
        assert _json.loads(lines[-1])["kind"] == "run.complete"
        # Identity cross-check: the text's execution_id IS this trace's run id.
        exec_id = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("execution_id: "))
        assert _json.loads(lines[0])["execution_id"] == exec_id
