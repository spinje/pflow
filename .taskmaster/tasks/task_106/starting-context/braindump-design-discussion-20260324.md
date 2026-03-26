# Braindump: Task 106 Design Discussion — Memoization Cache Architecture

**Date**: 2026-03-24
**Context**: Full design discussion with user, from reading starting context through architecture decisions to verified integration points. No implementation started. Task file written.

## Where I Am

Design is complete. The task file (`task-106.md`) captures WHAT to build. This braindump captures HOW we got there — the reasoning, dead ends, user priorities, and tacit knowledge that the task file doesn't contain.

## User's Mental Model

### How They Think

The user thinks in **composable primitives**, not features. The breakthrough moment was when they collapsed three "modes" (full run + cache, re-run one node, run-step standalone) into orthogonal flags:

> "run step standalone, isnt that the same as rerun node only that you can override cashed inputs (if exists?) with manual args?"

This is their design instinct: find the minimal set of primitives that compose into everything. They did the same with the memoization insight — I was proposing cascade invalidation as a separate concept, and they kept pushing:

> "but with this logic should nodes in mainworkflow that have uncached nodes before it, can they still be cached if they recieve the exact same inputs..?"

They were pointing out an inconsistency I'd introduced: sub-workflows get content-addressed caching, but individual nodes get conservative cascade. They wanted the SAME principle everywhere. This led directly to the memoization model.

### Key Phrases (Their Exact Words)

- On sub-workflow portability: "a sub-workflow CAN be run in isolation, if inputs are the same and nothing in it changed it shouldnt matter if it was run standalone the first time or not"
- On reinventing the wheel: "this should be a solved problem right? Why does it feel like I have to reinvent the wheel?" — This unlocked the memoization framing
- On trace duplication: "it still feels like we are duplicating data with the trace?" and later "It just feels this is a symptom that I didnt think of this in advance. How could I have designed ONE file for both of this?" — They care about architectural cleanliness even while accepting pragmatic choices
- On `--fresh` vs `--no-cache`: short discussion, landed on `--no-cache` as standard CLI convention

### Their Priorities (Stated and Unstated)

**Stated**: The cache must be automatic, invisible, zero-friction for AI agents.

**Unstated but clear from behavior**:
1. They want CONCEPTUAL CONSISTENCY more than anything. Same principle at every level. They will not accept a design that has special cases.
2. They care about CLEAN ARCHITECTURE even for pragmatic decisions. They accepted trace duplication but visibly didn't love it.
3. They want to UNDERSTAND deeply before building. They pushed me to explore every option before committing. "have we considered all approaches?"
4. They think about FUTURE UNIFICATION. The trace + cache unification came up multiple times. They want the cache designed so it could be unified later.

## Key Insights

### The Memoization Realization

I was proposing cascade invalidation ("upstream re-executed → downstream must too") as the invalidation strategy. The user kept asking questions that exposed its weakness. The cascade rule was a conservative approximation that would cause unnecessary re-execution.

The memoization model (`hash(config + resolved_inputs)`) is strictly better: it catches the cascade case (inputs changed) AND the no-cascade case (upstream re-executed but produced same output). It took several rounds of back-and-forth to arrive here. The user's question about sub-workflow caching is what forced the issue.

### Template Resolution is the Natural Cache Check Point

Template resolution (`TemplateAwareNodeWrapper._run()` lines 509-662) is side-effect-free — it only reads from a context dict built from the shared store. This means we can resolve templates to get the input hash WITHOUT committing to execution. This is the key architectural insight that makes memoization practical.

The investigation confirmed: after resolution, `merged_params` is a simple dict that can be serialized and hashed. No mutations to shared store during resolution (except `__template_errors__` in error paths).

### The Existing Cache is Half the Solution

The `InstrumentedNodeWrapper` already has `_check_cache_validity()`, `_handle_cached_execution()`, `_cache_result_if_successful()`, and `__execution__` state tracking. This mechanism works perfectly for in-process resume. For cross-process memoization, we need:
1. Disk persistence of cache entries
2. Enhanced hash (include template params, batch config, exclude `_source_lines`)
3. Input hash comparison (resolved template values)

The existing `_handle_cached_execution()` already records `cached=True` trace events and fires progress callbacks. We can reuse this for memoization hits.

