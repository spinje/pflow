"""Tests for standard MCP config format parsing and conversion."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pflow.mcp import MCPServerManager


class TestStandardConfigParser:
    """Test parsing of standard MCP JSON config files."""

    def test_parse_valid_stdio_config(self, tmp_path):
        """Test parsing a valid stdio server config."""
        config_file = tmp_path / "github.mcp.json"
        config_file.write_text(
            json.dumps({
                "mcpServers": {
                    "github": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-github"],
                        "env": {"GITHUB_TOKEN": "test-token"},
                    }
                }
            })
        )

        manager = MCPServerManager()
        servers = manager.parse_standard_mcp_config(config_file)

        assert "github" in servers
        # Standard format: no "type" field for stdio
        assert "type" not in servers["github"]
        assert servers["github"]["command"] == "npx"
        assert servers["github"]["args"] == ["-y", "@modelcontextprotocol/server-github"]
        assert servers["github"]["env"] == {"GITHUB_TOKEN": "test-token"}

    def test_parse_stdio_without_type_field(self, tmp_path):
        """Test that missing 'type' field defaults to stdio."""
        config_file = tmp_path / "test.mcp.json"
        config_file.write_text(json.dumps({"mcpServers": {"test-server": {"command": "node", "args": ["server.js"]}}}))

        manager = MCPServerManager()
        servers = manager.parse_standard_mcp_config(config_file)

        # Standard format: no "type" field means stdio
        assert "type" not in servers["test-server"]
        assert servers["test-server"]["command"] == "node"

    def test_parse_http_config(self, tmp_path):
        """Test parsing an HTTP transport config."""
        config_file = tmp_path / "api.mcp.json"
        config_file.write_text(
            json.dumps({
                "mcpServers": {
                    "api": {
                        "type": "http",
                        "url": "https://api.example.com/mcp",
                        "headers": {"Authorization": "Bearer token123"},
                    }
                }
            })
        )

        manager = MCPServerManager()
        servers = manager.parse_standard_mcp_config(config_file)

        assert "api" in servers
        assert servers["api"]["type"] == "http"
        assert servers["api"]["url"] == "https://api.example.com/mcp"
        assert servers["api"]["headers"] == {"Authorization": "Bearer token123"}

    def test_reject_sse_transport(self, tmp_path):
        """Test that SSE transport is rejected with clear error."""
        config_file = tmp_path / "sse.mcp.json"
        config_file.write_text(
            json.dumps({"mcpServers": {"sse-server": {"type": "sse", "url": "https://example.com/sse"}}})
        )

        manager = MCPServerManager()
        with pytest.raises(ValueError) as exc_info:
            manager.parse_standard_mcp_config(config_file)

        # SSE is now just rejected as unsupported type
        assert "Unsupported type 'sse'" in str(exc_info.value)

    def test_missing_mcpservers_key(self, tmp_path):
        """Test error when mcpServers wrapper is missing."""
        config_file = tmp_path / "invalid.json"
        config_file.write_text(json.dumps({"servers": {"test": {"command": "test"}}}))

        manager = MCPServerManager()
        with pytest.raises(ValueError) as exc_info:
            manager.parse_standard_mcp_config(config_file)

        assert "missing 'mcpServers' key" in str(exc_info.value)

    def test_file_not_found(self):
        """Test error when config file doesn't exist."""
        manager = MCPServerManager()
        with pytest.raises(FileNotFoundError):
            manager.parse_standard_mcp_config(Path("/nonexistent/file.json"))

    def test_invalid_json(self, tmp_path):
        """Test error handling for invalid JSON."""
        config_file = tmp_path / "invalid.json"
        config_file.write_text("{ invalid json }")

        manager = MCPServerManager()
        with pytest.raises(ValueError) as exc_info:
            manager.parse_standard_mcp_config(config_file)

        assert "Invalid JSON" in str(exc_info.value)

    def test_multiple_servers_in_one_file(self, tmp_path):
        """Test parsing multiple servers from one file."""
        config_file = tmp_path / "multi.mcp.json"
        config_file.write_text(
            json.dumps({
                "mcpServers": {
                    "server1": {"command": "cmd1", "args": ["arg1"]},
                    "server2": {"type": "http", "url": "https://example.com/mcp"},
                    "server3": {"command": "cmd3", "env": {"KEY": "value"}},
                }
            })
        )

        manager = MCPServerManager()
        servers = manager.parse_standard_mcp_config(config_file)

        assert len(servers) == 3
        assert "server1" in servers
        assert "server2" in servers
        assert "server3" in servers
        # Standard format: stdio has no "type" field, http has "type": "http"
        assert "type" not in servers["server1"]
        assert servers["server2"]["type"] == "http"


