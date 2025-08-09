# Task 17 Subtask 6: Complete Flow Path Resolution

## Overview
This document resolves all ambiguities about the complete flow paths in Task 17's Natural Language Planner System. After thorough investigation of the codebase and documentation, the complete flow architecture is now clear and unambiguous.

## The Complete Flow Architecture

### All Convergence Points
All nodes converge to ResultPreparationNode through 3 possible entry points:

```
1. SUCCESS PATH (both Path A and Path B):
   ParameterPreparationNode --("")--> ResultPreparationNode

2. MISSING PARAMS PATH:
   ParameterMappingNode --("params_incomplete")--> ResultPreparationNode

3. GENERATION FAILURE PATH:
   ValidatorNode --("failed")--> ResultPreparationNode
```

## Complete Node Action Strings

Based on examination of `/Users/andfal/projects/pflow/src/pflow/planning/nodes.py`:

| Node | Action Strings | Description |
|------|---------------|-------------|
| WorkflowDiscoveryNode | `"found_existing"` or `"not_found"` | Routes to Path A or Path B |
| ComponentBrowsingNode | `"generate"` | Always continues to generation |
| ParameterDiscoveryNode | `""` (empty) | Simple continuation |
| ParameterMappingNode | `"params_complete"` or `"params_incomplete"` | Verification gate |
| ParameterPreparationNode | `""` (empty) | Simple continuation |
| WorkflowGeneratorNode | `"validate"` | Always goes to validation |
| ValidatorNode | `"metadata_generation"`, `"retry"`, or `"failed"` | Three-way routing |
| MetadataGenerationNode | `""` (empty) | Simple continuation |
| ResultPreparationNode | `None` or `""` | Ends the flow |

## Complete Path Flows

### PATH A - Workflow Reuse (Fast Path)
```
START → WorkflowDiscoveryNode
         ├─("found_existing")→ ParameterMappingNode
         │                      ├─("params_complete")→ ParameterPreparationNode
         │                      │                       └─("")→ ResultPreparationNode → END
         │                      └─("params_incomplete")→ ResultPreparationNode → END
```

**Key Points:**
- Fastest path when existing workflow matches user intent
- Skips generation, validation, and metadata creation
- Still validates parameter availability

### PATH B - Workflow Generation
```
START → WorkflowDiscoveryNode
         └─("not_found")→ ComponentBrowsingNode
                           └─("generate")→ ParameterDiscoveryNode
                                           └─("")→ WorkflowGeneratorNode
                                                   └─("validate")→ ValidatorNode
                                                                    ├─("retry")→ WorkflowGeneratorNode [LOOP]
                                                                    ├─("failed")→ ResultPreparationNode → END
                                                                    └─("metadata_generation")→ MetadataGenerationNode
                                                                                                 └─("")→ ParameterMappingNode
                                                                                                         ├─("params_complete")→ ParameterPreparationNode
                                                                                                         │                       └─("")→ ResultPreparationNode → END
                                                                                                         └─("params_incomplete")→ ResultPreparationNode → END
```

**Key Points:**
- Full generation pipeline when no existing workflow matches
- Includes validation with up to 3 retry attempts
- Generates rich metadata for future discovery
- Converges with Path A at ParameterMappingNode

## ResultPreparationNode Requirements

ResultPreparationNode is the ONLY node that needs to be created in Subtask 6.

### Three Entry Scenarios

1. **Success Entry** (from ParameterPreparationNode)
   - Has `execution_params` ready for CLI
   - Has `workflow_ir` (either found or generated)
   - Has `workflow_metadata` if generated

2. **Missing Parameters Entry** (from ParameterMappingNode)
   - Has `missing_params` list
   - Has `workflow_ir` but cannot execute
   - CLI should prompt user for missing params

3. **Generation Failure Entry** (from ValidatorNode)
   - Has `validation_errors` from last attempt
   - No valid `workflow_ir`
   - Generation failed after 3 attempts

### Output Format
ResultPreparationNode must package output as `planner_output`:

```python
shared["planner_output"] = {
    "success": bool,                    # True if workflow ready to execute
    "workflow_ir": dict or None,        # The workflow IR (found or generated)
    "execution_params": dict or None,   # Parameters ready for execution
    "missing_params": list or None,     # List of missing required parameters
    "error": str or None,               # Error message if generation failed
    "workflow_metadata": dict or None,  # Metadata for saving workflow
    "suggested_name": str or None       # Suggested workflow name for saving
}
```

### Return Value
ResultPreparationNode should return `None` or `""` to end the flow.

## Two-Stage Convergence Architecture

The planner implements a sophisticated two-stage convergence:

### Stage 1: Path Convergence at ParameterMappingNode
- Path A arrives directly from WorkflowDiscoveryNode
- Path B arrives after generation, validation, and metadata creation
- Both paths have a workflow IR at this point

### Stage 2: Final Convergence at ResultPreparationNode
- All success paths arrive from ParameterPreparationNode
- Missing parameter paths arrive from ParameterMappingNode
- Generation failure path arrives from ValidatorNode
- All paths end here with packaged output for CLI

## Key Implementation Notes

### Empty String Routing
When a node returns `""` (empty string), it continues to the next node in a simple linear fashion. This must be explicitly wired in the flow:
```python
node1 >> node2  # Used when node1 returns ""
```

### Conditional Routing
Named action strings enable conditional branching:
```python
node1 - "action_name" >> node2  # Only follows if node1 returns "action_name"
```

### The Retry Loop
The retry loop between ValidatorNode and WorkflowGeneratorNode:
- Is correctly implemented with attempt counting
- Will work in production
- Should NOT be integration tested due to LLM non-determinism
- Test action strings only, not actual loop execution

## Testing Strategy for Subtask 6

1. **Test node wiring**: Verify all edges are defined correctly
2. **Test action routing**: Verify nodes return correct action strings
3. **Test ResultPreparationNode**: Unit test all three entry scenarios
4. **NO integration tests**: Don't test actual flow execution with loops
5. **Document limitations**: Clearly note that retry loop testing is limited

## Summary

All flow ambiguities are now resolved:
- ✅ Complete flow paths mapped
- ✅ All action strings documented
- ✅ ResultPreparationNode requirements defined
- ✅ Entry/exit points identified
- ✅ Convergence architecture understood
- ✅ Loop behavior clarified (works but test carefully)

The planner implements a sophisticated two-path system where workflows are either reused (Path A) or generated fresh (Path B), with intelligent convergence at parameter mapping and final result preparation stages.