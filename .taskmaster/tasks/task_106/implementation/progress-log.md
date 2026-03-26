# Task 106: Workflow Iteration Cache — Implementation Progress Log

## Phase 1: Template Wrapper Decomposition — COMPLETED
Extracted `resolve_templates()` from `TemplateAwareNodeWrapper._run()`.

- Extracted 150-line resolution block into standalone `resolve_templates(shared) -> dict` method
- `resolve_templates()` is a pure query: returns merged_params (static + resolved template params), sets `self.last_resolutions` for trace capture, no other instance state mutation
- `_run()` calls `resolve_templates()` internally on every execution
- 8 tests written in `tests/test_runtime/test_template_wrapper_resolve.py`

**Key insight**: The extraction is side-effect-free in strict mode — only writes `self.last_resolutions` (instance attr read by trace system) and optionally `shared["__template_errors__"]` in permissive mode error paths.

**Decision**: `resolve_templates()` is intentionally a public method (not underscore-prefixed) because the instrumented wrapper needs to call it externally for cache key computation.

## Phase 2: Enhanced Config Hash — COMPLETED
Enhanced `_compute_node_config()` in `InstrumentedNodeWrapper`.

- Template params (raw `${...}` templates) now included in config under `template_params` key
- Batch semantic config (`items_template`, `item_alias`, `error_handling`, `max_retries`) included under `batch` key
- `_source_line` keys filtered from params — these are markdown parser metadata (injected at `compiler.py:269`) that change when lines move but don't affect node behavior
- Operational batch config (`parallel`, `max_concurrent`, `retry_wait`) deliberately **excluded** — these affect performance/ordering but not the output values
- 11 tests written in `tests/test_runtime/test_instrumented_wrapper_config.py`

**Decision**: Filter pattern uses `k.endswith("_source_line")` — matches the compiler's injection pattern `_<key>_source_line`. Broader than strictly necessary but safe since user params should never end with `_source_line`.

## Phase 3: Cache Storage Module — COMPLETED
Created `src/pflow/runtime/cache.py` with SQLite-backed `MemoizationCache`.

- SQLite with WAL journal mode for concurrent read/write safety
- zlib compression for output storage (BLOB column) to keep DB size manageable
- TTL-based eviction (default 24h), checked on `get()` (expired entries deleted inline) and periodically on `put()` (every 50 writes)
- `read_enabled=False` mode for `--no-cache` — writes still happen (seeds cache for next run), reads return None
- `compute_node_cache_key()` and `compute_batch_cache_key()` as standalone functions (not methods) — keep cache key logic decoupled from storage
- `_make_serializable()` handles dunder keys (replaced with type string), non-primitive objects (replaced with `<module.ClassName>`), recursive dict/list traversal
- All operations catch `sqlite3.Error` for graceful degradation — cache failures never crash the workflow
- Connection per call (not per instance) for thread safety in parallel batch
- 18 tests written in `tests/test_runtime/test_cache.py`

**Decision**: Duplicated `_make_serializable` rather than extracting from `instrumented_wrapper.py`. The two implementations serve different contexts (config hashing vs cache key computation) and coupling them would create cross-module dependency for a simple utility. If they diverge, each can evolve independently.

**Decision**: No cache size limit (only TTL eviction). For the iteration loop use case (10-20 runs of the same workflow), the DB stays small. A future task could add max entry count if needed.

## Phase 4: Memoization Integration — COMPLETED
Added memoization cache checks to `InstrumentedNodeWrapper._run()`.

- Cache initialized in `executor_service._initialize_shared_store()` as `shared["__memoization_cache__"]`
- Check happens after loop guard, before in-process cache check (in-process cache is for within-run resume, memoization is cross-run)
- Non-batch: calls `tw.resolve_templates(shared)` to get merged_params, computes key from `config_hash + merged_params`
- Batch: resolves items template from shared store, computes key from `config_hash + semantic_batch_config + resolved_items`
- On hit: restores `shared[node_id] = cached_output`, records in `__execution__` state for checkpoint consistency, fires `_handle_cached_execution()`
- On miss: executes normally, stores result via `memo_cache.put()` after successful execution
- Skipped for revisited nodes (`visit_count > 1`) — memoization is for cross-run caching, not loop caching. Without this, looping nodes would return first iteration's cached result forever.
- No cache write on `"error"` result — errors should always re-execute
- 8 tests written in `tests/test_runtime/test_memoization_integration.py`

**Decision**: Extracted helper methods to manage complexity in `_run()`:
- `_enforce_loop_guard()` — visit counting + cache invalidation for revisited nodes
- `_check_memo_cache()` — returns `(hit, result, cache_key)` tuple
- `_write_memo_cache()` — stores result after successful execution
- `_compute_memo_cache_key()` — dispatches to non-batch or batch key computation
- `_compute_batch_memo_key()` — resolves items template and builds batch-specific key

This kept `_run()` complexity under the C901 limit (10) while maintaining readability.

**Decision**: `_compute_memo_cache_key()` catches all exceptions (`except Exception`) with debug logging, not a narrow exception list. Template resolution can fail in many ways (missing keys, type errors, JSON parse failures). The cache should never prevent execution — if we can't compute a key, we skip memoization and execute normally.

