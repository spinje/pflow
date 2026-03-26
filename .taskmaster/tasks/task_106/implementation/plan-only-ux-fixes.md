# Task 106 Follow-up: `--only` UX Fixes and Agent Polish

## Context

Task 106 (Workflow Iteration Cache) is feature-complete (4480 tests, `make check` clean). During the final review, we discovered that `--only` interacts poorly with the output pipeline — workflows with `## Outputs` fail on `--only` runs, and the execution summary doesn't explain why nodes were skipped. These fixes make `--only` and caching work well for AI agents as first-class users.

**Six issues, ordered by priority:**

1. `--only` + `## Outputs` → `OutputResolutionError` (broken)
2. `--only` output extraction doesn't return the target node's output (broken)
3. Execution summary unclear about `--only` (confusing)
4. No aggregate cache stats in output (missing)
5. Saved workflows get cached despite spec exclusion (spec update)
6. Cache DB init failure is silent (minor)

## Verified Facts (from codebase investigation)

**Compiler call order** (compiler.py:756-762):
- Step 10b: `_apply_only_node_stop(flow, only_node_id, nodes)` — patches `flow.get_next_node`
- Step 11: `_apply_run_hooks(flow, ir_dict)` — wraps `flow.run`
- `only_node_id` extracted from `initial_params.get("__only_node__")` at line 757

**`_apply_run_hooks`** (compiler.py:601-623):
- Wraps `flow.run` in `run_with_hooks` closure
- After `original_run(shared_storage)` returns, unconditionally calls `populate_declared_outputs(shared_storage, ir_dict)` if outputs exist and result isn't an error
- `populate_declared_outputs()` (output_resolver.py:95-153) raises `OutputResolutionError` for unresolved non-coalesce outputs

**Display pipeline**:
- `format_execution_success()` (success_formatter.py:12-97) builds the formatted dict. Called by BOTH CLI (workflow_output.py:197) and MCP (mcp_server/services/execution_service.py:139). **Both call sites must stay in sync.**
- `format_execution_success()` calls `build_execution_steps()` (execution_state.py:106-159) which returns a **list** of step dicts
- The list is wrapped in `result["execution"] = {"steps": steps, "nodes_executed": N, "nodes_total": N, ...}` at success_formatter.py:86-91
- `_display_execution_summary()` (workflow_output.py:549-598) receives the `formatted_result` dict, iterates `execution.steps`, renders each via `_format_node_status_line()`
- The completion header `_display_workflow_completion_status()` (workflow_output.py:531-546) currently shows `✓ Workflow completed in X.Xs` — this is where cache stats go
- **`_display_execution_summary` does NOT have access to `shared_storage`** — it only sees the formatted dict. All data must flow through `format_execution_success()`

**`build_execution_steps()`** (execution_state.py:106-159):
- Iterates ALL IR nodes (line 122: `for node in workflow_ir["nodes"]`)
- Marks each as `"completed"` (in `completed_nodes`), `"failed"` (is `failed_node`), or `"not_executed"` (catch-all)
- Returns `list[dict]` — no metadata outside the step list

**Output extraction** (two independent paths):
- `executor_service._extract_default_output()` (line 704-730): declared outputs → common root keys (`result`, `output`, `response`, `data`) → last IR node namespace
- `workflow_output._handle_text_output()` (line 162-237): output_key → declared outputs → `_find_auto_output()` (namespace search)
- With `--only`: last IR node may not have executed, declared outputs reference unreachable nodes

**MCP parity**: `format_execution_success()` takes no new required params — new data comes from `shared_storage` which is already passed. MCP call site (execution_service.py:139-147) needs no signature changes.

---

## Phase 1: Fix `--only` Output Pipeline

**Goal**: When `--only` is active, skip declared output resolution and return the target node's output directly. This fixes Issues 1 and 2 together.

**Files to modify**:
- `src/pflow/runtime/compilation/compiler.py`

### Step 1.1: Pass `only_node` to `_apply_run_hooks()`

Change signature and call site at line 762:

