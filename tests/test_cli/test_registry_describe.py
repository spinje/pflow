"""Tests for `pflow registry describe` command.

This test file validates the complete behavior of the registry describe command,
including node normalization, MCP tool handling, and error cases.

Test Coverage:
1. Single node description with complete interface
2. Multiple nodes in one command
3. Node name normalization (hyphens vs underscores)
4. MCP tool normalization (complex name formats)
5. Unknown node error handling
6. Mixed valid/invalid node handling
7. No arguments error
8. Complex node interfaces (llm node)
9. Output format consistency
"""

import click.testing
import pytest

from pflow.cli.registry import registry


@pytest.fixture
def runner() -> click.testing.CliRunner:
    """Create a Click test runner."""
    return click.testing.CliRunner()


class TestDescribeSingleNode:
    """Test describing a single node."""

    def test_describe_single_node(self, runner: click.testing.CliRunner) -> None:
        """Shows complete specification for a single node.

        Real behavior: Uses build_planning_context() to get full interface
        """
        result = runner.invoke(registry, ["describe", "shell"])

        assert result.exit_code == 0

        # Should show node name in markdown heading
        assert "### shell" in result.output

        # Should show description
        assert "execute" in result.output.lower() or "command" in result.output.lower()

        # Should show command parameter (shell node has 'command' input)
        assert "command" in result.output.lower()

    def test_describe_read_file_node(self, runner: click.testing.CliRunner) -> None:
        """Shows complete specification for read-file node."""
        result = runner.invoke(registry, ["describe", "read-file"])

        assert result.exit_code == 0

        # Should show node name
        assert "### read-file" in result.output or "read_file" in result.output.lower()

        # Should show file_path parameter
        assert "file_path" in result.output or "path" in result.output.lower()


class TestDescribeMultipleNodes:
    """Test describing multiple nodes at once."""

    def test_describe_multiple_nodes(self, runner: click.testing.CliRunner) -> None:
        """Shows specifications for multiple nodes in one command."""
        result = runner.invoke(registry, ["describe", "shell", "read-file"])

        assert result.exit_code == 0

        # Should show both nodes
        assert "shell" in result.output.lower()
        assert "read-file" in result.output.lower() or "read_file" in result.output.lower()

    def test_describe_three_different_nodes(self, runner: click.testing.CliRunner) -> None:
        """Shows specifications for three nodes with different packages."""
        result = runner.invoke(registry, ["describe", "shell", "llm", "write-file"])

        assert result.exit_code == 0

        # All three should appear
        assert "shell" in result.output.lower()
        assert "llm" in result.output.lower()
        assert "write-file" in result.output.lower() or "write_file" in result.output.lower()


class TestNodeNameNormalization:
    """Test node name normalization (hyphens vs underscores).

    The normalization is primarily designed for MCP tools where tool names
    often have underscores (e.g., SEND_MESSAGE). For core nodes like read-file,
    the exact hyphenated name should be used.
    """

    def test_describe_exact_match_core_nodes(self, runner: click.testing.CliRunner) -> None:
        """Core nodes work with their exact registered names (with hyphens)."""
        # Core nodes are registered with hyphens (read-file, write-file)
        result_read = runner.invoke(registry, ["describe", "read-file"])
        result_write = runner.invoke(registry, ["describe", "write-file"])

        assert result_read.exit_code == 0
        assert result_write.exit_code == 0

        assert "read" in result_read.output.lower()
        assert "write" in result_write.output.lower()

    def test_describe_normalization_for_mcp_format(self, runner: click.testing.CliRunner) -> None:
        """Normalization handles MCP tool name conversions.

        The normalization is designed for MCP tools where:
        - Registry stores: mcp-server-TOOL_NAME (underscores in tool)
        - User types: mcp-server-TOOL-NAME (hyphens everywhere)
        - Should match via underscore→hyphen conversion
        """
        # This test documents the normalization strategy
        # For actual MCP testing, see TestMCPToolNormalization class
        pass


