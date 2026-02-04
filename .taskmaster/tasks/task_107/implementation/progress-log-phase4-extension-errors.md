# Fork: Task 107 — Phase 4 — Improve error messages for wrong file extensions

## Entry 1: Add extension-specific error messages

Attempting: When a user runs pflow with a .json, .md, or other non-.pflow.md file, show a clear error pointing them to .pflow.md format instead of a generic "not found".

Result:
- ✅ `_try_load_workflow_from_file()`: Moved `.json` rejection BEFORE `path.exists()` check so it works even when the file doesn't exist on disk
- ✅ `_try_load_workflow_from_file()`: Added `.md` (non `.pflow.md`) rejection with suggested filename
- ✅ `_is_path_like()`: Added `.md` to recognized extensions so bare `workflow.md` reaches the file loading path
- ✅ `_handle_workflow_not_found()`: Added belt-and-suspenders extension checks for `.json` and `.md` identifiers that somehow reach the "not found" handler
- ✅ ruff clean, mypy clean
- ❌ Could not run pytest due to VIRTUAL_ENV mismatch in fork environment — main agent should verify

Decision: Put extension checks before `path.exists()` because the format rejection applies whether or not the file exists. This means `pflow old-workflow.json` shows "JSON no longer supported" even if the file doesn't exist, which is the desired behavior.

Files modified: `src/pflow/cli/main.py`

Error message examples:
- `.json`: "❌ JSON workflow format is no longer supported: old-workflow.json\nWorkflow files use .pflow.md format.\nExample: pflow ./my-workflow.pflow.md"
- `.md`: "❌ Wrong file extension: workflow.md\nWorkflow files use .pflow.md extension.\nRename to: workflow.pflow.md"

Status: Complete. Main agent should run `make test` to verify no regressions and manually test the 4 scenarios.