### Config Hash Gaps Are Significant

The current `_compute_node_config()` traverses to the INNERMOST node and reads only its static params. This misses:
- Template params (on `TemplateAwareNodeWrapper.template_params`)
- Batch config (on `PflowBatchNode`)
- Sub-workflow file content (only path string in params)
- Includes `_source_lines` noise (whitespace changes invalidate)

For an LLM node with `prompt: ./file.md` where the file contains `${var}`, the prompt content is a template param → NOT in the hash. This is the exact scenario the user cares most about.

### Sub-Workflow Input Canonicalization

`prep_res["child_params"]` from `WorkflowExecutor.prep()` is the canonical, fully-resolved input dict for a sub-workflow. Templates like `${upstream.result}` are resolved by the parent's `TemplateAwareNodeWrapper` BEFORE `prep()` runs. This is the clean place to compute the sub-workflow cache key.

For batch sub-workflows, templates like `${doc.name}` are resolved per-item by the batch node's item context injection. So `child_params` are already item-specific — different items naturally get different cache keys.

## Assumptions & Uncertainties

ASSUMPTION: The `resolve_templates()` method split on `TemplateAwareNodeWrapper` can be done cleanly. The template wrapper's `_run()` does resolution + execution in one method. Splitting it requires the instrumented wrapper to call `resolve_templates()` for the hash, then either skip execution (cache hit) or proceed with `_run()` (cache miss). The template wrapper would need to avoid double-resolution on the miss path. I proposed memoization within the wrapper but haven't verified this is straightforward.

ASSUMPTION: The existing `__execution__` in-process cache can coexist with the new memoization cache. I assumed we'd keep `__execution__` for its original purpose (in-process resume, loop detection) and ADD the memoization cache alongside it. But there might be interference — e.g., if memoization says "cache hit" but `__execution__` says "not completed" (first run of a fresh process). Need to think about the interaction.

UNCLEAR: How the instrumented wrapper should signal a memoization cache hit to the rest of the system. Currently `_handle_cached_execution()` handles in-process cache hits. Should memoization hits go through the same path? Probably yes — restore output to shared store, then let `_handle_cached_execution()` do its thing (trace event, callbacks).

UNCLEAR: Storage format. We discussed files vs SQLite but didn't decide. SQLite is cleaner for a key-value memoization cache with lookups and eviction. Files are simpler. This needs a decision during implementation.

NEEDS VERIFICATION: Whether `_make_serializable()` (used by `_compute_config_hash()`) handles all types that can appear in resolved template values. Resolved values can be dicts, lists, strings, ints, bools, None — `_make_serializable()` handles these. But what about custom objects that somehow end up as template values? Edge case, probably fine.

NEEDS VERIFICATION: Thread safety of cache reads/writes during parallel batch execution. `PflowBatchNode` runs items in parallel (threads). If two items read/write the same cache file simultaneously, there could be corruption. Atomic writes (temp file → rename) should handle this, but needs explicit consideration.

## Dead Ends and Why

### 1. Using Trace as Cache (extensively discussed)
**Rejected because**: 17MB trace vs ~3MB of useful cache data (10x overhead). The trace stores LLM prompts, full responses, template resolutions, nested sub-workflow event trees — all irrelevant for caching. Also missing cache_key and action fields. Different lifecycle (traces accumulate for debugging, cache is current-state lookup). Different access pattern (trace: sequential read of a run; cache: random lookup by key).

### 2. Cascade Invalidation
**Replaced by**: Memoization (input hash comparison). Cascade ("upstream re-executed → downstream must too") is a conservative approximation. If upstream re-executes but produces the same output, cascade unnecessarily invalidates downstream. Memoization is strictly better and conceptually consistent at every level.

### 3. Enriched `__execution__` Tree (Option A)
**Rejected because**: Sub-workflow cache would be trapped inside the parent's `__execution__` tree. A standalone run of the same sub-workflow wouldn't find the cache. The user's key insight: "a sub-workflow CAN be run in isolation" — cache must be portable.

### 4. Per-invocation-context Cache Keys (batch item indices in key)
**Replaced by**: Content-addressed keys (workflow path + content + inputs). Using batch item indices ties the cache to the parent context. Content-addressed keys make the cache portable — same file + same inputs = same cache, regardless of invocation context.

