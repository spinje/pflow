# WorkflowNode to Runtime Refactoring Plan

## Overview

Move WorkflowNode from `nodes/workflow/` to `runtime/` to properly reflect its role as internal infrastructure rather than a user-facing node.

## Current State
- WorkflowNode is fully implemented and working in `src/pflow/nodes/workflow/`
- Compiler has special handling to inject registry for `pflow.nodes.workflow` type
- All 39 tests passing
- Complete documentation exists

## Target State
- WorkflowNode renamed to WorkflowExecutor in `src/pflow/runtime/`
- Compiler handles `type: "workflow"` specially (not through registry)
- All tests still passing
- Documentation updated to reflect architectural change

## Why This Matters
- `nodes/` = User-facing features (the API of pflow)
- `runtime/` = Internal system machinery
- WorkflowNode is internal machinery for executing workflows, not a user feature

## Refactoring Steps

### Phase 1: Move and Rename Files
1. Create `src/pflow/runtime/workflow_executor.py`
2. Copy WorkflowNode implementation and rename class to WorkflowExecutor
3. Delete `src/pflow/nodes/workflow/` directory
4. Move tests from `tests/test_nodes/test_workflow/` to `tests/test_runtime/test_workflow_executor/`

### Phase 2: Update Compiler
1. Modify `import_node_class()` to handle `type: "workflow"` specially
2. Remove the current registry injection for `pflow.nodes.workflow`
3. Import WorkflowExecutor directly when type is "workflow"

### Phase 3: Update All References
1. Update imports in all test files
2. Update any documentation references
3. Remove WorkflowNode from node reference docs
4. Ensure examples still work

### Phase 4: Verify
1. Run all tests
2. Test example workflows
3. Verify WorkflowNode doesn't appear in registry

## Subagent Task Assignments

### Agent 1: File Movement and Renaming
**Task**: Move WorkflowNode to runtime as WorkflowExecutor
**Why**: This is the core refactoring - moving the implementation to its proper location

### Agent 2: Compiler Updates
**Task**: Update compiler to handle "workflow" type specially
**Why**: Without registry entry, compiler needs to know how to find WorkflowExecutor

### Agent 3: Import and Reference Updates
**Task**: Update all imports, tests, and references
**Why**: Everything that referenced the old location needs updating

## Risks and Mitigations
- **Risk**: Breaking existing workflows
  - **Mitigation**: Type "workflow" in IR remains unchanged
- **Risk**: Missing import updates
  - **Mitigation**: Use grep to find all references
- **Risk**: Tests failing after move
  - **Mitigation**: Update imports carefully, run tests frequently

## Success Criteria
- [ ] WorkflowExecutor works exactly like WorkflowNode did
- [ ] No "workflow" entry in registry
- [ ] All tests pass
- [ ] Example workflows still execute correctly
- [ ] Documentation reflects the architectural change
