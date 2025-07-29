# Task 21 Handoff Memo: Workflow Interface Declaration

## Why I Was Looking at Task 21

I was deep in Task 17 (Natural Language Planner) implementation analysis when I discovered that the planner needs to understand workflow interfaces to compose them effectively. This led me to investigate how workflows declare their inputs/outputs, which brought me to Task 21.

## ✅ Update: Output Declarations Added!

Based on earlier analysis, Task 21 has been expanded to include **both input and output** declarations. This critical enhancement enables proper workflow composition and validation.

What Task 21 now provides:
- Workflows can declare both inputs AND outputs in their IR
- Complete interface parity with nodes
- Enables static validation of workflow composition

## The Three-Way Split Problem

I discovered workflow interface information is scattered in three places:

1. **Metadata level** (current):
   ```json
   {
     "inputs": ["issue_number"],      // Simple strings
     "outputs": ["pr_url"],           // No validation!
     "ir": {...}
   }
   ```

2. **IR level** (Task 21 now includes):
   ```json
   {
     "ir": {
       "inputs": {                    // Detailed input declarations
         "issue_number": {"required": true, "type": "string"}
       },
       "outputs": {                   // Output declarations now included!
         "pr_url": {"type": "string", "description": "Created PR URL"}
       }
     }
   }
   ```

3. **Runtime reality**: What actually happens (no validation against declarations)

## Critical Architectural Tensions

### 1. The User's Clear Vision
The user explicitly stated that:
- **Contract** (inputs/outputs) belongs in the IR
- **Metadata** (timestamps, costs, execution info) is system-generated

This aligns perfectly with expanding Task 21 to include outputs.

### 2. Name vs Path Reference Hell
- Planner (Task 17) discovers workflows by name: "fix-issue"
- WorkflowExecutor (Task 20) loads by path: "./fix-issue.json"
- No component bridges this gap!
- WorkflowExecutor doesn't even expand `~` in paths

### 3. No Workflow Saving Exists
While investigating, I found that workflow saving isn't implemented anywhere. The planner docs mention it, but the code doesn't exist. This connects to Task 24 (WorkflowManager).

## Why Output Declarations Were Essential

The addition of output declarations enables:
```python
# Workflow A outputs: {"summary": {"type": "string"}}
# Workflow B inputs: {"text_input": {"type": "string"}}
# Can A feed into B? YES - we can validate this statically!
```

The planner can now:
- Know what workflows produce
- Validate if outputs match next workflow's inputs
- Verify template paths like `$workflow_result.field` are valid

## Connected Systems You Must Consider

### Task 17 (Natural Language Planner)
- Needs complete workflow interfaces for composition
- Can't validate workflow chains without outputs
- My analysis in `/scratchpads/task-17-implementation/` shows this clearly

### Task 20 (WorkflowExecutor)
- Uses `output_mapping` to map child outputs to parent
- But can't validate if those outputs actually exist!
- See `/scratchpads/task-17-implementation/task-20-impact-analysis.md`

### Task 24 (WorkflowManager)
- Will handle workflow lifecycle (save/load/resolve)
- Should probably own the name→path resolution
- Critical for Task 21's integration

## Files and Code to Review

1. **Current Loading Pattern**:
   - `/src/pflow/planning/context_builder.py` - `_load_saved_workflows()` (lines 158-213)
   - Shows the current metadata structure with inputs/outputs as strings

2. **Template Validation Gap**:
   - `/src/pflow/runtime/template_validator.py`
   - Only validates node outputs, not workflow outputs
   - Can't handle `$workflow_result.field` paths

3. **My Analysis Documents**:
   - `/scratchpads/task-17-implementation/workflow-outputs-gap-analysis.md`
   - `/scratchpads/task-17-implementation/critical-user-decisions/workflow-output-declarations.md`

## Warnings and Gotchas

1. **Don't just add inputs** - The system needs complete interfaces
2. **Metadata vs IR confusion** - There's already confusion about where things belong
3. **Validation complexity** - How do you validate that declared outputs are actually produced?
4. **Backward compatibility** - Existing workflows have metadata-level outputs

## Implementation Considerations

1. ✅ Task renamed to "Workflow Input/Output Declaration"
2. Output validation approach (from spec): Check declared outputs against union of all node outputs using registry interface data
3. Output detail level: Basic types for MVP, structure can be enhanced later
4. WorkflowManager integration: Will use these declarations for workflow compatibility validation

## The Current Implementation

Task 21 now implements complete workflow interfaces:

```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "issue_number": {
      "description": "GitHub issue to fix",
      "required": true,
      "type": "string"
    }
  },
  "outputs": {
    "pr_url": {
      "description": "Created PR URL",
      "type": "string"
    },
    "pr_number": {
      "description": "Created PR number",
      "type": "number"
    }
  },
  "nodes": [...]
}
```

This enables:
- Static validation of workflow composition
- Template path validation (`$result.pr_url`)
- Discovery by outputs ("find workflows that produce pr_url")
- Complete contracts for reuse

## Final Implementation Status

✅ The complete interface (inputs AND outputs) is now properly placed in the IR where it belongs, following the principle that:
- **Contract** (inputs/outputs) = IR (source of truth)
- **Metadata** (timestamps, costs) = system-generated information

This enables:
- Static validation of workflow composition
- Template path validation (`$result.pr_url`)
- Discovery by inputs OR outputs
- Complete contracts for workflow reuse

---

**Current Status**: Task 21 specification has been updated to include both input and output declarations. The implementation should follow the patterns in the 21_spec.md file, which provides comprehensive validation rules and test criteria for both inputs and outputs.
