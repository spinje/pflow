# Task 131 Implementation Progress Log

## 2026-03-22 ~19:00 - Investigation Starts

User reported batch + output_schema + error_handling: continue failing in a chorus generation pipeline. Launched parallel pflow-codebase-searcher agents to trace:
1. Batch error handling code path
2. output_schema JSON parsing in LLM node
3. Trace files from actual failures

## 2026-03-22 ~19:30 - Root Cause Identified

Three interacting issues found, not one:

**Issue 1**: `PflowBatchNode.post()` returns `"error"` action in continue mode (batch_node.py:858-860). Flow stops because no `on-error` edge exists. User sees "Workflow failed with action: error".

**Issue 2**: `json.loads()` in `LLMNode.post()` (llm.py:328) has no try/except. Raw response lost on parse failure. Comment says "constrained decoding should guarantee valid JSON" — but it doesn't.

**Issue 3**: LLM node is the ONLY external-calling node without a timeout. All others (shell, HTTP, MCP, Claude Code, Python Code) have configurable timeouts (default 30s).

Key finding from trace analysis:
- Trace 193321: `fail_fast` mode (default). 29/30 items succeeded, exception re-raised, `post()` never ran, **all 29 results lost**.
- Trace 195830: `continue` mode actually worked — all items processed, results written, but workflow stopped at `"error"` action.

💡 Insight: `error_handling: continue` IS catching per-item exceptions correctly. The bug is in the RETURN VALUE from `post()`, not in the exception handling.

## 2026-03-22 ~20:00 - User Reports Live Hang

User ran the workflow and saw it hang at `score-choruses 26/34` for 6+ minutes. Not a crash — a stalled API connection to Gemini.

Later progressed to 33/34 ✗ — so it wasn't truly hung, just very slow API responses. But confirmed: no timeout mechanism means a stalled connection blocks forever.

💡 Insight: The `llm-gemini` plugin passes `timeout=None` to httpx, which means infinite wait. Anthropic SDK has 600s default. Both can cause very long hangs.

## 2026-03-22 ~20:15 - Assumption Verification Phase

Launched 6 parallel pflow-codebase-searcher agents to verify assumptions before planning:

1. **`_extract_error()` + namespacing** ✅ — Chain works: LLM writes `shared["error"]` → NamespacedNodeWrapper redirects to `item_shared[node_id]["error"]` → batch reads via `_extract_error(result.get("error"))`.

2. **`__warnings__` format** ✅ — Format is `{node_id: message_str}`. Triggers DEGRADED only when workflow completes without `"error"` action AND dict is non-empty. Perfect for our case since Fix A changes batch to return `"default"`.

3. **Existing timeout patterns** ✅ — Python Code node uses ThreadPoolExecutor + `pool.shutdown(wait=False, cancel_futures=True)`. This is our template.

4. **Batch config schema** ⚠️ — `BATCH_CONFIG_SCHEMA` has `additionalProperties: false`. Must add `timeout` to accepted properties.

5. **PocketFlow retry + TimeoutError** ✅ — `TimeoutError` → `OSError` → `Exception`. PocketFlow catches it, retries 3x. `concurrent.futures.TimeoutError` is same class as `builtins.TimeoutError` since Python 3.3.

6. **ThreadPoolExecutor cleanup** ⚠️ CRITICAL — `__exit__` calls `shutdown(wait=True)`. A timed-out thread blocks cleanup. Python can't kill running threads. This means batch-level per-item timeout (`future.result(timeout=N)`) would cause the batch to hang on cleanup.

💡 Decision: Fix D (batch per-item timeout) DEFERRED. Fix C (node-level timeout) makes it unnecessary — every external node now has its own timeout.

## 2026-03-22 ~20:30 - Task Created

Created `.taskmaster/tasks/task_131/task-131.md` with all findings. Updated after verification phase to reflect deferred Fix D.

## 2026-03-22 ~20:45 - Planning Phase

Entered plan mode. Launched targeted pflow-codebase-searcher agents for implementation details:
- Python Code node timeout pattern (exact code)
- IR schema batch config (exact dict)
- LLM node full exec/prep/post code

Plan agent designed implementation order: D → B → C → A. Fix E (cost tracking) deferred — Fixes B and C make it unnecessary.

💡 Insight: Fix B restructures `post()` so usage extraction runs BEFORE response parsing. This ensures usage is always captured regardless of parse outcome, eliminating the need for Fix E.

## 2026-03-22 ~21:00 - Implementation

### Fix D (schema) + Fix A (batch node) — parallel background agents
Launched `code-implementer` agents in parallel for independent files.

### Fix B + C (LLM node) — direct implementation

