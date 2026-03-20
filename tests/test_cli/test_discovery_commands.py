"""Tests for discovery commands (workflow discover & registry discover).

These tests validate CLI integration for LLM-powered discovery commands.
They mock the discovery functions (not internal LLM calls) to test CLI behavior.

Critical bugs these tests prevent:
1. Poor error messages when LLM unavailable
2. Missing or malformed output when discovery returns results
3. Graceful handling of empty queries and no-match scenarios
"""

from unittest.mock import patch

import click.testing

from pflow.cli.commands.registry import registry as registry_cmd
from pflow.cli.commands.workflow import workflow as workflow_cmd
from pflow.core.workflow.discovery import WorkflowMatch
from pflow.registry.discovery import ComponentSelection


class TestWorkflowDiscover:
    """Tests for 'pflow workflow discover' command."""

    def test_workflow_discover_with_mocked_llm(self):
        """Returns matching workflows when LLM available.

        Mocks discover_workflow() to return a successful WorkflowMatch.
        Verifies CLI formats name, description, confidence, and reasoning.
        """
        mock_result = WorkflowMatch(
            found=True,
            workflow_name="pr-analyzer",
            confidence=0.9,
            reasoning="Matches GitHub PR analysis task",
            workflow={
                "description": "Analyzes GitHub pull requests",
                "version": "1.0.0",
                "ir": {
                    "edges": [
                        {"from": "fetch-pr", "to": "analyze"},
                        {"from": "analyze", "to": "report"},
                    ],
                    "inputs": {
                        "repo": {"type": "str", "required": True, "description": "Repository name"},
                        "pr_number": {"type": "int", "required": True, "description": "PR number"},
                    },
                    "outputs": {
                        "analysis": {"type": "str", "description": "Analysis result"},
                    },
                },
            },
        )

        with patch("pflow.core.workflow.discovery.discover_workflow", return_value=mock_result):
            runner = click.testing.CliRunner()
            result = runner.invoke(workflow_cmd, ["discover", "analyze pull requests"])

        assert result.exit_code == 0
        assert "pr-analyzer" in result.output
        assert "Analyzes GitHub pull requests" in result.output
        assert "90%" in result.output  # Confidence
        assert "Matches GitHub PR analysis task" in result.output  # Reasoning

    def test_workflow_discover_calls_function_with_query(self):
        """Verifies the CLI passes the query and a WorkflowManager to discover_workflow().

        Previously tested that workflow_manager was in the shared store.
        Now verifies the function receives the expected arguments.
        """
        mock_result = WorkflowMatch(
            found=True,
            workflow_name="test",
            confidence=0.95,
            reasoning="Test match",
            workflow={"metadata": {}, "ir": {}},
        )

        with patch("pflow.core.workflow.discovery.discover_workflow", return_value=mock_result) as mock_fn:
            runner = click.testing.CliRunner()
            result = runner.invoke(workflow_cmd, ["discover", "test query"])

        assert result.exit_code == 0
        mock_fn.assert_called_once()
        call_args = mock_fn.call_args
        assert call_args[0][0] == "test query"  # First positional arg is the query
        # CLI passes workflow_manager as keyword argument
        assert "workflow_manager" in call_args[1]

    def test_workflow_discover_llm_unavailable(self):
        """Shows helpful message when LLM unavailable.

        Mocks discover_workflow() to raise RuntimeError.
        Verifies the CLI presents guidance to the user.
        """
        with patch(
            "pflow.core.workflow.discovery.discover_workflow",
            side_effect=RuntimeError("No LLM API keys configured. Please set ANTHROPIC_API_KEY or OPENAI_API_KEY."),
        ):
            runner = click.testing.CliRunner()
            result = runner.invoke(workflow_cmd, ["discover", "test query"])

        # Should fail but with helpful message
        assert result.exit_code != 0
        # Should contain helpful guidance (error message or alternatives)
        helpful_patterns = ["API key", "workflow list", "pflow workflow"]
        assert any(pattern.lower() in result.output.lower() for pattern in helpful_patterns)

    def test_workflow_discover_empty_query(self):
        """Handles empty or whitespace-only queries gracefully.

        No mock needed - tests CLI validation before any discovery call.
        """
        runner = click.testing.CliRunner()
        result = runner.invoke(workflow_cmd, ["discover", ""])

        # Click should reject empty argument before we even get to the function
        # But if it doesn't, we should still handle it gracefully
        assert result.exit_code != 0 or "no" in result.output.lower() or "not found" in result.output.lower()

    def test_workflow_discover_no_workflows_exist(self):
        """Handles empty workflow library gracefully.

        Mocks discover_workflow() to return WorkflowMatch(found=False).
        Verifies the CLI shows a "no match" message.
        """
        mock_result = WorkflowMatch(
            found=False,
            workflow_name=None,
            confidence=0.0,
            reasoning="No existing workflows match the query",
            workflow=None,
        )

        with patch("pflow.core.workflow.discovery.discover_workflow", return_value=mock_result):
            runner = click.testing.CliRunner()
            result = runner.invoke(workflow_cmd, ["discover", "test query"])

        assert result.exit_code == 0  # Not an error, just no matches
        assert "no" in result.output.lower() or "not found" in result.output.lower()


