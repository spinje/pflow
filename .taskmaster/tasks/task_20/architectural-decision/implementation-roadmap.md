# Task 20 Implementation Roadmap

## Overview

This roadmap incorporates the architectural decision to implement WorkflowExecutor as a runtime component rather than a discoverable node.

## Implementation Phases

### Phase 1: Core Implementation

#### Step 1.1: Create WorkflowExecutor
- **File**: `src/pflow/runtime/workflow_executor.py`
- **Action**: Copy the WorkflowNode implementation from the plan, but:
  - Change class name to `WorkflowExecutor`
  - Update docstring to clarify it's a runtime component
  - Keep all functionality identical

#### Step 1.2: Update Compiler
- **File**: `src/pflow/runtime/compiler.py`
- **Action**: Add special handling in `import_node_class()`:
  ```python
  if node_type == "workflow":
      from pflow.runtime.workflow_executor import WorkflowExecutor
      return WorkflowExecutor
  ```

#### Step 1.3: Add Exceptions
- **File**: `src/pflow/core/exceptions.py`
- **Action**: Add WorkflowExecutionError as specified

### Phase 2: Testing

#### Step 2.1: Create Test Structure
```bash
mkdir -p tests/test_runtime/test_workflow_executor
touch tests/test_runtime/test_workflow_executor/__init__.py
touch tests/test_runtime/test_workflow_executor/test_workflow_executor.py
touch tests/test_runtime/test_workflow_executor/test_integration.py
```

#### Step 2.2: Write Tests
- Copy tests from the plan but update imports
- Add compiler special handling test
- Remove any registry-related tests

### Phase 3: Integration Verification

#### Step 3.1: Verify Not Discoverable
```bash
# Update registry
python -m pflow registry update

# Check registry doesn't contain workflow
grep -i workflow ~/.pflow/registry.json  # Should return nothing
```

#### Step 3.2: Test Execution
Create a test workflow that uses `type: "workflow"` and verify it executes correctly.

### Phase 4: Documentation

#### Step 4.1: Create Workflow Execution Guide
- **File**: `docs/features/workflow-execution.md`
- Explain how to use `type: "workflow"` in IR
- Show examples
- Clarify this is different from saved workflows

#### Step 4.2: Update Architecture Docs
- Add note about runtime components vs nodes
- Document the compiler special case

## Key Differences from Original Plan

1. **Location**: `runtime/` instead of `nodes/workflow/`
2. **Name**: `WorkflowExecutor` instead of `WorkflowNode`
3. **Discovery**: Not discoverable by planner
4. **Compiler**: Has special handling for "workflow" type
5. **Tests**: In `test_runtime/` instead of `test_nodes/`

## Success Criteria

- [ ] WorkflowExecutor works identically to planned WorkflowNode
- [ ] Does NOT appear in planner node list
- [ ] Does NOT appear in registry
- [ ] Workflows can execute sub-workflows using `type: "workflow"`
- [ ] All tests pass
- [ ] Documentation explains the architecture clearly

## Important Notes

1. **Don't create anything in `nodes/workflow/`** - this is the key change
2. **The implementation code remains the same** - just moved and renamed
3. **Users never see this as a "node"** - it's internal runtime machinery
4. **The IR format doesn't change** - still use `type: "workflow"`

This approach maintains the conceptual clarity that workflows are compositions, not components, while still providing the nested execution capability we need.
