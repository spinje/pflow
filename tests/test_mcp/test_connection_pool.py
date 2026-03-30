"""Tests for MCPConnectionPool — keeps MCP server sessions alive across workflow steps.

Tests mock at the MCP SDK boundary (stdio_client, ClientSession, streamablehttp_client)
for pool unit tests, and at the pool boundary for integration tests.

Thread safety: Every test that calls pool.call_tool() starts a background thread.
Always call pool.shutdown() in a finally block to prevent thread leaks.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pflow.mcp.pool import MCPConnectionPool, _is_transport_error

_HAS_EXCEPTION_GROUP = sys.version_info >= (3, 11)

# ---------------------------------------------------------------------------
# Helpers for building async-context-manager mocks compatible with AsyncExitStack
# ---------------------------------------------------------------------------


def _make_async_cm(return_value: object) -> MagicMock:
    """Create a mock that works as an async context manager.

    AsyncExitStack.enter_async_context(cm) calls cm.__aenter__().
    This helper creates a mock whose __aenter__ returns *return_value*.
    """
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=return_value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_mock_session(call_tool_return: object = None) -> AsyncMock:
    """Create a mock ClientSession with initialize() and call_tool()."""
    session = AsyncMock()
    session.initialize = AsyncMock()
    session.call_tool = AsyncMock(return_value=call_tool_return)
    return session


def _stdio_config() -> dict:
    """Minimal stdio server config."""
    return {"command": "echo", "args": ["hello"]}


def _http_config() -> dict:
    """Minimal HTTP server config."""
    return {"type": "http", "url": "http://localhost:8080/mcp"}


def _mock_call_result(text: str = "ok") -> MagicMock:
    """Create a mock CallToolResult."""
    result = MagicMock()
    result.content = [MagicMock(text=text)]
    result.isError = False
    result.structuredContent = None
    return result


# ---------------------------------------------------------------------------
# Pool unit tests — mock at MCP SDK boundary
# ---------------------------------------------------------------------------


class TestPoolLifecycle:
    """Test pool startup, lazy initialization, and shutdown semantics."""

    def test_pool_lazy_initialization(self):
        """No background thread is created until the first call_tool().

        The pool should be zero-cost if no MCP tools are used in a workflow.
        """
        pool = MCPConnectionPool()

        # Before any call_tool, no thread or event loop should exist
        assert pool._loop is None
        assert pool._thread is None
        assert pool._sessions == {}
        assert pool._stacks == {}

    @patch("pflow.mcp.pool.stdio_client")
    @patch("pflow.mcp.pool.ClientSession")
    def test_pool_shutdown_closes_all_sessions(self, mock_session_cls, mock_stdio):
        """shutdown() closes all exit stacks and stops the background thread.

        FIX HISTORY:
        - Initial: Verified stacks are cleaned up on shutdown.
        """
        mock_result = _mock_call_result("done")
        session = _make_mock_session(call_tool_return=mock_result)

        # stdio_client returns an async CM yielding (read, write)
        mock_stdio.return_value = _make_async_cm((MagicMock(), MagicMock()))
        # ClientSession constructor returns an async CM yielding the session
        mock_session_cls.return_value = _make_async_cm(session)

        pool = MCPConnectionPool()
        try:
            pool.call_tool("server-a", "tool", {}, _stdio_config(), timeout=5)
            pool.call_tool("server-b", "tool", {}, _stdio_config(), timeout=5)
        finally:
            pool.shutdown()

        # After shutdown, internal state should be cleared
        assert pool._loop is None
        assert pool._thread is None
        assert pool._sessions == {}
        assert pool._stacks == {}

    def test_pool_double_shutdown_safe(self):
        """Calling shutdown() twice must not raise.

        The executor's finally block always calls shutdown(), so it must be
        safe even if shutdown was already called (e.g., due to an error path).
        """
        pool = MCPConnectionPool()
        # First shutdown on a never-started pool
        pool.shutdown()
        # Second shutdown — must not raise
        pool.shutdown()

        assert pool._loop is None

    def test_pool_not_started_shutdown_safe(self):
        """shutdown() on a pool that was never used is a no-op.

        This happens when a workflow has no MCP nodes.
        """
        pool = MCPConnectionPool()
        # Should not raise
        pool.shutdown()
        assert pool._loop is None
        assert pool._thread is None


class TestPoolSessionManagement:
    """Test session creation, reuse, and eviction."""

    @patch("pflow.mcp.pool.stdio_client")
    @patch("pflow.mcp.pool.ClientSession")
    def test_pool_session_reuse_same_server(self, mock_session_cls, mock_stdio):
        """Two calls to the same server should reuse the same session.

        Without reuse, stateful servers (Playwright, databases) lose state
        between workflow steps.
        """
        mock_result = _mock_call_result("result")
        session = _make_mock_session(call_tool_return=mock_result)

        mock_stdio.return_value = _make_async_cm((MagicMock(), MagicMock()))
        mock_session_cls.return_value = _make_async_cm(session)

        pool = MCPConnectionPool()
        try:
            pool.call_tool("playwright", "navigate", {"url": "http://example.com"}, _stdio_config(), timeout=5)
            pool.call_tool("playwright", "screenshot", {}, _stdio_config(), timeout=5)

            # stdio_client should have been entered exactly once (session reused)
            assert mock_stdio.call_count == 1
            # call_tool should have been called twice on the same session
            assert session.call_tool.call_count == 2
        finally:
            pool.shutdown()

    @patch("pflow.mcp.pool.stdio_client")
    @patch("pflow.mcp.pool.ClientSession")
    def test_pool_separate_sessions_different_servers(self, mock_session_cls, mock_stdio):
        """Two different servers should get separate sessions.

        Each MCP server is a different process with its own state.
        """
        mock_result = _mock_call_result("result")
        session1 = _make_mock_session(call_tool_return=mock_result)
        session2 = _make_mock_session(call_tool_return=mock_result)

        mock_stdio.return_value = _make_async_cm((MagicMock(), MagicMock()))
        # Return different sessions for each server
        mock_session_cls.side_effect = [
            _make_async_cm(session1),
            _make_async_cm(session2),
        ]

        pool = MCPConnectionPool()
        try:
            pool.call_tool("github", "list-issues", {}, _stdio_config(), timeout=5)
            pool.call_tool("filesystem", "read-file", {}, _stdio_config(), timeout=5)

            # Two separate stdio_client connections
            assert mock_stdio.call_count == 2
            # Each session called once
            assert session1.call_tool.call_count == 1
            assert session2.call_tool.call_count == 1
        finally:
            pool.shutdown()


class TestPoolErrorHandling:
    """Test error handling, crash recovery, and timeout behavior."""

    @patch("pflow.mcp.pool.stdio_client")
    @patch("pflow.mcp.pool.ClientSession")
    def test_pool_shutdown_on_failure(self, mock_session_cls, mock_stdio):
        """Cleanup must happen even after a tool error.

        The executor_service.py finally block calls pool.shutdown().
        Sessions must be properly torn down even if call_tool raised.
        """
        session = _make_mock_session()
        session.call_tool = AsyncMock(side_effect=ValueError("bad argument"))

        mock_stdio.return_value = _make_async_cm((MagicMock(), MagicMock()))
        mock_session_cls.return_value = _make_async_cm(session)

        pool = MCPConnectionPool()
        try:
            with pytest.raises(ValueError, match="bad argument"):
                pool.call_tool("server", "tool", {}, _stdio_config(), timeout=5)
        finally:
            pool.shutdown()

        # Pool should be fully cleaned up
        assert pool._loop is None
        assert pool._sessions == {}

    @patch("pflow.mcp.pool.stdio_client")
    @patch("pflow.mcp.pool.ClientSession")
    def test_pool_crash_recovery_reconnects_on_transport_error(self, mock_session_cls, mock_stdio):
        """Transport error (BrokenPipeError) should evict the dead session and retry.

        Real scenario: MCP server crashes mid-workflow. The pool should
        automatically reconnect and retry the call on a fresh session.
        """
        mock_result = _mock_call_result("recovered")

        # First session: dies with BrokenPipeError
        dead_session = _make_mock_session()
        dead_session.call_tool = AsyncMock(side_effect=BrokenPipeError("pipe broke"))

        # Second session: works fine (created after eviction)
        fresh_session = _make_mock_session(call_tool_return=mock_result)

        mock_stdio.return_value = _make_async_cm((MagicMock(), MagicMock()))
        # First call creates dead session, second call (after eviction) creates fresh one
        mock_session_cls.side_effect = [
            _make_async_cm(dead_session),
            _make_async_cm(fresh_session),
        ]

        pool = MCPConnectionPool()
        try:
            result = pool.call_tool("server", "tool", {}, _stdio_config(), timeout=5)

            # Should have recovered and returned the fresh session's result
            assert result is mock_result
            # Two sessions created: the dead one and the fresh one
            assert mock_session_cls.call_count == 2
        finally:
            pool.shutdown()

    @patch("pflow.mcp.pool.stdio_client")
    @patch("pflow.mcp.pool.ClientSession")
    def test_pool_timeout_does_not_kill_session(self, mock_session_cls, mock_stdio):
        """A timeout must NOT evict the session — the server is alive, just slow.

        Real scenario: Playwright browser_navigate takes 35s on a slow page.
        With a 30s timeout, the pool should raise TimeoutError but keep the
        session alive so the next call (e.g., screenshot) still works.

        If the pool incorrectly treats TimeoutError as a transport error, it
        would kill the browser and start a fresh one — exactly the state-loss
        bug this whole feature was built to fix.
        """
        mock_result = _mock_call_result("recovered after timeout")
        session = _make_mock_session()

        # First call: times out (asyncio.timeout raises TimeoutError)
        # Second call: succeeds (session still alive)
        session.call_tool = AsyncMock(side_effect=[asyncio.TimeoutError("timed out"), mock_result])

        mock_stdio.return_value = _make_async_cm((MagicMock(), MagicMock()))
        mock_session_cls.return_value = _make_async_cm(session)

        pool = MCPConnectionPool()
        try:
            # First call should raise TimeoutError (not retry)
            with pytest.raises(asyncio.TimeoutError):
                pool.call_tool("playwright", "navigate", {}, _stdio_config(), timeout=5)

            # Session must NOT have been evicted — only 1 session created
            assert mock_session_cls.call_count == 1

            # Second call should reuse the same session and succeed
            result = pool.call_tool("playwright", "screenshot", {}, _stdio_config(), timeout=5)
            assert result is mock_result

            # Still only 1 session — the timeout didn't kill it
            assert mock_session_cls.call_count == 1
        finally:
            pool.shutdown()

    @patch("pflow.mcp.pool.stdio_client")
    @patch("pflow.mcp.pool.ClientSession")
    def test_pool_no_retry_on_non_transport_error(self, mock_session_cls, mock_stdio):
        """Non-transport errors (e.g., ValueError) should propagate without retry.

        Only transport errors (BrokenPipe, ConnectionError) indicate a dead
        session worth reconnecting. Application-level errors should fail immediately.
        """
        session = _make_mock_session()
        session.call_tool = AsyncMock(side_effect=ValueError("invalid argument"))

        mock_stdio.return_value = _make_async_cm((MagicMock(), MagicMock()))
        mock_session_cls.return_value = _make_async_cm(session)

        pool = MCPConnectionPool()
        try:
            with pytest.raises(ValueError, match="invalid argument"):
                pool.call_tool("server", "tool", {}, _stdio_config(), timeout=5)

            # Should NOT have created a second session (no retry)
            assert mock_session_cls.call_count == 1
        finally:
            pool.shutdown()


class TestPoolHTTPTransport:
    """Test HTTP transport path."""

    @patch("pflow.mcp.pool.ClientSession")
    def test_pool_http_transport_uses_streamablehttp_client(self, mock_session_cls):
        """HTTP config should route to streamablehttp_client, not stdio_client.

        HTTP transport is used for remote MCP servers (e.g., cloud-hosted).
        """
        mock_result = _mock_call_result("http-result")
        session = _make_mock_session(call_tool_return=mock_result)
        mock_session_cls.return_value = _make_async_cm(session)

        pool = MCPConnectionPool()
        try:
            with (
                patch("mcp.client.streamable_http.streamablehttp_client") as mock_http,
                patch("pflow.mcp.auth_utils.build_auth_headers", return_value={}),
            ):
                mock_http.return_value = _make_async_cm((MagicMock(), MagicMock(), MagicMock()))

                result = pool.call_tool("remote-server", "tool", {}, _http_config(), timeout=5)

                assert result is mock_result
                # streamablehttp_client should have been called
                mock_http.assert_called_once()
        finally:
            pool.shutdown()


class TestIsTransportError:
    """Test the _is_transport_error helper used for crash recovery decisions."""

    def test_broken_pipe_is_transport_error(self):
        assert _is_transport_error(BrokenPipeError("pipe broke"))

    def test_connection_error_is_transport_error(self):
        assert _is_transport_error(ConnectionError("refused"))

    def test_os_error_is_transport_error(self):
        assert _is_transport_error(OSError("disk error"))

    def test_closed_resource_error_is_transport_error(self):
        """ClosedResourceError (anyio) is detected by name to avoid import."""

        class ClosedResourceError(Exception):
            pass

        assert _is_transport_error(ClosedResourceError())

    def test_timeout_error_is_not_transport_error(self):
        """TimeoutError must NOT be treated as a transport error.

        Even though TimeoutError is an OSError subclass on Python 3.11+,
        a timeout means the server is slow, not dead. Retrying would:
        1. Kill the session (destroying state like a Playwright browser)
        2. Start a brand new server
        3. Retry the same slow call (likely timing out again)
        This is the exact state-loss bug the pool was built to prevent.
        """
        assert not _is_transport_error(TimeoutError())
        assert not _is_transport_error(asyncio.TimeoutError())

    def test_value_error_is_not_transport_error(self):
        assert not _is_transport_error(ValueError("bad value"))

    @pytest.mark.skipif(not _HAS_EXCEPTION_GROUP, reason="ExceptionGroup requires Python 3.11+")
    def test_exception_group_with_transport_error(self):
        """ExceptionGroup wrapping a transport error should be detected."""
        inner = BrokenPipeError("pipe broke")
        group = ExceptionGroup("group", [inner])  # noqa: F821
        assert _is_transport_error(group)

    @pytest.mark.skipif(not _HAS_EXCEPTION_GROUP, reason="ExceptionGroup requires Python 3.11+")
    def test_exception_group_without_transport_error(self):
        """ExceptionGroup without transport errors should not match."""
        inner = ValueError("not transport")
        group = ExceptionGroup("group", [inner])  # noqa: F821
        assert not _is_transport_error(group)

    @pytest.mark.skipif(not _HAS_EXCEPTION_GROUP, reason="ExceptionGroup requires Python 3.11+")
    def test_exception_group_with_only_timeout_is_not_transport(self):
        """ExceptionGroup wrapping only TimeoutError should not be a transport error."""
        inner = TimeoutError("timed out")
        group = ExceptionGroup("group", [inner])  # noqa: F821
        assert not _is_transport_error(group)


# ---------------------------------------------------------------------------
# Integration tests — mock at pool boundary
# ---------------------------------------------------------------------------


class TestMCPNodePoolIntegration:
    """Test that MCPNode correctly uses the pool when available."""

    def test_mcp_node_uses_pool_when_present_in_shared_store(self):
        """When __mcp_pool__ is in shared store, MCPNode should call pool.call_tool().

        This is the normal workflow execution path where the executor_service
        injects the pool into the shared store.
        """
        from pflow.nodes.mcp.node import MCPNode

        node = MCPNode()
        node.set_params({"__mcp_server__": "github", "__mcp_tool__": "list-issues"})

        # Create a mock pool
        mock_pool = MagicMock()
        mock_raw_result = _mock_call_result("pool result")
        mock_pool.call_tool.return_value = mock_raw_result

        # Prep with pool in shared store
        with patch.object(node, "_load_server_config", return_value=_stdio_config()):
            shared = {"__mcp_pool__": mock_pool}
            prep_res = node.prep(shared)

        # Exec should use the pool
        exec_res = node.exec(prep_res)

        # Pool's call_tool should have been called
        mock_pool.call_tool.assert_called_once_with(
            server_name="github",
            tool="list-issues",
            arguments={},
            config=prep_res["config"],
            verbose=False,
            timeout=30,
        )

        # Result should be extracted via _extract_result
        assert "result" in exec_res

    def test_mcp_node_fallback_when_no_pool(self):
        """When no pool in shared store, MCPNode falls back to asyncio.run().

        This path is used by `pflow registry run` (single-node execution).
        """
        from pflow.nodes.mcp.node import MCPNode

        node = MCPNode()
        node.set_params({"__mcp_server__": "test", "__mcp_tool__": "test-tool"})

        with patch.object(node, "_load_server_config", return_value=_stdio_config()):
            shared = {}  # No __mcp_pool__
            prep_res = node.prep(shared)

        # Pool should not be in prep_res
        assert prep_res.get("pool") is None

        # Exec should fall back to asyncio.run
        with patch.object(node, "_exec_async", new_callable=AsyncMock) as mock_async:
            mock_async.return_value = {"result": "async fallback"}
            exec_res = node.exec(prep_res)

        assert exec_res == {"result": "async fallback"}
        mock_async.assert_called_once_with(prep_res)

    def test_mcp_node_pool_result_extraction(self):
        """Pool returns raw CallToolResult; MCPNode must run _extract_result on it.

        Without extraction, downstream nodes would get the raw MCP SDK object
        instead of usable Python data.
        """
        from pflow.nodes.mcp.node import MCPNode

        node = MCPNode()
        node.set_params({"__mcp_server__": "test", "__mcp_tool__": "tool"})

        # Create a realistic CallToolResult mock
        mock_raw_result = MagicMock()
        mock_raw_result.structuredContent = {"key": "structured_value"}
        mock_raw_result.isError = False

        mock_pool = MagicMock()
        mock_pool.call_tool.return_value = mock_raw_result

        with patch.object(node, "_load_server_config", return_value=_stdio_config()):
            shared = {"__mcp_pool__": mock_pool}
            prep_res = node.prep(shared)

        exec_res = node.exec(prep_res)

        # _extract_result should have been applied: structuredContent takes priority
        assert exec_res["result"] == {"key": "structured_value"}


class TestRunnerPoolLifecycle:
    """Test that WorkflowRunner creates and shuts down the MCP pool."""

    def test_runner_creates_pool_in_shared_store(self):
        """Runner should create MCPConnectionPool for every execution.

        Every workflow execution needs a pool, even if no MCP nodes are present
        (the pool is lazy — no cost if unused).
        """
        from pflow.execution.result import RunnerConfig
        from pflow.execution.runner import WorkflowRunner

        workflow_ir = {
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo hi"}}],
            "edges": [],
        }

        result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

        assert result.success
        assert "__mcp_pool__" in result.shared_after
        assert isinstance(result.shared_after["__mcp_pool__"], MCPConnectionPool)

    def test_runner_shuts_down_pool_on_success(self):
        """Pool shutdown() should be called after successful execution."""
        from pflow.execution.result import RunnerConfig
        from pflow.execution.runner import WorkflowRunner

        mock_pool = MagicMock()
        mock_compiled = MagicMock(resolved_defaults={})
        mock_engine = MagicMock()
        mock_engine.run.return_value = "default"

        workflow_ir = {
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo hi"}}],
            "edges": [],
        }

        with (
            patch("pflow.runtime.compile_workflow", return_value=mock_compiled),
            patch("pflow.runtime.WorkflowEngine", return_value=mock_engine),
            patch("pflow.mcp.pool.MCPConnectionPool", return_value=mock_pool),
        ):
            WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

        mock_pool.shutdown.assert_called_once()

    def test_runner_shuts_down_pool_on_failure(self):
        """Pool shutdown() should be called even when compilation raises.

        The finally block in run() must always clean up the pool.
        """
        from pflow.execution.result import RunnerConfig
        from pflow.execution.runner import WorkflowRunner

        mock_pool = MagicMock()

        workflow_ir = {
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo hi"}}],
            "edges": [],
        }

        with (
            patch(
                "pflow.runtime.compile_workflow",
                side_effect=ValueError("compilation failed"),
            ),
            patch("pflow.mcp.pool.MCPConnectionPool", return_value=mock_pool),
        ):
            result = WorkflowRunner().run(workflow_ir, {}, RunnerConfig())

        assert not result.success
        mock_pool.shutdown.assert_called_once()
