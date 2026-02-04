# Fork: Task 107 — Phase 3.3 — Fix 3 heaviest CLI test files

## Entry 1: Analyze and fix test_workflow_output_handling.py

Attempting: Replace all JSON workflow file creation with markdown equivalents.

Result:
- ✅ Added `from tests.shared.markdown_utils import ir_to_markdown` import
- ✅ Replaced 24 occurrences of `NamedTemporaryFile(suffix=".json") + json.dump()` with `NamedTemporaryFile(suffix=".pflow.md") + f.write(ir_to_markdown(workflow))`
- ✅ Two indentation patterns: 8-space (standard) and 12-space (inside for loop) — both fixed
- ✅ All 24 tests pass

Files modified: `tests/test_cli/test_workflow_output_handling.py`
Status: File 1 of 3 complete.

## Entry 2: Analyze and fix test_main.py

Attempting: Update all JSON references to markdown format, rewrite tests that create JSON files.

Result:
- ✅ Updated help text assertion: `"pflow workflow.json"` → `"pflow workflow.pflow.md"`
- ✅ Renamed and rewrote `test_from_json_file` → `test_from_markdown_file`
- ✅ Renamed and rewrote `test_from_json_file_with_custom_extension` → `test_from_pflow_file_with_empty_steps`
- ✅ Renamed and rewrote `test_from_json_file_with_whitespace` → `test_from_pflow_file_with_whitespace`
- ✅ Updated `test_from_file_missing`: `nonexistent.json` → `nonexistent.pflow.md`
- ✅ Rewrote `test_json_workflow_with_parameters` → `test_markdown_workflow_with_parameters`
- ✅ Rewrote `test_file_with_parameters` to use .pflow.md
- ✅ Rewrote `test_json_file_with_no_parameters` → `test_pflow_file_with_no_parameters`
- ✅ Rewrote `test_file_with_parameters_template_resolution` to use .pflow.md
- ✅ Rewrote `test_stdin_with_file_workflow` to use .pflow.md
- ✅ Rewrote `test_error_empty_json_file` → `test_error_empty_pflow_file`
- ✅ Updated `test_error_file_permission_denied` to use .pflow.md
- ✅ Updated `test_error_file_encoding` to use .pflow.md
- ✅ Rewrote `test_json_file_automatic_detection` → `test_pflow_file_automatic_detection`
- ✅ Updated `test_path_with_slash_triggers_file_detection` to use .pflow.md
- ✅ Updated `test_absolute_path_workflow` to use .pflow.md
- ✅ Updated `test_home_directory_expansion` to use .pflow.md
- ✅ All 29 tests pass (1 skipped — pre-existing skip for oversized input test)

Files modified: `tests/test_cli/test_main.py`
Status: File 2 of 3 complete.

## Entry 3: Analyze and fix test_dual_mode_stdin.py

Attempting: Replace JSON workflow creation with markdown equivalents across all test classes.

Result:
- ✅ Added `from tests.shared.markdown_utils import ir_to_markdown` import
- ✅ Replaced all `workflow_file.write_text(json.dumps(workflow))` with `workflow_file.write_text(ir_to_markdown(workflow))`
- ✅ Changed all file extensions from `.json` to `.pflow.md` (workflow files, producer/consumer/transform files)
- ✅ Updated docstrings referencing .json to .pflow.md
- ✅ All 22 tests pass

Files modified: `tests/test_cli/test_dual_mode_stdin.py`
Status: File 3 of 3 complete.

## Summary

All 3 test files fixed and passing:
- `tests/test_cli/test_workflow_output_handling.py`: 24 passed
- `tests/test_cli/test_main.py`: 29 passed, 1 skipped (pre-existing)
- `tests/test_cli/test_dual_mode_stdin.py`: 22 passed

**Total: 75 passed, 1 skipped**

Files modified:
- `tests/test_cli/test_workflow_output_handling.py`
- `tests/test_cli/test_main.py`
- `tests/test_cli/test_dual_mode_stdin.py`

No issues for the main agent to resolve.
