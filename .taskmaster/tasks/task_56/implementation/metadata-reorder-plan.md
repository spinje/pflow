# Implementation Plan: Move Metadata Generation After Runtime Validation

## Problem Statement
MetadataGenerationNode is currently called BEFORE RuntimeValidationNode, causing it to be executed multiple times during runtime validation retries (up to 4 times total: 1 initial + 3 retries).

## Current Flow
```
ValidatorNode --("metadata_generation")--> MetadataGenerationNode --("")--> RuntimeValidationNode
                                                                               |
                                                                               v
                                                        ("runtime_fix")--------+
                                                               |               |
                                                               v               |
                                                        WorkflowGeneratorNode <-+
                                                               |
                                                               v (retry loop back to ValidatorNode)
```

## Proposed Flow
```
ValidatorNode --("runtime_validation")--> RuntimeValidationNode --("")--> MetadataGenerationNode --("")--> ParameterPreparationNode
                                                    |
                                                    v
                            ("runtime_fix")--------+
                                                    |
                                                    v
                             WorkflowGeneratorNode <-+
```

## Verification Complete ✅

1. **RuntimeValidationNode does NOT use metadata** - Verified
   - Only reads: `generated_workflow`, `execution_params`/`extracted_params`, `runtime_attempts`

2. **MetadataGenerationNode does NOT depend on RuntimeValidationNode** - Verified
   - Reads: `generated_workflow`, `user_input`, `planning_context`, `discovered_params`, `extracted_params`
   - All these are available before RuntimeValidationNode runs

3. **No circular dependencies** - Verified
   - The reordering creates no circular dependencies

## Implementation Steps

### 1. Update Flow Wiring (flow.py)
- Change line where ValidatorNode connects to MetadataGenerationNode
- Update to connect ValidatorNode to RuntimeValidationNode instead
- Connect RuntimeValidationNode success ("") to MetadataGenerationNode
- Keep RuntimeValidationNode error routes unchanged

### 2. Update Node Action Strings (nodes.py)
- **ValidatorNode.post()**: Change success return from `"metadata_generation"` to `"runtime_validation"`
- **RuntimeValidationNode.post()**: Keep default return as `""` (unchanged)
- **MetadataGenerationNode.post()**: Keep return as `""` (unchanged)

### 3. Update Flow Connections (flow.py)
```python
# REMOVE:
validator - "metadata_generation" >> metadata_generation
metadata_generation >> runtime_validation

# ADD:
validator - "runtime_validation" >> runtime_validation
runtime_validation >> metadata_generation
metadata_generation >> parameter_preparation
```

### 4. Fix Tests
Tests that will need updates:
- **test_flow_structure.py**: Update expected flow connections
- **test_planner_integration.py**: May need mock response reordering
- Any test that checks the specific flow path

## Benefits
1. **Efficiency**: Metadata generated only once (not 1-4 times)
2. **Logic**: Metadata describes the final, validated workflow
3. **Performance**: Faster retries, fewer LLM calls
4. **Simplicity**: Cleaner flow without redundant operations

## Risks & Mitigations
- **Risk**: Tests may break
  - **Mitigation**: Identified affected tests, will update systematically

- **Risk**: Trace files will look different
  - **Mitigation**: This is expected and beneficial (cleaner traces)

## No Breaking Changes
- No API changes
- No user-visible changes (except faster performance)
- Trace files will be cleaner but still valid