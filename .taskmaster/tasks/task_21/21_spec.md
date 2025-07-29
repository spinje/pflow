# Feature: workflow_input_output_declaration

## Objective

Enable workflows to declare their expected input parameters and output data in the IR schema, providing discovery, validation, documentation, and composition capabilities. This moves the interface contract from workflow metadata into the IR itself, establishing the IR as the single source of truth for workflow interfaces.

## Requirements

- Must extend IR schema with optional inputs and outputs fields
- Must validate initial_params against declared inputs at compile time
- Must validate that declared outputs match keys that workflow nodes can write to shared store (based on node registry interfaces)
- Must maintain backward compatibility with existing workflows
- Must apply defaults for missing optional inputs
- Must provide clear error messages for validation failures
- Should integrate with template validation system
- Should enable WorkflowNode to validate param_mapping and output_mapping
- Should enable workflow composition by matching outputs to inputs

## Scope

- Does not implement complex type validation
- Does not infer inputs from template usage
- Does not infer outputs from node execution
- Does not generate documentation automatically
- Does not provide IDE integration
- Does not enforce strict typing
- Does not validate output structure (only presence)
- Does not automatically migrate existing metadata-level inputs/outputs to IR (manual migration needed)

## Inputs

The IR schema will accept:
- inputs: Optional[Dict[str, WorkflowInput]] - Input parameter declarations
- outputs: Optional[Dict[str, WorkflowOutput]] - Output data declarations

Where WorkflowInput contains:
- description: Optional[str] - Human-readable description
- required: bool = True - Whether the input is required
- type: Optional[str] - Basic type hint ("string", "number", "boolean", "object", "array")
- default: Optional[Any] - Default value for optional inputs

Where WorkflowOutput contains:
- description: Optional[str] - Human-readable description
- type: Optional[str] - Basic type hint ("string", "number", "boolean", "object", "array")

## Outputs

- Validated initial_params with defaults applied
- Clear validation errors for missing/invalid inputs
- Validation that declared outputs can be produced by workflow nodes
- Enhanced template validation messages for both inputs and outputs
- Workflow interface information for composition

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
  "outputs": {
    "sentiment": {
      "description": "Sentiment score (-1 to 1)",
      "type": "number"
    },
    "summary": {
      "description": "Text summary",
      "type": "string"
    },
    "word_count": {
      "description": "Number of words analyzed",
      "type": "number"
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
7. If outputs field is present, validate that workflow nodes collectively can produce these outputs by:
   - Checking each declared output key against the union of all node outputs in the workflow
   - Using node registry interface data to determine what each node writes to shared store
   - Allowing outputs from nested workflows (type: "workflow") based on their output_mapping
8. Output names must be valid identifiers (match shared store key rules)
9. Validation should warn (not error) if declared outputs cannot be traced to specific nodes, as nodes may write dynamic keys
10. Both inputs and outputs are optional (backward compatibility)

## Test Criteria

1. Workflow without inputs/outputs fields works as before
2. Required input missing raises clear error
3. Optional input missing uses default value
4. Type mismatch raises validation error
5. Invalid input name raises error
6. Defaults are applied correctly
7. Validation errors include input descriptions
8. Template validator uses input information
9. Nested workflows validate inputs correctly
10. Workflow without outputs field works as before
11. Declared outputs that match node outputs validate successfully
12. Declared outputs from nested workflows (with output_mapping) validate correctly
13. Warning (not error) for outputs that cannot be traced to nodes
14. Invalid output names raise validation error
15. Template paths like $workflow_result.field validate against declared outputs

## Notes (Why)

- Enables discovery of workflow interfaces
- Provides compile-time validation for better developer experience
- Documents workflow expectations in a machine-readable format
- Enables better tooling and planner integration
- Makes workflows more like reusable functions with signatures
- Establishes IR as single source of truth for workflow contracts (replacing metadata-level declarations)
- Enables static validation of workflow composition without execution
- Critical for Task 17 (planner) to understand workflow interfaces for composition