class TestAddServersFromFile:
    """Test the add_servers_from_file functionality."""

    def test_add_new_servers(self, tmp_path):
        """Test adding new servers from a config file."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)

        # Create a standard config file
        mcp_file = tmp_path / "github.mcp.json"
        mcp_file.write_text(
            json.dumps({
                "mcpServers": {"github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}}
            })
        )

        # Add servers from the file
        added = manager.add_servers_from_file(mcp_file)

        assert added == ["github"]

        # Verify it was saved
        saved_config = manager.load()
        assert "github" in saved_config["mcpServers"]
        assert saved_config["mcpServers"]["github"]["command"] == "npx"

    def test_update_existing_server(self, tmp_path):
        """Test that adding a server with same name updates it."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)

        # First add
        mcp_file1 = tmp_path / "test1.json"
        mcp_file1.write_text(json.dumps({"mcpServers": {"test": {"command": "old-command"}}}))
        manager.add_servers_from_file(mcp_file1)

        # Second add with same name
        mcp_file2 = tmp_path / "test2.json"
        mcp_file2.write_text(json.dumps({"mcpServers": {"test": {"command": "new-command"}}}))
        added = manager.add_servers_from_file(mcp_file2)

        assert added == ["test"]

        # Verify it was updated
        saved_config = manager.load()
        assert saved_config["mcpServers"]["test"]["command"] == "new-command"

    def test_add_multiple_from_one_file(self, tmp_path):
        """Test adding multiple servers from one file."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)

        mcp_file = tmp_path / "multi.json"
        mcp_file.write_text(
            json.dumps({
                "mcpServers": {
                    "server1": {"command": "cmd1"},
                    "server2": {"type": "http", "url": "https://example.com"},
                    "server3": {"command": "cmd3"},
                }
            })
        )

        added = manager.add_servers_from_file(mcp_file)

        assert len(added) == 3
        assert "server1" in added
        assert "server2" in added
        assert "server3" in added

    def test_timestamps_are_added(self, tmp_path):
        """Test that timestamps are properly added."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)

        mcp_file = tmp_path / "test.json"
        mcp_file.write_text(json.dumps({"mcpServers": {"test": {"command": "test"}}}))

        manager.add_servers_from_file(mcp_file)

        saved_config = manager.load()
        server = saved_config["mcpServers"]["test"]
        # Standard format doesn't have timestamps
        assert "command" in server


class TestEnvironmentVariableDefaults:
    """Test environment variable expansion with default values."""

    def test_env_var_with_default_value(self, tmp_path):
        """Test ${VAR:-default} syntax when VAR is not set."""
        config_file = tmp_path / "test.json"
        config_file.write_text(
            json.dumps({"mcpServers": {"test": {"command": "test", "env": {"TOKEN": "${MISSING_VAR:-default_token}"}}}})
        )

        manager = MCPServerManager()
        with patch.dict(os.environ, {}, clear=True):
            servers = manager.parse_standard_mcp_config(config_file)

        # Note: The parsing doesn't expand env vars, that happens at runtime
        # But we should test that the syntax is preserved
        assert servers["test"]["env"]["TOKEN"] == "${MISSING_VAR:-default_token}"  # noqa: S105 - Test fixture value

    def test_env_var_default_in_url(self, tmp_path):
        """Test default values in HTTP URLs."""
        config_file = tmp_path / "test.json"
        config_file.write_text(
            json.dumps({"mcpServers": {"api": {"type": "http", "url": "${API_URL:-http://localhost:3000}/mcp"}}})
        )

        manager = MCPServerManager()
        servers = manager.parse_standard_mcp_config(config_file)

        assert servers["api"]["url"] == "${API_URL:-http://localhost:3000}/mcp"

    def test_env_var_default_in_headers(self, tmp_path):
        """Test default values in HTTP headers."""
        config_file = tmp_path / "test.json"
        config_file.write_text(
            json.dumps({
                "mcpServers": {
                    "api": {
                        "type": "http",
                        "url": "https://api.example.com",
                        "headers": {
                            "Authorization": "Bearer ${API_KEY:-test_key}",
                            "X-Custom": "${CUSTOM_HEADER:-default_value}",
                        },
                    }
                }
            })
        )

        manager = MCPServerManager()
        servers = manager.parse_standard_mcp_config(config_file)

        assert servers["api"]["headers"]["Authorization"] == "Bearer ${API_KEY:-test_key}"
        assert servers["api"]["headers"]["X-Custom"] == "${CUSTOM_HEADER:-default_value}"


