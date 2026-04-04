"""Tests for registry_run MCP node support.

After Task 138, run_registry_node() routes through WorkflowRunner with
synthetic IR. Tests verify behavior through the MCP service method, mocking
at the Runner level or using real shell execution where feasible.
"""

from unittest.mock import MagicMock, patch

from pflow.execution.result import ExecutionResult
from pflow.mcp_server.services.execution_service import ExecutionService, _build_error_text


class TestRegistryRunMCP:
    """Test MCP node execution via registry_run."""

    def test_mcp_node_parameter_injection(self):
        """Verify MCP nodes get __mcp_server__ and __mcp_tool__ in synthetic IR.

        run_registry_node builds synthetic IR with node params. The compiler
        handles MCP metadata injection during compilation (_parse_mcp_node_type).
        We verify the synthetic IR is correctly constructed by checking that
        the Runner receives it with the right node type and params.
        """
        with patch("pflow.execution.runner.WorkflowRunner") as mock_runner_cls:
            # Configure mock runner to return success
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            mock_runner.run.return_value = ExecutionResult(
                success=True,
                shared_after={
                    "mcp-test-server-TEST_TOOL": {"result": "test output"},
                },
            )

            # Registry must recognize the node type
            with patch("pflow.mcp_server.services.execution_service.Registry") as mock_registry_cls:
                mock_registry = MagicMock()
                mock_registry_cls.return_value = mock_registry
                mock_registry.load.return_value = {
                    "mcp-test-server-TEST_TOOL": {
                        "class_name": "MCPNode",
                        "module": "pflow.nodes.mcp.node",
                    }
                }

                result = ExecutionService.run_registry_node(
                    node_type="mcp-test-server-TEST_TOOL", parameters={"test_param": "test_value"}
                )

                # Verify Runner was called with synthetic IR containing the MCP node
                mock_runner.run.assert_called_once()
                call_args = mock_runner.run.call_args
                synthetic_ir = call_args[0][0]  # First positional arg

                assert len(synthetic_ir["nodes"]) == 1
                node = synthetic_ir["nodes"][0]
                assert node["type"] == "mcp-test-server-TEST_TOOL"
                assert node["params"]["test_param"] == "test_value"
                assert isinstance(result, str)

    def test_regular_node_not_affected(self):
        """Verify regular (non-MCP) nodes work via synthetic IR through Runner."""
        with patch("pflow.execution.runner.WorkflowRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            mock_runner.run.return_value = ExecutionResult(
                success=True,
                shared_after={"shell": {"stdout": "test output"}},
            )

            with patch("pflow.mcp_server.services.execution_service.Registry") as mock_registry_cls:
                mock_registry = MagicMock()
                mock_registry_cls.return_value = mock_registry
                mock_registry.load.return_value = {
                    "shell": {
                        "class_name": "ShellNode",
                        "module": "pflow.nodes.shell.node",
                    }
                }

                result = ExecutionService.run_registry_node(node_type="shell", parameters={"command": "echo test"})

                # Verify synthetic IR has the right params (no MCP injection)
                call_args = mock_runner.run.call_args
                synthetic_ir = call_args[0][0]
                node = synthetic_ir["nodes"][0]

                assert node["params"] == {"command": "echo test"}
                assert "__mcp_server__" not in node["params"]
                assert "__mcp_tool__" not in node["params"]
                assert isinstance(result, str)

    def test_template_variable_resolution_from_environment(self):
        """Verify ${var} templates are resolved from environment variables.

        expand_env_vars_nested runs BEFORE building synthetic IR,
        so resolved values end up in node.params.
        """
        with (
            patch("pflow.execution.runner.WorkflowRunner") as mock_runner_cls,
            patch.dict("os.environ", {"TEST_API_KEY": "secret-token-12345"}),
        ):
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            mock_runner.run.return_value = ExecutionResult(
                success=True,
                shared_after={"http": {"response": "ok"}},
            )

            with patch("pflow.mcp_server.services.execution_service.Registry") as mock_registry_cls:
                mock_registry = MagicMock()
                mock_registry_cls.return_value = mock_registry
                mock_registry.load.return_value = {
                    "http": {"class_name": "HttpNode", "module": "pflow.nodes.http.node"}
                }

                ExecutionService.run_registry_node(
                    node_type="http", parameters={"url": "https://api.example.com", "auth_token": "${TEST_API_KEY}"}
                )

                # Verify env var was resolved in node params
                call_args = mock_runner.run.call_args
                synthetic_ir = call_args[0][0]
                resolved_params = synthetic_ir["nodes"][0]["params"]

                assert resolved_params["auth_token"] == "secret-token-12345"  # noqa: S105 - Test fixture
                assert "${TEST_API_KEY}" not in str(resolved_params)

    def test_template_resolution_nested_structures(self):
        """Verify ${var} templates are resolved in nested dicts and lists."""
        with (
            patch("pflow.execution.runner.WorkflowRunner") as mock_runner_cls,
            patch.dict("os.environ", {"API_KEY": "key123", "API_SECRET": "secret456"}),
        ):
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            mock_runner.run.return_value = ExecutionResult(
                success=True,
                shared_after={"http": {"response": "ok"}},
            )

            with patch("pflow.mcp_server.services.execution_service.Registry") as mock_registry_cls:
                mock_registry = MagicMock()
                mock_registry_cls.return_value = mock_registry
                mock_registry.load.return_value = {
                    "http": {"class_name": "HttpNode", "module": "pflow.nodes.http.node"}
                }

                ExecutionService.run_registry_node(
                    node_type="http",
                    parameters={
                        "url": "https://api.example.com",
                        "headers": {"Authorization": "Bearer ${API_KEY}", "X-Secret": "${API_SECRET}"},
                        "body": {"credentials": ["${API_KEY}", "${API_SECRET}"]},
                    },
                )

                call_args = mock_runner.run.call_args
                synthetic_ir = call_args[0][0]
                resolved_params = synthetic_ir["nodes"][0]["params"]

                assert resolved_params["headers"]["Authorization"] == "Bearer key123"
                assert resolved_params["headers"]["X-Secret"] == "secret456"
                assert resolved_params["body"]["credentials"] == ["key123", "secret456"]

    def test_template_resolution_from_settings_json(self):
        """Verify ${var} templates are resolved from settings.json."""
        with (
            patch("pflow.execution.runner.WorkflowRunner") as mock_runner_cls,
            patch.dict("os.environ", {}, clear=True),
            patch("pflow.core.settings.SettingsManager") as mock_settings_cls,
        ):
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            mock_runner.run.return_value = ExecutionResult(
                success=True,
                shared_after={"http": {"response": "ok"}},
            )

            with patch("pflow.mcp_server.services.execution_service.Registry") as mock_registry_cls:
                mock_registry = MagicMock()
                mock_registry_cls.return_value = mock_registry
                mock_registry.load.return_value = {
                    "http": {"class_name": "HttpNode", "module": "pflow.nodes.http.node"}
                }

                # Configure settings
                mock_settings = MagicMock()
                mock_settings.list_env.return_value = {"replicate_api_token": "from-settings"}
                mock_settings_cls.return_value = mock_settings

                ExecutionService.run_registry_node(
                    node_type="http", parameters={"auth_token": "${REPLICATE_API_TOKEN}"}
                )

                call_args = mock_runner.run.call_args
                synthetic_ir = call_args[0][0]
                resolved_params = synthetic_ir["nodes"][0]["params"]

                assert resolved_params["auth_token"] == "from-settings"  # noqa: S105 - Test fixture

    def test_missing_variable_raises_helpful_error(self):
        """Verify helpful error message for missing variables.

        expand_env_vars_nested(raise_on_missing=True) raises before the Runner
        is ever called. run_registry_node catches the exception and returns
        a formatted error string.
        """
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("pflow.core.settings.SettingsManager") as mock_settings_cls,
            patch("pflow.mcp_server.services.execution_service.Registry") as mock_registry_cls,
        ):
            mock_registry = MagicMock()
            mock_registry_cls.return_value = mock_registry
            mock_registry.load.return_value = {"http": {"class_name": "HttpNode", "module": "pflow.nodes.http.node"}}

            mock_settings = MagicMock()
            mock_settings.list_env.return_value = {}
            mock_settings_cls.return_value = mock_settings

            # Execute with missing variable should return error (not raise)
            result = ExecutionService.run_registry_node(node_type="http", parameters={"auth_token": "${MISSING_VAR}"})

            # Should return error message string containing the var name
            assert isinstance(result, str)
            assert "MISSING_VAR" in result

    def test_execution_failure_shows_actual_error(self):
        """Verify run_registry_node propagates actual error details on failure.

        When a shell command fails, the error text returned to MCP agents
        should contain the actual error message — not just "Workflow execution failed".
        Regression guard for _build_error_text shape mismatch.
        """
        result = ExecutionService.run_registry_node("shell", parameters={"command": "exit 1"})
        assert isinstance(result, str)
        # Must contain actual error context, not generic fallback
        assert "Workflow execution failed" not in result or "exit" in result.lower()

    def test_build_error_text_omits_error_number_for_single_error(self):
        """Single-error MCP text should use "Error at node", not "Error 1 at node"."""
        error_text = _build_error_text({
            "error": {"message": "Workflow execution failed"},
            "errors": [{"node_id": "run-tests", "message": "Shell command failed"}],
            "trace_path": "",
        })

        assert "Error at node 'run-tests':" in error_text
        assert "Error 1 at node 'run-tests':" not in error_text
