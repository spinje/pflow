# Task 127: MCP Server Connection Pooling — Progress Log

## Implementation Steps

1. Create `MCPConnectionPool` class in `src/pflow/mcp/pool.py`
2. Modify `MCPNode` to use pool when available (fallback to `asyncio.run()`)
3. Modify `executor_service.py` to create pool in shared store and shut down in finally
4. Update `src/pflow/mcp/__init__.py` exports
5. Write comprehensive tests
6. Run `make test` and `make check`

---

## [2026-03-13] — Context Gathering & Code Analysis

Read the three key files before starting:
- `src/pflow/nodes/mcp/node.py` — MCPNode with `asyncio.run()` per exec
- `src/pflow/execution/executor_service.py` — where shared store is initialized
- `src/pflow/mcp/__init__.py` — existing exports

Confirmed root cause: `MCPNode.exec()` at line 187 calls `asyncio.run(self._exec_async(prep_res))`, creating a new event loop per call. Inside `_exec_async_stdio()`, the server subprocess lives inside `async with stdio_client(params)` which kills it on context exit.

Verified MCP SDK imports available: `ClientSession`, `StdioServerParameters`, `stdio_client`, `streamablehttp_client`, `CallToolResult`.

## [2026-03-13] — Step 1: Created MCPConnectionPool

Created `src/pflow/mcp/pool.py` (~130 lines).

Key design decisions:
- **Background daemon thread** running `loop.run_forever()` — persistent asyncio event loop
- **Lazy startup**: thread created on first `call_tool()`, not at `__init__()`. Zero cost for workflows with no MCP nodes.
- **Per-server `AsyncExitStack`**: each server gets its own stack managing `stdio_client` + `ClientSession` contexts. Independent cleanup.
- **Sync `call_tool()`** submits work via `asyncio.run_coroutine_threadsafe()`, blocks on `future.result()`
- **Transport support**: stdio (via `StdioServerParameters`) and HTTP (via `streamablehttp_client`)
- **Crash recovery**: on `BrokenPipeError`, `ConnectionError`, `OSError` → evict dead session, create new one, retry once
- **`_DevNull` helper class**: async context manager wrapping `os.devnull` for stderr suppression, managed by per-server exit stack

## [2026-03-13] — Steps 2-4: Integration (parallel)

All three integration changes done simultaneously:

**MCPNode (`node.py`):**
- `prep()`: reads `shared.get("__mcp_pool__")`, adds to return dict
- `exec()`: if pool exists → `pool.call_tool()` + `_extract_result()`. Otherwise → `asyncio.run()` fallback
- Removed TODO comment at line 70 ("Future improvement would be to cache and reuse server connections")
- Updated class docstring: added "Connection Pooling" section

**executor_service.py:**
- `_initialize_shared_store()`: adds `shared_store["__mcp_pool__"] = MCPConnectionPool()`
- `execute_workflow()` finally block: `mcp_pool.shutdown()` with exception safety, placed before metrics recording

**`__init__.py`:** Added `MCPConnectionPool` to exports.

## [2026-03-13] — Step 5: Tests

Delegated to `test-writer-fixer` subagent. Created `tests/test_mcp/test_connection_pool.py` with 24 tests across 7 classes.

Pool unit tests (mock at SDK boundary): lifecycle (4), session management (2), error handling (3), HTTP transport (1), `_is_transport_error` helper (8).

Integration tests (mock at pool boundary): MCPNode pool integration (3), executor service lifecycle (3).

All 24 tests passed in 0.38s.

## [2026-03-13] — Step 6: Full Suite Verification

- `make test`: 3788 passed, 485 skipped in 7.29s
- `make check`: all passing (ruff, mypy, deptry)

## [2026-03-13] — Bug Found: TimeoutError Classified as Transport Error

### Discovery

During post-implementation review, asked: "are there HIGH VALUE tests that could catch actual bugs?"

Traced the code path for a tool timeout:
1. `_do_call()` wraps `session.call_tool()` in `asyncio.timeout(timeout)`
2. Timeout fires → raises `asyncio.TimeoutError` (which IS `builtins.TimeoutError` on Python 3.11+)
3. `_call_tool_async()` catches `BaseException` → checks `_is_transport_error(exc)`
4. `TimeoutError` is a **subclass of `OSError`** on Python 3.11+
5. `OSError` is in `_TRANSPORT_ERRORS` → `_is_transport_error()` returns `True`
6. Pool **evicts the session** (kills server subprocess) and **retries**