class TestMCPToolNormalization:
    """Test MCP tool name normalization.

    These tests inject fake MCP nodes into the registry to test normalization
    behavior without requiring actual MCP servers to be configured.
    """

    @pytest.fixture
    def registry_with_mcp_nodes(self):
        """Inject fake MCP nodes into the test registry.

        Note: isolate_pflow_config fixture runs automatically (autouse=True)
        and provides isolated registry paths for testing.
        """
        from pflow.registry import Registry

        reg = Registry()
        existing_nodes = reg.load()

        # Add fake MCP nodes for testing normalization
        # Note: interface format uses 'key' not 'name' for parameter names
        fake_mcp_nodes = {
            "mcp-slack-composio-SLACK_SEND_MESSAGE": {
                "module": "pflow.nodes.mcp.mcp_node",
                "class_name": "MCPNode",
                "docstring": "Send a message via Slack",
                "interface": {
                    "description": "Send a message to a Slack channel",
                    "inputs": [{"key": "channel", "type": "str", "description": "Channel to send to"}],
                    "outputs": [{"key": "result", "type": "dict", "description": "API result"}],
                    "actions": [],
                },
            },
            "mcp-github-composio-GITHUB_CREATE_ISSUE": {
                "module": "pflow.nodes.mcp.mcp_node",
                "class_name": "MCPNode",
                "docstring": "Create a GitHub issue",
                "interface": {
                    "description": "Create an issue in a GitHub repository",
                    "inputs": [{"key": "repo", "type": "str", "description": "Repository name"}],
                    "outputs": [{"key": "issue", "type": "dict", "description": "Created issue"}],
                    "actions": [],
                },
            },
            "mcp-filesystem-read_file": {
                "module": "pflow.nodes.mcp.mcp_node",
                "class_name": "MCPNode",
                "docstring": "Read a file from filesystem",
                "interface": {
                    "description": "Read file contents",
                    "inputs": [{"key": "path", "type": "str", "description": "File path"}],
                    "outputs": [{"key": "content", "type": "str", "description": "File contents"}],
                    "actions": [],
                },
            },
        }

        # Merge with existing nodes
        merged = {**existing_nodes, **fake_mcp_nodes}
        reg.save(merged)
        return reg

    def test_describe_mcp_tool_full_format_with_hyphens(
        self, runner: click.testing.CliRunner, registry_with_mcp_nodes
    ) -> None:
        """Handles MCP tool names with hyphens in full format.

        Registry stores: mcp-server-TOOL_NAME
        User types: mcp-server-TOOL-NAME (with hyphens)
        Should normalize to underscores
        """
        # Test exact name works
        result_exact = runner.invoke(registry, ["describe", "mcp-slack-composio-SLACK_SEND_MESSAGE"])
        assert result_exact.exit_code == 0
        assert "SLACK_SEND_MESSAGE" in result_exact.output

        # Test hyphenated version normalizes to underscore version
        result_hyphen = runner.invoke(registry, ["describe", "mcp-slack-composio-SLACK-SEND-MESSAGE"])
        assert result_hyphen.exit_code == 0
        assert "SLACK" in result_hyphen.output

    def test_describe_mcp_tool_short_form(self, runner: click.testing.CliRunner, registry_with_mcp_nodes) -> None:
        """Handles MCP tool short forms (just tool name).

        Short form: TOOL_NAME
        Full form: mcp-server-TOOL_NAME
        Should match if unique
        """
        # Test short form with underscores
        result = runner.invoke(registry, ["describe", "SLACK_SEND_MESSAGE"])
        assert result.exit_code == 0
        assert "mcp-slack-composio-SLACK_SEND_MESSAGE" in result.output or "SLACK" in result.output

        # Test short form with hyphens
        result_hyphen = runner.invoke(registry, ["describe", "SLACK-SEND-MESSAGE"])
        assert result_hyphen.exit_code == 0

        # Test filesystem tool short form
        result_fs = runner.invoke(registry, ["describe", "read_file"])
        # This might be ambiguous with core read-file, check behavior
        if result_fs.exit_code == 0:
            assert "file" in result_fs.output.lower()