**Linter gotcha**: First attempt failed — added imports (`ThreadPoolExecutor`, `FuturesTimeoutError`) before using them. Ruff's auto-fix removed unused imports between edits. Solution: apply all changes and ensure imports are used before linter runs.

Changes to `src/pflow/nodes/llm/llm.py`:
1. Added `concurrent.futures` imports
2. Updated Interface docstring (timeout param, error write, actions)
3. Added `timeout` to `prep()` return dict
4. Extracted `_call_llm()` private method from `exec()`
5. Rewrote `exec()` with ThreadPoolExecutor timeout wrapper
6. Added `TimeoutError` branch to `exec_fallback()` (first check)
7. Restructured `post()`: moved usage extraction before response parsing
8. Added try/except for `json.JSONDecodeError` in `post()` with raw response preservation

### Tests — test-writer-fixer agent
7 tests written:
- Fix B: `test_malformed_json_with_schema_soft_error` (updated), `test_malformed_json_preserves_usage`, `test_valid_json_with_schema_unchanged`
- Fix C: `test_timeout_default_is_120`, `test_timeout_custom_value`, `test_timeout_raises_timeout_error`, `test_normal_execution_within_timeout`

All 56 LLM tests pass, 4242 total tests pass, `make check` clean.

## 2026-03-22 ~21:15 - Manual Verification

Created 3 test workflows in `scratchpads/output-schema-batch-error-handling/`:

**test-fix-a-continue-default.pflow.md**: Batch with one item raising ValueError + continue mode.
- First attempt: code node set `error` variable but batch didn't detect it (need `raise`, not variable assignment)
- ✅ Second attempt with `raise ValueError(...)`: Workflow completed with DEGRADED status, 2/3 succeeded, downstream node executed

**test-fix-b-json-parse-error.pflow.md**: Batch LLM with output_schema + timeout.
- ❌ First attempt: `unknown parameter 'timeout'` — registry cache stale
- Fixed by deleting `~/.pflow/registry.json` to force re-scan
- ✅ All 3 items scored with structured output, timeout accepted

**test-fix-c-timeout.pflow.md**: Simple LLM call with timeout.
- ✅ LLM responded in 0.7s with `timeout: 10`

⚠️ Registry cache issue: The `timeout` param was in the Interface docstring and metadata extractor, but the validator uses `~/.pflow/registry.json` which caches metadata at scan time. Deleting the cache forced a re-scan.

⚠️ Metadata extractor parsing bug: Initial Interface docstring used `(optional, default: 120)` — the comma caused the extractor to parse `default: 120)` as a separate param. Fixed by using `(default: 120)` without comma, matching existing patterns.

## 2026-03-22 ~21:30 - Integration Test

Identified one high-value gap: no test exercises the full wrapper chain (LLMNode → TemplateAwareNodeWrapper → NamespacedNodeWrapper → PflowBatchNode) with a real LLMNode and mocked model.

Wrote `TestBatchLLMOutputSchemaIntegration::test_batch_llm_output_schema_json_decode_error_continue`:
- 3 items: 2 valid JSON, 1 invalid
- Verifies: action="default", warning pushed, 2 successes + 1 error, raw response preserved, usage captured for all items
- Only mocks the LLM model itself — all wrappers are real

✅ 4243 tests pass, `make check` clean.

## Final State

### Files Modified (production)
| File | Fix | Lines changed |
|------|-----|---------------|
| `src/pflow/nodes/llm/llm.py` | B + C | ~60 (restructure post, extract _call_llm, timeout wrapper, exec_fallback) |
| `src/pflow/runtime/wrappers/batch_node.py` | A | ~8 (replace "error" return with "default" + warning) |
| `src/pflow/core/ir_schema.py` | D | ~5 (add timeout to batch schema) |

### Files Modified (tests)
| File | Tests |
|------|-------|
| `tests/test_nodes/test_llm/test_llm.py` | 1 updated + 6 new |
| `tests/test_runtime/test_batch_node.py` | 5 new (4 unit + 1 integration) |
| `tests/test_core/test_ir_schema.py` | 2 new |

### Key Decisions
1. **Fix E deferred**: Fixes B and C convert exceptions to soft errors where `_run()` completes normally, so `_capture_item_llm_usage` runs without changes.
2. **Fix D deferred**: Batch per-item timeout can't work with ThreadPoolExecutor cleanup semantics. Node-level timeouts are the primary protection.
3. **`post()` restructured (not just patched)**: Moved usage extraction before response parsing. Cleaner separation of concerns and eliminates Fix E need.
4. **Follow Python Code node pattern exactly**: ThreadPoolExecutor + `pool.shutdown(wait=False, cancel_futures=True)` for timeout wrapper.
5. **Interface docstring: no commas in descriptions**: Metadata extractor regex splits on commas. Use semicolons or separate parentheticals.
