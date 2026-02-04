# Fork: Task 107 — Phase 3.3 — Fix runtime/nodes test files

## Entry 1: Reading test files and planning changes

Attempting: Read all 5 assigned test files to understand what needs changing.

Result:
- ✅ Read all 5 files
- test_shell_smart_handling.py: 11 tests, all write JSON to disk via `json.dumps()` + `write_text()`. Mechanical: change `.json` → `.pflow.md`, use `write_workflow_file()`.
- test_workflow_executor_comprehensive.py: 3 tests write JSON files (test_workflow_ref_only, test_circular_dependency_simple, test_multilevel_circular_dependency). Others use inline IR dicts. Also test_malformed_json needs rewriting for markdown parse errors, and test_relative_path_resolution uses `.json` extensions.
- test_integration.py: 1 fixture `workflow_file` writes `.json`. Change to `.pflow.md`.
- test_workflow_name.py: 7 errors. Uses `WorkflowManager.save()` with old signature `save(name, ir_dict, description)`. Needs new signature with `ir_to_markdown()`. Also asserts on `.json` in workflow path.
- test_stdin_no_hang.py: 1 test writes JSON workflow to disk. Change to `.pflow.md`.

Files modified: none yet
Status: Starting implementation with test_shell_smart_handling.py

## Entry 2: Fix test_shell_smart_handling.py

Attempting: Replace JSON workflow writes with markdown equivalents.

Result:
- ✅ Replaced all 11 `tmp_path / "test.json"` + `json.dumps` with `tmp_path / "test.pflow.md"` + `write_workflow_file()`
- ✅ Kept `import json` for JSON output parsing in `TestSmartHandlingJsonOutput`
- ✅ 11/11 tests pass

Files modified: tests/test_nodes/test_shell_smart_handling.py
Status: Moving to test_workflow_executor_comprehensive.py

## Entry 3: Fix test_workflow_executor_comprehensive.py

Attempting: Replace JSON file writes and update error/assertion tests.

Result:
- ✅ Changed 3 file-writing tests to use `write_workflow_file()` + `.pflow.md`
- ✅ Changed `test_malformed_json` → `test_malformed_workflow` (writes markdown without Steps section)
- ✅ Changed `test_relative_path_resolution` to use `.pflow.md` extensions
- ✅ Changed `test_multilevel_circular_dependency` stack entries to `.pflow.md`
- ✅ Changed `test_workflow_file_missing` to reference `.pflow.md`
- ✅ Fixed `test_workflow_ref_only` assertion: markdown IR includes `purpose` field from required descriptions, so compare individual fields instead of full IR equality
- ✅ 26/26 tests pass

Files modified: tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py
Status: Moving to test_integration.py

## Entry 4: Fix test_integration.py

Attempting: Update workflow_file fixture.

Result:
- ✅ Changed fixture from `test_workflow.json` + `json.dump` to `test_workflow.pflow.md` + `write_workflow_file()`
- ✅ 7/7 tests pass

Files modified: tests/test_runtime/test_workflow_executor/test_integration.py
Status: Moving to test_workflow_name.py

## Entry 5: Fix test_workflow_name.py

Attempting: Update WorkflowManager.save() calls and assertions.

Result:
- ✅ Changed `workflow_manager` fixture to use new save() signature: `save("test-workflow", markdown_content)` with `ir_to_markdown()`
- ✅ Changed `.json` → `.pflow.md` in path assertions and file references
- ✅ Fixed 3 IR equality assertions to compare individual fields (markdown IR includes `purpose`)
- ✅ 9/9 tests pass

Files modified: tests/test_runtime/test_workflow_executor/test_workflow_name.py
Status: Moving to test_stdin_no_hang.py

## Entry 6: Fix test_stdin_no_hang.py

Attempting: Update integration test workflow file write.

Result:
- ✅ Changed `tmp_path / "test.json"` + `json.dumps` to `tmp_path / "test.pflow.md"` + `write_workflow_file()`
- ✅ 8/8 tests pass

Files modified: tests/test_core/test_stdin_no_hang.py
Status: ALL DONE — 61/61 tests pass across all 5 files

## Final Summary

All 5 assigned test files are fixed and passing:

| File | Before | After | Key Changes |
|------|--------|-------|-------------|
| test_shell_smart_handling.py | 11 failures | 11 pass | Mechanical .json → .pflow.md |
| test_workflow_executor_comprehensive.py | 3 failures | 26 pass | .json → .pflow.md, malformed test rewrite, purpose field assertions |
| test_integration.py | 1 failure | 7 pass | Fixture update |
| test_workflow_name.py | 7 errors | 9 pass | WorkflowManager.save() signature, .json → .pflow.md, purpose field |
| test_stdin_no_hang.py | 1 failure | 8 pass | Mechanical .json → .pflow.md |

Key insight: The markdown parser always produces a `purpose` field on nodes (from the required description text). Tests that assert `prep_res["workflow_ir"] == simple_workflow_ir` (where simple_workflow_ir has no purpose) fail. Fixed by comparing individual fields (id, type, params) instead of full IR equality.
