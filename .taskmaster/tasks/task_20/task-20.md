# Task 20: Implement Nested Workflow Execution

## Description
Enable workflows to execute other workflows as sub-components through a runtime execution component. This will allow users to compose complex workflows from simpler, reusable workflow components while maintaining proper parameter isolation and error handling.

## Dependencies
- Task 5: Node discovery and registry implementation (for runtime component discovery)
- Task 6: JSON IR schema (to understand workflow structure)
- Task 8: Shell pipe integration (for parameter passing patterns)
- Task 16: Planning context builder (to list available workflows)
- Task 18: Template Variable System (for parameter mapping)
- Task 19: Node Interface Registry (for validation)

## Details

### Objective
Create a runtime component that enables workflows to reference and execute other workflows with:
- Controlled parameter passing between parent and child workflows
- Storage isolation options to prevent data pollution
- Circular dependency detection
- Maximum nesting depth enforcement
- Error context preservation through nested execution

### Implementation Approach

1. **Runtime Component**: Create `WorkflowExecutor` in `src/pflow/runtime/` as internal infrastructure
   - Not a user-facing node (won't appear in planner)
   - Handles workflow loading, compilation, and execution
   - Manages storage isolation and parameter mapping

2. **Compiler Integration**: Add special handling in compiler for `type: "workflow"`
   - When compiler sees this type, use WorkflowExecutor directly
   - Inject registry for sub-workflow compilation
   - No registry entry needed (not discoverable)

3. **Storage Isolation Modes**:
   - `mapped`: Only explicitly mapped parameters (default, safest)
   - `isolated`: Completely empty storage
   - `scoped`: Filtered view with prefix
   - `shared`: Direct reference (dangerous but sometimes needed)

4. **Safety Features**:
   - Circular dependency detection via execution stack tracking
   - Maximum nesting depth (configurable, default 10)
   - Reserved key namespace (`_pflow_*`) for execution metadata
   - Path validation for workflow references

5. **Parameter System**:
   - Input mapping: Map parent values to child parameters
   - Template support: Full `$variable` resolution
   - Output mapping: Extract child results back to parent
   - Missing parameters handled gracefully

### IR Usage Example
```json
{
  "nodes": [{
    "id": "analyze",
    "type": "workflow",
    "params": {
      "workflow_ref": "analyzers/sentiment.json",
      "param_mapping": {
        "text": "$input_text",
        "language": "$config.lang"
      },
      "output_mapping": {
        "sentiment_score": "analysis_result"
      },
      "storage_mode": "mapped"
    }
  }]
}
```

### Key Design Decisions

1. **Runtime vs Node**: WorkflowExecutor is infrastructure, not a building block
   - Lives in `runtime/` with other execution machinery
   - Doesn't appear in user-facing documentation or planner
   - Maintains conceptual clarity: workflows are compositions, not components

2. **Compiler Special Case**: Worth the trade-off for user experience
   - Small, well-contained exception for `type: "workflow"`
   - Prevents confusion about workflows being nodes
   - Enables future workflow execution improvements

### Error Handling
- Wrap all errors with workflow execution context
- Preserve error path through nested levels
- Return configurable error action (default: "error")
- Set error in shared storage for parent handling

## Status
done

## Completed
2025-07-28

## Test Strategy

### Unit Tests (30+ tests covering all requirements)
1. **Parameter Validation**:
   - Test missing workflow_ref and workflow_ir
   - Test providing both parameters
   - Test invalid combinations

2. **Safety Features**:
   - Circular dependency detection (simple and multi-level)
   - Maximum depth enforcement
   - Reserved key isolation

3. **Storage Modes**:
   - Test all four isolation modes
   - Verify data flow restrictions
   - Check system key preservation

4. **Parameter System**:
   - Template resolution in mappings
   - Missing parameter handling
   - Output mapping with missing keys

5. **Error Scenarios**:
   - File not found
   - Malformed JSON
   - Compilation failures
   - Execution failures
   - Invalid storage modes

### Integration Tests
1. **End-to-end execution**:
   - Inline workflow execution
   - File-based workflow loading
   - Multi-level nesting
   - Parameter flow validation

2. **Error propagation**:
   - Child failures bubble up correctly
   - Error context preserved
   - Custom error actions work

3. **Real workflow scenarios**:
   - Data processing pipelines
   - Conditional workflows
   - Complex parameter mappings

### Test Organization
- Tests in `tests/test_runtime/test_workflow_executor/`
- Comprehensive test coverage following project patterns
- Mock external dependencies appropriately
- Verify compiler integration works correctly