class TestRegistryDiscover:
    """Tests for 'pflow registry discover' command."""

    def test_registry_discover_with_mocked_llm(self):
        """Returns relevant nodes when LLM available.

        Mocks discover_components() to return a ComponentSelection with component_context.
        Verifies the CLI displays the context content.
        """
        mock_result = ComponentSelection(
            node_ids=["github-get-pr", "github-list-prs"],
            reasoning="Selected GitHub PR tools for the task",
            component_context="""## GitHub Operations

### github-get-pr
**Description**: Fetch pull request details
**Inputs**:
  - repo: str (required) - Repository name
  - pr_number: int (required) - PR number
**Outputs**:
  - pr_data: dict - PR information

### github-list-prs
**Description**: List pull requests
**Inputs**:
  - repo: str (required) - Repository name
  - state: str (optional) - PR state filter
""",
        )

        with patch("pflow.registry.discovery.discover_components", return_value=mock_result):
            runner = click.testing.CliRunner()
            result = runner.invoke(registry_cmd, ["discover", "fetch GitHub pull requests"])

        assert result.exit_code == 0
        assert "github-get-pr" in result.output
        assert "Fetch pull request details" in result.output
        assert "pr_number" in result.output

    def test_registry_discover_llm_unavailable(self):
        """Shows helpful message when LLM not configured.

        Mocks discover_components() to raise RuntimeError.
        Verifies the CLI presents guidance to the user.
        """
        with patch(
            "pflow.registry.discovery.discover_components",
            side_effect=RuntimeError("No LLM API keys configured. Please set ANTHROPIC_API_KEY or OPENAI_API_KEY."),
        ):
            runner = click.testing.CliRunner()
            result = runner.invoke(registry_cmd, ["discover", "test query"])

        # Should fail with helpful message
        assert result.exit_code != 0
        # Should contain helpful guidance (error message or alternatives)
        helpful_patterns = ["API key", "registry list", "pflow registry"]
        assert any(pattern.lower() in result.output.lower() for pattern in helpful_patterns)

    def test_workflow_discover_returns_success(self):
        """Verifies the workflow discover command works end-to-end with a mock.

        Replaces the old Anthropic monkey patch test - that patch was removed
        when discovery switched from PocketFlow nodes to plain functions.
        """
        mock_result = WorkflowMatch(
            found=True,
            workflow_name="test-workflow",
            confidence=0.85,
            reasoning="Good match",
            workflow={"metadata": {"description": "A test workflow"}, "ir": {}},
        )

        with patch("pflow.core.workflow.discovery.discover_workflow", return_value=mock_result):
            runner = click.testing.CliRunner()
            result = runner.invoke(workflow_cmd, ["discover", "test"])

        assert result.exit_code == 0
        assert "test-workflow" in result.output

    def test_registry_discover_calls_function_correctly(self):
        """Verifies discover_components is called with the user's query.

        Replaces the old test that checked workflow_manager in shared store.
        The new discover_components() handles its own dependencies internally.
        """
        mock_result = ComponentSelection(
            node_ids=["shell", "read-file"],
            reasoning="Selected for file processing",
            component_context="## File Processing\n\nSome context",
        )

        with patch("pflow.registry.discovery.discover_components", return_value=mock_result) as mock_fn:
            runner = click.testing.CliRunner()
            result = runner.invoke(registry_cmd, ["discover", "process files"])

        assert result.exit_code == 0
        mock_fn.assert_called_once_with("process files")