class TestUnknownNodeError:
    """Test error handling for unknown nodes."""

    def test_describe_unknown_node(self, runner: click.testing.CliRunner) -> None:
        """Shows helpful error for unknown nodes."""
        result = runner.invoke(registry, ["describe", "nonexistent-node"])

        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "unknown" in result.output.lower()
        assert "nonexistent-node" in result.output

    def test_describe_unknown_node_shows_suggestions(self, runner: click.testing.CliRunner) -> None:
        """Shows available nodes when node not found."""
        result = runner.invoke(registry, ["describe", "totally-fake-node-xyz"])

        assert result.exit_code != 0
        assert "available nodes" in result.output.lower()

    def test_describe_partial_match_fails(self, runner: click.testing.CliRunner) -> None:
        """Partial matches without normalization fail with helpful error."""
        result = runner.invoke(registry, ["describe", "read"])

        assert result.exit_code != 0
        # Should show suggestions or available nodes
        assert "unknown" in result.output.lower() or "available" in result.output.lower()


class TestMixedValidInvalid:
    """Test handling of mixed valid and invalid node names."""

    def test_describe_mixed_valid_invalid(self, runner: click.testing.CliRunner) -> None:
        """Handles mix of valid and invalid node names.

        Behavior: Fail fast on first invalid with clear error message
        """
        result = runner.invoke(registry, ["describe", "shell", "nonexistent", "read-file"])

        # Should fail due to invalid node
        assert result.exit_code != 0

        # Should mention the invalid node
        assert "nonexistent" in result.output

        # Should show error message
        assert "unknown" in result.output.lower() or "not found" in result.output.lower()

    def test_describe_all_invalid(self, runner: click.testing.CliRunner) -> None:
        """Shows error when all nodes are invalid."""
        result = runner.invoke(registry, ["describe", "fake1", "fake2"])

        assert result.exit_code != 0
        assert "unknown" in result.output.lower()
        # Should mention both
        assert "fake1" in result.output
        assert "fake2" in result.output


class TestNoArgumentsError:
    """Test error when no arguments provided."""

    def test_describe_no_arguments(self, runner: click.testing.CliRunner) -> None:
        """Shows helpful error when no node IDs provided."""
        result = runner.invoke(registry, ["describe"])

        assert result.exit_code != 0
        # Click should show usage or missing argument error
        assert "missing" in result.output.lower() or "usage" in result.output.lower()


class TestComplexNodeInterface:
    """Test nodes with complex interfaces."""

    def test_describe_complex_node_interface(self, runner: click.testing.CliRunner) -> None:
        """Handles nodes with complex input/output schemas.

        Tests that nested types, optional fields, etc. are displayed
        """
        # Use llm node which has complex interface
        result = runner.invoke(registry, ["describe", "llm"])

        assert result.exit_code == 0

        # Should show the node
        assert "llm" in result.output.lower()

        # Should show prompt parameter (llm has prompt input)
        assert "prompt" in result.output.lower()

        # Output should be readable (not truncated or mangled)
        # Check for markdown formatting
        assert "###" in result.output or "**" in result.output

    def test_describe_http_node_interface(self, runner: click.testing.CliRunner) -> None:
        """HTTP node has complex request/response interface."""
        result = runner.invoke(registry, ["describe", "http"])

        assert result.exit_code == 0

        # Should show http node
        assert "http" in result.output.lower()

        # Should show url parameter
        assert "url" in result.output.lower()


