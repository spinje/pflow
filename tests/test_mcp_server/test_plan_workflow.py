"""Tests for ExecutionService.plan_workflow()."""

from __future__ import annotations

import json

import pytest

from pflow.mcp_server.services.execution_service import ExecutionService
from tests.shared.markdown_utils import write_workflow_file
from tests.test_cli.test_workflow_commands import invoke_cli


def test_plan_workflow_returns_dict_with_expected_keys(tmp_path) -> None:
    """Service returns the dry-run JSON shape."""
    workflow_path = tmp_path / "plan-service.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}],
            "edges": [],
        },
        workflow_path,
    )

    result = ExecutionService.plan_workflow(str(workflow_path))

    assert isinstance(result, dict)
    assert set(result) == {"workflow", "plan", "summary", "diagnostics"}


def test_plan_workflow_matches_cli_json_shape(tmp_path) -> None:
    """MCP plan_workflow should match the CLI dry-run JSON output exactly.

    Deep-compares the scalars that agents act on (summary totals, per-entry
    status/cause). A pure key-set comparison would pass even if MCP reported
    `status="cached"` while CLI reported `status="execute"` — that's the
    parity failure mode the test needs to catch.
    """
    workflow_path = tmp_path / "plan-shape.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "echo", "type": "shell", "params": {"command": "printf hi"}}],
            "edges": [],
        },
        workflow_path,
    )

    service_result = ExecutionService.plan_workflow(str(workflow_path))
    cli_result = invoke_cli(["--dry-run", "--output-format", "json", str(workflow_path)])
    cli_payload = json.loads(cli_result.output)

    # Top-level keys match.
    assert set(service_result) == set(cli_payload)

    # Summary scalars match (totals, counts, cost basis).
    service_summary = service_result["summary"]
    cli_summary = cli_payload["summary"]
    assert set(service_summary) == set(cli_summary)
    for key in ("total", "cached_count", "execute_count", "cache_boundary", "cost_basis"):
        assert service_summary[key] == cli_summary[key], (
            f"summary.{key} mismatch: service={service_summary[key]!r} cli={cli_summary[key]!r}"
        )

    # Per-entry status + cause match (the fields agents use for decisions).
    assert len(service_result["plan"]) == len(cli_payload["plan"])
    for service_entry, cli_entry in zip(service_result["plan"], cli_payload["plan"], strict=True):
        assert service_entry["node_id"] == cli_entry["node_id"]
        assert service_entry["status"] == cli_entry["status"]
        assert service_entry["cause"] == cli_entry["cause"]


def test_plan_workflow_not_found_raises_value_error_with_suggestion() -> None:
    """Unknown workflow names should raise ValueError."""
    with pytest.raises(ValueError, match="(?i)not found"):
        ExecutionService.plan_workflow("definitely-not-a-real-workflow")


def test_plan_workflow_validation_failure_raises_value_error(tmp_path) -> None:
    """Validation failures (unknown node type, etc.) raise ValueError with
    the full structured diagnostic — not a flattened RuntimeError.

    Mutation: revert the `except WorkflowValidationError` / `except
    (CompilationError, MarkdownParseError)` branches in `plan_workflow` →
    the error surfaces as a bare RuntimeError and this assertion fails.
    """
    workflow_path = tmp_path / "broken-plan.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "bad", "type": "nonexistent-node-type-xyz", "params": {}}],
            "edges": [],
        },
        workflow_path,
    )

    with pytest.raises(ValueError) as excinfo:
        ExecutionService.plan_workflow(str(workflow_path))
    # Structured diagnostics survive — the agent sees the validation-failure
    # header and the node-type error, not just a flat "Workflow planning failed".
    assert "Validation failed" in str(excinfo.value)
    assert "nonexistent-node-type-xyz" in str(excinfo.value)
