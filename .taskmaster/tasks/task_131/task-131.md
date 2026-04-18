# Task 131: Batch Error Handling + LLM Timeout Fixes

## Description

Fix multiple interacting issues where batch processing with `output_schema` and `error_handling: continue` fails to be fault-tolerant: the workflow stops despite `continue`, raw LLM responses are lost on parse failure, and stalled LLM API calls hang indefinitely with no timeout.

## Status

done

## Completed

2026-03-22

## Priority

high

## Problem

Discovered while running a batch LLM workflow (scoring 30-51 items with `output_schema` for structured JSON output). Five interacting failures:

1. **Workflow stops despite `error_handling: continue`**: The batch processes all items and catches per-item exceptions correctly, but `PflowBatchNode.post()` returns `"error"` action. If the workflow has no `on-error` edge (which is the common case), the flow stops. User sees `"Workflow failed with action: error"` even though all items were processed and partial results exist.

2. **Raw LLM response lost on parse failure**: `json.loads()` in `LLMNode.post()` (line 328) has no try/except. When it fails, the raw response text (local variable) is lost. The error record only contains the parse error message, not what the LLM actually returned. Users can't fall back to text parsing.

3. **No LLM node timeout**: The LLM node is the **only** external-calling node without a timeout. All others (shell, HTTP, MCP, Claude Code, Python Code) have configurable timeouts (default 30s). The `llm` library's `model.prompt()` is called without any timeout. Provider SDK defaults vary: Anthropic has 600s read timeout, Gemini with `timeout=None` means infinite wait. A stalled API connection hangs the entire workflow forever.

4. **No batch per-item timeout**: `PflowBatchNode._exec_single()` has no timeout mechanism. In parallel mode, `future.result()` is called without a timeout. A single hung item blocks the entire batch.

5. **LLM cost lost for failed items**: `_capture_item_llm_usage()` runs after `_run()` in the try block. If `_run()` raises, the LLM API call's cost is never tracked (the call likely succeeded but parsing failed).

### Evidence

Traces at `~/.pflow/debug/`:
- `workflow-trace-test-chorus-grouped-20260322-193321.json`: `fail_fast` mode (default). 29/30 items completed, one `JSONDecodeError`. Exception re-raised, `post()` never ran, **all 29 results lost**.
- `workflow-trace-test-chorus-grouped-20260322-195830.json`: `continue` mode. All items processed, results written, but workflow stopped at `"error"` action.
- Live run (2026-03-22 ~20:30): Item hung for 6+ minutes at `score-choruses 33/34` — stalled Gemini API connection with no timeout.

### Reproduction

Minimal repro workflow: `scratchpads/output-schema-batch-error-handling/repro-minimal.pflow.md`
Full bug report: `scratchpads/output-schema-batch-error-handling/BUG-REPORT.md`

## Solution

Three code changes + schema update + comprehensive tests:

### Fix A: `continue` mode returns `"default"` action + warning

Change `PflowBatchNode.post()` to return `"default"` (not `"error"`) when `error_handling: continue` and errors exist. Push a warning to `shared["__warnings__"]` so the executor reports `DEGRADED` status. The workflow continues normally; downstream nodes can check `${node.error_count}`.

### Fix B: Catch `JSONDecodeError` in `LLMNode.post()`, preserve raw response

Wrap the `json.loads()` call in `LLMNode.post()` with try/except. On failure, store the raw response text in `shared["response"]` and set `shared["error"]` with the parse error. Return `"error"` action. This converts a hard exception into a soft error that the batch handler's `_extract_error()` picks up naturally — no retry waste, raw response preserved for fallback parsing.

### Fix C: LLM node timeout (default 120s)

Add a `timeout` parameter to `LLMNode` (like every other external node). Default 120s. Follow the Python Code node pattern: wrap the `model.prompt()` + `response.text()` calls in a `ThreadPoolExecutor` with `future.result(timeout=N)` and `pool.shutdown(wait=False, cancel_futures=True)`. On timeout, raise `TimeoutError` which PocketFlow retries normally.

### Fix D: Batch per-item timeout — DEFERRED

~~Add a `timeout` config option to batch processing.~~

**Deferred.** Verification revealed that `ThreadPoolExecutor.__exit__` calls `shutdown(wait=True)`, which blocks until all threads complete — including timed-out ones. This means `future.result(timeout=N)` detects the timeout but the batch then hangs on cleanup. Python provides no mechanism to kill running threads.

