"""Tests for registry_run MCP node support.

This test ensures that MCP nodes work correctly via registry_run by verifying
that the special __mcp_server__ and __mcp_tool__ parameters are injected.
"""

from unittest.mock import MagicMock, patch

from pflow.mcp_server.services.execution_service import ExecutionService


class TestRegistryRunMCP:
    """Test MCP node execution via registry_run."""

    def test_mcp_node_parameter_injection(self):
        """Verify MCP nodes get __mcp_server__ and __mcp_tool__ injected."""
        # Setup: Mock the registry and node execution
        with (
            patch("pflow.mcp_server.services.execution_service.Registry") as mock_registry_class,
            patch("pflow.mcp_server.services.execution_service.import_node_class") as mock_import,
            patch("pflow.runtime.compiler._parse_mcp_node_type") as mock_parse,
        ):
            # Configure mock registry
            mock_registry = MagicMock()
            mock_registry_class.return_value = mock_registry
            mock_registry.load.return_value = {
                "mcp-test-server-TEST_TOOL": {
                    "class_name": "MCPNode",
                    "module": "pflow.nodes.mcp.node",
                }
            }

            # Configure mock node
            mock_node_instance = MagicMock()
            mock_node_class = MagicMock(return_value=mock_node_instance)
            mock_import.return_value = mock_node_class

            # Configure node execution to succeed
            mock_node_instance.run.return_value = "default"

            # Configure MCP parser
            mock_parse.return_value = ("test-server", "TEST_TOOL")

            # Execute: Call registry_run with an MCP node
            result = ExecutionService.run_registry_node(
                node_type="mcp-test-server-TEST_TOOL", parameters={"test_param": "test_value"}
            )

            # Verify: Parser was called to extract server and tool
            mock_parse.assert_called_once_with("mcp-test-server-TEST_TOOL")

            # Verify: set_params was called with injected parameters
            mock_node_instance.set_params.assert_called_once()
            injected_params = mock_node_instance.set_params.call_args[0][0]

            assert "__mcp_server__" in injected_params
            assert "__mcp_tool__" in injected_params
            assert injected_params["__mcp_server__"] == "test-server"
            assert injected_params["__mcp_tool__"] == "TEST_TOOL"
            assert injected_params["test_param"] == "test_value"

            # Verify: Result is a string (formatted output)
            assert isinstance(result, str)

    def test_regular_node_not_affected(self):
        """Verify regular (non-MCP) nodes still work without modification."""
        with (
            patch("pflow.mcp_server.services.execution_service.Registry") as mock_registry_class,
            patch("pflow.mcp_server.services.execution_service.import_node_class") as mock_import,
        ):
            # Configure mocks
            mock_registry = MagicMock()
            mock_registry_class.return_value = mock_registry
            mock_registry.load.return_value = {
                "shell": {
                    "class_name": "ShellNode",
                    "module": "pflow.nodes.shell.node",
                }
            }

            mock_node_instance = MagicMock()
            mock_node_class = MagicMock(return_value=mock_node_instance)
            mock_import.return_value = mock_node_class
            mock_node_instance.run.return_value = "default"

            # Execute: Call with regular node
            result = ExecutionService.run_registry_node(node_type="shell", parameters={"command": "echo test"})

            # Verify: set_params called with original parameters only (no MCP injection)
            mock_node_instance.set_params.assert_called_once()
            params = mock_node_instance.set_params.call_args[0][0]

            assert params == {"command": "echo test"}
            assert "__mcp_server__" not in params
            assert "__mcp_tool__" not in params
            assert isinstance(result, str)

    def test_template_variable_resolution_from_environment(self):
        """Verify ${var} templates are resolved from environment variables."""
        with (
            patch("pflow.mcp_server.services.execution_service.Registry") as mock_registry_class,
            patch("pflow.mcp_server.services.execution_service.import_node_class") as mock_import,
            patch.dict("os.environ", {"TEST_API_KEY": "secret-token-12345"}),
        ):
            # Configure mocks
            mock_registry = MagicMock()
            mock_registry_class.return_value = mock_registry
            mock_registry.load.return_value = {
                "http": {
                    "class_name": "HttpNode",
                    "module": "pflow.nodes.http.node",
                }
            }

            mock_node_instance = MagicMock()
            mock_node_class = MagicMock(return_value=mock_node_instance)
            mock_import.return_value = mock_node_class
            mock_node_instance.run.return_value = "default"

            # Execute: Call with ${VAR} template in parameters
            result = ExecutionService.run_registry_node(
                node_type="http", parameters={"url": "https://api.example.com", "auth_token": "${TEST_API_KEY}"}
            )

            # Verify: set_params called with resolved value (not template)
            mock_node_instance.set_params.assert_called_once()
            resolved_params = mock_node_instance.set_params.call_args[0][0]

            assert resolved_params["auth_token"] == "secret-token-12345"  # noqa: S105 - Test fixture, not real credential
            assert "${TEST_API_KEY}" not in str(resolved_params)
            assert isinstance(result, str)

    def test_template_resolution_nested_structures(self):
        """Verify ${var} templates are resolved in nested dicts and lists."""
        with (
            patch("pflow.mcp_server.services.execution_service.Registry") as mock_registry_class,
            patch("pflow.mcp_server.services.execution_service.import_node_class") as mock_import,
            patch.dict("os.environ", {"API_KEY": "key123", "API_SECRET": "secret456"}),
        ):
            # Configure mocks
            mock_registry = MagicMock()
            mock_registry_class.return_value = mock_registry
            mock_registry.load.return_value = {
                "http": {
                    "class_name": "HttpNode",
                    "module": "pflow.nodes.http.node",
                }
            }

            mock_node_instance = MagicMock()
            mock_node_class = MagicMock(return_value=mock_node_instance)
            mock_import.return_value = mock_node_class
            mock_node_instance.run.return_value = "default"

            # Execute: Call with nested structure containing templates
            result = ExecutionService.run_registry_node(
                node_type="http",
                parameters={
                    "url": "https://api.example.com",
                    "headers": {"Authorization": "Bearer ${API_KEY}", "X-Secret": "${API_SECRET}"},
                    "body": {"credentials": ["${API_KEY}", "${API_SECRET}"]},
                },
            )

            # Verify: Nested templates resolved
            mock_node_instance.set_params.assert_called_once()
            resolved_params = mock_node_instance.set_params.call_args[0][0]

            assert resolved_params["headers"]["Authorization"] == "Bearer key123"
            assert resolved_params["headers"]["X-Secret"] == "secret456"
            assert resolved_params["body"]["credentials"] == ["key123", "secret456"]
            assert isinstance(result, str)
