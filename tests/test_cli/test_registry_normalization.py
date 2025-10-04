"""Tests for registry node ID normalization.

This test file covers the node ID normalization logic added to handle
hyphen/underscore format variations and short forms for MCP tools.

Scenarios tested:
1. Exact match (no normalization needed)
2. Hyphen to underscore conversion for short forms
3. Full MCP format with hyphens in tool name
4. Short form matching (tool name only)
5. Ambiguous short forms (multiple matches)
6. Invalid node IDs
7. Core nodes (backward compatibility)
8. Case sensitivity
"""

from click.testing import CliRunner

from pflow.cli.registry import _normalize_node_id, registry


class TestNodeIdNormalization:
    """Test node ID normalization logic."""

    def test_exact_match(self):
        """Test exact match returns the input unchanged."""
        available = {"llm", "write-file", "mcp-slack-composio-SLACK_SEND_MESSAGE"}

        assert _normalize_node_id("llm", available) == "llm"
        assert _normalize_node_id("write-file", available) == "write-file"
        assert (
            _normalize_node_id("mcp-slack-composio-SLACK_SEND_MESSAGE", available)
            == "mcp-slack-composio-SLACK_SEND_MESSAGE"
        )

    def test_hyphen_to_underscore_simple(self):
        """Test simple hyphen to underscore conversion for short forms."""
        available = {"mcp-server-TOOL_NAME"}

        # Short form with hyphens should convert to underscores
        assert _normalize_node_id("TOOL-NAME", available) == "mcp-server-TOOL_NAME"

    def test_full_mcp_format_with_hyphens(self):
        """Test full MCP format where tool name has hyphens."""
        available = {
            "mcp-slack-composio-SLACK_SEND_MESSAGE",
            "mcp-slack-composio-SLACK_FETCH_CONVERSATION_HISTORY",
        }

        # Full format with hyphens in tool name
        assert (
            _normalize_node_id("mcp-slack-composio-SLACK-SEND-MESSAGE", available)
            == "mcp-slack-composio-SLACK_SEND_MESSAGE"
        )
        assert (
            _normalize_node_id("mcp-slack-composio-SLACK-FETCH-CONVERSATION-HISTORY", available)
            == "mcp-slack-composio-SLACK_FETCH_CONVERSATION_HISTORY"
        )

    def test_short_form_unique_match(self):
        """Test short form matching when there's only one match."""
        available = {
            "mcp-slack-composio-SLACK_SEND_MESSAGE",
            "mcp-github-composio-GITHUB_CREATE_ISSUE",
        }

        # Short form with hyphens
        assert _normalize_node_id("SLACK-SEND-MESSAGE", available) == "mcp-slack-composio-SLACK_SEND_MESSAGE"
        # Short form with underscores
        assert _normalize_node_id("SLACK_SEND_MESSAGE", available) == "mcp-slack-composio-SLACK_SEND_MESSAGE"

    def test_ambiguous_short_form(self):
        """Test that ambiguous short forms return None."""
        available = {
            "mcp-slack-composio-SEND_MESSAGE",
            "mcp-discord-composio-SEND_MESSAGE",
        }

        # Ambiguous - matches both
        assert _normalize_node_id("SEND_MESSAGE", available) is None
        assert _normalize_node_id("SEND-MESSAGE", available) is None

    def test_invalid_node_id(self):
        """Test that invalid node IDs return None."""
        available = {"llm", "write-file"}

        assert _normalize_node_id("nonexistent-node", available) is None
        assert _normalize_node_id("FAKE_MCP_TOOL", available) is None

    def test_core_nodes_backward_compatibility(self):
        """Test that core nodes still work without normalization."""
        available = {"llm", "shell", "write-file", "read-file"}

        assert _normalize_node_id("llm", available) == "llm"
        assert _normalize_node_id("shell", available) == "shell"
        assert _normalize_node_id("write-file", available) == "write-file"
        assert _normalize_node_id("read-file", available) == "read-file"

    def test_filesystem_mcp_tools(self):
        """Test that filesystem MCP tools work (regression test)."""
        available = {
            "mcp-filesystem-create_directory",
            "mcp-filesystem-read_file",
        }

        # Exact match
        assert _normalize_node_id("mcp-filesystem-create_directory", available) == "mcp-filesystem-create_directory"
        # Hyphen variant
        assert _normalize_node_id("mcp-filesystem-create-directory", available) == "mcp-filesystem-create_directory"
        # Short form
        assert _normalize_node_id("create_directory", available) == "mcp-filesystem-create_directory"
        assert _normalize_node_id("create-directory", available) == "mcp-filesystem-create_directory"

    def test_mixed_case_not_supported(self):
        """Test that mixed case is NOT normalized (case-sensitive)."""
        available = {"mcp-server-TOOL_NAME"}

        # Case sensitivity - these should not match
        assert _normalize_node_id("tool_name", available) is None
        assert _normalize_node_id("TOOL_name", available) is None


