# Task 21: Implement Workflow Input/Output Declaration

## ID
21

## Title
Implement Workflow Input/Output Declaration

## Description
Enable workflows to declare their expected input parameters and output data in the IR schema, providing discovery, validation, and documentation capabilities. This feature makes workflows self-documenting by declaring their complete interface (what they consume and produce), enabling compile-time validation, workflow composition, and better tooling integration.

## Dependencies
- Task 4: IR-to-PocketFlow Object Converter (for compiler integration)
- Task 6: JSON IR schema (to extend with input declarations)
- Task 18: Template Variable System (for template validation)
- Task 19: Node Interface Registry (for validation patterns)
- Task 20: Workflow Executor (optional - enhances workflow composition)

## Details

### Objective
Create a mechanism for workflows to declare their complete interface with:
- Optional input and output declarations in the IR schema
- Compile-time validation of initial_params against input declarations
- Static analysis of declared outputs against node capabilities
- Default value support for optional inputs
- Clear error messages for missing/invalid inputs or outputs
- Integration with template validation system for both inputs and outputs
- Enable workflow composition by matching outputs to inputs
- Support for the Natural Language Planner (Task 17) to understand workflow contracts
- Foundation for WorkflowManager (Task 24) to validate workflow compatibility

### Implementation Approach

1. **Schema Extension**: Add interface models to `src/pflow/core/ir_schema.py`
   - Create WorkflowInput class with description, required, type, and default fields
   - Create WorkflowOutput class with key, description, and type fields
   - Add optional `inputs` and `outputs` fields to workflow IR schema
   - Ensure Pydantic validation for the new schema components

2. **Compiler Enhancement**: Update `src/pflow/runtime/compiler.py`
   - Extract input and output declarations during compilation
   - Validate initial_params against declared inputs before template resolution
   - Apply default values for missing optional inputs
   - Validate declared outputs against node interfaces from registry
   - Provide detailed validation errors with input/output descriptions

3. **Template Validator Integration**: Enhance validation messages
   - Use input descriptions in template resolution errors
   - Optionally validate that template variables have declarations
   - Improve error context with parameter information

4. **Registry Support**: Update metadata extraction (optional)
   - Include input and output declarations in workflow metadata
   - Enable discovery of complete workflow interfaces
   - Support planner integration for workflow composition
   - Allow matching workflow outputs to inputs

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
  "outputs": {
    "summary": {
      "description": "Generated text summary",
      "type": "string"
    },
    "word_count": {
      "description": "Total word count",
      "type": "number"
    },
    "language_detected": {
      "description": "Detected language if different from input",
      "type": "string"
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

1. **Optional Feature**: Both `inputs` and `outputs` fields are completely optional
   - Existing workflows without interface declarations continue to work unchanged
   - Provides gradual migration path for workflow authors
   - No breaking changes to existing IR files

2. **IR as Source of Truth**: Interface declarations belong in the IR, not metadata
   - The IR contains the authoritative contract (what workflow needs and produces)
   - Metadata contains derived information (name, description, timestamps)
   - Enables validation and composition based on actual workflow structure
   - Metadata-level inputs/outputs lists are ignored when IR declarations exist

3. **Simple Type System**: Focus on basic validation
   - Types are documentation hints, not strict contracts
   - No complex schemas or nested validation in MVP
   - Can be enhanced in future versions

4. **Compile-Time Validation**: Fail fast with clear messages
   - Validate when workflow is loaded, not during execution
   - Provide helpful errors that reference input descriptions
   - Apply defaults early in the compilation process

5. **Template Alignment**: Input names must match template variable names
   - Ensures consistency between declaration and usage
   - Enables tooling to understand parameter flow
   - Simplifies validation logic

6. **Workflow Composition Support**: Complete interfaces enable composition
   - Planner can match workflow outputs to inputs automatically
   - Discovery can find workflows by what they produce, not just consume
   - WorkflowExecutor can validate param/output mappings at compile time

### Error Handling
- Missing required input: "Workflow requires input 'text' (Text to analyze)"
- Type mismatch: "Input 'max_length' expected type 'number' but got 'string'"
- Invalid input name: "Input name 'invalid-name' must be a valid identifier"
- Default type mismatch: "Default value for 'max_length' does not match declared type 'number'"
- Missing declared output: "Workflow declares output 'summary' but no node in workflow can produce this key"
- Invalid output key: "Output key 'invalid-key!' must be a valid identifier"

## Status
done

## Test Strategy

### Unit Tests (35+ tests covering all scenarios)
1. **Schema Validation**:
   - Valid input and output declarations with all field combinations
   - Invalid input/output names (non-identifiers)
   - Invalid type values
   - Default value type validation
   - Output key validation

2. **Compiler Validation**:
   - Missing required inputs raise ValidationError
   - Optional inputs use defaults when not provided
   - All provided inputs are validated
   - Extra inputs are allowed (for flexibility)
   - Declared outputs tracked during node compilation
   - Warning if declared outputs are never written

3. **Type Checking**:
   - String, number, boolean type validation
   - Object and array type validation
   - Null handling for optional inputs
   - Type mismatches raise clear errors

4. **Backward Compatibility**:
   - Workflows without inputs/outputs fields work unchanged
   - Empty inputs/outputs objects are valid
   - Mix of declared and undeclared variables allowed
   - Existing workflows continue to function without modification

5. **Output Validation**:
   - Validate output keys are valid identifiers
   - Static analysis: Check if any node in workflow CAN produce declared outputs (based on registry interfaces)
   - Warning (not error) if declared output cannot be traced to any node
   - Type hints are documentation only, not enforced
   - Note: Runtime validation that outputs are actually produced is deferred to future versions

6. **Error Messages**:
   - Include input/output descriptions in errors
   - Clear indication of required vs optional
   - Type mismatch details
   - Multiple validation errors reported together
   - Missing output warnings with node information

### Integration Tests
1. **End-to-end Workflow Execution**:
   - Workflows with input declarations execute correctly
   - Defaults are applied and accessible in nodes
   - Template resolution uses validated inputs

2. **WorkflowExecutor Integration** (Task 20 is complete):
   - Parent workflow validates child input requirements
   - Param mapping covers required child inputs
   - Child defaults apply when not mapped
   - Output declarations enable validation of output_mapping
   - WorkflowExecutor can verify child outputs exist before mapping

3. **Complex Scenarios**:
   - Nested workflows with input declarations
   - Template variables beyond declared inputs
   - Workflows using both initial_params and shared store

### Test Organization
- Tests in `tests/test_core/test_workflow_interfaces/`
- Fixture workflows in `tests/fixtures/workflows/with_interfaces/`
- Integration with existing test patterns
- Clear test names describing scenarios
