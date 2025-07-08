# CLAUDE.md - Core Module Documentation

This file provides guidance for understanding and working with the pflow core module, which handles JSON IR validation and schema management.

## Module Overview

The `core` module is responsible for:
- Defining the JSON schema for pflow's Intermediate Representation (IR)
- Validating IR documents against the schema
- Providing clear error messages for validation failures
- Serving as the foundation for all workflow definitions

## Module Structure

```
src/pflow/core/
├── __init__.py       # Module exports: FLOW_IR_SCHEMA, ValidationError, validate_ir
└── ir_schema.py      # Schema definition and validation implementation
```

## Key Components

### 1. FLOW_IR_SCHEMA
The JSON Schema definition that enforces the structure of pflow IR documents. This schema:
- Requires `ir_version` and `nodes` as minimum fields
- Validates node structure (id, type, params)
- Validates edge relationships (from, to, action)
- Ensures type correctness throughout the document
- Supports optional fields like metadata and mappings

### 2. validate_ir() Function
Primary validation function that:
- Accepts IR as dict or JSON string
- Returns validated IR dict if successful
- Raises `ValidationError` with helpful messages if validation fails
- Performs additional checks beyond JSON schema (e.g., edge node existence)

### 3. ValidationError Exception
Custom exception that provides:
- Clear error messages pointing to the exact problem
- Suggestions for fixing common mistakes
- Path to the error location in the JSON structure

## Understanding the Schema

The schema enforces several key concepts:

### Document Structure
```python
{
    "ir_version": "0.1.0",      # Required, semantic versioning
    "nodes": [...],             # Required, at least one node
    "edges": [...],             # Optional, defines connections
    "metadata": {...},          # Optional, workflow metadata
    "mappings": {...}           # Optional, proxy mappings
}
```

### Node Structure
```python
{
    "id": "unique-id",          # Required, unique within flow
    "type": "node-type",        # Required, references registry
    "params": {...},            # Optional, node configuration
    "execution": {...}          # Optional, runtime settings
}
```

### Edge Structure
```python
{
    "from": "source-node-id",   # Required, must exist
    "to": "target-node-id",     # Required, must exist
    "action": "action-name"     # Optional, for conditional routing
}
```

## Connection to Examples

The `examples/` directory contains real-world usage of this schema:

### Valid Examples (tested by test_ir_examples.py)
- `examples/core/minimal.json` - Demonstrates minimum requirements
- `examples/core/simple-pipeline.json` - Shows basic edge connections
- `examples/core/template-variables.json` - Uses `$variable` substitution
- `examples/core/error-handling.json` - Action-based routing
- `examples/core/proxy-mappings.json` - Interface adaptation

### Invalid Examples (demonstrate error messages)
- `examples/invalid/missing-version.json` - What happens without ir_version
- `examples/invalid/bad-edge-ref.json` - Edge validation errors
- `examples/invalid/duplicate-ids.json` - Unique ID enforcement
- `examples/invalid/wrong-types.json` - Type validation

## Common Validation Errors

### 1. Missing Required Fields
```python
ValidationError: 'ir_version' is a required property
```
**Fix**: Ensure all required fields are present

### 2. Invalid Node References in Edges
```python
ValidationError: Edge references non-existent node 'missing-node'
```
**Fix**: Verify all edge from/to values match existing node IDs

### 3. Duplicate Node IDs
```python
ValidationError: Duplicate node ID found: 'node1'
```
**Fix**: Ensure each node has a unique ID

### 4. Type Mismatches
```python
ValidationError: 'nodes' must be array, not string
```
**Fix**: Check field types match schema requirements

## Extending the Schema

When adding new features to the IR format:

1. **Update ir_schema.py**:
   - Add new fields to FLOW_IR_SCHEMA
   - Mark new fields as optional for backward compatibility
   - Add validation logic if needed beyond JSON schema

2. **Update Documentation**:
   - Update `docs/core-concepts/schemas.md` with new fields
   - Add examples showing the new feature
   - Update version compatibility notes

3. **Add Tests**:
   - Add test cases to `tests/test_core/test_ir_schema.py`
   - Create example files demonstrating the feature
   - Test both valid and invalid usage

4. **Version Considerations**:
   - Minor version bump for optional additions
   - Major version bump for breaking changes
   - Update ir_version compatibility checks

## Testing and Validation

### Unit Tests
- `tests/test_core/test_ir_schema.py` - Schema validation tests
- `tests/test_core/test_ir_examples.py` - Example file validation

### Integration Points
- Used by `runtime.compiler` to validate before compilation
- Used by CLI to validate workflow files
- Used by planner to ensure generated IR is valid

### Running Validation
```python
from pflow.core import validate_ir

# Validate a workflow
try:
    validated_ir = validate_ir(workflow_dict)
    print("Workflow is valid!")
except ValidationError as e:
    print(f"Validation failed: {e}")
```

## Best Practices

1. **Always validate early**: Validate IR as soon as it's loaded or generated
2. **Use helpful error messages**: Include suggestions for fixing common mistakes
3. **Test edge cases**: Ensure validation catches all invalid states
4. **Keep examples updated**: Examples serve as both documentation and tests
5. **Version carefully**: Consider backward compatibility when changing schema

## Related Documentation

- **Conceptual Overview**: `docs/core-concepts/schemas.md` - High-level schema documentation
- **Examples**: `examples/README.md` - Guide to all example files
- **Tests**: `tests/test_core/` - Validation test cases
- **Runtime Usage**: `src/pflow/runtime/compiler.py` - How validation fits into execution

## Future Enhancements

Planned improvements to the core module:
- Schema versioning and migration tools
- Performance optimization for large IR documents
- Additional validation rules (e.g., cycle detection)
- Schema extension points for custom node types
- Better error messages with fix suggestions

Remember: The core module is the foundation of pflow's reliability. Changes here affect the entire system, so proceed with careful testing and documentation.
