# Task 157 Review: Fix Dry-Run Batch Sub-Workflow Recursion

## Metadata

- **Implementation window**: 2026-04-20
- **Branch**: `fix/dry-run-batch-recursion`
- **GitHub issues**: #318 (cost/duration), #323 (false validation error)
- **Scope**: ~450 LOC added to production, ~200 LOC tests, 8 files touched

## Executive Summary

Filled the last structural gap in the dry-run planner's dispatch matrix: batch WorkflowExecutor nodes now get full per-item recursive planning. The planner compiles the child once, plans it N times (once per batch item) with per-item template context, aggregates N child plans into one synthetic plan with per-node cache status, and populates the parent shared store with the runtime batch output shape. This fixes three user-visible symptoms: missing cost/duration estimates, "nothing cached" cascade for entire pipelines, and false validation errors on `${item}`-backed child inputs.

## Implementation Overview

### What Was Built

A batch sub-workflow planning path consisting of 6 new/modified functions in `plan.py`:

- `_plan_batch_sub_workflow` — top-level orchestrator (dispatch target)
- `_prepare_batch_sub_workflow_params` — item[0]-scoped template resolution with try/finally cleanup
- `_plan_batch_sub_workflow_items` — per-item loop calling `_build_plan_with_shared` N times
- `_resolve_per_item_sub_workflow_inputs` — per-item input resolution with non-dict fallback + WARNING diagnostic
- `_aggregate_batch_child_plans` — collapses N plans into one synthetic plan (by node_id)
- `_aggregate_batch_summary` — builds PlanSummary from N child summaries (extracted for C901)
- `_build_batch_output_shape` — mirrors runtime's `_aggregate_batch_results` output for downstream template resolution

Plus `_nested_or_level` helper (reads `*_including_nested` with per-level fallback).

### Deviations from Plan

| Plan said | Actually built | Why |
|-----------|---------------|-----|
| Representative-item (Option B, ~200 LOC) | Full per-item recursion (~400 LOC) | User demonstrated representative gives WRONG answers for the "edit one item and re-check" scenario — THE primary use case for `--dry-run` |
| Call `plan_node` with stripped `batch_config` | Call `resolve_templates` directly | Review found `plan_node` computes meaningless config hash for WorkflowExecutor (memo_cache_lookup skips WE anyway). Direct call is honest about intent. |
| `batch_items_total = batch_count` | `batch_items_total = len(entries_for_node)` | Review found branching children produce contradictory display (per-node says "1/2 would execute" but summary says "0 execute"). Fix: denominator = items that traversed this node. |
| Silent fallback on non-dict inputs | Fallback + WARNING diagnostic | Review found this masks runtime failures — planner should honestly warn when an item will fail at execution time. |
| `# noqa: C901` on complex functions | Extracted `_aggregate_batch_summary` and `_nested_or_level` | User rejected suppressions; structural extraction was achievable. |

### Implementation Approach

**Mirrors the engine's outer-batch / inner-single-item split.** The engine handles batch at `_execute_node` level (outer concern), then `_execute_single_node` is batch-unaware (inner). The planner mirrors this: `_plan_sub_workflow` dispatches batch at entry, then `_build_plan_with_shared` is batch-unaware.

**Compile once, plan N times.** Child workflow is compiled once with items[0]'s inputs (structural compilation doesn't depend on input VALUES, only presence). Each per-item call to `_build_plan_with_shared` creates its own scratch shared seeded from per-item inputs — no cross-contamination between items.

**Aggregate by node_id, not position.** Different items may take different branches in a conditional child workflow, producing different entry sequences. Grouping by `node_id` handles this safely. `batch_items_total` = number of items that actually traversed each node.

## Files Modified/Created

### Core Changes

- `src/pflow/execution/result.py` (+4 lines) — `batch_count`, `batch_parallel`, `batch_items_cached`, `batch_items_total` on PlanEntry
- `src/pflow/execution/plan.py` (+410 lines) — Batch dispatch, 6 new functions, `_nested_or_level` helper
- `src/pflow/execution/formatters/plan_formatter.py` (+58 lines) — Batch parent header, partial-cache child lines, JSON serialization, `_has_any_cached_recursive` extension
- `src/pflow/execution/CLAUDE.md` (+26 lines) — "Batch sub-workflow planning" subsection

### Test Files

