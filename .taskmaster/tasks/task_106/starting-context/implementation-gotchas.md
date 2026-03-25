# Task 106: Implementation Gotchas

Things the task spec doesn't cover that will save you debugging time.

## Shared Store Key Naming — Don't Use Dunders

`_sanitize_for_json()` in `workflow_trace.py` strips keys from trace events:
- All `__dunder__` keys (except `__metrics__`)
- Keys starting with `_trace`, `_debug`, `_batch_trace`

If you add cache state to the shared store (e.g., a cache context object), use a prefix that won't be filtered. Example: `_memoization_cache` or `_cache_context`. If you must use a filtered prefix, add it to the sanitization allowlist.

The `_PROPAGATED_KEYS` in `WorkflowExecutor` uses single-underscore keys (`_trace_collector`). Follow this pattern if the cache needs state propagated to sub-workflows.

## Trace/Report Integration Is Already Done

`_handle_cached_execution()` in `instrumented_wrapper.py` already:
- Records trace event with `cached=True` and `duration_ms=0`
- Fires progress callbacks (`node_start` → `node_cached`)
- Tracks cache hits in `shared["__cache_hits__"]`
- The execution report renders these as `[cached]` in `_format_node_metadata()`

**Don't re-implement any of this.** Just ensure `shared[self.node_id]` contains the cached output BEFORE `_handle_cached_execution()` runs — it reads `node_output` from there for the trace event.

## Cached Output Must Be Restored to Shared Store

The existing `_handle_cached_execution()` returns early — the node's `prep()`, `exec()`, and `post()` never run. Downstream nodes read upstream data via template resolution (`${upstream_node.field}`), which resolves against the shared store.

If you serve a node from cache but don't put its output in `shared[node_id]`, downstream template resolution will fail with "variable not found."

## Side Effects: Cache Everything

The user's explicit preference: cache ALL nodes, including side-effect nodes (file writes, HTTP POSTs, GitHub issue creation). During iteration, you don't want side effects repeated. When the user needs side effects to actually happen (e.g., final run), they use `--no-cache`.

Don't add special "side-effect-aware" logic or node-type-based cache exclusions.

## Cost Tracking for Cached Nodes

Cached nodes should NOT contribute to cost metrics for the run. Cost tracking flows through trace events via `_enrich_llm_cost()` → `_record_trace()` → `WorkflowTraceCollector.collect_llm_calls()`. The `cached=True` trace events don't include `llm_call` data, so this works correctly as long as you use `_handle_cached_execution()`.

## Trace Collector Always Exists

`executor_service.py` auto-creates a `WorkflowTraceCollector` when none is provided. `--no-trace` only skips the file write, not in-memory collection. You can always count on `shared["_trace_collector"]` existing. No need for None checks.

## Parallelism Preservation

Batch nodes running sub-workflows in parallel (`parallel: true`) should maintain parallel execution for items that need re-execution. The cache shouldn't force serial execution. Since each batch item is independent (separate `item_shared` context), this should work naturally — each item independently checks its own cache.

## `storage_mode="shared"` Sub-Workflows

In shared storage mode, the child workflow shares the parent's entire store (no isolation). Caching is probably not meaningful here — the child can read/write anything in the parent's store. Consider skipping cache for shared-mode sub-workflows. Check `prep_res.get("storage_mode", "mapped")` in `WorkflowExecutor`.

## What Should NOT Invalidate Cache

- **Markdown prose**: Editing a node's description text (the prose above the YAML params) is cosmetic — not execution-relevant
- **Output file changes**: Manually editing files in the output directory doesn't affect pipeline execution
- **`_source_lines` metadata**: Line numbers from the markdown parser are injected into params as `_<key>_source_line`. These are in the current config hash but are noise — adding a blank line to the `.pflow.md` file changes line numbers and would invalidate cache. Exclude these from the config hash.

## MCP Nodes and External State

MCP nodes call external servers whose state may change between runs. They're fundamentally hard to cache correctly. For MVP, cache them like any other node. The `--no-cache` flag handles the "external state changed" case. Don't add special MCP-aware logic.

## File Content Is Already Inlined (Partially)

The file resolver (`core/file_resolver.py`) runs at compile time and replaces file paths with content in IR params. BUT:
- **Static params** (no `${...}`): file content lands on the inner node's `.params` — available for hashing
- **Template params** (contain `${...}`): file content lands on `TemplateAwareNodeWrapper.template_params` — NOT on the inner node. The current `_compute_node_config()` misses these entirely.

Both must be included in the config hash. The `_source_files` provenance dict on IR nodes (e.g., `{"prompt": "./write-lyrics.prompt.md"}`) records which params came from files — useful for cache invalidation debugging messages.

## `allow_interspersed_args=True`

The CLI already supports interspersed args (set during Task 108). New flags (`--no-cache`, `--only`) can be placed before or after the workflow argument without issues.
