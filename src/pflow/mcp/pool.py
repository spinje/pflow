"""MCP connection pool that keeps server sessions alive across workflow steps.

Without pooling, each MCPNode.exec() creates a new event loop and server subprocess.
Stateful servers (Playwright, databases) lose all state between steps. This pool keeps
sessions alive for the duration of a workflow run via a background asyncio event loop thread.

Usage:
    pool = MCPConnectionPool()
    result = pool.call_tool("playwright", "browser_navigate", {"url": "..."}, config, ...)
    result = pool.call_tool("playwright", "browser_screenshot", {}, config, ...)  # same session
    pool.shutdown()  # kills all servers
"""

import asyncio
import concurrent.futures
import logging
import os
import sys
import threading
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

logger = logging.getLogger(__name__)

# Transport errors that indicate a dead session worth retrying
_TRANSPORT_ERRORS = (BrokenPipeError, ConnectionError, OSError)


def _is_transport_error(exc: BaseException) -> bool:
    """Check if an exception (or ExceptionGroup member) is a transport error.

    TimeoutError is explicitly excluded even though it's an OSError subclass
    on Python 3.11+. A timeout means the server is slow, not dead — retrying
    would kill the session (destroying state) and restart from scratch.
    """
    # TimeoutError is an OSError subclass on Python 3.11+, but it's NOT
    # a transport error — the server is alive, just slow. Retrying would
    # kill state (e.g., Playwright browser session) for no benefit.
    if isinstance(exc, TimeoutError):
        return False
    # Direct match
    if isinstance(exc, _TRANSPORT_ERRORS):
        return True
    # anyio.ClosedResourceError is an OSError subclass on some versions,
    # but check by name to avoid import issues
    if type(exc).__name__ == "ClosedResourceError":
        return True
    # ExceptionGroup wrapping transport errors (Python 3.11+)
    if hasattr(exc, "exceptions"):
        return any(_is_transport_error(e) for e in exc.exceptions)
    return False


