# Task 106 Review: Workflow Iteration Cache

## Metadata

- Implementation Date: 2026-03-26
- Branch: `feat/workflow-iteration-cache`

## Executive Summary

Memoization-based caching for workflow node execution. When an agent re-runs a `.pflow.md` file, unchanged nodes serve cached results from a persistent SQLite cache. Same mechanism works at every nesting level via a single propagated cache instance. Three composable CLI flags (`--only`, `--no-cache`, `key=value`) complete the developer iteration loop. The feature required touching 7 core source files, 5 agent/user doc files, 6+ CLAUDE.md files, and creating 1 new module (`cache.py`) + 5 new test files (69 tests total).

## Implementation Overview

### What Was Built

1. **`resolve_templates()` public method** on `TemplateAwareNodeWrapper` — extracts the 150-line resolution block from `_run()` so the instrumented wrapper can compute the input hash without triggering execution.

2. **Enhanced config hash** in `InstrumentedNodeWrapper._compute_node_config()` — now includes template params (raw `${...}` templates), semantic batch config, and filters `_source_line` noise.

3. **`MemoizationCache` module** (`src/pflow/runtime/cache.py`) — SQLite-backed persistent cache with WAL mode, zlib compression, TTL eviction, graceful degradation.

4. **Memoization check** in `InstrumentedNodeWrapper._run()` — resolves templates, computes cache key, checks SQLite. On hit: restores output to shared store + reuses existing `_handle_cached_execution()`. Separate code path for batch nodes (can't resolve `${item}` outside the loop).

5. **`--cache/--no-cache` and `--only` CLI flags** — `--no-cache` disables reads but still writes. `--only` monkey-patches `get_next_node` to terminate after target. Both flow through `enhanced_params` with asymmetric handling (`__no_cache__` popped, `__only_node__` filtered).

6. **`--only` output pipeline** — skips `populate_declared_outputs()` (prevents `OutputResolutionError`), stores `__execution__["only_node"]` for display layer, relies on namespace-aware auto-detection for output extraction. `--report` integration shows pointer to target node's report file.

7. **Execution summary enhancements** — `(N cached, M executed)` in completion header, `Nodes executed (N/M):` with `⤷ Stopped after 'X' (--only)` summary line, `cache_hits`/`only_node`/`nodes_skipped` in JSON output.

### Deviations from Original Spec

| Spec said | Actually built | Why |
|-----------|---------------|-----|
| Sub-workflow cache key: `hash(path + content + child_params)` | No sub-workflow-level cache. Node-level caching via propagated `__memoization_cache__` | Sub-workflows compile fresh each run (reading current files). Node-level handles everything. The file reference problem (editing a prompt file inside a sub-workflow) is caught because file content is inlined at compile time → config hash changes. |
| Extend existing `__execution__` mechanism | Separate `__memoization_cache__` layer | `__execution__` is in-memory per-run state (loop detection, resume). Memoization is cross-run SQLite. Different lifecycles, no interference. |
| Per-workflow cache files | Single SQLite database | Concurrent batch safety (WAL), TTL eviction (one SQL statement), Task 133 alignment (add trace columns later). |
| `_resolved` optimization on template wrapper | Removed entirely after finding stale-state bug | The optimization was already dead after the bug fix. Double resolution is sub-millisecond. Eliminating instance state eliminates the bug class. |
| Saved workflows excluded | Included | Cache keys are content-addressed. Correct regardless of workflow origin. |

## Files Modified/Created

### Core Changes

- `src/pflow/runtime/cache.py` — **Created**. SQLite memoization cache: `MemoizationCache` class, `compute_node_cache_key()`, `compute_batch_cache_key()`, `_make_serializable()` (for hashing only), `_deterministic_json()`.
- `src/pflow/runtime/wrappers/instrumented_wrapper.py` — Memoization check in `_run()`, enhanced `_compute_node_config()`, helper methods: `_enforce_loop_guard()`, `_check_memo_cache()`, `_write_memo_cache()`, `_compute_memo_cache_key()`, `_compute_batch_memo_key()`, `_is_batch_node()`.
- `src/pflow/runtime/wrappers/template_wrapper.py` — Extracted `resolve_templates(shared) → dict` as public method. `_run()` calls it internally.
- `src/pflow/runtime/compilation/compiler.py` — `_apply_run_hooks(flow, ir_dict, only_node=None)` extended for `--only` metadata + output skip. `_apply_only_node_stop()` for `get_next_node` monkey-patch.
- `src/pflow/execution/executor_service.py` — `MemoizationCache` creation in `_initialize_shared_store()`, asymmetric `__no_cache__` pop vs `__only_node__` filter.
- `src/pflow/runtime/workflow_executor.py` — `__memoization_cache__` added to `_PROPAGATED_KEYS`.
- `src/pflow/cli/main.py` — `--cache/--no-cache` and `--only` click options, `_echo_target_node_path` for `--report` integration, `total_nodes` in ctx.obj.
- `src/pflow/execution/formatters/success_formatter.py` — `cache_hits`/`only_node`/`nodes_skipped` in JSON, MCP text filtering, namespace-aware `_find_auto_output`, cache stats header.
- `src/pflow/cli/workflow_output.py` — `--only` step filtering, summary line, cache stats in completion header, skip declared outputs when `--only`.
- `src/pflow/core/trace_report.py` — `[cached]` in pipeline table, `--only` context in summary, `only_node`/`total_nodes` params on `generate_report()`.
- `tests/conftest.py` — `MemoizationCache.__init__` monkey-patch for test isolation.

### Test Files

- `tests/test_runtime/test_template_wrapper_resolve.py` — 8 tests. Verifies `resolve_templates()` extraction.
- `tests/test_runtime/test_instrumented_wrapper_config.py` — 11 tests. Enhanced config hash: template params, batch config, `_source_line` exclusion.
- `tests/test_runtime/test_cache.py` — 18 tests. SQLite storage: put/get, TTL, concurrent access, corruption recovery.
- `tests/test_runtime/test_memoization_integration.py` — 8 tests. Single-node memoization: hit/miss, batch, loops.
- `tests/test_runtime/test_cache_integration.py` — 13 tests. Multi-node flows through real PocketFlow `Flow` objects. **Most valuable**: `test_cached_output_flows_through_template_resolution` (3-node chain with type preservation), `test_stale_resolved_regression_in_loop` (loop scenario).
- `tests/test_execution/formatters/test_success_formatter.py` — 11 tests. `--only` filtering, cache stats display.

## Integration Points & Dependencies

### Load-Bearing Integration Points

- **`shared["__memoization_cache__"]`** — Created by `executor_service._initialize_shared_store()`. Read by `InstrumentedNodeWrapper._run()`. Propagated to child workflows via `_PROPAGATED_KEYS`. If this key is missing, caching silently disabled (graceful).
- **`resolve_templates()` on `TemplateAwareNodeWrapper`** — Called by `InstrumentedNodeWrapper._compute_memo_cache_key()` to get resolved inputs for cache key. Found via `_find_template_wrapper()` (duck typing: `hasattr(current, "last_resolutions")`).
- **`_handle_cached_execution()`** — Reused for both in-process cache hits AND memoization cache hits. Handles trace recording, progress callbacks, `__cache_hits__` tracking. On memoization hit: `shared[node_id]` must be populated BEFORE calling this (it reads `node_output` from there).
- **`__execution__["only_node"]`** — Set by `_apply_run_hooks()` in compiler. Read by `success_formatter.py`, `workflow_output.py`, `trace_report.py`. Coordinates the display layer without the display layer needing to know about the compiler.
- **`conftest.py` MemoizationCache patch** — Without this, tests using real workflows pollute `~/.pflow/cache/cache.db`. The patch redirects to temp paths. Must be kept in sync if `MemoizationCache.__init__` signature changes.

### Shared Store Keys

- `__memoization_cache__` — `MemoizationCache` instance. Created in `_initialize_shared_store()`. Propagated via `_PROPAGATED_KEYS`.
- `__execution__["only_node"]` — `str | None`. Set in `_apply_run_hooks()`. Read by formatters/display.
- `__cache_hits__` — `list[str]`. Pre-existing, now also populated by memoization cache hits.

## Architectural Decisions & Tradeoffs

### Key Decisions

**Memoization over cascade invalidation** — Cache keys are `hash(config + resolved_inputs)`. If upstream re-executes but produces the same output, downstream stays cached. Cascade ("upstream changed → invalidate downstream") would over-invalidate. The memoization model is strictly more efficient and has zero special cases across nesting levels.

**No sub-workflow-level caching** — Originally spec'd as `hash(path + content + child_params)`. Rejected because: (1) editing a file INSIDE the sub-workflow (e.g., a prompt file) doesn't change the sub-workflow file itself, causing false cache hits; (2) node-level caching inside sub-workflows handles everything naturally — the cache is propagated, sub-workflows compile fresh reading current files, and each node checks its own cache key. Zero special-case code.

**SQLite over files** — Concurrent batch safety (WAL mode), TTL eviction (one SQL statement), zero dependencies (stdlib), Task 133 alignment (add trace columns later). One file: `~/.pflow/cache/cache.db`.

**`resolve_templates()` is pure — no `_resolved` instance state** — The original plan cached resolved params on the template wrapper to avoid double resolution. This caused a stale-state bug: `copy.copy()` in PocketFlow's `_orch()` loop shares the template wrapper instance across iterations. On memoization cache hit, `_resolved` was set but never consumed; on the next loop iteration (visit > 1), the stale value was consumed instead of fresh resolution. Removing `_resolved` eliminates the bug class. Double resolution is sub-millisecond (dict lookups, no I/O).

**Separate serialization for hashing vs storage** — `_make_serializable()` mangles `__dunder__` key values (replaces with type strings). Correct for hashing (deterministic, lossy is fine). Incorrect for storage (data loss). `put()` uses `json.dumps(output, default=str)` for faithful storage.

**Batch and non-batch have different cache key paths** — For non-batch nodes: `hash(config + resolved_template_values)`. For batch nodes: `hash(config + semantic_batch_config + resolved_items_list)`. Can't resolve batch-dependent templates like `${item.title}` from outside the batch loop (they'd fail in strict mode). The dispatch is via `_is_batch_node()`.

