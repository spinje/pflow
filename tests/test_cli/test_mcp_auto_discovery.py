"""Tests for automatic MCP server discovery at startup.

This module tests the _auto_discover_mcp_servers() function that runs
at pflow startup to automatically sync MCP servers. The tests focus on:
1. Boundary testing - mocking at MCP module level, not internals
2. Comprehensive scenarios - all startup conditions
3. Error resilience - partial failures don't break everything
4. Output control - interactive vs non-interactive modes
"""

from unittest.mock import ANY, Mock, call, patch

from pflow.cli.mcp_sync import _auto_discover_mcp_servers
from pflow.mcp.registrar import ServerSyncResult, SyncBatchResult
from pflow.mcp.sync_state import MCP_SERVER_FINGERPRINTS_KEY, fingerprint_server_configs


class TestAutoDiscovery:
    """Test automatic MCP server discovery at pflow startup."""

    def test_explicit_empty_config_reconciles_registry(self, tmp_path, monkeypatch):
        """An explicit empty config reaches reconciliation for stale cleanup."""
        monkeypatch.setenv("HOME", str(tmp_path))

        # Create mock context
        ctx = Mock()
        ctx.obj = {}

        # Mock output controller
        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.mcp_sync._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry"),
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar") as mock_registrar_class,
        ):
            # Existing empty config is explicit reconciliation state.
            mock_manager = mock_manager_class.return_value
            mock_manager.get_all_servers_if_configured.return_value = {}
            mock_registrar_class.return_value.sync_servers.return_value = SyncBatchResult([])

            # Run auto-discovery
            _auto_discover_mcp_servers(ctx, verbose=True)

            mock_manager.get_all_servers_if_configured.assert_called_once()
            mock_discovery_class.assert_called_once_with(mock_manager)
            mock_registrar_class.return_value.sync_servers.assert_called_once_with(
                [], reconcile_all=True, verbose=True, on_server_start=ANY
            )

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
            patch("pflow.cli.mcp_sync._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar") as mock_registrar_class,
            patch("pflow.cli.mcp_sync.click.echo") as mock_echo,
        ):
            # Configure manager to return servers
            mock_manager = mock_manager_class.return_value
            mock_manager.get_all_servers_if_configured.return_value = {
                "github": {"command": "github"},
                "slack": {"command": "slack"},
            }
            mock_manager.config_path = tmp_path / ".pflow" / "mcp-servers.json"
            mock_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
            mock_manager.config_path.touch()  # Create the config file

            # Configure registry
            mock_registry = mock_registry_class.return_value
            mock_registry.list_nodes.return_value = []
            mock_registry.get_metadata.side_effect = lambda _key, default=None: default
            mock_registry.load.return_value = {}  # Empty registry for cleaning old entries

            # Configure the shared batch coordinator result.
            mock_registrar = mock_registrar_class.return_value
            mock_registrar.sync_servers.return_value = SyncBatchResult([
                ServerSyncResult("github", tools_discovered=2, tools_registered=2),
                ServerSyncResult("slack", tools_discovered=2, tools_registered=2),
            ])

            # Run auto-discovery with verbose=False (summary only)
            _auto_discover_mcp_servers(ctx, verbose=False)

            # Verify MCPDiscovery was instantiated with manager
            mock_discovery_class.assert_called_once_with(mock_manager)

            mock_registrar.sync_servers.assert_called_once_with(
                ["github", "slack"], reconcile_all=True, verbose=False, on_server_start=ANY
            )

            # Verify summary message shown
            mock_echo.assert_called_with("✓ Synced 4 MCP tool(s) from 2 server(s)", err=True)

    def test_partial_failure_result_renders_success_and_warning(self, tmp_path, monkeypatch):
        """The auto-sync boundary renders a completed mixed batch result."""
        monkeypatch.setenv("HOME", str(tmp_path))

        ctx = Mock()
        ctx.obj = {}

        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.mcp_sync._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery"),
            patch("pflow.mcp.MCPRegistrar") as mock_registrar_class,
            patch("pflow.cli.mcp_sync.logger") as mock_logger,
            patch("pflow.cli.mcp_sync.click.echo") as mock_echo,
        ):
            # Configure manager
            mock_manager = mock_manager_class.return_value
            mock_manager.get_all_servers_if_configured.return_value = {
                "broken": {"command": "broken"},
                "working": {"command": "working"},
            }
            mock_manager.config_path = tmp_path / ".pflow" / "mcp-servers.json"
            mock_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
            mock_manager.config_path.touch()  # Create the config file

            # Configure registry
            mock_registry = mock_registry_class.return_value
            mock_registry.list_nodes.return_value = []
            mock_registry.get_metadata.side_effect = lambda _key, default=None: default
            mock_registry.load.return_value = {}  # Empty registry for cleaning old entries

            mock_registrar = mock_registrar_class.return_value
            mock_registrar.sync_servers.return_value = SyncBatchResult([
                ServerSyncResult("broken", error="Connection failed"),
                ServerSyncResult("working", tools_discovered=2, tools_registered=2),
            ])

            # Run auto-discovery
            _auto_discover_mcp_servers(ctx, verbose=False)

            mock_registrar.sync_servers.assert_called_once_with(
                ["broken", "working"], reconcile_all=True, verbose=False, on_server_start=ANY
            )
            mock_logger.debug.assert_not_called()
            mock_echo.assert_any_call("✓ Synced 2 MCP tool(s) from 1 server(s)", err=True)
            mock_echo.assert_any_call("⚠ Failed to connect to MCP server(s): broken", err=True)

    def test_verbose_mode_shows_progress(self, tmp_path, monkeypatch):
        """Test that verbose mode shows detailed progress messages."""
        monkeypatch.setenv("HOME", str(tmp_path))

        ctx = Mock()
        ctx.obj = {}

        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.mcp_sync._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery"),
            patch("pflow.mcp.MCPRegistrar"),
            patch("pflow.cli.mcp_sync.click.echo") as mock_echo,
        ):
            mock_manager = mock_manager_class.return_value
            mock_manager.get_all_servers_if_configured.return_value = {"test-server": {"command": "test"}}
            mock_manager.config_path = tmp_path / ".pflow" / "mcp-servers.json"
            mock_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
            mock_manager.config_path.touch()  # Create the config file

            mock_registry = mock_registry_class.return_value
            mock_registry.list_nodes.return_value = []
            mock_registry.get_metadata.side_effect = lambda _key, default=None: default
            mock_registry.load.return_value = {}  # Empty registry for cleaning old entries

            registrar = Mock()

            def sync_servers(_servers, **kwargs):
                kwargs["on_server_start"]("test-server")
                return SyncBatchResult([ServerSyncResult("test-server", tools_discovered=2, tools_registered=2)])

            registrar.sync_servers.side_effect = sync_servers

            # Run with verbose=True
            with patch("pflow.mcp.MCPRegistrar", return_value=registrar):
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
            patch("pflow.cli.mcp_sync._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar"),
            patch("pflow.cli.mcp_sync.click.echo") as mock_echo,
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
            patch("pflow.cli.mcp_sync._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager", side_effect=ImportError("MCP not installed")),
            patch("pflow.cli.mcp_sync.logger") as mock_logger,
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
            patch("pflow.cli.mcp_sync._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.cli.mcp_sync.logger") as mock_logger,
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
            patch("pflow.cli.mcp_sync._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery"),
            patch("pflow.mcp.MCPRegistrar") as mock_registrar_class,
            patch("pflow.cli.mcp_sync.click.echo") as mock_echo,
        ):
            mock_manager = mock_manager_class.return_value
            mock_manager.get_all_servers_if_configured.return_value = {"empty-server": {"command": "empty"}}

            mock_registry = mock_registry_class.return_value
            mock_registry.list_nodes.return_value = []

            mock_registrar = mock_registrar_class.return_value
            mock_registrar.sync_servers.return_value = SyncBatchResult([ServerSyncResult("empty-server")])

            # Run auto-discovery
            _auto_discover_mcp_servers(ctx, verbose=False)

            mock_registrar.sync_servers.assert_called_once_with(
                ["empty-server"], reconcile_all=True, verbose=False, on_server_start=ANY
            )
            mock_echo.assert_any_call("✓ Synced 0 MCP tool(s) from 1 server(s)", err=True)

    def test_mixed_success_and_empty_servers(self, tmp_path, monkeypatch):
        """Test mix of successful servers and servers with no tools."""
        monkeypatch.setenv("HOME", str(tmp_path))

        ctx = Mock()
        ctx.obj = {}

        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.mcp_sync._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery"),
            patch("pflow.mcp.MCPRegistrar") as mock_registrar_class,
            patch("pflow.cli.mcp_sync.click.echo") as mock_echo,
        ):
            mock_manager = mock_manager_class.return_value
            mock_manager.get_all_servers_if_configured.return_value = {
                "empty": {"command": "empty"},
                "github": {"command": "github"},
                "another-empty": {"command": "another-empty"},
            }
            mock_manager.config_path = tmp_path / ".pflow" / "mcp-servers.json"
            mock_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
            mock_manager.config_path.touch()  # Create the config file

            mock_registry = mock_registry_class.return_value
            mock_registry.list_nodes.return_value = []
            mock_registry.get_metadata.side_effect = lambda _key, default=None: default
            mock_registry.load.return_value = {}  # Empty registry for cleaning old entries

            mock_registrar = mock_registrar_class.return_value
            mock_registrar.sync_servers.return_value = SyncBatchResult([
                ServerSyncResult("empty"),
                ServerSyncResult("github", tools_discovered=2, tools_registered=2),
                ServerSyncResult("another-empty"),
            ])

            # Run auto-discovery
            _auto_discover_mcp_servers(ctx, verbose=False)

            mock_registrar.sync_servers.assert_called_once()

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
            patch("pflow.cli.mcp_sync._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery"),
            patch("pflow.mcp.MCPRegistrar"),
            patch("pflow.cli.mcp_sync.click.echo") as mock_echo,
        ):
            mock_manager = mock_manager_class.return_value
            mock_manager.get_all_servers_if_configured.return_value = {
                "failing-server": {"command": "failing"},
                "working-server": {"command": "working"},
            }
            mock_manager.config_path = tmp_path / ".pflow" / "mcp-servers.json"
            mock_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
            mock_manager.config_path.touch()  # Create the config file

            mock_registry = mock_registry_class.return_value
            mock_registry.list_nodes.return_value = []
            mock_registry.get_metadata.side_effect = lambda _key, default=None: default
            mock_registry.load.return_value = {}  # Empty registry for cleaning old entries

            registrar = Mock()

            def sync_servers(servers, **kwargs):
                for server in servers:
                    kwargs["on_server_start"](server)
                return SyncBatchResult([
                    ServerSyncResult("failing-server", error="Connection timeout"),
                    ServerSyncResult("working-server", tools_discovered=1, tools_registered=1),
                ])

            registrar.sync_servers.side_effect = sync_servers

            # Run with verbose=True
            with patch("pflow.mcp.MCPRegistrar", return_value=registrar):
                _auto_discover_mcp_servers(ctx, verbose=True)

            # Verify progress messages shown
            expected_calls = [
                call("Discovering tools from MCP server 'failing-server'...", err=True),
                call("Discovering tools from MCP server 'working-server'...", err=True),
                call("  ✓ Discovered 1 tool(s) from working-server", err=True),
                call("⚠ Failed to connect to MCP server(s): failing-server", err=True),
            ]
            mock_echo.assert_has_calls(expected_calls)

    def test_unchanged_fingerprints_skip_rediscovery(self, tmp_path, monkeypatch):
        """Unchanged per-server fingerprints avoid server startup and registry writes."""
        monkeypatch.setenv("HOME", str(tmp_path))

        ctx = Mock()
        ctx.obj = {}

        output_controller = Mock()
        output_controller.is_interactive.return_value = True

        with (
            patch("pflow.cli.mcp_sync._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry") as mock_registry_class,
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar") as mock_registrar_class,
        ):
            mock_manager = mock_manager_class.return_value
            configs = {"github": {"command": "github"}}
            mock_manager.get_all_servers_if_configured.return_value = configs
            mock_manager.config_path = tmp_path / ".pflow" / "mcp-servers.json"
            mock_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
            mock_manager.config_path.touch()  # Create the config file

            mock_registry = mock_registry_class.return_value
            mock_registry.get_metadata.side_effect = lambda key, default=None: (
                fingerprint_server_configs(configs) if key == MCP_SERVER_FINGERPRINTS_KEY else default
            )
            mock_registry.load.return_value = {}
            mock_registrar_class.full_reconciliation_removals.return_value = []

            # Run auto-discovery
            _auto_discover_mcp_servers(ctx, verbose=False)

            mock_discovery_class.assert_not_called()
            mock_registrar_class.assert_not_called()


