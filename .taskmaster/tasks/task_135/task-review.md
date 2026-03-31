# Task 135 Review: Execution Core Redesign — Orchestration Engine

## Metadata
- **Implementation Date**: 2026-03-30 to 2026-03-31
- **Branch**: `feat/execution-core-redesign`
- **Commits**: 7 (including 3 code review fix rounds)
- **Net diff (total)**: 209 files changed, +11,729 / -17,280 lines
- **Net diff (production .py only)**: 56 files changed, +2,456 / -3,606 lines
- **Net diff (tests only)**: 89 files changed, +6,388 / -9,614 lines
- **Net diff (markdown/docs)**: 64 files changed, +2,915 / -3,732 lines
- **Architecture delta**: Deleted ~4,200 lines (wrappers 3,924 + pocketflow 205 + dead compiler code) → Created ~2,100 lines (engine 2,021 + core/node.py 89) → Net ~2,100 lines of production code eliminated
- **Tests**: 4,679 → 4,630 (deleted wrapper-internal + pocketflow tests, added 19 regression/behavioral tests across 5 new files + 1 existing)
- **Subsumes**: Task 140 (Wrapper Chain Refactoring)
- **GitHub issues created**: #185 (exception placement), #188 (sub-workflow coercion), #189 (permissive batch errors)

## Executive Summary

Replaced pflow's 4-layer wrapper chain (3,924 lines) with a standalone orchestration engine (2,021 lines across 6 modules). Slimmed PocketFlow from 205 lines (10 classes) to 85 lines (3 classes), then moved node primitives to `src/pflow/core/node.py` and deleted the `pocketflow/` directory entirely. Sub-workflows now compile once per batch — both sequential and parallel — at O(1) vs O(N) at ~25ms per compilation. Shared store is the single source of runtime data — the `initial_params` dual-data-path that caused every downstream hack is eliminated.

### Measured Performance (parallel batch over 5-node file-based sub-workflow)

| Items | Compile-once | No cache (old O(N)) | Speedup |
|-------|-------------|---------------------|---------|
| 20    | 146ms (1 compile) | 716ms (21 compiles) | 4.9x |
| 50    | 425ms (1 compile) | 1,885ms (51 compiles) | 4.4x |
| 100   | 686ms (1 compile) | 4,635ms (101 compiles) | 6.8x |
| 500   | 3,696ms (1 compile) | 26,556ms (501 compiles) | 7.2x |

Compilation overhead is now constant regardless of batch size. At 500 items the old model spent ~12.5s on compilation alone; the new model spends 25ms.

## Implementation Overview

### What Was Built

The task went through three distinct phases of understanding before implementation:

**Phase 1 — Exploration**: Started as "compile-once optimization" and kept expanding. The exploring agent initially anchored on minimal fixes — patching `initial_params`, splitting `prepare_inputs()`, keeping the wrapper chain. The user pushed past each incremental proposal ("everything is on the table, even rewriting from scratch") until the root cause was identified: pflow conflated compiled structure with runtime state. Every hack (the `_orch()` modification, `initial_params` override, PflowBatchNode reimplementing BatchFlow, per-item recompilation) traced back to this conflation. The lesson: when every proposed fix requires working around the same structural constraint, the structure is the problem.

**Phase 2 — Architecture decision**: Five approaches were evaluated (A: fix data model only, B: slim PocketFlow + fix data model, B+: add batch decomposition, C: full execution engine rewrite, D: orchestration-level concerns replacing wrapper chain). The user rejected approaches that preserved the wrapper chain. The decisive insight came from recognizing that wrappers solve "add behavior to components you can't modify" — but pflow controls the framework, the compiler, the execution loop, and the nodes. Direct orchestration is the natural pattern when you control everything. Task 140 (Wrapper Chain Refactoring) was subsumed because both tasks target the same 3,920 lines — doing compile-once without wrapper refactoring would mean restructuring the same code twice.

