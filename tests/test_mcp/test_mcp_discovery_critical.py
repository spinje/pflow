"""
CRITICAL: Tests for MCP Discovery and Registration.

Without these components working, users cannot discover or use MCP tools at all.
These tests prevent complete feature failure in production.
"""

import asyncio
import builtins
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.mcp import MCPDiscovery, MCPRegistrar, MCPServerManager
from pflow.registry import Registry

httpx = pytest.importorskip("httpx")

_ExceptionGroup = getattr(builtins, "ExceptionGroup", None)


class TestMCPDiscoveryCritical:
    """Test the critical tool discovery process."""

    def test_convert_json_schema_to_pflow_params(self):
        """Test conversion from MCP's JSON Schema to pflow's param format.

        CRITICAL: If this conversion is wrong, ALL MCP tools will have wrong
        parameters, causing validation failures and incorrect execution.
        """
        discovery = MCPDiscovery()

        # Test a realistic GitHub tool schema
        json_schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Issue title"},
                "body": {"type": "string", "description": "Issue body text"},
                "labels": {"type": "array", "items": {"type": "string"}, "description": "Labels to apply"},
                "milestone": {"type": "integer", "description": "Milestone number"},
                "assignees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "GitHub usernames to assign",
                },
            },
            "required": ["title", "body"],
        }

        params = discovery.convert_to_pflow_params(json_schema)

        # Verify critical conversions
        assert len(params) == 5

        # Find params by key (not name - pflow uses "key")
        param_dict = {p["key"]: p for p in params}

        # Check required string param
        assert param_dict["title"]["type"] == "str"
        assert param_dict["title"]["required"] is True
        assert param_dict["title"]["description"] == "Issue title"

        # Check optional string param
        assert param_dict["body"]["type"] == "str"
        assert param_dict["body"]["required"] is True  # It's in required array

        # Check array param
        assert param_dict["labels"]["type"] == "list"
        assert param_dict["labels"]["required"] is False

        # Check integer param
        assert param_dict["milestone"]["type"] == "int"
        assert param_dict["milestone"]["required"] is False

    def test_discovery_handles_malformed_schemas(self):
        """Test that discovery handles malformed/incomplete schemas gracefully.

        CRITICAL: Real MCP servers might return incomplete schemas.
        We must handle this without crashing.
        """
        discovery = MCPDiscovery()

        # Schema missing properties
        bad_schema = {"type": "object"}
        params = discovery.convert_to_pflow_params(bad_schema)
        assert params == []  # Should return empty, not crash

        # Schema with unknown types
        weird_schema = {
            "type": "object",
            "properties": {
                "weird_field": {
                    "type": "quantum",  # Not a real JSON Schema type
                    "description": "Unknown type",
                }
            },
        }
        params = discovery.convert_to_pflow_params(weird_schema)
        # Should handle unknown type gracefully - fallback to str
        assert len(params) == 1
        assert params[0]["type"] == "str"  # Fallback to str (safe default)
        assert params[0]["key"] == "weird_field"

    def test_discovery_times_out_a_hung_server(self):
        """Discovery bounds the whole handshake/list operation, including stdio."""
        discovery = MCPDiscovery()

        async def hang(*_args, **_kwargs):
            await asyncio.Event().wait()

        with (
            patch.object(discovery, "_discover_async", side_effect=hang),
            pytest.raises(RuntimeError, match=r"Request timed out after 0\.01 seconds"),
        ):
            discovery.discover_tools(
                "hung",
                server_config={"command": "hung", "timeout": 0.01},
            )


