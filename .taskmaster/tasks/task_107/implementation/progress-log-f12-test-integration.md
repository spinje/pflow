# Fork: Task 107 — Phase 3.3 — Fix integration test files

## Entry 1: Analysis

Attempting: Analyze all 5 integration test files to understand what needs changing.

Result:
- ✅ Read all 5 test files completely
- ✅ Identified all patterns that need changing

Key patterns found:
1. `test_workflow_manager_integration.py` — calls `wm.save(name, ir_dict, description)` (old signature), checks `.json` paths, uses `json.JSONDecodeError`, checks `metadata.load()` format
2. `test_e2e_workflow.py` — writes `workflow.json` files with `json.dump()`, invokes CLI with `./workflow.json`
3. `test_metrics_integration.py` — uses `tempfile.NamedTemporaryFile(suffix=".json")` extensively, writes JSON workflows
4. `test_sigpipe_regression.py` — writes `workflow.json` in isolated filesystem, invokes CLI with `./workflow.json`
5. `test_workflow_outputs_namespaced.py` — uses `tempfile.NamedTemporaryFile(suffix=".json")` with `json.dump()`

New WorkflowManager.save() signature: `save(name, markdown_content, metadata=None)` — takes markdown string, not IR dict

Files modified: none yet
Status: Starting implementation of fixes, beginning with test_workflow_manager_integration.py