Fix C (node-level timeout) makes Fix D unnecessary: every external node type (shell, HTTP, MCP, Claude Code, Python Code, and now LLM) has its own timeout. The batch doesn't need a redundant safety net. Schema support for batch `timeout` is added for future use but not consumed.

## Design Decisions

- **`continue` returns `"default"`, not `"error"`**: Users who want error-based branching can check `${node.error_count}` in a downstream code node. Returning `"error"` defeats the purpose of `continue` mode. No need for a new config option — that's over-engineering.

- **Catch JSONDecodeError in `LLMNode.post()`, not in batch wrapper**: Catching in the LLM node is more precise — it can preserve the raw response text (which is a local variable in `post()`). The batch wrapper only sees the exception message, not the raw data.

- **LLM timeout via thread wrapper, not provider-specific options**: Provider timeout support is inconsistent (Gemini has it, Anthropic doesn't). A thread-based timeout in `exec()` is universal and works regardless of the `llm` plugin. Follow the Python Code node pattern (`ThreadPoolExecutor` + `pool.shutdown(wait=False, cancel_futures=True)`).

- **Batch per-item timeout deferred**: `ThreadPoolExecutor.__exit__` calls `shutdown(wait=True)`, blocking until all threads complete. A timed-out LLM call would hang the batch on cleanup. Since all external nodes now have their own timeouts, the batch doesn't need a redundant safety net.

- **Warning + DEGRADED status**: The executor checks `shared["__warnings__"]` (format: `{node_id: message_str}`). When batch returns `"default"` (Fix A) and warnings are populated, the executor reports `DEGRADED`. This was verified — DEGRADED only fires when the workflow completes without an `"error"` action AND warnings exist, which is exactly what Fix A produces.

## Dependencies

None.

## Requirements

### Fix A: Batch continue mode action
- `PflowBatchNode.post()` returns `"default"` when `error_handling: continue`, even with errors
- A warning is added to `shared["__warnings__"]` with error count summary
- Results, errors, error_count are all written to shared store (already works)
- Downstream nodes execute normally after a batch with errors
- Executor reports `DEGRADED` status (not `FAILED`) when batch had errors in continue mode

### Fix B: JSONDecodeError handling in LLM node
- `json.loads()` failure in `LLMNode.post()` does not raise an exception
- Raw LLM response text is preserved in `shared["response"]` on parse failure
- Parse error stored in `shared["error"]` with the JSONDecodeError message
- Returns `"error"` action (detected by batch `_extract_error()`)
- No PocketFlow retry for parse failures (already the case — `post()` is outside retry loop)
- The existing test `test_malformed_json_with_schema_raises` must be updated (behavior changes from exception to soft error)

### Fix C: LLM node timeout
- New optional parameter `timeout` (int/float, seconds, default 120)
- Timeout covers the entire `model.prompt()` + `response.text()` call
- On timeout: raises `TimeoutError` → PocketFlow retries (up to 3 times) → `exec_fallback` returns error dict
- Works regardless of `llm` provider plugin (not dependent on provider SDK timeout support)
- Configurable per-node in workflow files: `- timeout: 60`

### Fix D: Schema update (batch timeout field — deferred consumption)
- Add `timeout` to `BATCH_CONFIG_SCHEMA["properties"]` in `ir_schema.py` (currently `additionalProperties: false` rejects unknown fields)
- Field is accepted but not consumed by `PflowBatchNode` — reserved for future implementation
- No functional behavior change

### Fix E: LLM cost tracking for failed items
- Move `_capture_item_llm_usage()` call to a finally block (or equivalent) so it runs even when `_run()` raises
- Failed items that made successful API calls have their cost tracked

## Implementation Notes

### Key files to modify
- `src/pflow/runtime/wrappers/batch_node.py`: Fix A (post method, ~3 lines), Fix E (finally block for cost capture)
- `src/pflow/nodes/llm/llm.py`: Fix B (post method, ~6 lines), Fix C (timeout in exec, ~20 lines)
- `src/pflow/core/ir_schema.py`: Fix D (add `timeout` to `BATCH_CONFIG_SCHEMA`)

### Fix C implementation detail — follow Python Code node pattern
```python
# In LLMNode.exec():
pool = ThreadPoolExecutor(max_workers=1)
future = pool.submit(self._call_model, prep_res)
try:
    return future.result(timeout=timeout)
except concurrent.futures.TimeoutError:
    raise TimeoutError(f"LLM call timed out after {timeout}s")
finally:
    pool.shutdown(wait=False, cancel_futures=True)  # Don't wait for orphan
```
Orphan thread continues running but returns promptly. The thread will eventually complete via the provider SDK's own timeout or on process exit. This is the same pattern used by Python Code node (`python_code.py:327-335`).

### Verified: _extract_error + namespacing interaction
LLM node writes `shared["error"]` → NamespacedNodeWrapper redirects to `item_shared[node_id]["error"]` → batch reads `item_shared.get(node_id)` → `_extract_error(result)` checks `result.get("error")`. **Chain works end-to-end.** Confirmed by existing tests: `test_continue_records_error_in_result`, `test_error_in_result_returns_error`.

### Verified: __warnings__ format
Format is `{node_id: message_str}`. Written at `instrumented_wrapper.py:229`. Read at `executor_service.py:219` as `shared_store.get("__warnings__", {})`. Non-empty dict → DEGRADED status (only when workflow completes without `"error"` action).

### Verified: TimeoutError + PocketFlow retry
`TimeoutError` → `OSError` → `Exception`. PocketFlow's `except Exception` catches it, retries up to 3 times. `concurrent.futures.TimeoutError` is the same class as `builtins.TimeoutError` since Python 3.3. LLM node's `exec_fallback` handles it via generic else branch with clear message.

### Interaction between Fix B and Fix A
With Fix B, JSONDecodeError becomes a soft error (node returns `"error"` action, writes error to shared). The batch handler's `_extract_error()` detects the `"error"` key in the result dict and records it as a batch item error. Then Fix A ensures the batch returns `"default"` in continue mode, and the workflow proceeds.

### Edge case: `fail_fast` parallel mode result preservation
Currently, `fail_fast` in parallel mode raises from `_exec_parallel()` before `post()` runs, losing all successful results. Consider adding a `_write_partial_results()` call before the re-raise. This is a nice-to-have improvement, not blocking for this task.

## Verification

### Tests for Fix A
- Batch with `error_handling: continue` + item failures → returns `"default"` action
- Warning added to `shared["__warnings__"]` with error count
- Downstream nodes in a flow execute after batch with errors
- Executor reports `DEGRADED` status
- Batch with `error_handling: fail_fast` still raises (unchanged behavior)

### Tests for Fix B
- `LLMNode` with `output_schema` + malformed JSON → `shared["response"]` has raw text, `shared["error"]` has parse message
- Returns `"error"` action, no exception raised
- Batch + LLM with `output_schema` + malformed JSON + `error_handling: continue` → item recorded in errors, raw response preserved, other items unaffected
- Update `test_malformed_json_with_schema_raises` to test new soft-error behavior

### Tests for Fix C
- LLM node with timeout + slow model → `TimeoutError` raised
- LLM node with timeout + fast model → normal execution
- LLM node timeout + retry → retries on timeout, eventually `exec_fallback`
- Default timeout is 120s

### Tests for Fix D
- `timeout` field accepted in batch config without validation error (schema test)

### Integration test
- Full batch LLM node with `output_schema` + `error_handling: continue` + one malformed response → workflow completes with DEGRADED status, successful items in results, failed item in errors with raw response

## References

- Bug report: `scratchpads/output-schema-batch-error-handling/BUG-REPORT.md`
- Minimal repro: `scratchpads/output-schema-batch-error-handling/repro-minimal.pflow.md`
- Batch node: `src/pflow/runtime/wrappers/batch_node.py` (post at line 858, _exec_single at 372, _exec_parallel at 721)
- LLM node: `src/pflow/nodes/llm/llm.py` (post at line 324, exec at 252, exec_fallback at 371)
- PocketFlow retry: `src/pflow/pocketflow/__init__.py` (Node._exec at line 67)
- Instrumented wrapper: `src/pflow/runtime/wrappers/instrumented_wrapper.py` (_run at line 627)
- Executor status logic: `src/pflow/execution/executor_service.py` (line 215)
- Existing test: `tests/test_nodes/test_llm/test_llm.py:930` (test_malformed_json_with_schema_raises)
- Existing batch tests: `tests/test_runtime/test_batch_node.py`
- Trace files: `~/.pflow/debug/workflow-trace-test-chorus-grouped-20260322-*.json`
