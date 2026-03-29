# Task 135: Explore Execution Core Redesign — Compile-Once and PocketFlow Alignment

## Description

Explore redesigning pflow's execution core so sub-workflows compile once per batch (not N times for N items) and the data-flow model aligns with PocketFlow's intended design. This is an architectural exploration — the outcome may be a refactor plan, a modified PocketFlow variant, or a decision that the current approach is acceptable with targeted fixes.

## Status

not started

## Priority

medium

## Depends On

Task 138 (Shared Execution Pipeline) — provides unified param preparation path so `initial_params` has a consistent shape. Task 138's `_prepare_compilation()` is what this task splits further into structural validation and input preparation.

## Scope Update (2026-03-29)

This task now also includes batch decomposition (from Issue 5): unify `_exec_single` / `_exec_single_with_node` (~170 lines of duplication), consolidate error handling policy, deduplicate progress callbacks. Same files, same refactoring pass.

Key additional context from Task 138 research:
- `braindump-pipeline-analysis.md` in `.taskmaster/tasks/task_138/starting-context/` has the full `initial_params` flow trace, wrapper chain analysis, and batch decomposition details
- After Task 138, the `_prepare_compilation()` function (renamed from `_validate_workflow()`) contains only input preparation — this task splits it further
- The implementing agent should prototype compile-once (measure deepcopy cost) before committing to approach

## Problem

pflow's execution model has diverged from PocketFlow's design in ways that compound into real costs:

### 1. Sub-workflows recompile per batch item (measured overhead)

When a batch iterates over a workflow node, `WorkflowExecutor.exec()` calls `compile_ir_to_flow()` for every single item. The workflow structure is identical every time — only input data changes.

Measured cost per `compile_ir_to_flow()` call:
- 2-node workflow: **~20ms**
- 5-node workflow: **~50ms**

At scale: a batch of 50 items over a 5-node sub-workflow wastes **2.5 seconds** in pure compilation overhead before any actual work happens.

### 2. Data-flow model divergence

PocketFlow's model: compile flow once, pass per-item data through `set_params()` during orchestration.

pflow's model: compile per item, bake per-item data into `initial_params` at compile time, also put it in the shared store (duplicated).

This divergence created:
- The `_orch()` modification in `pocketflow/__init__.py` (`if params is not None: curr.set_params(p)`) — a hack to prevent `set_params()` from overwriting compile-time params
- `initial_params` priority in `_build_resolution_context()` — per-item values in `initial_params` override shared store values, making compile-once impossible without changes
- `PflowBatchNode` reimplementing what PocketFlow's `BatchFlow` already does, but differently

### 3. The `initial_params` duplication

Per-item values exist in TWO places:
1. `initial_params` (baked into `TemplateAwareNodeWrapper` during compilation)
2. `child_storage` (the shared store passed to `sub_flow.run()`)

`_build_resolution_context()` does `context.update(self.initial_params)` — so `initial_params` always wins. This means you can't compile once and reuse the flow — subsequent items would get the first item's stale `initial_params` values.

## Solution Direction (Exploratory)

The goal is a clean execution core where compile-once falls out naturally from the design. PocketFlow is a design reference, not a sacred dependency — we can modify or fork the ~200 lines freely.

### Key Principle

Using PocketFlow as-is has no intrinsic value. Having good architecture and being able to compile once does.

### What "Clean" Looks Like

| Concern | Current (messy) | Target (clean) |
|---|---|---|
| **Compile-time** | Bakes per-item data into `initial_params` | Structural only — node types, edges, wiring |
| **Runtime data** | Duplicated in `initial_params` AND shared store | One path — shared store only |
| **Batch** | Custom wrapper calls `_run()` N times, recompiles | Re-orchestrates compiled graph with different data |
| **`_orch()` params** | Hacked to conditionally skip `set_params()` | Clean contract — `set_params()` does the right thing |
| **Template resolution** | `initial_params` overrides shared store | Shared store is the single source of runtime data |

### Questions to Explore

1. **Can `set_params()` be made to work for both compile-time config AND per-item data?** The TemplateAwareNodeWrapper splits params into template/static at `set_params()` time. Calling it again during orchestration would need to merge, not overwrite.

2. **Can we use PocketFlow's `BatchFlow` pattern (or a variant)?** `BatchFlow._run()` calls `_orch(shared, {**self.params, **bp})` per item — same graph, different params. This is compile-once by design. But it requires `set_params()` to work during orchestration.

3. **Should the `_orch()` modification be reverted, extended, or replaced?** The modification exists because pflow uses params differently than PocketFlow intended. If we align the data-flow model, the hack becomes unnecessary.

