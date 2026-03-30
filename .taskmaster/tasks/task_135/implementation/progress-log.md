# Task 135: Execution Core Redesign — Progress Log

## Implementation Phases

1. **Phase 1**: New types + extracted functions (additive only — no existing code changes)
   - 1A: Create `engine/types.py` (CompiledWorkflow, NodeConfig, TemplateConfig, BatchConfig)
   - 1B: Create `engine/template_resolution.py` (extract from template_wrapper.py)
   - 1C: Create `engine/batch_executor.py` (extract from batch_node.py)
   - 1D: Create `engine/instrumentation.py` (extract from instrumented_wrapper.py)
   - 1E: Create `engine/__init__.py`
   - 1F: Move standalone utilities from wrappers/ to engine/
   - **Checkpoint**: `make test` passes
2. **Phase 2**: The Execution Engine (`engine/engine.py`)
   - **Checkpoint**: Unit tests for engine + existing tests pass
3. **Phase 3**: Compiler changes (compile_workflow + shim)
   - **Checkpoint**: `make test` — all tests pass via shim alias
4. **Phase 4**: Runner + WorkflowExecutor updates (compile-once)
   - **Checkpoint**: `make test` — engine used directly
5. **Phase 5**: PocketFlow slim + wrapper removal
6. **Phase 6**: Test updates (~283 tests)
   - **Checkpoint**: `make test && make check`
7. **Phase 7**: Documentation updates

---

## Pre-Implementation Context Gathering

**Date**: 2026-03-30

### Codebase state understood
- Read all 9 wrapper files (3,924 lines total)
- Read compiler.py (788 lines), pocketflow/__init__.py (205 lines)
- Read runner.py (615 lines), workflow_executor.py (447 lines), output_resolver.py (154 lines)
- Read template_resolver.py, template_errors.py, error_context.py, api_warning_detector.py
- All CLAUDE.md docs for runtime/, wrappers/, compilation/

### Key observations before starting
1. **Wrapper chain order**: template → namespace → batch → instrumented (outermost)
2. **`_build_resolution_context` in template_wrapper.py line 454**: `context.update(self.initial_params)` — this is THE hack we're eliminating
3. **PocketFlow `_orch()` hack at line 104**: `if params is not None: curr.set_params(p)` — goes away with Flow removal
4. **`copy.copy()` in `_orch()` line 99 and 107**: shallow copies during traversal — eliminated by engine
5. **InstrumentedNodeWrapper chain traversal**: 6 methods walk the wrapper chain by attribute name — all unnecessary when engine has direct data access
6. **`resolve_templates()` called twice on cache miss**: once for memo key, once for execution — plan eliminates this
7. **`_exec_single` vs `_exec_single_with_node`**: 170 lines of 80% duplication — plan merges into one path

### User directives
- "Defense-in-depth is not a blanket excuse. When the plan says strip, strip."
- Follow plan precisely; present specific evidence if deviating, not generic safety arguments

---

## Phase 1 — COMPLETE

**Date**: 2026-03-30
**Result**: All 4679 tests pass, zero existing code changed

### Files created
- `src/pflow/runtime/engine/__init__.py` — package init, exports type classes
- `src/pflow/runtime/engine/types.py` — CompiledWorkflow, NodeConfig, TemplateConfig, BatchConfig dataclasses
- `src/pflow/runtime/engine/template_resolution.py` — standalone template resolution functions
- `src/pflow/runtime/engine/batch_executor.py` — standalone batch execution functions
- `src/pflow/runtime/engine/instrumentation.py` — standalone instrumentation functions
- `src/pflow/runtime/engine/namespaced_store.py` — copied from wrappers/ (unchanged)
- `src/pflow/runtime/engine/api_warning_detector.py` — copied from wrappers/ (unchanged)
- `src/pflow/runtime/engine/template_errors.py` — copied from wrappers/ (unchanged)
- `src/pflow/runtime/engine/error_context.py` — copied from wrappers/ (unchanged)

### Key decisions
1. **`_source_line` filtering in `split_params()`**: Plan says "Filter _source_line keys from BOTH buckets." Implemented exactly — `split_params()` skips keys ending in `_source_line`. This is a change from the old `set_params()` which included them in static_params (they were later filtered in `_compute_node_config`). Now they never enter either bucket.

2. **`validate_resolved_type()` returns `Optional[str]`**: Eliminates the `__PERMISSIVE_TYPE_ERROR__` prefix protocol. Caller decides whether to raise or store based on mode. Cleaner API.

