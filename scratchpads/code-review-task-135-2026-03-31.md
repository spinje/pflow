# Code Review — Task 135

Review target: current branch vs `origin/main`

Context used:
- `task-135.md`
- `implementation/progress-log.md`
- targeted review of the changed runtime/compiler/test files

## Critical — must fix before merge

### 1. Compile-once caching still bakes per-run child inputs into the cached sub-workflow

**Files:** `src/pflow/runtime/workflow_executor.py`, `src/pflow/runtime/compilation/compiler.py`, `src/pflow/runtime/compilation/compile_validation.py`, `src/pflow/runtime/compilation/ir_preparation.py`

`WorkflowExecutor._compile_sub_workflow()` calls `compile_workflow(..., initial_params=dict(child_params))` and then caches the returned `CompiledWorkflow` only by `id(workflow_ir)`. But `compile_workflow()` is not structural-only here: `_prepare_compilation()` runs `prepare_inputs()`, and `CompiledWorkflow.resolved_defaults` ends up containing per-execution prepared inputs such as coerced provided values and defaults.

That means a static inline child workflow in sequential batch can reuse the first item's prepared child inputs on later items. Missing values can inherit the first item's value/default path, and the cached object is no longer the "pure structure" the task description requires.

**Recommended fix:** keep the cached object structural-only. Compile the child workflow without current `child_params`, then run child input preparation separately for each execution.

### 2. Nested workflow input coercion is undone immediately before execution

**Files:** `src/pflow/runtime/workflow_executor.py`

`exec()` seeds child storage with:

1. `compiled.resolved_defaults`
2. `child_params`

in that order. But `resolved_defaults` is exactly where compile-time input coercion lands for provided child inputs. So a child input declared as `int` can be coerced to `7` during compilation and then be overwritten back to raw `"7"` at runtime.

This breaks the compile/runtime contract for nested workflows and can reintroduce type failures that top-level execution no longer has.

**Recommended fix:** do not overwrite prepared/coerced child inputs with raw params. The runtime seeding path needs one source of truth for prepared child inputs.

### 3. `storage_mode: shared` is broken on the normal namespaced execution path

**Files:** `src/pflow/runtime/workflow_executor.py`, `src/pflow/runtime/engine/engine.py`, `src/pflow/runtime/engine/namespaced_store.py`

Workflow nodes execute through `NamespacedSharedStore` when namespacing is enabled. In shared mode, `_create_child_storage()` returns that proxy unchanged. `exec()` then does:

- `child_storage.update(compiled.resolved_defaults)`
- `child_storage.update(child_params)`

But `NamespacedSharedStore` does not implement `update()`. So the default namespaced `storage_mode: shared` path raises before the child workflow even runs.

**Recommended fix:** stop assuming the shared-mode store is a raw `dict`. Either unwrap to the parent dict first or seed keys through explicit assignment that works with the proxy.

## Warnings — should be addressed

### 1. Compile-once currently does not apply to file-based or saved-name sub-workflows

**Files:** `src/pflow/runtime/workflow_executor.py`, `tests/test_runtime/test_compile_once_regression.py`, `tests/test_runtime/test_workflow_executor/test_workflow_name.py`

The cache key is `id(workflow_ir)`. That works for static inline `workflow_ir`, but file- and saved-name paths load a fresh IR object on each `prep()`, so the cache never hits. This misses Task 135's compile-once goal for the common `workflow: ./child.pflow.md` and saved-workflow cases.

The new regression coverage only proves the inline-static case.

### 2. Permissive template errors inside batch items are dropped instead of surfacing on the parent workflow

**Files:** `src/pflow/runtime/engine/engine.py`, `src/pflow/runtime/engine/batch_executor.py`

`_execute_single_node()` writes permissive-mode template errors into each item's `item_shared["__template_errors__"]`, but `execute_batch()` never merges those errors back into the parent `shared` store.

That creates a silent degraded-success path: a batch item can keep going with unresolved/defaulted output, yet the parent run has no `__template_errors__` signal.

