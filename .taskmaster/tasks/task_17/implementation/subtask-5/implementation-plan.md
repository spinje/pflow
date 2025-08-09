# Task 17 - Subtask 5 Implementation Plan

## Context Verification Complete

### From Previous Subtasks (Subtask 4)
- ✅ GeneratorNode always routes to "validate" action string
- ✅ generation_attempts tracked in shared store (0-indexed, incremented in exec)
- ✅ Generated workflow follows FlowIR structure with `inputs` field
- ✅ validation_errors expected as list[str] (top 3 used for retry)
- ✅ Workflow stored in shared["generated_workflow"]

### Current Validation Landscape
- **validate_ir()**: Handles structural validation (JSON schema, node references)
- **TemplateValidator**: Validates template resolution from sources
- **Missing**: Unused inputs validation and node type validation

## Shared Store Contract
### Reads
- `shared["generated_workflow"]`: Complete workflow IR from GeneratorNode
- `shared["generation_attempts"]`: Number of attempts (1-indexed after increment)
- `shared["planning_context"]`: For metadata extraction
- `shared["user_input"]`: For metadata extraction

### Writes
- `shared["validation_errors"]`: list[str] - Error messages for retry
- `shared["workflow_metadata"]`: dict - Extracted metadata

## Implementation Strategy

### Phase 1: Enhance TemplateValidator (30 minutes)
1. **Locate Method**: `validate_workflow_templates()` in `src/pflow/runtime/template_validator.py`
2. **Current Logic**: Already extracts all template variables via `_extract_all_templates()`
3. **Enhancement**: Add unused input detection
   ```python
   # Extract declared inputs
   declared_inputs = set(workflow_ir.get("inputs", {}).keys())

   # Extract used template variables (base names only)
   template_vars = self._extract_all_templates(workflow_ir)
   used_inputs = {var.split('.')[0] for var in template_vars
                  if var.split('.')[0] in declared_inputs}

   # Find unused
   unused_inputs = declared_inputs - used_inputs
   if unused_inputs:
       errors.append(f"Declared input(s) never used: {', '.join(sorted(unused_inputs))}")
   ```
4. **Test independently**: Verify enhancement catches unused inputs

### Phase 2: Implement ValidatorNode (45 minutes)
1. **Orchestrator Pattern**: ValidatorNode calls existing validators
2. **Structure**:
   ```python
   class ValidatorNode(Node):
       def __init__(self):
           super().__init__(name="validator", wait=0)
           self.registry = Registry()  # Direct instantiation

       def exec(self, prep_res):
           errors = []

           # 1. Structural validation
           try:
               validate_ir(workflow)
           except ValidationError as e:
               errors.append(f"{e.path}: {e.message}")

           # 2. Template validation (includes unused inputs)
           template_errors = TemplateValidator.validate_workflow_templates(
               workflow, {}, self.registry
           )
           errors.extend(template_errors)

           # 3. Node type validation
           metadata = self.registry.get_nodes_metadata()
           for node in workflow.get("nodes", []):
               if node["type"] not in metadata:
                   errors.append(f"Unknown node type: '{node['type']}'")

           return {"errors": errors[:3]}  # Top 3 only
   ```
3. **Action Routing**:
   - "retry" if errors and attempts < 3
   - "metadata_generation" if no errors
   - "failed" if attempts >= 3

### Phase 3: Implement MetadataGenerationNode (30 minutes)
1. **Simple Extraction**:
   ```python
   def exec(self, prep_res):
       # Extract name from user input
       suggested_name = self._generate_name(prep_res["user_input"])

       # Extract inputs/outputs from workflow
       declared_inputs = list(prep_res["workflow"].get("inputs", {}).keys())
       declared_outputs = self._extract_outputs(prep_res["workflow"])

       return {
           "suggested_name": suggested_name,
           "description": prep_res["user_input"][:100],
           "declared_inputs": declared_inputs,
           "declared_outputs": declared_outputs
       }
   ```
2. **Routing**: Return empty string to continue flow

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Wrong error format | Generator can't parse | Test list[str] format |
| Registry incomplete | Node validation fails | Trust automatic scanning |
| Metadata format wrong | ParameterMapping fails | Keep simple extraction |
| Generation attempts off-by-one | Wrong retry count | Verify 1-indexed after increment |

## Testing Strategy

### Unit Tests
1. **TemplateValidator Enhancement**:
   - Test unused input detection
   - Test with empty inputs field
   - Test with all inputs used

2. **ValidatorNode**:
   - Test all three routing paths
   - Test error limiting (top 3)
   - Test with valid workflow

3. **MetadataGenerationNode**:
   - Test name extraction
   - Test metadata format

### Integration Tests
1. Test retry loop with GeneratorNode
2. Test flow continues to ParameterMappingNode
3. Test with real workflows from Subtask 4

## Dependencies Verified

### Import Paths
```python
from pflow.core.ir_schema import validate_ir, ValidationError
from pflow.runtime.template_validator import TemplateValidator
from pflow.registry import Registry
```

### Key Patterns from Subtask 4
- `_parse_structured_response()` helper available
- Lazy model loading in exec()
- Anthropic nested response: content[0]['input']
- North Star examples for testing

## Success Criteria
- ✅ Unused inputs detected and reported
- ✅ Node types validated against registry
- ✅ Correct action strings returned
- ✅ Top 3 errors for retry
- ✅ Metadata extracted
- ✅ Integration with GeneratorNode works
- ✅ All tests pass
- ✅ make test and make check pass

## Implementation Order
1. Create TemplateValidator enhancement
2. Write tests for enhancement
3. Implement ValidatorNode
4. Test ValidatorNode routing
5. Implement MetadataGenerationNode
6. Test metadata extraction
7. Integration tests
8. Update progress log