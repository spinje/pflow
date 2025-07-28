# Feature: workflow_input_declaration

## Objective

Enable workflows to declare their expected input parameters in the IR schema, providing discovery, validation, and documentation capabilities.

## Requirements

- Must extend IR schema with optional inputs field
- Must validate initial_params against declared inputs at compile time
- Must maintain backward compatibility with existing workflows
- Must apply defaults for missing optional inputs
- Must provide clear error messages for validation failures
- Should integrate with template validation system
- Should enable WorkflowNode to validate param_mapping

## Scope

- Does not implement complex type validation
- Does not infer inputs from template usage
- Does not generate documentation automatically
- Does not provide IDE integration
- Does not enforce strict typing

## Inputs

The IR schema will accept:
- inputs: Optional[Dict[str, WorkflowInput]] - Input parameter declarations

Where WorkflowInput contains:
- description: Optional[str] - Human-readable description
- required: bool = True - Whether the input is required
- type: Optional[str] - Basic type hint ("string", "number", "boolean", "object", "array")
- default: Optional[Any] - Default value for optional inputs

## Outputs

- Validated initial_params with defaults applied
- Clear validation errors for missing/invalid inputs
- Enhanced template validation messages

## Example

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
      "description": "Language code",
      "required": false,
      "type": "string",
      "default": "en"
    }
  },
  "nodes": [
    {
      "id": "analyze",
      "type": "text-analyzer",
      "params": {
        "text": "$text",
        "lang": "$language"
      }
    }
  ]
}
```

## Rules

1. If inputs field is present, validate initial_params against it
2. If required input is missing and no default, raise ValidationError
3. If optional input is missing, apply default value
4. If input has type, perform basic type validation
5. Input names must be valid identifiers (match template variable rules)
6. Defaults must match declared type (if type is specified)

## Test Criteria

1. Workflow without inputs field works as before
2. Required input missing raises clear error
3. Optional input missing uses default value
4. Type mismatch raises validation error
5. Invalid input name raises error
6. Defaults are applied correctly
7. Validation errors include input descriptions
8. Template validator uses input information
9. Nested workflows validate inputs correctly

## Notes (Why)

- Enables discovery of workflow interfaces
- Provides compile-time validation for better developer experience
- Documents workflow expectations in a machine-readable format
- Enables better tooling and planner integration
- Makes workflows more like reusable functions with signatures
