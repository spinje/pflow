# Workflow Execution Architecture Decision Report

## Executive Summary

We've identified a fundamental architectural issue with the proposed WorkflowNode implementation. The current design would make WorkflowNode appear as a user-selectable node in the planner, which violates the conceptual model where workflows are compositions, not building blocks. This report analyzes the problem and recommends moving WorkflowNode to the runtime layer as WorkflowExecutor with special compiler handling.

## The Problem

### Conceptual Mismatch

The current design creates a conceptual mismatch between how users think about workflows and how the system implements them:

**User's Mental Model**:
- Nodes = Building blocks (read-file, write-file, etc.)
- Workflows = Saved compositions of nodes
- "I want to use the sentiment analysis workflow"

**Current Implementation Model**:
- WorkflowNode = Just another node that executes workflows
- Would appear in planner as "workflow" alongside other nodes
- "I want to use the workflow node with parameter workflow_ref"

### Discovered Issues

1. **Planner Discovery**:
   - The planner shows ALL nodes from the registry to users
   - WorkflowNode would appear as a selectable node type
   - Users would see "workflow" in the node list, creating confusion

2. **Conceptual Violation**:
   - Workflows are meant to be outputs (things you create)
   - Not inputs (nodes you use to build with)
   - Having a "workflow node" blurs this important distinction

3. **User Experience Impact**:
   ```
   Current planner output would show:
   - File Operations: read-file, write-file, copy-file
   - Workflow Operations: workflow  <-- Confusing!
   - Available Workflows: sentiment-analyzer, data-processor
   ```

## Analysis of Options

### Option 1: Keep as Node, Filter from Planner

**Implementation**:
```python
# In context_builder.py
if node_metadata.get("type") == "workflow":
    continue  # Skip WorkflowNode
```

**Pros**:
- Minimal code changes
- WorkflowNode remains a standard node
- Follows existing patterns

**Cons**:
- Feels like a hack - why have a node that's hidden?
- Still conceptually wrong
- Creates a special case in planner
- Future developers might not understand why it's filtered

**Verdict**: Not recommended - violates principle of least surprise

### Option 2: Move to Runtime with Special Compiler Handling (Recommended)

**Implementation**:
- Move to `src/pflow/runtime/workflow_executor.py`
- Add special case in compiler for `type: "workflow"`
- Not discovered by scanner

**Pros**:
- Maintains clear conceptual separation
- Follows existing pattern (runtime components in runtime/)
- Planner remains clean - only shows actual building blocks
- Aligns with user mental model

**Cons**:
- Requires special case in compiler
- Deviates from "all nodes are equal" principle

**Verdict**: Best balance of conceptual clarity and implementation pragmatism

### Option 3: Explicit Workflow References in IR

**Implementation**:
- Extend IR schema to support workflow references at top level
- No WorkflowNode/Executor needed
- Compiler handles workflow composition directly

Example IR:
```json
{
  "nodes": [...],
  "workflows": [
    {
      "id": "sentiment",
      "ref": "analyzers/sentiment.json",
      "params": {...}
    }
  ]
}
```

**Pros**:
- Most conceptually pure
- Clear separation in IR structure
- No confusion about nodes vs workflows

**Cons**:
- Major architectural change
- Breaks existing IR schema
- More complex implementation

**Verdict**: Too disruptive for MVP, consider for v2

### Option 4: Embrace the Confusion

**Implementation**:
- Keep WorkflowNode as-is
- Document that it's for "advanced users"
- Let it appear in planner

**Pros**:
- No changes needed
- Consistent with "everything is a node" philosophy

**Cons**:
- Confuses users
- Violates conceptual model
- Makes planner output messy
- Poor user experience

**Verdict**: Not recommended - prioritizes implementation over user experience

## Recommendation

**Move WorkflowNode to runtime layer as WorkflowExecutor with special compiler handling.**

This approach:
1. Preserves the user's mental model
2. Keeps implementation relatively simple
3. Follows existing architectural patterns
4. Maintains clean planner output

## Implementation Plan

### Step 1: Move and Rename

Move from:
```
src/pflow/nodes/workflow/workflow_node.py
```

To:
```
src/pflow/runtime/workflow_executor.py
```

Rename class from `WorkflowNode` to `WorkflowExecutor`.

### Step 2: Update Compiler

In `src/pflow/runtime/compiler.py`, modify `import_node_class()`:

```python
def import_node_class(node_type: str, registry: Registry) -> type:
    """Import a node class by type, with special handling for workflows."""

    # Special handling for workflow execution
    if node_type == "workflow":
        from pflow.runtime.workflow_executor import WorkflowExecutor
        return WorkflowExecutor

    # Normal node lookup continues...
    nodes = registry.load()
    # ... rest of existing implementation
```

### Step 3: Ensure Not Discovered

Since WorkflowExecutor is in `runtime/`, the scanner won't find it. Verify by:
1. Running registry update
2. Checking that "workflow" doesn't appear in registry.json
3. Confirming planner doesn't show it

### Step 4: Update Documentation

1. Update the spec to reflect this is a runtime component, not a node
2. Document the special compiler handling
3. Explain why this architectural decision was made

### Step 5: Update Tests

Tests remain largely the same, but:
1. Remove any tests that check for WorkflowNode in registry
2. Add test for compiler special handling
3. Verify planner doesn't show workflow as an option

## Impact Analysis

### What Changes

1. **Compiler**: Gets one special case for workflow type
2. **Location**: WorkflowNode moves to runtime/
3. **Name**: Becomes WorkflowExecutor
4. **Discovery**: No longer appears in registry or planner

### What Stays the Same

1. **Functionality**: Still executes workflows with isolation
2. **IR Usage**: Still uses `type: "workflow"` in IR
3. **Parameters**: Same parameter structure
4. **Behavior**: Same execution semantics

### What This Enables

1. **Clear UX**: Planner only shows actual building blocks
2. **Conceptual Clarity**: Workflows remain compositions, not components
3. **Future Flexibility**: Can evolve workflow execution without affecting node system

## Risks and Mitigations

### Risk 1: Special Case in Compiler
**Mitigation**: Document clearly why this exception exists. It's a small, well-contained special case.

### Risk 2: Future Developers Confusion
**Mitigation**: Add clear comments in compiler explaining the architectural decision.

### Risk 3: Breaking "All Nodes are Equal" Principle
**Mitigation**: This isn't really a node - it's a runtime component that executes workflows. The principle still holds for actual nodes.

## Alternative Considerations

### Why Not Create a Separate Workflow Execution System?

We considered building a completely separate system for workflow execution, bypassing the node system entirely. However:
- Would duplicate much of the node lifecycle (prep/exec/post)
- Would require parallel execution paths in the runtime
- WorkflowExecutor can reuse existing node patterns while being internal

### Why Not Use a Different Type Name?

We considered using a type like "_workflow" or "internal:workflow" to signal it's special. However:
- Users would still write `type: "workflow"` in their IR
- The underscore would leak implementation details into user-facing IR
- Better to handle internally in compiler

## Conclusion

Moving WorkflowNode to the runtime layer as WorkflowExecutor preserves the conceptual model users have (workflows are compositions, not building blocks) while keeping the implementation pragmatic. The small special case in the compiler is a worthwhile trade-off for maintaining a clean user experience.

This approach:
- Keeps the planner output clean and understandable
- Maintains the conceptual separation between nodes and workflows
- Follows existing architectural patterns
- Requires minimal changes to the current implementation

The key insight is that WorkflowExecutor isn't really a "node" in the user-facing sense - it's runtime machinery for executing nested workflows. Placing it in the runtime layer reflects this reality.
