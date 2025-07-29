# Task 20 Impact Analysis on Task 17 Implementation

## Executive Summary

Task 20's WorkflowExecutor implementation fundamentally changes how Task 17 should approach workflow composition. The planner can now generate workflows that **reference other workflows as nodes** using `type: "workflow"`, enabling true compositional workflow design.

## Key Discoveries

### 1. The "workflow" Special Node Type

Task 20 introduced a special node type that doesn't appear in the registry:

```json
{
  "id": "run_fix_issue",
  "type": "workflow",  // Special type!
  "params": {
    "workflow_ref": "~/.pflow/workflows/fix-issue.json",
    "param_mapping": {
      "issue_number": "$selected_issue"
    },
    "output_mapping": {
      "pr_url": "fix_result_url"
    }
  }
}
```

### 2. Context Builder Already Shows Workflows

The context builder marks workflows with `(workflow)` suffix:
```markdown
## Available Workflows

### fix-issue (workflow)
Fetches a GitHub issue, analyzes it with AI, generates a fix
```

But doesn't explicitly document that these can be used with `type: "workflow"`.

### 3. Workflow Composition Architecture

This changes the planner's approach:

**Before Task 20**:
- Path A: Find complete workflow → return it unchanged
- Path B: Generate new workflow from scratch using only nodes

**After Task 20**:
- Path A: Find complete workflow → return it unchanged (no change)
- Path B: Generate new workflow that can **include other workflows as building blocks**

## Impact on Task 17 Design

### 1. ComponentBrowsingNode Enhancement

The ComponentBrowsingNode's ability to select workflows now has a concrete purpose:
- Selected workflows can be incorporated using `type: "workflow"`
- Enables modular composition: "fix issue AND notify team"

### 2. GeneratorNode Implications

The generator must now understand:
```python
# When LLM sees "fix-issue (workflow)" in context
# It can generate:
{
  "nodes": [
    {
      "id": "fix_issue_step",
      "type": "workflow",  # Use existing workflow!
      "params": {
        "workflow_ref": "~/.pflow/workflows/fix-issue.json",
        "param_mapping": {"issue_number": "$issue"}
      }
    },
    {
      "id": "notify",
      "type": "send-slack",
      "params": {"message": "Fixed: $fix_issue_step.pr_url"}
    }
  ]
}
```

### 3. Context Builder Gaps

**Gap 1: No Documentation of Special Type**
- Context shows workflows with `(workflow)` suffix
- But doesn't explain they can be used with `type: "workflow"`
- Planner prompts must explicitly teach this

**Gap 2: Workflow Reference Format**
- How should planner know the path to workflow files?
- Should it use workflow names or file paths?

**Gap 3: Original Gaps Still Exist**
- Still need structured workflow metadata access
- Still need `get_workflow_metadata()` for Path A

## Revised Context Builder Needs

### 1. Document the Special Node Type

Add to discovery context:
```markdown
## Special Node Types

### workflow
Execute another saved workflow as a sub-component.
Use `type: "workflow"` with workflow_ref parameter.
Example: {"type": "workflow", "params": {"workflow_ref": "~/.pflow/workflows/name.json"}}
```

### 2. Workflow Path Resolution

The planner needs to know:
- Workflow files are in `~/.pflow/workflows/`
- File naming convention: `{workflow-name}.json`
- Or provide full paths in workflow metadata

### 3. Enhanced Workflow Format

Show workflows with usage hint:
```markdown
### fix-issue (workflow)
Description: Fetches a GitHub issue and creates fix
Usage: {"type": "workflow", "params": {"workflow_ref": "~/.pflow/workflows/fix-issue.json"}}
```

## Critical Questions for Implementation

### Q1: Workflow Reference Format - ANSWERED
The system uses **file paths only** (no name resolution):
- Relative paths: `"./fix-issue.json"` (resolved from parent workflow location)
- Absolute paths: `"/full/path/to/workflow.json"`
- NOT workflow names: `"fix-issue"` is not supported
- Tilde expansion: Currently NOT supported (major gap!)

### Q2: Workflow Metadata Access
For Path B workflow composition, does the planner need:
- Just the name and description (current)
- Also inputs/outputs to plan data flow?
- Full IR to understand internals?

### Q3: Context Builder Enhancement Priority
Should we:
1. Add minimal methods for Path A (original plan)
2. Also enhance discovery format for workflow composition
3. Create separate "workflow composition guide" in context?

## Recommendations

### 1. Immediate Need (Unblock Path A)
Add these methods to context_builder.py:
```python
def get_workflow_metadata(workflow_name: str) -> Optional[dict]:
    """Get metadata for a specific workflow by name."""

def get_workflow_path(workflow_name: str) -> str:
    """Get the file path for a workflow by name."""
    return f"~/.pflow/workflows/{workflow_name}.json"
```

### 2. Enhanced Discovery Context
Update context builder to explicitly document the workflow node type:
- Add special node types section
- Show example usage for workflows
- Clarify parameter/output mapping

### 3. Planner Prompt Engineering
Teach the LLM about workflow composition:
```
When you see "workflow-name (workflow)" in the context, you can use it as a node:
{"type": "workflow", "params": {"workflow_ref": "~/.pflow/workflows/workflow-name.json"}}

This allows composing complex workflows from existing building blocks.
```

## Critical Design Mismatch Discovered

### File-Based vs Name-Based Workflow References

The WorkflowExecutor uses a **file-based** approach:
- References are file paths: `"./sub-workflow.json"`
- Relative paths resolve from parent workflow location
- No workflow name registry or resolution

But the planner operates in a **name-based** mental model:
- Discovers workflows by name: "fix-issue"
- Saves workflows by name
- Doesn't know final file locations

### The Fundamental Problem

When the planner generates a workflow, it doesn't know:
1. Where the workflow will be saved
2. Where referenced workflows are located
3. How to create valid relative paths

Example scenario:
```
User: "fix issue and notify team"
Planner discovers: "fix-issue" workflow exists
Planner wants to generate:
{
  "type": "workflow",
  "params": {
    "workflow_ref": "???"  // What path to use?
  }
}
```

### Implications for Task 17

This creates a **critical architectural tension**:
1. The planner thinks in workflow names
2. The runtime thinks in file paths
3. No component bridges this gap

## Possible Resolutions

### Resolution 1: Assume Standard Location
Planner assumes all workflows are in `~/.pflow/workflows/`:
```json
{
  "workflow_ref": "~/.pflow/workflows/fix-issue.json"
}
```
Requires: WorkflowExecutor to support tilde expansion

### Resolution 2: Add Name Resolution
Enhance WorkflowExecutor to resolve names:
```json
{
  "workflow_name": "fix-issue"  // New parameter
}
```
Requires: WorkflowExecutor changes

### Resolution 3: Use Inline IR
Planner loads workflow and inlines it:
```json
{
  "workflow_ir": { /* full workflow definition */ }
}
```
Downsides: Duplicates workflow content, loses reusability benefits

## Conclusion

Task 20 significantly enhances the planner's capabilities but reveals a fundamental design tension between name-based discovery and file-based execution. This requires:

1. **Original gaps still need filling** (structured workflow access)
2. **New documentation needs** (explain workflow node type)
3. **Path resolution strategy** (how to reference workflows)
4. **Architectural decision** on name vs file-based references

Without resolving the reference format issue, the planner cannot effectively use Task 20's workflow composition feature.
