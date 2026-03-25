# Task 106: Workflow Iteration Cache

## Description

Memoization-based caching for workflow node execution. When an AI agent iterates on a workflow file (edit prompt, re-run, evaluate, repeat), unchanged nodes are served from a disk-persisted cache instead of re-executing. Same mechanism works at every level: top-level nodes, sub-workflow nodes, sub-sub-workflow nodes. Zero configuration — caching is automatic for file-based workflows.

## Status

not started

## Priority

high

## Problem

When AI agents iterate on `.pflow.md` workflow files, every re-run executes ALL nodes from scratch:

```
Run 1: pflow workflow.pflow.md
  → fetch-sources      ✓ (4s)
  → analyze-sources    ✓ (16s, 6 LLM calls)
  → generate-concepts  ✓ (10s, 1 LLM call)
  → create-songs       ✓ (200s, 4 sub-workflows × 12 nodes each)
  → evaluate           ✓ (15s)

Agent edits write-lyrics.prompt.md (inside the create-songs sub-workflow)...

Run 2: pflow workflow.pflow.md
  → fetch-sources      ✓ (4s)   ← WASTED
  → analyze-sources    ✓ (16s)  ← WASTED
  → generate-concepts  ✓ (10s)  ← WASTED
  → create-songs       ✓ (200s) ← MOSTLY WASTED (only write-lyrics changed)
  → evaluate           ✓ (15s)  ← runs with new data (correct)
```

Cost: ~$1.58 and ~280s per iteration. Over 10+ iterations, that's significant wasted time and money. Side effects (GitHub issues, emails, file writes) are also duplicated.

## Solution

Memoization-based caching. Each node is treated as a pure function:

```
cache_key = hash(node_config + resolved_inputs)
if cache_key in cache → return cached output
else → execute, store result
```

**Core principle**: Same config + same inputs = same output. This applies identically at every level of the execution tree. No special sub-workflow logic, no cascade rules — just memoization.

With caching, the same iteration becomes:

```
Run 2 (after editing write-lyrics.prompt.md):
  → fetch-sources      ✓ cached (instant)
  → analyze-sources    ✓ cached (instant)
  → generate-concepts  ✓ cached (instant)
  → create-songs       re-executes, but INSIDE each song sub-workflow:
      → creative-direction  ✓ cached (same inputs, same config)
      → song-architecture   ✓ cached
      → choose-chorus       ✓ cached (saves ~50s per song!)
      → write-lyrics        RE-EXECUTES (prompt file changed)
      → downstream nodes    RE-EXECUTE (inputs changed)
  → evaluate           RE-EXECUTES (inputs changed)
```

Three composable flags provide the full development loop:

```bash
pflow workflow.pflow.md                                # full run + cache
pflow workflow.pflow.md --only write-lyrics             # run just one node (cached upstream)
pflow workflow.pflow.md --only write-lyrics tone=dark   # override an input
pflow workflow.pflow.md --no-cache                      # bypass cache entirely
```

## Design Decisions

- **Memoization, not cascade invalidation**: We do NOT use "upstream re-executed → downstream must too." Instead, we compare actual inputs. If upstream re-executes but produces the same output, downstream stays cached. This is strictly more efficient and conceptually consistent at every level.

- **Input comparison at template resolution time**: The cache check happens AFTER template resolution (which is cheap — just dict lookups). We hash the resolved template values to determine if inputs changed. This avoids needing compile-time dependency analysis.

- **Separate cache storage from trace**: The trace system stores 17MB per run for the lyrics generator workflow (LLM prompts, responses, template resolutions, nested event trees). The cache only needs ~3MB (node outputs + metadata). Different purposes, different access patterns, different files. Future unification opportunity noted but deferred.

- **Cache accumulates (not latest-only)**: Like a real memoization cache, old entries are kept. Running with input A, then input B, then input A again hits cache on the third run. TTL-based eviction bounds disk growth.

- **Per-workflow-file caching, keyed by content + inputs**: A sub-workflow's cache is portable — it doesn't matter if it was run standalone or as part of a parent. Same file + same inputs = same cache. The cache key for sub-workflows is `hash(workflow_path + workflow_content + child_params)`.

- **`--only <node>` instead of separate `run-step` command**: The three modes (full run, re-run one node, standalone execution with manual inputs) are all combinations of `--only`, `--no-cache`, and `key=value` overrides. One command, composable flags.

- **`--no-cache` (not `--fresh`)**: Standard CLI convention (Docker, npm, pip). Self-documenting. Click supports `--cache/--no-cache` paired flags natively.

- **Whole-batch caching for MVP**: Cache entire batch results, not individual items. Per-item caching only matters for partial failure recovery (3 of 4 items succeed, 1 fails from transient error). Narrow edge case — defer to later.

