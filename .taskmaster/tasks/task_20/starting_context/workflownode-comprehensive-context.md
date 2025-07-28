# WorkflowNode Implementation: Comprehensive Context

## Executive Summary

This document provides complete context for implementing WorkflowNode, a new node type that enables workflows to execute other workflows as sub-components. After rigorous analysis, we've identified that while the concept is architecturally sound, the implementation requires careful handling of several critical aspects including circular dependency detection, resource management, and error propagation.

## System Overview

### What is pflow?

pflow is a workflow compiler that transforms natural language and CLI pipe syntax into permanent, deterministic CLI commands. It follows a "Plan Once, Run Forever" philosophy, built on the PocketFlow framework.

### Core Architecture

1. **PocketFlow Framework** (`pocketflow/__init__.py`):
   - Provides Node, Flow, and Shared Store abstractions
   - Nodes have a three-phase lifecycle: prep(), exec(), post()
   - Flows orchestrate nodes using action-based routing
   - Shared store enables inter-node communication

2. **pflow Components**:
   - **CLI** (`src/pflow/cli/main.py`): Entry point for workflow execution
   - **Compiler** (`src/pflow/runtime/compiler.py`): Transforms IR to Flow objects
   - **Registry** (`src/pflow/registry/`): Node discovery and metadata storage
   - **Nodes** (`src/pflow/nodes/`): Discrete computational units

## What is WorkflowNode?

WorkflowNode is a specialized node that:
1. Loads workflow definitions from files or accepts inline IR
2. Compiles the workflow to a Flow object
3. Executes the Flow with parameter mapping and storage isolation
4. Returns results to the parent workflow

### Key Design Insight

WorkflowNode is NOT using PocketFlow's native Flow-as-Node capability. Instead, it's an execution wrapper that manages sub-workflow execution within its exec() method. This is architecturally correct because we need:
- Dynamic workflow loading at runtime
- Parameter mapping between parent and child
- Storage isolation options
- Error context preservation

## Current System Analysis

### How Nodes Work Today

1. **Discovery**: Scanner finds Python classes inheriting from BaseNode
2. **Registration**: Metadata stored with module path and class name
3. **Compilation**: Nodes instantiated via `node_class()` with no constructor params
4. **Parameter Setting**: Via `node.set_params(params)` after instantiation
5. **Execution**: Flow calls `node._run(shared)` which triggers prep/exec/post lifecycle

### Critical System Characteristics

1. **Registry Model**: Only handles Python modules, not data files
2. **Shared Storage**: Unlimited in-memory dictionary with no reserved keys
3. **Error Handling**: Nodes use exec_fallback for retries, return "error" action
4. **Template Resolution**: Runtime resolution from shared store + initial_params
5. **No Resource Limits**: No timeouts, memory limits, or execution controls
6. **Synchronous Execution**: No async support, no cancellation mechanism

## WorkflowNode Design Details

### Core Implementation

```python
class WorkflowNode(BaseNode):
    """Execute another workflow as a sub-workflow."""

    def prep(self, shared):
        # 1. Load workflow (from file or inline)
        # 2. Validate against circular dependencies
        # 3. Create storage context based on mode
        # 4. Apply input parameter mappings

    def exec(self, prep_res):
        # 1. Compile workflow IR to Flow
        # 2. Execute with isolated storage
        # 3. Capture success/failure

    def post(self, shared, prep_res, exec_res):
        # 1. Apply output mappings
        # 2. Handle error propagation
        # 3. Return appropriate action
```

### Storage Isolation Modes

1. **mapped** (default): Only explicitly mapped data flows between workflows
2. **isolated**: Complete isolation, empty storage for child
3. **scoped**: Filtered view of parent storage with prefix
4. **shared**: Direct access to parent storage (dangerous)

### Parameter System

- **Input Mapping**: Maps parent values to child parameters using template syntax
- **Output Mapping**: Extracts specific child outputs back to parent
- **Template Support**: Full `$variable` syntax with nested paths

## Integration Points

### 1. Compiler Integration

- No special handling needed - WorkflowNode is a regular node
- May be wrapped with TemplateAwareNodeWrapper if params contain templates
- Recursive compilation happens at runtime, not compile time

### 2. Registry Integration

- WorkflowNode registered like any other node
- Workflow files are NOT in registry - loaded at runtime
- Registry passed through compilation for sub-workflow compilation

### 3. Error Propagation

- WorkflowExecutionError preserves nested context
- Error path tracked through execution stack
- Child errors bubble up as "error" action

## Critical Implementation Requirements

### 1. Circular Dependency Detection

```python
# Track execution stack
execution_stack = shared.get("_pflow_workflow_stack", [])
if self.params["workflow_ref"] in execution_stack:
    raise CircularDependencyError()
execution_stack.append(self.params["workflow_ref"])
```

### 2. Resource Limits

- Maximum nesting depth: 10 levels (configurable)
- File size limit: 10MB for workflow files
- Execution timeout: Future enhancement

### 3. Security Validations

- Path traversal prevention for workflow_ref
- Reserved key namespace: `_pflow_*`
- JSON parsing error handling

### 4. Error Context Preservation

```python
class WorkflowExecutionError(Exception):
    def __init__(self, message, workflow_path, original_error):
        # Preserve full execution path
        # Include original error details
        # Build human-readable message
```

## Known Limitations and Risks

### 1. Architectural Constraints

- Registry doesn't handle workflow artifacts
- No workflow versioning system
- No built-in timeout mechanism
- Memory usage unbounded for shared storage

### 2. Performance Considerations

- Registry loaded on every compilation
- Shallow copy overhead for complex nodes
- No caching of compiled workflows
- Recursive compilation cost

### 3. Edge Cases Requiring Attention

- Missing workflow files
- Malformed workflow IR
- Parameter mapping to non-existent keys
- Output mapping failures
- Deep nesting stack overflow
- Concurrent execution of same workflow

## Implementation Impact Analysis

### Files to Modify

1. **New Files**:
   - `src/pflow/nodes/workflow/workflow_node.py` - Main implementation
   - `src/pflow/nodes/workflow/__init__.py` - Package initialization
   - `tests/test_nodes/test_workflow/` - Comprehensive tests

2. **Modified Files**:
   - `src/pflow/core/exceptions.py` - Add WorkflowExecutionError
   - `src/pflow/runtime/compiler.py` - Pass registry for recursion
   - Documentation updates

### No Breaking Changes

- Existing workflows continue to work
- New node type doesn't affect other nodes
- Backward compatible IR format

## Testing Strategy

### Unit Tests
- WorkflowNode lifecycle methods
- Parameter mapping logic
- Storage isolation modes
- Error handling paths

### Integration Tests
- Simple nested workflow execution
- Parameter passing scenarios
- Error propagation
- Circular dependency detection

### Edge Case Tests
- Missing files
- Malformed IR
- Deep nesting
- Resource exhaustion

## Future Enhancements

1. **Workflow Registry**: Store and version workflows
2. **Execution Timeouts**: Prevent runaway workflows
3. **Progress Reporting**: Monitor nested execution
4. **Workflow Caching**: Compile once, reuse Flow objects
5. **Async Execution**: Better control and cancellation

## Conclusion

WorkflowNode is a well-designed solution for enabling workflow composition in pflow. While it faces some architectural constraints (no workflow registry, no timeouts), the core design is sound and implementable. The key is careful attention to circular dependencies, error handling, and resource management. With proper implementation of the safety mechanisms outlined here, WorkflowNode will provide powerful workflow composition capabilities while maintaining system stability.