```python
# Current (compiler.py:601):
def _apply_run_hooks(flow: Any, ir_dict: dict[str, Any]) -> None:

# New:
def _apply_run_hooks(flow: Any, ir_dict: dict[str, Any], only_node: str | None = None) -> None:

# Current call site (compiler.py:762):
_apply_run_hooks(flow, ir_dict)

# New:
_apply_run_hooks(flow, ir_dict, only_node=only_node_id)
```

### Step 1.2: Modify `run_with_hooks` to handle `--only`

Replace the body of `run_with_hooks` inside `_apply_run_hooks`:

```python
def run_with_hooks(shared_storage: dict[str, Any]) -> str:
    if "__execution__" in shared_storage and "node_visit_counts" in shared_storage["__execution__"]:
        shared_storage["__execution__"]["node_visit_counts"] = {}

    result = original_run(shared_storage)

    is_error = result and isinstance(result, str) and result.startswith("error")

    if only_node:
        # Store --only metadata for execution summary display
        if "__execution__" in shared_storage:
            shared_storage["__execution__"]["only_node"] = only_node
        # Promote target node's output to root for extraction (skip declared outputs)
        if not is_error:
            target_output = shared_storage.get(only_node)
            if isinstance(target_output, dict):
                shared_storage["result"] = target_output
    elif has_outputs and not is_error:
        populate_declared_outputs(shared_storage, ir_dict)

    return str(result)
```

**Key design decisions**:
- `if only_node:` runs BEFORE the `elif has_outputs:` — `--only` takes precedence
- `only_node` metadata stored in `__execution__` regardless of success/error (display layer needs it)
- Output promotion ONLY on success (`not is_error`) — on error, let the error handler run normally
- `shared_storage["result"]` chosen because output extraction tries common root keys `["result", "output", "response", "data"]` in order — works for both `_extract_common_outputs()` (executor_service) and `_find_auto_output()` direct storage check (workflow_output)

**Edge cases handled**:
- `--only` target returns error → no output promotion, error handler shows the error
- `--only` target is cached → `shared[target_node_id]` was restored by memoization cache, promotion works
- `--only` target is last node → flow runs normally, promotion happens but was technically unnecessary (harmless)
- Workflow has NO `## Outputs` + `--only` → promotion still happens, `_find_auto_output` now finds `shared["result"]` directly

### Step 1.3: Tests

Tests MUST go through `compile_ir_to_flow()` to exercise `_apply_run_hooks`. The existing `--only` tests use raw `Flow` objects which bypass run hooks.

Need a helper to compile a minimal IR dict. The IR needs: `nodes` array with `id`/`type`/`params`, `edges` array, and optionally `outputs`. Use real test node types (e.g., `echo` which is registered in the test registry via `isolate_pflow_config`).

**Test 1: `--only` with `## Outputs` referencing downstream node**
- IR: nodes [A, B, C], outputs: `{summary: {source: "${C.result}"}}`
- Compile with `initial_params={"__only_node__": "B"}`
- `flow.run(shared)` → no exception
- Assert `shared["result"]` contains B's output

**Test 2: `--only` target returns error**
- IR: nodes [A, error_node, C]
- `--only error_node`
- Assert `"result" not in shared` (no promotion on error)

**Test 3: `--only` without `## Outputs`**
- IR: nodes [A, B, C], no outputs section
- `--only B`
- Assert `shared["result"]` contains B's output

---

## Phase 2: `--only` Context in Execution Summary

**Goal**: The execution summary clearly shows `--only` stopped the flow. One summary line replaces individual `not_executed` nodes.

**Agent sees (text)**:
```
✓ Workflow completed in 0.3s
Nodes executed (2/4):
  ✓ fetch-data (0ms) [cached]
  ✓ process (250ms)
  ⤷ Stopped after 'process' (--only), 2 remaining nodes skipped
```

**Agent sees (JSON)**:
```json
{
  "execution": {
    "nodes_executed": 2,
    "nodes_total": 4,
    "only_node": "process",
    "nodes_skipped": 2,
    "steps": [
      {"node_id": "fetch-data", "status": "completed", "cached": true, ...},
      {"node_id": "process", "status": "completed", "cached": false, ...},
      {"node_id": "summarize", "status": "not_executed", ...},
      {"node_id": "evaluate", "status": "not_executed", ...}
    ]
  }
}
```