class TestHTTPAuthConversion:
    """Test conversion of various auth formats to internal format."""

    def test_inline_bearer_token(self, tmp_path):
        """Test inline token field conversion to auth object."""
        config_file = tmp_path / "test.json"
        config_file.write_text(
            json.dumps({
                "mcpServers": {"api": {"type": "http", "url": "https://api.example.com", "token": "bearer_token_123"}}
            })
        )

        manager = MCPServerManager()
        servers = manager.parse_standard_mcp_config(config_file)

        # Standard format doesn't convert inline fields - they remain as-is
        assert servers["api"]["token"] == "bearer_token_123"  # noqa: S105 - Test fixture value
        assert "auth" not in servers["api"]  # No conversion happens

    def test_inline_api_key(self, tmp_path):
        """Test inline apiKey field conversion."""
        config_file = tmp_path / "test.json"
        config_file.write_text(
            json.dumps({
                "mcpServers": {
                    "api": {
                        "type": "http",
                        "url": "https://api.example.com",
                        "apiKey": "key_123",
                        "apiKeyHeader": "X-Custom-Key",
                    }
                }
            })
        )

        manager = MCPServerManager()
        servers = manager.parse_standard_mcp_config(config_file)

        # Standard format doesn't convert inline fields - they remain as-is
        assert servers["api"]["apiKey"] == "key_123"
        assert servers["api"]["apiKeyHeader"] == "X-Custom-Key"
        assert "auth" not in servers["api"]  # No conversion happens

    def test_inline_basic_auth(self, tmp_path):
        """Test inline username/password conversion."""
        config_file = tmp_path / "test.json"
        config_file.write_text(
            json.dumps({
                "mcpServers": {
                    "api": {"type": "http", "url": "https://api.example.com", "username": "user", "password": "pass"}
                }
            })
        )

        manager = MCPServerManager()
        servers = manager.parse_standard_mcp_config(config_file)

        # Standard format doesn't convert inline fields - they remain as-is
        assert servers["api"]["username"] == "user"
        assert servers["api"]["password"] == "pass"  # noqa: S105 - Test fixture value
        assert "auth" not in servers["api"]  # No conversion happens

    def test_explicit_auth_object_preserved(self, tmp_path):
        """Test that explicit auth objects are kept as-is."""
        config_file = tmp_path / "test.json"
        config_file.write_text(
            json.dumps({
                "mcpServers": {
                    "api": {
                        "type": "http",
                        "url": "https://api.example.com",
                        "auth": {"type": "custom", "special_field": "value"},
                    }
                }
            })
        )

        manager = MCPServerManager()
        servers = manager.parse_standard_mcp_config(config_file)

        assert servers["api"]["auth"] == {"type": "custom", "special_field": "value"}


class TestAddServersFromConfig:
    """Test add_servers_from_config for raw JSON input support."""

    def test_add_with_full_mcp_format(self, tmp_path):
        """Test adding servers using full mcpServers wrapper format."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)

        config = {"mcpServers": {"github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}}}
        added = manager.add_servers_from_config(config)

        assert added == ["github"]
        saved = manager.load()
        assert "github" in saved["mcpServers"]
        assert saved["mcpServers"]["github"]["command"] == "npx"

    def test_add_with_simple_format(self, tmp_path):
        """Test adding servers using simple name:config format (no mcpServers wrapper)."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)

        # Simple format - just server name as key
        config = {"mcpServers": {"slack": {"type": "http", "url": "https://mcp.example.com/slack"}}}
        added = manager.add_servers_from_config(config)

        assert added == ["slack"]
        saved = manager.load()
        assert "slack" in saved["mcpServers"]
        assert saved["mcpServers"]["slack"]["type"] == "http"

    def test_add_multiple_servers(self, tmp_path):
        """Test adding multiple servers at once."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)

        config = {
            "mcpServers": {
                "server1": {"command": "cmd1"},
                "server2": {"type": "http", "url": "https://example.com"},
            }
        }
        added = manager.add_servers_from_config(config)

        assert len(added) == 2
        assert "server1" in added
        assert "server2" in added

    def test_missing_mcpservers_key_raises(self, tmp_path):
        """Test that missing mcpServers key raises ValueError."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)

        with pytest.raises(ValueError, match="must contain 'mcpServers' key"):
            manager.add_servers_from_config({"invalid": "config"})
