# Refined Specification for Subtask 6.1

## Clear Objective
Create JSON Schema definitions for workflow IR in a Python module that enables validation of workflow structures before execution.

## Context from Knowledge Base
- Building on: JSON format convention from Task 5 Registry
- Avoiding: Over-engineering and complex metadata structures
- Following: Test-as-you-go pattern, clear error messages pattern
- **Cookbook patterns to apply**: None directly applicable - this is pure schema definition

## Technical Specification

### Inputs
- JSON strings or Python dicts representing workflow IR
- Schema version for compatibility checking

### Outputs
- Python module `src/pflow/core/ir_schema.py` containing:
  - `FLOW_IR_SCHEMA`: JSON Schema dict for workflow validation
  - `validate_ir(data)`: Function to validate IR against schema
  - `ValidationError`: Custom exception with helpful messages

### Implementation Constraints
- Must use: Standard JSON Schema Draft 7 format
- Must use: jsonschema library for validation
- Must avoid: Pydantic models or custom validation logic
- Must maintain: Extensibility for future schema versions

## Schema Structure (Minimal MVP)

```python
{
    "type": "object",
    "properties": {
        "ir_version": {"type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$"},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "type": {"type": "string"},  # NOT registry_id
                    "params": {"type": "object"}
                },
                "required": ["id", "type"],
                "additionalProperties": false
            }
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "action": {"type": "string", "default": "default"}
                },
                "required": ["from", "to"],
                "additionalProperties": false
            }
        },
        "start_node": {"type": "string"},  # Optional
        "mappings": {"type": "object"}      # Optional
    },
    "required": ["ir_version", "nodes"],
    "additionalProperties": false
}
```

## Success Criteria
- [ ] Schema validates correct IR structures
- [ ] Schema rejects invalid IR with clear errors
- [ ] Validation function provides helpful error messages with field paths
- [ ] All schema constraints are tested
- [ ] Module has comprehensive docstrings with examples
- [ ] Tests achieve >90% coverage

## Test Strategy
- **Valid IR Tests**:
  - Minimal IR (single node, no edges)
  - Complex IR (multiple nodes, edges, actions)
  - IR with mappings
  - IR without start_node (should be valid)

- **Invalid IR Tests**:
  - Missing required fields (ir_version, nodes)
  - Invalid node references in edges
  - Duplicate node IDs
  - Invalid version format
  - Unknown properties

- **Error Message Tests**:
  - Verify errors include field path
  - Check suggestions for common mistakes
  - Ensure messages are user-friendly

## Dependencies
- Requires: jsonschema library (must add to pyproject.toml)
- Requires: Creation of `src/pflow/core/__init__.py`
- Impacts: Task 4 (IR-to-Flow converter) will use this for validation

## Decisions Made
- Use standard JSON Schema format (not Pydantic) - per research file
- Use 'type' field for nodes (not 'registry_id') - per research file
- Make start_node optional - defaults to first node if not specified
- Include action field in edges - defaults to "default" if not specified
- Keep template variables as plain strings in params - no special handling
- Create Python module with schema as dict - not separate .json files
- Add jsonschema to dependencies - standard tool for validation

## Implementation Notes
1. Start with schema definition as Python dict
2. Implement validate_ir() with custom error formatting
3. Write tests immediately after each schema constraint
4. Include usage examples in module docstring
5. Keep schema minimal but allow additionalProperties: false for strict validation
