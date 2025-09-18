"""Unit tests for MCP authentication utilities."""

import base64
import os
from unittest.mock import patch

import pytest

from pflow.mcp.auth_utils import build_auth_headers, expand_env_vars_nested


class TestExpandEnvVarsNested:
    """Test environment variable expansion functionality."""

    def test_expand_simple_string(self):
        """Test expanding a simple string with env var."""
        os.environ["TEST_VAR"] = "test_value"
        try:
            result = expand_env_vars_nested("${TEST_VAR}")
            assert result == "test_value"
        finally:
            del os.environ["TEST_VAR"]

    def test_expand_nested_dict(self):
        """Test expanding environment variables in nested dictionary."""
        os.environ["TEST_TOKEN"] = "secret_token"  # noqa: S105
        os.environ["TEST_KEY"] = "secret_key"
        try:
            data = {"auth": {"token": "${TEST_TOKEN}", "nested": {"key": "${TEST_KEY}"}}}
            result = expand_env_vars_nested(data)
            assert result["auth"]["token"] == "secret_token"  # noqa: S105
            assert result["auth"]["nested"]["key"] == "secret_key"
        finally:
            del os.environ["TEST_TOKEN"]
            del os.environ["TEST_KEY"]

    def test_expand_list(self):
        """Test expanding environment variables in list."""
        os.environ["TEST_ITEM1"] = "item1"
        os.environ["TEST_ITEM2"] = "item2"
        try:
            data = ["${TEST_ITEM1}", "static", "${TEST_ITEM2}"]
            result = expand_env_vars_nested(data)
            assert result == ["item1", "static", "item2"]
        finally:
            del os.environ["TEST_ITEM1"]
            del os.environ["TEST_ITEM2"]

    def test_missing_env_var(self):
        """Test behavior with missing environment variable."""
        # Ensure TEST_MISSING is not set
        os.environ.pop("TEST_MISSING", None)

        with patch("pflow.mcp.auth_utils.logger") as mock_logger:
            result = expand_env_vars_nested("${TEST_MISSING}")
            assert result == ""
            mock_logger.warning.assert_called_once()

    def test_non_string_values(self):
        """Test that non-string values pass through unchanged."""
        data = {"string": "test", "number": 42, "bool": True, "none": None}
        result = expand_env_vars_nested(data)
        assert result == data


