# Task 127: MCP Server Connection Pooling Across Workflow Steps

## Description

Keep MCP server processes alive for the duration of a workflow run so that stateful MCP servers (like Playwright) preserve state between steps. Currently each MCP node spawns a fresh server subprocess, making multi-step MCP interactions impossible.

## Status
done

## Completed
2026-03-13

## Priority

high

## Problem

pflow starts a **fresh MCP server instance for each MCP node** in a workflow. The server subprocess is created inside an `async with stdio_client()` block in `MCPNode._exec_async_stdio()` (node.py:210-271), and killed when the block exits. Each `MCPNode.exec()` call creates a new event loop via `asyncio.run()`, so nothing survives between nodes.

This makes any multi-step stateful MCP interaction silently fail:
- **Playwright**: `browser_navigate` loads a page successfully, but `browser_take_screenshot` in the next step gets a fresh browser at `about:blank`. Screenshot is blank. No errors reported.
- **Database MCP**: Connect + query would fail because the connection is gone by the second step.
- Any 2+ step MCP workflow for the same server is broken.

**Why this is high severity**: It's a **silent failure**. All nodes report success. The workflow completes. But output data is wrong (blank screenshots, stale state). Users can't tell something went wrong.

### Reproduction

```bash
# Minimal repro: navigate then screenshot — screenshot captures about:blank
pflow test-mcp-lifecycle.pflow.md url="https://example.com" output_path="/tmp/test.png"
```

Full bug report with traces: `scratchpads/mcp-server-lifecycle-bug/bug-report.md`

## Solution

Introduce an `MCPConnectionPool` that manages MCP server processes on a background event loop thread. Servers start lazily on first use and stay alive until the workflow completes. All MCP nodes for the same server reuse the existing connection.

### Architecture

```
WorkflowExecutorService.execute_workflow()
  ├─ _initialize_shared_store()
  │    └─ shared["__mcp_pool__"] = MCPConnectionPool()
  ├─ flow.run(shared)
  │    ├─ MCP Node 1 (playwright-navigate)
  │    │    prep(): reads pool from shared, adds to prep_res
  │    │    exec(): pool.call_tool("playwright", "navigate", args)
  │    │           → lazily starts playwright server on bg loop
  │    │           → returns result synchronously
  │    ├─ Shell Node (other work)
  │    └─ MCP Node 2 (playwright-screenshot)
  │         exec(): pool.call_tool("playwright", "screenshot", args)
  │                → reuses existing session, state preserved
  └─ finally:
       shared["__mcp_pool__"].shutdown()  # kills all servers, stops bg thread
```

### Sync/Async Bridge

The core technical challenge: PocketFlow is synchronous, MCP SDK is async (anyio-based), and `asyncio.run()` per node destroys the event loop.

Solution: A **background thread running a persistent asyncio event loop**. `MCPConnectionPool` wraps the MCP SDK's `ClientSessionGroup` (which already handles multi-server session management with `AsyncExitStack`). Synchronous node code calls `asyncio.run_coroutine_threadsafe()` to submit work to the background loop and blocks on the `Future.result()`.

## Design Decisions

- **Lazy server startup**: Start each MCP server on first `call_tool()`, not eagerly at workflow start. Simpler, avoids wasting resources on servers that might not be needed (conditional branches).
- **Pool location**: `src/pflow/mcp/pool.py` — the `mcp/` package is the MCP infrastructure layer, fits alongside `manager.py` and `discovery.py`.
- **Crash recovery**: If a server process dies mid-workflow, detect on next `call_tool()` (broken pipe), evict dead session, auto-restart, retry once. Log a warning.
- **`pflow registry run` unchanged**: Single-shot command, pool adds overhead for no benefit. Keep current per-call behavior.
- **Fallback behavior**: If no pool in shared store (e.g., `registry run`), MCPNode falls back to current `asyncio.run()` per-call behavior. Zero breaking changes.
- **Server identity key**: Server name from `~/.pflow/mcp-servers.json` — it maps 1:1 to a config entry.
- **Leverage `ClientSessionGroup`**: The MCP SDK already has a built-in multi-session manager that uses `AsyncExitStack` to keep `stdio_client` contexts alive independently. We wrap it rather than reinvent it.

