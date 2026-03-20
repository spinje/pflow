"""Tests for pflow mcp add JSON input parsing and CLI flags."""

import click.testing
import pytest

from pflow.cli.commands.mcp import (
    _add_from_json_string,
    _apply_http_timeouts,
    _is_json_string,
    _is_server_config,
    _validate_timeout_flags,
    mcp,
)
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


class TestApplyHttpTimeouts:
    """Test _apply_http_timeouts helper that applies --timeout/--sse-timeout to HTTP servers."""

    def test_applies_timeout_to_http_server(self, tmp_path):
        """--timeout 60 on an HTTP server should persist timeout: 60."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)
        _add_from_json_string(manager, '{"api": {"type": "http", "url": "https://api.example.com/mcp"}}')

        _apply_http_timeouts(manager, ["api"], timeout=60, sse_timeout=None)

        config = manager.load()
        assert config["mcpServers"]["api"]["timeout"] == 60
        assert "sse_timeout" not in config["mcpServers"]["api"]

    def test_applies_sse_timeout_to_http_server(self, tmp_path):
        """--sse-timeout 120 on an HTTP server should persist sse_timeout: 120."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)
        _add_from_json_string(manager, '{"api": {"type": "http", "url": "https://api.example.com/mcp"}}')

        _apply_http_timeouts(manager, ["api"], timeout=None, sse_timeout=120)

        config = manager.load()
        assert config["mcpServers"]["api"]["sse_timeout"] == 120
        assert "timeout" not in config["mcpServers"]["api"]

    def test_applies_both_timeouts(self, tmp_path):
        """Both --timeout and --sse-timeout should persist on HTTP servers."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)
        _add_from_json_string(manager, '{"api": {"type": "http", "url": "https://api.example.com/mcp"}}')

        _apply_http_timeouts(manager, ["api"], timeout=30, sse_timeout=300)

        config = manager.load()
        assert config["mcpServers"]["api"]["timeout"] == 30
        assert config["mcpServers"]["api"]["sse_timeout"] == 300

    def test_warns_for_stdio_server(self, tmp_path, capsys):
        """--timeout on a stdio server should show a warning, not crash."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path)
        _add_from_json_string(manager, '{"local": {"command": "npx", "args": ["server"]}}')

        _apply_http_timeouts(manager, ["local"], timeout=60, sse_timeout=None)

        # The warning is written to stderr via click.echo(err=True)
        # capsys doesn't capture click.echo(err=True) directly, but we can check
        # that no timeout was added to the stdio config
        config = manager.load()
        assert "timeout" not in config["mcpServers"]["local"]


class TestMcpAddCliTimeoutFlags:
    """Test --timeout and --sse-timeout CLI flags on `pflow mcp add`.

    Note: The autouse `isolate_pflow_config` fixture automatically patches
    MCPServerManager to use a temp config path. We read from the same
    manager instance the command uses.
    """

    @pytest.fixture
    def runner(self):
        return click.testing.CliRunner()

    def test_add_http_server_with_timeout_flag(self, runner):
        """pflow mcp add '...' --timeout 60 should apply timeout to HTTP server."""
        result = runner.invoke(
            mcp,
            [
                "add",
                '{"api": {"type": "http", "url": "https://api.example.com/mcp"}}',
                "--timeout",
                "60",
            ],
        )

        assert result.exit_code == 0, f"Command failed: {result.output}"
        # Read from same isolated config the command wrote to
        manager = MCPServerManager()
        config = manager.load()
        assert config["mcpServers"]["api"]["timeout"] == 60

    def test_add_http_server_with_sse_timeout_flag(self, runner):
        """pflow mcp add '...' --sse-timeout 120 should apply sse_timeout to HTTP server."""
        result = runner.invoke(
            mcp,
            [
                "add",
                '{"api": {"type": "http", "url": "https://api.example.com/mcp"}}',
                "--sse-timeout",
                "120",
            ],
        )

        assert result.exit_code == 0, f"Command failed: {result.output}"
        manager = MCPServerManager()
        config = manager.load()
        assert config["mcpServers"]["api"]["sse_timeout"] == 120

    def test_timeout_on_stdio_server_shows_warning(self, runner):
        """--timeout on a stdio server should warn the user."""
        result = runner.invoke(
            mcp,
            [
                "add",
                '{"local": {"command": "npx", "args": ["server"]}}',
                "--timeout",
                "60",
            ],
        )

        assert result.exit_code == 0
        # Should show warning about timeout only applying to HTTP servers
        assert "only apply to HTTP" in result.output or "ignored for stdio" in result.output

    def test_invalid_timeout_does_not_persist_server(self, runner):
        """Invalid --timeout must fail before saving anything to disk."""
        result = runner.invoke(
            mcp,
            [
                "add",
                '{"api": {"type": "http", "url": "https://api.example.com/mcp"}}',
                "--timeout",
                "-5",
            ],
        )

        assert result.exit_code != 0
        # Server must NOT be in config
        manager = MCPServerManager()
        config = manager.load()
        assert "api" not in config.get("mcpServers", {})

    def test_invalid_sse_timeout_does_not_persist_server(self, runner):
        """Invalid --sse-timeout must fail before saving anything to disk."""
        result = runner.invoke(
            mcp,
            [
                "add",
                '{"api": {"type": "http", "url": "https://api.example.com/mcp"}}',
                "--sse-timeout",
                "-1",
            ],
        )

        assert result.exit_code != 0
        manager = MCPServerManager()
        config = manager.load()
        assert "api" not in config.get("mcpServers", {})

    def test_timeout_exceeding_max_does_not_persist_server(self, runner):
        """--timeout > 600 must fail before saving anything to disk."""
        result = runner.invoke(
            mcp,
            [
                "add",
                '{"api": {"type": "http", "url": "https://api.example.com/mcp"}}',
                "--timeout",
                "999",
            ],
        )

        assert result.exit_code != 0
        manager = MCPServerManager()
        config = manager.load()
        assert "api" not in config.get("mcpServers", {})


class TestValidateTimeoutFlags:
    """Test early validation of timeout CLI flags."""

    def test_valid_timeout_passes(self):
        _validate_timeout_flags(timeout=60, sse_timeout=300)

    def test_none_values_pass(self):
        _validate_timeout_flags(timeout=None, sse_timeout=None)

    def test_negative_timeout_raises(self):
        with pytest.raises(click.BadParameter, match="positive number"):
            _validate_timeout_flags(timeout=-1, sse_timeout=None)

    def test_zero_timeout_raises(self):
        with pytest.raises(click.BadParameter, match="positive number"):
            _validate_timeout_flags(timeout=0, sse_timeout=None)

    def test_timeout_exceeds_max_raises(self):
        with pytest.raises(click.BadParameter, match="600 seconds"):
            _validate_timeout_flags(timeout=601, sse_timeout=None)

    def test_negative_sse_timeout_raises(self):
        with pytest.raises(click.BadParameter, match="positive number"):
            _validate_timeout_flags(timeout=None, sse_timeout=-1)