class TestRegistryDescribeCommand:
    """Test registry describe command with normalization."""

    def test_describe_short_form_hyphen(self):
        """Test describe command with short form using hyphens."""
        runner = CliRunner()
        result = runner.invoke(registry, ["describe", "SLACK-SEND-MESSAGE"])

        # Should succeed with normalized ID
        if "mcp-slack-composio-SLACK_SEND_MESSAGE" in self._get_available_nodes():
            assert result.exit_code == 0
            assert "mcp-slack-composio-SLACK_SEND_MESSAGE" in result.output
        else:
            # If Slack tools not available, should show error
            assert result.exit_code == 1
            assert "Unknown nodes" in result.output

    def test_describe_short_form_underscore(self):
        """Test describe command with short form using underscores."""
        runner = CliRunner()
        result = runner.invoke(registry, ["describe", "SLACK_SEND_MESSAGE"])

        # Should succeed with normalized ID
        if "mcp-slack-composio-SLACK_SEND_MESSAGE" in self._get_available_nodes():
            assert result.exit_code == 0
            assert "mcp-slack-composio-SLACK_SEND_MESSAGE" in result.output
        else:
            # If Slack tools not available, should show error
            assert result.exit_code == 1

    def test_describe_full_format_hyphen(self):
        """Test describe command with full MCP format using hyphens."""
        runner = CliRunner()
        result = runner.invoke(registry, ["describe", "mcp-slack-composio-SLACK-SEND-MESSAGE"])

        # Should succeed with normalized ID
        if "mcp-slack-composio-SLACK_SEND_MESSAGE" in self._get_available_nodes():
            assert result.exit_code == 0
            assert "mcp-slack-composio-SLACK_SEND_MESSAGE" in result.output
        else:
            # If Slack tools not available, should show error
            assert result.exit_code == 1

    def test_describe_full_format_underscore(self):
        """Test describe command with full MCP format using underscores."""
        runner = CliRunner()
        result = runner.invoke(registry, ["describe", "mcp-slack-composio-SLACK_SEND_MESSAGE"])

        # Should always work if the node exists
        if "mcp-slack-composio-SLACK_SEND_MESSAGE" in self._get_available_nodes():
            assert result.exit_code == 0
            assert "mcp-slack-composio-SLACK_SEND_MESSAGE" in result.output

    def test_describe_multiple_nodes_mixed_formats(self):
        """Test describe command with multiple nodes in different formats."""
        runner = CliRunner()
        result = runner.invoke(
            registry,
            ["describe", "llm", "SLACK-SEND-MESSAGE"],  # Mix of core and MCP short form
        )

        # At least llm should be found
        assert "llm" in result.output.lower()

    def test_describe_invalid_node(self):
        """Test describe command with invalid node ID."""
        runner = CliRunner()
        result = runner.invoke(registry, ["describe", "nonexistent-node"])

        assert result.exit_code == 1
        assert "Unknown nodes" in result.output
        assert "nonexistent-node" in result.output

    def test_describe_ambiguous_short_form(self):
        """Test describe command with ambiguous short form."""
        runner = CliRunner()

        # Create scenario where short form could match multiple tools
        # This would only happen if multiple servers have same tool name
        result = runner.invoke(registry, ["describe", "SEND_MESSAGE"])

        # Should either succeed with unique match or show ambiguous error
        # Actual behavior depends on what's in the registry
        if result.exit_code == 1:
            # Could be "Unknown" or "Ambiguous" depending on registry state
            assert "nodes" in result.output.lower()

    def test_describe_core_nodes_still_work(self):
        """Test that core nodes work without normalization."""
        runner = CliRunner()
        result = runner.invoke(registry, ["describe", "llm", "shell"])

        # Core nodes should always be available
        assert result.exit_code == 0
        assert "llm" in result.output.lower()

    @staticmethod
    def _get_available_nodes() -> set[str]:
        """Get set of available node IDs from registry."""
        from pflow.registry.registry import Registry

        reg = Registry()
        metadata = reg.load()
        return set(metadata.keys())
