# Fork: Task 107 — Phase 3.3 — Fix ruff lint issues in test_workflow_save_integration.py

## Entry 1: Fix 4 ruff lint errors

Attempting: Fix S108 (insecure /tmp paths) on 3 lines and SIM105 (use contextlib.suppress) on 1 line.

Result:
- ✅ Replaced hardcoded `/tmp/test.txt` and `/tmp/t.txt` with `tmp_path` fixture paths on lines 57, 97, 183
- ✅ Added `tmp_path` parameter to 3 test methods that previously used `tempfile.TemporaryDirectory`
- ✅ Replaced try-except-pass with `contextlib.suppress(PermissionError, OSError)` on line 190
- ✅ Added `import contextlib`
- ✅ Removed unused `import tempfile` and `from pathlib import Path` imports
- ✅ Ran `ruff format` to fix formatting
- ✅ `uv run ruff check` passes with 0 errors
- ✅ `uv run ruff format --check` passes (already formatted)

Files modified: `tests/test_cli/test_workflow_save_integration.py`
Status: Complete. All 4 ruff lint issues fixed. Tests could not be run due to unrelated conftest import issue (other forks may be modifying test infrastructure).
