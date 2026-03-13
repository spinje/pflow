# Task 127 Review: MCP Server Connection Pooling Across Workflow Steps

## Metadata
- Implementation Date: 2026-03-13
- Status: Complete, verified with manual end-to-end test

## Executive Summary

Added `MCPConnectionPool` — a background asyncio event loop thread that keeps MCP server sessions alive across workflow steps. This fixes a **silent failure** where stateful MCP servers (Playwright, databases) lost all state between nodes because each `MCPNode.exec()` spawned and killed a fresh subprocess. The fix required bridging PocketFlow's synchronous execution model with the MCP SDK's async-only API via `asyncio.run_coroutine_threadsafe()`.

## Implementation Overview

### What Was Built

A connection pool (`MCPConnectionPool`) that:
- Runs a background daemon thread with a persistent `asyncio` event loop (`loop.run_forever()`)
- Lazily creates MCP server sessions on first use, reuses them for subsequent calls to the same server
- Manages per-server `AsyncExitStack` instances for independent lifecycle control
- Provides crash recovery: transport errors (BrokenPipe, ClosedResource) trigger evict-and-retry once
- Handles both stdio and HTTP MCP transports
- Falls back to the old `asyncio.run()` behavior when no pool is present (e.g., `pflow registry run`)

### Implementation Approach

The core challenge was bridging sync PocketFlow nodes with async MCP SDK resources that need to persist across multiple synchronous node executions. The solution: a background thread running `loop.run_forever()`, with sync callers submitting work via `asyncio.run_coroutine_threadsafe()` and blocking on the returned future.

Per-server `AsyncExitStack` (rather than one global stack) enables independent crash recovery — evicting a dead server's stack doesn't affect other servers' sessions.

## Files Modified/Created

### Core Changes
- `src/pflow/mcp/pool.py` — **Created.** The pool implementation (~310 lines). Contains `MCPConnectionPool` class and `_is_transport_error()` helper.
- `src/pflow/nodes/mcp/node.py` — **Modified.** `prep()` reads `__mcp_pool__` from shared store; `exec()` uses pool when available, falls back to `asyncio.run()` otherwise. ~15 lines changed.
- `src/pflow/execution/executor_service.py` — **Modified.** Pool created in `_initialize_shared_store()`, shut down in `finally` block of `execute_workflow()`. ~10 lines changed.
- `src/pflow/mcp/__init__.py` — **Modified.** Added `MCPConnectionPool` to exports.

### Test Files
- `tests/test_mcp/test_connection_pool.py` — **Created.** 26 tests across 7 test classes (~610 lines).

**Critical tests** (catch real bugs, not just coverage):
- `test_pool_session_reuse_same_server` — The core scenario: two calls to same server verify `stdio_client` entered once
- `test_pool_timeout_does_not_kill_session` — Prevents the exact state-loss bug: timeout must NOT evict the session
- `test_pool_crash_recovery_reconnects_on_transport_error` — Verifies BrokenPipe → evict → reconnect → retry
- `test_executor_shuts_down_pool_on_failure` — Ensures subprocess cleanup even on workflow failure
- `test_mcp_node_fallback_when_no_pool` — Ensures `pflow registry run` still works without a pool

## Integration Points & Dependencies

### Incoming Dependencies
- `WorkflowExecutorService` → creates and destroys `MCPConnectionPool` (lifecycle owner)
- `MCPNode.prep()` → reads pool from shared store
- `MCPNode.exec()` → calls `pool.call_tool()` synchronously

### Outgoing Dependencies
- `MCPConnectionPool` → `mcp.client.stdio.stdio_client` (MCP SDK, spawns subprocess)
- `MCPConnectionPool` → `mcp.ClientSession` (MCP SDK, protocol layer)
- `MCPConnectionPool` → `mcp.client.streamable_http.streamablehttp_client` (HTTP transport)
- `MCPConnectionPool` → `pflow.mcp.auth_utils.build_auth_headers` (HTTP auth)

### Shared Store Keys
- `__mcp_pool__` — `MCPConnectionPool` instance. Created in `_initialize_shared_store()`, consumed by `MCPNode.prep()`, cleaned up in `finally` block. Dunder key = bypasses namespacing, accessible to all nodes.

## Architectural Decisions & Tradeoffs

### Key Decisions

1. **Background thread + `run_coroutine_threadsafe()` over `asyncio.run()` per call**
   - Reasoning: MCP SDK resources (anyio task groups, streams, subprocesses) are event-loop-bound. To keep them alive across synchronous node calls, we need a persistent loop.
   - Alternative: `ClientSessionGroup` from MCP SDK — rejected because it calls `list_tools()` on every `connect_to_server()` (pflow already has this data) and routes by tool name (pflow already knows the server).

2. **Per-server `AsyncExitStack` over one global stack**
   - Reasoning: Enables evicting a single crashed server without affecting others. `AsyncExitStack` doesn't support selective cleanup of individual entries.
   - Alternative: Global `AsyncExitStack` with `pop_all()` — too complex, fragile.

3. **Lazy startup (thread created on first `call_tool()`, not at `__init__`)**
   - Reasoning: Zero cost for workflows with no MCP nodes. Pool creation happens in `_initialize_shared_store()` for every workflow.

4. **`TimeoutError` explicitly excluded from transport errors**
   - Reasoning: On Python 3.11+, `TimeoutError` inherits from `OSError`. Treating it as a transport error would evict the session (destroying state like a Playwright browser) and retry — exactly the state-loss bug this feature was built to prevent.
   - This was a real bug found during implementation.

