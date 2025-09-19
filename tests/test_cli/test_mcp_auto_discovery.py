"""Tests for automatic MCP server discovery at startup.

This module tests the _auto_discover_mcp_servers() function that runs
at pflow startup to automatically sync MCP servers. The tests focus on:
1. Boundary testing - mocking at MCP module level, not internals
2. Comprehensive scenarios - all startup conditions
3. Error resilience - partial failures don't break everything
4. Output control - interactive vs non-interactive modes
"""

from unittest.mock import Mock, call, patch

from pflow.cli.main import _auto_discover_mcp_servers


class TestAutoDiscovery:
    """Test automatic MCP server discovery at pflow startup."""

    def test_no_servers_configured_does_nothing(self, tmp_path, monkeypatch):
        """Test that auto-discovery exits early when no servers configured."""
        monkeypatch.setenv("HOME", str(tmp_path))

        # Create mock context
        ctx = Mock()
        ctx.obj = {}

        # Mock output controller
        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.main._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar") as mock_registrar_class,
        ):
            # Configure manager to return no servers
            mock_manager = mock_manager_class.return_value
            mock_manager.list_servers.return_value = []

            # Run auto-discovery
            _auto_discover_mcp_servers(ctx, verbose=True)

            # Should exit early, not attempt discovery
            mock_manager.list_servers.assert_called_once()
            # These should never be instantiated when no servers
            mock_registry_class.assert_not_called()
            mock_discovery_class.assert_not_called()
            mock_registrar_class.assert_not_called()

    def test_successful_discovery_all_servers(self, tmp_path, monkeypatch):
        """Test successful discovery of tools from all configured servers."""
        monkeypatch.setenv("HOME", str(tmp_path))

        # Create mock context
        ctx = Mock()
        ctx.obj = {}

        # Mock output controller
        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.main._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar") as mock_registrar_class,
            patch("pflow.cli.main.click.echo") as mock_echo,
        ):
            # Configure manager to return servers
            mock_manager = mock_manager_class.return_value
            mock_manager.list_servers.return_value = ["github", "slack"]
            mock_manager.config_path = tmp_path / ".pflow" / "mcp-servers.json"
            mock_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
            mock_manager.config_path.touch()  # Create the config file

            # Configure registry
            mock_registry = mock_registry_class.return_value
            mock_registry.list_nodes.return_value = []
            # Make it appear that sync is needed (old sync time)
            mock_registry.get_metadata.side_effect = lambda key, default: {
                "mcp_last_sync_time": 0,  # Very old sync
                "mcp_servers_hash": "",  # No previous hash
            }.get(key, default)
            mock_registry.load.return_value = {}  # Empty registry for cleaning old entries

            # Configure discovery to return tools
            mock_discovery = mock_discovery_class.return_value
            mock_discovery.discover_tools.side_effect = [
                ["create-issue", "list-issues"],  # github tools
                ["send-message", "list-channels"],  # slack tools
            ]

            # Configure registrar
            mock_registrar = mock_registrar_class.return_value

            # Run auto-discovery with verbose=False (summary only)
            _auto_discover_mcp_servers(ctx, verbose=False)

            # Verify MCPDiscovery was instantiated with manager
            mock_discovery_class.assert_called_once_with(mock_manager)

            # Verify discovery was called for each server
            assert mock_discovery.discover_tools.call_count == 2
            mock_discovery.discover_tools.assert_any_call("github", verbose=False)
            mock_discovery.discover_tools.assert_any_call("slack", verbose=False)

            # Verify tools were registered
            assert mock_registrar.register_tools.call_count == 2
            mock_registrar.register_tools.assert_any_call("github", ["create-issue", "list-issues"])
            mock_registrar.register_tools.assert_any_call("slack", ["send-message", "list-channels"])

            # Verify summary message shown
            mock_echo.assert_called_with("✓ Synced 4 MCP tool(s) from 2 server(s)", err=True)

    def test_partial_failure_continues_with_other_servers(self, tmp_path, monkeypatch):
        """Test that failure on one server doesn't stop discovery of others."""
        monkeypatch.setenv("HOME", str(tmp_path))

        ctx = Mock()
        ctx.obj = {}

        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.main._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar") as mock_registrar_class,
            patch("pflow.cli.main.logger") as mock_logger,
        ):
            # Configure manager
            mock_manager = mock_manager_class.return_value
            mock_manager.list_servers.return_value = ["broken", "working"]
            mock_manager.config_path = tmp_path / ".pflow" / "mcp-servers.json"
            mock_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
            mock_manager.config_path.touch()  # Create the config file

            # Configure registry
            mock_registry = mock_registry_class.return_value
            mock_registry.list_nodes.return_value = []
            # Make it appear that sync is needed (old sync time)
            mock_registry.get_metadata.side_effect = lambda key, default: {
                "mcp_last_sync_time": 0,  # Very old sync
                "mcp_servers_hash": "",  # No previous hash
            }.get(key, default)
            mock_registry.load.return_value = {}  # Empty registry for cleaning old entries

            # Configure discovery - first fails, second works
            mock_discovery = mock_discovery_class.return_value
            mock_discovery.discover_tools.side_effect = [
                Exception("Connection failed"),  # broken server
                ["tool1", "tool2"],  # working server
            ]

            # Configure registrar
            mock_registrar = mock_registrar_class.return_value

            # Run auto-discovery
            _auto_discover_mcp_servers(ctx, verbose=False)

            # Verify both servers were attempted
            assert mock_discovery.discover_tools.call_count == 2

            # Verify only working server's tools were registered
            mock_registrar.register_tools.assert_called_once_with("working", ["tool1", "tool2"])

            # Verify error was logged
            mock_logger.debug.assert_any_call("Failed to discover tools from broken: Connection failed")

    def test_verbose_mode_shows_progress(self, tmp_path, monkeypatch):
        """Test that verbose mode shows detailed progress messages."""
        monkeypatch.setenv("HOME", str(tmp_path))

        ctx = Mock()
        ctx.obj = {}

        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.main._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar"),
            patch("pflow.cli.main.click.echo") as mock_echo,
        ):
            mock_manager = mock_manager_class.return_value
            mock_manager.list_servers.return_value = ["test-server"]
            mock_manager.config_path = tmp_path / ".pflow" / "mcp-servers.json"
            mock_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
            mock_manager.config_path.touch()  # Create the config file

            mock_registry = mock_registry_class.return_value
            mock_registry.list_nodes.return_value = []
            # Make it appear that sync is needed (old sync time)
            mock_registry.get_metadata.side_effect = lambda key, default: {
                "mcp_last_sync_time": 0,  # Very old sync
                "mcp_servers_hash": "",  # No previous hash
            }.get(key, default)
            mock_registry.load.return_value = {}  # Empty registry for cleaning old entries

            mock_discovery = mock_discovery_class.return_value
            mock_discovery.discover_tools.return_value = ["tool1", "tool2"]

            # Run with verbose=True
            _auto_discover_mcp_servers(ctx, verbose=True)

            # Verify verbose messages shown
            mock_echo.assert_any_call("Discovering tools from MCP server 'test-server'...", err=True)
            mock_echo.assert_any_call("  ✓ Discovered 2 tool(s) from test-server", err=True)

    def test_non_interactive_mode_silent(self, tmp_path, monkeypatch):
        """Test that non-interactive mode (JSON, print) doesn't show progress."""
        monkeypatch.setenv("HOME", str(tmp_path))

        ctx = Mock()
        ctx.obj = {}

        # Mock non-interactive mode
        output_controller = Mock()
        output_controller.is_interactive.return_value = False

        with (
            patch("pflow.cli.main._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar"),
            patch("pflow.cli.main.click.echo") as mock_echo,
        ):
            mock_manager = mock_manager_class.return_value
            mock_manager.list_servers.return_value = ["server1"]

            mock_registry = mock_registry_class.return_value
            mock_registry.list_nodes.return_value = []

            mock_discovery = mock_discovery_class.return_value
            mock_discovery.discover_tools.return_value = ["tool1"]

            # Run auto-discovery
            _auto_discover_mcp_servers(ctx, verbose=True)

            # Verify NO messages shown (silent in non-interactive)
            mock_echo.assert_not_called()

    def test_import_error_handled_gracefully(self, tmp_path, monkeypatch):
        """Test that import errors are handled gracefully."""
        monkeypatch.setenv("HOME", str(tmp_path))

        ctx = Mock()
        ctx.obj = {}

        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.main._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager", side_effect=ImportError("MCP not installed")),
            patch("pflow.cli.main.logger") as mock_logger,
        ):
            # Should not crash
            _auto_discover_mcp_servers(ctx, verbose=True)

            # Verify error was logged at debug level
            mock_logger.debug.assert_called_with("MCP modules not available: MCP not installed")

    def test_general_exception_handled_gracefully(self, tmp_path, monkeypatch):
        """Test that general exceptions are handled gracefully."""
        monkeypatch.setenv("HOME", str(tmp_path))

        ctx = Mock()
        ctx.obj = {}

        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.main._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.cli.main.logger") as mock_logger,
        ):
            # Make manager crash
            mock_manager_class.side_effect = Exception("Unexpected error")

            # Should not crash
            _auto_discover_mcp_servers(ctx, verbose=True)

            # Verify error was logged at debug level
            mock_logger.debug.assert_called_with("Failed to auto-discover MCP servers: Unexpected error")

    def test_empty_tool_list_from_server(self, tmp_path, monkeypatch):
        """Test handling when a server returns no tools."""
        monkeypatch.setenv("HOME", str(tmp_path))

        ctx = Mock()
        ctx.obj = {}

        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.main._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar") as mock_registrar_class,
            patch("pflow.cli.main.click.echo") as mock_echo,
        ):
            mock_manager = mock_manager_class.return_value
            mock_manager.list_servers.return_value = ["empty-server"]

            mock_registry = mock_registry_class.return_value
            mock_registry.list_nodes.return_value = []

            # Server returns empty list (valid but no tools)
            mock_discovery = mock_discovery_class.return_value
            mock_discovery.discover_tools.return_value = []

            mock_registrar = mock_registrar_class.return_value

            # Run auto-discovery
            _auto_discover_mcp_servers(ctx, verbose=False)

            # Should not register anything for empty tool list
            mock_registrar.register_tools.assert_not_called()

            # Should not show summary for 0 tools
            mock_echo.assert_not_called()

    def test_mixed_success_and_empty_servers(self, tmp_path, monkeypatch):
        """Test mix of successful servers and servers with no tools."""
        monkeypatch.setenv("HOME", str(tmp_path))

        ctx = Mock()
        ctx.obj = {}

        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.main._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar") as mock_registrar_class,
            patch("pflow.cli.main.click.echo") as mock_echo,
        ):
            mock_manager = mock_manager_class.return_value
            mock_manager.list_servers.return_value = ["empty", "github", "another-empty"]
            mock_manager.config_path = tmp_path / ".pflow" / "mcp-servers.json"
            mock_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
            mock_manager.config_path.touch()  # Create the config file

            mock_registry = mock_registry_class.return_value
            mock_registry.list_nodes.return_value = []
            # Make it appear that sync is needed (old sync time)
            mock_registry.get_metadata.side_effect = lambda key, default: {
                "mcp_last_sync_time": 0,  # Very old sync
                "mcp_servers_hash": "",  # No previous hash
            }.get(key, default)
            mock_registry.load.return_value = {}  # Empty registry for cleaning old entries

            mock_discovery = mock_discovery_class.return_value
            mock_discovery.discover_tools.side_effect = [
                [],  # empty server
                ["create-issue", "list-issues"],  # github
                [],  # another empty
            ]

            mock_registrar = mock_registrar_class.return_value

            # Run auto-discovery
            _auto_discover_mcp_servers(ctx, verbose=False)

            # Should only register for non-empty server
            mock_registrar.register_tools.assert_called_once_with("github", ["create-issue", "list-issues"])

            # Summary counts servers that didn't fail (even if they had no tools)
            mock_echo.assert_called_with("✓ Synced 2 MCP tool(s) from 3 server(s)", err=True)

    def test_verbose_mode_with_failures(self, tmp_path, monkeypatch):
        """Test verbose mode shows failure details."""
        monkeypatch.setenv("HOME", str(tmp_path))

        ctx = Mock()
        ctx.obj = {}

        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.main._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar"),
            patch("pflow.cli.main.click.echo") as mock_echo,
        ):
            mock_manager = mock_manager_class.return_value
            mock_manager.list_servers.return_value = ["failing-server", "working-server"]
            mock_manager.config_path = tmp_path / ".pflow" / "mcp-servers.json"
            mock_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
            mock_manager.config_path.touch()  # Create the config file

            mock_registry = mock_registry_class.return_value
            mock_registry.list_nodes.return_value = []
            # Make it appear that sync is needed (old sync time)
            mock_registry.get_metadata.side_effect = lambda key, default: {
                "mcp_last_sync_time": 0,  # Very old sync
                "mcp_servers_hash": "",  # No previous hash
            }.get(key, default)
            mock_registry.load.return_value = {}  # Empty registry for cleaning old entries

            mock_discovery = mock_discovery_class.return_value
            mock_discovery.discover_tools.side_effect = [
                RuntimeError("Connection timeout"),
                ["tool1"],
            ]

            # Run with verbose=True
            _auto_discover_mcp_servers(ctx, verbose=True)

            # Verify progress messages shown
            expected_calls = [
                call("Discovering tools from MCP server 'failing-server'...", err=True),
                call("  ⚠ Failed to connect to failing-server", err=True),
                call("Discovering tools from MCP server 'working-server'...", err=True),
                call("  ✓ Discovered 1 tool(s) from working-server", err=True),
                call("⚠ Failed to connect to 1 server(s): failing-server", err=True),
            ]
            mock_echo.assert_has_calls(expected_calls)

    def test_already_synced_nodes_still_rediscover(self, tmp_path, monkeypatch):
        """Test that we always re-discover to catch updates, even with existing nodes."""
        monkeypatch.setenv("HOME", str(tmp_path))

        ctx = Mock()
        ctx.obj = {}

        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.main._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar") as mock_registrar_class,
        ):
            mock_manager = mock_manager_class.return_value
            mock_manager.list_servers.return_value = ["github"]
            mock_manager.config_path = tmp_path / ".pflow" / "mcp-servers.json"
            mock_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
            mock_manager.config_path.touch()  # Create the config file

            # Registry already has MCP nodes (previously synced)
            mock_registry = mock_registry_class.return_value
            mock_registry.list_nodes.return_value = [
                "mcp-github-create-issue",
                "mcp-github-list-issues",
                "regular-node",
            ]
            # Make it appear that sync is needed (old sync time)
            mock_registry.get_metadata.side_effect = lambda key, default: {
                "mcp_last_sync_time": 0,  # Very old sync
                "mcp_servers_hash": "",  # No previous hash
            }.get(key, default)
            mock_registry.load.return_value = {
                "mcp-github-create-issue": {},
                "mcp-github-list-issues": {},
            }  # Existing MCP entries to be cleaned

            mock_discovery = mock_discovery_class.return_value
            mock_discovery.discover_tools.return_value = ["create-issue", "list-issues", "new-tool"]

            mock_registrar = mock_registrar_class.return_value

            # Run auto-discovery
            _auto_discover_mcp_servers(ctx, verbose=False)

            # Should still attempt discovery
            mock_discovery.discover_tools.assert_called_with("github", verbose=False)

            # Should register the discovered tools (including new ones)
            mock_registrar.register_tools.assert_called_with("github", ["create-issue", "list-issues", "new-tool"])


