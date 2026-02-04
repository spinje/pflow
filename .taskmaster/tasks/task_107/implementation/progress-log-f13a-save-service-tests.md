# Fork: Task 107 — Phase 3.3 — Fix test_workflow_save_service.py

## Entry 1: Analysis and plan

Attempting: Analyze all 10 failures and plan fixes.

**Production code state** (verified):
- `save_workflow_with_options(name, markdown_content, *, force=, metadata=)` — no `description` param, `markdown_content` is a string
- `load_and_validate_workflow(source, auto_normalize=True)` — accepts dict, file path str, or workflow name str
- `_load_from_file()` now reads `.pflow.md` with `parse_markdown()`
- `WorkflowManager.save(name, markdown_content, metadata=None)` — no `description` param

**Tests needing updates:**

### TestLoadAndValidateWorkflow:
1. `test_load_from_file_path` — writes `.json`, needs `.pflow.md`
2. `test_load_from_workflow_name` — calls `manager.save("test-workflow", sample_ir, "Test")` (old 3-arg API)
3. `test_reject_invalid_json_in_file` — writes bad JSON `.json`, expects "Invalid JSON" match
4. `test_reject_invalid_workflow_structure` — writes `.json` file with invalid IR
5. `test_reject_invalid_output_sources` — writes `.json`, missing `description` on outputs
6. `test_accept_valid_output_sources` — writes `.json`, missing `description` on outputs

### TestSaveWorkflowWithOptions:
7. `test_save_new_workflow_without_force` — old signature `(name, ir, "Test", force=False)`
8. `test_save_existing_with_force_deletes_first` — old signature
9. `test_save_existing_without_force_raises` — old signature
10. `test_save_with_metadata` — old signature + metadata arg position assertions
11. `test_delete_failure_raises_clear_error` — old signature

Status: Plan complete, starting implementation.

## Entry 2: Implementation complete

Attempting: Update all test methods to use new markdown API.

Result:
- ✅ Removed `import json`, added `from tests.shared.markdown_utils import ir_to_markdown, write_workflow_file`
- ✅ Updated module docstring with Task 107 note
- ✅ `test_load_from_file_path`: writes `.pflow.md` via `write_workflow_file()` instead of `.json`
- ✅ `test_load_from_workflow_name`: calls `manager.save("test-workflow", ir_to_markdown(sample_ir))`
- ✅ `test_reject_invalid_json_in_file` → renamed to `test_reject_invalid_markdown_in_file`: writes `.pflow.md` with invalid content (no `## Steps`), match pattern updated to `"Invalid workflow|Missing"`
- ✅ `test_reject_invalid_workflow_structure`: changed from file-based to dict-based test (the markdown parser catches structure issues at parse time, but dict path tests IR-level validation directly)
- ✅ `test_reject_invalid_output_sources`: writes `.pflow.md` via `write_workflow_file()`, added `description` to output entries
- ✅ `test_accept_valid_output_sources`: writes `.pflow.md` via `write_workflow_file()`, added `description` to all output entries
- ✅ `test_save_new_workflow_without_force`: uses `ir_to_markdown()` for content, keyword-only `force=`, asserts `mock_wm.save.assert_called_once_with("new-workflow", markdown_content, None)`, path `.pflow.md`
- ✅ `test_save_existing_with_force_deletes_first`: same pattern, `.pflow.md` paths
- ✅ `test_save_existing_without_force_raises`: same pattern
- ✅ `test_save_with_metadata`: `save_workflow_with_options("with-metadata", markdown_content, metadata=metadata)`, asserts `mock_wm.save.assert_called_once_with("with-metadata", markdown_content, metadata)`
- ✅ `test_delete_failure_raises_clear_error`: same pattern
- ✅ Ruff lint: all checks passed
- ✅ Ruff format: already formatted
- ⚠️ Could not run pytest directly due to VIRTUAL_ENV conflict from forked session — main agent will verify

Files modified: `tests/test_core/test_workflow_save_service.py`
Status: Assignment complete. All changes implemented. Main agent should run `make test` to verify.
