"""MCP SDK error handling — unwrap ExceptionGroups, produce Diagnostics.

The MCP SDK uses anyio task groups internally, which wrap exceptions in
ExceptionGroups. This module provides shared error handling for both
MCP tool execution (MCPNode) and MCP server discovery.
"""

import asyncio
import re

from pflow.core.diagnostic import Diagnostic, Severity


def unwrap_exception_group(exc: BaseException) -> BaseException:
    """Recursively unwrap ExceptionGroups to find the leaf exception.

    The MCP SDK uses anyio task groups internally. When an exception occurs
    inside a task group, Python wraps it in an ExceptionGroup. This extracts
    the actual exception so it can be classified by type.
    """
    exceptions: tuple[BaseException, ...] | None = getattr(exc, "exceptions", None)
    if exceptions:
        return unwrap_exception_group(exceptions[0])
    return exc


def describe_mcp_error(exc: BaseException, *, timeout: int | None = None) -> Diagnostic:
    """Turn any MCP SDK exception into a structured Diagnostic.

    Unwraps ExceptionGroups, classifies by exception type, returns an
    actionable Diagnostic. Used by both MCPNode.exec_fallback and MCP discovery.

    Args:
        exc: The exception from the MCP SDK (may be an ExceptionGroup).
        timeout: Optional timeout value for context in timeout messages.

    Returns:
        A Diagnostic with severity, message, and optional suggestions/context.
    """
    root = unwrap_exception_group(exc)
    name = type(root).__name__
    technical_details = str(root)

    # httpx HTTP status errors (401, 403, 429, 5xx, etc.)
    if name == "HTTPStatusError":
        return _describe_http_status_error(root, technical_details)

    # httpx connection errors
    if name == "ConnectError":
        msg = str(root)
        if "CERTIFICATE_VERIFY_FAILED" in msg or "SSL" in msg:
            return Diagnostic(
                severity=Severity.ERROR,
                source="mcp",
                title="SSL Certificate Error",
                message="SSL certificate verification failed.",
                context={"technical_details": technical_details},
            )
        return Diagnostic(
            severity=Severity.ERROR,
            source="mcp",
            title="Connection Failed",
            message="Could not connect to MCP server.",
            suggestions=["Check if the server is running and the URL is correct"],
            context={"technical_details": technical_details},
        )

    # httpx timeout
    if name == "TimeoutException":
        timeout_msg = f" after {timeout} seconds" if timeout else ""
        return Diagnostic(
            severity=Severity.ERROR,
            source="mcp",
            title="Request Timed Out",
            message=f"HTTP request timed out{timeout_msg}.",
            suggestions=["Try increasing the timeout setting"],
            context={"technical_details": technical_details},
        )

    # asyncio timeout
    if isinstance(root, asyncio.TimeoutError):
        timeout_msg = f" after {timeout} seconds" if timeout else ""
        return Diagnostic(
            severity=Severity.ERROR,
            source="mcp",
            title="Request Timed Out",
            message=f"Request timed out{timeout_msg}.",
            suggestions=["Try increasing the timeout setting"],
            context={"technical_details": technical_details},
        )

    # Known enrichments (server-specific patterns in error messages)
    msg = str(root)
    if "users cache is not ready yet" in msg:
        return Diagnostic(
            severity=Severity.ERROR,
            source="mcp",
            title="Server Initializing",
            message="Server is still initializing (this can take 10-20 seconds).",
            suggestions=["Wait and try again"],
        )

    # MCP protocol errors — extract clean message
    mcp_match = re.search(r"McpError: (.+?)(?:\n|$)", msg)
    if mcp_match:
        msg = mcp_match.group(1)

    return Diagnostic(
        severity=Severity.ERROR,
        source="mcp",
        message=msg,
        context={"technical_details": technical_details} if technical_details != msg else None,
    )


_STATUS_MAP: dict[int, tuple[str, str, list[str]]] = {
    401: (
        "Authentication Failed",
        "Authentication failed.",
        ["Check your API credentials or token for this server"],
    ),
    403: (
        "Access Forbidden",
        "Access forbidden.",
        ["Check your permissions for this server"],
    ),
    404: (
        "Not Found",
        "Endpoint not found or session expired.",
        ["Check the server URL in your configuration"],
    ),
    429: (
        "Rate Limited",
        "Too many requests.",
        ["Wait and try again"],
    ),
}


def _describe_http_status_error(exc: BaseException, technical_details: str) -> Diagnostic:
    """Classify HTTP status codes into actionable Diagnostics."""
    status = getattr(getattr(exc, "response", None), "status_code", None)

    if status in _STATUS_MAP:
        title, message, suggestions = _STATUS_MAP[status]
        return Diagnostic(
            severity=Severity.ERROR,
            source="mcp",
            title=title,
            message=message,
            suggestions=suggestions,
            context={"technical_details": technical_details},
        )

    if status and 500 <= status < 600:
        return Diagnostic(
            severity=Severity.ERROR,
            source="mcp",
            title="Server Error",
            message=f"Server error (HTTP {status}).",
            suggestions=["The server encountered an internal error — try again later"],
            context={"technical_details": technical_details},
        )

    if status is None:
        return Diagnostic(
            severity=Severity.ERROR,
            source="mcp",
            title="HTTP Error",
            message=str(exc)[:200],
            context={"technical_details": technical_details},
        )

    response_text = ""
    if hasattr(exc, "response") and hasattr(exc.response, "text"):
        response_text = exc.response.text[:200]

    return Diagnostic(
        severity=Severity.ERROR,
        source="mcp",
        title="HTTP Error",
        message=f"HTTP error {status}: {response_text}" if response_text else f"HTTP error {status}.",
        context={"technical_details": technical_details},
    )
