# Task 36 Implementation Plan

## Context Gathered

### Current Implementation Issues
- `_format_all_parameters` (lines 676-703) shows "Parameters: none" for nodes without exclusive params
- "Inputs" section suggests nodes can read from shared store directly (they can't with namespacing)
- Template variable examples use unhelpful placeholders like "${key}"
- Inconsistent format between nodes with/without exclusive params

### Test Dependencies
- `test_context_builder_phases.py` expects "Parameters: none" assertions
- Tests check for "Inputs" section which will be removed
- Need to update assertions for new format

### Key Functions to Modify
1. `_format_node_section_enhanced` (lines 781-832) - Main formatting function
2. `_format_all_parameters` (lines 676-703) - Currently shows misleading info
3. Will create new functions rather than modifying existing to avoid confusion

## Implementation Steps

### Phase 1: Capture Current Output (5 minutes)
1. Create script to capture current context output
2. Save for before/after comparison
3. Document problematic patterns

### Phase 2: Add New Functions (30 minutes)
These can be done in parallel as they don't depend on each other:

1. **Create _format_all_parameters_new**
   - Location: Add new function (don't modify existing yet)
   - Purpose: Show ALL parameters clearly without exclusive params distinction
   - Shows both inputs and config params in one section

2. **Create _format_outputs_with_access**
   - Location: Add new function
   - Purpose: Show namespaced output access pattern
   - Include "(access as ${node_id.output_key})" in header

3. **Create _format_usage_example**
   - Location: Add new function
   - Purpose: Generate concrete JSON examples
   - Use realistic values, not "${key}" placeholders

### Phase 3: Update Core Function (15 minutes)
1. **Modify _format_node_section_enhanced**
   - Dependencies: Phase 2 complete
   - Changes:
     - Remove "Inputs" section
     - Use new _format_all_parameters_new instead of _format_all_parameters
     - Use new _format_outputs_with_access
     - Add _format_usage_example call
   - Keep complex structure display working

### Phase 4: Clean Up (10 minutes)
1. Comment out old _format_all_parameters function
2. Comment out _add_template_usage_example function (replaced by _format_usage_example)
3. Keep other helper functions that are still needed

### Phase 5: Testing (30 minutes)
1. Update test assertions in test_context_builder_phases.py
   - Replace "Parameters: none" checks
   - Remove "Inputs" section checks
   - Add new format checks
2. Run tests to verify no regressions
3. Test with real workflow generation

### Phase 6: Validation (15 minutes)
1. Create before/after comparison
2. Verify all 15 test criteria from spec
3. Document improvements

## Implementation Order

1. Capture current output FIRST
2. Add all three new functions (can be parallel)
3. Update _format_node_section_enhanced to use new functions
4. Comment out old functions
5. Update tests
6. Validate

## Risk Mitigation

| Risk | Mitigation Strategy |
|------|-------------------|
| Breaking existing tests | Update assertions before running full test suite |
| Complex structure display breaks | Test with github-get-issue node specifically |
| Performance impact | Keep logic simple, no expensive operations |
| Missing edge cases | Test with nodes of different types |

## Validation Strategy

### Unit Testing
- Verify new format for all node types
- Check JSON examples are valid
- Ensure consistent format

### Integration Testing
- Test workflow generation with new format
- Verify template variables work correctly
- Test multiple same-type nodes

### Manual Validation
- Visual inspection of output
- Compare before/after
- Test with real planning requests

## Success Criteria

Must achieve all 15 test criteria from spec:
1. ✅ Parameters section present for all nodes
2. ✅ No "Inputs" section appears
3. ✅ No "Parameters: none" for nodes with inputs
4. ✅ All parameters shown including exclusive
5. ✅ Output section includes namespacing pattern
6. ✅ JSON example present for every node
7. ✅ JSON examples are valid syntax
8. ✅ Template variables use realistic values
9. ✅ Optional parameters marked
10. ✅ Default values shown
11. ✅ Complex structures display JSON format
12. ✅ Test file assertions updated
13. ✅ Context size under 200KB limit
14. ✅ All existing tests pass
15. ✅ Planner can generate valid workflows

## Notes

- Do NOT add instructions or explanations in the context output
- Keep the implementation simple and efficient
- Focus on clarity of presentation, not cleverness
- The goal is to eliminate confusion about parameters