class TestAutoDiscoveryIntegration:
    """Integration-level tests for auto-discovery.

    These tests use less mocking to verify the interactions between components.
    """

    def test_batch_coordinator_receives_real_registry(self, tmp_path, monkeypatch):
        """Auto-sync passes its inspected registry to the batch coordinator."""
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
            patch("pflow.cli.mcp_sync._get_output_controller", return_value=output_controller),
            patch("pflow.mcp.MCPServerManager") as mock_manager_class,
            patch("pflow.registry.Registry", return_value=registry),  # Use real registry
            patch("pflow.mcp.MCPDiscovery") as mock_discovery_class,
            patch("pflow.mcp.MCPRegistrar") as mock_registrar_class,
        ):
            mock_manager = mock_manager_class.return_value
            mock_manager.get_all_servers_if_configured.return_value = {"test-server": {"command": "test"}}
            mock_manager.config_path = tmp_path / ".pflow" / "mcp-servers.json"
            mock_manager.config_path.parent.mkdir(parents=True, exist_ok=True)
            # Create a valid JSON config file
            mock_manager.config_path.write_text('{"mcpServers": {}}', encoding="utf-8")

            mock_registrar_class.return_value.sync_servers.return_value = SyncBatchResult([
                ServerSyncResult("test-server", tools_discovered=2, tools_registered=2)
            ])

            # Run auto-discovery
            _auto_discover_mcp_servers(ctx, verbose=False)

            # Verify registrar was initialized with real registry
            mock_registrar_class.assert_called_with(
                registry=registry,
                manager=mock_manager,
                discovery=mock_discovery_class.return_value,
            )