## Phase 5: --no-cache CLI Flag — COMPLETED
Added `--cache/--no-cache` click option to `workflow_command`.

- Flows through `ctx.obj["cache"]` → `enhanced_params["__no_cache__"]` → `_initialize_shared_store()`
- Popped from `execution_params` before shared store update to prevent template resolution context pollution
- `MemoizationCache(read_enabled=not no_cache)` — writes still happen for next run

**Decision**: `--cache/--no-cache` uses Click's boolean flag pair syntax. Default is `--cache` (True). This means `pflow workflow.pflow.md` enables caching with zero configuration.

## Phase 6: --only CLI Flag — COMPLETED
Added `--only` click option to `workflow_command`.

- Flows through `ctx.obj["only_node"]` → `enhanced_params["__only_node__"]` → compiler
- Filtered from shared store update in `_initialize_shared_store()` using dict comprehension (not popped — compiler needs it in `initial_params`)
- `_apply_only_node_stop()` validates target exists, monkey-patches `flow.get_next_node` to return None after target
- Error message lists available nodes on invalid target

**Subtle decision**: `__only_node__` is NOT popped from `execution_params` (unlike `__no_cache__`). It must remain for the compiler to read from `initial_params`. But it IS filtered from the shared store update to avoid polluting template resolution context. This asymmetry between the two flags required careful ordering in `_initialize_shared_store()`.

**Decision**: Extracted `_apply_only_node_stop()` as a standalone function (not a method) since it operates on the Flow object, not the compiler. Also extracted `_apply_run_hooks()` from `compile_ir_to_flow()` to bring the function under C901 complexity limit.

## Phase 7: key=value Override Verification — COMPLETED
Verified that CLI overrides work correctly with cache by design:
- Overrides flow into `initial_params` → `_build_resolution_context()` adds them with higher priority than shared store → different resolved values → different cache key → cache miss for affected nodes
- Covered in integration tests (`test_key_value_override_cache_interaction`)

## Phase 8: Integration Tests — COMPLETED
Created `tests/test_runtime/test_cache_integration.py` with 11 end-to-end tests:
1. Full cache cycle (run → all cached on second run)
2. Config change invalidation
3. Template input change invalidation
4. --no-cache flag behavior
5. --only flag stops after target
6. --only + cache combination
7. key=value override cache interaction
8. Error node not cached
9. Upstream cached, downstream executes
10. Cache TTL expiry
11. Stale `_resolved` regression test (loop scenario) — added after code review

**Decision**: Tests build real PocketFlow `Flow` objects with full wrapper chains rather than mocking. This catches integration issues that unit tests miss (e.g., the stale `_resolved` bug manifested only through the copy.copy behavior in `Flow._orch()`).

## Phase 9: Final Checks — COMPLETED

### Test isolation bug
`MemoizationCache` was using real `~/.pflow/cache/cache.db` in tests. The `isolate_pflow_config` autouse fixture patches `Registry`, `SettingsManager`, etc. to use temp paths — but didn't know about the new cache. This caused the `test_data_flows_between_nodes` e2e test to fail: both nodes showed `[cached]` because a previous test run had already cached them to the real DB.

**Fix**: Added `MemoizationCache` monkey-patch to `isolate_pflow_config` in `tests/conftest.py`. Follows the same pattern as the existing manager patches (capture original `__init__`, replace with version that defaults to temp path).

### C901 complexity
Adding memoization to `_run()` and `--only` to `compile_ir_to_flow()` pushed both over the C901 limit (10). Fixed by extracting helper methods/functions:
- `_run()`: `_enforce_loop_guard()`, `_check_memo_cache()`, `_write_memo_cache()`
- `compile_ir_to_flow()`: `_apply_run_hooks()`, `_apply_only_node_stop()`

### mypy errors
- `_enforce_loop_guard` returned `Any` from shared store dict access — fixed with type annotation at binding site
- Extracted functions lost the `type: ignore[method-assign]` comments that were on the monkey-patches — removed since `flow` is typed as `Any`

## Phase 10: Manual Testing — COMPLETED
All 8 manual test scenarios passed using real `.pflow.md` workflow files via CLI:
- Basic cache cycle, --no-cache, --only, template invalidation, config change invalidation, --only+cache, regression check, invalid --only target
- `[cached]` indicators display correctly in terminal with `<1ms` timing
- Cache invalidation is granular: only changed node re-executes

## Phase 11: Code Review Wave 1 — COMPLETED
Two parallel reviews (source + tests).

### Critical bug found: stale `_resolved` on memo cache hit in loops
The review identified a real correctness bug in the `_resolved` caching mechanism:
1. `_compute_memo_cache_key()` calls `resolve_templates()` which sets `self._resolved`
2. On memo cache HIT, `_check_memo_cache()` returns early — `_resolved` never consumed
3. `TemplateAwareNodeWrapper` instance is **shared** across `copy.copy()` iterations in PocketFlow's `_orch` loop (because `NamespacedNodeWrapper` has no `__copy__` — default shallow copy shares `_inner_node` reference)
4. On next loop iteration (visit > 1), memoization skipped, but stale `_resolved` from step 1 is consumed by `_run()` — using first iteration's resolved params instead of fresh resolution