### 3. Error actions are handled inconsistently unless they are exactly `"error"`

**Files:** `src/pflow/runtime/engine/engine.py`, `src/pflow/runtime/engine/instrumentation.py`, `src/pflow/execution/executor_service.py`, `src/pflow/runtime/workflow_executor.py`

Workflow-level failure detection uses `startswith("error")`, but execution-state, trace, progress, and cache bookkeeping use `action == "error"`.

A custom `error_action` like `error_child` will still fail the workflow, but the node can be recorded as completed, `failed_node` can stay unset, and progress/trace can mark it as non-error.

### 4. Invalid numeric batch config is silently coerced to zero

**Files:** `src/pflow/runtime/compilation/compiler.py`

`_coerce_int()` and `_coerce_float()` return `0` / `0.0` on bad input. That turns configuration mistakes into confusing runtime behavior instead of compile-time validation.

Examples:
- invalid `max_concurrent` becomes `0`
- invalid `max_retries` becomes `0`
- invalid `retry_wait` becomes `0.0`

### 5. The new tests miss the highest-risk runtime regressions

**Files:** `tests/test_runtime/test_compile_once_regression.py`, `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py`, `tests/test_runtime/test_workflow_executor/test_integration.py`

The added/updated coverage does not currently exercise:

- static compile-once with a child that actually consumes per-item child inputs
- full engine execution of `storage_mode="shared"`
- compile-once for file-based or saved-name sub-workflows
- custom `error_action` values other than `"error"`
- batch permissive-template-error propagation

## Suggestions — optional improvements

### 1. Update or remove the stale GitHub PR example

**Files:** `examples/github/create_pr_example.py`, `src/pflow/pocketflow/__init__.py`

The example still imports `Flow` from `pflow.pocketflow`, but this branch removes that API. It is now a broken consumer of the runtime redesign.

### 2. Make the structural-only cache invariant explicit

Add a short comment or assertion near `CompiledWorkflow` / `WorkflowExecutor` documenting that cached compiled workflows must not contain per-execution prepared inputs or mutable execution state.

## Areas Verified Clean

- The `NamespacedSharedStore` proxy itself looks internally consistent; the shared-mode failure comes from treating it like a raw dict.
- The standard `"default"` / `"error"` traversal path in `WorkflowEngine.run()` looks coherent for declared-output population and stop-on-missing-successor behavior.

## Agent Handoff

This section is intended as the shortest path for another agent to pick up the review without redoing all of the investigation.

### Confirmed 1: compile-once cache is not structural-only

- **Where:** `WorkflowExecutor._compile_sub_workflow()` in `src/pflow/runtime/workflow_executor.py`; `compile_workflow()` in `src/pflow/runtime/compilation/compiler.py`; `_prepare_compilation()` in `src/pflow/runtime/compilation/compile_validation.py`; `prepare_inputs()` in `src/pflow/runtime/compilation/ir_preparation.py`
- **Key symbols:** `_compile_sub_workflow`, `compile_workflow`, `_prepare_compilation`, `prepare_inputs`, `CompiledWorkflow.resolved_defaults`
- **Mechanism:** `_compile_sub_workflow()` caches a `CompiledWorkflow` by `id(workflow_ir)` but compiles it with `initial_params=dict(child_params)`. The compiler then runs input preparation and stores prepared values in `resolved_defaults`, so the cached object contains per-execution child input state, not just structure.
- **Minimal repro:** sequential batch over a static inline `workflow_ir`; first item passes child input `limit="7"`; second item omits `limit`; if the cache is reused, the second child execution can inherit the first item’s prepared value/default path.
- **Why I’m confident:** this follows directly from the call chain and data flow, not from a guessed interaction. `compile_workflow()` clearly consumes `initial_params`, and `prepare_inputs()` clearly writes prepared values into defaults.
- **What to test:** add a regression test where a static cached child workflow actually consumes child inputs. The new `tests/test_runtime/test_compile_once_regression.py` currently proves compile count, but not stale prepared-input reuse.

