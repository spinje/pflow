# Braindump: Task 138 → Task 135 Handoff

> Knowledge transfer from the Task 138 implementation conversation. Focused on what Task 135 needs that ISN'T written in the task-135.md spec, the task-138 review, the progress log, or CLAUDE.md files.

## Where I Am

When you read this, Task 138 is merged to main.The codebase now has a single `WorkflowRunner` that both CLI and MCP call. Task 135's dependency on Task 138 is satisfied.

## What Task 135 Must Know About the Post-138 State

### The `initial_params` flow CHANGED

The task-135.md spec describes the old flow. Here's the actual current flow:

```
CLI/MCP params (user-provided)
  → WorkflowRunner.run() copies at boundary: params = dict(params)
  → _fill_declared_defaults(ir, params)
      adds real defaults for optional inputs
      adds __pflow_declared_X__ placeholders for required/env inputs
  → _validate() — WorkflowValidator.validate(ir, params)
      sees all declared input names (real or placeholder)
  → _strip_placeholders(params)
      removes __pflow_declared_X__ entries
  → _initialize_shared_store(params, ...)
      shared_store.update(params)  ← STILL BEFORE _prepare_compilation mutates initial_params
  → compile_ir_to_flow(ir, initial_params=params, ...)
      → _prepare_compilation(ir, registry, initial_params, ...)
          calls prepare_inputs() — THE ONLY CALL
          mutates initial_params: adds defaults, __template_resolution_mode__, __env_param_names__
      → _instantiate_nodes(initial_params)
          every TemplateAwareNodeWrapper gets REFERENCE to same initial_params dict
  → flow.run(shared_store)
      → _build_resolution_context(shared):
          context = dict(shared)
          context.update(self.initial_params)  ← initial_params OVERRIDE shared store
```

**The critical subtlety is the same**: shared store is seeded BEFORE `_prepare_compilation` mutates `initial_params`. So defaults added by `prepare_inputs()` are in `initial_params` but NOT in shared store. The `context.update(initial_params)` override is what makes defaults work.