- **Extend existing `__execution__` mechanism**: The instrumented wrapper already has config hashing, cache checking, cache-hit trace recording. We're adding disk persistence and input-hash-based validation, not building from scratch.

## Dependencies

None. The existing instrumented wrapper, template wrapper, and trace system provide the integration points.

## Requirements

### Cache Validity

- Cache key is `hash(config_hash + resolved_input_hash)` per node invocation
- Config hash includes: node type, ALL params (static + template), batch config. Excludes `_source_lines` metadata (noise — whitespace changes shouldn't invalidate)
- Input hash includes: resolved template values after `TemplateAwareNodeWrapper` resolves `${...}` expressions
- Nodes without templates: config hash alone is sufficient (no upstream data dependency)
- File-resolved params with templates (e.g., prompt file containing `${var}`): file CONTENT must be included in the config hash. The file resolver already inlines content into params at compile time, but template params live on `TemplateAwareNodeWrapper.template_params`, not on the inner node. The enhanced config hash must include these.

### Sub-Workflow Caching

- Same memoization mechanism at every level — no special sub-workflow logic
- Sub-workflow cache key: `hash(workflow_file_path + workflow_content_hash + child_params)`
- `child_params` = resolved non-reserved params from `WorkflowExecutor.prep()` — the canonical input dict
- Cache is portable: same `.pflow.md` with same inputs hits cache regardless of whether run standalone or as sub-workflow
- For batch sub-workflows: each batch item gets different resolved `child_params` (templates like `${doc.name}` resolved per-item), producing different cache keys. This is correct — different items should cache independently.

### Cache Storage

- Separate from trace files (different purpose, access pattern, and lifecycle)
- Lean format: per-node entries containing only `cache_key`, `action` (string returned by node for flow routing), `output` (the data to restore into shared store), and `output_hash` (for quick comparison)
- Accumulating (memoization — old entries kept for different input combinations)
- TTL-based eviction to bound disk growth (default 24h, configurable)
- Location: `~/.pflow/cache/` directory

### CLI Flags

- `--cache/--no-cache` (default: cache enabled): Bypass memoization entirely when `--no-cache` is set
- `--only <node_id>`: Execute workflow up to and including the named node, then stop. Upstream nodes served from cache (if available). Downstream nodes do NOT execute.
- `key=value` positional args: Override inputs. Injected into `execution_params` before compilation, flow through both shared store and `initial_params` paths. Override cached upstream outputs.
- All flags are composable and orthogonal

### Scope

- **In scope**: File-based workflow execution (`pflow ./workflow.pflow.md`, `pflow /path/to/workflow.pflow.md`)
- **Out of scope**: Saved/named workflows (`pflow my-saved-workflow`) — these are production artifacts, always run fresh
- **Out of scope**: Per-batch-item caching, CLI cache commands (`pflow cache status/clear`), unifying trace + cache storage

## Implementation Notes

### Integration Points (verified by codebase investigation)

**Template wrapper — resolve without executing:**
- `TemplateAwareNodeWrapper._run()` resolves templates at lines 509-662, then calls `inner_node._run()` at line 667. Template resolution is side-effect-free (only reads from shared store context).
- Add a `resolve_templates(shared)` method that performs resolution without execution. The instrumented wrapper calls this to compute the input hash for the cache key.
- After resolution, `merged_params` is a simple dict that can be serialized and hashed.

**Instrumented wrapper — enhanced cache check:**
- Current `_check_cache_validity()` only checks config hash against `__execution__["node_hashes"]`. For memoization, it needs to also check the resolved input hash.
- Current `_compute_node_config()` traverses to innermost node and reads only static params. Must be enhanced to include template params from `TemplateAwareNodeWrapper` and batch config from `PflowBatchNode`.
- Current hash includes `_source_lines` metadata (noise). Exclude these.
- `_handle_cached_execution()` already records `cached=True` trace events and fires progress callbacks. Reuse this for memoization cache hits.

**`--only` flag — override `get_next_node`:**
- PocketFlow's `Flow._orch()` loop terminates when `get_next_node()` returns `None`.
- After `compile_ir_to_flow()`, override `flow.get_next_node` to return `None` when `curr.node_id == stop_after_node_id`. Same monkey-patch pattern as existing `run_with_hooks`.
- No PocketFlow modification needed.

**Sub-workflow caching:**
- `WorkflowExecutor.prep()` produces `prep_res["child_params"]` — the canonical resolved input dict (all non-reserved params, fully resolved by parent's `TemplateAwareNodeWrapper`).
- This is the clean interception point for computing the sub-workflow cache key.
- `_create_child_storage()` creates child shared store from `child_params.copy()` + infrastructure keys. Cache can pre-populate this with cached node outputs.

**CLI arg flow:**
- `key=value` pairs are parsed by `parse_workflow_params()` in `cli/param_parsing.py`
- Placed at root of shared store via `_initialize_shared_store()`
- Also passed as `initial_params` to every `TemplateAwareNodeWrapper`
- `initial_params` overrides shared store in resolution context (`context.update(self.initial_params)`)
- Override injection: add to `execution_params` before compilation — flows through both paths naturally

### Config Hash Gaps (current state → needed state)

| Element | Current | Needed |
|---------|---------|--------|
| Node type (class name) | Included | Keep |
| Static params (non-template) | Included | Keep |
| Template params | **Missing** (on TemplateAwareNodeWrapper, not inner node) | Include |
| Batch config | **Missing** (on PflowBatchNode) | Include |
| Sub-workflow file content | **Missing** (only path string in params) | Include content hash |
| `_source_lines` metadata | **Included** (noise) | Exclude |
| Resolved template values | **Missing** | This becomes the input hash |

### Cache File Design Note

The trace system stores per-node `node_output` (full data, no truncation) — the same data the cache needs. In a future task, the trace could be restructured as per-node files (content-addressed store), unifying trace and cache storage. For now, accept the ~3MB duplication per workflow run. Design the cache format to be compatible with future unification.

## Verification

### Core Memoization
- Second run of unchanged workflow: all nodes served from cache, no execution
- Edit a node's prompt file: that node + downstream re-execute, upstream cached
- Edit a prompt file inside a sub-workflow: sub-workflow re-executes but unchanged internal nodes are cached
- Same config + same inputs from different runs: cache hit regardless of time between runs
- Upstream re-executes but produces same output: downstream stays cached (no false invalidation)

### Sub-Workflow Caching
- Sub-workflow run standalone, then as part of parent with same inputs: cache hit
- Batch sub-workflow with 4 items: each item caches independently (different inputs → different keys)
- Edit a file deep in sub-sub-workflow: only affected nodes re-execute, rest cached

### CLI Flags
- `--no-cache`: full execution, no cache reads (writes still happen for next run)
- `--only <node>`: upstream cached, target executes, downstream does NOT execute
- `--only <node> key=value`: overrides cached upstream value for the specified key
- All flags composable: `--only <node> --no-cache key=value` works

### Edge Cases
- Cache file missing or corrupted: degrades gracefully to full execution
- Workflow file renamed/moved: different cache key, full execution (correct)
- Node added/removed from workflow: unaffected nodes still cache, new nodes execute
- Binary data in node output: handled correctly by serialization

### Performance
- Cache lookup: < 10ms per node
- Full workflow with all cache hits: < 1s overhead regardless of node count
- Cache file size: proportional to output data only (~3MB for lyrics generator, not 17MB like trace)

## References

### Key Code Files
- `src/pflow/runtime/wrappers/instrumented_wrapper.py` — Existing cache mechanism: `_check_cache_validity()`, `_handle_cached_execution()`, `_compute_node_config()`, `_compute_config_hash()`
- `src/pflow/runtime/wrappers/template_wrapper.py` — Template resolution in `_run()` (lines 509-672), `set_params()` splits template/static (lines 79-116)
- `src/pflow/runtime/workflow_executor.py` — Sub-workflow execution, `_create_child_storage()`, `RESERVED_PARAMS`, `_PROPAGATED_KEYS`
- `src/pflow/runtime/compilation/compiler.py` — Wrapper chain in `_create_single_node()`, `run_with_hooks` monkey-patch pattern
- `src/pflow/pocketflow/__init__.py` — `Flow._orch()` loop, `get_next_node()` termination
- `src/pflow/execution/executor_service.py` — `_initialize_shared_store()`, shared store setup
- `src/pflow/core/file_resolver.py` — File content inlining, `_source_files` provenance
- `src/pflow/cli/main.py` — CLI arg parsing, `workflow_command`, `_validate_and_prepare_workflow_params`
- `src/pflow/cli/param_parsing.py` — `parse_workflow_params()` key=value parsing

### Starting Context
- `.taskmaster/tasks/task_106/starting-context/braindump-post-task108-architecture.md` — Architecture state after Task 108
- `.taskmaster/tasks/task_106/starting-context/pflow-iteration-cache-agent-perspective.md` — Agent user perspective on iteration pain
- `.taskmaster/tasks/task_106/starting-context/run-step-insight.md` — How run-step was folded into --only flag
- `.taskmaster/tasks/task_106/starting-context/task-106-handover.md` — Original handover context

### Superseded Tasks
- Task 44 (Build caching system) — superseded by this task
- Task 73 (Checkpoint persistence with `--resume` flag) — superseded by this task's automatic approach
