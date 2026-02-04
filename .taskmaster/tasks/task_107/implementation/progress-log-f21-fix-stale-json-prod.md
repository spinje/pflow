# Fork: Task 107 — Fix stale .json workflow references in production code

## Entry 1: Fix 4 production files

Attempting: Fix stale .json workflow references in 4 production files.

Result:
- ✅ `src/pflow/core/user_errors.py:228`: `'workflow.json'` → `'workflow.pflow.md'` in error message
- ✅ `src/pflow/execution/formatters/workflow_save_formatter.py:11,49`: docstring examples `/path/to/workflow.json` → `/path/to/workflow.pflow.md`
- ✅ `src/pflow/planning/context_builder.py:317-326`: `*.json` glob → `*.pflow.md`, updated variable names and log messages
- ✅ `src/pflow/cli/repair_save_handlers.py`: 7 fixes — docstrings, file paths, comments all updated from `.json` to `.pflow.md` for workflow files
- ✅ ruff: all checks passed
- ✅ mypy: no issues found in 4 source files

Files modified:
- `src/pflow/core/user_errors.py`
- `src/pflow/execution/formatters/workflow_save_formatter.py`
- `src/pflow/planning/context_builder.py`
- `src/pflow/cli/repair_save_handlers.py`

Status: Assignment complete. All 4 files fixed, ruff/mypy clean.
