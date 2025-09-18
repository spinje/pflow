"""Unit tests for MCP HTTP transport functionality."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from pflow.mcp.manager import MCPServerManager
from pflow.nodes.mcp.node import MCPNode


class TestHTTPConfiguration:
    """Test HTTP transport configuration validation and management."""

    def test_http_config_validation_valid(self):
        """Test validation of valid HTTP configuration."""
        manager = MCPServerManager()

        # Valid HTTP config
        config = {
            "transport": "http",
            "url": "https://api.example.com/mcp",
            "auth": {"type": "bearer", "token": "${API_TOKEN}"},
            "headers": {"User-Agent": "pflow/1.0"},
            "timeout": 60,
            "sse_timeout": 300,
        }

        # Should not raise
        manager.validate_server_config(config)

    def test_http_config_validation_missing_url(self):
        """Test that HTTP transport requires URL."""
        manager = MCPServerManager()

        config = {"transport": "http"}

        with pytest.raises(ValueError, match="HTTP transport requires 'url'"):
            manager.validate_server_config(config)

    def test_http_config_validation_invalid_url(self):
        """Test URL format validation."""
        manager = MCPServerManager()

        # Invalid URL scheme
        config = {"transport": "http", "url": "ftp://example.com/mcp"}

        with pytest.raises(ValueError, match="URL must start with http"):
            manager.validate_server_config(config)

        # Empty URL
        config = {"transport": "http", "url": ""}

        with pytest.raises(ValueError, match="URL must be a non-empty string"):
            manager.validate_server_config(config)

    def test_http_config_validation_auth_types(self):
        """Test authentication configuration validation."""
        manager = MCPServerManager()

        # Bearer auth - missing token
        config = {
            "transport": "http",
            "url": "https://api.example.com/mcp",
            "auth": {"type": "bearer"},
        }
        with pytest.raises(ValueError, match="Bearer auth requires 'token'"):
            manager.validate_server_config(config)

        # API key auth - missing key
        config = {
            "transport": "http",
            "url": "https://api.example.com/mcp",
            "auth": {"type": "api_key"},
        }
        with pytest.raises(ValueError, match="API key auth requires 'key'"):
            manager.validate_server_config(config)

        # Basic auth - missing credentials
        config = {
            "transport": "http",
            "url": "https://api.example.com/mcp",
            "auth": {"type": "basic"},
        }
        with pytest.raises(ValueError, match="Basic auth requires 'username'"):
            manager.validate_server_config(config)

        # Invalid auth type
        config = {
            "transport": "http",
            "url": "https://api.example.com/mcp",
            "auth": {"type": "oauth"},
        }
        with pytest.raises(ValueError, match="Unsupported auth type"):
            manager.validate_server_config(config)

    def test_http_config_timeout_validation(self):
        """Test timeout parameter validation."""
        manager = MCPServerManager()

        # Negative timeout
        config = {
            "transport": "http",
            "url": "https://api.example.com/mcp",
            "timeout": -1,
        }
        with pytest.raises(ValueError, match="Timeout must be a positive"):
            manager.validate_server_config(config)

        # Timeout too large
        config = {
            "transport": "http",
            "url": "https://api.example.com/mcp",
            "timeout": 700,
        }
        with pytest.raises(ValueError, match="Timeout cannot exceed 600"):
            manager.validate_server_config(config)

    def test_add_http_server(self, tmp_path):
        """Test adding an HTTP server configuration."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path=config_path)

        # Add HTTP server
        manager.add_server(
            name="composio",
            transport="http",
            url="https://api.composio.dev/mcp",
            auth={"type": "bearer", "token": "${COMPOSIO_API_KEY}"},
            headers={"User-Agent": "pflow/1.0"},
            timeout=30,
        )

        # Verify configuration was saved
        config = manager.load()
        assert "composio" in config["servers"]

        server = config["servers"]["composio"]
        assert server["transport"] == "http"
        assert server["url"] == "https://api.composio.dev/mcp"
        assert server["auth"]["type"] == "bearer"
        assert server["auth"]["token"] == "${COMPOSIO_API_KEY}"  # noqa: S105
        assert server["headers"]["User-Agent"] == "pflow/1.0"
        assert server["timeout"] == 30

    def test_mixed_transport_servers(self, tmp_path):
        """Test managing both stdio and HTTP servers in same config."""
        config_path = tmp_path / "mcp-servers.json"
        manager = MCPServerManager(config_path=config_path)

        # Add stdio server
        manager.add_server(
            name="github",
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
        )

        # Add HTTP server
        manager.add_server(
            name="composio",
            transport="http",
            url="https://api.composio.dev/mcp",
            auth={"type": "bearer", "token": "${COMPOSIO_API_KEY}"},
        )

        # Load and verify both
        config = manager.load()
        assert len(config["servers"]) == 2
        assert config["servers"]["github"]["transport"] == "stdio"
        assert config["servers"]["composio"]["transport"] == "http"


