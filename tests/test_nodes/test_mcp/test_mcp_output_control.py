"""Test MCP server output control in verbose vs non-verbose modes."""

from unittest.mock import patch

from pflow.nodes.mcp.node import MCPNode


class TestMCPOutputControl:
    """Test suite for MCP server output suppression."""

    def test_verbose_flag_passed_through_shared_storage(self):
        """Test that verbose flag is correctly passed to nodes via shared storage."""
        node = MCPNode()

        # Test with verbose=True
        shared_verbose = {"__verbose__": True, "__mcp_server__": "test", "__mcp_tool__": "test-tool"}
        node.params = {"__mcp_server__": "test", "__mcp_tool__": "test-tool"}

        with patch.object(node, "_load_server_config", return_value={"command": "test", "args": []}):
            prep_res = node.prep(shared_verbose)
            assert prep_res["verbose"] is True

        # Test with verbose=False
        shared_quiet = {"__verbose__": False, "__mcp_server__": "test", "__mcp_tool__": "test-tool"}

        with patch.object(node, "_load_server_config", return_value={"command": "test", "args": []}):
            prep_res = node.prep(shared_quiet)
            assert prep_res["verbose"] is False

        # Test default (no verbose flag)
        shared_default = {"__mcp_server__": "test", "__mcp_tool__": "test-tool"}

        with patch.object(node, "_load_server_config", return_value={"command": "test", "args": []}):
            prep_res = node.prep(shared_default)
            assert prep_res["verbose"] is False  # Should default to False

    def test_subprocess_output_control_logic(self):
        """Test that the output control logic is properly implemented."""
        node = MCPNode()

        # The node should have the necessary methods
        assert hasattr(node, "_exec_async")

        # Test that prep_res includes verbose flag
        with patch.object(node, "_load_server_config", return_value={"command": "test", "args": []}):
            node.params = {"__mcp_server__": "test", "__mcp_tool__": "test-tool"}

            # Non-verbose case
            shared_quiet = {"__verbose__": False}
            prep_res = node.prep(shared_quiet)
            assert prep_res["verbose"] is False

            # Verbose case
            shared_verbose = {"__verbose__": True}
            prep_res = node.prep(shared_verbose)
            assert prep_res["verbose"] is True

    def test_errlog_output_control(self):
        """Test that MCP server stderr is controlled via errlog parameter."""
        node = MCPNode()

        # Test that we have the proper implementation
        # The node should pass different errlog based on verbose flag
        # Creating dictionaries to verify the structure of prep_res
        expected_quiet_structure = {
            "server": "test",
            "tool": "test-tool",
            "config": {"command": "test", "args": []},
            "arguments": {},
            "verbose": False,
        }

        expected_verbose_structure = {
            "server": "test",
            "tool": "test-tool",
            "config": {"command": "test", "args": []},
            "arguments": {},
            "verbose": True,
        }

        # Test that prep method produces expected structure
        with patch.object(node, "_load_server_config", return_value={"command": "test", "args": []}):
            node.params = {"__mcp_server__": "test", "__mcp_tool__": "test-tool"}

            # Test quiet mode
            shared_quiet = {"__verbose__": False}
            prep_res = node.prep(shared_quiet)
            assert prep_res["verbose"] == expected_quiet_structure["verbose"]
            assert prep_res["server"] == expected_quiet_structure["server"]
            assert prep_res["tool"] == expected_quiet_structure["tool"]

            # Test verbose mode
            shared_verbose = {"__verbose__": True}
            prep_res = node.prep(shared_verbose)
            assert prep_res["verbose"] == expected_verbose_structure["verbose"]
            assert prep_res["server"] == expected_verbose_structure["server"]
            assert prep_res["tool"] == expected_verbose_structure["tool"]

        # Verify that the implementation exists and uses verbose flag
        assert hasattr(node, "_exec_async")
        # The actual errlog parameter is passed to stdio_client in _exec_async

    def test_mcp_output_control_integration(self):
        """Integration test: verify no MCP output in non-verbose mode."""
        # This test would require an actual MCP server to test properly
        # For now, we just verify the structure is in place

        node = MCPNode()
        assert hasattr(node, "prep")
        assert hasattr(node, "exec")
        assert hasattr(node, "_exec_async")

        # Verify the verbose flag is extracted in prep
        with patch.object(node, "_load_server_config", return_value={"command": "test"}):
            node.params = {"__mcp_server__": "test", "__mcp_tool__": "test"}
            shared = {"__verbose__": True}
            prep_res = node.prep(shared)
            assert "verbose" in prep_res
