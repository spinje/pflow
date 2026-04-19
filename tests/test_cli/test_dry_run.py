"""CLI integration tests for --dry-run."""

from __future__ import annotations

import json

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
