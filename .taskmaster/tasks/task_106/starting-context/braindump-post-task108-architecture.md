# Braindump: Architecture State After Task 108 — What Task 106 Needs to Know

**Date:** 2026-03-23
**Context:** Just completed Task 108 (Smart Trace Debug Output) — Phases 1, 1.5, 2, D1-D10, docs cleanup. The trace/execution system has been significantly restructured. This braindump captures what changed and how it affects Task 106 (Iteration Cache).

## Where I Am

Task 108 is complete. The trace system was redesigned from the ground up. Several changes directly affect how Task 106 should be implemented. The user wants to start Task 106 next.

## User's Mental Model

The user sees Task 106 and Task 108 as two halves of the same story:
- **Task 108 (Report)**: "See what happened" — makes results understandable
- **Task 106 (Cache)**: "Don't repeat unchanged work" — makes iteration fast
- **Together**: Edit prompt → re-run (cached upstream) → read report (focus on re-executed nodes) → iterate

The user's exact framing: "Cache makes iteration FASTER, Report makes results UNDERSTANDABLE."

They also see the git diff workflow as central to both features: write report to a folder, stage it, edit prompt, re-run with cache (only downstream re-executes), `git diff report/` shows what changed. The report marks `[cached]` nodes so the agent knows where to focus.

The user thinks about cache invalidation in terms of **file content hashing** — prompt files and sub-workflow files must be hashed, not just the YAML config. They said: "If I edit `write-lyrics.prompt.md`, the node's YAML config hasn't changed — it still says `prompt: ./write-lyrics.prompt.md`. But the content of that file has changed."

## Key Architectural Changes from Task 108

### 1. `__llm_calls__` accumulator is GONE

Phase 1.5 removed the entire `__llm_calls__` system. Cost tracking now flows through trace events exclusively:
- `InstrumentedNodeWrapper._enrich_llm_cost(shared)` adds `cost_usd` to `llm_usage` before `_record_trace()`
- `WorkflowTraceCollector.collect_llm_calls()` walks the event tree recursively to get all LLM call data
- `MetricsCollector.get_summary()` receives this flat list for cost display
- `__llm_calls__` is NOT in `_PROPAGATED_KEYS` anymore

**Impact on Task 106**: If the cache needs to know cost of cached nodes, it comes from trace events. There's no accumulator to check.

### 2. Trace collector is ALWAYS created

`executor_service.py` now auto-creates a `WorkflowTraceCollector` when none is provided. `--no-trace` only skips the file write (gated in `_save_trace_and_report()`), not the in-memory collection.

**Impact on Task 106**: You can always count on `shared["_trace_collector"]` existing. The cache system doesn't need to handle the case where tracing is disabled.

### 3. `_trace_collector` is in shared store and propagated

Added to `_PROPAGATED_KEYS` in `WorkflowExecutor`. Sub-workflows get child collectors with `enable_llm_interception=False`. The parent's `InstrumentedNodeWrapper` embeds child events via `_child_trace_events`.

**Impact on Task 106**: When implementing cache, `_trace_collector` is already flowing through the system. You might want `_cache_context` or similar to follow the same propagation pattern.

### 4. Cached nodes already record trace events (D5)

`InstrumentedNodeWrapper._handle_cached_execution()` now calls `_record_trace()` with `cached=True` and `duration_ms=0`. The report shows these as `[cached]` in status.

**Impact on Task 106**: The trace/report integration for cached nodes is ALREADY DONE. Task 106 just needs to ensure the existing `_handle_cached_execution()` path is triggered correctly when serving from cache. The `node_output` for cached events comes from `shared[self.node_id]` which should contain the cached output.

### 5. `shared_before` full-store snapshot is gone from traces