### Other findings
- Warning: `__memoization_cache__` not in `_PROPAGATED_KEYS` — sub-workflows got no memoization
- Suggestions: bare `except Exception` without logging, unnecessary intermediate variable, duplicated `_make_serializable` (disputed — intentional separation)

## Phase 12: Review Fixes — COMPLETED
Applied fixes:
1. Initially: clear `_resolved` after cache key computation
2. Add `__memoization_cache__` to `_PROPAGATED_KEYS` in `workflow_executor.py`
3. Debug logging for bare except in batch memo key
4. Clean up `_enforce_loop_guard` annotation
5. Autouse fixtures for test state cleanup in integration tests
6. Update stale conftest comment

## Phase 13: Code Review Wave 2 + Architectural Simplification — COMPLETED

### Wave 2 review
Confirmed all fixes correct. Identified the same missing regression test. No new critical issues.

### Key architectural decision: Remove `_resolved` entirely
After the wave 2 review, we stepped back and questioned whether patching the `_resolved` stale state bug was the right approach, or whether the `_resolved` mechanism itself was the problem.

**Analysis** (verified by 3 parallel codebase searcher agents):

1. **The "optimization" was already dead.** After the stale-state fix (clearing `_resolved` after key computation), `_resolved` was always `None` when `_run()` executed. The "fast path" in `_run()` (`if self._resolved is not None`) was never taken. Double resolution was already happening on every cache miss.

2. **`resolve_templates()` is cheap.** Sub-millisecond: shallow dict copy of shared store + regex string substitution per template param. Dwarfed by actual node execution (LLM/HTTP/shell). No I/O, no network, fully deterministic.

3. **Nothing modifies shared store between the two resolution points.** The window between `_compute_memo_cache_key()` and `TemplateAwareNodeWrapper._run()` contains only: in-process cache check (reads `__execution__` metadata), namespace initialization (creates empty `shared[node_id] = {}`), and progress callback (display-only). None of these modify template-resolvable keys.

4. **`_resolved` is instance state creating temporal coupling.** It couples two methods (`resolve_templates()` sets it, `_run()` consumes it) across a wrapper chain where `copy.copy()` shares the underlying instance. This coupling is the root cause of a class of stale-state bugs.

5. **Removing `_resolved` eliminates the bug class entirely.** No stale state possible, no clearing logic needed, no fragility for future refactors. The regression test becomes a behavioral test (verify fresh resolution in loops) rather than testing lifecycle management of an internal field.

**What was removed:**
- `_resolved` field from `__init__`, `wrapper_attrs`, `resolve_templates()`, `_run()`
- Clearing lines from `_compute_memo_cache_key()` (both success and exception paths)
- 3 tests that specifically tested `_resolved` lifecycle (`test_resolve_templates_caches_on_resolved`, `test_resolved_cleared_after_run`, `test_resolved_cleared_after_run_without_prior_resolve`)
- Empty `TestResolveTemplatesCaching` class

**What was kept:**
- `resolve_templates()` as a public method (needed by instrumented wrapper for cache key computation)
- `self.last_resolutions` (needed by trace system — this is the ONLY instance state `resolve_templates()` sets)
- The loop regression test (`test_stale_resolved_regression_in_loop`) — still valuable as a behavioral test

**Final test delta:** 4479 tests pass (net -2 from the 4481 after Phase 9: removed 3 `_resolved` tests, added 1 regression test, added autouse fixtures)

## Summary of Subtle Decisions

### Architecture
- **Memoization, not cascade invalidation**: Cache keys are content-addressed (hash of config + resolved inputs). No need to track dependencies between nodes — if inputs change, the hash changes, cache misses.
- **Whole-batch caching for MVP**: Batch nodes are cached as a complete unit (all items together), not per-item. Simpler, and per-item caching would require a different key structure.
- **No sub-workflow-level caching**: Sub-workflows compile fresh each run (reading current file contents). Individual nodes inside sub-workflows are cached via the propagated `__memoization_cache__` instance. This handles the "edit a sub-workflow file" invalidation case naturally.
- **Side-effecting nodes ARE cached**: `write-file`, `shell` nodes with deterministic config+inputs will return cached output on second run (file won't be re-written, command won't re-execute). This is the correct behavior for the iteration loop use case. `--no-cache` provides an escape hatch.

### Implementation
- **`_make_serializable` duplication is intentional**: Two implementations serve different contexts (config hashing in instrumented wrapper vs cache key computation in cache module). Coupling them for a simple utility adds cross-module dependency with no real benefit.
- **`__only_node__` filtering vs `__no_cache__` popping**: Asymmetric handling because `__only_node__` must survive in `execution_params` for the compiler to read, while `__no_cache__` is consumed by `_initialize_shared_store()` and must not reach template resolution context.
- **`resolve_templates()` is pure (no `_resolved`)**: After the review cycle, we chose to eliminate instance state caching entirely. The double resolution on cache miss is negligible cost, and removing the temporal coupling eliminates a class of stale-state bugs. This is a case where "boring and obvious" (always resolve fresh) beats "clever optimization" (cache + lifecycle management).
- **Exception handling breadth**: `_compute_memo_cache_key()` and `_compute_batch_memo_key()` both catch `Exception` broadly (with debug logging). Template resolution can fail in many unanticipated ways. The cache should never prevent execution.
- **Cache DB path isolation**: The `isolate_pflow_config` conftest fixture patches `MemoizationCache.__init__` to use temp paths. Without this, tests pollute `~/.pflow/cache/cache.db` and cause cross-test cache hits (discovered when `test_data_flows_between_nodes` failed with both nodes showing `[cached]`).

