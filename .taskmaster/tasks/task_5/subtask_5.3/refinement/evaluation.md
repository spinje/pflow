# Evaluation for Subtask 5.3

## Ambiguities Found

### 1. Test File Organization - Severity: 3

**Description**: The subtask mentions creating tests/test_scanner.py and tests/test_registry.py, but these files already exist from subtasks 5.1 and 5.2. Should we extend existing files or create new ones?

**Why this matters**: Test organization affects maintainability and clarity. Wrong approach could lead to duplicated tests or confusing structure.

**Options**:
- [x] **Option A**: Extend existing test files with additional test methods for edge cases
  - Pros: Keeps all related tests together, follows established pattern
  - Cons: Files might become large
  - Similar to: Task 2.3 extended existing test_cli_core.py

- [ ] **Option B**: Create new test files like test_scanner_edge_cases.py
  - Pros: Separates edge case tests from core functionality
  - Cons: Fragments test coverage across multiple files
  - Risk: Harder to see full test coverage at a glance

**Recommendation**: Option A because it follows the established pattern from previous tasks and keeps related tests cohesive.

### 2. Mock vs Real Testing Balance - Severity: 4

**Description**: The requirements mention "mock importlib operations" but Task 5.1 discovered that "mocks are insufficient for dynamic loading". How should we balance mocks vs real tests?

**Why this matters**: Wrong approach could lead to tests that pass but don't catch real issues, or tests that are fragile and environment-dependent.

**Options**:
- [x] **Option A**: Use real tests for most scenarios, mock only dangerous operations
  - Pros: More reliable, catches real integration issues
  - Cons: Slightly slower, requires actual test nodes
  - Similar to: Task 5.1's successful integration test approach

- [ ] **Option B**: Mock all importlib operations as suggested
  - Pros: Faster, more isolated tests
  - Cons: May not catch real import issues
  - Risk: Tests pass but real code fails

**Recommendation**: Option A based on the hard-won learning from Task 5.1 that real integration tests are superior for dynamic loading scenarios.

### 3. Security Test Implementation - Severity: 5

**Description**: Requirements mention testing "security warning verification" and mocking to avoid "executing actual node code during discovery". But the scanner DOES execute code via importlib. What exactly should we test?

**Why this matters**: Security is critical. Wrong understanding could lead to inadequate security testing or false sense of security.

**Options**:
- [x] **Option A**: Test that documentation/comments contain security warnings, accept that MVP executes trusted code
  - Pros: Realistic for MVP scope, clear about actual behavior
  - Cons: Doesn't test sandboxing (not in MVP scope)
  - Similar to: MVP's stated limitation of trusted package nodes only

- [ ] **Option B**: Implement actual sandboxing/mocking to prevent code execution
  - Pros: More secure testing
  - Cons: Changes fundamental scanner behavior, not in MVP scope
  - Risk: Major architecture change beyond subtask scope

**Recommendation**: Option A because it aligns with MVP scope and the reality that importlib executes code. Focus on warning documentation.

## Conflicts with Existing Code/Decisions

### 1. Test Node Location
- **Current state**: Test nodes exist in src/pflow/nodes/test_node.py (created in 5.1)
- **Task assumes**: We need to test various malformed nodes
- **Resolution needed**: Should malformed test nodes go in tests/ directory or src/pflow/nodes/?

**Resolution**: Put malformed/edge-case test files in tests/fixtures/ directory to avoid polluting the actual nodes directory with broken code.

### 2. Coverage Expectations
- **Current state**: Scanner has ~95% coverage, Registry has ~100% coverage
- **Task assumes**: Need "comprehensive" tests but some edge cases may be impossible to test
- **Resolution needed**: What's the target coverage for edge cases?

**Resolution**: Aim for maintaining >90% coverage while being pragmatic about untestable scenarios (like true syntax errors that prevent import).

## Implementation Approaches Considered

### Approach 1: Incremental Test Enhancement
- Description: Add new test methods to existing files, focusing on highest-value edge cases
- Pros: Builds on solid foundation, quick to implement
- Cons: May miss some exotic edge cases
- Decision: **Selected** - Most pragmatic for MVP

### Approach 2: Comprehensive Edge Case Suite
- Description: Create exhaustive test suite covering every conceivable edge case
- Pros: Maximum coverage
- Cons: Time-consuming, diminishing returns
- Decision: **Rejected** - Over-engineering for MVP

### Approach 3: Property-Based Testing
- Description: Use hypothesis or similar to generate random test cases
- Pros: Finds unexpected edge cases
- Cons: New dependency, learning curve
- Decision: **Rejected** - Not aligned with current testing approach

## Key Decisions Summary

1. **Extend existing test files** rather than creating new ones
2. **Use real tests with actual imports** for most scenarios
3. **Focus on documentation/warning verification** for security
4. **Put test fixtures in tests/fixtures/** directory
5. **Target >90% coverage** but be pragmatic about untestable code
6. **Prioritize high-value edge cases** over exhaustive testing
