# Implementation Plan for Subtask 6.1

## Objective
Create JSON Schema definitions for workflow IR in a Python module that enables validation of workflow structures before execution.

## Implementation Steps

1. [ ] Add jsonschema dependency to pyproject.toml
   - File: `pyproject.toml`
   - Change: Add `jsonschema = "^4.20.0"` to dependencies
   - Test: Run `uv pip install -e .` to verify installation

2. [ ] Create core package structure
   - File: `src/pflow/core/__init__.py`
   - Change: Create file with minimal exports
   - Test: Verify package imports correctly

3. [ ] Define JSON Schema for workflow IR
   - File: `src/pflow/core/ir_schema.py`
   - Change: Create `FLOW_IR_SCHEMA` constant with schema definition
   - Test: Validate schema structure is valid JSON Schema

4. [ ] Implement custom ValidationError class
   - File: `src/pflow/core/ir_schema.py`
   - Change: Create custom exception with field path support
   - Test: Verify error messages are clear and helpful

5. [ ] Implement validate_ir() function
   - File: `src/pflow/core/ir_schema.py`
   - Change: Add validation function with custom error formatting
   - Test: Test with valid and invalid IR examples

6. [ ] Add comprehensive module documentation
   - File: `src/pflow/core/ir_schema.py`
   - Change: Add module docstring with usage examples
   - Test: Verify examples in docstring work correctly

7. [ ] Create test file with comprehensive test cases
   - File: `tests/test_ir_schema.py`
   - Change: Add tests for all validation scenarios
   - Test: Run pytest to ensure all tests pass

8. [ ] Run quality checks
   - Command: `make check`
   - Change: Fix any linting or type errors
   - Test: Ensure all checks pass

## Pattern Applications

### Previous Task Patterns
- Using **Python Package Module Structure** from Task 1 for clean package organization
- Using **Test-As-You-Go Development** pattern - writing tests immediately after each feature
- Using **Graceful JSON Configuration Loading** from Task 5 for error handling
- Using **Registry Storage Without Key Duplication** pattern - nodes as array with 'id' field
- Using **Direct Validation Without Abstraction** from Task 2 for custom error messages

### Cookbook Patterns
- No PocketFlow cookbook patterns directly applicable (this is pure schema definition)
- Note: Avoided complex Pydantic patterns from cookbook as per research decisions

## Risk Mitigations
- **Risk**: jsonschema API changes could break validation
  - **Mitigation**: Pin to stable major version (^4.20.0)

- **Risk**: Schema too strict for future needs
  - **Mitigation**: Use versioning field, design for extensibility

- **Risk**: Error messages too technical for users
  - **Mitigation**: Wrap jsonschema errors with user-friendly messages

- **Risk**: Missing edge cases in validation
  - **Mitigation**: Comprehensive test coverage including edge cases
