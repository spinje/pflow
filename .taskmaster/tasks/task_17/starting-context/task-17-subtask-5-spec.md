# Feature: validation_refinement_system

## Objective

Validate generated workflows and extract metadata.

## Requirements

- Must create ValidatorNode that orchestrates validation checks
- Must enhance TemplateValidator to detect unused inputs
- Must create MetadataGenerationNode for metadata extraction
- Must validate node types exist in registry
- Must format errors for generator retry
- Must support up to 3 retry attempts
- Must operate only on workflow IR

## Scope

- Does not access discovered_params from ParameterDiscoveryNode
- Does not enforce linear workflow constraints
- Does not detect "should have been parameterized" patterns
- Does not validate semantic correctness of prompts
- Does not modify workflows

## Inputs

- `shared["generated_workflow"]`: dict - Complete workflow IR from GeneratorNode
- `shared["generation_attempts"]`: int - Number of generation attempts so far (1-indexed)
- `shared["planning_context"]`: str - Context used for generation (for MetadataGenerationNode)
- `shared["user_input"]`: str - Original user request (for metadata extraction)

## Outputs

Returns: Action strings for routing in planner flow

Side effects:
- `shared["validation_errors"]`: list[str] - Error messages for retry (when invalid)
- `shared["workflow_metadata"]`: dict - Extracted metadata (when valid)
- Does not modify generated_workflow

## Structured Formats

```json
{
  "validation_errors": [
    "Template variable $repo_name used but not defined in inputs field",
    "Node type 'github-list-issuez' not found in registry",
    "Declared input 'unused_param' never used as template variable"
  ],
  "workflow_metadata": {
    "suggested_name": "generate-changelog",
    "description": "Generate changelog from GitHub issues",
    "declared_inputs": ["repo_name", "limit"],
    "declared_outputs": ["changelog"]
  }
}
```

## State/Flow Changes

```
GeneratorNode -"validate"→ ValidatorNode -"metadata_generation"→ MetadataGenerationNode → ParameterMappingNode
                                         -"retry"→ GeneratorNode (if attempts < 3)
                                         -"failed"→ ResultPreparationNode (if attempts >= 3)
```

## Constraints

- Maximum 3 validation errors returned for retry
- Registry automatically scans subdirectories via rglob
- Error messages must be actionable string format for LLM

## Rules

1. ValidatorNode imports validate_ir from pflow.core
2. ValidatorNode imports ValidationError from pflow.core
3. ValidatorNode catches ValidationError and converts to string
4. ValidatorNode calls TemplateValidator.validate_workflow_templates()
5. ValidatorNode passes (workflow_ir, {}, Registry()) as parameters
6. ValidatorNode checks each node type exists in registry.get_nodes_metadata()
7. ValidatorNode returns "metadata_generation" if all checks pass
8. ValidatorNode returns "retry" if errors found and attempts < 3
9. ValidatorNode returns "failed" if generation_attempts >= 3
10. ValidatorNode stores top 3 errors in shared["validation_errors"]
11. TemplateValidator enhancement adds unused input detection
12. TemplateValidator returns list of string error messages
13. MetadataGenerationNode creates suggested_name from user_input
14. MetadataGenerationNode stores metadata in shared["workflow_metadata"]
15. MetadataGenerationNode returns empty string to continue flow

## Edge Cases

- `generated_workflow` missing → return "failed"
- `inputs` field empty dict → valid if no $variables require inputs
- Node type typo (e.g., "github-list-issuez") → return error message
- Template variable from node output → valid if node outputs that key
- Declared input never used → TemplateValidator returns error
- ValidationError has path and suggestion → include in error string
- Generation attempts >= 3 → return "failed" not "retry"

## Error Handling

- ValidationError from validate_ir() → catch and convert to string with path
- TemplateValidator returns list → add to validation_errors directly
- Registry() instantiation failure → return "failed" with error message
- Empty registry.get_nodes_metadata() → log warning but continue

## Non-Functional Criteria

- Validation completes within 100ms
- Error messages are LLM-parseable
- Registry scan is cached per validation session

## Examples

### Valid workflow
```python
shared = {
    "generated_workflow": {
        "ir_version": "0.1.0",
        "inputs": {
            "repo_name": {"type": "string", "required": True, "description": "Repository"},
            "limit": {"type": "integer", "required": False, "default": 50, "description": "Issue limit"}
        },
        "nodes": [
            {"id": "fetch", "type": "github-list-issues",
             "params": {"repo": "$repo_name", "limit": "$limit"}},
            {"id": "analyze", "type": "llm",
             "params": {"prompt": "Analyze $issues"}}
        ],
        "edges": [{"from": "fetch", "to": "analyze"}]
    },
    "generation_attempts": 1
}
# ValidatorNode returns: "metadata_generation"
# No validation_errors stored
```