**Phase 3 — Implementation**: An implementing agent executed the plan across 7 phases with 3 rounds of code review (8 + 7 + 3 + 7 agents = 25 review agent deployments). The plan review (8 agents, pre-implementation) caught 6 critical issues before any code was written — most importantly that `self._last_resolutions` on the engine would be a data race in parallel batch, and that the `structural_only` compilation mode was unnecessary (since `initial_params` no longer bakes into compiled nodes, compiling with first-item params is safe). Post-implementation, the pocketflow directory was removed and node primitives moved to `core/node.py`.

**Why the shim was created then removed**: The backward-compat shim (`_CompiledWorkflowShim` wrapping `compile_ir_to_flow`) existed as a transition bridge — it let ~400 tests pass during Phases 3-5 without updating them. Once Phase 6 rewrote/updated those tests, the shim was dead code testing a non-production code path. It was removed because tests should exercise the same code path as production. The two-liner (`compile_workflow` + `engine.run`) is honest about what it does.

**Why `CompilationError` was moved to `core/exceptions.py`**: Not in the original plan, but solved the right problem. `CompilationError` is a leaf-level type (pure exception, zero dependencies) that was defined in `compiler.py` (a heavy module). Every module that needed to catch or raise it had to import `compiler.py`, creating circular import chains. Moving it to `core/exceptions.py` (where all other pflow exceptions live) breaks cycles at the architectural level and enables clean module-level imports with real type annotations throughout the engine.

### Key Deviations from Plan

1. **Phase 5 (prepare_inputs split) eliminated** — Since `initial_params` no longer bakes into compiled nodes, compiling sub-workflows with first-item params is safe. `prepare_inputs()` runs once, captures defaults. No `structural_only` mode needed.

2. **`_source_line` keys NOT filtered from `split_params()`** — Plan said filter. Wrong: `python_code.py:300` reads `self.params.get("_code_source_line")` for error line numbers. Filtering silently breaks error locations.

3. **`CompilationError` moved to `core/exceptions.py`** — Not in plan. Broke a circular import chain (`compiler.py` → `engine/` → `batch_executor.py` → `compiler.py`). Enables module-level imports with real types.

4. **Batch nodes skip top-level template resolution** — Engine guards on `if config.template_config and not config.batch_config`. Without this, `${item}` fails before the batch loop starts.

5. **Backward-compat shim returned `.run()` method** — Plan's alias returned raw `CompiledWorkflow`. 28+ tests call `flow.run(shared)` on the result. Shim was later removed entirely — all tests migrated to `compile_workflow()` + `WorkflowEngine`.

## Files Modified/Created

### Core Changes (new architecture)

- `src/pflow/runtime/engine/engine.py` — WorkflowEngine (328 lines). Graph walker + per-node orchestration.
- `src/pflow/runtime/engine/types.py` — CompiledWorkflow, NodeConfig, TemplateConfig, BatchConfig (59 lines).
- `src/pflow/runtime/engine/template_resolution.py` — Standalone template resolution (413 lines). Extracted from TemplateAwareNodeWrapper.
- `src/pflow/runtime/engine/batch_executor.py` — Standalone batch execution (630 lines). Unified `_exec_single`/`_exec_single_with_node` (170 lines duplication → one function).
- `src/pflow/runtime/engine/instrumentation.py` — Cache, trace, metrics, progress, loop guards (502 lines). Extracted from InstrumentedNodeWrapper.
- `src/pflow/core/node.py` — BaseNode, _ConditionalTransition, Node (~90 lines). Moved from `pocketflow/__init__.py`.

### Core Changes (modified)

- `src/pflow/runtime/compilation/compiler.py` — `compile_workflow()` replaces `compile_ir_to_flow()`. `_create_node_and_config()` replaces `_create_single_node()`. No wrappers applied.
- `src/pflow/execution/runner.py` — Uses `compile_workflow()` + `WorkflowEngine` directly.
- `src/pflow/runtime/workflow_executor.py` — Compile-once cache (`_cached_workflow`). Uses `compile_workflow()` + `WorkflowEngine`.
- `src/pflow/runtime/compilation/compile_validation.py` — Returns 4-tuple with `resolved_defaults` and `env_param_names`.

### Deleted (net -5,551 lines production code)

