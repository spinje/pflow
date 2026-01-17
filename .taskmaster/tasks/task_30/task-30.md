# Task 30: Refactor Validation Functions from compiler.py

## Description
Extract validation functions from the compiler module into a separate workflow_validator.py module to improve code organization and separation of concerns. This refactoring will reduce compiler.py size by ~110 lines while maintaining exact behavior and making validation logic easier to test in isolation.

## Status
done

## Completed
2025-07-29

## Dependencies
None

## Priority
medium

## Details
After analyzing the validation functions in `src/pflow/runtime/compiler.py`, we identified that the module has grown large (~745 lines) with mixed concerns. This task extracts two of the three validation functions into a new module while keeping one that's tightly coupled to compilation.

### Functions to Extract
1. **`_validate_ir_structure()`** (lines 99-146) - Pure validation of IR structure with no side effects
2. **`_validate_inputs()`** (lines 470-541) - Validates inputs AND applies defaults (note: this mutates initial_params)

### Function to Keep in Compiler
- **`_validate_outputs()`** (lines 543-615) - Remains in compiler because:
  - It's really static analysis, not validation (only produces warnings)
  - Has cross-module dependencies (uses TemplateValidator._extract_node_outputs)
  - Contains workflow-specific logic embedded in the function
  - Deeply coupled to compilation context

### Key Design Decisions
- **Honest naming**: Rename `_validate_inputs()` to `prepare_inputs()` to reflect that it both validates AND applies defaults
- **Explicit mutations**: Return defaults from prepare_inputs() and apply them explicitly in the compiler (no hidden mutations)
- **Pure functions**: Make extracted functions pure where possible (except for logging)
- **Maintain behavior**: Keep all error messages, logging, and behavior identical

### Technical Considerations
- Handle potential circular import with CompilationError (defined in compiler.py)
- Preserve all logger.debug() and extra fields for compatibility
- Ensure test files don't directly import these private functions
- The mutation of initial_params must remain visible in the compiler

### Implementation Approach
1. Create `src/pflow/runtime/workflow_validator.py`
2. Extract and make public: `validate_ir_structure()`
3. Extract and refactor: `prepare_inputs()` to return (errors, defaults)
4. Update compiler to use new module and apply mutations explicitly
5. Verify line count reduction is 100-120 lines

## Test Strategy
The refactoring must maintain exact behavior, so existing tests should pass without modification:

- All existing compiler tests must pass unchanged
- Verify `prepare_inputs()` correctly returns errors for missing required inputs
- Verify `prepare_inputs()` correctly returns defaults for missing optional inputs
- Test edge cases like invalid Python identifiers, None vs missing values
- Confirm compiler behavior is identical for all test workflows
- Add focused unit tests for the new workflow_validator module
- Measure and verify the line count reduction in compiler.py
