# Task 140: Wrapper Chain Refactoring

> NOTE: This task was subsumed by Task 135 (Execution Core Compile-Once Redesign).

## Description

Simplify the 3,920-line execution wrapper chain that wraps 205 lines of PocketFlow. The chain has accumulated multiple concerns per wrapper, cross-wrapper coupling, and duplicated boilerplate. Task 138 (shared runner) created a single compilation callsite making this refactoring safe. Task 135 (compile-once) may change batch patterns and should land first.

## Status

done

## Priority

medium

## Problem

The wrapper chain (`InstrumentedNodeWrapper → PflowBatchNode → NamespacedNodeWrapper → TemplateAwareNodeWrapper → ActualNode`) has four structural problems:

**1. InstrumentedNodeWrapper is a god class (810 lines, 6+ concerns)**
Metrics collection, tracing, memoization caching, progress callbacks, API warning detection, and loop guards are all in one wrapper. Changes to caching risk breaking tracing. Changes to progress callbacks risk breaking metrics. Each concern should be independently testable and modifiable.

**2. Cross-wrapper coupling (action-at-a-distance)**
`InstrumentedNodeWrapper` reaches into inner wrappers to read state:
- `TemplateAwareNodeWrapper.last_resolutions` — for trace recording
- `PflowBatchNode._trace_items` — for batch trace aggregation

This means the outermost wrapper has intimate knowledge of inner wrapper internals. Adding or reordering wrappers risks breaking these reads.

**3. Duplicate proxy boilerplate (~240 lines)**
Each wrapper repeats `__getattr__`, `__rshift__`, `__sub__` delegation methods. Four wrappers × ~60 lines each of identical boilerplate that should be in a shared base.

**4. `_exec_single` / `_exec_single_with_node` duplication (~170 lines, ~80% shared)**
In `PflowBatchNode`, sequential and parallel execution paths share most logic (context isolation, error capture, retry, trace recording) but are implemented as separate methods. Bug fixes must be applied to both.

**Combined impact**: Every new feature (e.g., approval gates, execution preview) must navigate 3,920 lines of wrapper logic to find where to hook in. The wrappers are the #1 barrier to feature velocity after Task 138 eliminated the orchestration duplication.

## Solution

Decompose the wrapper chain into focused, independently testable components. Three concrete workstreams:

### A. Split InstrumentedNodeWrapper

Extract each concern into its own wrapper or middleware:
- **CachingWrapper** — memoization cache check/write, cache key computation
- **TracingWrapper** — trace collection, LLM usage capture
- **MetricsWrapper** — timing, workflow start/end
- **ProgressWrapper** — callback invocation, node start/completion signals
- **LoopGuardWrapper** — visit counting, max visits enforcement

API warning detection is already extracted (`api_warning_detector.py`). The remaining wrapper becomes a thin coordinator that applies the middleware chain.

### B. Unify batch execution paths

Merge `_exec_single` and `_exec_single_with_node` into one `_execute_item()` method with a mode parameter. The ~80% shared logic (context isolation, error handling, retry, trace capture) lives once. Sequential vs parallel dispatch remains in `_run()`.

### C. Extract shared wrapper base

Create `BaseNodeWrapper` with `__getattr__`, `__rshift__`, `__sub__` delegation. All wrappers inherit from it. ~240 lines of boilerplate deleted.

### D. Surface child workflow compilation warnings

`compile_ir_to_flow()` returns `Flow`, not `(Flow, warnings)`. Warnings from child sub-workflow compilation inside `WorkflowExecutor` are silently dropped. This task should change the return type to `(Flow, list[Any])` or use a shared-store accumulator so child warnings reach `ExecutionResult.validation_warnings`. This touches the compiler/wrapper interface which is already being modified.

## Design Decisions