3. **`resolve_templates()` context building**: `context = dict(shared)` only — NO `initial_params` override. This is the core design change. Verified the old code at line 454-455 had `context.update(self.initial_params)`.

4. **Unified `_execute_batch_item()`**: Merged `_exec_single` (lines 477-565) and `_exec_single_with_node` (lines 567-648) into one function with an optional `item_shared` parameter. Parallel path passes pre-created `item_shared`, sequential path lets the function create it.

5. **Relative imports for copied files**: `template_errors.py` and `error_context.py` use `..template_resolver` which is correct from `engine/` (goes up to `runtime/`). No import changes needed.

6. **`handle_api_warning()` signature**: Plan's signature didn't include `node_type_name` and `node_params` needed for `record_trace()`. Added them — necessary for the trace call inside the function.

7. **`handle_cached_execution()` signature**: Plan had this as an engine method. Implemented as standalone function with explicit parameters (node_type_name, node_params, trace_collector) instead of engine instance state.

### No deviations from plan
All Phase 1 items implemented as specified. Files are additive — zero changes to existing code.

---

## Phase 2 — COMPLETE

**Date**: 2026-03-30
**Result**: Engine created, all 4679 tests still pass (additive)

### Files created
- `src/pflow/runtime/engine/engine.py` — WorkflowEngine class (~200 lines)

### Key decisions
- Engine is stateless per-node: `_execute_single_node` returns `(action, last_resolutions, template_errors)` tuple, no instance state stored. Safe for parallel batch.
- Template resolution skipped for batch nodes at the top `_execute_node` level — batch executor handles per-item resolution via `_execute_single_node` callback.

---

## Phase 3 — COMPLETE

**Date**: 2026-03-30
**Result**: 4655/4679 tests pass. 24 failures are all tests inspecting wrapper chain internals (Phase 6 rewrites).

### Files modified
- `src/pflow/runtime/compilation/compiler.py` — added `compile_workflow()`, `_create_node_and_config()`, `_instantiate_nodes_for_workflow()`, `_CompiledWorkflowShim`, `compile_ir_to_flow()` now delegates to shim
- `src/pflow/runtime/compilation/compile_validation.py` — `_prepare_compilation` returns 4-tuple: `(params, warnings, resolved_defaults, env_param_names)`
- `src/pflow/runtime/compilation/__init__.py` — exports `compile_workflow`
- `src/pflow/runtime/__init__.py` — exports `compile_workflow`, `CompiledWorkflow`, `WorkflowEngine`

### Key decisions and deviations

1. **Shim seeds `initial_params` into shared store**: The plan's shim only seeded `resolved_defaults`. But tests calling `compile_ir_to_flow` directly relied on `initial_params` being available via the old wrapper's `_build_resolution_context` override. The shim now receives `initial_params` and seeds them (minus `__` system keys) into shared store before engine execution. This preserves backward compat without the `initial_params` override in template resolution.

2. **`_prepare_compilation` returns 4-tuple instead of modifying return type**: Plan said to modify return to `(params, defaults, env_names)`. I chose `(params, warnings, defaults, env_names)` to maintain compatibility with the existing `_prepare_compilation` contract (warnings were already returned, just always `[]`).

3. **Batch template resolution skip**: Engine's `_execute_node` skips template resolution for batch nodes (`if config.template_config and not config.batch_config`). Without this, `${item.prompt}` would fail because `item` doesn't exist before the batch loop starts. The batch executor's `_execute_single_node` handles per-item resolution.

4. **`_source_line` keys NOT filtered in `split_params`**: The plan said "Filter _source_line keys from BOTH buckets." This was wrong — `python_code.py:300` reads `self.params.get("_code_source_line", 0)` for error location reporting. Filtering would silently break error line numbers in python code nodes. `_source_line` keys go into `static_params` (same as old code), and `compute_node_config()` in `instrumentation.py` filters them for cache hashing. **Deviation from plan with evidence**: the plan's instruction would break a real feature.

5. **Batch config coercion**: Plan's `_create_node_and_config` needs type coercion for batch config values (parallel, max_concurrent, etc.). Added simple `_coerce_bool`, `_coerce_int`, `_coerce_float` helper functions. Less robust than PflowBatchNode's versions (no logging), but sufficient since the batch config comes from parsed markdown/IR.