### Confirmed 2: nested input coercion is overwritten with raw child params

- **Where:** `WorkflowExecutor.exec()` in `src/pflow/runtime/workflow_executor.py`
- **Key symbols:** `exec`, `child_storage.update(compiled.resolved_defaults)`, `child_storage.update(child_params)`
- **Mechanism:** compile-time prepared inputs are seeded first, then raw child params are written over them. For nested workflows, this can undo type coercion and any other prepared-input normalization.
- **Minimal repro:** child workflow declares input `limit: int`; parent passes `limit: "7"`; compilation prepares `7`, but execution writes `"7"` back into child storage before child nodes run.
- **Why I’m confident:** the overwrite happens in a single obvious block in `exec()`, and `prepare_inputs()` explicitly coerces provided values.
- **What to test:** add a nested-workflow regression where the child input type is declared and the child node fails unless the coerced value survives into runtime.

### Confirmed 3: `storage_mode: shared` breaks under namespaced execution

- **Where:** `WorkflowExecutor._create_child_storage()` and `WorkflowExecutor.exec()` in `src/pflow/runtime/workflow_executor.py`; `NamespacedSharedStore` in `src/pflow/runtime/engine/namespaced_store.py`; workflow-node execution path in `src/pflow/runtime/engine/engine.py`
- **Key symbols:** `_create_child_storage`, `exec`, `NamespacedSharedStore`, `_execute_single_node`
- **Mechanism:** in shared mode, `_create_child_storage()` returns the parent store object as-is. Under the normal engine path, that object is a `NamespacedSharedStore`, not a raw `dict`. `exec()` then calls `update()` on it, but the proxy does not implement `update()`.
- **Minimal repro:** run a workflow node with `storage_mode: shared` and default namespacing enabled. The child setup fails before the sub-workflow executes.
- **Why I’m confident:** this is a direct API mismatch between the returned proxy type and the `update()` calls.
- **What to test:** add a full engine-level test for shared-mode nested workflow execution, not just `_create_child_storage()` identity checks.

### Confirmed 4: file-based and saved-name sub-workflows bypass compile-once

- **Where:** `WorkflowExecutor._load_workflow()` and `_compile_sub_workflow()` in `src/pflow/runtime/workflow_executor.py`
- **Key symbols:** `_load_workflow`, `_load_workflow_file`, `WorkflowManager.load_ir`, `_compile_sub_workflow`
- **Mechanism:** the cache key is `id(workflow_ir)`. Inline static child IR can reuse the same object reference, but file and saved-name loading produce a fresh IR object on each call, so the cache does not hit.
- **Minimal repro:** sequential batch over `workflow: ./child.pflow.md` or a saved workflow name; instrument `compile_workflow`; observe one compile per item instead of one compile for the batch.
- **Why I’m confident:** this follows directly from the object-identity cache key and the fact that file/name loading reparses or reloads IR each time.
- **What to test:** add file-based and saved-name compile-once regressions alongside the existing inline-static test.

### Confirmed 5: batch permissive template errors are lost at the parent level

- **Where:** `WorkflowEngine._execute_single_node()` / `_execute_node()` in `src/pflow/runtime/engine/engine.py`; `execute_batch()` and `_execute_batch_item()` in `src/pflow/runtime/engine/batch_executor.py`
- **Key symbols:** `_execute_single_node`, `execute_batch`, `_execute_batch_item`, `__template_errors__`
- **Mechanism:** permissive-mode template errors are written into each item’s isolated `item_shared`, but batch aggregation never merges those errors back into the parent `shared` store.
- **Minimal repro:** permissive template resolution inside a batch item that leaves unresolved/defaulted output but does not hard-fail the node. After the run, item-local `__template_errors__` existed, but parent `shared["__template_errors__"]` does not.
- **Why I’m confident:** the write site exists in engine code, and there is no corresponding merge in batch aggregation.
- **What to test:** a batch regression in permissive mode asserting that parent-level `__template_errors__` reflects item-level template failures.

