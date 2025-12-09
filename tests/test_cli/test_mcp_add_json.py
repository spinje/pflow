"""Tests for pflow mcp add JSON input parsing."""

import pytest

from pflow.cli.mcp import _add_from_json_string, _is_json_string, _is_server_config
from pflow.mcp import MCPServerManager


class TestJsonDetection:
    """Test JSON string detection helpers."""

    def test_is_json_string_with_object(self):
        """Test detection of JSON object strings."""
        assert _is_json_string('{"key": "value"}') is True
        assert _is_json_string('  {"key": "value"}  ') is True

    def test_is_json_string_with_array(self):
        """Test detection of JSON array strings."""
        assert _is_json_string("[1, 2, 3]") is True

    def test_is_json_string_with_file_path(self):
        """Test that file paths are not detected as JSON."""
        assert _is_json_string("./config.json") is False
        assert _is_json_string("/path/to/file.json") is False

    def test_is_server_config(self):
        """Test server config detection."""
        assert _is_server_config({"command": "npx", "args": []}) is True
        assert _is_server_config({"type": "http", "url": "https://example.com"}) is True
        assert _is_server_config({"nested": {"command": "npx"}}) is False


class TestAddFromJsonString:
    """Test _add_from_json_string with various formats."""

    def test_full_mcp_format(self, tmp_path):
        """Test full mcpServers wrapper format."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)

        json_str = '{"mcpServers": {"test": {"command": "echo", "args": ["hello"]}}}'
        added = _add_from_json_string(manager, json_str)

        assert added == ["test"]

    def test_simple_format_without_wrapper(self, tmp_path):
        """Test simple format without mcpServers wrapper."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)

        json_str = '{"github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}}'
        added = _add_from_json_string(manager, json_str)

        assert added == ["github"]

    def test_http_server_simple_format(self, tmp_path):
        """Test HTTP server with simple format."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)

        json_str = '{"slack": {"type": "http", "url": "https://mcp.example.com/slack"}}'
        added = _add_from_json_string(manager, json_str)

        assert added == ["slack"]
        saved = manager.load()
        assert saved["mcpServers"]["slack"]["type"] == "http"

    def test_invalid_json_raises(self, tmp_path):
        """Test that invalid JSON raises ValueError."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)

        with pytest.raises(ValueError, match="Invalid JSON"):
            _add_from_json_string(manager, "not valid json")

    def test_invalid_format_raises(self, tmp_path):
        """Test that invalid format raises ValueError."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)

        # Dict without command/url fields - not a valid server config
        with pytest.raises(ValueError, match="Invalid JSON format"):
            _add_from_json_string(manager, '{"name": {"invalid": "config"}}')