- `src/pflow/runtime/wrappers/` — entire directory (9 files, 3,924 lines)
- `src/pflow/pocketflow/` — entire directory (28 files, including docs for removed Flow/BatchFlow/async classes)
- Dead compiler functions: `_apply_template_wrapping`, `_create_single_node`, `_instantiate_nodes`, `_apply_run_hooks`, `_apply_only_node_stop`

### Tests

- **Rewritten**: ~283 tests (wrapper-internal tests → engine/function tests)
- **Updated**: ~100 tests (import paths, mock targets, isinstance checks)
- **Added**: 18 new tests across 5 new files + 1 existing file:
  - `test_compile_once_regression.py` (5): compile-once verification, distinct output per item, file-based compile-once, resolved_defaults leak, storage_mode shared
  - `test_engine_behavior.py` (5): unmatched action warning, edge following, --only + outputs, custom error_action (2)
  - `test_initial_params_override_removal.py` (4): shared store as single data source (upstream output, defaults, user params, unit test)
  - `test_memo_cache_error_skip.py` (1): error results not served from cache
  - `test_node_stateless_invariant.py` (2): AST meta-test for exec/post self-assignments + allowlist validation
  - `test_trace_integration.py` (+1): template resolution error captured in trace with partial resolutions
- **Deleted**: ~68 tests (10 test_pocketflow/ files for removed classes + wrapper-internal tests not replaced)

## Integration Points & Dependencies

### Incoming Dependencies (what calls the engine)

| Caller | Interface |
|--------|-----------|
| `execution/runner.py` | `compile_workflow()` + `WorkflowEngine(metrics, trace, only_node).run(workflow, shared)` |
| `runtime/workflow_executor.py` | Same, with compile-once cache |

### Outgoing Dependencies

| Component | Via |
|-----------|-----|
| `core/node.py` | BaseNode/Node lifecycle (`_run`, `set_params`, `successors`) |
| `runtime/cache.py` | Memo cache (`_deterministic_json`, `compute_node_cache_key`) |
| `runtime/output_resolver.py` | `populate_declared_outputs()` for declared outputs |
| `core/exceptions.py` | `CompilationError`, `MaxNodeVisitsError` |

### Shared Store Keys (engine writes)

| Key | Written by | Lifecycle |
|-----|-----------|-----------|
| `__execution__` | `instrumentation.py` | Per-workflow, NOT propagated to children |
| `__cache_hits__` | `instrumentation.py` | Per-workflow, NOT propagated |
| `__warnings__` | `instrumentation.py`, `batch_executor.py`, `engine.py` | Cross-workflow (shared reference) |
| `__template_errors__` | `engine.py` | Per-workflow, NOT propagated |
| `shared[node_id]` | `namespaced_store.py`, `batch_executor.py`, `instrumentation.py` | Per-node namespace |
| `_batch_trace` | `batch_executor.py` | Transient (init → append → collect → delete) |

## Architectural Decisions & Tradeoffs

### 1. Orchestration engine over wrapper chain

**Decision**: All runtime concerns (template resolution, namespacing, caching, tracing, batch) are sequential function calls in the engine, not nested wrapper delegation.

**Reasoning**: Wrappers solve "add behavior to components you can't modify." pflow controls everything. The wrapper chain created 4 layers of indirection, cross-wrapper coupling via chain traversal, copy semantics gotchas, and 80% code duplication in batch paths.

**Trade-off**: Engine's `_execute_node` is a 190-line function with 17 steps. It's linear and readable, but long. The old wrappers distributed this across 4 files — harder to follow but each file was shorter.

### 2. `_execute_single_node` returns tuple, no instance state

**Decision**: `(action, last_resolutions, template_errors)` return tuple. No `self._last_resolutions`.

**Reasoning**: 5/8 review agents flagged instance state on the engine as a data race in parallel batch. Each thread writes `self._last_resolutions` simultaneously.

### 3. Compile with first-item params (no structural_only mode)

**Decision**: Sub-workflows compile normally with the first item's params. `prepare_inputs()` runs once, captures defaults. Subsequent items reuse the cached `CompiledWorkflow`.

**Reasoning**: Since `initial_params` no longer bakes into compiled nodes, the compiled graph IS structural by design. No special compilation mode needed. This eliminated an entire phase from the plan.

