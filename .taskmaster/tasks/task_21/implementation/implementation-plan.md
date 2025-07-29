# Task 21 Implementation Plan - REVISED for Input/Output Declaration

## Critical Update: This is Input AND Output Declaration

After reading all starting context files, Task 21 implements COMPLETE workflow interfaces (both inputs and outputs), not just inputs. This enables workflow composition and validation.

## Context Gathered

### Current Schema Structure
- Uses JSON Schema (Draft 7), NOT Pydantic
- Schema defined in `FLOW_IR_SCHEMA` dict constant
- Optional fields use `"default": {}` or absence from required array
- Validation via `jsonschema.Draft7Validator`

### Compiler Validation Pattern
- Validation happens in `compile_ir_to_flow` function
- Insert point: After IR structure validation (line 519), before template validation
- Error handling uses `ValidationError` with message, path, and suggestion
- Initial params already flow through correctly

### Integration Points
- Template validator receives workflow IR, can access inputs field
- Error messages constructed at lines 66-82 in template validator
- Registry stores node output interfaces for validation
- Existing `_extract_node_outputs` method collects all outputs

## Implementation Steps

### Phase 1: Schema Extension
**Duration: 1-2 hours**
**Dependencies: None**

#### 1.1 Add Input/Output Schema Definitions (Subagent A)
- **File**: `src/pflow/core/ir_schema.py`
- **Task**: Add BOTH `inputs` and `outputs` fields to FLOW_IR_SCHEMA after line 181
- **Context**:
  - Use JSON Schema format (NOT Pydantic!)
  - Follow existing patterns - optional fields with empty dict defaults
  - Input schema: description, required, type, default
  - Output schema: description, type (no required/default)
- **Deliverable**: Complete workflow interface schema (inputs AND outputs)

#### 1.2 Create Schema Validation Tests (Subagent B)
- **File**: `tests/test_core/test_workflow_interfaces.py` (new file)
- **Task**: Write comprehensive tests for BOTH input and output schema validation
- **Context**:
  - Test input validation: required, defaults, types
  - Test output validation: valid names, types
  - Test backward compatibility (missing fields)
  - Test error messages quality
- **Dependencies**: Schema must be defined first (1.1)

### Phase 2: Compiler Input Validation
**Duration: 2-3 hours**
**Dependencies: Phase 1 complete**

#### 2.1 Implement Input Validation Logic (Subagent C)
- **File**: `src/pflow/runtime/compiler.py`
- **Task**: Add `_validate_inputs` helper function and call it after line 519
- **Context**:
  - Validate required inputs are in initial_params
  - Apply default values for optional inputs
  - Raise ValidationError with helpful messages
- **Dependencies**: Schema definition (1.1)

#### 2.2 Implement Output Validation Logic (Subagent D)
- **File**: `src/pflow/runtime/compiler.py`
- **Task**: Add `_validate_outputs` helper function to check declared outputs
- **Context**:
  - Import and use `_extract_node_outputs` from template validator
  - Check if declared outputs exist in union of all node outputs
  - Use registry to get node interface data
  - WARN (not error) if output cannot be traced - nodes may write dynamic keys
  - Support nested workflow outputs via output_mapping
- **Dependencies**: Schema definition (1.1)

#### 2.3 Create Compiler Validation Tests (Subagent E)
- **File**: `tests/test_runtime/test_compiler_interfaces.py` (new file)
- **Task**: Test input validation, default application, output validation
- **Context**: Test missing required inputs, defaults, output validation warnings
- **Dependencies**: Compiler logic (2.1, 2.2)

### Phase 3: Template Validator Enhancement
**Duration: 1-2 hours**
**Dependencies: Phase 1 complete**

#### 3.1 Enhance Error Messages (Subagent F)
- **File**: `src/pflow/runtime/template_validator.py`
- **Task**: Modify error messages at lines 66-82 to include input descriptions
- **Context**:
  - Add helper method `_get_input_description`
  - Check if template variable is declared input
  - Include description and requirements in errors
- **Dependencies**: Inputs field in IR (1.1)

#### 3.2 Test Enhanced Error Messages (Subagent G)
- **File**: `tests/test_runtime/test_template_validator_enhanced.py` (new file)
- **Task**: Test that error messages include input descriptions
- **Context**: Test various error scenarios with helpful messages
- **Dependencies**: Enhanced validator (3.1)

### Phase 4: Integration Testing
**Duration: 1 hour**
**Dependencies: Phases 1-3 complete**

#### 4.1 End-to-End Integration Tests (Subagent H)
- **File**: `tests/test_integration/test_workflow_interfaces.py` (new file)
- **Task**: Test complete workflow execution with input/output declarations
- **Context**:
  - Test workflows with inputs execute correctly
  - Test nested workflows with interfaces
  - Test output usage in parent workflows
- **Dependencies**: All previous phases

#### 4.2 Example Workflows (Subagent I)
- **Files**: `examples/interfaces/` directory with example workflows
- **Task**: Create example workflows showing input/output declarations
- **Context**: Simple examples, complex examples, composition examples
- **Dependencies**: Implementation complete

### Phase 5: Documentation
**Duration: 30 minutes**
**Dependencies: Implementation complete**

#### 5.1 Update Reference Documentation (Me - Main Agent)
- **Files**: Update relevant docs in `docs/reference/`
- **Task**: Document new IR fields and validation behavior
- **Context**: Add to existing docs, don't create new ones

## Risk Mitigation

| Risk | Mitigation Strategy |
|------|-------------------|
| Breaking existing workflows | Inputs/outputs fields are optional with empty dict defaults |
| JSON Schema complexity | Keep schema simple, follow existing patterns exactly |
| Type validation complexity | Types are hints only, no strict validation in MVP |
| Output validation performance | Use existing _extract_node_outputs, cache results |
| Test coverage gaps | Follow comprehensive test patterns from existing tests |

## Validation Strategy

### Schema Validation
- Test all field combinations
- Test invalid names (non-identifiers)
- Test type values
- Test default value presence

### Compiler Validation
- Unit test each validation method
- Integration test full compilation flow
- Test error message quality
- Test backward compatibility

### Manual Testing
- Run example workflows with inputs/outputs
- Test error cases manually
- Verify helpful error messages

## Success Metrics

- ✅ All existing tests pass (no regressions)
- ✅ New tests cover all scenarios (35+ tests)
- ✅ Workflows with interfaces compile and run
- ✅ Error messages include descriptions
- ✅ Backward compatibility maintained
- ✅ make test and make check pass

## Implementation Order

1. Phase 1: Schema Extension (Subagents A, B in parallel)
2. Phase 2: Compiler Validation (Subagents C, D in parallel, then E)
3. Phase 3: Template Enhancement (Subagents F, G in parallel)
4. Phase 4: Integration Testing (Subagents H, I in parallel)
5. Phase 5: Documentation (Main agent)

## Critical Notes

- **JSON Schema, NOT Pydantic** (despite what docs say!)
- **BOTH inputs AND outputs** - complete interfaces
- Keep types as documentation hints only
- Focus on helpful error messages
- Output validation: WARN if can't trace (nodes may write dynamic keys)
- All infrastructure already exists
- This enables workflow composition validation
