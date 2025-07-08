# Evaluation for 4.4

## Ambiguities Found

### 1. Edge Field Name Mismatch - Severity: 5

**Description**: The IR examples in `examples/` use `"from"/"to"` for edges, but the compiler expects `"source"/"target"`. This is a critical mismatch that will cause all example-based tests to fail.

**Why this matters**: Integration tests using real IR examples will fail immediately without resolution.

**Options**:
- [x] **Option A**: Update compiler to accept both formats (from/to and source/target)
  - Pros: Works with existing examples, backwards compatible
  - Cons: Adds complexity to handle two formats
  - Similar to: Common pattern in APIs that evolve

- [ ] **Option B**: Update all examples to use source/target
  - Pros: Single consistent format
  - Cons: Breaks existing examples, requires mass updates
  - Risk: May miss some examples or documentation

- [ ] **Option C**: Keep compiler as-is, create new test examples
  - Pros: No changes to existing code
  - Cons: Can't use existing examples for testing
  - Risk: Test examples diverge from real examples

**Recommendation**: Option A - Update compiler to accept both formats. This is the most pragmatic approach that maintains compatibility while allowing us to use existing examples for testing.

### 2. IR Validation Integration - Severity: 3

**Description**: The compiler doesn't call `validate_ir()` from `pflow.core` before compilation. Should integration tests assume pre-validated IR or test the full pipeline?

**Why this matters**: Determines scope of integration tests and error handling expectations.

**Options**:
- [x] **Option A**: Test both validated and unvalidated IR paths
  - Pros: More comprehensive testing, catches integration issues
  - Cons: Larger test scope
  - Similar to: End-to-end testing best practices

- [ ] **Option B**: Only test with pre-validated IR
  - Pros: Focused on compiler functionality
  - Cons: Misses real-world usage patterns
  - Risk: Integration issues go undetected

**Recommendation**: Option A - Test both paths to ensure robust integration.

### 3. Mock Node Implementation Level - Severity: 2

**Description**: How sophisticated should mock nodes be for integration testing?

**Why this matters**: Affects test reliability and maintenance burden.

**Options**:
- [x] **Option A**: Create realistic mock nodes with actual behavior
  - Pros: Tests closer to real usage, can test execution
  - Cons: More complex to create and maintain
  - Similar to: PocketFlow's own test approach

- [ ] **Option B**: Create minimal mock nodes that just track calls
  - Pros: Simple, focused on compilation
  - Cons: Can't test actual execution
  - Risk: Miss runtime issues

**Recommendation**: Option A - Create realistic mocks following PocketFlow test patterns for better coverage.

## Conflicts with Existing Code/Decisions

### 1. Performance Benchmark Location
- **Current state**: No performance tests exist
- **Task assumes**: Performance testing in integration tests
- **Resolution needed**: Confirm if performance should be part of integration tests or separate

## Implementation Approaches Considered

### Approach 1: Comprehensive Integration Suite
- Description: Full test_compiler_integration.py with all features
- Pros: Complete coverage, follows subtask description exactly
- Cons: Large file, might be harder to maintain
- Decision: Selected - matches requirements

### Approach 2: Modular Test Files
- Description: Split into multiple focused test files
- Pros: Better organization, easier to maintain
- Cons: Deviates from subtask specification
- Decision: Rejected - can refactor later if needed

### Approach 3: Minimal Integration + E2E Tests
- Description: Basic integration tests plus separate E2E suite
- Pros: Clear separation of concerns
- Cons: Not what was requested
- Decision: Rejected - doesn't meet requirements

## Test Data Strategy

### IR Examples Organization
Based on sub-agent findings:
- Use existing examples from `examples/core/` for valid IR
- Use `examples/invalid/` for error testing
- Create additional mock nodes as needed
- Adapt edge format as per decision above

### Mock Node Categories Needed
1. **Basic Nodes**: Simple input/output for flow testing
2. **Conditional Nodes**: For testing branching logic
3. **Error Nodes**: For testing error handling
4. **Performance Nodes**: For benchmarking (with delays)
5. **Parameter Nodes**: For testing parameter passing