## Phase 14: Data Integrity Review — COMPLETED

Independent review of all staged changes against the original design discussion. Verified every integration point, then asked: "what high-value test could catch actual bugs?"

### Bug found: `_make_serializable()` used for output STORAGE in `put()`

`MemoizationCache.put()` was calling `json.dumps(_make_serializable(output), ...)` to serialize the node output before writing to SQLite. The `_make_serializable()` function replaces `__dunder__` key values with type-name strings (e.g., `{"__meta__": {"model": "gpt-4"}}` → `{"__meta__": "<dict>"}`). This is correct for **hashing** (where you need a deterministic representation, not the actual value) but causes **data loss** for **storage** (where you need to faithfully reconstruct the original dict on read).

**Why it existed**: `_make_serializable()` was the only available serializer when `cache.py` was written, and it handles non-JSON-serializable objects gracefully. The distinction between "serialize for hashing" vs "serialize for storage" wasn't considered — both paths used the same function.

**Why it matters**: If a node ever produces output with `__dunder__` keys (e.g., structured LLM output with a `__metadata__` field), the cached version would lose the actual values. On cache hit, downstream template resolution would receive `"<dict>"` instead of the real data. In practice this hasn't triggered because standard pflow nodes don't use dunder keys in their namespaced output (dunder keys bypass the namespace to root level), but it's a correctness issue that would be very hard to debug if it ever did trigger.

**Fix**: Changed `put()` to use `json.dumps(output, sort_keys=True, default=str)` — preserves all data, handles non-serializable types via `str()` conversion (same graceful degradation, no data loss for JSON-native types). `_make_serializable()` remains in `cache.py` for its intended purpose: deterministic hashing in `compute_node_cache_key()` and `compute_batch_cache_key()`.

### Missing test found: data integrity through cache → template resolution

None of the existing 56 tests had a downstream node reading a cached upstream's output via `${upstream.field}`. Every test used independent static params — node B never referenced `${A.result}`. This is the core use case of the entire feature.

**Added**: `test_cached_output_flows_through_template_resolution` — a 3-node chain:
- A (`RichOutputNode`) produces a dict with str, int, float, bool, None, list, and nested dict values
- B (`ConcatNode`) reads `${A.text}` and `${A.count}` via template resolution
- C (`ConcatNode`) reads `${B.result}` via template resolution

Run 1: all execute. Run 2: all served from cache. Test verifies:
1. No nodes re-executed (cache hit for all three)
2. All three outputs identical to run 1 (dict equality)
3. Type preservation through the round-trip (str stays str, int stays int, float stays float, bool stays bool, None stays None, list stays list, nested dict traversable)

This single test exercises the full chain: execution → `_make_serializable` for key → `json.dumps` for storage → zlib compress → SQLite write → SQLite read → zlib decompress → `json.loads` → restore to `shared[node_id]` → `_build_resolution_context(dict(shared))` → `TemplateResolver.resolve_template("${A.text}", context)` → downstream execution with resolved value.

## Summary of Subtle Decisions

### Architecture
- **Memoization, not cascade invalidation**: Cache keys are content-addressed (hash of config + resolved inputs). No need to track dependencies between nodes — if inputs change, the hash changes, cache misses.
- **Whole-batch caching for MVP**: Batch nodes are cached as a complete unit (all items together), not per-item. Simpler, and per-item caching would require a different key structure.
- **No sub-workflow-level caching**: Sub-workflows compile fresh each run (reading current file contents from disk). Individual nodes inside sub-workflows are cached via the propagated `__memoization_cache__` instance. This handles the "edit a prompt file referenced by a sub-workflow" invalidation case naturally — the file content is inlined into node params at compile time, so the config hash changes when the file changes.
- **Side-effecting nodes ARE cached**: `write-file`, `shell` nodes with deterministic config+inputs will return cached output on second run (file won't be re-written, command won't re-execute). This is the correct behavior for the iteration loop use case. `--no-cache` provides an escape hatch.
- **SQLite, not files**: Concurrent-safe (WAL mode handles parallel batch threads writing simultaneously), TTL eviction is one SQL statement, zero external dependencies (stdlib `sqlite3`), single file (`~/.pflow/cache/cache.db`), aligns with future Task 133 (unified per-node storage — add trace columns to existing table, not a rewrite).