class TestAutoDiscoveryIntegration:
    """Integration-level tests for auto-discovery.

    These tests use less mocking to verify the interactions between components.
    """

    def test_discovery_with_real_registry(self, tmp_path, monkeypatch):
        """Test discovery with real Registry to verify registration works."""
        from pflow.registry import Registry

        monkeypatch.setenv("HOME", str(tmp_path))

        # Create real registry
        registry_path = tmp_path / ".pflow" / "registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry = Registry(registry_path=registry_path)

        ctx = Mock()
        ctx.obj = {}

        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.main._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry", return_value=registry),  # Use real registry
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar") as mock_registrar_class,
        ):
            mock_manager = mock_manager_class.return_value
            mock_manager.list_servers.return_value = ["test-server"]
            mock_manager.config_path = tmp_path / ".pflow" / "mcp-servers.json"
            mock_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
            # Create a valid JSON config file
            mock_manager.config_path.write_text('{"mcpServers": {}}')

            # Set up registry metadata to force sync
            registry.set_metadata("mcp_last_sync_time", 0)
            registry.set_metadata("mcp_servers_hash", "")

            mock_discovery = mock_discovery_class.return_value
            mock_discovery.discover_tools.return_value = ["tool1", "tool2"]

            # Let registrar use the real registry
            mock_registrar_class.return_value = Mock()

            # Run auto-discovery
            _auto_discover_mcp_servers(ctx, verbose=False)

            # Verify registrar was initialized with real registry
            mock_registrar_class.assert_called_with(registry=registry, manager=mock_manager)