### Impact

This is the exact state-loss scenario the pool was built to prevent. A slow Playwright `browser_navigate` (35s on a slow page with 30s timeout) would:
1. Kill the browser session (destroying all navigation state)
2. Start a brand new browser
3. Retry the same slow call (likely timing out again)

The user would see: timeout → fresh browser on `about:blank` → timeout again.

### Fix

Added `TimeoutError` exclusion at the top of `_is_transport_error()`:

```python
def _is_transport_error(exc: BaseException) -> bool:
    # TimeoutError is an OSError subclass on Python 3.11+, but it's NOT
    # a transport error — the server is alive, just slow.
    if isinstance(exc, TimeoutError):
        return False
    if isinstance(exc, _TRANSPORT_ERRORS):
        return True
    ...
```

### Tests Added

- `test_timeout_error_is_not_transport_error` — unit test for `_is_transport_error`
- `test_exception_group_with_only_timeout_is_not_transport` — ExceptionGroup wrapping timeout
- `test_pool_timeout_does_not_kill_session` — **the critical scenario**: first call times out, second call must reuse the same session (not start a fresh server). Verifies `mock_session_cls.call_count == 1` after both calls.

### Additional Fixes

- `BaseExceptionGroup` → `hasattr(exc, "exceptions")` in pool.py (Python 3.10 compat, ruff target py39)
- `assert self._loop is not None` → proper `RuntimeError` raise (ruff S101)
- `ExceptionGroup` tests marked `skipif not _HAS_EXCEPTION_GROUP` with `# noqa: F821`
- Existing `test_timeout_error_is_transport_error` renamed and assertion inverted

### Verification

- 26 tests pass (was 24, added 2)
- `make check`: all clean
- `make test`: 3790 passed, 485 skipped

## Final State

| File | Action | Lines |
|------|--------|-------|
| `src/pflow/mcp/pool.py` | **Created** | ~135 |
| `src/pflow/nodes/mcp/node.py` | Modified | ~20 changed |
| `src/pflow/execution/executor_service.py` | Modified | ~10 changed |
| `src/pflow/mcp/__init__.py` | Modified | 2 changed |
| `tests/test_mcp/test_connection_pool.py` | **Created** | ~310 |

## [2026-03-13] — Code Review Fixes

External review identified 6 issues. Items #2 and #3 were already fixed during the self-review above. Applied fixes for the remaining 4:

### #1 — `asyncio.timeout()` crashes on Python 3.10 (MUST FIX)

`asyncio.timeout()` was added in Python 3.11. Project requires `>=3.10`. `_do_call()` used it directly, which would crash with `AttributeError` on 3.10.

**Fix:** Added `getattr(asyncio, "timeout", None)` fallback to `asyncio.wait_for()`, matching the pattern already used in `MCPNode._exec_async_stdio()` (node.py:264-271).

### #4 — `concurrent.futures.TimeoutError` uncaught on Python 3.10 (SHOULD FIX)

`future.result(timeout=timeout+5)` raises `concurrent.futures.TimeoutError`, which is a separate class from `builtins.TimeoutError` on Python 3.10 (unified on 3.11+). The `except TimeoutError:` clause would not catch it on 3.10.

**Fix:** Changed to `except (TimeoutError, concurrent.futures.TimeoutError):`.

### #5 — `_shutting_down` flag never reset (SHOULD FIX)

After `shutdown()`, `_shutting_down = True` and `_loop = None`. If `call_tool()` were called again, `_ensure_started()` would create a new loop, but `shutdown()` would return early because `_shutting_down` was still `True`. The new pool could never be cleaned up.

**Fix:** Reset `self._shutting_down = False` in `_ensure_started()`.

### #6 — Stale `_sessions`/`_stacks` if `_shutdown_async` fails (SHOULD FIX)

If `_shutdown_async()` raises (caught by `except Exception`), `_sessions` and `_stacks` would retain stale entries pointing to dead sessions.