### Invalid workflow - unused input
```python
shared = {
    "generated_workflow": {
        "ir_version": "0.1.0",
        "inputs": {
            "repo_name": {"type": "string", "required": True},
            "unused_param": {"type": "string", "required": False}
        },
        "nodes": [
            {"id": "n1", "type": "llm", "params": {"prompt": "Process $repo_name"}}
        ],
        "edges": []
    },
    "generation_attempts": 2
}
# ValidatorNode returns: "retry"
# shared["validation_errors"] = ["Declared input 'unused_param' never used as template variable"]
```

## Test Criteria

1. validate_ir() passes, templates valid, nodes exist → "metadata_generation"
2. ValidationError from validate_ir() → "retry" with error string
3. Unknown node type → "retry" with node type error
4. Unused declared input → "retry" with unused input error
5. Template from node output → validation succeeds
6. Template from undefined source → "retry" with resolution error
7. Generation attempts >= 3 → "failed" not "retry"
8. Empty inputs dict with no input templates → "metadata_generation"
9. Top 3 errors stored when >3 errors exist
10. MetadataGenerationNode extracts suggested_name and description
11. Registry.get_nodes_metadata() returns all node types
12. TemplateValidator.validate_workflow_templates() called correctly
13. Error messages are strings not exception objects
14. All Rules have corresponding test
15. All Edge Cases have corresponding test

## Notes (Why)

- Unused inputs validation prevents ParameterMappingNode from extracting unnecessary values
- Registry validation catches typos that would fail at runtime
- Top 3 errors limit prevents overwhelming LLM with feedback
- Separation of ValidatorNode and MetadataGenerationNode keeps concerns clean
- Template resolution from both inputs and outputs enables data flow
- "failed" vs "invalid" distinction controls retry behavior

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1, 2                       |
| 2      | 1, 4, 5, 6                 |
| 3      | 1, 3, 11                   |
| 4      | 1                          |
| 5      | 2, 3, 4, 6                 |
| 6      | 7                          |
| 7      | 9, 13                      |
| 8      | 5, 6                       |
| 9      | 4                          |
| 10     | 5                          |
| 11     | 10                         |
| 12     | 10                         |
| 13     | 10                         |
| 14     | 10                         |
| 15     | 10                         |

## Versioning & Evolution

- v1.0.0 — Initial spec for Task 17 Subtask 5

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes generator always includes `inputs` field (verified: FlowIR model has inputs with default empty dict)
- Assumes Registry() constructor succeeds with default path ~/.pflow/registry.json
- Unknown: exact algorithm for extracting suggested_name from user_input
- Unknown: whether MetadataGenerationNode should parse planning_context for description

### Conflicts & Resolutions

- Handoff emphasized "catching hardcoded values" but clarification revealed this is impossible without discovered_params access. Resolution: Focus on unused inputs validation instead.
- Handoff showed action strings "invalid"/"valid" but code inspection showed GeneratorNode expects "retry"/"metadata_generation"/"failed". Resolution: Use actual action strings from implementation.
- Documentation suggested validate_ir() might need explicit subdirectory scanning but code shows Registry uses rglob for automatic recursion. Resolution: Trust Registry's automatic scanning.

### Decision Log / Tradeoffs

- Chose to enhance TemplateValidator for unused inputs rather than implement in ValidatorNode for separation of concerns
- Chose "retry" vs "failed" based on generation_attempts to control retry loop
- Chose top 3 errors limit to avoid overwhelming generator with feedback
- Chose to pass empty dict for available_params to TemplateValidator since ValidatorNode doesn't have discovered_params

### Ripple Effects / Impact Map

- TemplateValidator enhancement affects all workflows using template validation
- ValidatorNode retry logic affects GeneratorNode's retry prompt handling
- Registry scanning approach affects test setup and performance
- Error format affects generator's ability to fix issues

### Residual Risks & Confidence

- Risk: Registry incomplete if directories not scanned properly. Mitigation: Explicit subdirectory scanning.
- Risk: Metadata extraction from planning_context may be fragile. Mitigation: Fallback to basic extraction.
- Risk: Generator may not fix errors even with clear messages. Mitigation: Bounded retries.
- Confidence: High for validation logic, Medium for metadata extraction

### Epistemic Audit (Checklist Answers)

1. Assumed generator includes inputs field, registry scanning returns all nodes
2. Wrong assumptions would cause validation failures or missing node type errors
3. Prioritized robustness (explicit checks) over elegance (trusting generator)
4. All Rules mapped to Tests, all Tests cover Rules or Edge Cases
5. Affects TemplateValidator (enhancement), GeneratorNode (retry), tests (registry setup)
6. Metadata extraction format uncertain; Confidence: High for validation, Medium for metadata