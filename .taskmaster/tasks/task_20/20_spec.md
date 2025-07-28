# Feature: workflow_node

## Objective

Enable workflows to execute other workflows as sub-components.

## Requirements

- Must inherit from BaseNode
- Must compile sub-workflows at runtime
- Must provide storage isolation between parent and child
- Must detect circular dependencies
- Must enforce maximum nesting depth
- Must preserve error context through nesting levels
- Must resolve template parameters for child workflows

## Scope

- Does not implement workflow registry
- Does not support async execution
- Does not cache compiled workflows
- Does not provide workflow versioning
- Does not implement timeouts
- Does not support remote workflow loading

## Inputs

- workflow_ref: Optional[str] - Path to workflow JSON file
- workflow_ir: Optional[Dict[str, Any]] - Inline workflow definition
- param_mapping: Dict[str, Any] - Maps parent values to child parameters
- output_mapping: Dict[str, str] - Maps child outputs to parent keys
- storage_mode: Literal["mapped", "isolated", "scoped", "shared"] - Storage isolation strategy
- max_depth: int - Maximum nesting depth (default: 10)
- error_action: str - Action to return on error (default: "error")

## Outputs

Returns: str - Action string for flow control ("default" or error_action)

Side effects:
- Modifies parent shared storage based on output_mapping
- Sets error key in shared storage on failure
- Updates execution tracking keys in shared storage

## Structured Formats

```json
{
  "node_type": "workflow",
  "params_schema": {
    "workflow_ref": {"type": "string", "pattern": "^[^\\0]*$"},
    "workflow_ir": {"type": "object", "properties": {"nodes": {"type": "array"}}},
    "param_mapping": {"type": "object"},
    "output_mapping": {"type": "object", "patternProperties": {".*": {"type": "string"}}},
    "storage_mode": {"type": "string", "enum": ["mapped", "isolated", "scoped", "shared"]},
    "max_depth": {"type": "integer", "minimum": 1, "maximum": 100},
    "error_action": {"type": "string"}
  },
  "reserved_keys": {
    "prefix": "_pflow_",
    "keys": ["_pflow_depth", "_pflow_stack", "_pflow_workflow_file"]
  }
}
```

## State/Flow Changes

- prep() → Updates _pflow_stack with current workflow path
- prep() → Increments _pflow_depth
- exec() → Creates isolated child storage
- exec() → Compiles and runs sub-workflow
- post() → Merges child outputs to parent storage

## Constraints

- Either workflow_ref or workflow_ir must be provided (not both)
- Maximum nesting depth is configurable (default: 10)
- Reserved keys use _pflow_ prefix

## Rules

1. If neither workflow_ref nor workflow_ir provided then raise ValueError
2. If both workflow_ref and workflow_ir provided then raise ValueError
3. If current depth ≥ max_depth then raise RecursionError
4. If workflow_ref in execution stack then raise ValueError with cycle
5. If workflow file not found then raise FileNotFoundError
6. If workflow JSON invalid then raise ValueError
7. If param_mapping contains template then resolve using TemplateResolver
8. Template resolution uses parent's shared storage as context
9. If storage_mode is "mapped" then create new dict with mapped params only
10. If storage_mode is "isolated" then create empty dict
11. If storage_mode is "scoped" then filter parent keys by prefix
12. If storage_mode is "shared" then use parent storage reference
13. If child workflow compilation fails then return error result
14. If child workflow execution fails then return error result
15. If execution succeeds then apply output_mapping to parent storage
16. If child returns string action then return that action
17. If child returns non-string then return "default"

## Edge Cases

- workflow_ref is relative path → resolve from parent workflow directory
- param_mapping references non-existent key → template resolves to empty string
- output_mapping references non-existent child key → skip that mapping
- storage_mode invalid → raise ValueError
- circular dependency through multiple levels → detect via stack
- malformed workflow IR → compilation error wrapped with context
- child workflow modifies reserved keys → preserved in child only
- concurrent execution of same workflow → each gets fresh instance

## Error Handling

- FileNotFoundError → wrap with workflow path context
- JSONDecodeError → wrap as ValueError with file path
- PermissionError → wrap as IOError with context
- CompilationError → preserve original error in result
- Runtime exceptions → catch and return error result

## Examples

