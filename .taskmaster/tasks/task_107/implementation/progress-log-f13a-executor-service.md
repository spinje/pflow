# Fork: Task 107 — Phase 3.3 — Fix test_executor_service.py for markdown format

## Entry 1: Migrate test_executor_service.py from JSON to markdown format

Attempting: Update all 11 failing tests to use the new WorkflowManager.save() API (markdown content instead of IR dict), read .pflow.md files with YAML frontmatter instead of .json with json.load(), and access flat metadata instead of rich_metadata wrapper.

Result:
- ✅ Replaced `json` import with `yaml` import
- ✅ Added `ir_to_markdown` import from `tests.shared.markdown_utils`
- ✅ Created `_read_frontmatter()` helper to read and parse YAML frontmatter from .pflow.md files
- ✅ Created `_TEST_WORKFLOW_IR` shared constant and `_save_test_workflow()` helper to reduce boilerplate
- ✅ Updated all `workflow_manager.save()` calls: old `save(workflow_ir=..., name=..., description=...)` → new `save(name, ir_to_markdown(ir_dict))`
- ✅ Updated all file reads: `.json` → `.pflow.md`, `json.load()` → `_read_frontmatter()` YAML parsing
- ✅ Updated all metadata access: `saved_data["rich_metadata"]["last_execution_params"]` → `frontmatter["last_execution_params"]`
- ✅ Updated `test_metadata_not_updated_on_failure`: freshly saved files have no execution fields in frontmatter (no `rich_metadata` wrapper), so test now asserts `"last_execution_params" not in frontmatter` instead of comparing empty dicts
- ✅ Fixed IR dict: `"command": "echo hi"` was a top-level node field, changed to `"params": {"command": "echo hi"}` so ir_to_markdown generates valid markdown
- ✅ All 12 tests pass

Files modified: `tests/test_execution/test_executor_service.py`
Status: Assignment complete. All 12 tests pass.
