# Implementation Plan for 15.2

## Objective
Implement two-phase context building functions that enable the Natural Language Planner to browse components efficiently (discovery) and get detailed information only for selected items (planning), preventing LLM overwhelm.

## Implementation Steps

1. [ ] Examine existing context_builder.py structure
   - File: `src/pflow/planning/context_builder.py`
   - Change: Understand current helper methods and imports
   - Test: Read and verify line numbers match technical guide

2. [ ] Implement build_discovery_context()
   - File: `src/pflow/planning/context_builder.py`
   - Change: Add new function after existing build_context()
   - Test: Call with various node counts and verify lightweight output

3. [ ] Implement build_planning_context()
   - File: `src/pflow/planning/context_builder.py`
   - Change: Add function with error checking logic
   - Test: Verify error dict returned for missing components

4. [ ] Implement _format_structure_combined()
   - File: `src/pflow/planning/context_builder.py`
   - Change: Add helper to generate JSON + paths format
   - Test: Verify correct path extraction from nested structures

5. [ ] Create comprehensive test file
   - File: `tests/test_planning/test_context_builder_phases.py`
   - Change: Create new test file with discovery and planning tests
   - Test: Run pytest on new file

6. [ ] Update existing tests if needed
   - File: `tests/test_planning/test_context_builder.py`
   - Change: Update any tests that depend on build_context() behavior
   - Test: Ensure all existing tests still pass

## Pattern Applications

### Previous Task Patterns
- Using **Registry Pattern** from Task 15.1 for error handling in planning context
- Using **Three-Layer Validation** from Task 15.1 for component checking
- Avoiding **Function Complexity** pitfall by keeping functions focused
- Using **Path Objects** for workflow directory handling

### Key Conventions to Follow
- Exclusive params pattern is already implemented in _format_node_section()
- No placeholder text for missing descriptions
- Error dict format with specific keys: "error", "missing_nodes", "missing_workflows"
- Do NOT modify any parser regex patterns

## Risk Mitigations
- **Parser Modification Risk**: Will only reuse existing methods, no regex changes
- **Complexity Risk**: Keep each function focused on single responsibility
- **Test Breaking Risk**: Run existing tests frequently to catch regressions early
- **Integration Risk**: Test with actual registry data, not just mocks