### Technical Debt

- **Three divergent auto-detection functions** — `workflow_output._find_auto_output` (text), `success_formatter._find_auto_output` (JSON/MCP), `executor_service._extract_default_output` (unused by display). Different priority orders, different key lists. Task 134 created to unify.
- **`ExecutionResult.output_data` is dead code** — Populated by `_extract_default_output` but never read by any display path. Both CLI and MCP re-derive output from `shared_storage` independently.
- **`_find_template_wrapper()` uses duck typing** — `hasattr(current, "last_resolutions")` to identify template wrapper in chain traversal. Works but fragile if another wrapper adds this attribute.

## Unexpected Discoveries

### The `--only` Output Pipeline (5 Design Iterations)

The plan assumed `--only` output would "just work." In reality, the output pipeline has MORE independent code paths than it appears:
1. `_apply_run_hooks()` calls `populate_declared_outputs()` — crashes when downstream nodes didn't execute
2. CLI text path (`workflow_output.py`) has its own declared output resolution
3. JSON/MCP path (`success_formatter.py`) has its own auto-detection (was NOT namespace-aware)

Each path needed separate `--only` guards. The final design: no special output handling in the compiler, namespace-aware auto-detection everywhere, `--report` for detailed inspection. It took 5 attempts to get right because each attempt revealed another output path.

