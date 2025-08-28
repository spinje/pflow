"""
CRITICAL: Tests for MCPNode behaviors that prevent production failures.

These test critical behaviors that were previously untested.
"""

from unittest.mock import patch

import pytest

from pflow.nodes.mcp.node import MCPNode


class TestMCPNodeCriticalBehaviors:
    """Test critical MCPNode behaviors that prevent production failures."""

    def test_max_retries_prevents_multiple_processes(self):
        """Test that max_retries=1 prevents spawning multiple MCP server processes.

        CRITICAL BUG: Each retry starts a NEW subprocess. Without max_retries=1,
        a flaky server could spawn dozens of processes, exhausting resources.

        Real incident: Slack server initialization sometimes fails on first attempt.
        With retries, it would spawn 3+ server processes all trying to bind to
        the same resources, causing "unhandled errors in TaskGroup" crashes.
        """
        node = MCPNode()

        # CRITICAL: Must be exactly 1 (no retries)
        assert node.max_retries == 1
        assert node.wait == 0  # No wait between attempts

        # Verify it doesn't retry on failure
        node.set_params({"__mcp_server__": "flaky-server", "__mcp_tool__": "test-tool"})

        exec_count = 0

        async def failing_exec(prep_res):
            nonlocal exec_count
            exec_count += 1
            raise RuntimeError("Server initialization failed")

        with (
            patch.object(node, "_load_server_config", return_value={"command": "test"}),
            patch.object(node, "_exec_async", side_effect=failing_exec),
        ):
            shared = {}
            prep_res = node.prep(shared)

            # Should fail immediately, not retry
            with pytest.raises(RuntimeError, match="Server initialization failed"):
                node.exec(prep_res)

                # Should have tried exactly once
                assert exec_count == 1

    def test_structured_data_extraction_to_shared_store(self):
        """Test that structured data fields are extracted to shared store.

        CRITICAL: When MCP returns structured data (e.g., from GitHub),
        individual fields must be accessible in shared store for downstream nodes.

        Example: GitHub's create-issue returns {"issue_url": "...", "issue_number": 123}
        Both fields should be directly accessible as shared["issue_url"] and shared["issue_number"]
        """
        node = MCPNode()
        node.set_params({"__mcp_server__": "github", "__mcp_tool__": "create-issue"})

        shared = {}
        prep_res = {"server": "github", "tool": "create-issue", "arguments": {"title": "Test"}}

        # Simulate structured response from GitHub
        exec_res = {
            "result": {
                "issue_url": "https://github.com/test/repo/issues/123",
                "issue_number": 123,
                "issue_id": "I_kwDOBkpqZc5_y5mq",
                "_internal_field": "should_not_extract",  # Private field
                "is_closed": False,  # Internal flag
            }
        }

        action = node.post(shared, prep_res, exec_res)

        # Verify structured fields were extracted
        assert shared["issue_url"] == "https://github.com/test/repo/issues/123"
        assert shared["issue_number"] == 123
        assert shared["issue_id"] == "I_kwDOBkpqZc5_y5mq"

        # Private fields should NOT be extracted
        assert "_internal_field" not in shared
        assert "is_closed" not in shared  # Fields starting with "is_" are internal

        # Full result still available
        assert shared["result"] == exec_res["result"]

        # Server-specific result key also available
        assert shared["github_create-issue_result"] == exec_res["result"]

        # Should return "default" action
        assert action == "default"

    def test_error_handling_returns_default_not_error(self):
        """Test that errors return 'default' action, not 'error'.

        CRITICAL: The planner doesn't generate error handling edges.
        Returning "error" causes "Flow ends: 'error' not found" crashes.
        This is a documented workaround in the code.
        """
        node = MCPNode()
        node.set_params({"__mcp_server__": "test", "__mcp_tool__": "failing-tool"})

        shared = {}
        prep_res = {"server": "test", "tool": "failing-tool"}

        # Test protocol error
        exec_res = {"error": "Connection failed"}
        action = node.post(shared, prep_res, exec_res)

        # CRITICAL: Must return "default" not "error"
        assert action == "default"
        assert "error" in shared
        assert shared["error"] == "Connection failed"

        # Test tool-level error
        shared = {}
        exec_res = {"result": {"error": "Repository not found", "is_tool_error": True}}
        action = node.post(shared, prep_res, exec_res)

        # CRITICAL: Must return "default" even for tool errors
        assert action == "default"
        assert "error" in shared
        assert shared["error"] == "Repository not found"

    def test_multiple_server_results_dont_collide(self):
        """Test that multiple MCP tools in same workflow don't overwrite results.

        CRITICAL: Without proper namespacing, second MCP tool would overwrite
        first tool's results in shared store.
        """
        # First tool execution
        node1 = MCPNode()
        node1.set_params({"__mcp_server__": "github", "__mcp_tool__": "list-issues"})

        shared = {}
        prep1 = {"server": "github", "tool": "list-issues", "arguments": {}}
        exec1 = {"result": ["issue1", "issue2", "issue3"]}
        node1.post(shared, prep1, exec1)

        # Second tool execution (same workflow, different tool)
        node2 = MCPNode()
        node2.set_params({"__mcp_server__": "filesystem", "__mcp_tool__": "read-file"})

        prep2 = {"server": "filesystem", "tool": "read-file", "arguments": {}}
        exec2 = {"result": "File contents here"}
        node2.post(shared, prep2, exec2)

        # Both results should be available
        assert shared["github_list-issues_result"] == ["issue1", "issue2", "issue3"]
        assert shared["filesystem_read-file_result"] == "File contents here"

        # Generic "result" gets overwritten (last one wins)
        assert shared["result"] == "File contents here"
