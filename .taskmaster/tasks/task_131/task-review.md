# Task 131 Review: Batch Error Handling + LLM Timeout Fixes

## Metadata
- Implementation Date: 2026-03-22
- Status: Completed

## Executive Summary

Fixed three interacting failures in batch + output_schema + error_handling workflows: (1) `continue` mode stopping the workflow via `"error"` action, (2) raw LLM responses lost on JSON parse failure, (3) LLM node hanging indefinitely with no timeout. The LLM node is now the last external-calling node to get a timeout, completing the safety net across all node types.

## Implementation Overview

### What Was Built

Four fixes shipped, two deferred:

| Fix | What | Status |
|-----|------|--------|
| A | Batch `continue` mode returns `"default"` + pushes warning → DEGRADED status | Shipped |
| B | JSONDecodeError caught in LLMNode.post(), raw response preserved, usage captured | Shipped |
| C | LLM node timeout (default 120s) via ThreadPoolExecutor wrapper | Shipped |
| D | `timeout` field added to batch config schema (reserved for future use) | Shipped (schema only) |
| E | LLM cost tracking for failed items (finally block in batch) | Deferred — unnecessary after B+C |
| D impl | Batch per-item timeout consumption | Deferred — ThreadPoolExecutor cleanup blocks on timed-out threads |

### Deviations from Original Spec

**Fix E eliminated**: The original spec called for moving `_capture_item_llm_usage()` to a finally block. During implementation, realized Fixes B and C convert all exceptions into soft errors where `_run()` completes normally — so `_capture_item_llm_usage` already runs. Fix E only helps for an extremely narrow window of uncaught exceptions between usage write and `_run()` completion.

**Fix D partially deferred**: Batch per-item timeout via `future.result(timeout=N)` was planned but verification revealed `ThreadPoolExecutor.__exit__` calls `shutdown(wait=True)`, which hangs on timed-out threads. Python cannot kill running threads. Since all external nodes now have their own timeouts, the batch safety net is unnecessary.

**`post()` restructured, not just patched**: Instead of just adding a try/except for JSONDecodeError, the entire `post()` method was restructured to extract usage metrics BEFORE response parsing. This is cleaner and eliminates the need for Fix E.

## Files Modified/Created

### Core Changes

- `src/pflow/nodes/llm/llm.py` — Fix B + C. Restructured `post()` (usage before parsing, JSONDecodeError catch). Extracted `_call_llm()` from `exec()`. New `exec()` wraps in ThreadPoolExecutor with timeout. Added TimeoutError handling to `exec_fallback()`. Updated Interface docstring (timeout param, error output, actions).

- `src/pflow/runtime/wrappers/batch_node.py` — Fix A. Changed `post()` to return `"default"` in continue mode with errors. Pushes warning to `shared["__warnings__"]`.

- `src/pflow/core/ir_schema.py` — Fix D. Added `timeout` (type: number, minimum: 0) to `BATCH_CONFIG_SCHEMA["properties"]`.

### Test Files

- `tests/test_nodes/test_llm/test_llm.py` — 1 updated (`test_malformed_json_with_schema_soft_error`), 6 new (usage preservation, valid JSON regression, timeout default/custom/raises/normal)

- `tests/test_runtime/test_batch_node.py` — 4 unit tests (continue returns default, pushes warning, no warning on success, initializes dict) + 1 integration test (full wrapper chain with real LLMNode)

- `tests/test_core/test_ir_schema.py` — 2 new (timeout accepted as int and float)

### Critical Tests

- `test_batch_llm_output_schema_json_decode_error_continue` — THE integration test. Exercises real LLMNode → TemplateAwareNodeWrapper → NamespacedNodeWrapper → PflowBatchNode with one item returning invalid JSON. Only mocks the LLM model. Would have caught the original bug.

- `test_malformed_json_with_schema_soft_error` — Verifies the behavioral change from exception to soft error. Previously this test asserted `pytest.raises(json.JSONDecodeError)`.

- `test_timeout_raises_timeout_error` — Verifies timeout → retry → exec_fallback → error dict flow end-to-end.

## Architectural Decisions & Tradeoffs

### Key Decisions

**`continue` returns `"default"`, not `"error"`**: The `"error"` action from batch `post()` was defeating the purpose of `continue` mode. Users who want error-based branching can check `${node.error_count}` in a downstream code node. No new config option — that would be over-engineering.

**Catch JSONDecodeError in LLMNode.post(), not in batch wrapper**: The LLM node can preserve the raw response text (a local variable in `post()`). The batch wrapper only sees the exception message. Catching at the source gives better error data.

