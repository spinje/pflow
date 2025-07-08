# Implementation Plan for 4.4

## Objective
Create comprehensive integration tests for the IR compiler that validate end-to-end compilation with real IR examples, ensure <100ms performance, and verify error message quality while supporting both edge field formats.

## Implementation Steps
1. [ ] Update compiler to support both edge field formats
   - File: src/pflow/runtime/compiler.py
   - Change: Modify _wire_nodes() to accept from/to and source/target
   - Test: Verify existing tests still pass

2. [ ] Create mock node classes for testing
   - File: tests/test_compiler_integration.py
   - Change: Add BasicMockNode, ConditionalMockNode, ErrorMockNode, PerformanceMockNode
   - Test: Each inherits BaseNode and has specific behavior

3. [ ] Set up test registry fixtures
   - File: tests/test_compiler_integration.py
   - Change: Create fixture that returns mock registry data
   - Test: Registry contains all mock node types

4. [ ] Implement end-to-end compilation tests
   - File: tests/test_compiler_integration.py
   - Change: Test full IR → Flow compilation with execution
   - Test: Compiled flows execute and produce expected results

5. [ ] Add IR example tests
   - File: tests/test_compiler_integration.py
   - Change: Load and compile real examples from examples/core/
   - Test: All valid examples compile successfully

6. [ ] Create performance benchmarks
   - File: tests/test_compiler_integration.py
   - Change: Add tests measuring compilation time for various node counts
   - Test: Assert <100ms for 5-10 node workflows

7. [ ] Test error message quality
   - File: tests/test_compiler_integration.py
   - Change: Test various error scenarios with actionable message checks
   - Test: Error messages include helpful suggestions

8. [ ] Integration with real registry
   - File: tests/test_compiler_integration.py
   - Change: Test with actual Registry instance from Task 5
   - Test: Real registry integration works if nodes exist

9. [ ] Polish and documentation
   - File: src/pflow/runtime/compiler.py
   - Change: Add/improve docstrings and inline comments
   - Test: Code follows conventions, all tests pass

10. [ ] Run coverage and quality checks
    - File: N/A
    - Change: Run pytest with coverage, then make check
    - Test: 95%+ coverage, all quality checks pass

## Pattern Applications

### Cookbook Patterns (only potentially applicable to tasks that can leverage pocketflow)
- **Test Node Creation Pattern**: Create mock nodes with prep/exec/post lifecycle
  - Specific code/approach: Inherit from Node, implement minimal behavior
  - Modifications needed: Adapt to simulate pflow-specific nodes

- **Flow Testing Pattern**: Test compiled flows by running them
  - Specific code/approach: Use flow.run(shared_storage) and verify results
  - Modifications needed: None, direct application

- **Performance Measurement Pattern**: Use time.perf_counter() for benchmarks
  - Specific code/approach: Measure compilation time in milliseconds
  - Modifications needed: Focus on compilation, not execution time

### Previous Task Patterns
- Using MockNode with connection tracking from 4.3 for verifying flow structure
- Avoiding logging field conflicts discovered in 4.2
- Following module pattern from 4.1 for test organization

## Risk Mitigations
- [Edge format change breaks existing tests]: Run tests after each change to catch regressions
- [Performance benchmarks are flaky]: Use multiple runs and take median time
- [Real registry not available]: Make registry tests conditional with pytest.mark.skipif
