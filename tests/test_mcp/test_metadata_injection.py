"""
Complete tests for MCP metadata injection that catch real bugs.

These tests go beyond basic functionality to catch actual production issues
that would break MCP tool execution. Consolidated from multiple test files
to avoid redundancy while maintaining comprehensive coverage.
"""

from unittest.mock import MagicMock, patch

from pflow.runtime.compiler import _inject_special_parameters


class TestMetadataInjectionRealBugs:
    """Test metadata injection edge cases that cause real failures."""

    def test_tool_names_with_underscores_preserved(self):
        """Tool names with underscores should be preserved exactly.

        Real Bug: GitHub tools use underscores (e.g., list_repositories).
        If we convert underscores to dashes, the MCP call fails.
        """
        # Mock the MCPServerManager to provide the github server
        with patch("pflow.mcp.manager.MCPServerManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.list_servers.return_value = ["github"]
            mock_manager_class.return_value = mock_manager

            params = _inject_special_parameters(
                node_type="mcp-github-list_repositories", node_id="test", params={"per_page": 30}, registry=None
            )

            # CRITICAL: Must preserve underscore in tool name
            assert params["__mcp_tool__"] == "list_repositories"
            assert params["__mcp_server__"] == "github"

    def test_deeply_nested_tool_names(self):
        """Tools with many segments should preserve everything after server.

        Real Bug: Slack tools have long names like get-channel-history.
        We must preserve the full tool name structure.
        """
        # Mock the MCPServerManager to provide the slack server
        with patch("pflow.mcp.manager.MCPServerManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.list_servers.return_value = ["slack"]
            mock_manager_class.return_value = mock_manager

            params = _inject_special_parameters(
                node_type="mcp-slack-get-channel-history-with-threads", node_id="test", params={}, registry=None
            )

            assert params["__mcp_server__"] == "slack"
            # Everything after server name becomes tool name
            assert params["__mcp_tool__"] == "get-channel-history-with-threads"

    def test_numeric_params_preserved_as_numbers(self):
        """Numeric parameters must stay numeric, not become strings.

        Real Bug: MCP servers validate parameter types. If we pass "30"
        instead of 30 for 'limit', the validation fails with cryptic errors.
        """
        # Mock the MCPServerManager to provide the github server
        with patch("pflow.mcp.manager.MCPServerManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.list_servers.return_value = ["github"]
            mock_manager_class.return_value = mock_manager

            params = _inject_special_parameters(
                node_type="mcp-github-list-issues",
                node_id="test",
                params={
                    "limit": 30,  # Must stay as integer
                    "page": 1,
                    "is_open": True,  # Must stay as boolean
                    "threshold": 0.5,  # Must stay as float
                },
                registry=None,
            )

            # Types must be preserved
            assert isinstance(params["limit"], int)
            assert isinstance(params["page"], int)
            assert isinstance(params["is_open"], bool)
            assert isinstance(params["threshold"], float)

            # Metadata injection shouldn't change types
            assert params["limit"] == 30
            assert params["is_open"] is True

    def test_empty_server_or_tool_not_injected(self):
        """Malformed node types should not inject broken metadata.

        Real Bug: If we inject __mcp_server__="" it causes confusing
        downstream errors. Better to not inject at all.
        """
        # Just "mcp-" without server
        params = _inject_special_parameters(node_type="mcp-", node_id="test", params={"key": "value"}, registry=None)
        assert "__mcp_server__" not in params
        assert "__mcp_tool__" not in params

        # Just "mcp-server" without tool
        params = _inject_special_parameters(
            node_type="mcp-server", node_id="test", params={"key": "value"}, registry=None
        )
        assert "__mcp_server__" not in params
        assert "__mcp_tool__" not in params

    def test_special_params_always_overwritten_for_consistency(self):
        """Special params are ALWAYS overwritten based on node type.

        Design Decision: The node type is the source of truth for MCP metadata.
        Even if params contain __mcp_* keys, we overwrite them to ensure
        consistency and prevent confusion. The compiler determines metadata
        from the node type string, not from user-provided parameters.

        Real Bug Prevention: If users could override these, they might
        accidentally use wrong server/tool combinations that don't exist.
        """
        # Mock the MCPServerManager to provide the github server
        with patch("pflow.mcp.manager.MCPServerManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.list_servers.return_value = ["github"]
            mock_manager_class.return_value = mock_manager

            params = _inject_special_parameters(
                node_type="mcp-github-create-issue",
                node_id="test",
                params={
                    "__mcp_server__": "custom-server",  # Will be overwritten
                    "__mcp_tool__": "custom-tool",  # Will be overwritten
                    "title": "Test",
                },
                registry=None,
            )

            # Verify that node type is the source of truth
            assert params["__mcp_server__"] == "github"  # From node type
            assert params["__mcp_tool__"] == "create-issue"  # From node type
            assert params["title"] == "Test"  # User param preserved

    def test_registry_injection_not_affected_by_mcp(self):
        """Workflow nodes should still get registry injection with MCP nodes present.

        Real Bug: The MCP injection logic shouldn't break workflow node handling.
        """
        mock_registry = MagicMock()

        # Workflow node should get registry
        params = _inject_special_parameters(
            node_type="workflow", node_id="test", params={"workflow_name": "test"}, registry=mock_registry
        )
        assert params["__registry__"] == mock_registry
        assert "__mcp_server__" not in params

        # MCP node should NOT get registry
        # Mock the MCPServerManager to provide the test server
        with patch("pflow.mcp.manager.MCPServerManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.list_servers.return_value = ["test"]
            mock_manager_class.return_value = mock_manager

            params = _inject_special_parameters(
                node_type="mcp-test-tool", node_id="test", params={}, registry=mock_registry
            )
            assert "__registry__" not in params
            assert params["__mcp_server__"] == "test"
            assert params["__mcp_tool__"] == "tool"


class TestMetadataInjectionInWorkflow:
    """Test metadata injection in full workflow context."""

    def test_multiple_mcp_nodes_independent_metadata(self):
        """Each MCP node in a workflow must get its own correct metadata.

        Real Bug: If metadata is shared/leaked between nodes, wrong tools execute.
        This actually caught a bug where all nodes got the same metadata!
        """
        from pflow.runtime.compiler import compile_ir_to_flow
        from pocketflow import BaseNode

        workflow_ir = {
            "name": "multi-mcp",
            "nodes": [
                {"id": "gh_issues", "type": "mcp-github-list-issues", "params": {"limit": 10}},
                {"id": "slack_users", "type": "mcp-slack-get-users", "params": {}},
                {"id": "fs_read", "type": "mcp-filesystem-read-file", "params": {"path": "/test/mock/test.txt"}},
            ],
            "edges": [],
        }

        # Track what each node receives
        captured_params = {}

        class CapturingNode(BaseNode):
            def __init__(self):
                super().__init__()

            def set_params(self, params):
                # Store params by server name for verification
                if "__mcp_server__" in params:
                    captured_params[params["__mcp_server__"]] = params.copy()

            def exec(self, shared, **kwargs):
                return {}

        # Mock registry and imports
        mock_registry = MagicMock()
        mock_registry.load.return_value = {
            "mcp-github-list-issues": {"class_name": "CapturingNode", "module": "test", "file_path": "virtual://mcp"},
            "mcp-slack-get-users": {"class_name": "CapturingNode", "module": "test", "file_path": "virtual://mcp"},
            "mcp-filesystem-read-file": {"class_name": "CapturingNode", "module": "test", "file_path": "virtual://mcp"},
        }

        # Mock the MCPServerManager to provide the servers
        with patch("pflow.mcp.manager.MCPServerManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.list_servers.return_value = ["github", "slack", "filesystem"]
            mock_manager_class.return_value = mock_manager

            with patch("pflow.runtime.compiler.importlib.import_module") as mock_import:
                mock_module = MagicMock()
                mock_module.CapturingNode = CapturingNode
                mock_import.return_value = mock_module

                compile_ir_to_flow(workflow_ir, mock_registry)

        # Verify each node got correct, independent metadata
        assert len(captured_params) == 3

        assert captured_params["github"]["__mcp_server__"] == "github"
        assert captured_params["github"]["__mcp_tool__"] == "list-issues"
        assert captured_params["github"]["limit"] == 10

        assert captured_params["slack"]["__mcp_server__"] == "slack"
        assert captured_params["slack"]["__mcp_tool__"] == "get-users"

        assert captured_params["filesystem"]["__mcp_server__"] == "filesystem"
        assert captured_params["filesystem"]["__mcp_tool__"] == "read-file"
        assert captured_params["filesystem"]["path"] == "/test/mock/test.txt"


class TestMetadataInjectionEdgeCases:
    """Test edge cases that were found in the original tests."""

    def test_params_immutability(self):
        """Original params dict should not be mutated during injection.

        Real Bug: If we modify the original params dict, it could affect
        other parts of the system that still reference it.
        """
        original_params = {"key": "value", "number": 42}
        original_params_copy = original_params.copy()

        # Mock the MCPServerManager to provide the test server
        with patch("pflow.mcp.manager.MCPServerManager") as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.list_servers.return_value = ["test"]
            mock_manager_class.return_value = mock_manager

            result = _inject_special_parameters(
                node_type="mcp-test-tool", node_id="test", params=original_params, registry=None
            )

            # Original must be unchanged
            assert original_params == original_params_copy
            assert "__mcp_server__" not in original_params
            assert "__mcp_tool__" not in original_params

            # Result has metadata (new dict)
            assert result is not original_params
            assert result["__mcp_server__"] == "test"
            assert result["__mcp_tool__"] == "tool"
            assert result["key"] == "value"
            assert result["number"] == 42

    def test_malformed_node_types_handled_gracefully(self):
        """Malformed MCP node types should not crash or inject broken metadata.

        Real Bug: Node types like "mcp-" or "mcp" could cause index errors
        or inject empty strings as metadata.
        """
        # Just "mcp" without any dashes
        params = _inject_special_parameters(node_type="mcp", node_id="test", params={"data": "value"}, registry=None)
        assert "__mcp_server__" not in params
        assert "__mcp_tool__" not in params
        assert params["data"] == "value"

        # "mcp-" with trailing dash
        params = _inject_special_parameters(node_type="mcp-", node_id="test", params={}, registry=None)
        assert "__mcp_server__" not in params
        assert "__mcp_tool__" not in params

        # "mcp-server" without tool (only 2 parts)
        params = _inject_special_parameters(node_type="mcp-server", node_id="test", params={}, registry=None)
        assert "__mcp_server__" not in params
        assert "__mcp_tool__" not in params
