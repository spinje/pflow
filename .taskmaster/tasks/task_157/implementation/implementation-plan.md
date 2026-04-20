# Fix: Dry-Run Batch Sub-Workflow Recursion

## Context

`--dry-run` fails for batch sub-workflow nodes (GH #318, #323). Three symptoms from one root cause:
1. **Missing cost/duration** — reports `$0 (no history)` for batch sub-workflows even when child cache exists
2. **"Nothing cached" cascade** — first batch sub-workflow fails to populate parent shared → all downstream templates fail → entire plan shows "0 cached · 47 would execute" when everything is cached
3. **False validation error** — emits "Workflow requires input 'source'" at the end of an otherwise-correct plan

**Root cause**: The planner's dispatch has a hole — batch WorkflowExecutor nodes get no per-item planning. `plan_node()` (plan_node.py:50) skips template resolution when `config.batch_config` is set, so `inputs: {source: ${item}}` never resolves. The child compile fails with "missing required input." Even if it compiled, the planner has no per-item loop for cache checking or cost aggregation.

**Fix**: Add `_plan_batch_sub_workflow` — plans the child per-item with full recursion for correct cache status, cost aggregation, and downstream template resolution.

## Architecture Context (for cold-start agents)

**Read these files first (in order):**
1. `src/pflow/execution/plan.py` — top-of-file docstring (4 load-bearing invariants)
2. `src/pflow/execution/CLAUDE.md` → "Dry-Run Planner" section (state machine, entry builders, sub-workflow recursion)
3. `src/pflow/runtime/engine/plan_node.py` — the shared decision primitive (specifically line 50: batch_config skip)
4. `src/pflow/runtime/engine/batch_executor.py:249-290` — per-item context setup pattern to mirror
5. `.taskmaster/tasks/task_156/task-review.md` → "Patterns Established" (shared primitives, state machine)

**Key existing functions (reuse, don't duplicate):**
- `_plan_sub_workflow` (plan.py:909) — non-batch sub-workflow planning (our dispatch target)
- `_build_plan_with_shared` (plan.py:206) — creates child scratch shared, walks child graph, returns (Plan, shared)
- `_compile_child` (plan.py:1253) — compiles child IR with inputs, raises `_ChildCompileFailed` on error
- `_populate_sub_workflow_outputs` → `_resolve_declared_outputs` + `_mirror_child_shared` (plan.py:1022-1101) — extracts clean child outputs for parent shared
- `resolve_batch_items` (batch_executor.py:32) — resolves items template against shared store
- `resolve_sub_workflow` (sub_workflow_resolver.py) — resolves child workflow file path
- `_raw_workflow_ref` (plan.py:1198), `_opaque_sub_workflow_entry` (plan.py:1224), `_sub_workflow_error_entry` (plan.py:1234) — shared helpers

**How the engine handles batch sub-workflows at runtime:**
1. `_execute_node` detects `config.batch_config` → calls `execute_batch`
2. `execute_batch` resolves items, then per item: `item_shared = dict(shared); item_shared[alias] = item; item_shared["__index__"] = idx`
3. Calls `_execute_single_node(node, config, item_shared)` which resolves templates per-item (NOT `plan_node` — the engine skips top-level resolution for batch, delegates per-item to the callback)
4. `WorkflowExecutor._run()` compiles child, runs child engine, exposes outputs
5. `_aggregate_batch_results` writes `{results: [...], count: N, ...}` to `shared[node_id]`

**Our planner mirrors this:** resolve items → per-item context setup → per-item template resolution → per-item child planning → aggregate → populate parent shared with batch shape.

## Expected CLI Output

**Fresh run (no cache), batch of 2 items:**
```
Dry-run for parent.pflow.md: 1 node

  ─── nothing cached — full run ───
  ▸ fanout  [workflow './child.pflow.md' × 2 items]
      ▸ echo  [shell]

Summary (including nested): 0 cached · 2 would execute (2 shell)
  (2 nodes without duration history)
```

**After a full run (all cached):**
```
Dry-run for parent.pflow.md: 1 node

  ↻ fanout  [workflow './child.pflow.md' × 2 items]
      ↻ echo  (5s ago)

Summary (including nested): 2 cached · 0 would execute
```

**Edit one item (a stays cached, b→c is new):**
```
Dry-run for parent.pflow.md: 1 node

  ▸ fanout  [workflow './child.pflow.md' × 2 items]
      ▸ echo  [shell]  1/2 would execute  ≈ $0.01 · ~2.3s

Summary (including nested): 1 cached · 1 would execute (1 shell)
  Estimated cost: ≈ $0.01
  Estimated duration: ~2.3s
```

**Display rules:**
- Parent line: `▸ node  [workflow 'path' × N items, parallel]` (include path from `sub_plan.workflow`)
- Child nodes all-cached: normal `↻ node (age)` — no M/N annotation (redundant)
- Child nodes all-execute: normal `▸ node [type]` — no M/N annotation (redundant)
- Child nodes PARTIAL: `▸ node [type]  M/N would execute  ≈ $avg · ~avg_time`
  - M = items that would execute, N = total items
  - Cost and duration are per-execution AVERAGES (what one call costs/takes)
- Parent node symbol: `↻` if ALL items fully cached, `▸` if ANY item has ANY work
- Summary: real aggregated totals (sum of actual per-item costs, parallel-aware duration)

## Files to Modify

| File | Change |
|------|--------|
| `src/pflow/execution/result.py` | Add 4 optional fields to `PlanEntry` |
| `src/pflow/execution/plan.py` | Add batch dispatch (3 lines) + `_plan_batch_sub_workflow` (~110 LOC) + `_aggregate_batch_child_plans` (~50 LOC) + `_build_batch_output_shape` (~15 LOC) |
| `src/pflow/execution/formatters/plan_formatter.py` | Batch-aware rendering (~35 LOC) |
| `src/pflow/execution/CLAUDE.md` | Document batch sub-workflow planning path |
| `tests/test_execution/test_plan_batch_sub_workflow.py` | NEW — unit tests (~200 LOC) |
| `tests/test_execution/test_plan_drift.py` | Add batch sub-workflow drift test (~80 LOC) |
| `tests/test_execution/formatters/test_plan_formatter.py` | Batch display tests (~50 LOC) |

## Implementation Steps

### Step 1: Extend PlanEntry (`result.py:82-104`)

Add after `diagnostic` field (line 103):
```python
batch_count: int | None = None
batch_parallel: bool = False
batch_items_cached: int | None = None
batch_items_total: int | None = None
```

- `batch_count` / `batch_parallel`: set on the PARENT batch entry (for "× N items" header)
- `batch_items_cached` / `batch_items_total`: set on CHILD entries inside the batch sub_plan (for "M/N would execute" per-node display)

### Step 2: Add batch dispatch in `_plan_sub_workflow` (plan.py:~934)

Insert after `downstream = cause == "downstream"` (line 934):
```python
if config.batch_config and not downstream:
    return _plan_batch_sub_workflow(
        curr, config, shared, cache, registry,
        visited_paths=visited_paths, depth=depth,
    )
```

The `not downstream` guard is critical: in BFS post-first-miss mode, the existing downstream path with `_force_downstream=True` is correct (plans entire child as downstream). Per-item planning only fires in the state-machine path where upstream shared state is reliable for item resolution.

### Step 3: Implement `_plan_batch_sub_workflow` (plan.py)

New function, ~110 LOC.

```
_plan_batch_sub_workflow(curr, config, shared, cache, registry, *, visited_paths, depth) -> PlanEntry:

    node_id = config.node_id
    node_type = config.node_type_name
    batch_config = config.batch_config

    PROLOGUE:
    1. Depth check (same as non-batch):
       if depth >= WorkflowExecutor.MAX_DEPTH_DEFAULT → _sub_workflow_error_entry

    2. Opaque pre-check on workflow ref (same):
       workflow_ref = _raw_workflow_ref(curr, config)
       if isinstance(workflow_ref, str) and "${" in workflow_ref → _opaque_sub_workflow_entry

    3. Resolve batch items:
       items = resolve_batch_items(batch_config.items_template, shared)
       - if items is None → return _opaque_sub_workflow_entry (items unresolvable)
       - if not isinstance(items, list) → return _sub_workflow_error_entry with diagnostic
       - if len(items) == 0 → return PlanEntry(status="sub_workflow", batch_count=0, sub_plan=empty_plan)

    4. Template resolution for workflow ref + inputs (try/finally for cleanup):
       NOTE: We call resolve_templates directly (NOT plan_node) because we only need
       resolved params. plan_node with stripped batch_config would compute a meaningless
       config_hash for WorkflowExecutor (memo_cache_lookup skips WE nodes anyway).

       alias = batch_config.item_alias
       try:
           shared[alias] = items[0]
           shared["__index__"] = 0
           if config.template_config:
               resolved_params, _, _ = resolve_templates(config.template_config, shared, node_id)
               merged = dict(getattr(curr, "params", {}) or {})
               if config.template_config:
                   merged.update(config.template_config.static_params or {})
               merged.update(resolved_params)
           else:
               merged = dict(getattr(curr, "params", {}) or {})
       finally:
           shared.pop(alias, None)
           shared.pop("__index__", None)

       child_inputs = dict(merged.get("inputs") or {})

    5. Resolve child workflow (same as non-batch):
       parent_file = shared.get("_pflow_workflow_file")
       base_path = Path(parent_file).parent if parent_file else Path.cwd()
       resolved = resolve_sub_workflow(merged, base_path=base_path)
       Handle errors same as _plan_sub_workflow

    6. Cycle check (same):
       resolved_path_str = str(resolved.path.resolve()) if resolved.path else None
       if resolved_path_str in visited_paths → _sub_workflow_error_entry

    7. Compile child ONCE with items[0]'s inputs:
       compiled_child = _compile_child(resolved.ir, resolved_path_str, child_inputs, registry, node_id, node_type)

    PER-ITEM LOOP:
    child_plans: list[Plan] = []
    item_outputs: list[dict[str, Any]] = []
    raw_inputs_template = config.template_config.template_params.get("inputs") if config.template_config else None

    for idx, item in enumerate(items):
        # Build per-item inputs (mirrors batch_executor.py:279-287)
        if raw_inputs_template is not None:
            # Context: shared first, then per-item overrides (NOT the reverse!)
            context = {**shared, alias: item, "__index__": idx}
            per_item_inputs = TemplateResolver.resolve_nested(raw_inputs_template, context)
            if not isinstance(per_item_inputs, dict):
                per_item_inputs = child_inputs  # fallback to items[0]'s resolved inputs
        else:
            per_item_inputs = child_inputs  # static inputs, same for all items

        # Plan this item's child execution
        child_plan, child_shared = _build_plan_with_shared(
            compiled_child, per_item_inputs, cache, registry,
            workflow_name=str(merged.get("workflow") or "<sub-workflow>"),
            _visited_paths=[*visited_paths, resolved_path_str] if resolved_path_str else visited_paths,
            _depth=depth + 1,
            _parent_workflow_file=resolved_path_str,
        )
        child_plans.append(child_plan)

        # Capture CLEAN child outputs (use declared-output/mirror-child logic, not raw child_shared)
        declared = getattr(compiled_child, "outputs", None)
        if isinstance(declared, dict) and declared:
            item_outputs.append(_resolve_declared_outputs(declared, child_shared))
        else:
            item_outputs.append(_mirror_child_shared(child_shared, per_item_inputs))

    AGGREGATION:
    aggregated_plan = _aggregate_batch_child_plans(
        child_plans, batch_parallel=batch_config.parallel, batch_count=len(items)
    )

    OUTPUT POPULATION (for downstream template resolution):
    shared[node_id] = _build_batch_output_shape(item_outputs, batch_config)

    RETURN:
    return PlanEntry(
        node_id=node_id, node_type=node_type,
        status="sub_workflow", cause="no_cache_match",
        sub_plan=aggregated_plan,
        batch_count=len(items), batch_parallel=batch_config.parallel,
    )
```

**New imports needed in plan.py:**
- `from pflow.runtime.engine.batch_executor import resolve_batch_items`
- `from pflow.runtime.template_resolver import TemplateResolver`
- `from pflow.runtime.engine.template_resolution import resolve_templates` (already used by plan_node; check if re-export needed)

### Step 4: Implement `_aggregate_batch_child_plans` (plan.py)

New function, ~50 LOC. Aggregates N per-item child plans into one synthetic Plan.

**Key design choice**: Aggregate by `node_id` (NOT position). Branching children may produce different entry sequences per item. Grouping by node_id is safe regardless of child topology.

```
_aggregate_batch_child_plans(child_plans: list[Plan], *, batch_parallel: bool, batch_count: int) -> Plan:

    1. Build node_id → list[PlanEntry] across all child plans:
       entries_by_node: dict[str, list[PlanEntry]] = defaultdict(list)
       for plan in child_plans:
           for entry in plan.entries:
               entries_by_node[entry.node_id].append(entry)

    2. Build synthetic entries (preserve order from child_plans[0]):
       seen_node_ids: list[str] = []  # preserve first-seen order
       for entry in child_plans[0].entries:
           if entry.node_id not in seen_node_ids:
               seen_node_ids.append(entry.node_id)

       synthetic_entries = []
       for nid in seen_node_ids:
           entries_for_node = entries_by_node.get(nid, [])
           cached_count = sum(1 for e in entries_for_node if e.status == "cached")
           cost_values = [e.last_cost_usd for e in entries_for_node if e.last_cost_usd is not None]
           duration_values = [e.last_duration_ms for e in entries_for_node if e.last_duration_ms is not None]
           # None-safe averaging (never produces 0 when no data exists)
           avg_cost = sum(cost_values) / len(cost_values) if cost_values else None
           avg_duration = sum(duration_values) / len(duration_values) if duration_values else None
           # Use first entry for metadata (node_type, sub_plan for nested)
           template_entry = entries_for_node[0] if entries_for_node else child_plans[0].entries[0]

           synthetic_entries.append(PlanEntry(
               node_id=nid,
               node_type=template_entry.node_type,
               status="cached" if cached_count == batch_count else "execute",
               cause="hash_match" if cached_count == batch_count else "no_cache_match",
               last_cost_usd=avg_cost,
               last_duration_ms=avg_duration,
               batch_items_cached=cached_count,
               batch_items_total=batch_count,
               sub_plan=template_entry.sub_plan,  # preserve nested sub-workflows from items[0]
           ))

    3. Build aggregated PlanSummary:
       # Read *_including_nested (fall back to per-level) from each child plan
       per_item_totals = [p.summary.total_including_nested or p.summary.total for p in child_plans]
       per_item_cached = [p.summary.cached_including_nested or p.summary.cached_count for p in child_plans]
       per_item_execute = [p.summary.execute_including_nested or p.summary.execute_count for p in child_plans]
       per_item_cost = [p.summary.estimated_cost_usd_including_nested if p.summary.estimated_cost_usd_including_nested is not None else p.summary.estimated_cost_usd for p in child_plans]
       per_item_duration = [p.summary.estimated_duration_ms_including_nested if p.summary.estimated_duration_ms_including_nested is not None else p.summary.estimated_duration_ms for p in child_plans]
       per_item_no_history = [p.summary.nodes_without_history_including_nested if p.summary.nodes_without_history_including_nested is not None else p.summary.nodes_without_history for p in child_plans]
       per_item_no_duration = [p.summary.nodes_without_duration_history_including_nested if p.summary.nodes_without_duration_history_including_nested is not None else p.summary.nodes_without_duration_history for p in child_plans]

       total_duration = max(per_item_duration) if batch_parallel else sum(per_item_duration)

       # Merge execute_by_type across all child plans
       merged_by_type: dict[str, int] = {}
       for p in child_plans:
           src = p.summary.execute_by_type_including_nested or p.summary.execute_by_type
           for k, v in src.items():
               merged_by_type[k] = merged_by_type.get(k, 0) + v

       # cost_basis: upper_bound if ANY child has upper_bound
       effective_basis = "exact"
       for p in child_plans:
           if p.summary.cost_basis == "upper_bound":
               effective_basis = "upper_bound"
               break

       # Build summary with BOTH per-level AND *_including_nested populated
       # (set equal — batch plan is already fully aggregated)
       agg_total = sum(per_item_totals)
       agg_cached = sum(per_item_cached)
       agg_execute = sum(per_item_execute)
       agg_cost = sum(c for c in per_item_cost if c)
       agg_no_history = sum(per_item_no_history)
       agg_no_duration = sum(per_item_no_duration)

       summary = PlanSummary(
           total=agg_total, cached_count=agg_cached, execute_count=agg_execute,
           cache_boundary=None, execute_by_type=merged_by_type,
           estimated_cost_usd=agg_cost, nodes_without_history=agg_no_history,
           estimated_duration_ms=total_duration, nodes_without_duration_history=agg_no_duration,
           cost_basis=effective_basis,
           # *_including_nested = same values (fully aggregated already)
           total_including_nested=agg_total, cached_including_nested=agg_cached,
           execute_including_nested=agg_execute,
           execute_by_type_including_nested=merged_by_type,
           estimated_cost_usd_including_nested=agg_cost,
           nodes_without_history_including_nested=agg_no_history,
           estimated_duration_ms_including_nested=total_duration,
           nodes_without_duration_history_including_nested=agg_no_duration,
       )

    4. Return Plan(workflow=child_plans[0].workflow, entries=synthetic_entries, summary=summary)
```

### Step 5: Implement `_build_batch_output_shape` (plan.py)

New function, ~15 LOC. Constructs batch output for `parent_shared[node_id]` so downstream parent nodes can resolve templates like `${batch_node.results}`.

```python
def _build_batch_output_shape(
    item_outputs: list[dict[str, Any]],
    batch_config: BatchConfig,
) -> dict[str, Any]:
    results = []
    for idx, output in enumerate(item_outputs):
        result = dict(output) if output else {}
        result["original_index"] = idx
        results.append(result)
    return {
        "results": results,
        "count": len(item_outputs),
        "success_count": len(item_outputs),
        "error_count": 0,
        "errors": None,
        "batch_metadata": {
            "parallel": batch_config.parallel,
            "execution_mode": "parallel" if batch_config.parallel else "sequential",
        },
    }
```

### Step 6: Update formatter (`plan_formatter.py`)

**6a. Batch parent line** — modify `_render_entry_line` (around line 207-211):

Add BEFORE the existing `sub_workflow` rendering:
```python
if entry.status == "sub_workflow" and entry.batch_count is not None:
    ref = entry.sub_plan.workflow if entry.sub_plan else "<unknown>"
    parallel_tag = ", parallel" if entry.batch_parallel else ""
    return f"{indent}▸ {entry.node_id}  [workflow '{ref}' × {entry.batch_count} items{parallel_tag}]"
```

When all items cached (parent shows ↻): check the aggregated plan — if `sub_plan.summary.execute_count == 0`, use `↻` instead of `▸`.

**6b. Batch child entries** — add check BEFORE default execute/cached rendering in `_render_entry_line`:

```python
if entry.batch_items_total is not None:
    if entry.batch_items_cached == entry.batch_items_total:
        # All cached — render as normal cached (no M/N, it's redundant)
        age_str = _format_age(entry.age_sec) if entry.age_sec else ""
        return f"{indent}↻ {entry.node_id}  {age_str}".rstrip()
    else:
        # Partial or all-execute
        execute_count = entry.batch_items_total - (entry.batch_items_cached or 0)
        tag = _NODE_TYPE_TAGS.get(entry.node_type, entry.node_type)
        # Only show M/N when partial (not when all would execute — that's also redundant)
        if entry.batch_items_cached and entry.batch_items_cached > 0:
            stats = _format_batch_node_stats(entry)
            return f"{indent}▸ {entry.node_id}  [{tag}]  {execute_count}/{entry.batch_items_total} would execute{stats}"
        else:
            # All execute — normal format with stats
            stats = _format_stats_annotation(entry)
            suffix = f"   {stats}" if stats else ""
            return f"{indent}▸ {entry.node_id}  [{tag}]{suffix}"
```

**6c. New helper `_format_batch_node_stats`**: Format `≈ $X · ~Ys` from average cost/duration (same thresholds as `_format_stats_annotation`).

**6d. JSON serialization** — add to `_entry_to_dict`:
```python
if entry.batch_count is not None:
    d["batch_count"] = entry.batch_count
    d["batch_parallel"] = entry.batch_parallel
if entry.batch_items_total is not None:
    d["batch_items_cached"] = entry.batch_items_cached
    d["batch_items_total"] = entry.batch_items_total
```

**6e. `_has_any_cached_recursive`** — add batch partial-cache detection:
```python
if entry.batch_items_cached is not None and entry.batch_items_cached > 0:
    return True
```
Prevents "nothing cached — full run" divider when some batch items are cached.

### Step 7: Tests

**7a. Drift-catcher** (`test_plan_drift.py`):
- Create parent.pflow.md with batch sub-workflow (shell/LLM child) + child.pflow.md
- Run end-to-end via WorkflowRunner to populate cache
- Plan via build_plan → assert per-item cache status matches execution
- Change one item → plan → assert partial cache detected (N-1/N cached)
- Verify cost aggregation is sum of actual per-item costs (not average × N)
- Verify parallel batch duration uses max (not sum)
- Mutation-test: temporarily break dispatch → verify drift test fails

**7b. Unit tests** (new file `test_plan_batch_sub_workflow.py`):
- All cached, partial cache, no cache scenarios
- Opaque fallback (items unresolvable — template depends on would-execute upstream)
- Empty items (batch_count=0)
- Parallel vs sequential duration in summary (max vs sum)
- Error: items resolves to non-list
- Per-node aggregation by node_id (not position-dependent)
- Nested sub-workflows within batch child (grandchild cost rollup)
- `error_handling: continue` doesn't affect plan (planner assumes all succeed — runtime handles failures)

**7c. Formatter tests** (`test_plan_formatter.py`):
- "× N items, parallel" header includes workflow path
- "M/N would execute" display for partial cache
- Normal `↻` for all-cached batch nodes (no M/N annotation)
- Normal `▸` for all-execute batch nodes (no M/N annotation)
- "nothing cached" divider NOT shown when batch items partially cached
- JSON includes batch fields when present, omits when None

### Step 8: Update CLAUDE.md

Update `src/pflow/execution/CLAUDE.md` "Dry-Run Planner" section:
- Add "Batch sub-workflow planning" subsection
- Document: dispatch condition (`config.batch_config and not downstream`)
- Document: compile-once + plan-N-times pattern
- Document: aggregation by node_id (not position) and why
- Document: batch output shape for downstream resolution
- Document: per-execution averages for display, real sums for totals
- Document: `batch_count`/`batch_parallel` on parent entry, `batch_items_cached`/`batch_items_total` on child entries

## Review-Identified Fixes (incorporated in steps above)

Issues found by 4 specialized review agents and addressed in the implementation:

1. **Dict unpacking order** (silent-failures): Per-item context MUST be `{**shared, alias: item, "__index__": idx}` — shared first, per-item overrides AFTER. The reverse silently uses stale shared values when shared contains a key matching the alias.

2. **try/finally for prologue cleanup** (silent-failures, impact-completeness): Injection of `item`/`__index__` into parent shared is wrapped in try/finally. Exception between injection and cleanup would leak stale batch context.

3. **Aggregate by node_id, not position** (silent-failures, feature-interactions): Branching children may produce different entry sequences per item. Positional aggregation would mix nodes. Group by `node_id` for safety.

4. **None-safe averaging** (silent-failures): `avg = sum(values) / len(values) if values else None`. Never produces 0 when no data exists. 0 would suppress "no history" warnings.

5. **Per-item output via declared-output/mirror-child logic** (silent-failures): Use `_resolve_declared_outputs` or `_mirror_child_shared` per item (same logic `_populate_sub_workflow_outputs` uses). Raw `child_shared` includes internal keys (`__execution__`, etc.) that would pollute the batch output and cause downstream templates to resolve against keys absent at runtime.

6. **`*_including_nested` fields explicitly computed** (impact-completeness): Sum `child_plans[i].summary.*_including_nested ?? per-level` across all items. Duration uses max (parallel) or sum (sequential). Without these, `_summarize` falls back to per-level values and parent rollup silently under-reports.

7. **`_has_any_cached_recursive` extended** (feature-interactions): Check `entry.batch_items_cached > 0` to detect partial batch cache. Without this, the "nothing cached — full run" divider appears incorrectly when some items are cached.

8. **Call `resolve_templates` directly** (validation-consistency): Instead of calling `plan_node` with a stripped `batch_config` (which computes a meaningless config hash for WorkflowExecutor nodes), call `resolve_templates` directly. Cleaner intent, no dead computation.

## Design Decisions

- **`_summarize` needs NO changes**: The aggregated sub_plan carries correct `*_including_nested` values in its summary. `_summarize` reads these and rolls up naturally. Verified by review agents.
- **`_classify` / `_represents_work` need NO changes**: Batch entry has `status="sub_workflow"` with `sub_plan` — existing dispatch handles it.
- **`_compute_totals` handles it correctly**: Parent batch entry counts as 1 WorkflowExecutor in per-level totals (same as non-batch sub-workflows). Nested costs come from `_summarize`'s rollup loop.
- **`error_handling: continue`**: Doesn't affect the planner. The planner assumes all items succeed (it's predicting cache status and cost, not simulating error handling). Runtime handles failures. The `success_count` in `_build_batch_output_shape` is set to N (optimistic for plan time).
- **No circular imports**: `plan.py` → `batch_executor.py` (for `resolve_batch_items`). `batch_executor.py` never imports from `execution/`. Verified.
- **Existing batch drift tests unaffected**: `test_plan_batch_items_cache_matches` and `test_plan_batch_llm_cost_aggregates_across_results` test standard batch nodes (ShellNode/LLMNode), not WorkflowExecutor. Our dispatch only fires for `node_type_name == "WorkflowExecutor"`. Standard batch nodes route through `_plan_standard_node` unchanged.

## Known Limitations (deferred)

1. **Downstream batch**: In BFS post-first-miss mode, batch sub-workflows are planned as single iterations (items template usually depends on would-execute upstream, so `resolve_batch_items` returns None → opaque). When items ARE resolvable downstream, cost underestimates by factor N. Acceptable for v1 — the summary displays no specific cost for opaque entries.

2. **Compile-once**: Compiles child once with items[0]'s inputs. Structural compilation doesn't depend on input VALUES (only presence). This matches runtime behavior (`_compiled_workflow_cache` reuses first compilation).

3. **Heterogeneous workflow refs**: `workflow: ${item.ref}` is caught by the opaque pre-check (`${` in workflow ref → opaque entry). Batch dispatch never fires for these.

4. **Nested batch sub-workflows**: A batch child that itself contains a batch node works naturally via recursion but is not explicitly tested in v1.

## Verification

1. `make check` — ruff + mypy + deptry clean
2. `make test` — all pass (currently 5144+)
3. Manual: Run lyrics-generator pipeline → dry-run → verify no validation error, shows "× N items" with correct cache display
4. Manual: Run → edit one source → dry-run → verify partial cache detection (N-1/N cached nodes)
5. Mutation-test the drift-catcher: temporarily break batch dispatch → assert drift test fails
6. Verify JSON output includes batch fields for MCP agent consumers
