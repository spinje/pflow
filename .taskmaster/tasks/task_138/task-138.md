# Task 138: Shared Execution Pipeline

> **Authoritative design decisions**: `implementation/progress-log.md` contains all resolved design questions and assumption audit results etc. This spec provides problem context, requirements, and implementation notes. Where they conflict, the progress log is correct.

## Description

Replace the parallel CLI/MCP orchestration layers with a single execution pipeline. Both entry points call one runner, eliminating ~1,500 lines of duplicated/glue code. Resolves Issue 6 (entry point divergence) and Issue 4 remainder (dual validation).

## Status

in progress

## Priority

high

## Problem

Two structural problems compound every feature addition:

**1. Five entry points, five different setup paths (Issue 6)**
CLI file execution, CLI validate-only, MCP server, CLI registry run, and MCP registry run each build their own orchestration from partially-shared components. Two `resolve_workflow()` functions share zero code. MCP skips `prepare_inputs()` entirely, so `initial_params` has a different shape per entry point. Result: every new feature must work through 5 paths, and "works in CLI, breaks in MCP" is a recurring bug class (Tasks 107, 80, 72).

**2. Dual validation (Issue 4 remainder)**
`WorkflowValidator` (8-step, pre-execution) and `_validate_workflow()` (5-step, during compilation) duplicate 4 checks: stdin, data flow, templates, and IR structure. The compiler's `_validate_workflow()` also does input preparation (defaults, type coercion, template mode) — a compilation concern mixed into validation. Neither calls the other.

**Combined impact on AI agents adding features:** ~12,000 lines of orchestration code to understand before reaching the node being modified. `cli/main.py` alone is 1,383 lines (49% pure glue), and `mcp_server/services/execution_service.py` reimplements ~800 lines of the same logic.

## Solution

Two phases, each independently shippable:

### Phase 0 — Dead Code Cleanup ✅
Removed ~620 lines of verified dead code (plus `__cache_chunks__` dead parameter). No behavioral changes. 4,666 tests pass unchanged.

