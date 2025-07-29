# Task 30: Implementation Plan - Refactor Validation Functions

## Context Summary

We're extracting two validation functions from `compiler.py` (~745 lines) into a new `workflow_validator.py` module to reduce compiler size by ~110 lines. The key challenge is that `_validate_inputs()` secretly mutates data, which we'll make explicit.

## Task Breakdown

### Phase 1: Context Gathering (Parallel Execution)
Deploy multiple subagents to gather all necessary context simultaneously.

#### 1.1 Current Function Analysis
**Subagent Task 1**: "Analyze validation functions in src/pflow/runtime/compiler.py"
- Extract exact code for `_validate_ir_structure()` (lines 99-146)
- Extract exact code for `_validate_inputs()` (lines 470-541)
- Extract exact code for `_validate_outputs()` (lines 543-615)
- Note all imports these functions use
- Identify mutation points (especially line 527)

#### 1.2 Usage Analysis
**Subagent Task 2**: "Find all calls to validation functions in compiler.py"
- Find where `_validate_ir_structure()` is called
- Find where `_validate_inputs()` is called
- Find where `_validate_outputs()` is called
- Note the context and error handling around each call

#### 1.3 Import Dependencies
**Subagent Task 3**: "Check for external imports of private validation functions"
- Search all test files for imports of `_validate_ir_structure`
- Search all test files for imports of `_validate_inputs`
- Check if CompilationError is used in other modules
- Analyze potential circular import issues

#### 1.4 Template Validator Analysis
**Subagent Task 4**: "Analyze _validate_outputs dependency on TemplateValidator"
- Find `TemplateValidator._extract_node_outputs()` usage
- Document the workflow-specific logic (lines 581-587)
- Understand why this coupling exists

### Phase 2: Module Creation (Sequential)

#### 2.1 Create workflow_validator.py
- Create file at `src/pflow/runtime/workflow_validator.py`
- Add necessary imports:
  ```python
  import logging
  from typing import Any
  from .compiler import CompilationError
  from ..core.ir_schema import ValidationError
  ```
- Add module docstring explaining its purpose

#### 2.2 Extract validate_ir_structure
- Copy function from compiler.py (lines 99-146)
- Remove underscore prefix to make public
- Keep all error messages identical
- Preserve all logging statements with extra fields
- No behavioral changes

#### 2.3 Extract and refactor _validate_inputs
- Copy function from compiler.py (lines 470-541)
- Rename to `prepare_inputs()`
- Refactor to return `(errors: list[str], defaults: dict[str, Any])`
- Remove mutation of `initial_params`
- Collect errors in list instead of raising immediately
- Build defaults dict for missing optional inputs

### Phase 3: Update Compiler (Sequential)

#### 3.1 Update imports
- Add: `from .workflow_validator import validate_ir_structure, prepare_inputs`
- Remove old function imports if any

#### 3.2 Update validate_ir_structure usage
- Replace `self._validate_ir_structure(ir_dict)` with `validate_ir_structure(ir_dict)`
- Keep error handling identical

#### 3.3 Update _validate_inputs usage
- Replace validation call with:
  ```python
  errors, defaults = prepare_inputs(ir_dict, initial_params)
  if errors:
      raise ValidationError(errors[0])  # Use first error
  initial_params.update(defaults)  # Explicit mutation
  ```
- Ensure mutation is visible and explicit

#### 3.4 Remove old functions
- Delete `_validate_ir_structure()` from compiler.py
- Delete `_validate_inputs()` from compiler.py
- Keep `_validate_outputs()` unchanged

### Phase 4: Testing and Verification (Parallel where possible)

#### 4.1 Run existing tests
**Subagent Task 5**: "Run all compiler tests"
- Execute: `pytest tests/test_runtime/test_compiler.py -v`
- Document any failures

#### 4.2 Test edge cases
**Subagent Task 6**: "Test validation edge cases"
- Test with missing required inputs
- Test with missing optional inputs
- Test with invalid Python identifiers
- Test None vs missing values

#### 4.3 Verify line count
- Count lines in compiler.py before and after
- Ensure reduction is 100-120 lines

#### 4.4 Run full test suite
- Execute: `make test`
- Execute: `make check`

### Phase 5: Final Cleanup

#### 5.1 Update any test imports
- Check if any tests import the private functions directly
- Update imports if necessary

#### 5.2 Add module tests
- Create focused unit tests for workflow_validator.py
- Test `validate_ir_structure()` with various invalid inputs
- Test `prepare_inputs()` return values

## Dependency Mapping

```
Phase 1 (all parallel) → Phase 2.1 → Phase 2.2 → Phase 2.3 → Phase 3 (sequential) → Phase 4 (partial parallel) → Phase 5
```

Key dependencies:
- Must complete all context gathering before creating module
- Must create module before extracting functions
- Must extract both functions before updating compiler
- Can run some tests in parallel after compiler updates

## Risk Identification and Mitigation

### Risk 1: Circular Import with CompilationError
**Mitigation**: Import at module level should work due to import-time evaluation. If issues arise, consider moving exception classes to separate module.

### Risk 2: Hidden External Imports
**Mitigation**: Comprehensive search in Phase 1.3 will identify any external imports. If found, update them as part of Phase 5.

### Risk 3: Mutation Behavior Change
**Mitigation**: Explicit mutation in compiler makes behavior clear. Tests will catch any behavioral differences.

### Risk 4: Logger Extra Fields
**Mitigation**: Preserve all logger calls exactly as-is, including extra fields that might be parsed by external systems.

## Testing Strategy

### Unit Tests for New Module
- Test `validate_ir_structure()` with missing 'nodes' key
- Test `validate_ir_structure()` with non-list 'edges' value
- Test `prepare_inputs()` returns errors for missing required inputs
- Test `prepare_inputs()` returns defaults for missing optional inputs
- Test edge cases: invalid identifiers, None values, empty defaults

### Integration Tests
- All existing compiler tests must pass unchanged
- Verify compiler behavior identical for all test workflows
- Ensure no performance regressions

### Verification Criteria
- ✅ All existing tests pass
- ✅ Line count reduction: 100-120 lines
- ✅ No behavioral changes
- ✅ Mutations are explicit
- ✅ Error messages unchanged
- ✅ Logging preserved

## Implementation Timeline

1. **Context Gathering**: 15 minutes (parallel)
2. **Module Creation**: 30 minutes
3. **Function Extraction**: 45 minutes
4. **Compiler Updates**: 30 minutes
5. **Testing**: 30 minutes
6. **Cleanup**: 15 minutes

Total estimated time: 2.5-3 hours

## Success Metrics

- All tests pass without modification
- Compiler.py reduced by 100-120 lines
- Clean separation of concerns
- Honest function naming
- Explicit mutations
- No circular import issues