class TestHTTPTransportExecution:
    """Test HTTP transport execution in MCPNode."""

    def test_build_auth_headers_bearer(self):
        """Test building bearer token authentication headers."""
        node = MCPNode()

        # Test with environment variable already expanded
        config = {"auth": {"type": "bearer", "token": "test-token-123"}}

        headers = node._build_auth_headers(config)
        assert headers["Authorization"] == "Bearer test-token-123"

    def test_build_auth_headers_api_key(self):
        """Test building API key authentication headers."""
        node = MCPNode()

        config = {"auth": {"type": "api_key", "key": "test-key-456", "header": "X-Custom-Key"}}

        headers = node._build_auth_headers(config)
        assert headers["X-Custom-Key"] == "test-key-456"

    def test_build_auth_headers_basic(self):
        """Test building basic authentication headers."""
        import base64

        node = MCPNode()

        config = {"auth": {"type": "basic", "username": "user", "password": "pass"}}

        headers = node._build_auth_headers(config)
        expected = base64.b64encode(b"user:pass").decode()
        assert headers["Authorization"] == f"Basic {expected}"

    def test_build_auth_headers_with_custom(self):
        """Test building headers with custom headers."""
        node = MCPNode()

        config = {
            "headers": {"User-Agent": "pflow/1.0", "Accept": "application/json"},
            "auth": {"type": "bearer", "token": "test-token"},
        }

        headers = node._build_auth_headers(config)
        assert headers["User-Agent"] == "pflow/1.0"
        assert headers["Accept"] == "application/json"
        assert headers["Authorization"] == "Bearer test-token"

    def test_expand_env_vars_nested(self):
        """Test environment variable expansion in nested structures."""
        import os

        node = MCPNode()

        # Set test environment variable
        os.environ["TEST_TOKEN"] = "secret-token"  # noqa: S105
        os.environ["TEST_KEY"] = "secret-key"

        try:
            # Test nested dictionary
            data = {"auth": {"type": "bearer", "token": "${TEST_TOKEN}"}, "headers": {"API-Key": "${TEST_KEY}"}}

            expanded = node._expand_env_vars(data)

            assert expanded["auth"]["token"] == "secret-token"  # noqa: S105
            assert expanded["headers"]["API-Key"] == "secret-key"

        finally:
            # Clean up
            del os.environ["TEST_TOKEN"]
            del os.environ["TEST_KEY"]

    def test_exec_async_http_routing(self):
        """Test that HTTP transport routes to correct method."""
        import asyncio

        node = MCPNode()

        prep_res = {
            "config": {"transport": "http", "url": "https://api.example.com/mcp"},
            "server": "test",
            "tool": "test_tool",
            "arguments": {},
        }

        # Mock the HTTP method
        with patch.object(node, "_exec_async_http", new_callable=AsyncMock) as mock_http:
            mock_http.return_value = {"result": "test_result"}

            # Run the async method using asyncio.run
            result = asyncio.run(node._exec_async(prep_res))

            mock_http.assert_called_once_with(prep_res)
            assert result == {"result": "test_result"}

    def test_exec_async_stdio_routing(self):
        """Test that stdio transport routes to correct method."""
        import asyncio

        node = MCPNode()

        prep_res = {
            "config": {"transport": "stdio", "command": "test"},
            "server": "test",
            "tool": "test_tool",
            "arguments": {},
        }

        # Mock the stdio method
        with patch.object(node, "_exec_async_stdio", new_callable=AsyncMock) as mock_stdio:
            mock_stdio.return_value = {"result": "test_result"}

            # Run the async method using asyncio.run
            result = asyncio.run(node._exec_async(prep_res))

            mock_stdio.assert_called_once_with(prep_res)
            assert result == {"result": "test_result"}

    def test_http_error_handling(self):
        """Test HTTP-specific error handling in exec_fallback."""
        node = MCPNode()

        prep_res = {"config": {"url": "https://api.example.com/mcp"}}

        # Test connection error
        try:
            import httpx

            exc = httpx.ConnectError("Connection failed")
            result = node.exec_fallback(prep_res, exc)
            assert "Could not connect to MCP server" in result["error"]

            # Test timeout error
            exc = httpx.TimeoutException("Timeout")
            result = node.exec_fallback(prep_res, exc)
            assert "timed out" in result["error"]

            # Test 401 error
            response_mock = Mock()
            response_mock.status_code = 401
            exc = httpx.HTTPStatusError("Auth failed", request=None, response=response_mock)
            result = node.exec_fallback(prep_res, exc)
            assert "Authentication failed" in result["error"]

            # Test 429 error
            response_mock.status_code = 429
            exc = httpx.HTTPStatusError("Rate limited", request=None, response=response_mock)
            result = node.exec_fallback(prep_res, exc)
            assert "Rate limited" in result["error"]

        except ImportError:
            # httpx not installed in test environment - skip
            pytest.skip("httpx not available")


class TestHTTPDiscovery:
    """Test tool discovery over HTTP transport."""

    def test_discovery_routing(self):
        """Test that discovery routes based on transport."""
        import asyncio

        from pflow.mcp.discovery import MCPDiscovery

        discovery = MCPDiscovery()

        # Test HTTP routing
        http_config = {"transport": "http", "url": "https://api.example.com/mcp"}

        with patch.object(discovery, "_discover_async_http", new_callable=AsyncMock) as mock_http:
            mock_http.return_value = [{"name": "tool1"}]

            # Run the async method using asyncio.run
            result = asyncio.run(discovery._discover_async("test", http_config))

            mock_http.assert_called_once_with("test", http_config)
            assert result == [{"name": "tool1"}]

        # Test stdio routing
        stdio_config = {"transport": "stdio", "command": "test"}

        with patch.object(discovery, "_discover_async_stdio", new_callable=AsyncMock) as mock_stdio:
            mock_stdio.return_value = [{"name": "tool2"}]

            # Run the async method using asyncio.run
            result = asyncio.run(discovery._discover_async("test", stdio_config))

            mock_stdio.assert_called_once_with("test", stdio_config)
            assert result == [{"name": "tool2"}]


# Simple test runner for manual testing
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
