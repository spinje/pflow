# Engine Module

Orchestration engine that handles graph traversal and all runtime concerns: template resolution, namespacing, batch processing, instrumentation (caching, tracing, metrics, progress callbacks).

## File Structure

```
src/pflow/runtime/engine/
├── __init__.py              # Exports: CompiledWorkflow, WorkflowEngine, type classes
├── engine.py                # WorkflowEngine — graph walker + per-node orchestration (328 lines)
├── types.py                 # CompiledWorkflow, NodeConfig, TemplateConfig, BatchConfig (59 lines)
├── template_resolution.py   # Standalone template resolution functions (413 lines)
├── batch_executor.py        # Standalone batch execution functions (630 lines)
├── instrumentation.py       # Cache, trace, metrics, progress, loop guards (502 lines)
├── namespaced_store.py      # NamespacedSharedStore proxy for per-node store isolation (191 lines)
├── api_warning_detector.py  # API error classification — 73 validation + 20 resource patterns (449 lines)
├── template_errors.py       # Template error formatting with coalesce diagnosis, "did you mean" (388 lines)
└── error_context.py         # Upstream stderr extraction for error enrichment (92 lines)
```

## Architecture

```
WorkflowEngine(metrics, trace, only_node).run(workflow, shared) → action_string
  └── for each node in graph:
      _execute_node(node, config, shared) → action
        ┌─ OUTSIDE try (always runs):
        │  1. setup_llm_interception
        │  2. initialize_execution_state
        │  3. enforce_loop_guard
        │  4. compute_config_hash (doesn't need resolved params)
        │
        ├─ INSIDE try (template errors get trace recording):
        │  5. resolve_templates (SKIP for batch nodes — per-item in callback)
        │  6. check_memo_cache → early return (SKIP when cache_enabled=False)
        │  7. check_cache_validity → early return via handle_cached_execution
        │  8. call_start_callback
        │  9. execute: batch → execute_batch() | single → node._run(namespaced_store)
        │  10. detect_api_warning → handle_api_warning if found
        │  11. cache_result, 12. write_memo_cache (SKIP when cache_enabled=False),
        │  13-17. duration, metrics, enrich_llm_cost, record_trace, call_completion_callback
        │
        └─ EXCEPT (error path — ~30% of _execute_node):
           metrics, enrich_llm_cost, record_trace(error=e),
           call_completion_callback(action="error"),
           set failed_node, annotate e._pflow_node_id, re-raise
```

**Note**: Steps 1-4 run outside the try block (always execute). Steps 5-17 are inside try so template errors get trace recording. Config hash (step 4) is computed before template resolution (step 5) because it doesn't depend on resolved params.

## Key Design Decisions

1. **`_execute_single_node` returns `(action, last_resolutions, template_errors)`** — NO instance state on the engine. This prevents data races in parallel batch where multiple threads call the same function concurrently.

2. **Shared store is the single source of runtime data** — no `initial_params` override. `resolved_defaults` are seeded into shared store by the Runner/WorkflowExecutor before `engine.run()`.

3. **Batch nodes skip top-level template resolution** — `_execute_node` guards on `if config.template_config and not config.batch_config`. Without this, `${item}` would fail before the batch loop starts. Per-item resolution happens via the `_execute_single_node` callback.

4. **Engine does NOT restore node.params** — sets `node.params = resolved_params` permanently. Safe because: each node is visited once per traversal (loops re-resolve), batch items use the callback which sets params per item.

5. **Template resolution inside try block** — so that strict-mode `ValueError` gets trace recording on the error path. `resolve_templates` attaches `._partial_resolutions` to the exception (non-standard, but needed for trace to show what resolved before the error).

6. **`record_trace` has explicit `success` parameter** — nodes returning `"error"` action (without raising) need `success=False` in the trace. Without explicit `success`, `error is None` → `success=True` would be wrong. Engine passes `success=not str(action).startswith("error")`.

## WorkflowEngine (`engine.py`)

Stateless executor. No per-node instance state.

### `run(workflow, shared) → str`

1. Validates `--only` target exists (raises `CompilationError` if not)
2. Resets `node_visit_counts`
3. Walks graph: `_execute_node` per node, follows `curr.successors.get(action or "default")`
4. On unmatched action: writes to `__warnings__` (visible in JSON output, unlike `warnings.warn`)
5. On `--only`: stops after target node, sets `__execution__["only_node"]`
6. On success: calls `populate_declared_outputs` (skipped on error or `--only`)

### `_execute_node(node, config, shared) → str`

The 17-step orchestration. Two paths:
- **Happy path**: steps 1-17, returns action string
- **Error path**: catches exception, records metrics/trace/callback with error info, annotates exception with `_pflow_node_id`, re-raises

**Error path details** (unintuitive — an agent modifying this must preserve all of these):
- `getattr(e, "_partial_resolutions", None)` extracts template resolutions that happened before the error (attached by `resolve_templates`)
- `call_completion_callback(..., action="error", error=e)` — without this, the progress spinner shows the failed node as still "running"
- `e._pflow_node_id = config.node_id` — the Runner's `_exception_to_result` reads this to include `node_id` in the error dict

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

