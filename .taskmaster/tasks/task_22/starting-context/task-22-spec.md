# Feature: named_workflow_execution

## Objective

Execute saved workflows by name with unified resolution.

## Requirements

- Must resolve workflows from saved registry
- Must resolve workflows from file paths
- Must support parameter passing
- Must validate parameters against workflow inputs
- Must provide discovery commands
- Must remove --file flag completely

## Scope

- Does not handle workflow saving
- Does not modify planner behavior
- Does not change node execution
- Does not implement workflow versioning
- Does not support workflow aliases

## Inputs

- workflow_identifier: str - First CLI argument (name, path, or name.json)
- parameters: tuple[str, ...] - Remaining CLI arguments as key=value pairs
- stdin_data: str | StdinData | None - Optional piped input (StdinData has text_data, binary_data, or temp_path fields)

## Outputs

Returns: Workflow execution result with exit code
Side effects:
- Executes resolved workflow
- Outputs workflow results to stdout
- Shows error messages to stderr
- Lists available workflows when requested

## Structured Formats

```json
{
  "resolution_order": [
    "file_path_with_indicators",
    "saved_workflow_exact",
    "saved_workflow_without_json",
    "not_found"
  ],
  "workflow_storage": {
    "path": "~/.pflow/workflows/",
    "format": "{name}.json",
    "wrapper": {
      "name": "string",
      "description": "string",
      "ir": "object",
      "created_at": "ISO8601",
      "updated_at": "ISO8601",
      "version": "string",
      "rich_metadata": "object|null"
    }
  },
  "parameter_parsing": {
    "function": "parse_workflow_params",
    "type_inference": "infer_type",
    "supported_types": ["boolean", "integer", "float", "json", "string"]
  },
  "validation": {
    "function": "prepare_inputs",
    "returns": ["errors", "defaults"],
    "error_fields": ["message", "path", "suggestion"]
  },
  "discovery_commands": [
    "pflow workflow list",
    "pflow workflow describe <name>"
  ]
}
```

## State/Flow Changes

- None

## Constraints

- workflow_identifier length ≤ 255 characters
- parameter key names must be valid Python identifiers
- file paths must be valid filesystem paths

## Rules

1. If workflow_identifier contains "/" then treat as file path
2. If workflow_identifier ends with ".json" then treat as potential file
3. If file path exists then load workflow IR from file
4. If WorkflowManager.exists(workflow_identifier) returns true then use WorkflowManager.load_ir()
5. If workflow_identifier ends with ".json" and WorkflowManager.exists(name[:-5]) then load without extension
6. If workflow not found then show error with substring-matched suggestions
7. Call parse_workflow_params(parameters) to get typed dictionary
8. Call infer_type() on each parameter value for type conversion
9. Call prepare_inputs() to validate against workflow inputs field
10. Apply defaults from prepare_inputs() for missing optional parameters
11. Call execute_json_workflow() with validated parameters
12. Output workflow results to stdout via safe_output()
13. Show ValidationError messages with path and suggestion fields
14. List command calls WorkflowManager.list_all() and formats output
15. Describe command loads workflow and displays inputs and outputs fields

## Edge Cases

- workflow_identifier is empty → show help message
- workflow_identifier has spaces → treat as natural language
- workflow_identifier is single word without params → check registry then planner
- file path does not exist → error with suggestions
- saved workflow not found → error with similar names using substring match
- required parameter missing → ValidationError with message and path
- parameter type invalid → infer_type() falls back to string
- no workflows saved → list_all() returns empty array
- workflow has no inputs field → execute without validation
- stdin data with named workflow → inject via _inject_stdin_data()

## Error Handling

- File not found → Show path error with suggestions
- Workflow not found → Show similar workflow names
- Missing required params → Show parameter requirements
- Invalid parameter type → Show type conversion error
- Validation failure → Show validation details

## Non-Functional Criteria

