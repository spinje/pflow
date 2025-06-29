# Refined Specification for 4.4

## Clear Objective
Create comprehensive integration tests for the IR compiler that validate end-to-end compilation with real IR examples, ensure <100ms performance, and verify error message quality while supporting both edge field formats.

## Context from Knowledge Base
- Building on: Module pattern (4.1), CompilationError rich context (4.1-4.3), MockNode pattern (4.3), structured logging (4.1)
- Avoiding: Logging field conflicts (use "module_path"), type safety issues, missing BaseNode inheritance
- Following: 100% coverage standard, test-as-you-go strategy, direct PocketFlow usage
- **Cookbook patterns to apply**: Test node creation patterns from pocketflow/tests, flow testing patterns, performance measurement approaches

## Technical Specification
### Inputs
- IR examples from `examples/` directory (JSON files)
- Mock registry with test nodes
- Both validated and unvalidated IR for different test paths

### Outputs
- Compiled pocketflow.Flow objects
- Performance metrics (<100ms for 5-10 nodes)
- Error messages with actionable suggestions
- Test coverage report (target: 95%+)

### Implementation Constraints
- Must use: PocketFlow test patterns for mock nodes, pytest fixtures for setup
- Must avoid: Wrapper abstractions, reserved logging field names
- Must maintain: Support for both edge formats (from/to and source/target)

## Success Criteria
- [ ] All existing IR examples compile successfully
- [ ] Compilation time <100ms for workflows with 5-10 nodes
- [ ] Error messages include helpful suggestions (e.g., "Did you mean 'llm-node'?")
- [ ] Integration with real registry from Task 5 works
- [ ] Mock nodes inherit from BaseNode and track behavior
- [ ] Tests cover all compiler phases (parse, validate, instantiate, wire)
- [ ] Both validated and unvalidated IR paths tested
- [ ] 95%+ code coverage across compiler modules
- [ ] Edge field format compatibility (from/to and source/target)

## Test Strategy
- **Unit tests**: Already exist (keep and enhance)
- **Integration tests**: New test_compiler_integration.py with:
  - End-to-end compilation tests
  - Real IR example tests
  - Mock node execution tests
  - Performance benchmarks
  - Error message quality tests
- **Manual verification**: Run compiled flows to ensure execution works

## Dependencies
- Requires: Compiler implementation from 4.1-4.3, registry from Task 5, IR examples
- Impacts: Future tests can use established mock patterns

## Decisions Made
- **Edge field compatibility**: Compiler will accept both from/to and source/target (User confirmed on 2025-06-29)
- **Test both IR paths**: Include validated and unvalidated IR tests
- **Realistic mock nodes**: Create behavioral mocks following PocketFlow patterns

## Implementation Details

### 1. Update Compiler for Edge Compatibility
First update `_wire_nodes()` in compiler.py to handle both formats:
```python
source = edge.get("source") or edge.get("from")
target = edge.get("target") or edge.get("to")
```

### 2. Create Mock Nodes
Following PocketFlow patterns:
- BasicMockNode: Simple pass-through behavior
- ConditionalMockNode: Returns different actions
- ErrorMockNode: Simulates failures for error testing
- PerformanceMockNode: Adds delays for benchmarking

### 3. Test Structure
- test_compiler_integration.py with sections:
  - Mock node definitions
  - Registry setup fixtures
  - End-to-end compilation tests
  - IR example tests
  - Performance benchmarks
  - Error message quality tests

### 4. Performance Testing
- Use time.perf_counter() for accurate timing
- Test with varying node counts (1, 5, 10, 20)
- Assert compilation <100ms for typical workflows

### 5. Error Message Testing
- Verify suggestions for typos
- Check context includes phase and node info
- Ensure actionable error messages
