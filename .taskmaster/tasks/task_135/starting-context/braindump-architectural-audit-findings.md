# Braindump: Architectural Audit Findings for Task 135

> Date: 2026-03-27
> Source: Deep architectural audit of compounding issues (scratchpads/architectural-debt/compounding-issues.md)

## What the task spec already covers

The spec correctly identifies: compile-once as the goal, the `initial_params` duplication root cause, the PocketFlow alignment opportunity, 6 exploration questions, key files, measured baselines, and the constraint that batch error handling fixes must be preserved.

## What the task spec is MISSING

The audit found significant structural issues in `batch_node.py` that are **orthogonal to compile-once** but should be addressed when touching this file. Doing the compile-once redesign without addressing these will result in reimplementing the same tangled structure in a new architecture.

### 1. Five tangled concern clusters (1,026 lines)

The file has 19 methods and 10 `except` blocks with these concerns interleaved:

**Tangle 1: Item execution + Error handling + Retry + Tracing** (LARGEST — 171 lines)
- `_exec_single` (lines 477-565, 89 lines) and `_exec_single_with_node` (lines 567-648, 82 lines) are **~80% identical**
- Only differences: who creates `item_shared` (internal vs pre-created), node reference (`self.inner_node` vs `thread_node`), isolation setup
- This duplication is the single largest contributor to complexity

**Tangle 2: Parallel result collection + Error handling + Status reporting** (114 lines)
- `_collect_parallel_results` (lines 728-841, marked `noqa: C901`) has two near-parallel internal branches (`if should_stop` vs normal) that both: call `future.result()`, handle CompilationError, handle Exception, call progress callback, accumulate errors

**Tangle 3: Progress reporting woven through execution** (4 sites, ~40 lines scattered)
- Identical 10-line callback blocks in: `_exec_sequential:672`, `_collect_parallel_results:767`, `_collect_parallel_results:792`, `_collect_parallel_results:825`

**Tangle 4: Trace capture + LLM cost tracking** (59 lines)
- `_capture_item_trace` reaches into 3 external systems: wrapper chain (`_find_in_chain`), shared store, LLM pricing

**Tangle 5: `post()` aggregation + Error policy + Trace cleanup + Warning push** (83 lines)

### 2. The `_batch_trace` implicit protocol

Trace data flows through a convoluted path using mutable shared state + dynamic attribute creation:
```
prep() → shared["_batch_trace"][node_id] initialized
  → _capture_item_trace() appends to it via self._shared.get("_batch_trace")
  → post() pops from shared, moves to self._trace_items (dynamic attribute)
  → InstrumentedNodeWrapper._record_trace() reads via hasattr(batch_node, "_trace_items")
```

This implicit protocol is fragile and hard to trace. A direct trace collector reference would be cleaner.

### 3. Error handling policy spread across 5 methods

The `error_handling` setting ("continue" vs "fail_fast") is evaluated in:
1. `_exec_sequential:686` — immediate re-raise
2. `_collect_parallel_results:806` — set should_stop, cancel futures
3. `_collect_parallel_results:836` — same, for executor errors
4. `_exec_parallel:900` — deferred re-raise after collection
5. `post():946` — all-fail abort (applies regardless of mode)

Each site implements a different aspect of the same policy. Consolidating into one method would make the error matrix comprehensible.

### 4. Concurrency issue: `with ThreadPoolExecutor`

At line 884, parallel mode uses `with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:`. This means:
- `__exit__` calls `shutdown(wait=True)` — blocks until ALL threads complete
- The real blocking is `as_completed()` waiting for running threads that `f.cancel()` couldn't stop (cancel only prevents unstarted tasks)
- LLM node (`llm.py:327-355`) and Python code node (`python_code.py:327-335`) correctly use bare `ThreadPoolExecutor()` with `shutdown(wait=False, cancel_futures=True)` in `finally`
- Batch should follow the same pattern

### 5. Decomposition opportunities (for the redesign)

If the compile-once redesign touches batch execution (which it must — "re-orchestrates compiled graph with different data"), these decompositions should happen at the same time:

1. **Extract unified `_execute_item(idx, item, node_chain, item_shared)`** — both seq/parallel call it, eliminating 171 lines → ~90 lines
2. **Extract progress reporting as callback wrapper** — eliminates 4 × 10 scattered identical blocks
3. **Consolidate error handling policy** — one method decides "accumulate vs raise vs abort"
4. **Extract trace capture as observer** — replace `_batch_trace` shared-store protocol with direct collector reference
5. **Flatten `_collect_parallel_results`** — remove should_stop branch duplication

### 6. Zero CompilationError propagation tests

4 production `except CompilationError: raise` sites (lines 543, 627, 778, 811) have ZERO test coverage. Verified by manual grep — the string "CompilationError" does not appear in `test_batch_node.py`.

If the redesign changes error handling, these untested paths could regress silently. Add tests BEFORE redesigning.

### 7. Zero end-to-end integration tests for batch

All batch tests are unit/component tests in `test_batch_node.py`. Zero tests in `tests/test_integration/` exercise batch through the full CLI pipeline (parse → validate → compile → batch execute → format → display). The display path divergence (Issue 2 in the audit) and the executor_service error formatting would only be caught by e2e tests.

### 8. Untested feature combinations

From the feature interaction audit:
- Partial-fail batch + sub-workflow with `error_handling: continue` (only all-fail tested with real compiler)
- Batch × conditional branching (batch on one branch, coalesce of batch output)
- Batch × nested workflow × output_schema (three-way combination)

### 9. `PflowBatchNode` has no `__copy__`

PocketFlow's `_orch` loop uses `copy.copy()` on nodes. `PflowBatchNode` has no `__copy__` method, so Python's default shallow copy is used. Currently safe because mutable state (`_shared`, `_errors`, `_item_timings`) is rebound in `prep()`/`_exec()`. But a future state addition could silently leak across loop iterations. Adding `__copy__` that explicitly handles each attribute would document the invariant.

## Recommendation

The compile-once redesign and the decomposition are **orthogonal** — compile-once changes HOW items are executed (reuse compiled flow vs recompile), while decomposition changes how the EXISTING concerns are organized (untangling errors, progress, tracing from iteration).

However, touching `batch_node.py` twice is wasteful. I'd recommend:

1. **Before redesign**: Add CompilationError propagation tests + partial-fail integration test (safety net)
2. **During redesign**: Do the decomposition alongside compile-once (same files, same refactoring pass)
3. **After redesign**: Add e2e integration tests through CLI pipeline

## Reference

Full analysis: `scratchpads/architectural-debt/compounding-issues.md` (Issue 5)
Batch error handling session braindump: `.taskmaster/tasks/task_135/starting-context/braindump-batch-error-handling-session.md`