6. **`CompilationError` moved to `core/exceptions.py`**: The plan didn't call for this, but it was the right fix. `CompilationError` was defined in `compiler.py` (heavy module), forcing 16 import sites to use lazy imports. Moving it to `core/exceptions.py` (where all other pflow exceptions live) breaks the circular import chain `compiler.py` → `engine/types.py` → `engine/__init__.py` → `engine.py` → `batch_executor.py` → `compiler.py` and allows clean module-level imports everywhere. Now `compiler.py` imports engine types at module level with real type annotations — no `noqa`, no `Any` erasure, no `TYPE_CHECKING` hacks. Created #185 for the remaining misplaced exceptions (`ValidationError` in `ir_schema.py`, `MarkdownParseError` in `markdown_parser.py`).

### Bugs found and fixed
- **`write_memo_cache` hardcoded `"default"` action**: The extracted function always passed `"default"` as the action to `memo_cache.put()`. The old `InstrumentedNodeWrapper._write_memo_cache` checked `if result == "error": return` to skip caching errors. Fixed: added `action` parameter, skip when `action == "error"`.
- **Unused `node_type_name` parameter in `check_cache_validity`**: Copied from old code but never used in the function body. Removed.
- **Unused `trace_success` variable in engine**: Assigned but never read. Removed.

### 24 remaining failures (all Phase 6)
Categories:
- `isinstance(flow, Flow)` checks (3 tests)
- `flow.start_node.initial_params` inspection (8 tests — null_defaults)
- `flow.start` attribute access (2 tests — compiler_integration)
- `flow.run.__name__ == "run_with_hooks"` (2 tests — compiler_output_wrapping)
- `isinstance(node, PflowBatchNode)` / `inner_node` chain traversal (7 tests — compiler_batch)
- Stale mock + complex trace assertion (1 test — metrics_propagation)
- Mock flow with `.run()` return (1 test — compiler_basic)

---

## Phase 4 — COMPLETE

**Date**: 2026-03-30
**Result**: 4655/4679 tests pass. Runner and WorkflowExecutor use engine directly.

### Files modified
- `src/pflow/core/exceptions.py` — `CompilationError` moved here from `compiler.py` (breaks circular import chain, enables module-level type imports)
- `src/pflow/execution/runner.py` — `_compile_and_execute` uses `compile_workflow` + `WorkflowEngine` instead of `compile_ir_to_flow` + `flow.run()`
- `src/pflow/runtime/workflow_executor.py` — uses `compile_workflow` + `WorkflowEngine` with compile-once caching (`_cached_workflow`, `_cached_workflow_ir_id`)
- `src/pflow/runtime/compilation/compiler.py` — imports `CompilationError` from `core.exceptions`, imports engine types at module level
- `src/pflow/runtime/engine/batch_executor.py` — imports `CompilationError` from `core.exceptions` (module-level, no lazy import)
- `src/pflow/runtime/engine/engine.py` — lazy import of `CompilationError` from `core.exceptions` (only used in error guard)
- `tests/test_runtime/test_workflow_executor/test_workflow_executor.py` — fixed 4 stale mock patches
- `tests/test_runtime/test_workflow_executor/test_workflow_name.py` — fixed 2 stale mock patches
- `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py` — fixed 8 stale mock patches
- `tests/test_execution/test_workflow_execution.py` — fixed 1 stale mock patch
- `tests/test_mcp/test_connection_pool.py` — fixed 2 stale mock patches + updated mock return types

### Key decisions

1. **WorkflowExecutor compile-once caching**: Instance-level `_cached_workflow` and `_cached_workflow_ir_id`. For sequential batch: compile once, reuse for all items (O(1)). For parallel batch: each deep-copied WorkflowExecutor starts with `_cached_workflow=None`, compiles independently (O(N)). This matches the plan.

2. **WorkflowExecutor `_compile_sub_workflow` signature change**: Removed `child_trace` parameter. Trace is now an engine concern — `exec()` creates the engine with `trace_collector=child_trace`.

