# Task 138 Implementation Progress Log

## Phase 0 — Dead Code Cleanup

### 2026-03-29 — Phase 0 Complete

**Baseline captured** before any changes: 10 smoke test outputs saved to `.taskmaster/tasks/task_138/baseline/`.

**Starting state**: 4,666 tests passing, `make check` clean.

#### Removed Items

| Item | Lines | Notes |
|------|-------|-------|
| `executor_service.py:_extract_default_output` + 3 helpers | ~90 | Zero production callers confirmed via grep |
| `planning/` directory | 0 | Already removed by Task 92 |
| `core/workflow/__init__.py` re-exports | ~59 | Zero consumers — all imports from submodules |
| `mcp_server/tools/settings_tools.py` | ~173 | Commented out in `__init__.py` |
| `mcp_server/services/settings_service.py` | ~136 | Only served disabled tools |
| `mcp_server/tools/test_tools.py` | ~146 | Commented out in `__init__.py` |
| `mcp_server/utils/validation.py:validate_file_path()` | ~48 | Never called |
| `core/__init__.py` redundant re-exports | ~20 | Reduced from 16 to 5 exports |
| Commented-out references in `server.py`, `tools/__init__.py` | ~10 | Cleaned up dead comments |
| `services/__init__.py` SettingsService import | ~2 | Would have caused ImportError |

**Total removed**: ~620 lines

#### Verification

- ✅ 4,666 tests pass (zero test changes)
- ✅ `make check` clean (lint, mypy, deptry)
- ✅ Smoke tests diff: only timing/timestamps/cache hits differ — zero behavioral changes

#### Also Updated

- `execution/CLAUDE.md` — removed reference to deleted `_extract_default_output()` output priority section

#### Decisions Made

- **`sanitize_parameters()` is NOT dead** — confirmed by code review. Called by `executor_service.py:546`, `workflow_errors.py:84,91`, `error_formatter.py:67,70`. Left in place.
- **`core/__init__.py` kept 5 exports**: `normalize_ir`, `StdinData`, `validate_ir`, `ValidationError`, `FLOW_IR_SCHEMA` — all have consumers via `from pflow.core import` path (src or tests).
- **`PflowError`, `BATCH_CONFIG_SCHEMA`, `detect_binary_content`** confirmed truly dead (zero imports from any path). Removed from re-exports.
- **`core/workflow/__init__.py`** reduced to docstring-only — convention comment pointing to submodule imports.

---

## Phase 1 — Shared WorkflowRunner

### Implementation Steps

1. Design `WorkflowRunner.run()` signature and config object
2. Resolve open design questions with user (10 questions in task spec)
3. Show concrete before/after for `cli/main.py` and MCP `execution_service.py`
4. Get user approval on API design
5. Merge two `resolve_workflow()` functions into one
6. Strip duplicated validation from `_validate_workflow()` → rename to `_prepare_compilation()`
7. Implement `WorkflowRunner` — absorb `WorkflowExecutorService` + `execute_workflow()`
8. Thin down `cli/main.py` to Click handler + Runner call
9. Thin down MCP `execution_service.py` to async wrapper + Runner call
10. Migrate affected tests (8-10 test files with mock target changes)
11. Add new tests: CLI/MCP parity, validator-called-once guard, registry template resolution
12. Verify: `make test && make check`, smoke test diffs, manual spot checks

### Status: Awaiting design discussion with user

**Open design questions** (from task spec):
- Runner config shape (dataclass vs separate params)
- Validate-only mode (separate method vs flag)
- CLI vs Runner responsibility boundary (stdin routing, flag validation)
- Merged `resolve_workflow()` return signature
- Registry run template resolution
- MCP service classes fate (plain functions vs shrink)
- `display_validation_warnings()` routing through Runner output interface
- `_load_settings_env()` deduplication
- Exception wrapping strategy for `ExecutionResult`
