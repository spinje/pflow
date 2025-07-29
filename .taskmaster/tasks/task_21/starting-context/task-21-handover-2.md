# Task 21: Workflow Input/Output Declaration - Handover Document

## Context & Problem Statement

Currently, pflow workflows use template variables (e.g., `$issue_number`) in node parameters and write outputs to the shared store, but there's no mechanism in the IR schema to declare what inputs a workflow expects or what outputs it produces. This creates several problems:

1. **Discovery**: No way to programmatically know what parameters a workflow needs or what data it produces
2. **Validation**: Can't validate at compile-time that all required inputs are provided or that declared outputs are actually produced
3. **Documentation**: No standardized way to document workflow interfaces (both consumption and production)
4. **Composition**: WorkflowNode users must read workflow files to understand both param_mapping and output_mapping requirements
5. **Planning**: The planner (Task 17) can't determine what parameters to provide or what outputs are available for downstream use
6. **Template Path Validation**: Can't validate paths like `$workflow_result.field` without knowing output structure

## Current State Analysis

### What Exists Today

1. **Template Variables in Nodes**:
   ```json
   {
     "id": "analyzer",
     "type": "analyze-text",
     "params": {
       "text": "$input_text",
       "language": "$lang"
     }
   }
   ```

2. **Workflow Metadata** (stored separately from IR):
   ```json
   {
     "name": "sentiment-analyzer",
     "description": "Analyzes text sentiment",
     "inputs": ["input_text", "lang"],  // Just documentation
     "outputs": ["sentiment_score"],
     "ir": { ... }  // The actual workflow
   }
   ```

3. **Runtime Validation**:
   - Template validation happens at runtime via TemplateValidator
   - Checks if template variables can be resolved from initial_params + shared store
   - Fails at runtime if required variables are missing

### What's Missing

The IR schema itself has no way to declare inputs or outputs. When WorkflowNode loads a workflow, it can't know:
- What parameters are expected without parsing all template usage
- What outputs will be produced without analyzing all node outputs
- Whether the workflow actually produces the outputs it claims in metadata

## Proposed Solution

### 1. Extend IR Schema

Add optional `inputs` and `outputs` fields to the IR schema:

```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "input_text": {
      "description": "Text to analyze",
      "required": true,
      "type": "string"
    },
    "lang": {
      "description": "Language code",
      "required": false,
      "type": "string",
      "default": "en"
    }
  },
  "outputs": {
    "sentiment_score": {
      "description": "Sentiment score from -1 (negative) to 1 (positive)",
      "type": "number"
    },
    "confidence": {
      "description": "Confidence level of the analysis",
      "type": "number"
    },
    "language_detected": {
      "description": "Detected language if different from input",
      "type": "string"
    }
  },
  "nodes": [...],
  "edges": [...]
}
```

### 2. Key Design Decisions

1. **Single Source of Truth**: Input/output declarations in IR supersede any metadata-level lists
2. **Simple Types**: Start with basic validation (string, number, boolean, object, array)
3. **Validation Focus**: Types are for documentation/validation, not strict typing
4. **Name Alignment**: Input names must match template variable names, output names must match shared store keys
5. **Complete Interfaces**: Both inputs and outputs together form the workflow's complete interface
6. **No Migration Needed**: Since there are no users, existing test workflows can be updated directly

## Integration Points

### 1. IR Schema (`src/pflow/core/ir_schema.py`)

Add new Pydantic models:
```python
class WorkflowInput(BaseModel):
    description: Optional[str] = None
    required: bool = True
    type: Optional[str] = None  # "string", "number", "boolean", "object", "array"
    default: Optional[Any] = None

class WorkflowOutput(BaseModel):
    description: Optional[str] = None
    type: Optional[str] = None  # "string", "number", "boolean", "object", "array"
    # Note: outputs don't have required/default - they're always optional to produce

class WorkflowIR(BaseModel):
    ir_version: str = "0.1.0"
    inputs: Optional[Dict[str, WorkflowInput]] = None  # NEW
    outputs: Optional[Dict[str, WorkflowOutput]] = None  # NEW
    nodes: List[NodeConfig]
    edges: List[EdgeConfig]
    # ... rest of schema
```

### 2. Compiler (`src/pflow/runtime/compiler.py`)

Enhance `compile_ir_to_flow()` to:
1. Extract declared inputs and outputs from IR
2. Validate initial_params against input declarations
3. Apply defaults for missing optional inputs
4. Provide clear errors for missing required inputs
5. Store output declarations for runtime validation (optional for MVP)
6. Enable output validation hooks for debugging

### 3. Template Validator (`src/pflow/runtime/template_validator.py`)

Could be enhanced to:
1. Check that all template variables have corresponding input declarations
2. Warn about declared inputs that aren't used
3. Provide better error messages using input descriptions
4. Validate workflow output references (e.g., `$workflow_result.field`) against output declarations
5. Enable validation of output paths in nested workflow scenarios

