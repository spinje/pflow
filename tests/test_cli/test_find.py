"""Tests for the top-level `pflow find` command."""

from unittest.mock import patch

import click.testing

from pflow.cli.commands.find import find_cmd
from pflow.core.workflow.discovery import WorkflowMatch


def test_find_returns_matching_workflow() -> None:
    mock_result = WorkflowMatch(
        found=True,
        workflow_name="pr-analyzer",
        confidence=0.9,
        reasoning="Matches GitHub PR analysis task",
        workflow={
            "description": "Analyzes GitHub pull requests",
            "version": "1.0.0",
            "ir": {
                "inputs": {"repo": {"type": "string", "required": True, "description": "Repository name"}},
                "outputs": {"analysis": {"type": "string", "description": "Analysis result"}},
            },
        },
    )

    with patch("pflow.core.workflow.discovery.find_workflow", return_value=mock_result):
        result = click.testing.CliRunner().invoke(find_cmd, ["analyze pull requests"])

    assert result.exit_code == 0
    assert "pr-analyzer" in result.output
    assert "Analyzes GitHub pull requests" in result.output
    assert "90%" in result.output


def test_find_calls_discovery_with_workflow_manager() -> None:
    mock_result = WorkflowMatch(
        found=True,
        workflow_name="test",
        confidence=0.95,
        reasoning="Test match",
        workflow={"metadata": {}, "ir": {}},
    )

    with patch("pflow.core.workflow.discovery.find_workflow", return_value=mock_result) as mock_fn:
        result = click.testing.CliRunner().invoke(find_cmd, ["test query"])

    assert result.exit_code == 0
    mock_fn.assert_called_once()
    assert mock_fn.call_args[0][0] == "test query"
    assert "workflow_manager" in mock_fn.call_args[1]


def test_find_no_match_shows_guidance() -> None:
    """When no workflow matches, find should display guidance — not crash."""
    mock_result = WorkflowMatch(
        found=False,
        workflow_name=None,
        confidence=0.0,
        reasoning="No workflows match the description",
        workflow=None,
    )

    with patch("pflow.core.workflow.discovery.find_workflow", return_value=mock_result):
        result = click.testing.CliRunner().invoke(find_cmd, ["nonexistent thing"])

    assert result.exit_code == 0
    assert "no" in result.output.lower() or "match" in result.output.lower()


def test_find_handles_discovery_errors() -> None:
    with patch(
        "pflow.core.workflow.discovery.find_workflow",
        side_effect=RuntimeError("No LLM API keys configured."),
    ):
        result = click.testing.CliRunner().invoke(find_cmd, ["test query"])

    assert result.exit_code != 0
    assert "API key" in result.output or "pflow list" in result.output
