# The Missing Piece: Workflow Input Declaration

Currently, the JSON IR schema has NO mechanism for declaring workflow-level inputs. The workflow storage format shows an inputs
field, but this is metadata stored alongside the IR, not part of the IR itself.

## Current State:

1. Nodes use template variables in params: {"params": {"issue": "$issue_number"}}
2. Workflows have inputs listed in metadata: "inputs": ["issue_number"]
3. But the IR itself has no way to declare "this workflow expects these parameters"

## The Problem for Subworkflows:

If workflows can use other workflows as nodes, how do we:
1. Know what parameters the subworkflow needs?
2. Pass values to those parameters?
3. Validate that all required inputs are provided?

## Two Potential Solutions:

### Option A: Workflow Node with Params Mapping

```
{
  "id": "fix-step",
  "type": "workflow:fix-issue",  // Special prefix for workflows?
  "params": {
    "issue_number": "$current_issue",  // Map parent's variable to sub's input
    "repo": "myrepo"                   // Static value
  }
}
```

### Option B: Add Inputs Declaration to IR Schema

```
  {
    "ir_version": "0.1.0",
    "inputs": [  // NEW field in IR
      {"name": "issue_number", "type": "string", "required": true},
      {"name": "repo", "type": "string", "default": "pflow"}
    ],
    "nodes": [...],
    "edges": [...]
  }
```

## My Assessment:

This is a critical ambiguity that affects:
- How the planner generates workflows that use other workflows
- How validation works for subworkflows
- How parameters flow from parent to child workflows
- The entire "workflows as building blocks" concept

Without resolving this, the planner cannot properly implement workflow composition. This needs a design decision before Task 17
implementation can be complete.







---
