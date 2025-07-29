# Summary of Findings: Context Builder & Task 20 Impact

## Executive Summary

Task 17 (Natural Language Planner) faces **two categories of gaps** that need resolution:

1. **Original Context Builder Gaps**: Need for structured workflow metadata access
2. **New Task 20 Gaps**: Workflow reference format mismatch between planner and runtime

Both must be addressed for the planner to function properly.

## Category 1: Original Context Builder Gaps

### What's Missing
1. **No public access to workflow metadata** after LLM selection
   - `_load_saved_workflows()` is private
   - No `get_workflow_metadata(name)` method

2. **Path A blocked**: WorkflowDiscoveryNode can't return found workflow's IR

### Required Additions
```python
# Minimal methods needed in context_builder.py:
def get_workflow_metadata(workflow_name: str) -> Optional[dict]:
    """Get metadata for a specific workflow by name."""

def get_all_workflows_metadata() -> list[dict]:
    """Get all saved workflow metadata."""
```

## Category 2: Task 20 Integration Gaps

### The Design Mismatch
- **Planner Mental Model**: Name-based ("fix-issue")
- **Runtime Mental Model**: File-based ("./fix-issue.json")
- **Gap**: No component bridges between names and paths

### Critical Problems

1. **WorkflowExecutor doesn't expand tilde (~)**
   - `"~/.pflow/workflows/fix-issue.json"` fails
   - Must use absolute or relative paths

2. **No workflow name resolution**
   - Can't use `"fix-issue"` as reference
   - Must provide full file path

3. **Planner can't know paths**
   - Doesn't know where workflows are saved
   - Can't generate valid relative paths
   - Absolute paths aren't portable

### The Special "workflow" Node Type

Task 20 enables powerful composition:
```json
{
  "type": "workflow",
  "params": {
    "workflow_ref": "path/to/workflow.json",
    "param_mapping": { /* map parent → child params */ },
    "output_mapping": { /* map child → parent outputs */ }
  }
}
```

But the planner can't generate valid `workflow_ref` values!

## Critical Decisions Needed

### Decision 1: Context Builder API Extension
**Options**:
- A) Add public methods (recommended) ✓
- B) Use private methods (fragile)
- C) Create duplicate loader (redundant)
- D) Parse markdown (error-prone)

### Decision 2: Workflow Reference Resolution
**Options**:
- A) Fix WorkflowExecutor for name resolution
- B) Fix WorkflowExecutor for tilde expansion (minimal) ✓
- C) Add compiler-level resolution
- D) Document absolute paths (non-portable)

### Decision 3: Planner Workflow Composition Strategy
**Options**:
- A) Use standard location assumption + tilde fix
- B) Load and inline workflow IR (loses benefits)
- C) Skip workflow composition for MVP

## Recommended Path Forward

### Phase 1: Unblock Basic Functionality
1. Add public methods to context_builder.py
2. Add tilde expansion to WorkflowExecutor
3. Planner uses `"~/.pflow/workflows/{name}.json"` pattern

### Phase 2: Document Workarounds
1. Document that planner assumes standard workflow location
2. Add examples showing the pattern
3. Note this as a known limitation

### Phase 3: Future Enhancement
Consider adding proper name resolution:
- Either in WorkflowExecutor
- Or as a new runtime component
- Enables true name-based workflow references

## Impact on Task 17 Implementation

Without these fixes:
- **Path A works** (can find and return workflows)
- **Path B limited** (can't compose using existing workflows)
- **Lost opportunity** to leverage Task 20's power

With minimal fixes:
- **Both paths work**
- **Workflow composition enabled**
- **Some architectural debt** (name/path mismatch)

## Next Steps

1. **Get user decision** on context builder API extension
2. **Get user decision** on workflow reference approach
3. **Implement chosen solutions**
4. **Update planner prompts** to teach LLM about workflow composition

The planner can be implemented with these limitations documented, but addressing them would significantly improve the system's usability and power.