- Resolution completes in < 100ms
- Error messages include actionable guidance
- Discovery commands complete in < 500ms

## Examples

```bash
# Saved workflow
pflow analyze-code → executes saved workflow

# With .json extension
pflow analyze-code.json → strips .json, executes saved

# Local file
pflow ./workflow.json → loads and executes file

# With parameters
pflow analyze-code input=main.py verbose=true → executes with params

# Discovery
pflow workflow list → shows all workflows
pflow workflow describe analyze-code → shows interface
```

## Test Criteria

1. workflow_identifier with "/" loads from file path
2. workflow_identifier with ".json" checks file then strips extension
3. Existing file path loads workflow from file
4. Exact name match loads from registry
5. Name without .json loads from registry after stripping
6. Non-existent workflow shows error with suggestions
7. key=value arguments parsed as parameters
8. String "true" converts to boolean True
9. String "5" converts to integer 5
10. Required parameters validated and error if missing
11. Optional parameters use defaults when not provided
12. Workflow executes with validated parameters
13. Results output to stdout
14. Errors show user-friendly messages
15. List command displays all workflows
16. Describe command shows inputs and outputs
17. Empty identifier shows help
18. Identifier with spaces goes to planner
19. Single word checks registry before planner
20. Missing file shows path error
21. Missing saved workflow suggests similar names
22. Missing required param shows requirements
23. Invalid type shows conversion error
24. No saved workflows shows empty guidance
25. Workflow without inputs executes successfully
26. Stdin data available in shared storage

## Notes (Why)

- Removing --file flag simplifies user mental model
- Unified resolution eliminates code duplication
- Discovery commands enable self-service workflow exploration
- Type conversion enables natural parameter passing
- User-friendly errors reduce support burden

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 2                          |
| 3      | 3                          |
| 4      | 4                          |
| 5      | 5                          |
| 6      | 6, 21                      |
| 7      | 7                          |
| 8      | 8, 9                       |
| 9      | 10, 22                     |
| 10     | 11                         |
| 11     | 12                         |
| 12     | 13                         |
| 13     | 14, 20, 21, 22, 23        |
| 14     | 15, 24                     |
| 15     | 16                         |

## Versioning & Evolution

- v1.0.0 — Initial spec for unified workflow execution

## Epistemic Appendix

### Assumptions & Unknowns

- None (all functions and methods verified to exist with exact signatures)

### Conflicts & Resolutions

- Original task mentions lockfile validation → Resolution: Removed as not in current implementation
- Task ID discrepancy (22 vs 43 in file) → Resolution: Use 22 as authoritative from context

### Decision Log / Tradeoffs

- Chose complete removal of --file over deprecation for maximum simplification
- Chose file path precedence over saved workflows to avoid ambiguity
- Chose simple substring matching (existing pattern) over adding fuzzy matching dependency
- Chose to use existing prepare_inputs() validation over custom implementation
- Chose to reuse infer_type() for parameter conversion over new type system

### Ripple Effects / Impact Map

- Breaks existing scripts using --file flag
- Affects main.py routing logic significantly (removes get_input_source, process_file_workflow, _determine_workflow_source, _get_file_execution_params)
- Requires new src/pflow/cli/workflow.py command file with Click group
- Impacts main_wrapper.py routing (add elif block for "workflow" command)
- Removes ~200 lines of code from main.py

### Residual Risks & Confidence

- Risk: Users confused by removal of --file flag; Mitigation: Clear error messages
- Risk: Ambiguous workflow names vs files; Mitigation: Clear precedence rules
- Confidence: High (based on extensive planning and investigation)

### Epistemic Audit (Checklist Answers)

1. No assumptions made - all functions verified via codebase search
2. Nothing would break as all dependencies confirmed to exist
3. Prioritized simplicity over backward compatibility
4. All rules have corresponding tests
5. Major impact on CLI routing and user scripts
6. No remaining uncertainty after verification; Confidence: Very High