### 5. Separate `run-step` Command
**Collapsed into**: `--only <node>` flag + `key=value` overrides. The user realized these "modes" aren't separate features — they're combinations of orthogonal flags.

### 6. Latest-only Cache
**Replaced by**: Accumulating memoization cache. The user challenged "why should cache be latest only?" — in a memoization model, keeping old entries lets you switch between input combinations without re-executing. TTL eviction bounds growth.

## Unexplored Territory

UNEXPLORED: **How the memoization cache interacts with the existing `__execution__` in-process cache.** The in-process cache checks `completed_nodes` and `node_hashes`. The memoization cache checks disk-persisted `cache_key = hash(config + inputs)`. These are two different caching layers. On a fresh process invocation: memoization cache loads from disk, but `__execution__` starts empty. Does the memoization cache populate `__execution__`? Or does it bypass `__execution__` entirely? This interaction needs careful design during implementation.

UNEXPLORED: **MCP nodes and caching.** MCP nodes call external servers. The server's state could change between runs. Same inputs might produce different outputs. Should MCP nodes be cacheable? Probably yes (with `--no-cache` as escape hatch), but this wasn't discussed.

UNEXPLORED: **Conditional branching interaction with `--only`.** If the target node is on branch B, but the flow takes branch A, the target node is never reached. What should happen? Error? Execute up to the branch point and stop? The `get_next_node` override would just let the flow run until it terminates naturally (never reaching the target). This might be confusing — the user asks for `--only branch-b-node` and it runs branch A nodes instead.

UNEXPLORED: **How to handle the `resolve_templates()` split when the node has NO TemplateAwareNodeWrapper.** Some nodes have no template params (purely static config). The instrumented wrapper's `_find_template_wrapper()` method (line 260-279) returns None in this case. The memoization check for template-less nodes should use config hash only (no input hash needed since they don't read from upstream via templates).

CONSIDER: **Whether batch config should be part of config hash or treated separately.** The batch config determines HOW many times the inner node runs and with what items. Changing `parallel: true` to `parallel: false` shouldn't invalidate the cache (same results, different execution strategy). But changing `items` template or `error_handling` mode should. Maybe split batch config into "semantic" (affects results) and "operational" (affects execution but not results).

CONSIDER: **Cache key stability across pflow versions.** If the config hash computation changes between versions (e.g., we add batch config to the hash), all existing cache entries become misses. This is fine for now (no users) but worth noting.

MIGHT MATTER: **The `_build_resolution_context()` in template wrapper does `context = dict(shared)` then `context.update(self.initial_params)`.** The `initial_params` include CLI args AND workflow defaults. If you run with `--only <node>` and provide `key=value` overrides, these overrides go into `initial_params` and take priority over cached upstream outputs in the shared store. This is correct and desirable, but the interaction is subtle.

MIGHT MATTER: **The `WorkflowExecutor._resolve_child_inputs()` is a redundant resolution pass.** In normal execution, templates are already resolved by the parent's TemplateAwareNodeWrapper. This method is a belt-and-suspenders safety net. For caching, we should use the already-resolved `child_params` from after `_extract_child_inputs()`, not re-resolve.

MIGHT MATTER: **For `storage_mode="shared"` sub-workflows, the child shares the parent's entire store.** Caching is probably not meaningful in this mode since the child can see/modify everything. This mode might need to be excluded from sub-workflow caching.

## What I'd Tell Myself

1. **Don't start with the cache storage format.** Start with the `resolve_templates()` split on the template wrapper. This is the architectural change that everything else depends on. If this split is clean, the rest follows. If it's messy, rethink the approach.

2. **The user's consistency principle is non-negotiable.** Every design choice must work the same at top-level and sub-workflow level. If you find yourself adding special cases for sub-workflows, stop and rethink.

3. **Test with the lyrics-generator workflow.** It has 3 levels of nesting, batch sub-workflows, prompt files with templates, and 270 output files. If the cache works for this workflow, it works for everything. The trace files in `~/.pflow/debug/workflow-trace-lyrics-generator-*.json` contain real data to validate against.

4. **The `_source_lines` noise issue is a quick win.** Excluding `_source_lines` from the config hash prevents false invalidation from whitespace changes. Do this early — it's a one-line filter in `_compute_node_config()`.