### Basic nested workflow
```json
{
  "id": "process_data",
  "type": "workflow",
  "params": {
    "workflow_ref": "analyzers/sentiment.json",
    "param_mapping": {
      "text": "$input_text"
    },
    "output_mapping": {
      "sentiment_score": "analysis_result"
    }
  }
}
```

### Inline workflow with storage isolation
```json
{
  "id": "isolated_task",
  "type": "workflow",
  "params": {
    "workflow_ir": {
      "nodes": [{
        "id": "task",
        "type": "some_node",
        "params": {}
      }]
    },
    "storage_mode": "isolated"
  }
}
```

## Test Criteria

1. workflow_ref only provided → loads and executes workflow
2. workflow_ir only provided → executes inline workflow
3. neither parameter provided → raises ValueError
4. both parameters provided → raises ValueError
5. depth at max_depth → raises RecursionError
6. workflow in execution stack → raises ValueError with cycle
7. workflow file missing → raises FileNotFoundError
8. workflow JSON malformed → raises ValueError
9. param_mapping with template → resolves correctly
10. storage_mode "mapped" → child sees only mapped params
11. storage_mode "isolated" → child sees empty storage
12. storage_mode "scoped" → child sees filtered storage
13. storage_mode "shared" → child uses parent storage
14. child compilation error → returns error result
15. child execution error → returns error result
16. successful execution → applies output mapping
17. child returns "custom_action" → returns "custom_action"
18. child returns None → returns "default"
19. relative workflow_ref → resolves from parent directory
20. missing param in mapping → handles gracefully
21. missing output key → skips mapping
22. invalid storage_mode → raises ValueError
23. multi-level circular dependency → detects cycle
24. malformed child IR → wraps error with context
25. reserved key modification → isolated to child
26. concurrent execution → independent instances

## Notes (Why)

- Storage isolation prevents unintended data pollution between workflows
- Circular dependency detection prevents infinite recursion
- Template resolution enables dynamic parameter passing
- Reserved key prefix prevents collision with user data
- Execution stack tracking enables meaningful error messages

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 3                          |
| 2      | 4                          |
| 3      | 5                          |
| 4      | 6, 23                      |
| 5      | 7                          |
| 6      | 8, 24                      |
| 7      | 9, 20                      |
| 8      | 9                          |
| 9      | 10                         |
| 10     | 11                         |
| 11     | 12                         |
| 12     | 13                         |
| 13     | 14                         |
| 14     | 15                         |
| 15     | 16, 21                     |
| 16     | 17                         |
| 17     | 18                         |

## Versioning & Evolution

- v1.0.0 - Initial WorkflowNode implementation with basic features
- Future v2.0.0 - Add workflow caching, async support, registry integration

## Epistemic Appendix

### Assumptions & Unknowns

- Registry is passed to nodes during compilation via node.set_params()
- WorkflowNode accesses it as self.params.get("__registry__")
- Assumes compile_ir_to_flow is importable without circular dependencies
- Unknown: Optimal default for max_depth (chose 10 conservatively)

### Conflicts & Resolutions

- Original design suggested using native Flow-as-Node → Resolution: WorkflowNode as execution wrapper provides needed isolation
- Registry stores Python module metadata → Resolution: Load workflow files at runtime
- No reserved key namespace → Resolution: Establish _pflow_ prefix convention

### Decision Log / Tradeoffs

- Chose runtime compilation over compile-time inclusion for flexibility
- Chose explicit parameter mapping over automatic inheritance for clarity
- Chose "mapped" as default storage mode for safety over convenience

### Ripple Effects / Impact Map

- No changes to existing node discovery or registry
- No changes to compiler beyond normal node handling
- Adds new node type that other workflows can use
- Establishes reserved key convention that future features should respect

### Residual Risks & Confidence

- Risk: No timeout mechanism for long-running child workflows. Mitigation: Future enhancement. Confidence: High
- Overall confidence in design: High
- Overall confidence in implementation feasibility: High

### Epistemic Audit (Checklist Answers)

1. Registry access mechanism now clearly specified
2. Break if wrong: Child workflow compilation would fail without registry access
3. Prioritized robustness (explicit mappings) over elegance (automatic inheritance)
4. All rules mapped to tests: Yes (see Compliance Matrix)
5. Main ripple: Establishes _pflow_ reserved namespace
6. Remaining uncertainty: Performance at scale; Confidence: Medium-High