### 4. `CompiledWorkflow` is NOT concurrent-safe

**Decision**: `node.params = resolved_params` mutates the compiled node. One `engine.run()` at a time per workflow instance.

**Reasoning**: Making nodes truly immutable would require changing the `BaseNode` contract (all 28 nodes read `self.params` in `prep()`). Not worth it — the Runner creates fresh `WorkflowEngine` per call, and `WorkflowExecutor` compile-once is for sequential batch within one execution.

### Technical Debt Incurred

- **#185**: `CompilationError` canonical in `core/exceptions.py`, but 4 sibling modules still lazy-import via `compiler.CompilationError` re-export. Same pattern for `ValidationError` and `MarkdownParseError`.
- **#188**: Per-item type coercion lost for sub-workflow inputs. Old model ran `prepare_inputs()` per item, coercing `"7"` → `7`. New model skips per-item coercion.
- **#189**: Permissive template errors in parallel batch may be dropped if `__template_errors__` doesn't exist in parent store at thread start.

## Unexpected Discoveries

### Bugs Found During Implementation

1. **`NamespacedSharedStore` missing `update()`** — `storage_mode: shared` crashed. Added method routing through `__setitem__`.
2. **`resolved_defaults` leaking between batch items** — First item's coerced values persisted in cached defaults. Fix: only seed defaults for keys NOT already in `child_params`.
3. **Compile-once broken for file-based sub-workflows** — `prep()` re-parsed file each batch item → new dict → different `id()`. Fix: cache loaded IR in `prep()` for non-inline sources.
4. **Error action inconsistency** — 6 sites used `== "error"` while 4 used `startswith("error")`. Custom `error_action` values created contradictory state.
5. **Memo cache hits didn't populate `__cache_hits__`** — CLI "↻" indicator was silently broken.

### Key Gotchas for Future Agents

- **`_partial_resolutions` on exceptions**: `resolve_templates` attaches partial resolution data to `ValueError` as `._partial_resolutions`. Non-standard Python. The engine's except handler reads it via `getattr(e, "_partial_resolutions", None)`.
- **Step numbering in `_execute_node`**: Step 5 (config hash) runs BEFORE step 4 (template resolution) because hash doesn't need resolved params but template resolution must be inside try.
- **`node.node_id` is dynamic**: `BaseNode` doesn't define it. The compiler sets it after instantiation. If missing, engine raises a clear error.
- **Batch callback contract**: `_execute_single_node` returns `(action, last_resolutions, template_errors)`. Changing this breaks batch.

## Patterns Established

### The compile + engine two-step pattern

```python
workflow = compile_workflow(ir, registry=registry, initial_params=params)
shared = {}
shared.update(user_params)
shared.update(workflow.resolved_defaults)
engine = WorkflowEngine(metrics_collector=mc, trace_collector=tc, only_node=on)
result = engine.run(workflow, shared)
```

This is the production path. Tests should use the same pattern (via `tests/shared/engine_utils.py:compile_and_run`).

### Standalone functions over wrappers

Every runtime concern is a standalone function that receives its data as parameters:
```python
# Good: data in, result out
merged, resolutions, errors = resolve_templates(config, shared, node_id)

# Bad (old pattern): instance state, chain traversal
wrapper.resolve_templates(shared)  # reads self.initial_params, self._expected_types, self.template_resolution_mode...
```

### Anti-Patterns

- **Instance state on the engine** — Use return values. Instance state on a shared object creates races in parallel batch.
- **Restoring node.params after execution** — Unnecessary. Each execution sets params fresh.
- **`initial_params` as runtime data carrier** — This was the root cause of every hack. All runtime data flows through the shared store.

## Lessons Learned

### 1. When every fix requires working around the same constraint, the constraint is the problem

The exploring agent proposed five incremental approaches before reaching the right answer. Each approach worked around `initial_params` being baked into compiled nodes — patching the override, splitting validation, adding caching layers. The user's push to "think about the best architecture, not the least disruptive one" was the turning point. The root cause was a single design decision (putting runtime data in a compile-time artifact), and every hack in the system was a downstream consequence.