- `tests/test_execution/test_plan_batch_sub_workflow.py` (NEW, 490 lines, 9 tests) — Unit tests for all batch planning paths
- `tests/test_execution/test_plan_drift.py` (+74 lines, 1 test) — Drift-catcher: partial-cache prediction matches real execution
- `tests/test_execution/formatters/test_plan_formatter.py` (+183 lines, 4 tests) — Batch display rendering

**Critical tests** (don't weaken these):
- `test_plan_batch_sub_workflow_partial_cache_matches_execution` — THE drift-catcher. Runs workflow, edits one item, asserts planner detects partial cache. Mutation: remove batch dispatch → fails.
- `test_plan_batch_sub_workflow_branching_child_reports_correct_per_node_status` — Pins the `batch_items_total = len(entries_for_node)` fix. Without it, branching children show contradictory display.
- `test_aggregate_batch_child_plans_parallel_duration_uses_max` — Pins parallel vs sequential duration semantics.

## Integration Points & Dependencies

### Incoming (consumers of the new code)

- `_plan_sub_workflow` → `_plan_batch_sub_workflow` (batch dispatch at line ~936)
- `plan_formatter._render_entry_line` → reads `batch_count`, `batch_items_cached`, `batch_items_total`
- `plan_formatter._entry_to_dict` → serializes batch fields to JSON for MCP consumers
- `plan_formatter._has_any_cached_recursive` → checks `batch_items_cached > 0`
- `_summarize` → reads aggregated `sub_plan.summary.*_including_nested` (no batch-specific code needed)

### Outgoing (what this code depends on)

- `resolve_batch_items` (batch_executor.py:32) — items resolution from shared store
- `resolve_templates` (template_resolution.py) — prologue param resolution with item[0] in scope
- `TemplateResolver.resolve_nested` (template_resolver.py) — per-item input resolution
- `_build_plan_with_shared` (plan.py:206) — per-item child planning (isolated scratch shared)
- `_resolve_declared_outputs` / `_mirror_child_shared` (plan.py:1022-1101) — per-item output extraction
- `_compile_child` (plan.py) — one-shot child compilation
- `resolve_sub_workflow` (sub_workflow_resolver.py) — child workflow file resolution

### Shared Store Keys

- `shared[node_id]` — batch output shape written after per-item loop: `{results: [...], count: N, success_count: N, error_count: 0, errors: None, batch_metadata: {...}}`. Each result has `item` + `original_index`. Downstream parent nodes template against this.
- `shared[batch_config.item_alias]` + `shared["__index__"]` — temporarily injected during prologue (try/finally cleanup). Never persists past the function.

## Architectural Decisions & Tradeoffs

### D1. Full per-item recursion over representative-item

**Reasoning**: The "elderberry argument" — representative-item (plan items[0], multiply by N) gives WRONG answers for the primary use case. If you run a batch, edit one item, then `--dry-run`, representative says "all cached" when one item would actually execute. The agent proceeds thinking it's free.

**LOC delta**: ~50 lines more than representative. The architecture (dispatch, PlanEntry fields, formatter, output shape) is identical either way. Only the inner loop differs.

**Alternative rejected**: Representative-item. Wrong for the edit-one-item scenario. Would need fixing later (Task 147's lesson: "phased approaches accrue debt the next task has to fix").

### D2. Aggregate by node_id, not list position

**Reasoning**: Conditional child workflows produce different entry sequences per item. Item "a" might take the `fast` branch, item "b" the `slow` branch. Positional aggregation silently mixes unrelated nodes.

**`batch_items_total`**: Set to `len(entries_for_node)` (items that traversed this node), NOT `batch_count` (total items). This prevents branch-local nodes from appearing as partial misses.

### D3. `resolve_templates` directly (not `plan_node`)

**Reasoning**: `plan_node` computes a config hash and checks memo cache. For WorkflowExecutor nodes, memo cache always returns `(False, None, None)` — the hash is dead computation. Calling `resolve_templates` directly is honest about intent.

### D4. 3-way merge mirroring non-batch path

**Reasoning**: The non-batch path does `curr.params → static_params → resolved_params`. The batch path initially only did `static_params → resolved_params`, missing keys that live solely on `curr.params`. Although not reachable today (compiler routes all keys through template_config), the 3-way merge is defense-in-depth that matches the non-batch path.

### D5. WARNING diagnostic (not error) for non-dict per-item inputs

**Reasoning**: Runtime raises `ValueError` when inputs resolve to non-dict. The planner should be honest about this. But it shouldn't STOP planning other items — `error_handling: continue` means runtime will skip the bad item and proceed. A WARNING surfaces the issue without blocking the plan.

### D6. Downstream batch deferred

**Reasoning**: In BFS post-first-miss mode, batch items templates usually depend on would-execute upstream (`${fetch-sources.results}` where fetch-sources hasn't executed). `resolve_batch_items` returns None → opaque entry. Per-item planning only fires in the state-machine path where upstream shared state is reliable.

## Testing Implementation

### Test Strategy

Three layers, matching the established drift-catcher pattern from Task 156:

1. **Drift-catcher** (`test_plan_drift.py`) — runs workflow end-to-end then plans, asserts prediction matches execution. THE load-bearing parity test. Has explicit mutation recipe in docstring.
2. **Unit tests** (`test_plan_batch_sub_workflow.py`) — tests each function/path in isolation: all-cached, partial-cache, empty items, opaque fallback, non-list items, parallel duration, cost aggregation, branching children, non-dict input warning.
3. **Formatter tests** (`test_plan_formatter.py`) — pins display rendering: "× N items" header, "M/N would execute", absence of redundant annotations, JSON batch fields.

### Critical Test Cases

| Test | What it catches |
|------|-----------------|
| `test_plan_batch_sub_workflow_partial_cache_matches_execution` | Planner-engine parity for batch sub-workflows. Mutation: remove dispatch → fails |
| `test_plan_batch_sub_workflow_branching_child_reports_correct_per_node_status` | `batch_items_total` uses traversal count, not batch count |
| `test_plan_batch_sub_workflow_non_dict_per_item_inputs_emits_warning` | Non-dict inputs produce WARNING, not silent fallback |
| `test_aggregate_batch_child_plans_parallel_duration_uses_max` | Parallel = max, sequential = sum |
| `test_aggregate_batch_child_plans_sums_costs_without_average_times_count` | Cost = sum of actuals, not average × N |
| `test_format_plan_text_nothing_cached_divider_respects_partial_batch_cache` | Partial batch cache prevents "nothing cached" divider |

## Unexpected Discoveries

### Pre-existing cache key drift (NOT our bug)

The lyrics-generator pipeline (the motivating example from #318) still shows "nothing cached" for `fetch-sources` even after the fix. Investigation revealed: cache entries written 3h ago have DIFFERENT cache keys than both the planner AND the engine compute NOW. The runtime and planner agree on the same key (`19e9455...`) but the stored key is `d285e99...`. This is a pre-existing cache key drift issue (prior pflow version wrote entries with different serialization). Running the workflow FRESH and then dry-running correctly shows "all cached."

### The `not downstream` guard is load-bearing

Without it, batch sub-workflows reached via BFS (downstream) crash because items templates depend on would-execute upstream. The guard routes downstream batch sub-workflows through the existing force-downstream path, which uses placeholders and skips per-item planning entirely.

### `ir_to_markdown` doesn't handle routing syntax

The `write_workflow_file` helper from `tests/shared/markdown_utils.py` doesn't emit `- next: end` directives needed for branch targets. Tests with conditional child workflows must write raw markdown instead of using the IR→markdown conversion.

### Formatter uses Click styling for `↻`

Test assertions on cached batch entries must account for ANSI escape codes from `click.style('↻', fg='blue', dim=True)`. Assert on semantic payload (`(5s ago)`, absence of `M/N would execute`) not on exact string equality.

## Patterns Established

### P1. Batch dispatch at sub-workflow entry (outer-batch / inner-single-item)

```python
# In _plan_sub_workflow, before any existing logic:
if config.batch_config and not downstream:
    return _plan_batch_sub_workflow(...)
```

Mirrors the engine's `if config.batch_config: execute_batch(...)` dispatch. The rest of `_plan_sub_workflow` is batch-unaware.

### P2. `_nested_or_level` for PlanSummary field access

```python
def _nested_or_level(summary: PlanSummary, *, nested: str, level: str) -> Any:
    value = getattr(summary, nested)
    return value if value is not None else getattr(summary, level)
```

Eliminates 7 near-identical list comprehensions. Use whenever reading `*_including_nested` with per-level fallback across N plans.

### P3. try/finally for shared-store injection in planner

```python
try:
    shared[alias] = items[0]
    shared["__index__"] = 0
    # ... template resolution ...
finally:
    shared.pop(alias, None)
    shared.pop("__index__", None)
```

Prevents leaking batch context into parent shared on exception. Matches runtime pattern at `_execute_batch_item`.

### P4. WARNING diagnostic for runtime-would-fail cases

When the planner detects a condition that runtime would reject, emit a WARNING diagnostic and fall back to safe defaults. Don't silently mask the failure. Don't error (that would stop planning other items).

### P5. Dict unpacking order: `{**shared, alias: item}`

NOT `{alias: item, **shared}`. Python evaluates left-to-right; later keys override earlier. The per-item override must come AFTER the shared spread, otherwise shared overwrites it if shared has a key matching the alias.

### Anti-patterns to avoid

- **Don't use `batch_count` (total items) as denominator for branch-local nodes** — use `len(entries_for_node)` (items that traversed this node).
- **Don't aggregate by list position** — branching children produce different entry sequences. Always group by `node_id`.
- **Don't call `plan_node` when you only need template resolution** for WorkflowExecutor. It computes a dead config hash. Call `resolve_templates` directly.
- **Don't attach per-child-workflow warnings inside the per-item loop** — they describe the child workflow (invariant across items), not individual items.
- **Don't suppress M/N when `batch_items_total == batch_count`** — suppress only when ALL items cached or ALL execute. Partial display is the value add.

## Known Limitations

1. **Downstream batch** — In BFS post-first-miss, batch sub-workflows planned as single iteration. Items usually unresolvable (depends on would-execute upstream). Cost underestimates by factor N for the rare case where items ARE resolvable downstream.
2. **Nested `sub_plan` on synthetic entries** — Preserves items[0]'s nested sub-workflow view only. Cross-item aggregation of nested sub_plans is not implemented. Aggregated SUMMARY is correct; only the displayed nested tree is approximate.
3. **Stale cache from prior pflow versions** — Cache entries written by older versions have different keys. Dry-run shows "nothing cached" until the workflow is re-run with the current version.

## AI Agent Guidance

### Quick Start for Related Tasks

**Read first (in order):**
1. `src/pflow/execution/plan.py` — search for `_plan_batch_sub_workflow` to see the complete implementation
2. `src/pflow/execution/CLAUDE.md` → "Batch sub-workflow planning" subsection
3. `tests/test_execution/test_plan_batch_sub_workflow.py` — shows all exercised paths
4. This review

**For changes to batch sub-workflow planning:**
- Run `test_plan_batch_sub_workflow_partial_cache_matches_execution` first — it's the parity invariant.
- The aggregation is in `_aggregate_batch_child_plans` + `_aggregate_batch_summary`.
- Per-item inputs are resolved in `_resolve_per_item_sub_workflow_inputs`.
- Output population is in `_build_batch_output_shape`.

**For changes to the formatter:**
- Batch-specific rendering fires when `entry.batch_count is not None` (parent) or `entry.batch_items_total is not None` (child).
- Run `test_format_plan_text_batch_*` tests.
- The `_has_any_cached_recursive` check handles batch partial-cache.

### Common Pitfalls

1. **Forgetting `not downstream` in the batch dispatch** — downstream mode uses force-downstream, which is correct. Per-item planning in downstream mode crashes because items can't resolve.
2. **Using `batch_count` instead of `len(entries_for_node)`** for denominator — causes contradictory display for branching children.
3. **Dict unpacking order** — `{alias: item, **shared}` silently uses stale values if shared has the alias key.
4. **Testing branching children with `write_workflow_file`** — `ir_to_markdown` doesn't emit `- next: end` directives. Use raw markdown for routing tests.
5. **Expecting lyrics-generator to show "all cached"** with old cache entries — pre-existing key drift issue, not a bug in this implementation. Run the workflow fresh first.

### Test-First Recommendations

When modifying batch sub-workflow planning:
1. Run `test_plan_batch_sub_workflow_partial_cache_matches_execution` — if this fails, planner-engine parity is broken.
2. Run `test_plan_batch_sub_workflow_branching_child_reports_correct_per_node_status` — if this fails, denominator logic regressed.
3. Run the full `tests/test_execution/test_plan_batch_sub_workflow.py` suite (9 tests, <1s).
4. Run `tests/test_execution/test_plan_drift.py` for full drift-catcher coverage (30+ tests).

---

*Generated from implementation context of Task 157.*