class TestMCPRegistrarCritical:
    """Test the critical tool registration process."""

    def test_create_registry_entry_structure(self):
        """Test that registry entries have the EXACT structure needed.

        CRITICAL: Wrong registry structure causes compilation failures.
        Missing "inputs": [] or using "name" instead of "key" breaks everything.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Use tmpdir for isolated test config to avoid affecting user's ~/.pflow
            config_path = Path(tmpdir) / "mcp-servers.json"
            manager = MCPServerManager(config_path=config_path)
            registrar = MCPRegistrar(manager=manager)

            tool_def = {
                "name": "create-issue",
                "description": "Create a GitHub issue",
                "server": "github",
                "inputSchema": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
                    "required": ["title"],
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {"issue_url": {"type": "string"}, "issue_number": {"type": "integer"}},
                },
            }

            entry = registrar._create_registry_entry("github", tool_def)

            # CRITICAL structure validations
            assert entry["class_name"] == "MCPNode"
            assert entry["module"] == "pflow.nodes.mcp.node"
            assert entry["file_path"] == "virtual://mcp"
            # type="mcp" so the entry survives core-node refresh (issue #462)
            assert entry["type"] == "mcp"

            # Interface MUST have these exact fields
            interface = entry["interface"]
            assert "inputs" in interface
            assert interface["inputs"] == []  # MUST be empty list for MCP
            assert "params" in interface
            assert len(interface["params"]) > 0
            assert "outputs" in interface
            assert len(interface["outputs"]) > 0

            # MCP runtime stores every successful response under ``result``.
            # Probe discovers the concrete fields from the actual response.
            assert interface["outputs"] == [
                {
                    "key": "result",
                    "type": "any",
                    "description": "Tool execution result",
                }
            ]

            # Check MCP metadata preserved
            assert interface["mcp_metadata"]["server"] == "github"
            assert interface["mcp_metadata"]["tool"] == "create-issue"
            assert interface["mcp_metadata"]["output_schema"] == tool_def["outputSchema"]

    def test_sync_server_updates_registry(self):
        """Test that syncing a server updates the registry correctly.

        CRITICAL: This is the core feature - discovering and registering tools.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp-servers.json"
            registry_path = Path(tmpdir) / "registry.json"

            manager = MCPServerManager(config_path=config_path)
            registry = Registry(registry_path=registry_path)
            discovery = MCPDiscovery(manager=manager)
            registrar = MCPRegistrar(registry=registry, manager=manager, discovery=discovery)

            # Configure a test server
            manager.add_server(name="test", transport="stdio", command="test-cmd", args=[])

            # Mock discovery to return tools
            def mock_discover(server_name, verbose=False, *, server_config=None):
                return [
                    {
                        "name": "tool1",
                        "description": "Test tool 1",
                        "inputSchema": {"type": "object", "properties": {"param1": {"type": "string"}}},
                    },
                    {"name": "tool2", "description": "Test tool 2", "inputSchema": {}},
                ]

            with patch.object(discovery, "discover_tools", side_effect=mock_discover):
                result = registrar.sync_servers(["test"], reconcile_all=False).servers[0]

            # Verify sync results
            assert result.server == "test"
            assert result.tools_discovered == 2
            assert result.tools_registered == 2

            # Verify registry was updated
            nodes = registry.load()
            assert "mcp-test-tool1" in nodes
            assert "mcp-test-tool2" in nodes

            # Verify structure
            assert nodes["mcp-test-tool1"]["class_name"] == "MCPNode"
            assert nodes["mcp-test-tool1"]["file_path"] == "virtual://mcp"

    def test_remove_server_tools_cleans_registry(self):
        """Test that removing a server removes its tools from registry.

        CRITICAL: Orphaned registry entries cause confusion and errors.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path=registry_path)
            registrar = MCPRegistrar(registry=registry)

            # Add some tools to registry
            nodes = {
                "mcp-github-create-issue": registrar._create_registry_entry("github", {"name": "create-issue"}),
                "mcp-github-list-issues": registrar._create_registry_entry("github", {"name": "list-issues"}),
                "mcp-slack-send-message": registrar._create_registry_entry("slack", {"name": "send-message"}),
                "read-file": {"class_name": "ReadFileNode"},  # Non-MCP node
            }
            registry.save(nodes)

            # Remove GitHub tools
            removed_count = registrar.remove_server_tools("github")

            assert removed_count == 2

            # Verify only GitHub tools were removed
            remaining = registry.load()
            assert "mcp-github-create-issue" not in remaining
            assert "mcp-github-list-issues" not in remaining
            assert "mcp-slack-send-message" in remaining  # Different server
            assert "read-file" in remaining  # Non-MCP node

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="ExceptionGroup requires Python 3.11+")
    def test_sync_server_returns_diagnostic_with_suggestions_on_failure(self):
        """When discovery fails, sync_servers should return a Diagnostic with suggestions.

        CRITICAL: Without this, the CLI falls back to raw ExceptionGroup text
        with no actionable guidance — the exact bug this refactor fixes.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp-servers.json"
            registry_path = Path(tmpdir) / "registry.json"

            manager = MCPServerManager(config_path=config_path)
            registry = Registry(registry_path=registry_path)
            discovery = MCPDiscovery(manager=manager)
            registrar = MCPRegistrar(registry=registry, manager=manager, discovery=discovery)

            manager.add_server(name="test", transport="stdio", command="test-cmd", args=[])

            # Simulate a 401 wrapped in ExceptionGroup (the real MCP SDK pattern)
            response_mock = type("Response", (), {"status_code": 401, "text": ""})()
            inner_exc = httpx.HTTPStatusError("Client error '401 Unauthorized'", request=None, response=response_mock)
            exc_group = _ExceptionGroup("unhandled errors in a TaskGroup", [inner_exc])

            with patch.object(discovery, "discover_tools", side_effect=exc_group):
                result = registrar.sync_servers(["test"], reconcile_all=False).servers[0]

            # Must have structured error, not ExceptionGroup garbage
            assert result.error is not None
            assert "unhandled errors" not in result.error
            assert "Authentication failed" in result.error

            # Must have Diagnostic with suggestions for CLI rendering
            diagnostic = result.diagnostic
            assert isinstance(diagnostic, Diagnostic)
            assert diagnostic.severity == Severity.ERROR
            assert diagnostic.suggestions is not None
            assert len(diagnostic.suggestions) > 0
            assert diagnostic.context is not None
            assert "technical_details" in diagnostic.context