### 4. Registry/Metadata (`src/pflow/registry/metadata_extractor.py`)

When extracting workflow metadata:
1. Include both `inputs` and `outputs` declarations from IR
2. Make this available for discovery and composition
3. Could validate saved workflows have proper input/output declarations
4. Enable workflow discovery by outputs (e.g., "find workflows that produce pr_url")

### 5. Context Builder (`src/pflow/planning/context_builder.py`)

For Task 17 planner support:
1. Include input and output declarations when loading saved workflows
2. Format them clearly for LLM understanding
3. Enable planner to provide correct parameters
4. Show workflow outputs for composition planning
5. Allow matching workflow outputs to next workflow inputs

### 6. WorkflowExecutor Enhancement (Task 20)

WorkflowExecutor could:
1. Read child workflow's input and output declarations
2. Validate param_mapping covers all required inputs
3. Validate output_mapping references valid outputs
4. Provide better error messages using input/output descriptions
5. Apply defaults for unmapped optional inputs
6. Warn when output_mapping references non-existent outputs

## Implementation Order

### Phase 1: Core Schema & Validation (Required)
1. Extend IR schema with inputs and outputs fields
2. Update compiler to validate inputs against declarations
3. Add tests for input/output validation logic

### Phase 2: Integration (Required)
1. Update template validator to use input/output info
2. Update existing test workflows to use new format
3. Add comprehensive tests for both inputs and outputs

### Phase 3: Enhanced Features (Optional)
1. Registry metadata extraction for workflows
2. Context builder integration for planner (inputs + outputs)
3. WorkflowExecutor validation improvements
4. Output production validation at runtime

## Example Implementation

### Complete Workflow with Inputs and Outputs
```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "file_path": {
      "description": "Path to the file to process",
      "required": true,
      "type": "string"
    },
    "output_format": {
      "description": "Output format (json or text)",
      "required": false,
      "type": "string",
      "default": "json"
    }
  },
  "outputs": {
    "formatted_data": {
      "description": "The processed and formatted data",
      "type": "string"
    },
    "metadata": {
      "description": "Processing metadata including file info",
      "type": "object"
    }
  },
  "nodes": [
    {
      "id": "read",
      "type": "read-file",
      "params": {
        "path": "$file_path"
      }
    },
    {
      "id": "format",
      "type": "format-output",
      "params": {
        "data": "$content",
        "format": "$output_format"
      }
    }
  ],
  "edges": [
    {"from": "read", "to": "format"}
  ]
}
```

### Using with WorkflowExecutor
```json
{
  "id": "process",
  "type": "workflow",
  "params": {
    "workflow_ref": "~/.pflow/workflows/processor.json",
    "param_mapping": {
      "file_path": "$input_file"
      // output_format not mapped, will use default "json"
    },
    "output_mapping": {
      "formatted_data": "processed_content",
      "metadata": "file_metadata"
    }
  }
}
```

## Success Criteria

1. ✅ IR schema supports optional input declarations
2. ✅ Compiler validates initial_params against declarations
3. ✅ Defaults are applied for missing optional inputs
4. ✅ Clear errors for missing required inputs
5. ✅ Backward compatibility - workflows without inputs still work
6. ✅ Template validator can leverage input information
7. ✅ All tests pass, no regressions

## Technical Considerations

### Validation Timing
- Compile-time: Validate initial_params against declarations
- Runtime: Template resolution still happens at runtime
- This provides early feedback while maintaining flexibility

### Type System
- Keep it simple - basic types only for MVP
- Types are hints for validation, not strict enforcement
- Focus on required/optional and defaults

### Error Messages
When validation fails, include:
- Which input is missing/invalid
- The input's description (if provided)
- Whether it's required or has a default

## Risks & Mitigations

1. **Risk**: Breaking existing workflows
   - **Mitigation**: inputs field is completely optional

2. **Risk**: Over-complicating the type system
   - **Mitigation**: Start with simple types, enhance later

3. **Risk**: Confusion between compile-time and runtime validation
   - **Mitigation**: Clear documentation about what validates when

## Not in Scope (Future Enhancements)

- Complex type validation (schemas, patterns)
- Type inference from template usage
- Automatic documentation generation
- IDE integration for autocomplete
- Workflow "interfaces" or "contracts"

## Key Insights for Implementation

1. This feature makes workflows more like "functions with signatures"
2. It's primarily about discovery and documentation, not strict typing
3. The implementation should be minimally invasive
4. Focus on making workflow composition easier and safer
5. This directly enables better planner integration (Task 17)

## Questions to Resolve

1. Should we validate that declared inputs are actually used in templates?
2. Should we warn about template variables without declarations?
3. How detailed should the type system be for MVP?
4. Should WorkflowNode enforce child workflow input requirements?

These can be decided during implementation based on complexity vs. value trade-offs.