class MCPConnectionPool:
    """Keeps MCP server connections alive across synchronous PocketFlow node calls.

    Threading model:
    - A background daemon thread runs an asyncio event loop (loop.run_forever())
    - Sync call_tool() submits coroutines via run_coroutine_threadsafe(), blocks on future
    - All mutable state (_sessions, _stacks) is accessed only from the background loop
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._sessions: dict[str, ClientSession] = {}
        self._stacks: dict[str, AsyncExitStack] = {}
        self._shutting_down = False

    # -- Public sync API --

    def call_tool(
        self,
        server_name: str,
        tool: str,
        arguments: dict[str, Any],
        config: dict[str, Any],
        verbose: bool = False,
        timeout: int = 30,
    ) -> CallToolResult:
        """Call an MCP tool, reusing or creating a server session.

        Args:
            server_name: MCP server name (e.g. "playwright")
            tool: Tool name (e.g. "browser_navigate")
            arguments: Tool arguments
            config: Server config from mcp-servers.json (already env-expanded)
            verbose: Whether to route server stderr to sys.stderr
            timeout: Timeout in seconds for the tool call

        Returns:
            Raw CallToolResult from the MCP SDK
        """
        self._ensure_started()
        if self._loop is None:  # pragma: no cover — _ensure_started guarantees this
            raise RuntimeError("MCPConnectionPool event loop not initialized")

        future = asyncio.run_coroutine_threadsafe(
            self._call_tool_async(server_name, tool, arguments, config, verbose, timeout),
            self._loop,
        )
        try:
            # Safety net timeout: async timeout should fire first
            return future.result(timeout=timeout + 5)
        except (TimeoutError, concurrent.futures.TimeoutError):
            # concurrent.futures.TimeoutError is a separate class on Python 3.10
            # (unified with builtins.TimeoutError on 3.11+). Convert to
            # asyncio.TimeoutError so MCPNode.exec_fallback handles it uniformly.
            raise asyncio.TimeoutError(f"MCP tool timed out after {timeout} seconds") from None

    def shutdown(self) -> None:
        """Close all sessions and stop the background loop. Safe to call multiple times."""
        if self._loop is None or self._shutting_down:
            return
        self._shutting_down = True

        try:
            future = asyncio.run_coroutine_threadsafe(self._shutdown_async(), self._loop)
            future.result(timeout=10)
        except Exception:
            logger.debug("MCP pool shutdown error", exc_info=True)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._loop = None
            self._thread = None
            self._sessions.clear()
            self._stacks.clear()

    # -- Internal sync helpers --

    def _ensure_started(self) -> None:
        """Start the background event loop thread on first use."""
        if self._loop is not None:
            return
        with self._lock:
            if self._loop is not None:
                return
            self._shutting_down = False  # reset in case of restart after shutdown
            loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=loop.run_forever,
                name="mcp-pool",
                daemon=True,
            )
            self._thread.start()
            # Set _loop last so the fast-path check above only passes
            # after the thread is actually running.
            self._loop = loop

    # -- Async internals (run on background loop) --

    async def _get_or_create_session(
        self,
        server_name: str,
        config: dict[str, Any],
        verbose: bool,
    ) -> ClientSession:
        """Get existing session or create a new one for the server."""
        if server_name in self._sessions:
            return self._sessions[server_name]

        stack = AsyncExitStack()
        await stack.__aenter__()

        transport_type = config.get("type", "stdio")

        if transport_type == "http":
            session = await self._create_http_session(stack, config, verbose)
        else:
            session = await self._create_stdio_session(stack, config, verbose)

        self._stacks[server_name] = stack
        self._sessions[server_name] = session
        logger.debug(f"MCP pool: created session for server '{server_name}' ({transport_type})")
        return session

    async def _create_stdio_session(
        self,
        stack: AsyncExitStack,
        config: dict[str, Any],
        verbose: bool,
    ) -> ClientSession:
        """Create a stdio transport session."""
        env = config.get("env", {})
        if not isinstance(env, dict):
            env = {}

        params = StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env=env if env else None,
        )

        if verbose:
            errlog = sys.stderr
        else:
            devnull = await stack.enter_async_context(_open_devnull())
            errlog = devnull

        read, write = await stack.enter_async_context(stdio_client(params, errlog=errlog))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    async def _create_http_session(
        self,
        stack: AsyncExitStack,
        config: dict[str, Any],
        verbose: bool,
    ) -> ClientSession:
        """Create an HTTP transport session."""
        from mcp.client.streamable_http import streamablehttp_client

        from pflow.mcp.auth_utils import build_auth_headers

        url = config.get("url")
        if not url:
            raise ValueError("HTTP transport requires 'url' in config")

        headers = build_auth_headers(config)
        timeout = config.get("timeout", 30)
        sse_timeout = config.get("sse_timeout", 300)

        read, write, _get_session_id = await stack.enter_async_context(
            streamablehttp_client(
                url=url,
                headers=headers,
                timeout=timeout,
                sse_read_timeout=sse_timeout,
                terminate_on_close=True,
            )
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    async def _call_tool_async(
        self,
        server_name: str,
        tool: str,
        arguments: dict[str, Any],
        config: dict[str, Any],
        verbose: bool,
        timeout: int,
    ) -> CallToolResult:
        """Get/create session and call the tool. Retry once on transport errors."""
        try:
            return await self._do_call(server_name, tool, arguments, config, verbose, timeout)
        except BaseException as exc:
            if not _is_transport_error(exc):
                raise
            logger.debug(f"MCP pool: transport error for '{server_name}', reconnecting: {exc}")
            await self._evict_session(server_name)
            return await self._do_call(server_name, tool, arguments, config, verbose, timeout)

    async def _do_call(
        self,
        server_name: str,
        tool: str,
        arguments: dict[str, Any],
        config: dict[str, Any],
        verbose: bool,
        timeout: int,
    ) -> CallToolResult:
        """Execute a single tool call with timeout.

        The timeout covers both session creation (server spawn + MCP handshake)
        and the tool call itself. For reused sessions, _get_or_create_session is
        a dict lookup so the timeout effectively only covers call_tool.
        """
        # asyncio.timeout() is Python 3.11+; fall back to wait_for on 3.10
        timeout_context = getattr(asyncio, "timeout", None)
        if timeout_context is not None:
            async with timeout_context(timeout):
                session = await self._get_or_create_session(server_name, config, verbose)
                return await session.call_tool(tool, arguments)
        else:

            async def _work() -> CallToolResult:
                session = await self._get_or_create_session(server_name, config, verbose)
                return await session.call_tool(tool, arguments)

            return await asyncio.wait_for(_work(), timeout=timeout)

    async def _evict_session(self, server_name: str) -> None:
        """Close and remove a dead session."""
        self._sessions.pop(server_name, None)
        stack = self._stacks.pop(server_name, None)
        if stack is not None:
            try:
                await stack.aclose()
            except Exception:
                logger.debug(f"MCP pool: error closing session for '{server_name}'", exc_info=True)

    async def _shutdown_async(self) -> None:
        """Close all exit stacks (kills all server subprocesses)."""
        for server_name in list(self._stacks):
            await self._evict_session(server_name)


@asynccontextmanager
async def _open_devnull() -> AsyncIterator[Any]:
    f = open(os.devnull, "w")  # noqa: SIM115
    try:
        yield f
    finally:
        f.close()