### Implementation
- **`_make_serializable` duplication is intentional**: Two implementations serve different contexts (config hashing in instrumented wrapper vs cache key computation in cache module). Coupling them for a simple utility adds cross-module dependency with no real benefit.
- **`_make_serializable` for hashing only, `default=str` for storage**: The cache module has two serialization paths. `_make_serializable()` + `_deterministic_json()` is used for cache KEY computation (deterministic, lossy for dunder keys — acceptable because keys only need to be comparable, not reconstructable). `json.dumps(output, default=str)` is used for output STORAGE (faithful, lossless for JSON-native types — required because cached output must be identical to live output).
- **`__only_node__` filtering vs `__no_cache__` popping**: Asymmetric handling because `__only_node__` must survive in `execution_params` for the compiler to read, while `__no_cache__` is consumed by `_initialize_shared_store()` and must not reach template resolution context.
- **`resolve_templates()` is pure (no `_resolved`)**: After the review cycle, we chose to eliminate instance state caching entirely. The double resolution on cache miss is negligible cost, and removing the temporal coupling eliminates a class of stale-state bugs. This is a case where "boring and obvious" (always resolve fresh) beats "clever optimization" (cache + lifecycle management).
- **Exception handling breadth**: `_compute_memo_cache_key()` and `_compute_batch_memo_key()` both catch `Exception` broadly (with debug logging). Template resolution can fail in many unanticipated ways. The cache should never prevent execution.
- **Cache DB path isolation**: The `isolate_pflow_config` conftest fixture patches `MemoizationCache.__init__` to use temp paths. Without this, tests pollute `~/.pflow/cache/cache.db` and cause cross-test cache hits (discovered when `test_data_flows_between_nodes` failed with both nodes showing `[cached]`).
- **`resolve_templates(raw_shared)` is safe**: The instrumented wrapper calls `resolve_templates()` with the raw shared store (not the NamespacedSharedStore proxy). This produces identical resolution results because: (1) upstream node outputs are stored as `shared["node_id"] = {...}` in both raw and proxy views, (2) the current node's namespace is empty at resolution time (resolution happens before execution), (3) `initial_params` overlay is the same regardless of shared store type. Verified by tracing through `_build_resolution_context()`, `NamespacedSharedStore.keys()/items()`, and `TemplateResolver.resolve_value()`.
- **Batch and non-batch have different cache key paths**: For non-batch nodes, `_compute_memo_cache_key()` calls `resolve_templates()` on the inner template wrapper. For batch nodes, this would fail (batch-item templates like `${item.title}` don't exist outside the per-item loop), so `_compute_batch_memo_key()` resolves only the items list from the shared store and includes semantic batch config in the key. The two paths are dispatched by `_is_batch_node()`.

## Files Changed (Final)

| File | Action | Purpose |
|------|--------|---------|
| `src/pflow/runtime/cache.py` | **Created** | SQLite memoization cache module (313 lines) |
| `src/pflow/runtime/wrappers/instrumented_wrapper.py` | Modified | Memoization check, enhanced config hash, helper methods (+200 lines) |
| `src/pflow/runtime/wrappers/template_wrapper.py` | Modified | Extract `resolve_templates()`, simplify `_run()` (+45/-8 lines) |
| `src/pflow/runtime/compilation/compiler.py` | Modified | `--only` monkey-patch, extracted `_apply_run_hooks` and `_apply_only_node_stop` (+83/-20 lines) |
| `src/pflow/cli/main.py` | Modified | `--cache/--no-cache`, `--only` CLI options (+15 lines) |
| `src/pflow/execution/executor_service.py` | Modified | Initialize `__memoization_cache__`, filter internal params (+15/-3 lines) |
| `src/pflow/runtime/workflow_executor.py` | Modified | Add `__memoization_cache__` to `_PROPAGATED_KEYS` (+1 line) |
| `tests/conftest.py` | Modified | MemoizationCache test isolation patch (+16 lines) |
| `tests/test_runtime/test_template_wrapper_resolve.py` | **Created** | Template resolve tests (8 tests) |
| `tests/test_runtime/test_instrumented_wrapper_config.py` | **Created** | Enhanced config hash tests (11 tests) |
| `tests/test_runtime/test_cache.py` | **Created** | Cache storage module tests (18 tests) |
| `tests/test_runtime/test_memoization_integration.py` | **Created** | Memoization wrapper tests (8 tests) |
| `tests/test_runtime/test_cache_integration.py` | **Created** | End-to-end integration tests (12 tests) |

**Total: 57 new tests, 4480 all passing, `make check` clean.**

## CLAUDE.md Updates — COMPLETED
Updated 5 CLAUDE.md files documenting what agents need to know:

| File | What was added | Why |
|------|---------------|-----|
| `runtime/CLAUDE.md` | `cache.py` in file structure, `MemoizationCache` section (storage, key formula, TTL, test isolation, side-effecting nodes), `__memoization_cache__` in shared store keys, updated cache invalidation to cover both levels | Hard to discover: cache module exists, what the key includes, that side-effecting nodes ARE cached |
| `runtime/wrappers/CLAUDE.md` | Updated `_run()` interception chain with memoization steps, memoization helper methods, `resolve_templates()` as pure public method, `cache.py` cross-dependency, 3 new gotchas (shared template wrapper across copy.copy, memoization skip for loops, no instance state caching on template wrapper) | **Critical**: the shared `TemplateAwareNodeWrapper` across `copy.copy()` is the most unintuitive behavior. Future agents must not re-introduce instance state caching. |
| `runtime/compilation/CLAUDE.md` | `_apply_run_hooks()` and `_apply_only_node_stop()` extracted functions, `__only_node__` asymmetric handling | Easy to get wrong: `__only_node__` is filtered (not popped) because compiler needs it |
| `execution/CLAUDE.md` | Memoization cache creation and the asymmetric `__no_cache__` pop vs `__only_node__` filter | Easy to get wrong: the two internal flags flow differently through the same function |
| `cli/CLAUDE.md` | `--cache/--no-cache` and `--only` flags, `cache` and `only_node` context keys | Hard to find: new CLI options and how they flow to execution |

## Phase 15: Final Code Review (Review 5) — COMPLETED
Deep review of all staged changes. No critical issues. 7 cosmetic/documentation fixes applied:

1. **W2**: Updated `test_template_wrapper_resolve.py` module docstring — removed stale `_resolved` references
2. **W3**: Fixed `test_only_with_cache` docstring — B is cached, not "re-executes"
3. **W4**: Clarified `--only` help text — "Run workflow through this node then stop (caching still applies)"
4. **W1**: Added comment to `_write_memo_cache` documenting non-dict branch as dead code (namespace wrapper guarantees dict)
5. **S1**: Removed redundant `conn.commit()` after `executescript` (auto-commits per Python sqlite3 docs)
6. **S2**: Added comment to `_compute_batch_memo_key` noting parallel with `PflowBatchNode._resolve_items()`
7. **S3**: Added inline comment to `output_hash` column — reserved for Task 133 trace unification

## Phase 16: --only UX Fixes and Agent Polish — COMPLETED

Follow-up fixes addressing 6 issues discovered during final review of Task 106, then significantly redesigned through manual testing and design discussion about how `--only` output should work for AI agents.

### Issues Fixed (Original 6)

1. **`--only` + `## Outputs` → `OutputResolutionError`** (broken): `_apply_run_hooks` unconditionally called `populate_declared_outputs()`. When `--only` stopped early, downstream nodes in `## Outputs` hadn't executed → crash.
2. **`--only` output extraction returns nothing** (broken): Last IR node hasn't executed → `_extract_default_output()` fallback found nothing.
3. **Execution summary unclear about `--only`** (confusing): Downstream nodes showed as `not_executed` with no explanation.
4. **No aggregate cache stats in output** (missing): No way to see cached vs fresh count.
5. **Saved workflows excluded from caching** (spec update): Removed exclusion — cache keys are content-addressed.
6. **Cache DB init failure is silent** (minor): Upgraded `_init_db` failure from DEBUG to WARNING.

### Design Evolution

The `--only` output went through several design iterations. Documenting the reasoning because the final design is non-obvious.

**Attempt 1: Output promotion in compiler.** Promoted `shared[only_node]` → `shared["result"]` in `_apply_run_hooks`. Problem: three separate code paths resolve declared outputs (compiler, CLI text, JSON/MCP formatter). The plan only identified one. Manual testing revealed the other two still fired, producing warnings or empty results.

**Attempt 2: Bypass all declared outputs + promote to root.** Added `only_node` guards to all three declared-output paths. Fell through to auto-detection. Problem: the JSON `_find_auto_output` (success_formatter.py) was NOT namespace-aware — only checked root-level keys. Returned the entire namespace dict (including shell metadata like `command`, `exit_code`, `stderr`) as the `result` field. Text worked because its `_find_auto_output` (workflow_output.py) IS namespace-aware.

**Attempt 3: Extract meaningful key from namespace.** Created `_collect_only_node_outputs` / `_extract_only_node_output` to pick the "right" key from the namespace (`result` > `response` > `stdout` > `output`). Problem: we were guessing which key is relevant. For debugging, the agent needs everything. For clean output, we were picking wrong keys.

**Attempt 4: Full namespace dump.** Returned the entire namespace dict in JSON `result`. Problem: exposes internal data (resolved `command` with potentially sensitive template values, shell metadata). Conflicts with the `structure` mode design philosophy where agents see paths but must use `read-fields` for values.

**Final design (Attempt 5): No special `--only` output handling.**

Key insight from design discussion: `--only` is a debugging/iteration tool. The agent wants the primary output value immediately (text), and detailed debugging context through the existing `--report` system. The JSON `result` should use the same auto-detection as any workflow without matching declared outputs.

Changes:
- **Compiler**: `_apply_run_hooks` only stores `__execution__["only_node"]` metadata. No output promotion.
- **JSON/MCP path**: `_collect_outputs` skips declared outputs when `--only` active, falls through to `_find_auto_output` (now namespace-aware).
- **CLI text path**: `_handle_text_output` skips declared outputs when `--only` active, falls through to existing namespace-aware `_find_auto_output`.
- **Report integration**: `--only` + `--report` points the agent to the target node's report file for detailed inspection (resolved command, stdout, stderr, exit code, timing).

### Implementation Details

#### Compiler: `_apply_run_hooks` (`compiler.py`)

Extended `_apply_run_hooks(flow, ir_dict, only_node=None)`. When `only_node` is set:
1. Stores `shared["__execution__"]["only_node"] = only_node` — unconditionally (success or error) so display layer knows `--only` was active.
2. Skips `populate_declared_outputs()` — prevents `OutputResolutionError` from unresolved downstream outputs.

No output promotion. The display layer handles output extraction via namespace-aware auto-detection.

#### Namespace-aware JSON auto-detection (`success_formatter.py`)

The JSON `_find_auto_output` was root-level only. Made it namespace-aware to match the text version's behavior:

```
1. Root-level common keys: result > output > response > text > data > stdout
2. Inside namespace dicts: same keys, last occurrence wins (most downstream node)
3. Last-key fallback
```

Added `stdout` to common_keys (shell nodes write `stdout`, not `result`). This fixes `--only` AND improves auto-detection for workflows without declared outputs.

**Pre-existing inconsistency found**: Three separate auto-detection implementations exist with different priority orders and namespace awareness. Created Task 134 to unify them.

**Test updated**: `test_json_output_includes_stderr_in_steps` in `test_shell_stderr_warnings.py` was asserting the old last-key-fallback behavior (full namespace under node name). Updated to assert new behavior (stdout extracted from namespace). The test's core intent (stderr accessible in execution steps) preserved.

#### Execution summary (`success_formatter.py` + `workflow_output.py`)

Both CLI and MCP text formatters filter `not_executed` steps when `--only` active:
- `Nodes executed (N/M):` format (executed/total)
- `⤷ Stopped after 'X' (--only), N remaining nodes skipped` summary line
- Singular/plural grammar for "node"/"nodes"

JSON keeps ALL steps including `not_executed` for programmatic access.

**New fields in `execution` dict**: `only_node` (str), `nodes_skipped` (int) — only when `--only` active. `cache_hits` (int) — only when > 0.

#### Cache stats (`success_formatter.py` + `workflow_output.py`)

Completion header: `✓ Workflow completed in 2.3s (3 cached, 2 executed)` when `cache_hits > 0`. CLI and MCP text formatter both show it. Extended `_display_workflow_completion_status()` with `cache_hits=0, nodes_executed=0` kwargs.

#### Report integration (`main.py` + `trace_report.py`)

When `--only` + `--report` are both active:

1. **Pointer line**: `→ Target node: ~/.pflow/reports/test-pipeline/02-process.md` — displayed after the report directory path. Helper `_echo_target_node_path` computes the filename from trace events using 1-based enumeration + `_safe_name` (same logic as `_write_node_files`). Handles batch/sub-workflow containers (points to `summary.md` inside directory).

2. **Summary context**: `generate_report()` accepts optional `only_node` and `total_nodes` params. Summary shows `Nodes: 3/4 (--only 'summarize', 1 skipped)` instead of just `Nodes: 3`. `total_nodes` stored in `ctx.obj["total_nodes"]` where the IR node count is computed.

3. **Pipeline table cached tag**: `_format_event_status()` now appends `[cached]` suffix to the status column when `event.get("cached")` is True. Applies to both `--only` and normal reports.

#### Cache DB init warning (`cache.py`)

`logger.debug` → `logger.warning` with message about permissions. Per-node `get()`/`put()` failures remain DEBUG.

### Key Design Decisions

1. **No output promotion in compiler**: The compiler only stores metadata (`__execution__["only_node"]`). Output extraction is the display layer's responsibility. This avoids mutating shared storage for presentation purposes.

2. **Auto-detection over special `--only` handling**: Rather than building a parallel output extraction path for `--only`, made the existing JSON auto-detection namespace-aware. Same code path handles both `--only` and workflows without declared outputs.

3. **Detailed debugging through `--report`, not JSON `result`**: The JSON `result` field gives the auto-detected primary value (e.g., `{"stdout": "..."}`). The full debugging context (resolved command, stderr, exit code) lives in the per-node report file. This avoids exposing internal state in the JSON output and aligns with the `structure` mode design philosophy where detailed node data requires explicit access.

4. **Declared outputs skipped entirely with `--only`**: When `--only` stops the flow, declared outputs reference nodes that didn't execute. Rather than best-effort partial resolution, we skip them entirely and use auto-detection. This is correct because `--only` is about inspecting a specific node's output, not the workflow's declared result.

### Pre-existing Issues Discovered

1. **Three divergent auto-detection functions**: `workflow_output._find_auto_output` (text, namespace-aware, response-first priority), `success_formatter._find_auto_output` (JSON, now namespace-aware, result-first priority), `executor_service._extract_default_output` (unused by display). Different priorities, different key lists. Created **Task 134** to unify.

2. **Static commands missing from report**: When a shell command has no templates, `template_resolutions` is empty so the report's `## Command` section doesn't appear. The resolved command IS in `node_output["command"]` but `_format_node_output` skips it (in `shown_keys`). Pre-existing, not caused by our changes.

3. **`ExecutionResult.output_data` is dead code**: `_extract_default_output` populates it, but no display path reads it. Both CLI and MCP re-derive output from `shared_storage` independently.

### Files Modified

| File | What |
|------|------|
| `src/pflow/runtime/compilation/compiler.py` | `_apply_run_hooks` takes `only_node`, stores metadata, skips output resolution |
| `src/pflow/execution/formatters/success_formatter.py` | `execution_dict` with `only_node`/`nodes_skipped`/`cache_hits`; MCP text filtering + cache header; namespace-aware `_find_auto_output`; removed `_collect_only_node_outputs` |
| `src/pflow/cli/workflow_output.py` | CLI filtering for `--only`, summary line, cache stats in header, skip declared outputs when `--only` |
| `src/pflow/cli/main.py` | `_echo_target_node_path` helper, `--only` context passed to `generate_report`, `total_nodes` stored in ctx.obj |
| `src/pflow/core/trace_report.py` | `generate_report` accepts `only_node`/`total_nodes`, summary shows skipped count, pipeline table shows `[cached]` |
| `src/pflow/runtime/cache.py` | DB init → WARNING |
| `.taskmaster/tasks/task_106/task-106.md` | Removed saved workflow exclusion |
| `.taskmaster/tasks/task_134/task-134.md` | New task: unify auto-detection functions |
| `tests/test_execution/formatters/test_success_formatter.py` | 11 new tests |
| `tests/test_runtime/test_cache_integration.py` | 1 new test |
| `tests/test_cli/test_shell_stderr_warnings.py` | Updated 1 test for namespace-aware auto-detection |

## Phase 17: Agent and User Documentation — COMPLETED

Review identified that no agent-facing instructions or user-facing docs mentioned caching, `--only`, or `--no-cache`. An agent using pflow for the first time would have no way to discover these features.

### Gap analysis

- `pflow instructions usage` (CLI basic usage) — zero mentions of caching or iteration
- `pflow instructions create` (CLI agent instructions) — zero mentions
- MCP agent instructions (`pflow://instructions`) — zero mentions
- MCP sandbox instructions (`pflow://instructions/sandbox`) — zero mentions
- User-facing docs (`docs/reference/cli/index.mdx`) — `--cache/--no-cache` and `--only` missing from global options table, no iteration section, JSON output example missing `cache_hits` field

### Changes

**Agent instructions** (4 files, ~25 lines total):

| File | Addition |
|------|----------|
| `src/pflow/cli/resources/cli-basic-usage.md` | "Iterating on Workflow Files" section after "Execute workflow by name" — 4 example commands showing cache, `--only`, `key=value` override, `--no-cache` |
| `src/pflow/cli/resources/cli-agent-instructions.md` | "Iteration is Free" paragraph after Phase-Based Building — caching is automatic, `--only` for focused iteration, `--no-cache` for fresh execution |
| `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` | Same "Iteration is Free" block (MCP agents with CLI access can use `--only` and `--no-cache`) |
| `src/pflow/mcp_server/resources/instructions/mcp-sandbox-agent-instructions.md` | Shorter version — caching is automatic via `workflow_execute`, no CLI flags mentioned (sandbox agents have no CLI access) |

**User-facing docs** (1 file):

| Change | What |
|--------|------|
| Global options table | Added `--cache/--no-cache` and `--only NODE` rows |
| New "Iteration and caching" section | Explains automatic caching, `--only` for single-node runs, `--no-cache` for bypass. Placed between "Validation mode" and "Traces and reports" |
| JSON output example | Added `cache_hits` field and a cached step (`"cached": true, "duration_ms": 0`) |
| Key fields table | Added `execution.cache_hits` row |

### Design decisions

- **Minimal token footprint**: Agent instructions kept short (~8 lines per file) because agents pay per token and the instructions are loaded every session. The key information (caching is automatic, `--only` exists, `--no-cache` exists) fits in 3 bullet points.
- **Sandbox instructions omit CLI flags**: Sandbox agents use `workflow_execute` MCP tool, which doesn't expose `--only` or `--no-cache`. They only need to know that re-execution is automatically cached.
- **User docs follow existing patterns**: The "Iteration and caching" section mirrors the structure of "Stdin input" and "Validation mode" — brief explanation, code examples, subsections for specific flags.

## Implementation Complete

**Final state**: 4492 tests pass, `make check` clean (ruff + mypy + deptry).

7 code reviews / design iterations performed across the implementation:
- Reviews 1-2 (parallel, wave 1): Found critical `_resolved` stale-state bug + missing sub-workflow propagation
- Review 3 (wave 2): Confirmed all fixes, identified missing regression test
- Review 4 (Phase 14, data integrity): Found `_make_serializable` data loss bug in `put()`, missing data-flow-through-cache test
- Review 5 (final): 7 cosmetic/documentation fixes, no behavioral issues
- Review 6 (Phase 17): Identified zero documentation of cache features across all agent instructions and user docs
- Review 7 (Phase 16, design iteration): 5 attempts at `--only` output design. Manual testing revealed 3 missed declared-output code paths, namespace-awareness gap in JSON auto-detection, and data exposure concerns. Final design: no special output handling, namespace-aware auto-detection, detailed inspection through `--report`.

Phase 16 (--only UX fixes) went through significant design evolution — 5 implementation attempts before settling on the final approach. The key lesson: the output pipeline has more independent code paths than it appears (3 declared-output resolution points, 3 auto-detection implementations). Changes that seem simple in one path often miss the others. Manual end-to-end testing caught issues that unit tests couldn't.

Phase 17 (documentation) updated 5 files to ensure agents and users can discover and use the cache features.

**Follow-up task created**: Task 134 (Unify Auto-Detection Output Functions) — consolidate the three divergent `_find_auto_output` implementations into a single shared function.
