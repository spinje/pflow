# Task 21: Implement Workflow Input Declaration

## ID
21

## Title
Implement Workflow Input Declaration

## Description
Enable workflows to declare their expected input parameters in the IR schema, providing discovery, validation, and documentation capabilities. This feature makes workflows self-documenting by declaring what parameters they expect, enabling compile-time validation and better tooling integration.

## Dependencies
- Task 4: IR-to-PocketFlow Object Converter (for compiler integration)
- Task 6: JSON IR schema (to extend with input declarations)
- Task 18: Template Variable System (for template validation)
- Task 19: Node Interface Registry (for validation patterns)
- Task 20: Workflow Executor (optional - enhances workflow composition)

## Details

### Objective
Create a mechanism for workflows to declare their input parameters with:
- Optional input declarations in the IR schema
- Compile-time validation of initial_params against declarations
- Default value support for optional inputs
- Clear error messages for missing/invalid inputs
- Backward compatibility with existing workflows
- Integration with template validation system

### Implementation Approach

1. **Schema Extension**: Add `WorkflowInput` model to `src/pflow/core/ir_schema.py`
   - Create WorkflowInput class with description, required, type, and default fields
   - Add optional `inputs` field to workflow IR schema
   - Ensure Pydantic validation for the new schema components

2. **Compiler Enhancement**: Update `src/pflow/runtime/compiler.py`
   - Extract input declarations during compilation
   - Validate initial_params against declared inputs before template resolution
   - Apply default values for missing optional inputs
   - Provide detailed validation errors with input descriptions

3. **Template Validator Integration**: Enhance validation messages
   - Use input descriptions in template resolution errors
   - Optionally validate that template variables have declarations
   - Improve error context with parameter information

4. **Registry Support**: Update metadata extraction (optional)
   - Include input declarations in workflow metadata
   - Enable discovery of workflow interfaces
   - Support planner integration

5. **Type System**:
   - Basic types only: "string", "number", "boolean", "object", "array"
   - Types are hints for documentation, not strict enforcement
   - Focus on required/optional semantics over complex validation

### IR Usage Example
```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "text": {
      "description": "Text to analyze",
      "required": true,
      "type": "string"
    },
    "language": {
      "description": "Language code (ISO 639-1)",
      "required": false,
      "type": "string",
      "default": "en"
    },
    "max_length": {
      "description": "Maximum output length",
      "required": false,
      "type": "number",
      "default": 1000
    }
  },
  "nodes": [
    {
      "id": "analyze",
      "type": "text-analyzer",
      "params": {
        "text": "$text",
        "lang": "$language",
        "limit": "$max_length"
      }
    }
  ]
}
```

### Key Design Decisions

1. **Optional Feature**: The `inputs` field is completely optional
   - Existing workflows without inputs continue to work unchanged
   - Provides gradual migration path for workflow authors
   - No breaking changes to existing IR files

2. **Simple Type System**: Focus on basic validation
   - Types are documentation hints, not strict contracts
   - No complex schemas or nested validation in MVP
   - Can be enhanced in future versions

3. **Compile-Time Validation**: Fail fast with clear messages
   - Validate when workflow is loaded, not during execution
   - Provide helpful errors that reference input descriptions
   - Apply defaults early in the compilation process

4. **Template Alignment**: Input names must match template variable names
   - Ensures consistency between declaration and usage
   - Enables tooling to understand parameter flow
   - Simplifies validation logic

### Error Handling
- Missing required input: "Workflow requires input 'text' (Text to analyze)"
- Type mismatch: "Input 'max_length' expected type 'number' but got 'string'"
- Invalid input name: "Input name 'invalid-name' must be a valid identifier"
- Default type mismatch: "Default value for 'max_length' does not match declared type 'number'"

## Status
pending

## Test Strategy

### Unit Tests (25+ tests covering all scenarios)
1. **Schema Validation**:
   - Valid input declarations with all field combinations
   - Invalid input names (non-identifiers)
   - Invalid type values
   - Default value type validation

2. **Compiler Validation**:
   - Missing required inputs raise ValidationError
   - Optional inputs use defaults when not provided
   - All provided inputs are validated
   - Extra inputs are allowed (for flexibility)

3. **Type Checking**:
   - String, number, boolean type validation
   - Object and array type validation
   - Null handling for optional inputs
   - Type mismatches raise clear errors

4. **Backward Compatibility**:
   - Workflows without inputs field work unchanged
   - Empty inputs object is valid
   - Mix of declared and undeclared variables

5. **Error Messages**:
   - Include input descriptions in errors
   - Clear indication of required vs optional
   - Type mismatch details
   - Multiple validation errors reported together

### Integration Tests
1. **End-to-end Workflow Execution**:
   - Workflows with input declarations execute correctly
   - Defaults are applied and accessible in nodes
   - Template resolution uses validated inputs

2. **WorkflowNode Integration** (if Task 20 is complete):
   - Parent workflow validates child input requirements
   - Param mapping covers required child inputs
   - Child defaults apply when not mapped

3. **Complex Scenarios**:
   - Nested workflows with input declarations
   - Template variables beyond declared inputs
   - Workflows using both initial_params and shared store

### Test Organization
- Tests in `tests/test_core/test_workflow_inputs/`
- Fixture workflows in `tests/fixtures/workflows/with_inputs/`
- Integration with existing test patterns
- Clear test names describing scenarios
