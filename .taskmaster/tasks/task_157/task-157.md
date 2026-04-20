# Task 157: Fix Dry-Run Batch Sub-Workflow Recursion

## Problem

`pflow <workflow> --dry-run` produces three incorrect behaviors for batch sub-workflow nodes (nodes with both `type: workflow` and a `batch:` config):

1. **Missing cost/duration estimates** (GH #318) — Reports `$0 (no history)` and unknown duration even when per-item cache entries exist with full cost/duration data. Agents cost/time-gating on dry-run output approve runs they should abort.

2. **"Nothing cached" cascade** — After a successful full run, dry-run reports "0 cached · 47 would execute" when all 47 nodes are actually cached. The first batch sub-workflow fails to populate parent shared store → all downstream template resolution fails → no cache keys computed anywhere.

3. **False validation error** (GH #323) — Emits `Workflow requires input 'X'` for child inputs that are correctly satisfied via batch `${item}`. The error fires after a complete plan is printed. The same workflow passes `--validate-only` and runs successfully.

## Why This Matters

`--dry-run` exists so agents can cost/time-gate before expensive runs. When it reports "$0, nothing cached" for a fully-cached $2.43 pipeline, agents either:
- Trust it and proceed (wasting the dry-run entirely)
- Learn to distrust it (defeating the feature's purpose)

The batch-of-sub-workflow pattern is used in every non-trivial pipeline (the lyrics-generator uses it for `fetch-sources`, `analyze-sources`, `create-songs`, `curate-briefs`). This isn't an edge case — it's the primary composition pattern that dry-run can't handle.

## Root Cause

The planner's dispatch has a structural gap. It handles:
- Standard nodes (batch or not) via `_plan_standard_node` + `plan_node`
- Non-batch sub-workflow nodes via `_plan_sub_workflow`

But NOT batch sub-workflow nodes. When `_plan_sub_workflow` is reached for a batch WorkflowExecutor:
- `plan_node()` skips template resolution because `config.batch_config` is set (plan_node.py:50)
- `inputs: {source: ${item}}` never resolves → child compile fails → "missing required input"
- Even if it compiled, there's no per-item loop → no per-item cache checking → no cost aggregation

## Requirements

### Functional

1. **Per-item cache detection**: For a batch of N items, each item's child nodes must be individually checked against the memo cache. If 4/5 items are cached and 1 is new, the plan must report this accurately (not "all cached" or "nothing cached").

2. **Cost aggregation**: Total cost = sum of actual per-item historical costs from cache (not one item × N). Items may have different costs (different input lengths → different token counts).

3. **Duration estimation**: Sequential batches = sum of per-item durations. Parallel batches = max of per-item durations (wall-clock). Never multiply by N for parallel.

4. **Downstream template resolution**: After planning the batch, `parent_shared[node_id]` must contain the batch output shape (`{results: [...], count: N, ...}`) so downstream parent nodes can resolve templates like `${batch_node.results}`.

5. **No false validation errors**: Batch items provide `${item}` context for child inputs at runtime. The planner must provide the same context at plan time.

6. **Opaque fallback**: When batch items can't be resolved (template depends on would-execute upstream), return an opaque entry honestly (not an error).

### Display

Per-node lines inside a batch sub-plan:
- **All items cached for a node**: normal `↻ node (age)` — no M/N (redundant)
- **All items would execute**: normal `▸ node [type]` — no M/N (redundant)
- **Partial cache**: `▸ node [type]  M/N would execute  ≈ $avg · ~avg_time`
  - M = items that would execute, N = total items
  - Cost/duration = per-execution averages

Parent batch node line:
- `▸ node  [workflow 'path' × N items, parallel]` or `↻` if all items fully cached

Summary: real aggregated totals (sum of actual per-item costs, parallel-aware duration).

### Non-functional

- No changes to `_summarize`, `_classify`, `_represents_work`, `_compute_totals` — the fix must work within existing aggregation infrastructure
- No circular imports (plan.py may import from batch_executor.py but not vice versa)
- Existing batch drift tests (`test_plan_batch_items_cache_matches`, `test_plan_batch_llm_cost_aggregates_across_results`) must pass unchanged — they test standard batch nodes, not WorkflowExecutor
- `make check` and `make test` clean

## Acceptance Criteria

1. **Repro from GH #323 produces correct output**: Parent with `batch: items: ${sources}` + child with required input → `--dry-run` shows no validation error, displays per-item cache status.

2. **"Nothing cached" cascade fixed**: After a full run of the lyrics-generator pipeline, `--dry-run` shows "47 cached · 0 would execute" (not "0 cached · 47 would execute").

3. **Partial cache detected**: Run a batch workflow → change one item → `--dry-run` correctly identifies which items are cached and which would execute.

4. **Cost is sum of actuals**: Drift-catcher test verifies plan cost equals sum of per-item historical costs from cache (not average × N).

5. **Parallel duration is max, not sum**: A parallel batch of 5 items each taking 2s shows ~2s duration (not 10s).

6. **Downstream nodes resolve**: After the batch sub-workflow is planned, downstream parent nodes that template against `${batch_node.results}` resolve correctly (no template_error cascade).

7. **Drift-catcher test exists and is mutation-verified**: Temporarily breaking the batch dispatch causes the test to fail.

## Scope

### In scope
- Batch sub-workflow planning in the pre-boundary (state-machine) path
- Per-item full recursion with accurate cache checking
- Aggregation across N child plans
- Batch output shape for downstream template resolution
- Formatter changes for batch display
- CLAUDE.md documentation

### Out of scope (deferred)
- Downstream (BFS post-first-miss) batch handling — items usually unresolvable, existing single-iteration path acceptable for v1
- Heterogeneous workflow refs (`workflow: ${item.ref}`) — already handled by opaque pre-check
- Nested batch-inside-batch testing — works via recursion, explicit tests later
- Per-item input validation in planner — validator catches these pre-execution

## Related Issues

- **GH #318**: Cost AND duration estimates missing for batch-of-sub-workflow nodes
- **GH #323**: False validation error for sub-workflow inputs satisfied via batch `${item}`
- **GH #321**: Extend shared-primitive pattern to sub-workflow output population (our fix is neutral to this — operates above the level #321 targets)
- **GH #297**: Aggregation shape in compile_validation (context only, not fixed here)

## Implementation

See `implementation/implementation-plan.md` for the detailed HOW.