**Strict mode**: raises `ValueError` with `._partial_resolutions` attribute (dict of params resolved before the error). The engine's except handler extracts these for trace recording.

**Permissive mode**: returns errors in `template_errors` list. Each error is a dict with `message`, `type`/`unresolved`, `param`/`template`. The engine writes them to `shared["__template_errors__"][node_id]`.

## Batch Executor (`batch_executor.py`)

### `execute_batch(node, config, shared, execute_single_fn) → (action, batch_trace_items)`

The `execute_single_fn` callback signature: `(node, config, item_shared) → (action, last_resolutions, template_errors)`. This is `engine._execute_single_node`.

### Execution flow

1. `_resolve_and_validate_items` — resolve items template, validate result is a list
2. Initialize `shared["_batch_trace"][node_id] = []` — accumulator for per-item trace events
3. Dispatch to `_execute_sequential` or `_execute_parallel`
4. `_aggregate_batch_results` — write `shared[node_id]` with standard output shape
5. `_collect_batch_trace` — transfer trace items from shared store, clean up
6. `_push_batch_warnings` — write to `__warnings__` for DEGRADED status

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

### Output shape

`{results, count, success_count, error_count, errors, batch_metadata}` — identical to old `PflowBatchNode.post()`. Verified by `BATCH_OUTPUTS` contract in `template_validation/validator.py`.

## Instrumentation (`instrumentation.py`)

### Execution state

- `initialize_execution_state(shared)` — ensure `__execution__` + `__cache_hits__` exist
- `enforce_loop_guard(node_id, shared)` → `visit_counts` dict. Raises `MaxNodeVisitsError` at 100 visits (configurable via `PFLOW_MAX_NODE_VISITS` env var). Invalidates in-process cache for revisited nodes (loops).

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
- `setup_llm_interception(...)` — activates if trace collector present AND (class name contains "llm" OR params contain "prompt"/"model"). **Known limitation**: if `prompt` is in template_params (not static), the params check misses it — the class name fallback catches LLM nodes.

### Progress callbacks

- `call_start_callback` — `node_start` event
- `call_completion_callback` — `node_complete` with duration, error info, batch metadata. Detects batch nodes by checking for `batch_metadata` key in output.

## Utility Files

### `api_warning_detector.py` (449 lines)

Classifies node output as API warning based on 93+ patterns. See `runtime/CLAUDE.md` "Error Categorization" for the pattern categories and ambiguity rule. Key function: `detect_api_warning(node_id, shared) → Optional[str]`.

### `template_errors.py` (388 lines)

Error message formatting for template resolution failures. Key functions:
- `build_enhanced_template_error(key, template, context)` — the gold-standard error message: available context keys with type previews, coalesce diagnosis ("node X did not execute" vs "executed but path Y not found"), JSON parse hints, "did you mean" suggestions
- `build_type_error_message(...)` — dict/list received where string expected
- `build_json_parse_error_message(...)` — string that looks like JSON but failed to parse

### `namespaced_store.py` (191 lines)

`NamespacedSharedStore` — dict proxy that routes writes to `parent[namespace][key]`. Special `__*__` keys bypass namespacing (read/write at root). Has `update()` method (added in Task 135 — without it, `storage_mode: shared` sub-workflows crash).

### `error_context.py` (92 lines)

`get_upstream_stderr(template_str, context)` — extracts stderr from upstream shell nodes referenced in a template. Appended to error messages for "shell command failed, here's what it said" context.

## Cross-Module Dependencies

- `runtime/template_resolver.py`: used by `template_resolution.py` and `batch_executor.py`
- `runtime/cache.py`: used by `instrumentation.py` (`_deterministic_json`, `compute_node_cache_key`, `compute_batch_cache_key`)
- `core/json_utils.py`: used by `template_resolution.py`, `batch_executor.py`
- `core/param_coercion.py`: used by `template_resolution.py`
- `core/llm_pricing.py`: used by `instrumentation.py`, `batch_executor.py`
- `core/exceptions.py`: `CompilationError`, `MaxNodeVisitsError`

## Gotchas

- **Steps 1-4 are outside try, 5-17 inside try** in `_execute_node`. Config hash (step 4) runs before template resolution (step 5) because it doesn't need resolved params.
- **Batch nodes skip top-level template resolution** — per-item resolution in callback instead.
- **`_source_line` keys NOT filtered in `split_params()`** — `python_code.py` reads them. Filtered only in `compute_node_config()` for cache hashing.
- **`._partial_resolutions` on exceptions** — non-standard Python pattern. `resolve_templates` attaches this to `ValueError` so the engine can include partial template data in error traces.
- **Engine doesn't restore `node.params`** — intentional. Each execution sets params fresh.
- **`handle_cached_execution` serves both cache levels** — memo (SQLite) and in-process (resume).
- **Parallel batch deep-copies bare node** — cheap, but `_batch_trace` list append relies on GIL (CPython only).
- **`CompiledWorkflow` is NOT concurrent-safe** — `node.params` mutation means one `engine.run()` at a time per workflow instance.