- **Split InstrumentedNodeWrapper, don't flatten the chain**: The 5-wrapper chain is the right abstraction levels (template resolution, namespacing, batch, instrumentation). The problem is InstrumentedNodeWrapper doing 6 jobs, not the existence of 5 wrappers.
- **Cross-wrapper reads should become explicit interfaces**: Instead of InstrumentedNodeWrapper reaching into TemplateAwareNodeWrapper for `last_resolutions`, the template wrapper should expose resolved data through a defined protocol (e.g., write to shared store key or return from `_run()`).
- **Batch deduplication is the highest-ROI change**: `_exec_single` / `_exec_single_with_node` duplication is the most likely source of "fixed in sequential, broken in parallel" bugs. Unify first.

## Dependencies

- Task 135: Compile-Once Redesign — may change `PflowBatchNode` patterns (compile-once affects how batch items are dispatched, whether `deepcopy` is used, and instance state management). Land 135 first so this task doesn't redo batch work.

## Requirements

### InstrumentedNodeWrapper split
- Each extracted concern independently testable (can mock others)
- Application order documented (caching before tracing? metrics around everything?)
- No behavioral change in existing test suite — same metrics, same traces, same cache behavior

### Batch unification
- Single `_execute_item()` replacing `_exec_single` and `_exec_single_with_node`
- Sequential and parallel modes produce identical results for the same input
- All 4 batch error handling fixes preserved: CompilationError propagation, structured error display, all-fail abort, empty batch warning

### Shared wrapper base
- `BaseNodeWrapper` with proxy methods
- All wrappers inherit from it
- `isinstance(node, BaseNodeWrapper)` works for wrapper detection

### Child workflow warnings
- `compile_ir_to_flow()` return type change or accumulator pattern
- Warnings from child sub-workflow compilation appear in `ExecutionResult.validation_warnings`
- Batch deduplication: N identical child warnings compressed to 1

## Implementation Notes

### Copy semantics are critical

`PocketFlow._orch()` does `copy.copy()` on nodes during traversal. `NamespacedNodeWrapper` has no `__copy__`, so its `_inner_node` (TemplateAwareNodeWrapper) is shared across loop iterations. This means:
- Never store mutable per-execution state on `TemplateAwareNodeWrapper` (it leaks between iterations)
- `resolve_templates()` is intentionally pure (no instance state caching) for this reason
- Any new wrapper must define `__copy__` if it has per-execution state, or be aware of sharing

See `wrappers/CLAUDE.md` "Gotchas" section for the full explanation.

### PflowBatchNode instance state

`self._shared`, `self._errors`, `self._item_timings`, `self._trace_items` are set during execution and NOT reset between top-level executions. Safe today (recompiles per execution). After Task 135 (compile-once), these accumulate across executions. The batch unification should use local accumulators instead of instance state.

### Memoization cache computation calls resolve_templates() twice on miss

`_compute_memo_cache_key()` calls `template_wrapper.resolve_templates(shared)` for the cache key hash. Then `TemplateAwareNodeWrapper._run()` calls it again for actual resolution. This double-call is intentional (avoids stale-state bugs from caching). The split should preserve this — CachingWrapper computes its own key, TemplateWrapper resolves independently.

## Verification

- All existing tests pass with zero behavioral changes
- `InstrumentedNodeWrapper` reduced from 810 lines to <200 (coordinator only)
- `_exec_single` / `_exec_single_with_node` unified into single method
- Proxy boilerplate reduced from ~240 lines to one `BaseNodeWrapper` definition
- New test: child workflow warnings appear in `ExecutionResult.validation_warnings`
- Metrics, traces, and caching produce identical output before/after (compare trace JSON)

## References

- `src/pflow/runtime/wrappers/CLAUDE.md` — comprehensive architecture doc including copy semantics, application order, and gotchas
- `src/pflow/runtime/wrappers/instrumented_wrapper.py` — the god class to split
- `src/pflow/runtime/wrappers/batch_node.py` — batch execution with duplicated paths
- `src/pflow/runtime/compilation/compiler.py:_create_single_node()` — wrapper chain assembly
- `.taskmaster/tasks/task_138/task-review.md` — "Future Considerations > For Wrapper Chain Refactor"
- `.taskmaster/tasks/task_138/implementation/progress-log.md` — Phase 3 explains why template validation left the compiler
- `src/pflow/pocketflow/PFLOW_MODIFICATIONS.md` — the `_orch()` hack context
