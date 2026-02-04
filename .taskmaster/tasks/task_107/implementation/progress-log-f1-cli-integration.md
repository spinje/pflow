# Fork: Task 107 — Phase 2.1 + 2.1b — CLI Integration

## Entry 1: Update cli/main.py for markdown workflow loading

Attempting: Replace all JSON workflow loading, path detection, error display, and help text with markdown equivalents.

Result:
- ✅ `_is_path_like()`: Added `.pflow.md` check; kept `.json` for rejection path
- ✅ `_show_json_syntax_error()` → `_show_markdown_parse_error()`: Uses `MarkdownParseError` fields (line number, suggestion embedded in error message)
- ✅ `_try_load_workflow_from_file()`: Replaced `json.loads()` with `parse_markdown()` + `normalize_ir()`. `.json` files get clear rejection message. Error source renamed from `"json_error"` to `"parse_error"`.
- ✅ `_try_load_workflow_from_registry()` [G3]: Strips `.pflow.md` suffix (9 chars) instead of `.json` (5 chars)
- ✅ `resolve_workflow()`: Updated docstring and comments to reference `.pflow.md` and `"parse_error"`
- ✅ `_handle_workflow_not_found()` [G4]: `"json_error"` → `"parse_error"` check
- ✅ `_setup_workflow_execution()` [G5]: Both `.json` checks → `.pflow.md` checks; used ternary for SIM108 compliance
- ✅ `is_likely_workflow_name()` [G6]: Added `.pflow.md` check alongside `.json`
- ✅ Help text: All 4 occurrences of `workflow.json` → `workflow.pflow.md` in help strings and examples
- ✅ Added `TYPE_CHECKING` import for `MarkdownParseError` (mypy resolution)
- ✅ mypy passes on `cli/main.py`
- ✅ ruff passes (only pre-existing F841 in gated planner code remains)
- 💡 Two pre-existing ruff F841 errors exist in gated planner save functions (`_auto_save_workflow` line 1204, `_prompt_workflow_save` line 1275) where `description` is assigned but unused after gating removed it from the save call. These are from Phase 0.2 gating, not this fork.

Files modified: `src/pflow/cli/main.py`

## Entry 2: Update cli/commands/workflow.py save command

Attempting: Remove `--description` flag, update loading to use markdown parser, prepare save for new content-based flow.

Result:
- ✅ Removed `--description` required option from `save_workflow` command
- ✅ Renamed `_load_and_normalize_workflow()` → `_load_and_parse_workflow()`: Returns `(validated_ir, markdown_content, description)` tuple
- ✅ New function reads `.pflow.md` file, parses with `parse_markdown()`, normalizes IR, validates with `validate_ir()`
- ✅ Rejects `.json` files with clear migration message
- ✅ Updated `_save_with_overwrite_check()` signature: Removed `description` param, accepts `markdown_content` instead of `validated_ir`
- ✅ Added TODO comment for F3: `save_workflow_with_options` signature is changing — passes `markdown_content` as `workflow_ir` with `type: ignore` annotation for now
- ✅ Updated docstring and example: `draft.json` → `my-workflow.pflow.md`, removed `--description` from example
- ✅ `format_save_success()` still receives `validated_ir` for interface display (G7 handled)
- ✅ mypy passes on `cli/commands/workflow.py`
- ✅ ruff passes on `cli/commands/workflow.py`

Files modified: `src/pflow/cli/commands/workflow.py`

## Final Status

All changes in both files complete and verified:
- `src/pflow/cli/main.py` — 9 integration points updated (path detection, loading, error display, registry lookup, workflow not found, setup execution, workflow name heuristic, help text, TYPE_CHECKING import)
- `src/pflow/cli/commands/workflow.py` — Save command updated (removed --description, markdown parsing, content-based save)

Quality checks on assigned files:
- ✅ ruff: clean (pre-existing F841 in gated code only)
- ✅ mypy: no issues found
- ✅ Python syntax: both files parse correctly

Notes for main agent:
- Pre-existing ruff F841 errors in gated planner save functions (lines 1204, 1275 of main.py) — `description` variables assigned but unused after Phase 0.2 gating. Not from this fork.
- `_save_with_overwrite_check` in workflow.py passes `markdown_content` as `workflow_ir` to `save_workflow_with_options` with a `type: ignore` annotation. F3 (save-service) will update the save service signature to accept markdown content properly.

Fork F1 complete.
