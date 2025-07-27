# Template Validation Error: Node Type Attribution

## Overview

Enhancement to template validation error messages to include which specific node types were checked when a template variable cannot be resolved. This improvement would help users debug validation failures more effectively and could provide valuable feedback to the planner.

## Current State

When template validation fails for a variable not found in node outputs, the current error message is:
```
Template variable $api_config.endpoint has no valid source - not provided in initial_params and path 'endpoint' not found in outputs from any node in the workflow
```

## Proposed Enhancement

The original Task 19 specification called for more specific error messages that attribute the missing variable to specific node types:
```
Template variable $api_config.endpoint has no valid source - not in initial_params and path 'endpoint' not found in outputs of node type 'config-loader'
```

## Context and Discovery

During Task 19 implementation (Node IR for accurate template validation), this requirement was identified in the formal specification but not fully implemented. The implementation successfully moved from heuristic-based validation to registry-based validation, eliminating false failures, but stopped short of tracking which node types produce which outputs.

### Why This Matters

1. **Debugging Clarity**: Users could immediately see which node types were present in their workflow and confirm the validator checked the right nodes.

2. **Planner Feedback Loop**: When validation fails, the planner could use the specific node type information to make better decisions:
   - If the variable is missing from a specific node type's outputs, the planner might choose a different node
   - If no nodes in the workflow produce the variable, the planner could search for nodes that do

3. **Multi-Node Workflows**: In complex workflows with many nodes, knowing exactly which nodes were checked reduces debugging time.

## Technical Requirements

### Data Structure Changes

Currently, `_extract_node_outputs()` merges all outputs into a single dict:
```python
node_outputs = {
    "api_config": {"type": "dict", "structure": {...}},
    "summary": {"type": "str"},
    # ... more outputs
}
```

Would need to track sources:
```python
node_outputs = {
    "api_config": {
        "type": "dict",
        "structure": {...},
        "sources": ["config-loader", "env-reader"]  # NEW
    }
}
```

### Error Generation Logic

The error generation would need to:
1. Check if the base variable exists in any node's outputs
2. If yes but path fails, report which node types were checked
3. If no, list all node types in the workflow that were checked

### Edge Cases

- Multiple nodes writing the same variable (common for "error", "status")
- Variables with different structures from different nodes
- Empty workflows (no nodes to check)

## Implementation Complexity

**Estimated effort**: 2-4 hours

**Changes required**:
1. Modify `_extract_node_outputs()` to track source node types
2. Update `_validate_template_path()` to return richer failure information
3. Enhance error message generation with node type details
4. Update all affected tests

**Risk**: Low - changes are localized to template validator

## Decision Rationale

This enhancement was **not implemented** in Task 19 because:

1. **MVP Focus**: The core goal of eliminating false validation failures was achieved
2. **Diminishing Returns**: The current error messages are clear enough for most debugging
3. **Assumptions**: The spec assumes 1:1 mapping between variables and node types, but reality is more complex
4. **Test Coverage**: All 611 tests pass with current implementation

## Future Considerations

### For Planner Integration

When implementing planner improvements, consider:
- Planner could parse validation errors to extract missing variable names
- Registry could expose a "find nodes that output X" query method
- Validation could return structured data, not just string errors

### For User Experience

Consider a `--verbose-validation` flag that shows:
- All nodes checked
- All outputs found
- Detailed path traversal attempts
- Suggestions for which nodes might provide missing variables

## Recommendation

Implement this enhancement when:
1. Users report difficulty debugging validation errors
2. The planner needs richer feedback for workflow adjustments
3. As part of a broader validation improvement initiative

Priority: **Low-Medium** - Nice to have, but not blocking any core functionality.