### Confirmed 6: `error*` actions are treated inconsistently across the runtime

- **Where:** `WorkflowEngine.run()` and `_execute_node()` in `src/pflow/runtime/engine/engine.py`; `cache_result()` and `call_completion_callback()` in `src/pflow/runtime/engine/instrumentation.py`; `build_error_list()` path in `src/pflow/execution/executor_service.py`; `WorkflowExecutor.post()` / `exec()` in `src/pflow/runtime/workflow_executor.py`
- **Key symbols:** `startswith("error")`, `action == "error"`, `cache_result`, `call_completion_callback`
- **Mechanism:** workflow-level failure detection uses `startswith("error")`, but execution bookkeeping, callbacks, and trace success flags often use exact equality with `"error"`.
- **Minimal repro:** return or configure `error_child` instead of `error`. The workflow is treated as failed at the top level, but per-node bookkeeping can still record completion or omit `failed_node`.
- **Why I’m confident:** the differing predicates are explicit in the code and were easy to verify.
- **What to test:** add runtime coverage for a custom `error_action` such as `error_child`, checking workflow result, `failed_node`, progress callback error flag, and trace success value.

### Confirmed 7: invalid numeric batch config is silently normalized to zero

- **Where:** `_coerce_int()` and `_coerce_float()` in `src/pflow/runtime/compilation/compiler.py`
- **Key symbols:** `_coerce_int`, `_coerce_float`
- **Mechanism:** bad numeric config values are coerced to `0` / `0.0` instead of failing validation.
- **Minimal repro:** pass non-numeric strings for `max_concurrent`, `max_retries`, or `retry_wait`; compilation succeeds; runtime fails later or behaves nonsensically.
- **Why I’m confident:** the helper functions explicitly catch conversion errors and return zero.
- **What to test:** add compiler-level validation tests asserting these configs fail fast instead of becoming zero.

### Confirmed 8: current tests do not cover the highest-risk regressions

- **Where:** `tests/test_runtime/test_compile_once_regression.py`, `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py`, `tests/test_runtime/test_workflow_executor/test_integration.py`, `tests/test_runtime/test_workflow_executor/test_workflow_name.py`
- **Key gaps:** static compile-once with real child inputs; shared-mode execution through the full engine path; compile-once for file/name child workflows; custom `error*` actions; parent surfacing of batch permissive template errors.
- **Why I’m confident:** I checked the added/updated tests directly and compared them to the reviewed runtime paths.

### Confirmed 9: example still depends on removed `Flow` API

- **Where:** `examples/github/create_pr_example.py`; removed API in `src/pflow/pocketflow/__init__.py`
- **Key symbols:** `from pflow.pocketflow import Flow`, `Flow(name=...)`
- **Minimal repro:** run or import the example on this branch.
- **Why I’m confident:** the example still imports `Flow`, while the PocketFlow module on this branch no longer exports it.
- **What to test:** at minimum, update or remove the example; if examples are validated anywhere, add coverage there.

## Deferred Findings Needing More Verification

These were raised by subagents and remain plausible, but I did not elevate them in the main review because I was not yet sure enough.

### Deferred A: cached child workflows may reuse mutable node instance state

- **Raised by:** `review-concurrency-safety`
- **Where:** cached `CompiledWorkflow` reuse in `src/pflow/runtime/workflow_executor.py`; mutable node instances in `src/pflow/pocketflow/__init__.py`
- **Why plausible:** the cached compiled child workflow reuses the same node instances, and nodes mutate instance state such as `params`; some nodes also keep other instance attributes.
- **Why I did not promote it:** I did not independently produce a concrete failing runtime example strong enough to present it as confirmed. The risk is real enough that a future reviewer should check it directly.
- **How to verify:** build a child workflow around a node with observable instance state across runs and confirm whether state leaks between sequential child executions.

