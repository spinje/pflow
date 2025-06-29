# Refined Specification for Subtask 5.3

## Clear Objective
Extend existing test suites with comprehensive edge case coverage, security validation, and integration scenarios to ensure the node discovery system is robust and production-ready.

## Context from Knowledge Base
- Building on: Test-as-you-go pattern, real integration tests over mocks (Task 5.1)
- Avoiding: Over-mocking dynamic imports, permission test cleanup issues
- Following: Extend existing test files pattern, use tempfile for isolation
- **Key Learning Applied**: "Mocks are insufficient for dynamic loading" - will use real tests

## Technical Specification

### Inputs
- Existing test files: tests/test_scanner.py and tests/test_registry.py
- Test fixtures: Various Python files in tests/fixtures/ representing edge cases
- Current implementations: Scanner and Registry classes from 5.1 and 5.2

### Outputs
- Extended test_scanner.py with 15-20 additional edge case tests
- Extended test_registry.py with 5-10 additional integration tests
- Test fixtures directory with malformed/edge-case Python files
- Maintained test coverage >90% for both modules

### Implementation Constraints
- Must use: Real imports for core functionality tests (not mocks)
- Must avoid: Executing actually malicious code (use controlled test fixtures)
- Must maintain: Existing test structure and naming conventions
- Must include: Security warning validation (documentation level)

## Success Criteria
- [ ] All existing tests continue to pass
- [ ] Edge cases for malformed Python files are tested
- [ ] Security warnings in code/docs are validated
- [ ] Multiple inheritance scenarios are covered
- [ ] Circular import handling is tested
- [ ] Integration tests cover error scenarios
- [ ] Test coverage remains >90% for both modules
- [ ] No test pollution between test runs

## Test Strategy

### Scanner Edge Case Tests
1. **Syntax Error Handling**
   - Create fixture with Python syntax errors
   - Verify scanner continues past error
   - Check appropriate warning is logged

2. **Import Variation Tests**
   - Test `from pocketflow import Node` (should NOT find)
   - Test `import pocketflow as pf` with `pf.BaseNode`
   - Test relative imports within packages

3. **Inheritance Edge Cases**
   - Multiple inheritance with BaseNode
   - Indirect inheritance chains
   - Abstract base classes (shouldn't register)

4. **File System Edge Cases**
   - Empty Python files
   - Non-UTF8 encoded files
   - Very large Python files (performance baseline)

### Registry Integration Tests
1. **Error Recovery Scenarios**
   - Scanner with partial failures
   - Registry update with some invalid nodes
   - Handling of duplicate names from scanner

2. **Data Integrity Tests**
   - Unicode in node names/docstrings
   - Very large registry handling
   - Concurrent access simulation (if time permits)

### Security Validation Tests
1. **Warning Verification**
   - Check scanner module has security docstring
   - Verify logging includes security considerations
   - Test fixture that "executes" code on import (controlled)

2. **Path Safety**
   - Test scanning with relative paths
   - Verify can't escape allowed directories

## Dependencies
- Requires: Existing scanner and registry implementations
- Requires: tests/fixtures/ directory creation
- Impacts: Future maintainers will have comprehensive test examples

## Decisions Made
- **File Organization**: Extend existing test files (User confirmed via Option A selection)
- **Mock Strategy**: Use real tests, mock only for dangerous operations (Based on 5.1 learning)
- **Security Focus**: Test warning presence, not actual sandboxing (MVP scope limitation)
- **Fixture Location**: tests/fixtures/ for malformed test files (Avoids polluting nodes/)
- **Coverage Target**: Maintain >90% but be pragmatic about untestable scenarios

## Implementation Order
1. Create tests/fixtures/ directory structure
2. Add scanner edge case tests (highest priority)
3. Add security validation tests
4. Add registry integration tests
5. Performance baseline tests (if time permits)
6. Update any documentation as needed
