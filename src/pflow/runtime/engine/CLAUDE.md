# Engine Module

Orchestration engine that replaces the 4-layer wrapper chain. Handles graph traversal and all runtime concerns: template resolution, namespacing, batch processing, instrumentation (caching, tracing, metrics, progress callbacks).

## File Structure

```
src/pflow/runtime/engine/
├── __init__.py              # Exports: CompiledWorkflow, WorkflowEngine, type classes
├── engine.py                # WorkflowEngine — graph walker + per-node orchestration
├── types.py                 # CompiledWorkflow, NodeConfig, TemplateConfig, BatchConfig
├── template_resolution.py   # Standalone template resolution functions
├── batch_executor.py        # Standalone batch execution functions
├── instrumentation.py       # Standalone instrumentation functions (cache, trace, metrics)
├── namespaced_store.py      # NamespacedSharedStore proxy for per-node store isolation
├── api_warning_detector.py  # API error classification (standalone functions)
├── template_errors.py       # Template error message formatting (standalone functions)
└── error_context.py         # Upstream stderr extraction for error enrichment
```

## Architecture

```
compile_workflow(ir, registry, initial_params) → CompiledWorkflow
  ├── start_node: bare BaseNode/Node instance (first node in graph)
  ├── node_configs: {node_id: NodeConfig}  — per-node metadata
  ├── outputs: declared workflow outputs
  ├── resolved_defaults: from prepare_inputs()
  └── env_param_names: params that came from environment

WorkflowEngine(metrics, trace, only_node).run(workflow, shared) → action
  └── for each node (while curr):
      _execute_node(node, config, shared) → action
        1. LLM interception setup
        2. Execution state init
        3. Loop guard (visit count, max visits)
        4. Template resolution (if config.template_config and not batch)
        5. Memo cache check (cross-run SQLite)
        6. In-process cache check (within-run resume)
        7. Progress callback (node_start)
        8. Execute: batch → execute_batch() | single → node._run()
        9. API warning detection
        10-15. Post-execution: cache, memo write, metrics, cost, trace, callback
```

## Key Design Decisions

1. **`_execute_single_node` returns a tuple** `(action, last_resolutions, template_errors)` — NO instance state on the engine. Safe for parallel batch (each thread calls the same function with different data).

2. **Shared store is the single source of runtime data** — no `initial_params` override. The old wrapper's `_build_resolution_context` merged `initial_params` over the shared store. Now `resolved_defaults` are seeded into shared store before engine starts.

3. **Batch nodes skip top-level template resolution** — `_execute_node` has `if config.template_config and not config.batch_config` guard. Without this, `${item}` would fail before the batch loop starts. The batch executor's `_execute_single_node` callback handles per-item resolution.

4. **Engine does NOT restore node.params** — the old wrapper swapped params in `_run()` and restored in `finally`. The engine sets `node.params = resolved_params` permanently. Safe because: nodes are visited once per traversal (loops re-resolve), batch items use the callback which sets params per item.

## WorkflowEngine (`engine.py`)

Stateless executor. No per-node instance state.

- `run(workflow, shared)` — walk graph, call `_execute_node` per node, follow successor edges, populate outputs
- `_execute_node(node, config, shared)` — full orchestration: template resolution → caching → execution → tracing
- `_execute_single_node(node, config, shared)` — resolve templates + execute for non-batch nodes (also used as callback by batch executor)

## Types (`types.py`)

- **`CompiledWorkflow`** — structural result from `compile_workflow()`. Reusable for sequential batch items. NOT safe for concurrent `engine.run()` calls (node.params mutated).
- **`NodeConfig`** — per-node metadata: template config, batch config, namespacing flag, interface metadata
- **`TemplateConfig`** — template vs static param split, expected types, resolution mode
- **`BatchConfig`** — items template, alias, error handling, parallel, concurrency, retry settings

## Template Resolution (`template_resolution.py`)

Standalone functions extracted from `TemplateAwareNodeWrapper`:

- `build_type_cache(interface_metadata)` — extract param→type from registry metadata
- `split_params(params, expected_types)` — separate template vs static params
- `resolve_templates(config, shared, node_id)` — resolve all template params, return `(merged, resolutions, errors)`
- `validate_resolved_type(key, value, template, types, mode)` — type validation, returns error string or None
- `contains_unresolved_template(value, template)` — detect partial resolution
- `inject_none_for_optional_inputs(key, value, template, context, keys)` — branch convergence

**Context building**: `context = dict(shared)` — NO `initial_params` override.

**`inputs` processed first**: resolved input values merged into context before other params, enabling `${text}` after `inputs.text` is resolved.

**`__PERMISSIVE_TYPE_ERROR__` prefix eliminated**: `validate_resolved_type()` returns `Optional[str]`. Caller decides whether to raise or store.

## Batch Executor (`batch_executor.py`)

Standalone functions extracted from `PflowBatchNode`:

- `execute_batch(node, config, shared, execute_single_fn)` — main entry, returns `(action, batch_trace_items)`
- `_execute_batch_item(...)` — unified sequential/parallel item execution with retry
- `_execute_sequential(...)` / `_execute_parallel(...)` — dispatch
- `_aggregate_batch_results(...)` — write `shared[node_id]` with standard output shape

**Parallel path**: deep-copies bare node per thread (cheap). Uses bare `ThreadPoolExecutor` + `shutdown(wait=False, cancel_futures=True)`.

**Output shape**: `{results, count, success_count, error_count, errors, batch_metadata}` — identical to old `PflowBatchNode.post()`.

## Instrumentation (`instrumentation.py`)

Standalone functions extracted from `InstrumentedNodeWrapper`:

- **Execution state**: `initialize_execution_state()`, `enforce_loop_guard()`
- **In-process cache**: `check_cache_validity()`, `cache_result()`, `invalidate_cache()`
- **Memo cache**: `compute_node_config()`, `compute_config_hash()`, `check_memo_cache()`, `write_memo_cache()`
- **Trace**: `record_trace()`, `enrich_llm_cost()`, `setup_llm_interception()`
- **Progress**: `call_start_callback()`, `call_completion_callback()`
- **API warning**: `handle_api_warning()`

## Cross-Module Dependencies

- `template_resolver.py` (parent `runtime/`): used by `template_resolution.py` for `TemplateResolver`
- `cache.py` (parent `runtime/`): used by `instrumentation.py` for memo cache
- `core/json_utils.py`: used by `template_resolution.py`, `batch_executor.py`
- `core/param_coercion.py`: used by `template_resolution.py`
- `core/llm_pricing.py`: used by `instrumentation.py`, `batch_executor.py`
- `core/exceptions.py`: `CompilationError` (canonical location)

## Gotchas

- **Batch nodes skip top-level template resolution** — `_execute_node` guards on `not config.batch_config`
- **`_source_line` keys are NOT filtered in `split_params()`** — `python_code.py` reads them for error line numbers
- **Compile-once `id()` check** in WorkflowExecutor only works for static `workflow_ir` — template expressions in IR create new dicts per item
- **Engine doesn't restore node.params** — intentional, see design decisions above
- **Parallel batch: each thread deep-copies the bare node** — cheap compared to deep-copying wrapper chains
