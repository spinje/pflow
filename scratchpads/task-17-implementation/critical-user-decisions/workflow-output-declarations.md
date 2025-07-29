# Workflow Output Declarations - Importance 5/5

Task 21 only addresses workflow input declarations, but workflows also need output declarations for proper composition and validation.

## Context:

### Current Asymmetry
- **Nodes**: Have both inputs AND outputs in registry interface
- **Workflows**: Will have inputs (Task 21) but NOT outputs in IR

### Why Outputs Matter
Without output declarations:
1. Can't validate workflow composition (do outputs match next inputs?)
2. Can't validate template paths like `$workflow_result.field`
3. Can't discover workflows by what they produce
4. Half a contract - incomplete interface definition

### Example Problem
```json
// Workflow A (with Task 21):
{
  "inputs": {"text": {"required": true}},
  "nodes": [...] // What does it output? Unknown!
}

// Workflow B wants to use A's output:
{
  "type": "workflow",
  "params": {
    "workflow_name": "workflow-a"
  }
}
// Later: {"params": {"input": "$workflow_a_result.summary"}}
// Will this work? Can't validate without output declaration!
```

## Options:

- [x] **Option A: Expand Task 21 to include input AND output declarations**
  ```json
  {
    "inputs": {...},
    "outputs": {
      "summary": {"type": "string", "description": "Text summary"},
      "word_count": {"type": "number", "description": "Word count"}
    },
    "nodes": [...]
  }
  ```
  - Pros: Complete interface, enables composition, single coherent change
  - Cons: Larger scope for Task 21

- [ ] **Option B: Keep Task 21 inputs-only, create Task 21b for outputs**
  - Pros: Smaller incremental changes
  - Cons: Leaves system in incomplete state, duplicated effort

- [ ] **Option C: Use metadata for outputs (current approach)**
  - Pros: No IR schema changes needed
  - Cons: Can't validate, not part of workflow contract, inconsistent

- [ ] **Option D: Infer outputs from workflow execution**
  - Pros: No declarations needed
  - Cons: Can't know outputs without running, breaks static analysis

**Recommendation**: Option A - Expand Task 21 to include both input and output declarations. This creates complete workflow interfaces that enable:
- Static validation of workflow composition
- Discovery by inputs OR outputs
- Template path validation for workflow results
- Clear contracts for workflow reuse

## Implementation Impact:

With complete interfaces:
```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "issue_number": {"required": true, "type": "string"}
  },
  "outputs": {
    "pr_url": {"type": "string"},
    "pr_number": {"type": "number"}
  },
  "nodes": [...]
}
```

The planner can:
1. Validate workflow composition statically
2. Show users what workflows produce
3. Enable `$workflow_result.pr_url` validation
4. Match workflow outputs to inputs automatically

## Critical for Task 17:

Without output declarations, the planner can't:
- Know what data workflows produce
- Validate composition before execution
- Suggest compatible workflows
- Generate valid template paths

This is essential for the "Plan Once, Run Forever" philosophy - workflows need complete interfaces to be truly reusable components.
