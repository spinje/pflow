# Fork: Task 107 — Phase 3.3 — Fix core/execution/MCP test files

## Entry 1: Initial analysis

Attempting: Read all 5 test files and understand the changes needed.

Result:
- ✅ Read all 5 files. Key patterns identified:
  - test_workflow_manager.py: Uses old `save(name, ir_dict, description)`, `json.load()` for reading saved files, `.json` extension, `rich_metadata` wrapper
  - test_executor_service.py: Uses `save(workflow_ir=..., name=..., description=...)`, reads saved `.json` with `json.load()`, checks `rich_metadata.last_execution_params`
  - test_mcp_server/test_workflow_save.py: Uses `ExecutionService.save_workflow(workflow=ir_dict, name=..., description=..., force=...)` — needs to pass markdown content
  - test_workflow_save_service.py: Tests `save_workflow_with_options(name, ir_dict, description, ...)` — needs new signature, some tests use mocks
  - test_workflow_manager_update_ir.py: Tests dead code — skip entire file

Status: Starting fixes, beginning with the skip file and then test_workflow_manager.py.
