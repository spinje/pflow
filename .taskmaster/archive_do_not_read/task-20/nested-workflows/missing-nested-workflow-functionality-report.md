# Missing Components for Nested Workflow Support in pflow

This report details the specific components and changes needed to enable workflows containing sub-workflows in the pflow system.

## Executive Summary

While the underlying PocketFlow framework fully supports nested workflows (Flows can contain other Flows as nodes), the pflow CLI layer lacks the necessary components to expose this capability. The primary gaps are in the IR schema, workflow node implementation, compiler support, and registry extensions.

## Missing Components

### 1. Workflow Node Implementation

**What's Missing**: A dedicated node type that can execute another workflow as a sub-component.

**Required Implementation**:
```python
class WorkflowNode(Node):
    """A node that executes another workflow as a sub-workflow."""

    def __init__(self, workflow_ref=None, workflow_ir=None, param_mapping=None):
        """
        Args:
            workflow_ref: Reference to a workflow (file path or registry ID)
            workflow_ir: Inline workflow IR definition
            param_mapping: How to map parent params to sub-workflow
        """
        super().__init__()
        self.workflow_ref = workflow_ref
        self.workflow_ir = workflow_ir
        self.param_mapping = param_mapping or {}

    def prep(self, shared):
        # Load workflow IR if using reference
        # Prepare sub-workflow parameters from parent shared store
        # Create isolated or scoped storage for sub-workflow
        pass

    def exec(self, prep_res):
        # Compile sub-workflow IR to Flow
        # Execute sub-workflow with prepared storage
        # Handle sub-workflow errors appropriately
        pass

    def post(self, shared, prep_res, exec_res):
        # Merge sub-workflow results back to parent shared store
        # Handle output mapping configuration
        # Return appropriate action for parent flow
        pass
```

### 2. IR Schema Extensions

**What's Missing**: The current IR schema has no way to define nested workflows.

**Required Schema Additions**:

```json
{
  "nodes": [
    {
      "id": "sub_workflow_1",
      "type": "pflow.nodes.workflow.WorkflowNode",
      "params": {
        // Option 1: Reference to external workflow
        "workflow_ref": "path/to/workflow.json",

        // Option 2: Inline workflow definition
        "workflow_ir": {
          "nodes": [...],
          "edges": [...],
          "start_node": "..."
        },

        // Parameter mapping from parent to child
        "input_mapping": {
          "parent_key": "child_key"
        },

        // Result mapping from child to parent
        "output_mapping": {
          "child_result": "parent_result"
        },

        // Storage isolation strategy
        "storage_mode": "isolated" | "shared" | "scoped"
      }
    }
  ]
}
```

### 3. Compiler Enhancements

**What's Missing**: The compiler cannot handle recursive workflow compilation.

**Required Changes to `compiler.py`**:

1. **Recursive Compilation Support**:
   - Detect WorkflowNode types during compilation
   - Recursively compile nested workflow IRs
   - Handle circular reference detection
   - Manage compilation context for nested scopes

2. **Workflow Reference Resolution**:
   - Load external workflow files
   - Validate referenced workflows exist
   - Cache compiled sub-workflows for reuse
   - Handle relative vs absolute paths

3. **Parameter Propagation**:
   - Pass template parameters to sub-workflows
   - Support parameter mapping/transformation
   - Validate parameter compatibility

### 4. Registry Extensions

**What's Missing**: The registry only tracks individual nodes, not reusable workflows.

**Required Registry Enhancements**:

1. **Workflow Storage**:
   - Store workflow definitions as first-class entities
   - Support versioning and namespacing
   - Enable workflow discovery by name/tag
   - Implement workflow metadata extraction

2. **Workflow Resolution**:
   - Resolve workflow references by ID/name
   - Support local and remote workflow repositories
   - Handle workflow dependencies
   - Implement caching for performance

### 5. Shared Storage Management

**What's Missing**: No mechanism for storage isolation between parent and sub-workflows.

**Required Storage Features**:

1. **Storage Scoping**:
   ```python
   class ScopedSharedStore:
       """Provides isolated or scoped storage for sub-workflows."""

       def create_subscope(self, prefix):
           # Create isolated namespace for sub-workflow
           pass

       def merge_subscope(self, subscope, mapping):
           # Merge sub-workflow results back to parent
           pass
   ```

2. **Storage Strategies**:
   - **Isolated**: Sub-workflow gets empty storage
   - **Shared**: Sub-workflow shares parent storage (risky)
   - **Scoped**: Sub-workflow gets filtered view of parent storage
   - **Mapped**: Explicit input/output mappings

### 6. CLI Interface Updates

**What's Missing**: No CLI commands for workflow composition.

**Required CLI Features**:

```bash
# Define a workflow that uses other workflows
pflow compose main-workflow.json \
  --add-subflow step1=process-workflow.json \
  --add-subflow step2=transform-workflow.json

# List available workflows
pflow workflows list

# Validate workflow including sub-workflows
pflow validate workflow.json --recursive
```

### 7. Error Handling and Debugging

**What's Missing**: No nested error context or debugging support.

**Required Features**:

1. **Error Context**:
   - Track workflow nesting depth
   - Provide full stack trace through nested workflows
   - Clear error messages showing workflow hierarchy

2. **Debugging Support**:
   - Verbose mode showing sub-workflow execution
   - Storage snapshots at workflow boundaries
   - Ability to debug specific sub-workflow in isolation

### 8. Documentation and Examples

**What's Missing**: No documentation for workflow composition patterns.

**Required Documentation**:

1. **Conceptual Guide**:
   - When to use nested workflows
   - Best practices for workflow composition
   - Parameter passing strategies
   - Storage isolation patterns

2. **Reference Documentation**:
   - WorkflowNode API
   - IR schema for nested workflows
   - CLI commands for composition

3. **Example Workflows**:
   - Simple sub-workflow inclusion
   - Parameter mapping examples
   - Error handling in nested workflows
   - Complex multi-level nesting

## Implementation Roadmap

### Phase 1: Foundation (Prerequisites)
1. Implement WorkflowNode class
2. Extend IR schema for workflow references
3. Add basic compiler support for WorkflowNode

### Phase 2: Core Functionality
1. Implement storage scoping mechanisms
2. Add recursive compilation support
3. Create workflow registry extensions
4. Implement parameter mapping

### Phase 3: CLI and UX
1. Add CLI commands for workflow composition
2. Enhance error messages for nested contexts
3. Implement debugging features
4. Create comprehensive examples

### Phase 4: Advanced Features
1. Workflow versioning support
2. Remote workflow repositories
3. Dependency management
4. Performance optimizations

## Technical Considerations

### Performance Impact
- Recursive compilation overhead
- Storage isolation costs
- Workflow caching strategies

### Security Concerns
- Workflow injection attacks
- Resource consumption limits
- Storage access controls

### Compatibility
- Backward compatibility with flat workflows
- Migration path for existing workflows
- Framework version requirements

## Conclusion

Adding nested workflow support to pflow requires systematic enhancements across multiple layers of the system. While the PocketFlow framework provides the necessary foundation, significant work is needed in the pflow CLI layer to expose this capability in a user-friendly and robust manner. The implementation should be approached in phases, starting with core functionality and gradually adding advanced features.