5. **Timeout covers session creation + tool call**
   - Reasoning: `_get_or_create_session()` is inside the `asyncio.timeout()` context. If a server never starts or the MCP handshake hangs, it times out rather than blocking indefinitely. For reused sessions, the dict lookup is instant so timeout effectively only covers `call_tool()`.
   - This was a code review finding — the initial implementation had session creation outside the timeout.

### Technical Debt Incurred

- **Thread safety of `_ensure_started()`**: Uses `_loop is not None` check without a lock. Safe under current sequential PocketFlow execution, but would need a lock if Task 39 (parallel nodes) is implemented.
- **`_is_transport_error` catches `OSError` broadly**: Includes `FileNotFoundError`, `PermissionError`. Retrying these once is harmless but noisy. Could be narrowed to network-specific subclasses.

## Unexpected Discoveries

### Gotchas Encountered

1. **Python 3.11 `TimeoutError` inheritance change**: `TimeoutError` became an `OSError` subclass in Python 3.11. The initial `_TRANSPORT_ERRORS = (BrokenPipeError, ConnectionError, OSError)` tuple matched `TimeoutError` via `OSError`, causing timeouts to trigger session eviction. Fix: explicit `isinstance(exc, TimeoutError)` check before `isinstance(exc, _TRANSPORT_ERRORS)`.

2. **`asyncio.timeout()` doesn't exist on Python 3.10**: Initial code used `asyncio.timeout()` unconditionally. Fix: `getattr(asyncio, "timeout", None)` with `asyncio.wait_for()` fallback for 3.10.

3. **`concurrent.futures.TimeoutError` is a separate class on Python 3.10**: The `future.result(timeout=...)` timeout raises `concurrent.futures.TimeoutError`, not `builtins.TimeoutError`, on Python 3.10. Fix: catch both in the `except` clause.

4. **`AsyncExitStack` LIFO cleanup order matters for devnull**: The devnull file (for stderr suppression) must be closed AFTER `stdio_client` exits (which terminates the subprocess). `AsyncExitStack` closes in LIFO order: `ClientSession` → `stdio_client` → devnull. This is correct but non-obvious.

## Patterns Established

### Reusable Patterns

1. **Shared store infrastructure injection** (`__dunder_key__` pattern):
   ```python
   # In _initialize_shared_store():
   shared_store["__mcp_pool__"] = MCPConnectionPool()

   # In finally block:
   pool = shared_store.get("__mcp_pool__")
   if pool: pool.shutdown()
   ```
   This follows `__llm_calls__`, `__progress_callback__`. Future infrastructure objects (e.g., Task 39 parallel executor, Task 64 long-running MCP servers) should use the same pattern.

2. **Sync/async bridge via background thread**:
   ```python
   loop = asyncio.new_event_loop()
   thread = threading.Thread(target=loop.run_forever, daemon=True)
   thread.start()
   # Submit work:
   future = asyncio.run_coroutine_threadsafe(coro, loop)
   result = future.result(timeout=...)
   # Shutdown:
   loop.call_soon_threadsafe(loop.stop)
   thread.join()
   ```
   First use of this pattern in pflow. If Task 64 (long-running MCP servers) needs persistent async resources, reuse this approach.

3. **Per-resource `AsyncExitStack`** for independent lifecycle management of multiple async context managers that need selective cleanup.

## Future Considerations

### Extension Points

- **Task 39 (Parallel Nodes)**: Multiple threads calling `pool.call_tool()` concurrently. `run_coroutine_threadsafe()` is thread-safe; the background loop serializes coroutines. But `_ensure_started()` needs a lock for concurrent first-call scenarios.
- **Task 64 (Long-Running MCP Servers)**: The pool already keeps servers alive. Task 64 could extend this to persist across workflow runs (e.g., application-scoped pool instead of workflow-scoped).
- **Task 39 + Batch Mode**: `PflowBatchNode` creates shallow copies of the shared store. The pool object is shared by reference — correct for a connection pool, but verify thread safety of concurrent `call_tool()` calls.

### Scalability Concerns

- Server processes accumulate for the duration of a workflow. A workflow using 10 different MCP servers keeps 10 processes alive. For most workflows this is fine; for very long workflows with many servers, a timeout-based eviction could be added.

## AI Agent Guidance

### Quick Start for Related Tasks

1. Read `src/pflow/mcp/pool.py` first — it's self-contained (~310 lines)
2. Read `src/pflow/runtime/namespaced_store.py:40-90` to understand dunder key bypass
3. Read `src/pflow/execution/executor_service.py:130-200` for the lifecycle pattern
4. The test file `tests/test_mcp/test_connection_pool.py` has helper functions (`_make_async_cm`, `_make_mock_session`) reusable for any MCP-related test

### Common Pitfalls

- **Never treat `TimeoutError` as a transport error** — it destroys state on stateful servers. This is the exact bug this task was built to fix.
- **Always include session creation inside the timeout context** — otherwise a hung server blocks indefinitely.
- **`AsyncExitStack` cleanup is LIFO** — enter resources in dependency order (devnull → stdio_client → ClientSession), so cleanup happens in reverse.
- **Python 3.10 compat**: `asyncio.timeout()` doesn't exist. Always use `getattr(asyncio, "timeout", None)` with `wait_for()` fallback.

### Test-First Recommendations

When modifying MCP pool behavior:
1. Run `pytest tests/test_mcp/test_connection_pool.py -v` first
2. `test_pool_timeout_does_not_kill_session` is the most important regression test
3. `test_pool_session_reuse_same_server` validates the core feature
4. Always call `pool.shutdown()` in a `finally` block in tests to prevent thread leaks

---

*Generated from implementation context of Task 127*