JSON keeps ALL steps (for programmatic access). Text display filters out `not_executed` when `--only` is active and shows the summary line instead.

**Files to modify**:
- `src/pflow/execution/formatters/success_formatter.py` — add `only_node` and `nodes_skipped` to `execution` dict
- `src/pflow/cli/workflow_output.py` — filter `not_executed` steps in text, show summary line, fix header count

### Step 2.1: Add `only_node` to `format_execution_success()` output

In `success_formatter.py`, inside the `if steps:` block (line 81-91), add after existing fields:

```python
result["execution"] = {
    "duration_ms": ...,
    "nodes_executed": completed_count,
    "nodes_total": nodes_total,
    "steps": steps,
}

# --only metadata (from __execution__ state)
exec_state = shared_storage.get("__execution__", {})
only_node = exec_state.get("only_node")
if only_node:
    result["execution"]["only_node"] = only_node
    not_executed_count = sum(1 for s in steps if s["status"] == "not_executed")
    result["execution"]["nodes_skipped"] = not_executed_count
```

**No changes to `format_execution_success` signature** — `only_node` comes from `shared_storage` which is already a parameter. MCP call site needs no update.

### Step 2.2: Filter `not_executed` nodes in text display

In `_display_execution_summary()` (workflow_output.py:549-598), modify the step rendering loop:

```python
# Current (line 588-592):
if steps:
    click.echo(f"Nodes executed ({total_nodes}):", err=True)
    for step in steps:
        status_line = _format_node_status_line(step)
        click.echo(status_line, err=True)

# New:
if steps:
    only_node = execution.get("only_node")
    nodes_skipped = execution.get("nodes_skipped", 0)

    # Show executed nodes count (not total)
    executed_steps = [s for s in steps if s["status"] != "not_executed"] if only_node else steps
    click.echo(f"Nodes executed ({len(executed_steps)}):", err=True) if not only_node else \
        click.echo(f"Nodes executed ({len(executed_steps)}/{total_nodes}):", err=True)

    for step in executed_steps:
        status_line = _format_node_status_line(step)
        click.echo(status_line, err=True)

    # --only summary line
    if only_node and nodes_skipped > 0:
        noun = "node" if nodes_skipped == 1 else "nodes"
        click.echo(f"  ⤷ Stopped after '{only_node}' (--only), {nodes_skipped} remaining {noun} skipped", err=True)
```

Note: when `--only` is NOT active, display all steps unchanged (including `not_executed` from branches etc). The filtering ONLY applies when `--only` is active.

### Step 2.3: Tests

- Test `_display_execution_summary` with `--only` in formatted result: verify `not_executed` nodes hidden, summary line shown
- Test `_display_execution_summary` without `--only`: verify all nodes shown, no summary line
- Test JSON output contains `only_node` and `nodes_skipped` when `--only` is active
- Test JSON output has no `only_node` field when `--only` is not active

---

## Phase 3: Aggregate Cache Stats

**Goal**: Show cache stats so agents immediately know how many nodes were cached vs freshly executed.

**Agent sees (text)**:
```
✓ Workflow completed in 2.3s (3 cached, 2 executed)
```

