# Task 138 Plan Review Results (2026-03-29)

8 specialized review agents deployed against `task-138.md`. All findings evaluated, verified, and applied to the task spec.

## Confirmed Findings (applied to task spec)

### 1. `sanitize_parameters()` is NOT dead code
- **Found by**: 5 of 8 agents independently
- **Issue**: Plan listed it as dead (63 lines, never called). Actually called in `executor_service.py:546`, `workflow_errors.py:84,91`, `error_formatter.py:67,70`. Module-level import at `executor_service.py:11`.
- **Root cause**: The MCP CLAUDE.md says "never called in any service" — meaning MCP services specifically, not the execution layer.
- **Fix applied**: Removed from Phase 0 dead code list. Marked as "NOT dead code" with callers listed.

### 2. `core/__init__.py` cleanup scope overstated
- **Found by**: 2 agents
- **Issue**: Plan said "only `normalize_ir` and `StdinData` used via this path." Tests also import `validate_ir` (5-6 files), `ValidationError` (3-4 files), `FLOW_IR_SCHEMA` (1 file).
- **Root cause**: Original searcher agent only checked `src/`, not `tests/`.
- **Fix applied**: Changed to per-symbol grep verification requirement. Listed known-used and likely-dead symbols.

### 3. `services/__init__.py` needs updating alongside `settings_service.py` deletion
- **Found by**: 1 agent
- **Issue**: `mcp_server/services/__init__.py:11` imports `SettingsService`. Deleting the file without updating causes `ImportError`.
- **Fix applied**: Added to Phase 0 requirements.

### 4. Sub-workflow validation path was ambiguous
- **Found by**: 4 agents
- **Issue**: Plan said "WorkflowValidator runs on child IR during compilation" — unclear whether this replaces or supplements `_prepare_compilation()`, and what happens to mutation side effects (`__template_resolution_mode__`, defaults, `__env_param_names__`).
- **Correct answer**: `_prepare_compilation()` (with `prepare_inputs()` mutations) continues to run for ALL compilation paths including children. Only duplicated *validation checks* are stripped. `WorkflowValidator` Step 8 already validates children at pre-execution time — no new call needed inside the compiler.
- **Fix applied**: Rewrote the validation requirement to be precise.

### 5. Design constraints missing
- **Found by**: 3 agents (concurrency, silent-failures, validation-consistency)
- **Issue**: Load-bearing ordering constraints documented in Implementation Notes but not elevated to explicit rules. Implementer could "clean up" the ordering and break things.
- **Fix applied**: Added 5 non-negotiable design constraints (mutation ordering, per-execution instantiation, runner statelessness, asymmetric key handling, pipeline ordering).

### 6. Test migration scope understated
- **Found by**: 3 agents
- **Issue**: Plan said "test migration expected." Actually ~8-10 specific test files need updating with specific mock target paths that will move.
- **Fix applied**: Listed 6 specific test files with what needs changing in each.

## Investigated and Dismissed

### `${item}` batch variable registration side effect
- **Raised by**: review-feature-interactions
- **Claim**: `validate_workflow_templates()` registers `${item}` as a side effect. Stripping the call from the compiler would break batch workflows.
- **Investigation**: Read the code. `validate_workflow_templates()` builds a LOCAL `node_outputs` dict that registers `item` and `__index__` — but this dict is never returned or stored. It exists solely to prevent false-positive validation errors. Runtime injection of `${item}` happens in `PflowBatchNode`, not in validation.
- **Verdict**: Not a real concern. Stripping the call loses pre-execution validation of batch variable references (acceptable — `WorkflowValidator` Step 4 already validates them), but runtime behavior is unaffected.

## Additional Open Design Questions (from review)

Added to the task spec's open design questions:
- How does `display_validation_warnings()` (prints directly to stderr from `_prepare_compilation()`) route through the Runner's output interface?
- Where does `_load_settings_env()` live? Currently duplicated in `compile_validation.py` and `cli/main.py`.
- Which exception types does the Runner wrap into `ExecutionResult`? Two-layer re-raise dance between `_handle_execution_exception()` and `execute_workflow()` must be preserved or replaced.

## Additional Test Suggestions (from review)

- **CLI/MCP parity integration test**: Same workflow through both paths, assert identical `ExecutionResult`. Highest-value test for the task's goal.
- **"Validator called once" regression guard**: Mock-wrap `WorkflowValidator.validate`, assert `call_count == 1`. Prevents reintroducing dual validation.
- **Registry run template resolution regression test**: `${var}` params resolve correctly (currently silently broken).

## Verified Clean (do not re-check)

All 8 agents confirmed these are correct:
- `_extract_default_output` + 3 helpers: genuinely dead (zero production callers)
- `planning/` directory: empty remnants only
- `core/workflow/__init__.py` re-exports: zero consumers
- MCP disabled tools (`settings_tools.py`, `test_tools.py`): properly commented out
- `validate_file_path()`: genuinely dead
- Dual validation matrix (4 duplicated checks): accurately described
- `initial_params` mutation flow: correctly documented
- PocketFlow batch thread isolation: safe, unaffected by Phase 1
- `_PROPAGATED_KEYS` for child workflows: unaffected
- MCP pool double-check locking: correct
- `asyncio.to_thread` per-call isolation: correct
- `normalize_ir()` called in both resolver paths: correct
- `__no_cache__` pop vs `__only_node__` filter asymmetry: correctly documented