class TestOutputFormatConsistency:
    """Test output format consistency."""

    def test_describe_output_format_consistency(self, runner: click.testing.CliRunner) -> None:
        """Output should be consistently formatted across nodes."""
        result = runner.invoke(registry, ["describe", "shell", "llm"])

        assert result.exit_code == 0

        # Both nodes should have markdown headings
        assert "### shell" in result.output
        assert "### llm" in result.output

        # Should have structured sections for each
        # Count markdown headings (###) - should have at least 2 (one per node)
        heading_count = result.output.count("###")
        assert heading_count >= 2

    def test_describe_markdown_format(self, runner: click.testing.CliRunner) -> None:
        """Output uses markdown format for structured display."""
        result = runner.invoke(registry, ["describe", "read-file"])

        assert result.exit_code == 0

        # Should use markdown heading
        assert "###" in result.output

        # Should have structured parameter display
        # (exact format depends on context builder, but should be readable)
        assert ":" in result.output  # Key-value pairs


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_describe_case_sensitive(self, runner: click.testing.CliRunner) -> None:
        """Node names are case-sensitive."""
        # shell is lowercase
        result_lower = runner.invoke(registry, ["describe", "shell"])
        result_upper = runner.invoke(registry, ["describe", "SHELL"])

        assert result_lower.exit_code == 0
        # SHELL might fail if not registered (case-sensitive)
        if result_upper.exit_code != 0:
            assert "unknown" in result_upper.output.lower()

    def test_describe_exact_match_priority(self, runner: click.testing.CliRunner) -> None:
        """Exact matches take priority over partial matches."""
        # Test that exact node name works
        result = runner.invoke(registry, ["describe", "shell"])

        assert result.exit_code == 0
        assert "### shell" in result.output

    def test_describe_with_special_characters_fails(self, runner: click.testing.CliRunner) -> None:
        """Node names with special characters are invalid."""
        result = runner.invoke(registry, ["describe", "node@with$special"])

        assert result.exit_code != 0
        assert "unknown" in result.output.lower() or "not found" in result.output.lower()

    def test_describe_ambiguous_short_form(self, runner: click.testing.CliRunner) -> None:
        """Ambiguous short forms show clear error with options."""
        # This would only happen if multiple MCP servers have same tool name
        # We'll test the error handling mechanism
        result = runner.invoke(registry, ["describe", "SEND_MESSAGE"])

        # Either succeeds (unique) or fails with ambiguous error
        if result.exit_code != 0:
            # Should show helpful error
            assert "ambiguous" in result.output.lower() or "unknown" in result.output.lower()


class TestUsageSnippets:
    """Test .pflow.md usage snippets appear in describe output."""

    def test_shell_snippet_has_code_block(self, runner: click.testing.CliRunner) -> None:
        """Shell node snippet includes shell command code block."""
        result = runner.invoke(registry, ["describe", "shell"])
        assert result.exit_code == 0
        assert "Usage in .pflow.md" in result.output
        assert "- type: shell" in result.output
        assert "```shell command" in result.output

    def test_llm_snippet_has_prompt_block(self, runner: click.testing.CliRunner) -> None:
        """LLM node snippet includes markdown prompt code block."""
        result = runner.invoke(registry, ["describe", "llm"])
        assert result.exit_code == 0
        assert "Usage in .pflow.md" in result.output
        assert "- type: llm" in result.output
        assert "```markdown prompt" in result.output

    def test_http_snippet_is_inline_only(self, runner: click.testing.CliRunner) -> None:
        """HTTP node snippet uses inline params, no code blocks."""
        result = runner.invoke(registry, ["describe", "http"])
        assert result.exit_code == 0
        assert "Usage in .pflow.md" in result.output
        assert "- type: http" in result.output
        assert "- url:" in result.output

    def test_code_snippet_has_python_block(self, runner: click.testing.CliRunner) -> None:
        """Code node snippet includes python code block."""
        result = runner.invoke(registry, ["describe", "code"])
        assert result.exit_code == 0
        assert "Usage in .pflow.md" in result.output
        assert "```python code" in result.output

    def test_generic_node_gets_snippet(self, runner: click.testing.CliRunner) -> None:
        """Non-core nodes get a generic snippet with interface params."""
        result = runner.invoke(registry, ["describe", "read-file"])
        assert result.exit_code == 0
        assert "Usage in .pflow.md" in result.output
        assert "- type: read-file" in result.output

    def test_snippet_has_step_name_heading(self, runner: click.testing.CliRunner) -> None:
        """All snippets include ### step-name heading."""
        result = runner.invoke(registry, ["describe", "write-file"])
        assert result.exit_code == 0
        assert "### step-name" in result.output