**ThreadPoolExecutor for timeout, not provider-specific options**: Provider timeout support is inconsistent (Gemini has it via Options, Anthropic doesn't). The Python Code node pattern (`pool.shutdown(wait=False, cancel_futures=True)`) is proven and node-agnostic.

**Batch per-item timeout deferred**: `ThreadPoolExecutor.__exit__` calls `shutdown(wait=True)`. A timed-out LLM thread blocks the entire batch on cleanup. This is a fundamental Python limitation — no mechanism to kill running threads. Node-level timeouts (Fix C) make this unnecessary.

### Technical Debt

- **Orphan threads on timeout**: When `exec()` times out, the underlying LLM API call thread continues running until the provider SDK's own timeout or process exit. This is the same accepted pattern as the Python Code node. The thread holds a reference to `prep_res` but doesn't modify shared state.

- **Registry cache invalidation**: The `~/.pflow/registry.json` file caches Interface metadata at scan time. Adding a new param requires re-scanning (or deleting the cache). This is an existing issue, not new debt.

## Unexpected Discoveries

### Gotchas

**Metadata extractor regex splits on commas in descriptions**: Interface docstring `(optional, default: 120)` caused the extractor to parse `default: 120)` as a separate param. Fixed by using `(default: 120)` without comma. Other nodes use this pattern already but it's not documented.

**Ruff removes unused imports between edits**: Adding imports before using them triggers ruff's auto-fix removal. Must ensure imports are used in the same edit or apply all changes atomically.

**Trace 193321 used `fail_fast`, not `continue`**: The bug report claimed both traces used `continue`, but trace analysis revealed the first used `fail_fast` (default). This led to different failure modes — `fail_fast` loses all successful results because `post()` never runs.

**The hang wasn't rate limiting**: User initially suspected rate limits for the 6+ minute hang. Investigation showed `llm-gemini` passes `timeout=None` to httpx, meaning infinite wait. Not rate limiting — a stalled HTTP connection.

### Edge Cases

- **`fail_fast` parallel mode loses ALL results**: When one item fails with `fail_fast`, `_exec_parallel()` raises before `post()` runs. All successful results (already computed, costing API time and money) are discarded. Not fixed in this task but documented as a future improvement.

## Patterns Established

### Reusable Patterns

**Node timeout via ThreadPoolExecutor** (follow `python_code.py:324-335`):
```python
pool = ThreadPoolExecutor(max_workers=1)
future = pool.submit(self._call_method, args)
try:
    return future.result(timeout=timeout)
except FuturesTimeoutError:
    raise TimeoutError(f"... timed out after {timeout}s ...") from None
finally:
    pool.shutdown(wait=False, cancel_futures=True)
```
IMPORTANT: Do NOT use `with ThreadPoolExecutor` — its `__exit__` calls `shutdown(wait=True)`.

**Soft error in node `post()`**: Write error to shared store, return `"error"` action. The batch handler's `_extract_error()` detects the `"error"` key in the namespaced result dict.

**Warning for DEGRADED status**: `shared["__warnings__"][node_id] = message_str`. Only triggers DEGRADED when workflow completes without `"error"` action.

### Anti-Patterns to Avoid

- **Commas in Interface docstring descriptions**: The metadata extractor regex splits on them. Use semicolons or separate parentheticals.
- **Batch per-item timeout via `future.result(timeout=N)`**: The ThreadPoolExecutor's `__exit__` blocks until all threads finish, including timed-out ones. Use node-level timeouts instead.

## Breaking Changes

### Behavioral Changes

- **Batch `continue` mode**: Previously returned `"error"` action (stopping workflow). Now returns `"default"` with warning (DEGRADED status). Workflows that wired `on-error` edges from batch nodes in `continue` mode will no longer follow those edges.

- **LLM node with output_schema + invalid JSON**: Previously raised `json.JSONDecodeError` (crashing the node). Now returns `"error"` action with raw response preserved in `shared["response"]`. The existing test `test_malformed_json_with_schema_raises` was renamed and updated.

- **LLM node timeout**: New default 120s timeout on all LLM calls. Workflows with legitimately slow LLM calls (>120s) need `timeout: 300` (or higher) in their LLM node params.

## AI Agent Guidance

### Quick Start for Related Tasks

Read these files first:
1. `src/pflow/pocketflow/__init__.py` — Node lifecycle (prep → _exec with retry → exec_fallback → post)
2. `src/pflow/runtime/wrappers/batch_node.py` — Batch wrapper chain and error handling
3. `src/pflow/nodes/llm/llm.py` — LLM node with timeout and JSONDecodeError handling
4. `src/pflow/runtime/wrappers/CLAUDE.md` — Wrapper application order and interception chain

### Common Pitfalls

1. **`_extract_error()` checks the namespace dict, not the action string**: The batch handler ignores the return value of `inner_node._run()`. It reads `item_shared.get(self.node_id)` and checks for an `"error"` key.

2. **`exec_fallback()` returns a dict, not raises**: After all retries exhaust, PocketFlow calls `exec_fallback()` which returns an error dict. `post()` then detects `status: "error"` and handles it. The exception does NOT propagate.

3. **ThreadPoolExecutor `__exit__` blocks**: Always use manual `pool.shutdown(wait=False)` in a finally block, never `with ThreadPoolExecutor(...)`.

4. **Registry cache**: After modifying a node's Interface docstring, the `~/.pflow/registry.json` cache must be refreshed. Delete it or run a workflow (which triggers auto-discovery).

### Test-First Recommendations

When modifying batch error handling or LLM node post-processing:
1. Run `test_batch_llm_output_schema_json_decode_error_continue` first — it's the integration test that catches interaction bugs
2. Run `test_malformed_json_with_schema_soft_error` — it verifies the JSONDecodeError → soft error conversion
3. Run the full batch test suite: `uv run pytest tests/test_runtime/test_batch_node.py -v`

---

*Generated from implementation context of Task 131*