class TestBuildAuthHeaders:
    """Test authentication header building."""

    def test_bearer_auth_success(self):
        """Test successful Bearer token authentication."""
        config = {"auth": {"type": "bearer", "token": "test_token_123"}}
        headers = build_auth_headers(config)
        assert headers["Authorization"] == "Bearer test_token_123"

    def test_bearer_auth_with_env_var(self):
        """Test Bearer auth with environment variable expansion."""
        os.environ["TEST_BEARER"] = "secret_bearer_token"
        try:
            config = {"auth": {"type": "bearer", "token": "${TEST_BEARER}"}}
            headers = build_auth_headers(config)
            assert headers["Authorization"] == "Bearer secret_bearer_token"
        finally:
            del os.environ["TEST_BEARER"]

    def test_bearer_auth_with_control_chars(self):
        """Test that Bearer tokens with control characters are rejected."""
        config = {"auth": {"type": "bearer", "token": "token\nwith\nnewlines"}}
        with patch("pflow.mcp.auth_utils.logger") as mock_logger:
            headers = build_auth_headers(config)
            assert "Authorization" not in headers
            mock_logger.error.assert_called()

    def test_api_key_auth_success(self):
        """Test successful API key authentication."""
        config = {"auth": {"type": "api_key", "key": "test_api_key_456"}}
        headers = build_auth_headers(config)
        assert headers["X-API-Key"] == "test_api_key_456"

    def test_api_key_auth_custom_header(self):
        """Test API key with custom header name."""
        config = {"auth": {"type": "api_key", "key": "test_key", "header": "X-Custom-Auth"}}
        headers = build_auth_headers(config)
        assert headers["X-Custom-Auth"] == "test_key"

    def test_api_key_with_control_chars(self):
        """Test that API keys with control characters are rejected."""
        config = {"auth": {"type": "api_key", "key": "key\rwith\rcarriage\rreturns"}}
        with patch("pflow.mcp.auth_utils.logger") as mock_logger:
            headers = build_auth_headers(config)
            assert "X-API-Key" not in headers
            mock_logger.error.assert_called()

    def test_basic_auth_success(self):
        """Test successful Basic authentication."""
        config = {"auth": {"type": "basic", "username": "testuser", "password": "testpass"}}
        headers = build_auth_headers(config)

        # Verify Basic auth header is correct
        expected = base64.b64encode(b"testuser:testpass").decode()
        assert headers["Authorization"] == f"Basic {expected}"

    def test_basic_auth_username_with_colon(self):
        """Test that Basic auth warns about colons in username."""
        config = {"auth": {"type": "basic", "username": "user:name", "password": "password"}}
        with patch("pflow.mcp.auth_utils.logger") as mock_logger:
            headers = build_auth_headers(config)
            # Should still create header but warn
            assert "Authorization" in headers
            mock_logger.warning.assert_called()

    def test_basic_auth_with_control_chars(self):
        """Test that Basic auth rejects credentials with control characters."""
        config = {
            "auth": {
                "type": "basic",
                "username": "user\x00name",  # Null character
                "password": "password",
            }
        }
        with patch("pflow.mcp.auth_utils.logger") as mock_logger:
            headers = build_auth_headers(config)
            assert "Authorization" not in headers
            mock_logger.error.assert_called()

    def test_basic_auth_password_with_control_chars(self):
        """Test that Basic auth rejects passwords with control characters."""
        config = {
            "auth": {
                "type": "basic",
                "username": "username",
                "password": "pass\x01word",  # Control character
            }
        }
        with patch("pflow.mcp.auth_utils.logger") as mock_logger:
            headers = build_auth_headers(config)
            assert "Authorization" not in headers
            mock_logger.error.assert_called()

    def test_custom_headers(self):
        """Test adding custom headers."""
        config = {"headers": {"User-Agent": "pflow/1.0", "X-Custom": "value"}}
        headers = build_auth_headers(config)
        assert headers["User-Agent"] == "pflow/1.0"
        assert headers["X-Custom"] == "value"

    def test_custom_headers_with_auth(self):
        """Test combining custom headers with authentication."""
        config = {"headers": {"User-Agent": "pflow/1.0"}, "auth": {"type": "bearer", "token": "test_token"}}
        headers = build_auth_headers(config)
        assert headers["User-Agent"] == "pflow/1.0"
        assert headers["Authorization"] == "Bearer test_token"

    def test_empty_auth_config(self):
        """Test with empty auth configuration."""
        config = {}
        headers = build_auth_headers(config)
        assert headers == {}

    def test_unknown_auth_type(self):
        """Test with unknown authentication type."""
        config = {"auth": {"type": "unknown_type"}}
        with patch("pflow.mcp.auth_utils.logger") as mock_logger:
            headers = build_auth_headers(config)
            assert headers == {}
            mock_logger.warning.assert_called_with("Unknown auth type: unknown_type")

    def test_missing_bearer_token(self):
        """Test Bearer auth with missing token."""
        config = {"auth": {"type": "bearer"}}
        with patch("pflow.mcp.auth_utils.logger") as mock_logger:
            headers = build_auth_headers(config)
            assert "Authorization" not in headers
            mock_logger.warning.assert_called()

    def test_missing_api_key(self):
        """Test API key auth with missing key."""
        config = {"auth": {"type": "api_key"}}
        with patch("pflow.mcp.auth_utils.logger") as mock_logger:
            headers = build_auth_headers(config)
            assert "X-API-Key" not in headers
            mock_logger.warning.assert_called()

    def test_missing_basic_credentials(self):
        """Test Basic auth with missing username or password."""
        # Missing password
        config = {"auth": {"type": "basic", "username": "user"}}
        with patch("pflow.mcp.auth_utils.logger") as mock_logger:
            headers = build_auth_headers(config)
            assert "Authorization" not in headers
            mock_logger.warning.assert_called()

        # Missing username
        config = {"auth": {"type": "basic", "password": "pass"}}
        with patch("pflow.mcp.auth_utils.logger") as mock_logger:
            headers = build_auth_headers(config)
            assert "Authorization" not in headers
            mock_logger.warning.assert_called()

    def test_auth_not_dict_after_expansion(self):
        """Test handling when auth is not a dict after env var expansion."""
        # This could happen if someone misconfigures their env vars
        with patch("pflow.mcp.auth_utils.expand_env_vars_nested") as mock_expand:
            # Return a string instead of dict for auth expansion
            mock_expand.return_value = "not_a_dict"

            config = {"auth": {"type": "bearer"}}

            with patch("pflow.mcp.auth_utils.logger") as mock_logger:
                headers = build_auth_headers(config)
                assert headers == {}
                mock_logger.warning.assert_called_with("Auth config is not a dictionary after expansion")


# Simple test runner for manual testing
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
