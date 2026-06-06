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

    def test_structured_data_stays_under_result(self):
        """Structured MCP output uses result as its only success namespace.

        The validator only declares ``result`` for MCP nodes because MCP servers
        do not publish stable output schemas. Keeping fields under result makes
        runtime, validation, and probe teach the same downstream path:
        ``${node.result.field}``.
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

        # Full result is available through the canonical result key.
        assert shared["result"] == exec_res["result"]

        # Structured fields are not splayed into a second namespace.
        assert "issue_url" not in shared
        assert "issue_number" not in shared
        assert "issue_id" not in shared
        assert "_internal_field" not in shared
        assert "is_closed" not in shared

        # Should return "default" action
        assert action == "default"

    def test_error_handling_returns_error_for_repair_system(self):
        """Test that errors return 'error' action to enable repair system.

        CRITICAL: Nodes MUST return "error" on failures to enable the repair system.
        The InstrumentedNodeWrapper handles error actions properly by:
        1. Detecting if it's a repairable validation error (allows repair)
        2. Detecting if it's a non-repairable resource error (stops workflow)
        3. Caching results and preventing infinite loops
        """
        node = MCPNode()
        node.set_params({"__mcp_server__": "test", "__mcp_tool__": "failing-tool"})

        shared = {}
        prep_res = {"server": "test", "tool": "failing-tool"}

        # Protocol/transport errors are node failures, not successful output.
        exec_res = {"error": "Connection failed"}
        action = node.post(shared, prep_res, exec_res)

        assert action == "error"
        assert "error" in shared
        assert shared["error"] == "Connection failed"
        assert shared["error_details"] == {
            "server": "test",
            "tool": "failing-tool",
            "timeout": False,
        }

        # Test tool-level error - should return "error" for repair system
        shared = {}
        exec_res = {"result": {"error": "Repository not found", "is_tool_error": True}}
        action = node.post(shared, prep_res, exec_res)

        # Tool errors return "error" to trigger repair system (line 384 in node.py)
        assert action == "error"
        assert "error" in shared
        assert shared["error"] == "Repository not found"

    def test_mcp_node_does_not_write_server_specific_result_alias(self):
        """MCP nodes do not expose duplicate server/tool result aliases.

        In a real workflow each MCP node is already namespaced by node id. A
        second ``<server>_<tool>_result`` key inside that namespace is not
        validator-addressable and creates duplicate probe paths.
        """
        node = MCPNode()
        node.set_params({"__mcp_server__": "github", "__mcp_tool__": "list-issues"})

        shared = {}
        prep = {"server": "github", "tool": "list-issues", "arguments": {}}
        exec_res = {"result": ["issue1", "issue2", "issue3"]}
        node.post(shared, prep, exec_res)

        assert shared == {"result": ["issue1", "issue2", "issue3"]}