### Deferred B: direct `WorkflowEngine(trace_collector=...)` consumers may miss sub-workflow traces

- **Raised by:** `review-impact-completeness`
- **Where:** `WorkflowExecutor.exec()` checks `parent_shared.get("_trace_collector")` before creating a child collector; `WorkflowEngine` also accepts `trace_collector` directly
- **Why plausible:** there may be a contract mismatch between constructor-based trace injection and shared-store-based trace propagation.
- **Why I did not promote it:** I did not verify enough real call sites to state this as a confirmed regression.
- **How to verify:** construct a direct `WorkflowEngine(trace_collector=...)` call with a nested workflow and check whether `sub_workflow_events` are emitted without also seeding `shared["_trace_collector"]`.

## Subagent Inventory

This section records every concrete subagent finding I received, and how I handled it in this review.

### Included as written or near-equivalent

- Batch permissive template errors are dropped instead of surfacing on the parent workflow.
  Source: `review-silent-failures`
  Disposition: included as `Warnings / 2`.

- Error actions are handled inconsistently unless they are exactly `"error"`.
  Source: `review-silent-failures`
  Disposition: included as `Warnings / 3`.

- Invalid numeric batch config is silently coerced to zero.
  Source: `review-silent-failures`
  Disposition: included as `Warnings / 4`.

- Compile-once caching still bakes per-run child inputs into the cached sub-workflow.
  Source: `review-validation-consistency`
  Disposition: included as `Critical / 1`.

- Nested workflow input coercion is undone immediately before execution.
  Source: `review-validation-consistency`
  Disposition: included as `Critical / 2`.

- Compile-once currently does not apply to file-based or saved-name sub-workflows.
  Source: `review-impact-completeness`, `review-feature-interactions`
  Disposition: included as `Warnings / 1`.

- `storage_mode: shared` is broken on the normal namespaced execution path.
  Source: `review-feature-interactions`
  Disposition: included as `Critical / 3`.

- The GitHub PR example still imports removed `Flow` API.
  Source: `review-impact-completeness`
  Disposition: included as `Suggestions / 1`.

### Merged into broader findings

- Nested workflow input coercion is being undone.
  Source: `review-impact-completeness`
  Disposition: duplicate of `Critical / 2`.

- In shared mode with a plain dict parent store, seeding child defaults can overwrite parent values.
  Source: `review-feature-interactions`
  Disposition: merged into `Critical / 3` because it is the same shared-mode seeding/design problem, just the non-namespaced variant.

- The new tests miss the stale-data failure mode in compile-once coverage.
  Source: `review-test-fidelity`
  Disposition: merged into `Warnings / 5`.

### Not included as standalone findings because I did not verify them strongly enough

- Cached `CompiledWorkflow` reuses live node instances, so mutable node instance state may leak across child executions.
  Source: `review-concurrency-safety`
  Disposition: not promoted in the main review. I agree this is a plausible risk, but I did not independently prove a concrete failing path strong enough to present it as a confirmed issue.

- Direct `WorkflowEngine(trace_collector=...)` consumers may miss nested sub-workflow traces unless `_trace_collector` is also seeded into `shared`.
  Source: `review-impact-completeness`
  Disposition: not promoted in the main review. I did not independently verify enough surrounding call paths to state it as a confirmed regression.

### Not included as standalone findings because they were lower-priority test-quality concerns

- `tests/test_runtime/test_initial_params_override_removal.py` does not reproduce the exact same-key collision shape it claims to lock down.
  Source: `review-test-fidelity`
  Disposition: not called out separately. I agree it is a real test-quality concern, but it was weaker than the more direct missing-coverage issues already listed in `Warnings / 5`.

- Some nested-workflow integration assertions are weak (`len(execution_order) > 0`, depth assertions using `>=`).
  Source: `review-test-fidelity`
  Disposition: not called out separately. I treated this as lower-priority test-strength cleanup rather than a main review finding.

### No findings returned

- `review-agent-ux` returned no concrete findings.
