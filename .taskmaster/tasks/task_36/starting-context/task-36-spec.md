# Feature: update_context_builder_namespacing

## Objective

Fix misleading node presentation in context builder for namespaced environments.

## Requirements

- Must have automatic namespacing enabled (Task 9 complete)
- Must have context builder with node formatting functions
- Must have test infrastructure for context builder
- Must maintain backward compatibility with planner

## Scope

- Does not modify node implementations
- Does not change IR schema structure
- Does not alter compiler logic
- Does not modify workflow execution
- Does not update planner prompts

## Inputs

- registry_metadata: dict[str, dict[str, Any]] - Node metadata from registry
- selected_node_ids: list[str] - List of node types to include
- selected_workflow_names: list[str] - List of workflows to include

## Outputs

Returns: str - Formatted markdown context for LLM planner with:
- All parameters shown in single "Parameters" section
- Output access patterns with namespacing syntax
- Concrete JSON usage examples for every node
- No misleading "Parameters: none" messages

## Structured Formats

```json
{
  "node_format": {
    "sections": ["title", "description", "parameters", "outputs", "example"],
    "parameters_header": "**Parameters** (all go in params field):",
    "outputs_header": "**Outputs** (access as ${node_id.output_key}):",
    "example_header": "**Example usage**:"
  },
  "parameter_format": "- `{key}: {type}` - {description} {default_info}",
  "example_structure": {
    "id": "string",
    "type": "string",
    "params": "object"
  }
}
```

## State/Flow Changes

- None

## Constraints

- Changes limited to src/pflow/planning/context_builder.py
- Must preserve all existing node metadata
- Output size must remain under 200KB limit
- Performance impact must be negligible

## Rules

1. Replace "Inputs" section heading with "Parameters" in node formatting
2. Show all parameters in single Parameters section regardless of exclusive status
3. Add clarification text "(all go in params field)" to Parameters header
4. Include output access pattern "(access as ${node_id.output_key})" in Outputs header
5. Generate JSON usage example for every node
6. Use realistic template variable values in examples not placeholder "${key}"
7. Remove _format_exclusive_parameters function logic
8. Remove _format_template_variables function logic
9. Update _format_node_section_enhanced to use new formatting functions
10. Create _format_all_parameters function to show all parameters
11. Create _format_outputs_with_access function for output formatting
12. Create _format_usage_example function for JSON examples
13. Preserve complex structure display for nested types
14. Update test assertions in test_context_builder_phases.py
15. Maintain consistent format across all node types

## Edge Cases

- Node with no parameters → Show "**Parameters**: none"
- Node with only exclusive params → Show all in Parameters section
- Node with complex nested structure → Preserve JSON structure display
- Node with no outputs → Show "**Outputs**: none"
- Parameter with no description → Show key and type only
- Optional parameter → Add "(optional)" to description
- Parameter with default value → Add "(default: value)" to description

## Error Handling

- Invalid node metadata → Skip node with warning log
- Missing interface data → Raise ValueError with clear message
- Circular reference in structure → Limit depth to prevent infinite recursion

## Non-Functional Criteria

- Context generation time ≤ 100ms for 50 nodes
- Memory usage increase ≤ 5% compared to current implementation
- Output remains valid markdown
- JSON examples are syntactically valid

## Examples

### Before (misleading):
```markdown
### read-file
**Inputs**:
- `file_path: str` - Path to the file to read

**Parameters**: none
```

### After (clear):
```markdown
### read-file
Read content from a file and add line numbers for display.

**Parameters** (all go in params field):
- `file_path: str` - Path to the file to read
- `encoding: str` - File encoding (optional, default: utf-8)

**Outputs** (access as ${node_id.output_key}):
- `content: str` - File contents with line numbers
- `error: str` - Error message if operation failed

**Example usage**:
```json
{
  "id": "read_file",
  "type": "read-file",
  "params": {
    "file_path": "${input_file}"
  }
}
```
```

## Test Criteria

1. Parameters section present for all nodes with correct header format
2. No "Inputs" section appears in any node output
3. No "Parameters: none" for nodes with input requirements
4. All parameters shown including exclusive params
5. Output section includes namespacing access pattern
6. JSON example present for every node
7. JSON examples are valid JSON syntax
8. Template variables use realistic values not "${key}"
9. Optional parameters marked with "(optional)"
10. Default values shown with "(default: value)"
11. Complex structures display JSON format
12. Test file assertions updated for new format
13. Context size remains under 200KB limit
14. All existing tests pass after changes
15. Planner can generate valid workflows with new format

## Notes (Why)

- Automatic namespacing prevents direct shared store access requiring all data via params
- Misleading "Parameters: none" causes workflow generation failures
- Exclusive params distinction confuses rather than clarifies with namespacing
- Concrete examples eliminate ambiguity in usage patterns
- Single formatting approach reduces cognitive load

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1, 2                       |
| 2      | 4                          |
| 3      | 1                          |
| 4      | 5                          |
| 5      | 6                          |
| 6      | 8                          |
| 7      | 14                         |
| 8      | 14                         |
| 9      | 14                         |
| 10     | 4                          |
| 11     | 5                          |
| 12     | 6, 7                       |
| 13     | 11                         |
| 14     | 12, 14                     |
| 15     | 1, 6                       |

## Versioning & Evolution

- **Version:** 1.0.0
- **Changelog:**
  - **1.0.0** — Initial spec for context builder namespacing update

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes all nodes have interface field populated (Task 19 complete)
- Assumes planner can adapt to new format without prompt changes
- Unknown if any third-party tools depend on current format

### Conflicts & Resolutions

- Documentation suggests "exclusive params" pattern but code shows it causes confusion
  - **Resolution:** Eliminate exclusive params distinction per code behavior observation

### Decision Log / Tradeoffs

- Chose presentation-only change over system-wide refactor for minimal risk
- Chose explicit examples over abstract templates for clarity
- Chose to comment out old functions rather than delete for rollback safety

### Ripple Effects / Impact Map

- Affects context builder output format
- Affects test assertions in test_context_builder_phases.py
- May affect future documentation references to context format
- No impact on node execution or workflow runtime

### Residual Risks & Confidence

- Risk: Planner may need minor prompt adjustments; Mitigation: Test with real workflows
- Risk: Performance impact from example generation; Mitigation: Simple string formatting
- Confidence: High (surgical change to single file)

### Epistemic Audit (Checklist Answers)

1. Assumed planner adapts without prompt changes
2. Wrong assumption requires prompt updates
3. Chose robustness (clear format) over elegance (compact)
4. All rules mapped to tests
5. Minimal ripple to tests only
6. Uncertainty on third-party dependencies; Confidence: High