## Dependencies

None — all required infrastructure exists.

## Implementation Notes

### New code

**`src/pflow/mcp/pool.py` — `MCPConnectionPool` class (~100-150 lines)**
- Manages a background `threading.Thread` running an asyncio event loop
- Wraps MCP SDK's `ClientSessionGroup` for multi-server session management
- Exposes synchronous `call_tool(server, tool, args, config, timeout)` that uses `asyncio.run_coroutine_threadsafe()`
- `shutdown()` method: closes all sessions (kills server subprocesses), stops event loop, joins thread
- Thread-safe: pool state accessed via `run_coroutine_threadsafe`, no shared mutable state

### Modified files

**`src/pflow/nodes/mcp/node.py` — MCPNode (~15 lines changed)**
- `prep()`: Read `shared.get("__mcp_pool__")`, add to `prep_res`
- `exec()`: If pool exists, use `pool.call_tool()` instead of `asyncio.run(self._exec_async())`. Else fall back to current behavior.

**`src/pflow/execution/executor_service.py` (~10 lines changed)**
- `_initialize_shared_store()`: Create `MCPConnectionPool`, store as `shared["__mcp_pool__"]`
- `finally` block (line 130): Call `shared["__mcp_pool__"].shutdown()`

### Key integration details

- **Shared store access**: `__mcp_pool__` uses dunder convention, which bypasses `NamespacedSharedStore` namespacing — all nodes see it regardless of namespace.
- **Existing pattern**: Follows `__progress_callback__` and `__llm_calls__` patterns — infrastructure objects injected before `flow.run()` and accessible to all nodes.
- **HTTP transport**: HTTP MCP servers (external, already running) also benefit from session reuse, though their lifecycle isn't managed by pflow. The pool handles both stdio and HTTP transports.
- **Batch processing**: Shallow copies of shared store in batch mode share the same pool reference, which is correct — the pool is thread-safe and designed for concurrent use.

### Files to read before implementing

- `src/pflow/nodes/mcp/node.py` — current MCPNode implementation
- `src/pflow/execution/executor_service.py` — injection and cleanup points
- `src/pflow/runtime/namespaced_store.py` — dunder key bypass mechanism
- `.venv/lib/python3.13/site-packages/mcp/client/session_group.py` — SDK's `ClientSessionGroup`
- `.venv/lib/python3.13/site-packages/mcp/client/stdio/__init__.py` — `stdio_client` lifecycle
- `scratchpads/mcp-server-lifecycle-bug/bug-report.md` — full bug report with traces

## Verification

### Functional tests

- **State persists between steps**: Two MCP nodes for the same server share state (navigate then screenshot captures the navigated page, not `about:blank`)
- **Different servers are independent**: MCP nodes for different servers get separate sessions
- **Cleanup on success**: All MCP servers shut down after successful workflow completion
- **Cleanup on failure**: All MCP servers shut down if a workflow fails mid-execution
- **Crash recovery**: If an MCP server crashes mid-workflow, next node auto-restarts it
- **Fallback without pool**: MCPNode works normally when no `__mcp_pool__` in shared store (`registry run` path)
- **HTTP transport**: HTTP MCP sessions are reused across nodes

### Manual verification

```bash
# The original reproduction case should now work:
pflow test-mcp-lifecycle.pflow.md url="https://example.com" output_path="/tmp/test.png"
# Screenshot should show example.com content, not blank page

# Verify cleanup: no orphaned MCP server processes after workflow completes
pflow test-mcp-lifecycle.pflow.md url="https://example.com" output_path="/tmp/test.png"
ps aux | grep playwright  # Should show no playwright processes
```

### Acceptance criteria

1. Multi-step MCP workflows produce correct results (Playwright navigate+screenshot is the canonical test)
2. No orphaned server processes after workflow completion (success or failure)
3. No breaking changes — single MCP node workflows, `registry run`, and stateless MCP servers all work identically
4. Performance: Server startup cost paid once per server per workflow, not once per node