4. **How does `prepare_inputs()` work without per-item values at compile time?** Currently validates required inputs exist in `initial_params`. Compile-once needs structural validation separated from input validation. Can we split `_validate_workflow()` into "structural" (compile-time) and "input" (runtime)?

5. **Can `PflowBatchNode` be simplified?** It currently handles sequential/parallel execution, error handling, retries, tracing — all of which are valuable. But the core iteration pattern (per-item `_run()` calls) might be replaceable with a BatchFlow-like re-orchestration.

6. **What about the wrapper chain?** `InstrumentedNodeWrapper → PflowBatchNode → NamespacedNodeWrapper → TemplateAwareNodeWrapper → ActualNode` was designed for the current model. How does compile-once affect each layer?

## Design Decisions

- **This is exploratory, not prescriptive.** The task is to investigate, prototype, and propose — not to commit to a specific implementation upfront.
- **PocketFlow can be modified freely.** It's pflow's execution core, not an external dependency. The ~200 lines exist to serve pflow.
- **Backwards compatibility is not a concern** (no users yet), but existing test coverage should guide what's safe to change.
- **Compile-once is the concrete, measurable goal.** Architectural cleanup is valuable but secondary — we measure success by whether batch compilation overhead goes from O(N) to O(1).

## Dependencies

None — this is an exploration task. Implementation tasks would be created based on findings.

## Requirements

### Exploration Phase
- Investigate each of the 6 questions above
- Prototype at least one approach (compile-once with current PocketFlow vs. modified core)
- Measure compilation overhead before/after
- Identify which existing tests break and why

### Deliverable
- A design document (scratchpad or task spec) with:
  - Recommended approach with rationale
  - List of files/components affected
  - Risk assessment
  - Estimated scope for implementation
  - Open questions that need resolution

### Constraints
- The 4 batch error handling fixes from this session must continue working: CompilationError propagation (#153), structured error display (#154), all-fail abort (#157), empty batch warning (#160)
- `PflowBatchNode`'s features (parallel execution, error handling, retries, tracing) must be preserved regardless of architecture changes

## Implementation Notes

### Key Files

**PocketFlow core** (the ~200 lines):
- `src/pflow/pocketflow/__init__.py` — `BaseNode`, `Node`, `Flow`, `BatchFlow`, `_orch()`
- `src/pflow/pocketflow/PFLOW_MODIFICATIONS.md` — documents the `_orch()` hack and its implications

**Compilation pipeline**:
- `src/pflow/runtime/compilation/compiler.py` — `compile_ir_to_flow()`, node instantiation, wrapper chain assembly
- `src/pflow/runtime/compilation/compile_validation.py` — `_validate_workflow()`, `prepare_inputs()`

**Data-flow model**:
- `src/pflow/runtime/wrappers/template_wrapper.py` — `_build_resolution_context()` (the `initial_params` override), `set_params()` (template/static split)
- `src/pflow/runtime/workflow_executor.py` — `_compile_sub_workflow()`, `exec()`, child param construction

**Batch execution**:
- `src/pflow/runtime/wrappers/batch_node.py` — `PflowBatchNode`, per-item `_run()` calls, parallel/sequential dispatch

### Measured Baselines

```
compile_ir_to_flow() per call:
  2-node workflow: ~20ms
  5-node workflow: ~50ms

Target: 1 compilation + N × deep-copy (expected ~1-5ms per copy)
```

### What We Verified During Investigation

- `compile_ir_to_flow()` is structurally independent of per-item `initial_params` values (node types, edges, wiring don't change)
- `initial_params` affects: template resolution context priority, input validation, template validation — all deferrable to runtime
- Per-item values already exist in `child_storage` (shared store) — the duplication in `initial_params` is the only blocker for compile-once
- PocketFlow `Flow._orch()` uses `copy.copy()` on nodes during traversal — shallow copy shares inner wrappers, which has implications for reuse
- Parallel batch already uses `copy.deepcopy()` per thread — so deep-copy cost is already paid in parallel mode

## Verification

- Compilation overhead for batched sub-workflows is O(1) not O(N)
- All existing tests pass (or are updated with clear rationale)
- The `_orch()` modification is either reverted or replaced with a clean solution
- `initial_params` is no longer duplicating per-item data
- Batch error handling fixes (#153, #154, #157, #160) continue working

## References

- `src/pflow/pocketflow/PFLOW_MODIFICATIONS.md` — documents current divergence and future considerations
- `src/pflow/pocketflow/docs/` — PocketFlow documentation
- Memory: `project_batch_compile_once.md` — architectural notes from this session
- GitHub issues: #153, #154, #155, #157, #159, #160 — related batch error handling work
- Scratchpad: `scratchpads/batch-error-handling-compile-vs-runtime/` — bug report and test workflows
