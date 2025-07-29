# Workflow Reference Resolution - Importance 5/5

Task 20's WorkflowExecutor implementation reveals a fundamental design question about how workflows should be referenced.

## Context:

The WorkflowExecutor enables workflows to reference other workflows using `type: "workflow"`, but it currently requires full paths and doesn't handle common patterns:

```json
{
  "type": "workflow",
  "params": {
    "workflow_ref": "????"  // What should go here?
  }
}
```

Current WorkflowExecutor behavior:
- Expects full paths (absolute or relative)
- Does NOT expand `~` to home directory
- Does NOT resolve workflow names to `~/.pflow/workflows/`
- Just passes paths to `Path.resolve()`

## The Problem:

The design inconsistency between nodes and workflows:
- **Nodes**: Referenced by name via registry (`"type": "github-get-issue"`)
- **Workflows**: Referenced by file path (`"workflow_ref": "./path.json"`)

This creates an **architectural mismatch** where:
1. The planner discovers workflows by name
2. But must reference them by file path
3. No component bridges this gap

## Options:

- [ ] **Option A: Create a Workflow Registry/Resolution Service**
  ```python
  # New component that maps names to paths
  workflow_path = WorkflowResolver.get_path("fix-issue")
  # Returns: "~/.pflow/workflows/fix-issue.json"
  ```
  - Pros: Clean architecture, consistent with node pattern
  - Cons: New component, more complexity

- [ ] **Option B: Add name parameter to WorkflowExecutor**
  ```python
  # Support both patterns:
  {"workflow_ref": "./path.json"}  # Existing
  {"workflow_name": "fix-issue"}   # New
  ```
  - Pros: Backwards compatible, natural API
  - Cons: Two ways to reference workflows

- [x] **Option C: Minimal fix - Add tilde expansion + document pattern**
  ```python
  # In _resolve_safe_path():
  path = Path(os.path.expanduser(str(path)))
  ```
  Then planner always generates: `"~/.pflow/workflows/{name}.json"`
  - Pros: Minimal change, unblocks planner
  - Cons: Planner must know storage convention

- [ ] **Option D: Add resolution at compiler level**
  ```python
  # Compiler resolves workflow names to paths
  if "workflow_name" in params:
      params["workflow_ref"] = resolve_workflow_path(params["workflow_name"])
  ```
  - Pros: Clean separation, WorkflowExecutor unchanged
  - Cons: Compiler becomes more complex

**Recommendation**: Option C for immediate unblocking, with a note that Option A or B would be the proper long-term solution. The architectural inconsistency between node and workflow references should be addressed in a future iteration.

## Impact on Task 17:

Without this fix, the planner CANNOT generate valid workflow references. It would have to:
1. Guess absolute paths (impossible)
2. Use relative paths from unknown working directory (fragile)
3. Not use workflow composition (defeats Task 20's purpose)

With Option B implemented:
```python
# Planner can generate:
{
  "type": "workflow",
  "params": {
    "workflow_ref": "~/.pflow/workflows/fix-issue.json"
  }
}
```

This is portable and will work on any system.

## Critical Note:

This blocks Task 17's ability to leverage Task 20's workflow composition feature. The planner needs a reliable way to reference saved workflows.