### Phase 1 — Shared WorkflowRunner
A single `WorkflowRunner` that both CLI and MCP call:
```
WorkflowRunner.run(ir, params, config, *, output, workflow_manager, workflow_name) → ExecutionResult
  # resolve file refs
  # validate (once, via WorkflowValidator)
  # compile (via compile_ir_to_flow)
  # run (via flow.run)
  # extract results, errors, warnings
  # update metadata (if workflow_manager provided)
  # cleanup (MCP pool)
```
- CLI and MCP become thin callers configuring the runner
- Merge two `resolve_workflow()` into one accepting `str | dict`
- Strip duplicated validation from `_validate_workflow()`, rename to `_prepare_compilation()` — keeps only input preparation (defaults, type coercion, template mode)
- `WorkflowExecutorService` class absorbed into runner (it's a function cosplaying as a class — single public method, instantiated once, discarded)
- `execute_workflow()` wrapper inlined

## Design Decisions

- **Strip compiler validation, don't merge validators**: `_validate_workflow()` does two things — validation (duplicated) and preparation (unique). Strip the duplicated validation, keep the preparation, rename to `_prepare_compilation()`. Don't try to merge with `WorkflowValidator` — they have different error contracts (return strings vs raise exceptions) and the preparation logic is a compiler concern.

- **Preserve `initial_params` semantics**: This task preserves the current data-flow model (how `initial_params` override shared store). Task 135 changes that model later. This avoids a big-bang rewrite.

- **Dead code first**: Phase 0 reduces noise (745 lines) before the structural work begins. Shipped independently as a simple PR.

- **This is NOT Issue 6 "unification"**: Issue 6 was framed as "merge 5 divergent paths." The actual solution eliminates the divergent orchestration code, not merges it. Entry points become thin configuration, not implementations.

## Dependencies

- Task 134 (Output Detection Unification) — in progress by another agent. Should land first so the Runner calls the unified output detector. Not blocking, but better ordering.

No hard dependencies.

## Implementation Approach

This is a **design-then-implement** task, not implement-from-spec. The research is complete (braindumps have full file inventories, code traces, metrics). What's missing is the design decisions that should be made collaboratively with the user.

### Phase 0 — Just do it
Mechanical deletion. Grep to verify each item has zero callers, delete, run tests. Ship as one PR.

### Phase 1 — Design the Runner API first
Before writing any code:
1. Design the `WorkflowRunner.run()` signature and config object
2. Show concrete before/after for cli/main.py and MCP execution_service.py
3. Get user approval on the API, then implement

**Design questions — ALL RESOLVED.** See `implementation/progress-log.md` for decisions Q1–Q10 plus 4 additional items resolved during pre-Phase 1 audit.

**Design constraints (non-negotiable, from code review):**
1. **Mutation ordering**: Shared store seeded from `execution_params` BEFORE `_prepare_compilation()` mutates `initial_params`. This task preserves this ordering; Task 135 changes it deliberately.
2. **Per-execution instantiation**: `MCPConnectionPool` and `MemoizationCache` created per `run()` call, never on Runner init. MCP pool is stateful (daemon thread, sessions). Memoization cache holds per-execution `read_enabled` flag.
3. **Runner statelessness**: No mutable state on Runner instance. MCP uses `asyncio.to_thread` for concurrent calls — shared mutable state causes races.
4. **Asymmetric key handling**: Currently `__no_cache__` is popped from params, `__only_node__` is filtered from store but kept in `initial_params`. Phase 1 moves both to `RunnerConfig` — `cache_enabled` and `only_node` — eliminating the pop/filter hacks. The compiler reads `only_node` from config instead of `initial_params`.
5. **Pipeline ordering**: `_inject_workflow_file_path()` → `resolve_file_references()` → `WorkflowValidator.validate()` → `_validate_workflow()` (renamed to `_prepare_compilation()`) → `compile_ir_to_flow()`. Sub-workflow relative paths need `_pflow_workflow_file` set before validation.

## Requirements

### Phase 0 — Dead Code ✅ (~620 lines removed)

Completed 2026-03-29. See `implementation/progress-log.md` for full details.

Also removed during pre-Phase 1 audit: `__cache_chunks__` dead parameter from `cli/main.py` (never passed at call site, zero consumers).

### Phase 1 — Shared Runner

#### Pipeline
- Single `WorkflowRunner` class/module that both CLI and MCP call
- Runner accepts `RunnerConfig` (frozen dataclass: trace, cache, verbose, only_node, output_format, source_file_path) + kwargs (`output`, `workflow_manager`, `workflow_name`) — entry points configure but don't implement
- `cli/main.py` reduced from ~1,383 lines to thin Click handler + Runner call
- `mcp_server/services/execution_service.py` reduced from ~790 lines to thin async wrapper + Runner call
- `execute_workflow()` in `workflow_execution.py` absorbed into runner
- `WorkflowExecutorService` class absorbed into runner

#### Resolution
- Single `resolve_workflow()` accepting `str | dict` with input-type dispatch
- CLI's extension validation (.json migration hint, .md rename suggestion) preserved
- MCP's raw-markdown and dict-input support preserved
- Suggestion mechanisms unified

#### Validation
- `WorkflowValidator.validate()` called once per execution (not twice)
- `_validate_workflow()` renamed to `_prepare_compilation()` — retains ONLY: input preparation (`prepare_inputs()`), template resolution mode, output name validation, output producibility check
- Duplicated checks removed from compiler: stdin validation, `validate_data_flow()`, `validate_workflow_templates()`
- **Sub-workflow validation**: `_prepare_compilation()` (with its `prepare_inputs()` mutation side effects) continues to run for ALL compilation paths, including child workflows inside `WorkflowExecutor`. Only the duplicated *validation checks* are stripped. `WorkflowValidator` Step 8 already validates children recursively at pre-execution time — no new `WorkflowValidator` call needed inside the compiler. The mutations (`__template_resolution_mode__`, defaults, `__env_param_names__`) must be preserved for child workflows.
- Validate-only mode uses unified error pipeline (no more `sys.exit()` bypass)

#### Param Flow
- CLI and MCP params go through the same preparation path (unified `prepare_inputs()` call)
- `initial_params` has consistent shape regardless of entry point
- MCP gains type coercion (currently skipped) and input defaults (currently skipped)
- Internal keys (`__verbose__`, etc.) injected uniformly. `__no_cache__` and `__only_node__` absorbed by `RunnerConfig` — no longer in params dict.

#### Registry Run
- Full: build synthetic single-node IR, call `runner.run()` — gets template resolution, tracing, metrics, error handling for free
- Unified MCP metadata injection (currently split between `inject_special_parameters` and `_parse_mcp_node_type`)
- Unified type coercion (currently split between `coerce_input_to_declared_type` and `coerce_to_declared_type`)
- Empty shared store in MCP registry run fixed (should have params like CLI)

## Implementation Notes

### The `initial_params` flow (critical to understand)

Current chain:
```
entry point constructs execution_params
  → _initialize_shared_store() copies params INTO shared store (BEFORE compilation)
  → compile_ir_to_flow(initial_params=execution_params)
    → _validate_workflow() MUTATES initial_params in-place:
        - adds __template_resolution_mode__
        - merges defaults from prepare_inputs()
        - adds __env_param_names__
    → _instantiate_nodes(initial_params)
      → every TemplateAwareNodeWrapper gets REFERENCE to same dict
  → flow.run(shared_store)
    → wrapper._build_resolution_context():
        context = dict(shared)           # shared store
        context.update(initial_params)   # compile-time OVERRIDES runtime
```

Key subtlety: shared store is seeded from `execution_params` BEFORE `_validate_workflow()` mutates it. So defaults added by `prepare_inputs()` are in `initial_params` but NOT in the shared store. The `context.update(initial_params)` override is what makes defaults available to template resolution. This task preserves this pattern — Task 135 changes it.

For sub-workflows: `child_params` is a FRESH dict containing resolved template values (changes per batch item), NOT inheriting parent's `initial_params`. This is why sub-workflows recompile — per-item `child_params` differ. Task 135 addresses this.

### MCP param divergence (Phase 1 fixes this)

| Aspect | CLI | MCP |
|--------|-----|-----|
| Early `prepare_inputs()` | Yes (type coercion, defaults) | No |
| Internal keys | `__verbose__`, `__only_node__`, `__no_cache__` | None |
| Type coercion | `coerce_input_to_declared_type` | None (compiler's `prepare_inputs` does it later) |
| Env var resolution | Via `prepare_inputs` 5-tier | None |

After Phase 1: both paths go through the same param preparation in the Runner.

### Files that change significantly

**Phase 0**: `executor_service.py`, `core/__init__.py`, `core/workflow/__init__.py`, `mcp_server/` (dead files)

**Phase 1**: `cli/main.py` (shrinks dramatically), `execution/workflow_execution.py` (absorbed), `execution/executor_service.py` (restructured into runner), `mcp_server/services/execution_service.py` (shrinks dramatically), `cli/workflow_resolution.py` + `mcp_server/utils/resolver.py` (merged), `runtime/compilation/compile_validation.py` (stripped + renamed)

### What this does NOT solve

- **Wrapper chain complexity** (3,920 lines, 19x PocketFlow): Becomes easier to address but not directly changed.
- **Output layer** (5,404 lines, 166 functions): Becomes easier (one callsite) but not directly changed.
- **Error hierarchy** (241 bare `raise ValueError`, no unified base): Not addressed.
- **Compile-once / batch recompilation**: Addressed by Task 135, which depends on this task.

### Interaction with Task 134

Task 134 (in progress) unifies the output detection divergence (`_find_auto_output()` with different priority orders in `workflow_output.py` vs `success_formatter.py`). If it lands first, the Runner calls the unified detector. If not, the Runner can call either and Task 134 cleans up later. No blocking dependency.

### Relationship to Task 135

Task 135 (Compile-Once + Batch Decomposition) depends on this task. This task unifies the param preparation path so `initial_params` has a consistent shape. Task 135 then changes `initial_params` semantics (compile-time-only, shared store as single runtime source). The `_prepare_compilation()` function created here is what Task 135 will split further into structural validation and input preparation.

## Verification

### Phase 0 ✅
- 4,666 tests pass with zero test changes, `make check` clean
- Grep confirmed zero remaining references to removed functions/files
- 10 smoke test baselines diffed — only timing/timestamps/cache hits differ

### Phase 1
- All existing tests pass (test migration required — see affected files below)
- 14 smoke test baselines in `.taskmaster/tasks/task_138/baseline/` — diff before/after for behavioral regression
- CLI workflow execution produces identical output before/after
- MCP workflow execution produces identical output before/after
- Add CLI/MCP parity integration test: same workflow through both paths, assert identical `ExecutionResult` contents
- MCP gains type coercion and input defaults (new behavior — verify with test)
- Validate-only mode produces JSON output when `--output-format json` (currently bypasses unified pipeline)
- Registry run with template params (`${var}`) resolves correctly (currently silently broken) — add regression test
- Add regression guard: mock-wrap `WorkflowValidator.validate`, assert `call_count == 1` during full execution

**Test files requiring migration** (mock targets and direct instantiations that move):
- `test_executor_service.py` — 13+ tests directly instantiating `WorkflowExecutorService`, testing `_update_workflow_metadata`
- `test_api_warning_system.py` — 3 direct instantiations
- `test_workflow_execution.py` — mock patches of `pflow.execution.workflow_execution.WorkflowExecutorService`
- `test_workflow_output_handling.py` — patches `pflow.execution.workflow_execution.execute_workflow`
- `test_validate_only.py` — 9+ tests testing current `sys.exit()` behavior (exit codes must be preserved)
- `test_checkpoint_tracking.py` — 1 mock patch of `WorkflowExecutorService.execute_workflow`

## References

### Research documents
- `scratchpads/architectural-debt/compounding-issues.md` — the 10-issue catalog with per-issue analysis, ~~DONE~~ markers for completed fixes
- `scratchpads/handoffs/architectural-debt-fixes.md` — handoff from 6 completed sweeps, decision history, open threads

### Starting context (braindumps from design conversation)
- `.taskmaster/tasks/task_138/starting-context/braindump-pipeline-analysis.md` — detailed technical analysis: codebase metrics, entry point comparison matrix, `initial_params` flow trace, dead code inventory, validation overlap matrix, wrapper chain analysis, MCP duplication quantification, output layer inventory
- `.taskmaster/tasks/task_138/starting-context/braindump-conversation-context.md` — reasoning journey, user's mental model, where assumptions were corrected, unexplored territory, advice for implementing agent
- `.taskmaster/tasks/task_138/starting-context/code-review-results.md` — 8 review agents' findings on original spec

### Implementation artifacts
- `.taskmaster/tasks/task_138/implementation/progress-log.md` — **authoritative**: all design decisions, assumption audit results, ambiguity resolutions
- `.taskmaster/tasks/task_138/implementation/design-review-synthesis.md` — 8 review agents' analysis of 10 design questions with consensus/conflict per question
- `.taskmaster/tasks/task_138/baseline/` — 14 smoke test baselines (10 original + 4 HIGH-risk paths added during audit)

### Key source files
- `src/pflow/execution/executor_service.py` — `WorkflowExecutorService` (absorbed into runner)
- `src/pflow/execution/workflow_execution.py` — thin `execute_workflow()` wrapper (absorbed)
- `src/pflow/cli/main.py` — CLI orchestration (1,383 lines, shrinks dramatically)
- `src/pflow/mcp_server/services/execution_service.py` — MCP execution (790 lines, shrinks dramatically)
- `src/pflow/cli/workflow_resolution.py` — CLI resolver (merged)
- `src/pflow/mcp_server/utils/resolver.py` — MCP resolver (merged)
- `src/pflow/runtime/compilation/compile_validation.py` — dual validation (stripped + renamed)

### Prior tasks
- Task 135 (Compile-Once + Batch Decomposition) — depends on this task
- Task 134 (Output Detection Unification) — in progress, soft dependency (better if it lands first)
- Task 137 (Unified CLI Output Pipeline) — completed, laid foundation for unified error output
- Issue 6 (Entry Points) in compounding-issues.md — RESOLVED by this task

### Architectural context
- `.taskmaster/tasks/task_137/task-review.md` — output layer design insights relevant to runner design