**Fix:** Added `self._sessions.clear()` and `self._stacks.clear()` to the `shutdown()` finally block.

### Verification

- 26 tests pass
- `make check`: all clean (ruff, mypy, deptry)
- `make test`: 3790 passed, 485 skipped

## [2026-03-13] — Second Code Review Fix

### Timeout doesn't cover session creation (BUG)

`_do_call()` called `_get_or_create_session()` *outside* the timeout context. If a server binary doesn't exist or `session.initialize()` hangs (bad MCP handshake), the async task blocks indefinitely. The sync `future.result(timeout=timeout+5)` safety net would eventually fire, but that's 35 seconds of waiting for what should be a fast failure.

Contrast with the standalone `MCPNode._exec_async_stdio()` which wraps the entire operation (server start + init + call) in the timeout.

**Fix:** Moved `_get_or_create_session()` inside the timeout context. For reused sessions it's a dict lookup (instant), so the timeout effectively only covers `call_tool` on subsequent calls — same as before, but with safety on first call.

```python
# Before (broken):
session = await self._get_or_create_session(...)  # NOT timed
async with timeout_context(timeout):
    return await session.call_tool(tool, arguments)

# After (fixed):
async with timeout_context(timeout):
    session = await self._get_or_create_session(...)  # timed on first call
    return await session.call_tool(tool, arguments)
```

### Verification

- 26 tests pass
- `make check`: all clean

## Final State

| File | Action | Lines |
|------|--------|-------|
| `src/pflow/mcp/pool.py` | **Created** | ~155 |
| `src/pflow/nodes/mcp/node.py` | Modified | ~20 changed |
| `src/pflow/execution/executor_service.py` | Modified | ~10 changed |
| `src/pflow/mcp/__init__.py` | Modified | 2 changed |
| `tests/test_mcp/test_connection_pool.py` | **Created** | ~320 |

## [2026-03-13] — PR Review Fixes

PR #94 reviewed by claude[bot]. Two warnings addressed:

### Warning 1 — Thread safety of `_ensure_started()` (applied)

TOCTOU race: two threads could both see `self._loop is None` and create duplicate event loops/threads. While PocketFlow is sequential today, this is a latent bug for Task 39 (parallelism).

**Fix:** Added `self._lock = threading.Lock()` in `__init__` with double-check locking in `_ensure_started()`. Also set `self._loop` last (after thread starts) so the fast-path check only passes when the thread is actually running.

### Warning 2 — `_DevNull` class simplification (applied)

Replaced 15-line `_DevNull` class + `_open_devnull()` factory with 6-line `@asynccontextmanager`. Functionally identical, more idiomatic.

### Skipped suggestions

- INFO log for session creation → left as DEBUG (pool should be invisible to users)
- `_shutting_down` guard in `call_tool()` → impossible scenario in current architecture (`shutdown()` runs in `finally` after `flow.run()` returns)

### Manual verification

Ran the bug reproduction workflow (`test-mcp-lifecycle.pflow.md`): navigate to example.com → screenshot. Screenshot shows "Example Domain" content (not blank page). Screenshot step took 196ms (reused session) vs navigate's 1641ms (includes server startup).

### Verification

- 26 tests pass
- `make check`: all clean

## Key Insights

1. **Python's `TimeoutError` inheriting from `OSError` is a footgun.** On Python 3.11+, `isinstance(TimeoutError(), OSError)` is `True`. Any code that catches `OSError` for "I/O failed" semantics will accidentally catch timeouts too. Always check `TimeoutError` first.

2. **The test-writer subagent missed this bug** because it rationalized the behavior: "a stuck server might recover after reconnection." This is technically true for transport errors, but wrong for timeouts — the server isn't stuck, it's just slow. The session is still alive. The critical insight requires understanding the *purpose* of the pool (preserve state), not just the mechanics.

3. **`hasattr(exc, "exceptions")` is the right way to detect ExceptionGroups** on Python 3.10+ without importing the backport. Cleaner than version checks or conditional imports.

4. **Python 3.10 compat requires vigilance across three APIs**: `asyncio.timeout()` (3.11+), `BaseExceptionGroup` (3.11+), and `concurrent.futures.TimeoutError` being a separate class from `builtins.TimeoutError` (unified in 3.11+). All three bit us in the same file.
