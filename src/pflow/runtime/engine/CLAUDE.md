# Engine Module

Orchestration engine that handles graph traversal and all runtime concerns: template resolution, namespacing, batch processing, instrumentation (caching, tracing, metrics, progress callbacks).

## File Structure

```
src/pflow/runtime/engine/
├── __init__.py              # Exports: CompiledWorkflow, WorkflowEngine, type classes
├── engine.py                # WorkflowEngine, parse_only_path — graph walker + per-node orchestration
├── types.py                 # CompiledWorkflow, NodeConfig, TemplateConfig, BatchConfig
├── template_resolution.py   # Standalone template resolution functions
├── batch_executor.py        # Standalone batch execution functions
├── instrumentation.py       # Cache, trace, metrics, progress, loop guards
├── namespaced_store.py      # NamespacedSharedStore proxy for per-node store isolation
├── api_warning_detector.py  # API error classification (73 validation + 20 resource patterns)
├── template_errors.py       # Structured Diagnostic builder for unresolved templates
└── error_context.py         # Upstream stderr extraction for error enrichment
```

## Architecture

```
WorkflowEngine(metrics, trace, only_node).run(workflow, shared) → action_string
  ├── install self.trace into shared["__trace_collector__"] (save+restore for nested sub-workflows)
  └── for each node in graph:
      _execute_node(node, config, shared) → action
        ┌─ OUTSIDE try (always runs):
        │  (Step 1 — LLM trace registration — removed in Task 158 Phase A
        │   post-cleanup; LLMNode.prep now reads shared["__trace_collector__"]
        │   + self.node_id directly. Numbering preserved for cross-reference.)
        │  2. initialize_execution_state
        │  3. enforce_loop_guard       (clears stale __failures__ on revisit)
        │
        ├─ INSIDE try (template errors get trace recording):
        │  4-7. plan_node() → decides cached/miss and returns NodePlan
        │  8. call_start_callback
        │  9. execute: batch → execute_batch() | single → node._run(namespaced_store)
        │  10. detect_api_warning → handle_api_warning if found (returns "error")
        │  11. cache_result, 12. write_memo_cache (SKIP when cache_enabled=False)
        │  13-17. duration, metrics, enrich_llm_cost, record_trace, call_completion_callback
        │  17.5. if action starts with "error": mark_node_failed (archive to __failures__,
        │        + warning= when error successor exists → triggers DEGRADED, GH #246)
        │
        └─ EXCEPT (error path):
           metrics, enrich_llm_cost, record_trace(error=e),
           call_completion_callback(action="error", error=e),
           mark_node_failed (archive to __failures__),
           annotate e._pflow_node_id, re-raise
```