Replaced with `node_output` (just this node's namespace), `template_resolutions`, `node_params`, `mutations` (key-set diff only, no value comparison). The full `dict(shared)` copy still happens in `_run()` but only for `_find_llm_prompt()` legacy path (which was also removed in Phase 1.5).

**Impact on Task 106**: The cache system doesn't need to worry about trace snapshots being expensive. Each node's trace event is O(node output size), not O(total accumulated store size).

### 6. Trace format is now 2.0.0 (tree-structured)

Events are nested: batch items have per-item events, sub-workflow nodes have child events. The trace mirrors the execution tree.

**Impact on Task 106**: If cache stores/restores trace data, it needs to handle the tree structure. But more likely, cached nodes just record a minimal `cached: true` event (which is already implemented).

## What The Agent-Perspective Doc Says (Key Points)

I read `.taskmaster/tasks/task_106/starting-context/pflow-iteration-cache-agent-perspective.md` in detail. The most important points that aren't obvious:

1. **External file content hashing is the #1 correctness concern.** `- prompt: ./write-lyrics.prompt.md` means the config hash must include the FILE CONTENT, not just the path string. Same for sub-workflow files referenced by workflow nodes.

2. **Sub-workflow file hashing is recursive.** If `song-creator.pflow.md` references `chorus-chooser.pflow.md` which references `select-chorus.prompt.md`, ALL of these must be hashed. A change to any of them invalidates the parent cache.

3. **LLM nodes don't use `- inputs:`.** They resolve `${template_variables}` directly from shared state. `run-step` for LLM nodes needs to parse the prompt for template variables and place values in the shared store, not map to `inputs` params.

4. **Per-item batch caching is explicitly deferred.** The spec says "cache entire batch result, not individual items." The agent-perspective doc argues per-item would be more valuable but accepts the tradeoff. Design the data model to support per-item later.

5. **Cache + report interaction**: The report should indicate cached vs re-executed nodes. This is DONE — `[cached]` rendering exists. The cache should also store rendered prompts so the report can show them for cached nodes.

6. **`--no-cache` / `--fresh` flag** is essential as an escape hatch. When a node "succeeded" but produced bad output, the user needs to force re-execution.

## Assumptions & Uncertainties

**ASSUMPTION**: The existing `_handle_cached_execution()` in `InstrumentedNodeWrapper` (lines ~541-565) is where Task 106's cache integration point is. When the cache system determines a node can be served from cache, it should set up the shared store with cached data and let `_handle_cached_execution()` handle the rest (trace event, return cached action).

**ASSUMPTION**: The `_check_cache_validity()` method (line ~628 in `_run()`) is the hook point. Currently it checks `__execution__` for completed nodes (loop detection). Task 106 would extend this with actual cache lookup.

**NEEDS VERIFICATION**: How does the current `_check_cache_validity()` work? Is it the right place to add cache lookup, or should the cache check happen earlier (before the wrapper chain runs)?

**UNCLEAR**: Should cached node output be re-injected into the shared store before downstream nodes run? Or does the cache system replay the entire execution result? The existing `_handle_cached_execution()` returns early, which means the node's `post()` never runs — so whatever the cached output is, it needs to be placed in `shared[node_id]` before the next node starts.

**UNCLEAR**: How does the file resolver interact with cache invalidation? External file references are resolved during compilation (`file_resolver.py:resolve_file_references()`). By compile time, `params["prompt"]` already contains the file content. So the cache hash could include `params["prompt"]` (which has the file content) rather than separately hashing the file. But compilation happens once per run — if you edit a prompt file between runs, the NEW content is only loaded on the next compilation.

## Unexplored Territory

**UNEXPLORED**: How does the cache interact with MCP nodes? MCP nodes call external servers. The cache would need to know if the MCP server's state has changed. This might be fundamentally uncacheable.

**UNEXPLORED**: How does the cache interact with `error_handling: continue` in batch nodes? If one batch item fails and is re-run, should only that item's cache be invalidated? This intersects with the "per-item batch caching" decision.

**CONSIDER**: The trace collector is now always present in the shared store. Could the cache use the trace collector to record cache hit/miss metadata? E.g., `trace.record_cache_event(node_id, hit=True, reason="config_unchanged")`.

**CONSIDER**: The `template_resolutions` field in trace events shows what each template resolved to. For cache invalidation, you could compare the current `template_resolutions` against the cached ones to detect input changes. But this only works AFTER resolution — you'd need to resolve templates to check the cache, which partially defeats the purpose.

**MIGHT MATTER**: The `_batch_trace` accumulator pattern (shared mutable list in `self._shared`) used for per-batch-item trace collection could be reused for cache. E.g., `_batch_cache` could track per-item cache hits in the same pattern.

**MIGHT MATTER**: The `__execution__` state in the shared store tracks `completed_nodes` and `node_hashes`. This is used for loop detection but could be extended for cache tracking. Currently initialized in `_initialize_execution_state()`.

## What I'd Tell Myself

1. **Read the existing `_handle_cached_execution()` and `_check_cache_validity()` in `instrumented_wrapper.py` first.** These are the integration points. Understanding what they do now (loop detection, early return) tells you exactly what the cache needs to provide.

2. **The D5 work (cached trace events) already bridges cache → trace → report.** Don't re-implement this. Just make sure your cache system sets the right state in `shared` before `_handle_cached_execution()` runs.

3. **The user cares deeply about file content hashing correctness.** They brought up the `write-lyrics.prompt.md` scenario unprompted. This is their primary concern. Get this right first, optimize later.

4. **The `_PROPAGATED_KEYS` pattern is the way to flow cross-cutting concerns through sub-workflows.** If the cache needs state in sub-workflows, add a key there. Follow the `_trace_collector` pattern exactly.

5. **Don't use `__dunder__` keys for new cache state in the shared store.** Phase 1 added filtering that strips dunders from trace events and mutations. Use `_cache_` prefix (single underscore) and add it to the `_sanitize_for_json()` and mutations filter lists if needed.

## Open Threads

1. **The user wants to start Task 106 next.** There was no implementation discussion yet — only the agent-perspective doc and some mentions during Task 108 planning.

2. **The `run-step` feature** is part of Task 106's scope but was discussed as potentially separate. The agent-perspective doc has detailed thoughts on it.

3. **The report already handles `[cached]` nodes.** When implementing cache, verify that the report renders correctly for a mix of cached and fresh nodes.

4. **The `allow_interspersed_args=True` change** in Phase 1 means new CLI flags (like `--no-cache` or `--fresh`) can be placed before or after the workflow argument.

## Relevant Files & References

**Task 106 docs:**
- `.taskmaster/tasks/task_106/task-106.md` — main task definition
- `.taskmaster/tasks/task_106/starting-context/pflow-iteration-cache-agent-perspective.md` — ESSENTIAL reading, the most insightful doc
- `.taskmaster/tasks/task_106/starting-context/run-step-insight.md`
- `.taskmaster/tasks/task_106/starting-context/task-106-handover.md`

**Task 108 docs (for understanding the current architecture):**
- `.taskmaster/tasks/task_108/implementation/progress-log.md` — complete implementation history, all deviations, all decisions
- `.taskmaster/tasks/task_108/implementation/phase-1-implementation-plan.md` — detailed plan with exact code changes

**Key code files (cache integration points):**
- `src/pflow/runtime/wrappers/instrumented_wrapper.py` — `_handle_cached_execution()`, `_check_cache_validity()`, `_run()`, `_record_trace()`
- `src/pflow/runtime/workflow_trace.py` — `WorkflowTraceCollector`, `record_node_execution(cached=True)`, `collect_llm_calls()`
- `src/pflow/runtime/workflow_executor.py` — `_PROPAGATED_KEYS`, `_create_child_storage()`
- `src/pflow/execution/executor_service.py` — trace collector auto-creation, shared store initialization
- `src/pflow/runtime/compilation/compiler.py` — wrapper chain assembly in `_create_single_node()`
- `src/pflow/core/trace_report.py` — report generator, `[cached]` rendering in `_format_node_metadata()`

**Agent instructions (updated for --report):**
- `src/pflow/cli/resources/cli-agent-instructions.md`
- `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md`

## For the Next Agent

**Start by**: Read `.taskmaster/tasks/task_106/starting-context/pflow-iteration-cache-agent-perspective.md` — it has the user's perspective on what the cache should do and critical edge cases. Then read `.taskmaster/tasks/task_106/task-106.md` for the formal spec.

**Then**: Read `src/pflow/runtime/wrappers/instrumented_wrapper.py` — specifically `_check_cache_validity()` and `_handle_cached_execution()`. These are your integration points. Understand what they do NOW before adding cache logic.

**Don't bother with**: Re-implementing trace integration for cached nodes. D5 already did this. Just make sure `shared[self.node_id]` has the cached output before `_handle_cached_execution()` runs.

**The user cares most about**: (1) File content hashing correctness — editing a prompt file MUST invalidate the cache. (2) The development loop: edit → re-run (cached upstream) → read report → iterate. (3) `--no-cache`/`--fresh` escape hatch for when cached output is bad.

**Key gotcha**: `_PROPAGATED_KEYS` uses single-underscore `_trace_collector`, not dunder. The `_sanitize_for_json()` method strips dunders AND keys starting with `_trace`, `_debug`, `_batch_trace`. If you add cache state to the shared store, choose a prefix that won't be filtered (or add it to the allowlist).

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