### Template Wrapper Instance Sharing in Loops

PocketFlow's `Flow._orch()` uses `copy.copy()` to create node instances for each loop iteration. `NamespacedNodeWrapper` has no `__copy__` — default shallow copy shares `_inner_node` reference. This means the `TemplateAwareNodeWrapper` instance is SHARED across loop iterations. Any instance state set during iteration N is visible in iteration N+1. This is the root cause of the `_resolved` stale-state bug and a landmine for future modifications.

### Conftest Test Isolation

`MemoizationCache` defaulting to `~/.pflow/cache/cache.db` caused cross-test pollution. The `isolate_pflow_config` fixture patches `Registry`, `WorkflowManager`, etc. to temp paths — but didn't know about the new cache. The `test_data_flows_between_nodes` e2e test failed with `[cached]` because a previous test run had already cached the same node config + inputs to the REAL database.

## Patterns Established

### Propagated Shared Store Resources

`_PROPAGATED_KEYS` in `workflow_executor.py` is how cross-nesting-level infrastructure works. To add a new resource that child workflows need:
1. Create it in `executor_service._initialize_shared_store()`
2. Add the key to `_PROPAGATED_KEYS` tuple
3. Patch it in `conftest.py::isolate_pflow_config` for test isolation

### Broad Exception Handling for Optional Features

```python
try:
    cache_key = self._compute_memo_cache_key(shared)
except Exception:
    logger.debug("Failed to compute cache key", exc_info=True)
    return None  # skip caching, execute normally
```

The cache should NEVER prevent execution. Template resolution can fail in many unanticipated ways. Catch broadly, log at debug, degrade gracefully.

### Wrapper Chain Traversal