3. **Shim `initial_params` seeding**: Runner seeds user params via `_initialize_shared_store`. Shim seeds via explicit `initial_params` injection. Both paths result in the same shared store state. The `resolved_defaults` are seeded AFTER user params in both paths (so defaults don't override user values).

### Stale mock pattern
The plan correctly predicted all stale mock locations. Pattern: any test mocking `compile_ir_to_flow` at an import path where the production code now uses `compile_workflow`. For tests mocking at `pflow.runtime.workflow_executor.*`, the fix was mechanical: change target name + add `WorkflowEngine` mock. For runner tests, the fix was changing `pflow.runtime.compile_ir_to_flow` to `pflow.runtime.compile_workflow`.

---

## Post-Phase 4 Cleanup

**Date**: 2026-03-30

### Lint fixes
- **TRY203 in `compile_workflow()`**: Removed 4 unnecessary `try/except SomeError: raise` blocks that just re-raised without adding context. These were cargo-culted from `compile_ir_to_flow` where they also served no purpose. The functions (`_parse_ir_input`, `_instantiate_nodes_for_workflow`, `_wire_nodes`, `_get_start_node`) raise their own errors — catching and re-raising adds nothing.
- **S101 in `batch_executor.py`**: Changed `assert batch_config is not None` to `if batch_config is None: raise ValueError(...)`. Ruff disallows `assert` in production code (stripped by `python -O`).
- **SIM102 in `instrumentation.py`**: Combined `elif exit_code and exit_code != 0: if ignore_errors:` into single `elif exit_code and exit_code != 0 and ignore_errors:`.
- **F841 in `engine.py`**: Removed `trace_success = action != "error"` — was assigned but never used (the old `InstrumentedNodeWrapper` used it but the engine passes `error=e` to `record_trace` on the error path instead).
- **Ruff auto-format**: Reformatted `engine.py`, `instrumentation.py`, `template_resolution.py`, `batch_executor.py`. Key change: ruff removed a duplicate `detect_api_warning` import from `engine.py` — it was imported both at the top level AND from `.api_warning_detector`. The `instrumentation.py` had an unused `from .api_warning_detector import detect_api_warning` (the detector is called by the engine directly, not by instrumentation functions).

### Circular import resolution — the journey

The initial `make check` flagged F821 (`Undefined name 'NodeConfig'`) in `compiler.py` function signatures. Three approaches were tried:

1. **`from __future__ import annotations` + `TYPE_CHECKING`** — worked but `from __future__ import annotations` made ruff surface 26 pre-existing UP045 warnings on code I didn't write (every `Optional[X]` became a warning). Rejected: too much noise.

2. **Module-level import** (`from pflow.runtime.engine.types import ...` in compiler.py) — circular import: `compiler.py` → `engine/__init__.py` → `engine.py` → `batch_executor.py` → `compiler.py` (for `CompilationError`). 192 test failures.

3. **`# noqa: F821` on string annotations** — works but is a band-aid. User correctly asked: "is the noqa the best solution or just the easiest?"

The root cause was `CompilationError` living in `compiler.py` — a heavy module that the engine can't import without triggering a cycle. `CompilationError` is a pure exception class with zero dependencies. The fix: move it to `core/exceptions.py` where all other pflow exceptions live. This breaks the cycle at the architectural level — `batch_executor.py` imports from `core/exceptions.py` (leaf module), `compiler.py` imports engine types at module level (clean, real types, no hacks).

Created #185 for the same pattern in `ValidationError` (17 imports, 11 lazy, in `ir_schema.py`) and `MarkdownParseError` (10 imports, 7 lazy, in `markdown_parser.py`).

---

## Handoff Notes for Next Agent (Phase 5+)

### Current state
- **Phases 1-4 complete**. Engine is the active execution path for ALL workflows.
- **4655/4679 tests pass** (99.5%). 24 failures are tests inspecting wrapper chain internals.
- **No production code broken**. Wrappers still exist as dead code (Phase 5 deletes them).
- **`compile_ir_to_flow()` is now a thin shim** — it calls `compile_workflow()` + wraps in `_CompiledWorkflowShim`. All real execution goes through the engine.

### Architecture after Phase 4

```
CLI / MCP
  → WorkflowRunner._compile_and_execute()
    → compile_workflow(ir, registry, initial_params)    [NEW — returns CompiledWorkflow]
    → shared_store.update(workflow.resolved_defaults)
    → WorkflowEngine(metrics, trace, only_node).run(workflow, shared_store)  [NEW]
      → for each node: _execute_node(node, config, shared)
        → resolve_templates / execute_batch / node._run(namespaced_store)
    → ExecutionResult(...)

Sub-workflows (WorkflowExecutor):
  → compile_workflow() with compile-once cache (_cached_workflow)
  → WorkflowEngine(trace_collector=child_trace).run(compiled, child_storage)
```

### What the next agent needs that ISN'T in the plan

The implementation plan (`.taskmaster/tasks/task_135/implementation/implementation-plan.md`) has detailed Phase 5-7 instructions including file lists, test tables, and step-by-step actions. Don't repeat that here. This section covers only what changed DURING implementation.

**Dead code in compiler.py** — functions still present but no longer called by any production path: `_apply_template_wrapping`, `_create_single_node`, `_instantiate_nodes`, `_apply_run_hooks`, `_apply_only_node_stop`. Also dead: `from pflow.pocketflow import BaseNode` (only used by dead functions), wrapper imports (lines 23-24), lazy imports of `PflowBatchNode` (line 366) and `InstrumentedNodeWrapper` (line 385).

**`CompilationError` location changed** (not in plan) — now in `core/exceptions.py`, not `compiler.py`. All existing import paths still work via re-export chains. The canonical import is `from pflow.core.exceptions import CompilationError`. The 4 sibling compilation modules still lazy-import from `compiler.py` — those lazy imports can be cleaned up in Phase 5 since the circular import reason no longer exists (see #185).

**`engine/batch_executor.py` has ONE remaining lazy import** — `from pflow.core.exceptions import CompilationError` inside `_execute_parallel`. The module-level import covers `_execute_batch_item`. `_execute_parallel` has its own because ruff auto-moved it during formatting. Both import from `core.exceptions` (not `compiler`), so no circular risk. Can be consolidated to module-level only.

**Compile-once only works for STATIC `workflow_ir`** — discovered during testing. When `workflow_ir` contains `${item}` templates, `resolve_nested` creates a new dict each time, producing a different `id()` per item. This is correct behavior (the child structure IS different per item). For compile-once to apply, per-item values should flow through child_params, not through template expressions inside workflow_ir.

### Regression tests added

- `tests/test_runtime/test_compile_once_regression.py` — 2 tests:
  - `test_compile_workflow_called_once_for_static_child_ir`: patches `compile_workflow` with counter, verifies called exactly once for 3 sequential batch items
  - `test_each_batch_item_produces_distinct_output`: verifies batch items with `${item}` in child IR produce distinct output (not stale from first compilation)
- `tests/test_runtime/test_memo_cache_error_skip.py` — 1 test:
  - `test_error_results_not_served_from_cache`: runs `exit 1` workflow twice with cache enabled, verifies second run also fails (not served from cache)

### 24 currently-failing tests

All inspect wrapper chain internals (isinstance checks, inner_node traversal, flow.run.__name__, hasattr initial_params). Grouped by file — see the plan's Phase 6 section for the full table with fix strategies. The plan's categorization is accurate and doesn't need amendment.

### Gotchas for the next agent

These are things discovered during implementation that deviate from or supplement the plan:

1. **`_source_line` keys are NOT filtered in `split_params`** — plan said filter, but `python_code.py:300` reads `_code_source_line` for error line numbers. Filtering would break it silently.

2. **Batch nodes skip top-level template resolution** — `_execute_node` has `if config.template_config and not config.batch_config` guard. Not in the plan. Without it, `${item}` fails before the batch loop starts.

3. **`_CompiledWorkflowShim` seeds `initial_params` into shared store** — plan's shim only seeded `resolved_defaults`. Tests calling `compile_ir_to_flow` directly need user params in the shared store too (since the `initial_params` override in template resolution is gone).

4. **`CompilationError` import chain**: `core.exceptions` (canonical) → `compiler.py` (re-export) → `compilation/__init__.py` (re-export) → `runtime/__init__.py` (re-export). All paths work. Phase 5 can simplify the sibling modules' lazy imports since the circular import reason is gone.

5. **Engine does NOT restore `node.params` after execution** — the old wrapper did `finally: self.inner_node.params = original_params`. The engine sets `node.params = resolved_params` and never restores. Safe because: each node is visited once per graph traversal (loops re-resolve), and batch items use `_execute_single_node` which sets params per item.

6. **Compile-once `id()` check only works for static `workflow_ir`** — see "Compile-once only works for STATIC workflow_ir" above. The test `test_compile_workflow_called_once_for_static_child_ir` verifies this specifically.

7. **Subagent strategy for Phase 6**: Mechanical test updates (import path changes, assertion updates) → use `test-writer-fixer` in parallel. Complex tests (trace integration, memoization, cache) → main agent with full context.
