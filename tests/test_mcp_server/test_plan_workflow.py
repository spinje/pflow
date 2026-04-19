"""Tests for ExecutionService.plan_workflow()."""

from __future__ import annotations

import pytest

from pflow.mcp_server.services.execution_service import ExecutionService
from tests.shared.markdown_utils import write_workflow_file


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


def test_plan_workflow_not_found_raises_value_error_with_suggestion() -> None:
    """Unknown workflow names should raise ValueError."""
    with pytest.raises(ValueError, match="(?i)not found"):
        ExecutionService.plan_workflow("definitely-not-a-real-workflow")


def test_plan_workflow_compile_error_raises_runtime_error(tmp_path) -> None:
    """Planner failures surface as RuntimeError from the service boundary."""
    workflow_path = tmp_path / "broken-plan.pflow.md"
    write_workflow_file(
        {
            "nodes": [{"id": "bad", "type": "nonexistent-node-type-xyz", "params": {}}],
            "edges": [],
        },
        workflow_path,
    )

    with pytest.raises(RuntimeError, match="Workflow planning failed"):
        ExecutionService.plan_workflow(str(workflow_path))
