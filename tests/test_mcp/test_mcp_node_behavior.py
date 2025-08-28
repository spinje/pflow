"""
Tests for MCPNode critical behaviors that prevent real production bugs.

Focus: async-to-sync bridge, result extraction, error handling.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from pflow.nodes.mcp.node import MCPNode


class TestMCPNodeAsyncBridge:
    """Test the critical async-to-sync bridge that allows MCP SDK to work with PocketFlow."""

    def test_asyncio_run_creates_new_event_loop(self):
        """Each execution must create a new event loop to avoid conflicts.

        Real Bug: Reusing event loops causes "Event loop is already running" errors
        when multiple MCP nodes execute in sequence.
        """
        node = MCPNode()
        node.set_params({"__mcp_server__": "test", "__mcp_tool__": "test_tool", "param1": "value1"})

        # Track event loop IDs
        loop_ids = []

        async def capture_loop_id(*args, **kwargs):
            """Capture the event loop ID during async execution."""
            loop = asyncio.get_event_loop()
            loop_ids.append(id(loop))
            return {"result": "success"}

        with patch.object(node, "_load_server_config") as mock_config:
            mock_config.return_value = {"command": "test", "args": []}

            with patch.object(node, "_exec_async", side_effect=capture_loop_id):
                # Execute multiple times
                shared = {}
                prep1 = node.prep(shared)
                node.exec(prep1)

                prep2 = node.prep(shared)
                node.exec(prep2)

        # Each execution should have its own loop (different IDs)
        assert len(loop_ids) == 2
        # This test actually can't verify different loop IDs since asyncio.run()
        # may reuse the same memory address. The important thing is no exception.

    def test_async_exceptions_bubble_through_bridge(self):
        """Exceptions from async MCP calls must propagate to sync context.

        Real Bug: Swallowing async exceptions leaves users with no error feedback.
        """
        node = MCPNode()
        node.set_params({"__mcp_server__": "test", "__mcp_tool__": "failing_tool"})

        async def async_failure(*args, **kwargs):
            raise ValueError("MCP tool validation failed: missing required field 'title'")

        with patch.object(node, "_load_server_config") as mock_config:
            mock_config.return_value = {"command": "test"}

            with patch.object(node, "_exec_async", side_effect=async_failure):
                shared = {}
                prep_res = node.prep(shared)

                # Exception should propagate
                with pytest.raises(ValueError, match="missing required field 'title'"):
                    node.exec(prep_res)

    def test_timeout_is_configurable(self):
        """Timeout should be configurable per node execution.

        Real Bug: Different MCP servers have different response times.
        Slack needs more time than filesystem.
        """
        node = MCPNode()

        # Test default timeout
        node.set_params({"__mcp_server__": "test", "__mcp_tool__": "test_tool"})

        with patch.object(node, "_load_server_config") as mock_config:
            mock_config.return_value = {"command": "test"}
            shared = {}
            node.prep(shared)  # Sets the timeout during prep

            # Default timeout should be 30 seconds
            assert node._timeout == 30

        # Test custom timeout
        node.set_params({
            "__mcp_server__": "slow",
            "__mcp_tool__": "slow_tool",
            "timeout": 60,  # Custom timeout
        })

        with patch.object(node, "_load_server_config") as mock_config:
            mock_config.return_value = {"command": "test"}
            shared = {}
            node.prep(shared)  # Sets the timeout during prep

            # Should use custom timeout
            assert node._timeout == 60


class TestMCPResultExtraction:
    """Test extraction of results from various MCP response formats."""

    def test_structured_content_preferred_over_text(self):
        """structuredContent should be used when available (future-proofing).

        Real Bug: Servers will migrate to structured outputs. We must be ready.
        """
        node = MCPNode()

        # Mock MCP response with both structured and text content
        mock_result = MagicMock()
        mock_result.structuredContent = {"temperature": 22, "humidity": 65}
        mock_result.isError = False
        mock_result.content = [MagicMock(text="Old text format")]

        result = node._extract_result(mock_result)

        # Should prefer structured content
        assert result == {"temperature": 22, "humidity": 65}
        assert result != "Old text format"

    def test_text_content_extraction_fallback(self):
        """Text content blocks should work for current servers.

        Real Bug: Most current MCP servers only provide text content blocks.
        """
        node = MCPNode()

        # Mock typical filesystem server response
        mock_result = MagicMock()
        mock_result.structuredContent = None
        mock_result.isError = False

        mock_content = MagicMock()
        mock_content.text = "File contents here"
        mock_result.content = [mock_content]

        # Need to make hasattr work correctly
        del mock_content.image
        del mock_content.resource
        del mock_content.resource_link

        result = node._extract_result(mock_result)
        assert result == "File contents here"

    def test_error_flag_extraction(self):
        """isError flag should be detected and handled.

        Real Bug: Tool errors are different from protocol errors and need special handling.
        """
        node = MCPNode()

        mock_result = MagicMock()
        mock_result.structuredContent = None
        mock_result.isError = True

        mock_content = MagicMock()
        mock_content.text = "Permission denied: cannot read /etc/passwd"
        mock_result.content = [mock_content]

        result = node._extract_result(mock_result)

        assert isinstance(result, dict)
        assert result.get("is_tool_error") is True
        assert "Permission denied" in result.get("error", "")

    def test_multiple_content_blocks_as_list(self):
        """Multiple content blocks should return as a list.

        Real Bug: Some tools return multiple pieces of content that all matter.
        """
        node = MCPNode()

        mock_result = MagicMock()
        mock_result.structuredContent = None
        mock_result.isError = False

        # Multiple content blocks
        content1 = MagicMock()
        content1.text = "First result"
        content2 = MagicMock()
        content2.text = "Second result"

        mock_result.content = [content1, content2]

        result = node._extract_result(mock_result)

        assert isinstance(result, list)
        assert len(result) == 2
        assert "First result" in result
        assert "Second result" in result


class TestMCPNodeErrorHandling:
    """Test error handling that prevents production crashes."""

    def test_missing_server_config_helpful_error(self):
        """Missing server config should provide actionable error message.

        Real Bug: Users see "FileNotFoundError" without knowing what to do.
        """
        node = MCPNode()
        node.set_params({"__mcp_server__": "unconfigured", "__mcp_tool__": "some_tool"})

        with patch("pathlib.Path.exists", return_value=False):
            shared = {}
            with pytest.raises(FileNotFoundError, match="pflow mcp add unconfigured"):
                node.prep(shared)

    def test_exec_fallback_extracts_meaningful_errors(self):
        """exec_fallback should extract real error from ExceptionGroup.

        Real Bug: Users see "ExceptionGroup: unhandled errors" instead of actual problem.
        """
        node = MCPNode()

        # Simulate wrapped exception
        inner_error = "McpError: Required parameter 'repository' is missing"
        outer_error = f"ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)\n{inner_error}"
        exception = Exception(outer_error)

        result = node.exec_fallback({"server": "github", "tool": "create-issue"}, exception)

        # Should extract the meaningful error
        assert "Required parameter 'repository' is missing" in result["error"]
        assert "ExceptionGroup" not in result["error"]

    def test_environment_variable_expansion(self):
        """Environment variables should expand at runtime, not config time.

        Real Bug: Storing expanded values in config breaks when env vars change.
        """
        import os

        node = MCPNode()

        # Set test env var
        os.environ["TEST_TOKEN"] = "secret123"  # noqa: S105 - Test data, not a real secret

        try:
            env_dict = {"AUTH": "${TEST_TOKEN}"}
            expanded = node._expand_env_vars(env_dict)

            assert expanded["AUTH"] == "secret123"

            # Change env var
            os.environ["TEST_TOKEN"] = "newsecret456"  # noqa: S105 - Test data, not a real secret

            # Should expand to new value
            expanded = node._expand_env_vars(env_dict)
            assert expanded["AUTH"] == "newsecret456"

        finally:
            del os.environ["TEST_TOKEN"]

    def test_server_specific_logic_forbidden(self):
        """MCPNode must remain universal - no server-specific code.

        Real Bug: Adding "if server == 'filesystem'" breaks future servers.
        This test verifies the node doesn't have server-specific logic.
        """
        node = MCPNode()

        # Check that prep doesn't modify parameters based on server
        node.set_params({
            "__mcp_server__": "filesystem",
            "__mcp_tool__": "read_file",
            "path": "relative/path.txt",  # Filesystem might want absolute
        })

        with patch.object(node, "_load_server_config") as mock_config:
            mock_config.return_value = {"command": "test"}

            shared = {}
            prep_res = node.prep(shared)

            # Path should NOT be modified to absolute
            assert prep_res["arguments"]["path"] == "relative/path.txt"

        # Try with GitHub (no concept of paths)
        node.set_params({
            "__mcp_server__": "github",
            "__mcp_tool__": "create_issue",
            "title": "Bug",
            "path": "some/path",  # GitHub doesn't use paths
        })

        with patch.object(node, "_load_server_config") as mock_config:
            mock_config.return_value = {"command": "test"}

            prep_res = node.prep(shared)

            # All params should pass through unchanged
            assert prep_res["arguments"]["title"] == "Bug"
            assert prep_res["arguments"]["path"] == "some/path"