**Step 17.5 is the LAST thing on the happy path for failed nodes.** It runs AFTER `record_trace`, `call_completion_callback`, and `enrich_llm_cost` — those consumers still read `shared[node_id]` directly with the data in its original location. After step 17.5, the data lives in `shared["__failures__"][node_id].data` and any subsequent reader must use `node_state.get_node_output`. When the failed node has an error successor (`node.successors.get("error")`), step 17.5 passes `warning=` to `mark_node_failed` so the recovery is visible in `__warnings__` → DEGRADED status + WARNING diagnostic (GH #246). When there is no error successor, `warning=None` and behavior is unchanged.

**Steps 1-4 outside try, 5-17.5 inside try** so strict-mode template `ValueError` raised during step 5 still gets trace recording on the error path.

## Key Design Decisions

1. **`_execute_single_node` returns `(action, last_resolutions, template_errors)`** — NO instance state on the engine. This prevents data races in parallel batch where multiple threads call the same function concurrently.

2. **Shared store is the single source of runtime data** — no `initial_params` override. `resolved_defaults` are seeded into shared store by the Runner/WorkflowExecutor before `engine.run()`.

3. **Batch nodes skip top-level template resolution** — `_execute_node` guards on `if config.template_config and not config.batch_config`. Without this, `${item}` would fail before the batch loop starts. Per-item resolution happens via the `_execute_single_node` callback.

4. **Engine does NOT restore node.params** — sets `node.params = resolved_params` permanently. Safe because: each node is visited once per traversal (loops re-resolve), batch items use the callback which sets params per item.

5. **Template resolution inside try block** — so that strict-mode `ValueError` gets trace recording on the error path. `resolve_templates` attaches `._pflow_partial_resolutions` to the exception (non-standard, but needed for trace to show what resolved before the error).

6. **`record_trace` has explicit `success` parameter** — nodes returning `"error"` action (without raising) need `success=False` in the trace. Without explicit `success`, `error is None` → `success=True` would be wrong. Engine passes `success=not str(action).startswith("error")`.

## WorkflowEngine (`engine.py`)

Stateless executor. No per-node instance state.

### `run(workflow, shared) → str`

1. Parses `--only` via `parse_only_path` into `(this_only, child_only)`. Validates first segment exists; if dotted, validates it's a `WorkflowExecutor`.
2. Resets `node_visit_counts`
3. Walks graph: `_execute_node` per node, follows `curr.successors.get(action or "default")`
4. On unmatched action: `_handle_no_successor` checks if step 17.5 already archived the node; if so, preserves the existing failure record and only writes a routing hint to `__warnings__`. Otherwise rolls back success bookkeeping, archives as `routing_error` via `mark_node_failed`, AND calls `self.trace.mark_last_event_failed(node_id, error=...)` to flip the already-recorded trace event so trace state agrees with `__failures__` (GH #250). The trace-flip call happens only in the non-error-action branch — the error-action branch is already correct because `is_error_action=True` caused step 16 to record `success=False`.
5. On `--only`: writes `shared["_pflow_child_only_node"] = child_only` before target sub-workflow execution (cleaned up after). Stops after target, sets `__execution__["only_node"]` to the full dotted path.
6. On success: calls `populate_declared_outputs` (skipped on error or `--only`)

### `_execute_node(node, config, shared) → str`

Happy path: steps 1-17.5, returns action string. Error path: catches exception, records metrics/trace/callback, archives via `mark_node_failed`, annotates exception, re-raises.

**Error path details** (load-bearing — preserve these on any modification):
- `getattr(e, "_pflow_partial_resolutions", None)` extracts template resolutions before the error (attached by `resolve_templates`)
- `getattr(e, "_pflow_template_diagnostic", None)` extracts a structured Diagnostic for strict-mode template errors so `_builtin_exception_diagnostic` can return it directly without losing the per-reference structure
- `call_completion_callback(..., action="error", error=e)` — without this the progress spinner shows the failed node as still running
- `mark_node_failed(shared, id, category=..., error=...)` — categorizes template-resolution `ValueError` (via `_pflow_partial_resolutions` presence) as `template_error`, otherwise `exception`
- `e._pflow_node_id = config.node_id` — the Runner's `_exception_to_result` reads this to annotate diagnostics
- The Runner additionally attaches `e._pflow_shared_store = shared_store` so `_exception_to_result` can populate `ExecutionResult.shared_after`. Without this, exception-path failures have empty `shared_after` and CLI/MCP formatters lose all per-node detail.

### `plan_node.py` — The Shared Decision Primitive

`plan_node(node, config, shared) -> NodePlan` is called by both:

- `engine.py::_execute_node()`
- `execution/plan.py::build_plan()`

It owns config hashing, non-batch template resolution, memo-cache lookup, and in-process cache lookup. It does **not** execute the node, call the loop guard, emit progress, or mutate `shared`.

`check_memo_cache()` and `check_cache_validity()` remain as thin compatibility wrappers. The new lower-level primitives are:

- `memo_cache_lookup()`
- `apply_memo_hit()`
- `in_process_cache_lookup()`

**Engine vs planner consumers diverge only in how they consume `NodePlan`**:
- Engine dispatches on `NodePlan.status` → cached path (`apply_memo_hit` + `handle_cached_execution`) or miss path (proceed to step 9).
- Planner dispatches on `NodePlan.status` via five named entry builders (`_template_error_entry` / `_cache_disabled_entry` / `_cached_memo_entry` / `_cached_in_process_entry` / `_miss_entry`), then runs `_classify` to decide the walker's `Transition`. See `execution/CLAUDE.md` → "Dry-Run Planner" for the walker state machine.

Parity is enforced by `tests/test_execution/test_plan_drift.py`. State-machine semantics are unit-tested at `tests/test_execution/test_plan_classify.py`.

### Engine-injected output metadata: `__pflow_stats__`

`write_memo_cache()` injects a reserved key `__pflow_stats__` into the output blob before calling `MemoizationCache.put()`:

```python
output_dict["__pflow_stats__"] = {"duration_ms": duration_ms}
```

This carries engine-owned execution metadata (currently duration; extendable to memory/tokens later) so `--dry-run` can surface historical estimates via `MemoizationCache.get_latest_for_node()` without a parallel storage system.

**Convention — load-bearing:**
- **Name must be double-underscore dunder**. `_make_serializable` in `cache.py` collapses dunder-keyed values to `"<dict>"` for deterministic cache-key hashing, so stats deltas never invalidate cache identity. A single-underscore key (e.g., `_pflow_stats`) would feed stats INTO the hash — every run would produce a new cache_key, silently breaking caching.
- **Node authors must not write this key.** It's engine-owned; conflicts are a user-code smell.
- **Readers must be absent-tolerant.** Pre-existing cache entries (from before this feature) don't have the key. Code that consumes it (e.g. `plan.py::_read_stats_from_output`) returns `None` cleanly.
- **`apply_memo_hit` strips the key when restoring to `shared[node_id]`.** A fresh execution would never produce the key in live shared state, so restoring it would make cached vs fresh paths observably differ (template resolution, equality, trace output).
- **Display-site filtering**: `node_output_formatter.py` and `trace_report.py` filter `_`-prefixed keys when iterating output dicts so reserved keys don't leak into agent-visible output (`-p/--print`, `--structure`, `--report`, MCP node-run text).

### `_execute_single_node(node, config, shared) → (action, last_resolutions, template_errors)`

Used in two contexts:
1. **Non-batch nodes**: called directly by `_execute_node` (step 9)
2. **Batch items**: called as `execute_single_fn` callback by `execute_batch`

The return tuple is the contract between engine and batch executor. Changing it breaks batch.

## Types (`types.py`)

- **`CompiledWorkflow`** — structural result from `compile_workflow()`. Reusable for sequential batch items within one execution. **NOT safe for concurrent `engine.run()` calls** — `node.params` is mutated during execution.
- **`NodeConfig`** — per-node metadata: template config, batch config, namespacing flag, interface metadata, cache_enabled flag
- **`TemplateConfig`** — template vs static param split, expected types, resolution mode, optional input keys
- **`BatchConfig`** — items template, alias, error handling, parallel/sequential, concurrency, retry settings

## Template Resolution (`template_resolution.py`)

### Key functions

- `build_type_cache(interface_metadata)` — one-time: extract param→type from registry metadata
- `split_params(params, expected_types)` — one-time: separate template vs static. `_source_line` keys go to static (python_code.py reads them)
- `resolve_templates(config, shared, node_id)` → `(merged_params, last_resolutions, template_errors)`
- `validate_resolved_type(...)` → `Optional[str]` (error message or None). **No raise** — caller handles mode.
- `contains_unresolved_template(value, template)` — recursive, depth-limited to 100
- `inject_none_for_optional_inputs(...)` — for code nodes with `T | None` annotations

### Ordering contract

The `inputs` key is ALWAYS processed first. Resolved input values are merged into context before other params. This enables `${text}` in `prompt` after `inputs.text: ${upstream.text}` is resolved.

### Context building

`context = dict(shared)` — shared store only. No `initial_params` override. Static inputs (from `TemplateConfig.static_params["inputs"]`) are also merged into context so other params can reference them.

### Error handling

**Strict mode**: raises `ValueError` with `._pflow_partial_resolutions` attribute (dict of params resolved before the error). The engine's except handler extracts these for trace recording.

**Permissive mode**: returns errors in `template_errors` list. Each error is a dict with `message`, `type`/`unresolved`, `param`/`template`, **and a structured `diagnostic`** (`Diagnostic` object). The engine writes them to `shared["__template_errors__"][node_id]`. Both the unresolved-template path and the type_validation path attach a Diagnostic at the source site so `runner._extract_runtime_warnings` has a single code path — any entry without a `diagnostic` key is a contract violation and gets skipped with a logger warning.

## Batch Executor (`batch_executor.py`)

### `execute_batch(node, config, shared, execute_single_fn) → (action, batch_trace_items)`

The `execute_single_fn` callback signature: `(node, config, item_shared) → (action, last_resolutions, template_errors)`. This is `engine._execute_single_node`.

### Execution flow

1. `_resolve_and_validate_items` — resolve items template, validate result is a list
2. Initialize `shared["_batch_trace"][node_id] = []` — accumulator for per-item trace events
3. Dispatch to `_execute_sequential` or `_execute_parallel` (both return partial state on fail_fast — they break out of the loop, never raise)
4. `_aggregate_batch_results` — write `shared[node_id]` with standard output shape **BEFORE** any abort-raise. This is load-bearing: step 17.5's `mark_node_failed` archives `data = shared[node_id]`, so anything written here survives into `__failures__[id].data`.
5. `_collect_batch_trace` — transfer trace items from shared store, clean up
6. `_push_batch_warnings` — write to `__warnings__` for DEGRADED status
7. **Then** `execute_batch` raises if fail_fast had errors, or `_aggregate_batch_results` raised at step 4 for all-failed continue mode. The raise always happens AFTER `shared[node_id]` is populated.

### `_execute_batch_item` — unified sequential/parallel

Merges the old `_exec_single` + `_exec_single_with_node` (170 lines of duplication → one function). Key parameters:
- `item_shared`: `None` for sequential (function creates it), pre-created for parallel
- `node`: original for sequential, `copy.deepcopy(node)` for parallel

**CompilationError always fatal** — never swallowed, never retried. All other exceptions go through retry loop.

**Child trace events**: after `execute_single_fn` returns, reads `node._child_trace_events` from `WorkflowExecutor` (sub-workflow in batch) and passes to `_capture_item_trace`.

### Parallel specifics

- Deep-copies bare node per thread (sub-millisecond — nodes have trivial `__init__`)
- Bare `ThreadPoolExecutor` (NOT context manager — `__exit__` calls `shutdown(wait=True)`)
- `pool.shutdown(wait=False, cancel_futures=True)` in `finally`
- `_batch_trace` list append is GIL-protected (CPython only)
- `fail_fast` cancels pending futures but can't interrupt running threads (LLM/HTTP calls)

### Per-worker progress buffer (parallel batch)

Sub-workflow nodes inside a parallel batch create a child `WorkflowEngine` that fires `call_start_callback`/`call_completion_callback` from the **worker thread**. Firing these on the shared `OutputController` concurrently doesn't just corrupt bytes — it swaps semantic labels (valid output, wrong node id attached). A `threading.Lock` wouldn't fix it: `_partial_line_open` tracks *whether* a partial is open, not *whose*.

Pattern: workers produce transcripts, main thread drains atomically.
- `process_item` replaces the inherited `__progress_callback__` in `item_shared` with a per-thread buffering wrapper that captures `(args, kwargs)` tuples. The child engine fires into this local buffer instead of touching the real callback.
- The buffer is returned as the 5th element of the future result.
- `_collect_parallel_results` (main thread) calls `_drain_worker_buffer(real_callback, events)` via `as_completed` **before** `_report_batch_progress`. Single-threaded by construction — one future at a time in the calling thread.
- Recursively correct: nested parallel batches install their own buffers inside worker threads; inner drains flush into outer buffers; the outermost main thread reaches the real `OutputController`. No depth-specific code.

Peak memory is `O(events_per_item x max_concurrent)`. No hard cap today.

### Output shape

`{results, count, success_count, error_count, errors, batch_metadata}`. `results` contains only successful items (failed items filtered out via `error_indices`). `errors` is the authoritative failure record with index, item, and error message per failure. `count` = total items attempted. `success_count` = `len(results)`. `error_count` = `len(errors)`. Verified by `BATCH_OUTPUTS` contract in `template_validation/validator.py`.

## Instrumentation (`instrumentation.py`)

### Execution state

- `initialize_execution_state(shared)` — ensure `__execution__` + `__cache_hits__` exist
- `enforce_loop_guard(node_id, shared)` → `visit_counts` dict. Raises `MaxNodeVisitsError` at 100 visits (configurable via `PFLOW_MAX_NODE_VISITS` env var). Invalidates in-process cache for revisited nodes (loops) and calls `clear_node_failure` on loop re-entry so the new attempt starts with a clean state.
- `cache_result(node_id, hash, action, shared)` — for non-error actions only adds to `completed_nodes`. For error actions it's a **no-op** (the canonical failure write happens at engine step 17.5 via `mark_node_failed`). Direct writes to `failed_node` from anywhere except `mark_node_failed` are contract violations.
- `handle_api_warning(...)` — records trace + metrics + completion callback, then archives via `mark_node_failed` at the END (so all bookkeeping reads `shared[id]` first). Uses `mark_node_failed` for the warning + failed_node writes, no direct writes.
- `handle_cached_execution(...)` — no longer defensively clears `__failures__`. Both cache paths (memo + in-process) are unreachable for nodes with a stale failure record: memo cache is skipped on revisits; the in-process path runs after `enforce_loop_guard` has already cleared failures; error results are never cached. If future work makes this reachable (e.g. checkpoint-resume seeding shared state), add the clear back with a test that exercises the reaching path.

### Two-level caching

**In-process cache** (`check_cache_validity`, `cache_result`, `invalidate_cache`): Node completed in THIS run with matching config hash → skip re-execution. For workflow resume.

**Memo cache** (`check_memo_cache`, `write_memo_cache`): Cross-run SQLite cache. Key = `hash(config + resolved_params)`. Batch key uses `resolve_batch_items() + semantic_config`. **Skipped for**: revisited nodes (`visit_count > 1`), `WorkflowExecutor` (sub-workflow files may change), error results.

**`handle_cached_execution`** — shared by BOTH cache levels. Records trace with `cached=True`, populates `__cache_hits__`, calls progress callbacks (`node_start` + `node_cached`).

### `compute_node_config` → `compute_config_hash`

Builds a deterministic config dict for cache key computation:
- `type`: node class name
- `params`: static params (with `_source_line` keys filtered out)
- `template_params`: raw template strings (changing `${old}` to `${new}` invalidates cache)
- `batch`: semantic config only (`items_template`, `item_alias`, `error_handling`, `max_retries` — NOT `parallel`, `max_concurrent`, `retry_wait`)

### Trace and metrics

- `record_trace(...)` — receives all data directly (no chain traversal). Computes shared store mutations (added/removed keys, system keys filtered). `success` parameter takes precedence over `error is None`.
- `enrich_llm_cost(node_id, shared)` — checks both root and namespaced locations for `llm_usage`
- **LLM trace_hook plumbing**: Engine.run installs `self.trace` into `shared["__trace_collector__"]` for the duration of the run (save+restore handles nested sub-workflow runs). LLMNode.prep reads the collector + `self.node_id` from shared, builds the per-call trace hook via `collector.get_trace_hook(node_id)`, stores it in `prep_res["_trace_hook"]`. LLMNode.exec captures the hook before submitting to its inner ThreadPoolExecutor — explicit-arg passing survives the worker-thread boundary, unlike the previous thread-local registry approach.

### Progress callbacks

All emitters wrap the callback in `contextlib.suppress(Exception)` so rendering bugs can't crash execution.

- `call_start_callback` → `node_start`.
- `call_completion_callback` → `node_complete`. Reads `batch_metadata`, `smart_handled`, and `smart_handled_reason` from the node output namespace (via `NamespacedSharedStore` rewriting — `shared[node_id][key]`). Shell nodes write `smart_handled=True` + reason string to signal safe non-error exits; reason strings MUST contain `"no matches"` or `"not found"` for the tag mapping in `OutputController._build_smart_handled_tag` to fire (contract pinned in `shell.py`).
- `handle_api_warning` → `node_warning`. Warning text flows through the `error_message` kwarg; do NOT pass strings via `duration_ms` (that was a smuggler pattern; the receiving end no longer tolerates it).
- `handle_cached_execution` fires `node_start` then `node_cached` as a pair from the main thread — the callback sees both events for a single cached node.

## Utility Files

### `api_warning_detector.py` (449 lines)

Classifies node output as API warning based on 93+ patterns. See `runtime/CLAUDE.md` "Error Categorization" for the pattern categories and ambiguity rule. Key function: `detect_api_warning(node_id, shared) → Optional[str]`.

### `template_errors.py`

Builds structured `Diagnostic` objects for unresolved template variables. Key functions:
- `build_template_error_diagnostic(param_key, template, context, *, node_id, source_file, source_line)` → `Diagnostic` with `category="template_error"` and `unresolved_references` in context. Used by both strict mode (raised `ValueError` carries the diagnostic via `_pflow_template_diagnostic`) and permissive mode (stored in `__template_errors__[node_id]["diagnostic"]`).
- `classify_unresolved_references(template, context)` — returns a list of per-reference dicts with `status` (`absent`/`failed`/`path_error`), category-aware failure detail, peer suggestions, typo hints (`did_you_mean`), and `corrected_var` (used for paste-able fixes when both a typo AND a failure exist on the same node).
- `build_type_error_message(...)` — dict/list received where string expected (returns plain string, not a Diagnostic)
- `build_json_parse_error_message(...)` — string that looks like JSON but failed to parse (returns plain string)

The structured `Diagnostic` carries all rich data in `context.unresolved_references`. Text rendering is a pure function of the context — see `_format_template_error_lines` in `core/diagnostic_render.py`. JSON/MCP consumers read the structure directly via `Diagnostic.to_dict()`.

### `namespaced_store.py`

`NamespacedSharedStore` — dict proxy that routes writes to `parent[namespace][key]`. Special `__*__` keys bypass namespacing (read/write at root). `__init__` eagerly creates `parent[namespace] = {}` even before any write — meaning a node that fails before writing anything still has an empty dict at root. Step 17.5's `mark_node_failed` archives this empty dict to `__failures__[id].data = {}`, which is correct (the failure record exists, just with no captured data).

`update()` is a required override (not inherited from `dict`) — without it, `storage_mode: shared` sub-workflows crash when the child engine calls `shared_store.update(...)`. Any new proxy subclass must override `update()`, `__contains__`, `get()`, and the mutation methods explicitly.

### `error_context.py` (92 lines)

`get_upstream_stderr(template_str, context)` — extracts stderr from upstream shell nodes referenced in a template. Appended to error messages for "shell command failed, here's what it said" context.

## Cross-Module Dependencies

- `runtime/template_resolver.py`: used by `template_resolution.py` and `batch_executor.py`
- `runtime/cache.py`: used by `instrumentation.py` (`_deterministic_json`, `compute_node_cache_key`, `compute_batch_cache_key`)
- `core/json_utils.py`: used by `template_resolution.py`, `batch_executor.py`
- `core/param_coercion.py`: used by `template_resolution.py`
- `core/llm_client.py`: `enrich_llm_usage_with_cost` used by `instrumentation.py`, `batch_executor.py` (cost-key normalization; cost values come from LiteLLM via the adapter)
- `core/exceptions.py`: `CompilationError`, `MaxNodeVisitsError`

## Gotchas

- **Step 17.5 is the only place that archives action="error" failures.** Don't add direct writes to `__failures__` elsewhere — they'll drift from the canonical record shape and break the "single write site" guarantee.
- **`_handle_no_successor` must check `get_node_failure` first** before re-archiving. Step 17.5 may have already archived with the real category and data; a second `mark_node_failed` call would `pop` an already-empty `shared[id]` and overwrite the rich record with `{data: {}, category: routing_error}`.
- **Exception annotation pattern** (load-bearing — survives across the engine→runner→formatter boundary): all annotations listed in `_PFLOW_EXCEPTION_ANNOTATIONS` (`core/exceptions.py`). `raise X from e` LOSES these — use `copy_pflow_annotations(source, target)` when wrapping. Readers use `getattr(e, "_pflow_*", None)`.
- **Batch fail_fast raises in `execute_batch`, NOT in `_execute_sequential`/`_execute_parallel`.** The inner functions break out of their loops on first failure and return partial state. The raise happens AFTER `_aggregate_batch_results` writes `shared[node_id]` so step 17.5 can archive the metadata.
- **Steps 1-4 are outside try, 5-17.5 inside try** in `_execute_node`. Config hash (step 4) runs before template resolution (step 5) because it doesn't need resolved params.
- **Batch nodes skip top-level template resolution** — per-item resolution in callback instead.
- **`_source_line` keys NOT filtered in `split_params()`** — `python_code.py` reads them. Filtered only in `compute_node_config()` for cache hashing.
- **Engine doesn't restore `node.params`** — intentional. Each execution sets params fresh.
- **`handle_cached_execution` serves both cache levels** — memo (SQLite) and in-process (resume). Defensively clears `__failures__[id]` before restoring.
- **Parallel batch deep-copies bare node** — cheap, but `_batch_trace` list append relies on GIL (CPython only).
- **`CompiledWorkflow` is NOT concurrent-safe** — `node.params` mutation means one `engine.run()` at a time per workflow instance.
