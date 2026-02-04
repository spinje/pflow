# Fork: Task 107 — Phase 3.3 — Fix test_mcp_server/test_workflow_save.py

## Entry 1: Update MCP workflow save tests for markdown format

Attempting: Migrate all 10 tests from old ExecutionService.save_workflow(workflow=dict, description=str) API to new save_workflow(workflow=markdown_str) API.

Result:
- ✅ Added `ir_to_markdown` import from `tests.shared.markdown_utils`
- ✅ Converted all 4 TestWorkflowSaveWithInputs tests: IR dict → markdown content via `ir_to_markdown()`, removed `description=` parameter
- ✅ Converted TestWorkflowSaveValidation.test_rejects_invalid_node_type: uses `ir_to_markdown()` for markdown content
- ✅ Converted TestWorkflowSaveValidation.test_rejects_malformed_templates: hand-crafted raw markdown with `${malformed` (missing closing brace) in prompt code block — `ir_to_markdown()` can't produce malformed templates
- ✅ Converted TestWorkflowSaveValidation.test_rejects_unused_inputs: added descriptions to inputs (required by parser), uses `ir_to_markdown()`
- ✅ Converted TestWorkflowSaveNameValidation tests: both use `ir_to_markdown()`, removed `description=`
- ✅ Converted TestWorkflowSaveOverwrite tests: removed `copy.deepcopy()` (no longer needed since markdown content strings are immutable), removed `description=`
- ✅ All 11 tests pass (was 10 failures + 1 passing before)
- 💡 Removed `import copy` — no longer needed since markdown content is a string (immutable), not a dict that might be mutated in-place

Files modified: `tests/test_mcp_server/test_workflow_save.py`
Status: Assignment complete. All 11 tests pass.
