# Fork: Task 107 — Phase 2.6 — Runtime Executor

## Entry 1: Replace JSON loading with markdown parser

Attempting: Update `_load_workflow_file()` in `runtime/workflow_executor.py` to use `parse_markdown()` instead of `json.load()`.

Result:
- ✅ Replaced `import json` with `from pflow.core.markdown_parser import MarkdownParseError, parse_markdown`
- ✅ `_load_workflow_file()` now reads file as text via `path.read_text(encoding="utf-8")` and calls `parse_markdown(content)`
- ✅ Error handling: `MarkdownParseError` caught instead of `json.JSONDecodeError`, with path included in error message
- ✅ Removed `isinstance(workflow_ir, dict)` type check — `parse_markdown()` always returns a dict via `MarkdownParseResult.ir`, so the check is unnecessary
- ✅ Updated error message for missing nodes: references `## Steps` section instead of JSON
- ✅ Updated docstring from "Load workflow from file" to "Load workflow from .pflow.md file"

Files modified: `src/pflow/runtime/workflow_executor.py`

## Final Status

All changes complete:
- `_load_workflow_file()` uses `parse_markdown()` instead of `json.load()`
- All error messages reference markdown format, not JSON
- `json` import removed (no longer needed)

Fork F5 complete.