### 2. Adapting tests to accept less is a red flag

The implementing agent twice adapted tests to accept regressions rather than questioning the implementation: (a) memo cache hits not populating `__cache_hits__` (CLI "cached" indicator silently broken), (b) template resolution errors producing empty trace events. Both were caught by code review and fixed. The pattern: when a rewritten test needs to assert LESS than the original, that's a signal the new implementation dropped behavior, not that the old test was over-specified.

### 3. Plan reviews catch different bugs than code reviews

The pre-implementation plan review (8 agents) found the `self._last_resolutions` race condition, the unnecessary `structural_only` mode, and the shim type mismatch — none of which would have been caught by code review because the code didn't exist yet. The three post-implementation code reviews found the `NamespacedSharedStore.update()` crash, the `resolved_defaults` leak between batch items, and the compile-once miss for file-loaded IR — issues that only surface when code meets real data flows. Both types of review are necessary for changes of this scope.

### 4. `_source_line` filtering: verify assumptions against code, not docs

The plan said "filter `_source_line` keys from both template and static param buckets." The implementing agent found `python_code.py:300` reads `self.params.get("_code_source_line", 0)` for error line reporting. Filtering would silently break error locations in Python code nodes. The plan was written from architectural reasoning ("these are metadata, not real params"); the code disagreed. The fix: `_source_line` keys stay in `static_params`, filtered only in `compute_node_config()` for cache hashing — same as the old code.

### 5. The shim was necessary for transition but dangerous to keep

The backward-compat shim let ~400 tests pass during the phased migration (Phases 3-5) without updating them. This was valuable — it prevented a "big bang" of test failures while production code was being restructured. But once the migration was complete, the shim had its own param-seeding logic that differed subtly from the Runner's production path. Tests passing through the shim were testing a code path no user would ever hit. Removing the shim and migrating all tests to the production path was the right final step.

## Breaking Changes

- `compile_ir_to_flow()` and `_CompiledWorkflowShim` — deleted. All callers use `compile_workflow()` + `WorkflowEngine`.
- `Flow`, `BatchFlow`, `BatchNode`, all async variants — deleted from PocketFlow.
- `src/pflow/pocketflow/` — entire directory deleted. Imports: `from pflow.core.node import BaseNode, Node`.
- `src/pflow/runtime/wrappers/` — entire directory deleted. Standalone utilities moved to `runtime/engine/`.
- `TemplateAwareNodeWrapper`, `NamespacedNodeWrapper`, `InstrumentedNodeWrapper`, `PflowBatchNode` — deleted.

## AI Agent Guidance

### Quick Start for Related Tasks

1. Read `src/pflow/runtime/engine/CLAUDE.md` — the engine architecture with try/except boundary diagram
2. Read `src/pflow/runtime/compilation/CLAUDE.md` — `_create_node_and_config` ordering (load-bearing)
3. The production path is: `compile_workflow()` → seed shared store → `WorkflowEngine.run()`
4. For node changes: nodes read `self.params` in `prep()`, write to `shared` in `post()`. Engine handles everything else.

### Common Pitfalls

1. **Don't add instance state to `WorkflowEngine`** — parallel batch will race on it
2. **Don't skip `resolved_defaults` seeding** — defaults won't resolve in templates
3. **Don't move template resolution outside the try block** — error traces lose partial resolution data
4. **Don't change `_execute_single_node` return type** — batch executor depends on the tuple contract
5. **Don't add `self.X = result` in node `exec()`/`post()`** — compile-once reuses nodes across sequential batch items. The AST meta-test in `test_node_stateless_invariant.py` will catch this.

### Test-First Recommendations

When modifying the engine:
- Run `tests/test_runtime/test_engine_behavior.py` — engine-level behavioral tests
- Run `tests/test_runtime/test_compile_once_regression.py` — compile-once verification
- Run `tests/test_runtime/test_initial_params_override_removal.py` — shared store single source
- Run `tests/test_runtime/test_trace_integration.py` — trace capture across all features
- Run `tests/test_integration/` — end-to-end through the full pipeline

---

*Generated from implementation context of Task 135 — Execution Core Redesign*
