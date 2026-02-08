"""Tests for MCP server config env var expansion at entry points.

Verifies that expand_env_vars_nested is called correctly in both
MCPDiscovery._discover_async and MCPNode.prep, covering two bugs that were fixed:

1. URLs in MCP server config were never expanded -- ${VAR} in URLs was passed
   literally to the HTTP client.
2. Settings.json env vars were never checked -- only os.environ was used,
   values set via `pflow settings set-env` were ignored.

These tests do NOT re-test the expand_env_vars_nested function itself (that is
covered in test_auth_utils.py and test_env_var_defaults.py). Instead, they verify
that the function is called at the right entry points with the right flags.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from pflow.mcp.discovery import MCPDiscovery
from pflow.nodes.mcp.node import MCPNode


class TestDiscoveryConfigExpansion:
    """Test that MCPDiscovery._discover_async expands the entire server config."""

    def test_discovery_expands_url_in_http_config(self):
        """Test that ${VAR} references in URLs are expanded before transport routing.

        This was the primary bug: URLs like https://${PROJECT_REF}.supabase.co/mcp
        were passed literally to the HTTP client, causing connection failures.
        """
        discovery = MCPDiscovery()

        config_with_var = {
            "type": "http",
            "url": "https://${PROJECT_REF}.supabase.co/functions/v1/mcp",
            "auth": {"type": "bearer", "token": "${SUPABASE_KEY}"},
            "headers": {"X-Custom": "${CUSTOM_HEADER}"},
        }

        with (
            patch.dict(
                "os.environ",
                {
                    "PROJECT_REF": "my-project",
                    "SUPABASE_KEY": "sb-key-123",
                    "CUSTOM_HEADER": "custom-val",
                },
                clear=True,
            ),
            patch.object(discovery, "_discover_async_http", new_callable=AsyncMock) as mock_http,
        ):
            mock_http.return_value = []

            asyncio.run(discovery._discover_async("supabase", config_with_var))

            # Verify the transport method received the EXPANDED config
            called_config = mock_http.call_args[0][1]
            assert called_config["url"] == "https://my-project.supabase.co/functions/v1/mcp"
            assert called_config["auth"]["token"] == "sb-key-123"  # noqa: S105
            assert called_config["headers"]["X-Custom"] == "custom-val"

    def test_discovery_expands_env_field_in_stdio_config(self):
        """Test that env dict values in stdio config are expanded.

        Stdio servers pass env vars to subprocess. These must be expanded
        so the child process gets real values, not ${VAR} literals.
        """
        discovery = MCPDiscovery()

        config_with_var = {
            "command": "npx",
            "args": ["-y", "@mcp/server-github"],
            "env": {"GITHUB_TOKEN": "${GH_TOKEN}"},
        }

        with (
            patch.dict("os.environ", {"GH_TOKEN": "ghp_realtoken123"}, clear=True),
            patch.object(discovery, "_discover_async_stdio", new_callable=AsyncMock) as mock_stdio,
        ):
            mock_stdio.return_value = []

            asyncio.run(discovery._discover_async("github", config_with_var))

            called_config = mock_stdio.call_args[0][1]
            assert called_config["env"]["GITHUB_TOKEN"] == "ghp_realtoken123"  # noqa: S105

    def test_discovery_resolves_settings_json_vars(self):
        """Test that vars from settings.json resolve during discovery.

        Bug: only os.environ was checked. If a user ran
        `pflow settings set-env SUPABASE_PROJECT_REF=my-project`,
        the value was ignored and the URL was passed with ${...} literal.
        """
        discovery = MCPDiscovery()

        config_with_var = {
            "type": "http",
            "url": "https://${SUPABASE_PROJECT_REF}.supabase.co/mcp",
        }

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("pflow.core.settings.SettingsManager") as mock_settings_cls,
            patch.object(discovery, "_discover_async_http", new_callable=AsyncMock) as mock_http,
        ):
            mock_settings = mock_settings_cls.return_value
            mock_settings.list_env.return_value = {
                "SUPABASE_PROJECT_REF": "my-project-ref",
            }
            mock_http.return_value = []

            asyncio.run(discovery._discover_async("supabase", config_with_var))

            called_config = mock_http.call_args[0][1]
            assert called_config["url"] == "https://my-project-ref.supabase.co/mcp"

    def test_discovery_raises_on_missing_var(self):
        """Test that missing vars produce a clear ValueError during discovery.

        With raise_on_missing=True, the error message should tell users
        how to set the variable (via pflow settings set-env or export).
        """
        discovery = MCPDiscovery()

        config_with_missing = {
            "type": "http",
            "url": "https://${MISSING_PROJECT}.supabase.co/mcp",
        }

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("pflow.core.settings.SettingsManager") as mock_settings_cls,
        ):
            mock_settings = mock_settings_cls.return_value
            mock_settings.list_env.return_value = {}

            # _discover_async raises ValueError, which discover_tools wraps in RuntimeError
            with pytest.raises(ValueError, match="MISSING_PROJECT"):
                asyncio.run(discovery._discover_async("supabase", config_with_missing))


class TestNodePrepConfigExpansion:
    """Test that MCPNode.prep expands the entire server config."""

    def _make_node_with_params(self, server: str = "test-server", tool: str = "test-tool") -> MCPNode:
        """Create an MCPNode with server/tool params set."""
        node = MCPNode()
        node.set_params({"__mcp_server__": server, "__mcp_tool__": tool})
        return node

    def test_node_prep_expands_url_in_config(self):
        """Test that MCPNode.prep expands ${VAR} in the loaded server config.

        This verifies the fix: after _load_server_config returns the raw config,
        expand_env_vars_nested is called to resolve all variables.
        """
        node = self._make_node_with_params()

        raw_config = {
            "type": "http",
            "url": "https://${PROJECT_ID}.example.com/mcp",
            "auth": {"type": "bearer", "token": "${API_TOKEN}"},
        }

        with (
            patch.dict(
                "os.environ",
                {
                    "PROJECT_ID": "prod-123",
                    "API_TOKEN": "tok_secret",
                },
                clear=True,
            ),
            patch.object(node, "_load_server_config", return_value=raw_config),
        ):
            prep_res = node.prep(shared={})

            assert prep_res["config"]["url"] == "https://prod-123.example.com/mcp"
            assert prep_res["config"]["auth"]["token"] == "tok_secret"  # noqa: S105

    def test_node_prep_resolves_settings_json_vars(self):
        """Test that settings.json env vars are available during node execution.

        Bug: MCPNode.prep only checked os.environ. A user who ran
        `pflow settings set-env API_TOKEN=secret` would still get an error.
        """
        node = self._make_node_with_params()

        raw_config = {
            "type": "http",
            "url": "https://api.example.com/mcp",
            "auth": {"type": "bearer", "token": "${API_TOKEN}"},
        }

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("pflow.core.settings.SettingsManager") as mock_settings_cls,
            patch.object(node, "_load_server_config", return_value=raw_config),
        ):
            mock_settings = mock_settings_cls.return_value
            mock_settings.list_env.return_value = {"API_TOKEN": "from-settings"}

            prep_res = node.prep(shared={})

            assert prep_res["config"]["auth"]["token"] == "from-settings"  # noqa: S105

    def test_node_prep_raises_on_missing_var(self):
        """Test that missing vars in node config raise a clear error.

        The error message should include instructions for setting the variable.
        """
        node = self._make_node_with_params()

        raw_config = {
            "type": "http",
            "url": "https://api.example.com/mcp",
            "auth": {"type": "bearer", "token": "${UNDEFINED_TOKEN}"},
        }

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("pflow.core.settings.SettingsManager") as mock_settings_cls,
            patch.object(node, "_load_server_config", return_value=raw_config),
        ):
            mock_settings = mock_settings_cls.return_value
            mock_settings.list_env.return_value = {}

            with pytest.raises(ValueError) as exc_info:
                node.prep(shared={})

            error_msg = str(exc_info.value)
            assert "UNDEFINED_TOKEN" in error_msg
            assert "pflow settings set-env" in error_msg
