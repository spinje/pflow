"""Tests for shared MCP SDK error handling (mcp/errors.py)."""

import asyncio
import builtins
import sys

import pytest

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.mcp.errors import describe_mcp_error, unwrap_exception_group

httpx = pytest.importorskip("httpx")

_ExceptionGroup = getattr(builtins, "ExceptionGroup", None)


class TestUnwrapExceptionGroup:
    """Test ExceptionGroup unwrapping."""

    def test_non_exception_group_returns_self(self):
        exc = ValueError("plain error")
        assert unwrap_exception_group(exc) is exc

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="ExceptionGroup requires Python 3.11+")
    def test_single_child_unwraps(self):
        inner = ValueError("the real error")
        group = _ExceptionGroup("wrapper", [inner])
        assert unwrap_exception_group(group) is inner

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="ExceptionGroup requires Python 3.11+")
    def test_nested_groups_unwrap_recursively(self):
        inner = ValueError("the real error")
        inner_group = _ExceptionGroup("inner", [inner])
        outer_group = _ExceptionGroup("outer", [inner_group])
        assert unwrap_exception_group(outer_group) is inner

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="ExceptionGroup requires Python 3.11+")
    def test_multi_child_takes_first(self):
        first = ValueError("first")
        second = TypeError("second")
        group = _ExceptionGroup("multi", [first, second])
        assert unwrap_exception_group(group) is first


class TestDescribeMcpError:
    """Test describe_mcp_error produces correct Diagnostics."""

    def _make_http_status_error(self, status_code: int) -> "httpx.HTTPStatusError":
        response_mock = type("Response", (), {"status_code": status_code, "text": ""})()
        return httpx.HTTPStatusError(f"Client error '{status_code}'", request=None, response=response_mock)

    def test_http_401_produces_auth_diagnostic(self):
        exc = self._make_http_status_error(401)
        d = describe_mcp_error(exc)

        assert isinstance(d, Diagnostic)
        assert d.severity == Severity.ERROR
        assert "Authentication failed" in d.message
        assert d.title == "Authentication Failed"
        assert d.suggestions
        assert any("credentials" in s or "token" in s for s in d.suggestions)

    def test_http_403_produces_forbidden_diagnostic(self):
        d = describe_mcp_error(self._make_http_status_error(403))
        assert "forbidden" in d.message.lower()
        assert d.title == "Access Forbidden"

    def test_http_429_produces_rate_limit_diagnostic(self):
        d = describe_mcp_error(self._make_http_status_error(429))
        assert "Too many requests" in d.message
        assert d.suggestions

    def test_http_500_produces_server_error_diagnostic(self):
        d = describe_mcp_error(self._make_http_status_error(500))
        assert "Server error" in d.message
        assert d.title == "Server Error"

    def test_connect_error_produces_connection_diagnostic(self):
        exc = httpx.ConnectError("Connection refused")
        d = describe_mcp_error(exc)

        assert "Could not connect" in d.message
        assert d.title == "Connection Failed"
        assert d.suggestions

    def test_ssl_error_produces_ssl_diagnostic(self):
        exc = httpx.ConnectError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate"
        )
        d = describe_mcp_error(exc)

        assert "SSL" in d.title
        assert "SSL certificate verification failed" in d.message
        # No specific fix suggestions — multiple possible causes
        assert d.suggestions is None

    def test_timeout_with_value(self):
        exc = httpx.TimeoutException("Timeout")
        d = describe_mcp_error(exc, timeout=30)
        assert "timed out" in d.message
        assert "30 seconds" in d.message

    def test_timeout_without_value(self):
        exc = httpx.TimeoutException("Timeout")
        d = describe_mcp_error(exc)
        assert "timed out" in d.message

    def test_asyncio_timeout(self):
        exc = asyncio.TimeoutError()
        d = describe_mcp_error(exc, timeout=60)
        assert "timed out" in d.message
        assert "60 seconds" in d.message

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="ExceptionGroup requires Python 3.11+")
    def test_exception_group_wrapping_401_unwraps(self):
        """ExceptionGroup wrapping a 401 should produce 'Authentication failed'."""
        inner = self._make_http_status_error(401)
        group = _ExceptionGroup("unhandled errors in a TaskGroup", [inner])

        d = describe_mcp_error(group)

        assert "Authentication failed" in d.message
        assert d.title == "Authentication Failed"
        assert "unhandled errors" not in d.message

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="ExceptionGroup requires Python 3.11+")
    def test_nested_exception_group_unwraps(self):
        """Nested ExceptionGroups should still find the inner error."""
        inner = self._make_http_status_error(401)
        inner_group = _ExceptionGroup("inner", [inner])
        outer_group = _ExceptionGroup("outer", [inner_group])

        d = describe_mcp_error(outer_group)
        assert "Authentication failed" in d.message

    def test_mcp_error_string_extraction(self):
        """McpError pattern in exception string should be extracted."""
        exc = Exception("McpError: Required parameter 'repository' is missing")
        d = describe_mcp_error(exc)
        assert "Required parameter 'repository' is missing" in d.message
        assert "McpError" not in d.message

    def test_slack_cache_enrichment(self):
        """Known Slack cache error should get enriched message."""
        exc = Exception("users cache is not ready yet")
        d = describe_mcp_error(exc)
        assert "initializing" in d.message
        assert d.suggestions
        assert any("wait" in s.lower() or "Wait" in s for s in d.suggestions)

    def test_generic_exception_uses_str(self):
        exc = ValueError("something unexpected happened")
        d = describe_mcp_error(exc)
        assert d.message == "something unexpected happened"

    def test_technical_details_in_context(self):
        """HTTP errors should include technical_details in context for --verbose."""
        exc = self._make_http_status_error(401)
        d = describe_mcp_error(exc)
        assert d.context is not None
        assert "technical_details" in d.context

    def test_diagnostic_source_is_mcp(self):
        exc = ValueError("any error")
        d = describe_mcp_error(exc)
        assert d.source == "mcp"