**What changed**: `prepare_inputs()` now runs EXACTLY ONCE (in the compiler's `_prepare_compilation`). The old triple-call (CLI early, Runner, compiler) is gone. The Runner's `_fill_declared_defaults` is a lightweight 6-line method that only marks which inputs exist — it doesn't do 5-tier resolution.

### The `_prepare_compilation` signature changed

```python
def _prepare_compilation(
    ir_dict: dict[str, Any],
    registry: Registry,
    initial_params: dict[str, Any],
) -> tuple[dict[str, Any], list[Any]]:
```

The `validate` and `validate_templates` boolean parameters were REMOVED. Template validation no longer runs in the compiler at all — it's in WorkflowValidator (called by the Runner before compilation). The return type is now a tuple `(initial_params, warnings)` where warnings is always `[]` (template warnings come from WorkflowValidator, not the compiler).

### The `compile_ir_to_flow` signature changed

```python
def compile_ir_to_flow(
    ir_json: Union[str, dict[str, Any]],
    registry: Registry,
    initial_params: Optional[dict[str, Any]] = None,
    metrics_collector: Optional[Any] = None,
    trace_collector: Optional[Any] = None,
    only_node: Optional[str] = None,
) -> Flow:
```

`validate` parameter removed. `only_node` added as explicit parameter (was `__only_node__` in initial_params).

### `WorkflowExecutorService` is gone

Completely deleted. The error helpers (`build_error_list`, `determine_error_category`) are now standalone functions in `executor_service.py`. The class that Task 135's spec might reference (`WorkflowExecutorService.execute_workflow()`) doesn't exist. The Runner's `_compile_and_execute` is the equivalent.

### Sub-workflow compilation path

`WorkflowExecutor.exec()` at `runtime/workflow_executor.py:176` still calls `compile_ir_to_flow()` directly — NOT through the Runner. This is where compile-once matters most. The current call:

```python
sub_flow = self._compile_sub_workflow(workflow_ir, workflow_path, child_params, child_trace)
```

Which internally does:

```python
compile_ir_to_flow(
    workflow_ir,
    registry=Registry(),
    initial_params=child_params,
    metrics_collector=child_metrics,
    trace_collector=child_trace,
)
```

`child_params` is a FRESH dict per batch item (from `_extract_child_inputs()` with resolved template values). This is why recompilation happens — each item has different `child_params`.

## Hard-Won Knowledge from Task 138

### `PflowBatchNode` instance state — THE compile-once trap

The progress log mentions this but doesn't explain how dangerous it is. Here's the specific problem:

`PflowBatchNode` sets during execution:
- `self._shared` (line ~220 in batch_node.py)
- `self._errors` (accumulated during batch)
- `self._item_timings` (per-item timing)
- `self._trace_items` (trace data per item)

These are set in `_run()` and read in `post()`. They're NOT reset between top-level executions. Today this is safe because each execution recompiles → creates new `PflowBatchNode` instances. With compile-once, the same instance runs multiple times. The second execution accumulates onto the first's `_errors` and `_item_timings`.

**The fix**: Either reset these in `_run()` before the batch loop, or use a local accumulator pattern instead of instance state.

### `TemplateAwareNodeWrapper` is shared across `copy.copy()` iterations

From `wrappers/CLAUDE.md` (critical for compile-once): PocketFlow's `_orch` loop does `copy.copy()` on the outermost wrapper (`InstrumentedNodeWrapper`). But `NamespacedNodeWrapper` has no `__copy__`, so its `_inner_node` (the `TemplateAwareNodeWrapper`) is shared across loop iterations.

**For compile-once**: If you deepcopy the entire flow for reuse, the template wrapper's `self.initial_params` is a REFERENCE to the same dict all nodes share. Changing it for one reuse affects all. You'd need to either:
- Deepcopy the flow (copies the dict reference, but the dict itself is shared)
- Or: Stop using `initial_params` as the override mechanism entirely (the actual goal of Task 135)

### The `_orch()` hack's real purpose

`PFLOW_MODIFICATIONS.md` documents it, but here's the concrete scenario: PocketFlow's `_orch()` calls `curr.set_params(p)` during traversal. In pflow, `set_params()` on `TemplateAwareNodeWrapper` splits params into template/static. If called during orchestration with orchestration params (like batch's `{**self.params, **bp}`), it would OVERWRITE the compile-time template/static split.

The hack: `if params is not None: curr.set_params(p)` — only calls `set_params()` when params are explicitly provided. Since pflow's normal flow never uses orchestration-level params (it bakes everything into `initial_params` at compile time), the conditional is always false during normal execution.

**For Task 135**: If you move per-item data to the shared store and stop baking it into `initial_params`, you might want `set_params()` to work during orchestration — which means the hack could be reverted. But `set_params()` on `TemplateAwareNodeWrapper` does more than just store params (it does template/static splitting) — so you'd need to ensure that split is already done at compile time and orchestration params don't redo it.

### `deepcopy` cost — STILL UNVERIFIED

The task-135 spec says: "Target: 1 compilation + N × deep-copy (expected ~1-5ms per copy)." This was never measured. The wrapper chain includes:
- `InstrumentedNodeWrapper` (810 lines, references to shared collectors)
- `PflowBatchNode` (861 lines, mutable instance state)
- `NamespacedNodeWrapper` (94 lines)
- `TemplateAwareNodeWrapper` (710 lines, `initial_params` dict reference)
- Actual node instance

Deepcopy of this chain might be expensive because:
- `MCPNode` instances might hold transport references
- Collector references (metrics, trace) should NOT be deepcopied (shared across batch)
- The `__memoization_cache__` reference in shared store is a SQLite connection

NEEDS VERIFICATION: Measure `copy.deepcopy(flow)` time for a real 5-node workflow before committing to the deepcopy approach.

CONSIDER: `PflowBatchNode` already deepcopies the node chain for parallel mode (`batch_node.py` line ~430). Look at how it handles the collector references — it probably excludes them. That pattern might be reusable for compile-once.

## Assumptions & Uncertainties

ASSUMPTION: Task 135 will be implemented on top of the `feat/shared-execution-pipeline` branch (or after it merges to main). The branch has NOT been merged yet.

ASSUMPTION: The user intends Task 135 as the natural continuation — they said "Task 138 (shared runner) then Task 135 (compile-once), two tasks ordered" in memory.

UNCLEAR: Whether the user wants Task 135 to remain exploratory (as the spec says "Explore Execution Core Redesign") or become a full implementation task. The spec's deliverable is a "design document" but the scope update adds concrete work (batch decomposition).

UNCLEAR: Whether the `_orch()` hack should be addressed in Task 135 or left for later. The spec lists it as a question to explore but the user might consider it lower priority than compile-once.

NEEDS VERIFICATION: The task-135 spec references `_validate_workflow()` in several places. This function was renamed to `_prepare_compilation()` in Task 138. The spec needs updating before implementation starts.

## Unexplored Territory

UNEXPLORED: **How `_fill_declared_defaults` + `_strip_placeholders` interact with compile-once.** The Runner fills placeholders before validation, then strips them before shared store seeding. For sub-workflows, this doesn't happen (they go through `compile_ir_to_flow` directly). If compile-once means the sub-workflow's `_prepare_compilation` runs only once, the `prepare_inputs()` call inside it (which resolves the REAL values) only runs once too. Per-item values would need to come from the shared store, not `initial_params`.

UNEXPLORED: **Whether `_prepare_compilation` should be split for Task 135.** The task-138 spec said "Task 135's `_prepare_compilation()` is what this task splits further into structural validation and input preparation." After Task 138, `_prepare_compilation` does: template mode detection, `prepare_inputs()` (5-tier resolution), output validation. The "structural" part (IR structure validation, data flow) stayed because those are compiler prerequisites. The split for Task 135 would be: structural stays in compiler, input preparation moves to... where? The Runner? A new pre-compilation step?

CONSIDER: **`compile_ir_to_flow` for sub-workflows creates a fresh `Registry()` each time.** `WorkflowExecutor._compile_sub_workflow` at line 149 does `registry=Registry()`. If you cache the compiled flow, you'd also cache the registry state at compile time. If a new MCP tool is registered between compilations, the cached flow wouldn't know about it. Probably fine (workflow structure doesn't change) but worth noting.

MIGHT MATTER: **The Runner creates `MCPConnectionPool()` unconditionally.** The pool starts a background daemon thread on first `call_tool()` — not on creation. But if compile-once means reusing flows across top-level executions (not just across batch items), pool lifecycle gets more complex. For batch-level compile-once (same pool, same execution), this is fine.

MIGHT MATTER: **`shared_store["_trace_collector"]` read-back at runner.py:207.** The Runner reads the trace collector back from shared_store after `flow.run()`: `trace_collector = shared_store.get("_trace_collector", trace_collector)`. This is because sub-workflows might replace it. If compile-once caches the flow, and the flow mutates `shared_store["_trace_collector"]`, the second execution would start with the first's trace collector. The Runner should always reset this before each execution.

## What I'd Tell the Task 135 Agent

1. **Start by measuring deepcopy cost.** Everything else is premature without knowing if the approach is viable. Measure for a 2-node and 5-node workflow with the full wrapper chain.

2. **Read `wrappers/CLAUDE.md` thoroughly.** It has the copy semantics details that determine whether compile-once is safe. The `TemplateAwareNodeWrapper` sharing via `copy.copy()` and the `PflowBatchNode` instance state are the two main hazards.

3. **The goal is NOT to align with PocketFlow.** The user's exact words: "Using PocketFlow as-is has no intrinsic value. Having good architecture and being able to compile once does." Don't spend time making pflow match PocketFlow's patterns if a simpler path exists.

4. **The `context.update(self.initial_params)` line at template_wrapper.py:455 is THE line to change.** If `initial_params` stops being the per-item data carrier, this override becomes unnecessary (or should be removed). The shared store becomes the single source of runtime data — which is the "clean" target state.

5. **Don't break the Runner contract.** The Runner always returns `ExecutionResult`. The Runner calls `WorkflowValidator.validate()` once. The Runner creates and cleans up MCP pools. Whatever Task 135 changes internally, these external contracts must hold.

6. **Update the task-135 spec before starting.** It references `_validate_workflow()` (renamed to `_prepare_compilation`), `WorkflowExecutorService` (deleted), and the old `initial_params` flow. Read this braindump and the task-138 review first, then update the spec.

## Relevant Files & References

**Must-read before starting:**
- `.taskmaster/tasks/task_138/task-review.md` — comprehensive review with patterns, anti-patterns, integration map
- `src/pflow/execution/runner.py` — the Runner (where compile_ir_to_flow is called)
- `src/pflow/runtime/wrappers/CLAUDE.md` — copy semantics, batch state, template wrapper sharing
- `src/pflow/pocketflow/PFLOW_MODIFICATIONS.md` — the `_orch()` hack

**Key code to trace:**
- `runtime/workflow_executor.py:176-200` — where sub-workflows recompile (the hot path)
- `runtime/wrappers/template_wrapper.py:442-464` — `_build_resolution_context()` (the override that blocks compile-once)
- `runtime/wrappers/batch_node.py:~220,~430` — instance state accumulation + parallel deepcopy pattern
- `runtime/compilation/compile_validation.py:130-180` — `_prepare_compilation()` (what Task 135 might split)

**Don't bother re-reading:**
- The braindumps in `task_138/starting-context/` — they describe the PRE-Task-138 state which is now wrong
- `scratchpads/architectural-debt/compounding-issues.md` — Issue 6 is resolved, Issue 5 (batch decomposition) is folded into Task 135

## For the Next Agent

The user operates with high standards. They push back on "defense-in-depth" reasoning that avoids the actual work. They want honest analysis: "Is this really needed, or is it fear of breaking things?" They approve measured risk-taking and value structural simplification over safe incrementalism. See `feedback_honesty_over_defensiveness.md` in memory.

Start by: reading this braindump, then the task-138 review, then `runner.py` and `wrappers/CLAUDE.md`. Measure deepcopy cost as your first concrete action. Everything else follows from whether that number is ~1-5ms (proceed with compile-once) or ~50ms+ (rethink approach).

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