`_find_template_wrapper()` and `_find_batch_or_workflow_node()` traverse the wrapper chain using duck typing. The chain order is fixed by data flow constraints (can't reorder). When you need data from an inner wrapper, traverse to find it rather than trying to restructure the chain.

## Anti-Patterns to Avoid

**Never cache instance state on the template wrapper.** The `TemplateAwareNodeWrapper` instance is shared across `copy.copy()` iterations in PocketFlow's loop. Any field set during one iteration persists into the next. `resolve_templates()` is cheap (sub-millisecond) — always resolve fresh.

**Never use `_make_serializable()` for data storage.** It's for hashing (deterministic representation). For storage, use `json.dumps(output, default=str)` to preserve all data faithfully.

**Don't assume one output extraction path.** There are currently 3 independent auto-detection implementations. Changes to output behavior must touch all of them (or wait for Task 134 unification).

## Testing Implementation

### Tests That Catch Real Bugs

- **`test_stale_resolved_regression_in_loop`** — Pre-populates cache, runs a looping flow. Catches any future reintroduction of cached resolution state on the template wrapper. This test would have caught the `_resolved` bug.
- **`test_cached_output_flows_through_template_resolution`** — 3-node chain where downstream reads `${upstream.field}` from cached output. Verifies type preservation (str/int/float/bool/None/list/dict) through the full SQLite round-trip. Would have caught the `_make_serializable` storage bug.
- **`test_cache_db_init_failure_logs_warning`** — Verifies graceful degradation: SQLite failure → WARNING logged, workflow executes normally.
- **Conftest `isolate_pflow_config` patch** — Not a test, but prevents ALL cache-related tests from polluting the real `~/.pflow/cache/cache.db`.

### Tests That Are Coverage, Not Bug-Catchers

The unit tests in `test_cache.py` (basic put/get, TTL, deterministic keys) and `test_instrumented_wrapper_config.py` (config hash includes X, excludes Y) are useful for documenting behavior but unlikely to catch regressions — the code they test is straightforward.

## Future Considerations

### Extension Points

- **Per-batch-item caching** — Currently whole-batch. To add per-item: intercept inside `PflowBatchNode._exec_single()`, compute per-item cache key from `item_shared` context. The `_compute_batch_memo_key()` dispatching is already in place.
- **Task 133 (Unified storage)** — Add trace metadata columns to the SQLite cache table. `output_hash` column is already reserved for content-addressed lookup. The schema is designed for this extension.
- **Task 134 (Unify auto-detection)** — Three `_find_auto_output` implementations need consolidation. The namespace-aware version in `success_formatter.py` is the most complete.
- **Cache management CLI** — `pflow cache status` (show DB size, entry count, TTL), `pflow cache clear` (delete all or per-workflow). Not needed for MVP.

### What Would Break If Modified Naively

1. **Reintroducing instance state on template wrapper** → stale-state bugs in loops
2. **Forgetting `_PROPAGATED_KEYS` for new shared store resources** → child workflows silently miss the resource
3. **Forgetting conftest patch for new shared store resources** → cross-test pollution
4. **Changing `_compute_node_config()` without updating both hash consumers** → cache key drift between in-process and memoization checks
5. **Using `_make_serializable()` in `put()`** → data loss for dunder keys in output

## AI Agent Guidance

### Quick Start for Related Tasks

Read these files in this order:
1. `src/pflow/runtime/cache.py` — the cache module (self-contained, ~313 lines)
2. `src/pflow/runtime/wrappers/instrumented_wrapper.py` lines 655-767 — the memoization check flow
3. `src/pflow/runtime/wrappers/template_wrapper.py` lines 495-660 — `resolve_templates()` method
4. `src/pflow/runtime/compilation/compiler.py` lines 601-650 — `_apply_run_hooks()` and `_apply_only_node_stop()`
5. `tests/test_runtime/test_cache_integration.py` — the integration tests show how everything connects

### Common Pitfalls

1. The output pipeline has 3 independent paths. Test end-to-end with real CLI, not just unit tests.
2. Template wrapper instances are shared across loop iterations via `copy.copy()`. Never add mutable instance state.
3. The `--only` flag is filtered (not popped) from `execution_params` — the compiler needs it in `initial_params`. `--no-cache` IS popped. This asymmetry is deliberate.
4. Batch nodes can't use `resolve_templates()` from outside the batch loop — `${item}` doesn't exist in the outer context. Use `_compute_batch_memo_key()` instead.
5. Always test with `make test` (full suite), not just your new test file — the conftest isolation can mask cross-test issues if you only run a subset.

---

*Generated from implementation context of Task 106, 2026-03-26*