No change when zero nodes are cached (don't add noise to the default case).

**Agent sees (JSON)**:
```json
{
  "execution": {
    "cache_hits": 3,
    ...
  }
}
```

**Files to modify**:
- `src/pflow/execution/formatters/success_formatter.py` — add `cache_hits` to execution dict
- `src/pflow/cli/workflow_output.py` — add cache stats to completion header

### Step 3.1: Add `cache_hits` to `format_execution_success()`

In `success_formatter.py`, inside the `execution` dict construction:

```python
# Count cache hits from steps
cache_hit_count = sum(1 for s in steps if s.get("cached"))
if cache_hit_count > 0:
    result["execution"]["cache_hits"] = cache_hit_count
```

### Step 3.2: Modify completion header

`_display_workflow_completion_status()` (workflow_output.py:531-546) currently receives `duration_s`, `status`, `has_stderr_warnings`. It needs access to cache stats from the formatted result.

**Option**: Pass the cache stats through from `_display_execution_summary()` which has the formatted result:

In `_display_execution_summary()`, before calling `_display_workflow_completion_status()` at line 585, extract cache stats from `execution`:

```python
cache_hits = execution.get("cache_hits", 0)
completed_count = execution.get("nodes_executed", 0)
executed_fresh = completed_count - cache_hits
```

Then modify `_display_workflow_completion_status` to accept and display them:

```python
# Current:
click.echo(f"✓ Workflow completed in {duration_s:.3f}s", err=True)

# New (when cache_hits > 0):
click.echo(f"✓ Workflow completed in {duration_s:.3f}s ({cache_hits} cached, {executed_fresh} executed)", err=True)
```

### Step 3.3: Tests

- Test completion header with mixed cached/executed nodes
- Test completion header with all cached (N cached, 0 executed)
- Test completion header with no cached nodes (no cache stats shown)
- Test JSON output has `cache_hits` field when nodes are cached

---

## Phase 4: Cache DB Init Warning

**Goal**: If the SQLite cache can't be initialized, warn the agent. DB init failure means NO caching for the entire run.

**Files to modify**:
- `src/pflow/runtime/cache.py`

### Step 4.1: Upgrade `_init_db` failure to warning

```python
# Current (cache.py:166):
except sqlite3.Error:
    logger.debug("Failed to initialize memoization cache DB", exc_info=True)

# New:
except sqlite3.Error:
    logger.warning(
        "Memoization cache unavailable — all nodes will execute fresh. "
        "Check permissions on ~/.pflow/cache/",
        exc_info=True,
    )
```

Individual `get()`/`put()` failures stay at `DEBUG` — those are per-node, non-fatal. But total DB failure disables the feature for the entire run.

### Step 4.2: Tests

- Test that DB init failure logs at WARNING (mock `sqlite3.connect` to raise)

---

## Phase 5: Accept Saved Workflow Caching

**Goal**: Spec update only. Saved workflows benefit from caching during iteration.

**Files to modify**:
- `.taskmaster/tasks/task_106/task-106.md` — remove "Out of scope: saved workflows" exclusion
- `.taskmaster/tasks/task_106/implementation/progress-log.md` — document the decision

**No code changes.** The implementation already caches saved workflows through the same `_initialize_shared_store()` path. Cache keys are content-addressed (node config + resolved inputs) — correct regardless of workflow origin.

---

## Implementation Order

Phases 1 and 2 share code in `compiler.py:_apply_run_hooks`. Implement together.

```
Phase 1+2 (--only output + summary) → Phase 3 (cache stats) → Phase 4 (DB warning) → Phase 5 (spec update)
```

## File Summary

| File | Phase | Change |
|------|-------|--------|
| `src/pflow/runtime/compilation/compiler.py` | 1+2 | `_apply_run_hooks` takes `only_node`, skips output resolution, promotes target output, stores in `__execution__` |
| `src/pflow/execution/formatters/success_formatter.py` | 2, 3 | Add `only_node`, `nodes_skipped`, `cache_hits` to execution dict |
| `src/pflow/cli/workflow_output.py` | 2, 3 | Filter `not_executed` in text when `--only`, show summary line, cache stats in header |
| `src/pflow/runtime/cache.py` | 4 | `_init_db` failure → WARNING level |
| `.taskmaster/tasks/task_106/task-106.md` | 5 | Remove saved workflow exclusion |
| `.taskmaster/tasks/task_106/implementation/progress-log.md` | 5 | Document decision |
| `tests/test_runtime/test_cache_integration.py` | 1, 2, 3 | New tests through `compile_ir_to_flow` |
| `src/pflow/runtime/compilation/CLAUDE.md` | 1 | Update `_apply_run_hooks` docs |

## Verification

After all phases:
1. `make test` — all tests pass
2. `make check` — lint and type check clean
3. Manual test: `pflow workflow.pflow.md --only <node>` where workflow has `## Outputs` → no error, target node's output displayed
4. Manual test: second run of cached workflow shows "(N cached, M executed)" in completion header
5. Manual test: `--only` summary line shows "⤷ Stopped after X, N remaining nodes skipped"
6. Verify MCP parity: `format_execution_success()` signature unchanged, new fields present in output
