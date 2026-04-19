"""CLI integration tests for --dry-run."""

from __future__ import annotations

import json
from unittest.mock import patch

from tests.shared.markdown_utils import write_workflow_file
from tests.test_cli.test_workflow_commands import invoke_cli


def test_dry_run_does_not_execute_shell_node(tmp_path) -> None:
    """Dry-run must not trigger shell side effects."""
    proof = tmp_path / "proof.txt"
    workflow_path = tmp_path / "dry-run.pflow.md"
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "touch-proof",
                    "type": "shell",
                    "params": {"command": f"echo touched > {proof}; printf done"},
                }
            ],
            "edges": [],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 0
    assert "No side effects performed." in result.output
    assert not proof.exists()


def test_dry_run_json_output_is_valid_json(tmp_path) -> None:
    """Dry-run JSON output should be a single JSON document."""
    workflow_path = tmp_path / "dry-run-json.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}],
            "edges": [],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", "--output-format", "json", str(workflow_path)])
    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert set(payload) == {"workflow", "plan", "summary", "diagnostics"}


def test_dry_run_exits_zero_on_success(tmp_path) -> None:
    """Successful dry-run exits 0."""
    workflow_path = tmp_path / "dry-run-success.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}],
            "edges": [],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 0


def test_dry_run_exits_one_on_missing_required_input(tmp_path) -> None:
    """Planning failures should exit 1."""
    workflow_path = tmp_path / "dry-run-missing-input.pflow.md"
    write_workflow_file(
        {
            "inputs": {"name": {"type": "string", "required": True, "description": "Required name"}},
            "nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf ${name}"}}],
            "edges": [],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 1


def test_dry_run_text_output_contains_boundary_divider(tmp_path) -> None:
    """Fresh dry-run text output should include a cache divider."""
    workflow_path = tmp_path / "dry-run-text.pflow.md"
    write_workflow_file(
        {
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "printf a"}},
                {"id": "b", "type": "shell", "params": {"command": "printf ${a.stdout}"}},
            ],
            "edges": [{"from": "a", "to": "b"}],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 0
    assert "─── nothing cached — full run ───" in result.output


def test_dry_run_plus_validate_only_exits_one_with_clear_error(tmp_path) -> None:
    """--dry-run and --validate-only are mutually exclusive."""
    workflow_path = tmp_path / "dry-run-conflict.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}],
            "edges": [],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", "--validate-only", str(workflow_path)])

    assert result.exit_code == 1
    assert "Cannot combine --dry-run and --validate-only" in (result.output + result.stderr)


def test_dry_run_plus_report_exits_one_with_clear_error(tmp_path) -> None:
    """--dry-run and --report are mutually exclusive."""
    workflow_path = tmp_path / "dry-run-report.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}],
            "edges": [],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", "--report", str(workflow_path)])

    assert result.exit_code == 1
    assert "Cannot combine --dry-run and --report" in (result.output + result.stderr)


def test_dry_run_plus_no_trace_is_silent_accept(tmp_path) -> None:
    """--no-trace is accepted as a no-op for dry-run."""
    workflow_path = tmp_path / "dry-run-no-trace.pflow.md"
    write_workflow_file(
        {"nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}], "edges": []},
        workflow_path,
    )

    result = invoke_cli(["--dry-run", "--no-trace", str(workflow_path)])

    assert result.exit_code == 0


def test_dry_run_plus_print_is_silent_accept(tmp_path) -> None:
    """-p must not suppress the plan itself."""
    workflow_path = tmp_path / "dry-run-print.pflow.md"
    write_workflow_file(
        {"nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}], "edges": []},
        workflow_path,
    )

    result = invoke_cli(["--dry-run", "-p", str(workflow_path)])

    assert result.exit_code == 0
    assert "Plan for" in result.output


def test_dry_run_composes_with_only_node(tmp_path) -> None:
    """--only should stop the plan at the requested node."""
    workflow_path = tmp_path / "dry-run-only.pflow.md"
    write_workflow_file(
        {
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "printf a"}},
                {"id": "b", "type": "shell", "params": {"command": "printf b"}},
            ],
            "edges": [{"from": "a", "to": "b"}],
        },
        workflow_path,
    )

    result = invoke_cli(["--dry-run", "--output-format", "json", "--only", "a", str(workflow_path)])
    payload = json.loads(result.output)

    assert result.exit_code == 0
    assert [entry["node_id"] for entry in payload["plan"]] == ["a"]


def test_dry_run_no_network_calls(tmp_path) -> None:
    """Planner must not execute HTTP or LLM nodes."""
    workflow_path = tmp_path / "dry-run-no-network.pflow.md"
    write_workflow_file(
        {
            "nodes": [
                {
                    "id": "http-step",
                    "type": "http",
                    "params": {"url": "https://example.com", "method": "GET"},
                },
                {
                    "id": "llm-step",
                    "type": "llm",
                    "params": {"prompt": "hello", "model": "gpt-4"},
                },
            ],
            "edges": [{"from": "http-step", "to": "llm-step"}],
        },
        workflow_path,
    )

    with patch("requests.request") as mock_request, patch("llm.get_model") as mock_get_model:
        result = invoke_cli(["--dry-run", str(workflow_path)])

    assert result.exit_code == 0
    assert mock_request.call_count == 0
    assert mock_get_model.call_count == 0