5. **Don't over-engineer eviction for MVP.** Simple TTL check on file modification time is enough. SQLite with LRU can come later if needed.

6. **The existing `_handle_cached_execution()` is your friend.** It already handles trace recording (`cached=True`), progress callbacks, and `__cache_hits__` tracking. Memoization cache hits should flow through this same path.

## Open Threads

1. **Storage format not decided.** Files vs SQLite vs single JSON file. Leaning toward files (one per cache entry, named by cache key hash) for simplicity and atomic writes. But SQLite is more elegant for lookups and eviction.

2. **The relationship between `__execution__` and memoization cache needs design.** Option: on process start, load memoization cache entries into `__execution__` (populate `completed_nodes`, `node_hashes`, `node_actions`). Then the existing `_check_cache_validity()` works as-is for the config hash check. The input hash check is the new addition.

3. **The `resolve_templates()` split implementation.** I proposed adding a method to `TemplateAwareNodeWrapper` that does lines 509-662 without 667. The tricky part: if cache misses, `_run()` must not re-resolve. Options: (a) memoize the resolved values on the wrapper instance, (b) pass resolved values to `_run()` somehow, (c) have `_run()` check if already resolved.

4. **How does `--only` interact with the report?** Task 108 generates execution reports. If `--only` stops after one node, the report shows only that node. Is this confusing? Probably fine — the user asked for just that node.

5. **The user mentioned the braindump files might be outdated.** The starting-context files were written at different times. The new task file supersedes all of them for design decisions. But the agent-perspective doc (`pflow-iteration-cache-agent-perspective.md`) still has valuable context about real workflow pain points.

## Relevant Files & References

### Must-Read Before Implementation
- `src/pflow/runtime/wrappers/instrumented_wrapper.py` — THE integration point. Read `_run()` (596-693), `_check_cache_validity()` (526-551), `_handle_cached_execution()` (564-594), `_compute_node_config()` (392-425), `_compute_config_hash()` (427-445)
- `src/pflow/runtime/wrappers/template_wrapper.py` — `_run()` (495-672) is where you'll add `resolve_templates()`. `set_params()` (79-116) shows template/static split
- `src/pflow/runtime/workflow_executor.py` — `prep()` for sub-workflow input canonicalization, `_create_child_storage()` for child shared store setup

### The Compiled Flow Pattern
- `src/pflow/runtime/compilation/compiler.py:711-729` — `run_with_hooks` monkey-patch. This is the pattern to follow for `--only` (`get_next_node` override).

### Real Test Data
- `~/.pflow/debug/workflow-trace-lyrics-generator-20260324-151824.json` — 17MB, the largest trace. Shows real output sizes per node. Use this to validate cache size estimates.

### The Investigation Results
Five parallel agents investigated the codebase. Their findings are summarized in the task file's Implementation Notes section, but the full agent outputs (in conversation context) contain more detail about exact line numbers, code flows, and edge cases.

## For the Next Agent

**Start by**: Reading the task file (`task-106.md`). It's comprehensive and captures all decisions.

**Then**: Read `instrumented_wrapper.py` and `template_wrapper.py`. Understand the existing cache mechanism and the template resolution flow. These are your two primary integration points.

**Don't bother with**: The starting-context files (braindump, agent-perspective, etc.) — they're pre-decision context. The task file supersedes them. Only read them if you need to understand WHY a decision was made.

**The user cares most about**: (1) Conceptual consistency — same mechanism everywhere, no special cases. (2) The memoization model being correct — `hash(config + inputs)` must be the single principle. (3) Sub-workflow cache portability — standalone run and parent-invoked run should share cache.

**Implementation order I'd suggest**:
1. `resolve_templates()` split on template wrapper
2. Enhanced config hash (include template params, batch config, exclude `_source_lines`)
3. Memoization cache storage (write/read)
4. Integration in instrumented wrapper (resolve → hash → check → hit/miss)
5. Sub-workflow cache (WorkflowExecutor integration)
6. `--only` flag
7. `--no-cache` flag
8. `key=value` overrides
9. Tests

**Key risk**: The `resolve_templates()` split is the make-or-break. If it's clean, everything else flows. If it's messy, reconsider whether the instrumented wrapper should call template resolution directly or whether a different wrapper ordering makes more sense.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
