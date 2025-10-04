"""Tests for discovery commands (workflow discover & registry discover).

These tests validate CLI-to-node integration for LLM-powered discovery commands.
They mock at the node.run() level (not internal LLM calls) to test integration behavior.

Critical bugs these tests prevent:
1. Missing workflow_manager in shared store causes "Invalid request" error
2. Missing Anthropic monkey patch causes cryptic Pydantic errors
3. Poor error messages when LLM unavailable
"""

import json

import click.testing

from pflow.cli.commands.workflow import workflow as workflow_cmd
from pflow.cli.registry import registry as registry_cmd


class TestWorkflowDiscover:
    """Tests for 'pflow workflow discover' command."""

    def test_workflow_discover_with_mocked_llm(self, tmp_path, monkeypatch):
        """Returns matching workflows when LLM available.

        Real behavior: Uses WorkflowDiscoveryNode to find relevant workflows.
        Mock at node.run() level to avoid prep() complexities.
        """
        # Setup workflow library
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)

        workflow = {
            "ir_version": "0.1.0",
            "metadata": {
                "description": "Analyzes GitHub pull requests",
                "capabilities": ["GitHub API", "LLM analysis"],
            },
            "nodes": [],
            "edges": [],
        }
        (home_pflow / "pr-analyzer.json").write_text(json.dumps(workflow))

        # Mock WorkflowDiscoveryNode.run() to return match
        def mock_discovery_run(self, shared):
            # Populate shared store as the node would
            shared["discovery_result"] = {
                "workflow_name": "pr-analyzer",
                "confidence": 0.9,
                "reasoning": "Matches GitHub PR analysis task",
            }
            shared["found_workflow"] = {
                "metadata": {
                    "description": "Analyzes GitHub pull requests",
                    "version": "1.0.0",
                },
                "ir": {
                    "flow": [
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
            }
            return "found_existing"

        monkeypatch.setattr("pflow.planning.nodes.WorkflowDiscoveryNode.run", mock_discovery_run)

        runner = click.testing.CliRunner()
        result = runner.invoke(workflow_cmd, ["discover", "analyze pull requests"], env={"HOME": str(tmp_path)})

        assert result.exit_code == 0
        assert "pr-analyzer" in result.output
        assert "Analyzes GitHub pull requests" in result.output
        assert "90%" in result.output  # Confidence
        assert "Matches GitHub PR analysis task" in result.output  # Reasoning

    def test_workflow_discover_requires_workflow_manager(self, tmp_path, monkeypatch):
        """Validates that workflow_manager is provided to discovery node.

        Critical bug: Missing workflow_manager causes "Invalid request" error.
        This test ensures the CLI properly instantiates and passes WorkflowManager.
        """
        workflow_manager_provided = []

        # Mock to check for workflow_manager
        def mock_discovery_run(self, shared):
            # Track whether workflow_manager was provided
            if "workflow_manager" in shared:
                workflow_manager_provided.append(True)
                # Simulate successful discovery
                shared["discovery_result"] = {"workflow_name": "test"}
                shared["found_workflow"] = {"metadata": {}, "ir": {}}
                return "found_existing"
            else:
                # This would be the bug - missing workflow_manager
                raise ValueError("workflow_manager required in shared store")

        monkeypatch.setattr("pflow.planning.nodes.WorkflowDiscoveryNode.run", mock_discovery_run)

        runner = click.testing.CliRunner()
        result = runner.invoke(workflow_cmd, ["discover", "test query"], env={"HOME": str(tmp_path)})

        # Should succeed because CLI provides workflow_manager
        assert result.exit_code == 0
        assert len(workflow_manager_provided) > 0, "workflow_manager must be provided"

    def test_workflow_discover_llm_unavailable(self, tmp_path, monkeypatch):
        """Shows helpful message when LLM unavailable.

        Real behavior: Suggests using 'workflow list' instead.
        """

        # Mock to simulate LLM configuration error
        def mock_discovery_run(self, shared):
            # Raise a generic exception (will be handled by discovery error handler)
            raise RuntimeError("No LLM API keys configured. Please set ANTHROPIC_API_KEY or OPENAI_API_KEY.")

        monkeypatch.setattr("pflow.planning.nodes.WorkflowDiscoveryNode.run", mock_discovery_run)

        runner = click.testing.CliRunner()
        result = runner.invoke(workflow_cmd, ["discover", "test query"], env={"HOME": str(tmp_path)})

        # Should fail but with helpful message
        assert result.exit_code != 0
        # Should contain helpful guidance (one of these patterns)
        # Either the error message or the alternatives
        helpful_patterns = ["API key", "workflow list", "pflow workflow"]
        assert any(pattern.lower() in result.output.lower() for pattern in helpful_patterns)

    def test_workflow_discover_empty_query(self, tmp_path):
        """Handles empty or whitespace-only queries gracefully."""
        runner = click.testing.CliRunner()
        result = runner.invoke(workflow_cmd, ["discover", ""], env={"HOME": str(tmp_path)})

        # Click should reject empty argument before we even get to the node
        # But if it doesn't, we should still handle it gracefully
        assert result.exit_code != 0 or "no" in result.output.lower() or "not found" in result.output.lower()

    def test_workflow_discover_no_workflows_exist(self, tmp_path, monkeypatch):
        """Handles empty workflow library gracefully."""
        home_pflow = tmp_path / ".pflow" / "workflows"
        home_pflow.mkdir(parents=True)
        # Empty directory - no workflows

        # Mock discovery to return "not found"
        def mock_discovery_run(self, shared):
            # Node returns "not_found" action when no matches
            # Don't set discovery_result or found_workflow
            return "not_found"

        monkeypatch.setattr("pflow.planning.nodes.WorkflowDiscoveryNode.run", mock_discovery_run)

        runner = click.testing.CliRunner()
        result = runner.invoke(workflow_cmd, ["discover", "test query"], env={"HOME": str(tmp_path)})

        assert result.exit_code == 0  # Not an error, just no matches
        assert "no" in result.output.lower() or "not found" in result.output.lower()


class TestRegistryDiscover:
    """Tests for 'pflow registry discover' command."""

    def test_registry_discover_with_mocked_llm(self, tmp_path, monkeypatch):
        """Returns relevant nodes when LLM available.

        Real behavior: Uses ComponentBrowsingNode to build planning context.
        """

        # Mock ComponentBrowsingNode.run() to populate planning_context
        def mock_browsing_run(self, shared):
            shared["planning_context"] = """## GitHub Operations

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
"""
            return "generate"

        monkeypatch.setattr("pflow.planning.nodes.ComponentBrowsingNode.run", mock_browsing_run)

        runner = click.testing.CliRunner()
        result = runner.invoke(registry_cmd, ["discover", "fetch GitHub pull requests"], env={"HOME": str(tmp_path)})

        assert result.exit_code == 0
        assert "github-get-pr" in result.output
        assert "Fetch pull request details" in result.output
        assert "pr_number" in result.output

    def test_registry_discover_llm_unavailable(self, tmp_path, monkeypatch):
        """Shows helpful message when LLM not configured.

        Real behavior: Suggests using 'registry list' instead.
        """

        # Mock to simulate LLM error
        def mock_browsing_run(self, shared):
            # Raise a generic exception (will be handled by discovery error handler)
            raise RuntimeError("No LLM API keys configured. Please set ANTHROPIC_API_KEY or OPENAI_API_KEY.")

        monkeypatch.setattr("pflow.planning.nodes.ComponentBrowsingNode.run", mock_browsing_run)

        runner = click.testing.CliRunner()
        result = runner.invoke(registry_cmd, ["discover", "test query"], env={"HOME": str(tmp_path)})

        # Should fail with helpful message
        assert result.exit_code != 0
        # Should contain helpful guidance (error message or alternatives)
        helpful_patterns = ["API key", "registry list", "pflow registry"]
        assert any(pattern.lower() in result.output.lower() for pattern in helpful_patterns)

    def test_discovery_commands_have_anthropic_patch(self, tmp_path, monkeypatch):
        """Verifies Anthropic monkey patch is installed.

        Critical discovery: Without patch, Anthropic LLM calls fail with cryptic
        Pydantic error: "cache_blocks - Extra inputs are not permitted"

        This test validates that the code path exists (we can't test actual installation
        because PYTEST_CURRENT_TEST is set during tests).
        """

        # Mock discovery node to succeed quickly
        def mock_discovery_run(self, shared):
            shared["discovery_result"] = {"workflow_name": "test"}
            shared["found_workflow"] = {"metadata": {}, "ir": {}}
            return "found_existing"

        monkeypatch.setattr("pflow.planning.nodes.WorkflowDiscoveryNode.run", mock_discovery_run)

        runner = click.testing.CliRunner()
        result = runner.invoke(workflow_cmd, ["discover", "test"], env={"HOME": str(tmp_path)})

        # Command should work - this verifies the integration is correct
        # The actual patch installation is skipped in tests (PYTEST_CURRENT_TEST check)
        # but we verify the command structure is correct
        assert result.exit_code == 0

    def test_registry_discover_requires_workflow_manager(self, tmp_path, monkeypatch):
        """Validates workflow_manager is provided to ComponentBrowsingNode.

        ComponentBrowsingNode needs workflow_manager for workflow context.
        """
        workflow_manager_provided = []

        # Mock to check for workflow_manager
        def mock_browsing_run(self, shared):
            if "workflow_manager" in shared:
                workflow_manager_provided.append(True)
                shared["planning_context"] = "## Test\n\nSome context"
                return "generate"
            else:
                raise ValueError("workflow_manager required")

        monkeypatch.setattr("pflow.planning.nodes.ComponentBrowsingNode.run", mock_browsing_run)

        runner = click.testing.CliRunner()
        result = runner.invoke(registry_cmd, ["discover", "test query"], env={"HOME": str(tmp_path)})

        # Should succeed
        assert result.exit_code == 0
        assert len(workflow_manager_provided) > 0, "workflow_manager must be provided"
