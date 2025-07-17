# Implementation Plan for Subtask 14.2

## Objective
Add structure navigation hints to the context builder's output for complex types (dict/list) while maintaining the existing type display functionality.

## Implementation Steps

1. [ ] Add _extract_navigation_paths() helper function
   - File: `src/pflow/planning/context_builder.py`
   - Change: Add new function to extract navigation paths from structure dict
   - Test: Unit test with various structure types

2. [ ] Update _format_node_section() for inputs
   - File: `src/pflow/planning/context_builder.py`
   - Change: Add navigation hints for dict/list inputs with structures
   - Test: Verify hints appear in formatted output

3. [ ] Update _format_node_section() for outputs
   - File: `src/pflow/planning/context_builder.py`
   - Change: Add navigation hints for dict/list outputs with structures
   - Test: Verify hints appear with actions preserved

4. [ ] Update _format_node_section() for params
   - File: `src/pflow/planning/context_builder.py`
   - Change: Add navigation hints for dict/list params (rare but possible)
   - Test: Verify exclusive params still work with hints

5. [ ] Add structure hint limiting
   - File: `src/pflow/planning/context_builder.py`
   - Change: Add counter in build_context() to limit hints to first 20-30
   - Test: Verify limit works with many complex nodes

6. [ ] Create unit tests
   - File: `tests/test_planning/test_context_builder.py`
   - Change: Add tests for _extract_navigation_paths()
   - Test: Various structures, edge cases, depth limits

7. [ ] Create integration tests
   - File: `tests/test_planning/test_context_builder.py`
   - Change: Add tests for full formatting with structures
   - Test: Complete node formatting with navigation hints

## Pattern Applications

### Cookbook Patterns
Not applicable - this task doesn't use PocketFlow

### Previous Task Patterns
- Using **Rich Format Handling** from Task 14.1 for understanding structure format
- Avoiding **Regex Complexity Explosion** by using simple dict traversal
- Following **Minimal Changes** pattern - only adding, not modifying existing

## Risk Mitigations
- **Risk**: Breaking existing type display
  - **Mitigation**: Only add to existing format strings, don't replace
- **Risk**: Exceeding 50KB limit
  - **Mitigation**: Implement hint counter early, test with large datasets
- **Risk**: Circular references in structures
  - **Mitigation**: Track visited paths, limit recursion depth
