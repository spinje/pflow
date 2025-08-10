# Phase 2: Interactive Parameter Collection - Implementation Guide

## Executive Summary

Phase 1 successfully fixed the validation flow by extracting parameters BEFORE validation. However, when parameters cannot be extracted from the initial user input, the system simply fails. Phase 2 adds **interactive parameter collection** to gracefully handle missing parameters by prompting the user for additional information.

## Background: What Was Completed in Phase 1

✅ **Validation Flow Fixed**: Parameters are now extracted before validation
✅ **Both Paths Work**: Path A (reuse) and Path B (generation) properly handle parameters
✅ **Template Validation Fixed**: ValidatorNode validates with actual extracted values

### Current Behavior (After Phase 1)
```
User: "analyze some data"
System: Generates workflow with $input_file, $output_file
System: Tries to extract parameters → Can't find file names
System: Returns "params_incomplete" → Fails with error
User: Gets error message about missing parameters
```

## The Problem: No User Recovery Path

When ParameterMappingNode cannot extract required parameters, it routes to `"params_incomplete"` → ResultPreparationNode → **END**. The user must start over with a more complete query.

This is poor UX because:
1. The system knows exactly what's missing
2. The workflow is already generated and validated
3. Simple prompts could collect the missing values
4. Users shouldn't need to repeat the entire request

## Your Mission: Add Interactive Parameter Collection

Enable the planner to pause, ask for missing parameters, and resume execution.

### Desired Behavior (After Phase 2)
```
User: "analyze some data"
System: Generates workflow with $input_file, $output_file
System: Tries to extract parameters → Can't find file names
System: "I need some additional information:"
System: "input_file (CSV file to analyze): "
User: data.csv
System: "output_file (Output report file): "
User: report.txt
System: Continues with provided parameters → Success!
```

## Implementation Requirements

### 1. Modify ResultPreparationNode
- When `missing_params` exist AND no `validation_errors`:
  - Set `"needs_user_input": True` in output
  - Include `"missing_params_spec"` with parameter descriptions
  - Include `"partial_params"` with any successfully extracted params
  - Include `"workflow_ir"` to enable resumption

### 2. Integrate with CLI (`src/pflow/cli/main.py`)
- Currently has TODO comment for planner integration
- Add planner flow execution
- Detect `"needs_user_input"` status
- Prompt user for each missing parameter
- Support parameter type hints and validation

### 3. Add Flow Resumption Capability
- Create `resume_planner_flow()` function
- Start from ParameterMappingNode with combined parameters
- Merge user-provided params with originally extracted params
- Continue through validation → metadata → result

### 4. Handle Edge Cases
- User cancellation (Ctrl+C)
- Invalid parameter values
- File path validation
- Optional vs required parameters
- Default values

## Success Criteria

1. **Basic Interactive Collection Works**
   - [ ] User can provide missing required parameters via CLI prompts
   - [ ] Flow resumes and completes successfully with provided params

2. **User Experience**
   - [ ] Clear prompts with parameter descriptions
   - [ ] Shows which parameters are required vs optional
   - [ ] Validates input before continuing

3. **State Management**
   - [ ] Original extracted params are preserved
   - [ ] User-provided params are merged correctly
   - [ ] Workflow IR is maintained for resumption

4. **Error Handling**
   - [ ] Graceful handling of user cancellation
   - [ ] Clear error messages for invalid inputs
   - [ ] Option to retry or abort

## Implementation Workflow

### Step 1: Read Context (30 min)
1. Read `interactive-parameter-collection-design.md` (detailed design)
2. Review `src/pflow/cli/main.py` for current CLI structure
3. Understand ResultPreparationNode's current implementation
4. Review ParameterMappingNode's parameter extraction logic

### Step 2: Plan Implementation (20 min)
1. Create implementation checklist
2. Identify test scenarios
3. Document assumptions and decisions

### Step 3: Core Implementation (2 hours)
1. Modify ResultPreparationNode for `needs_user_input` status
2. Add CLI integration in main.py
3. Implement parameter prompting logic
4. Add flow resumption capability

### Step 4: Testing (1 hour)
1. Manual test with simple workflow
2. Test cancellation handling
3. Test invalid input handling
4. Test optional parameters
5. Create automated tests

### Step 5: Documentation (30 min)
1. Update CLI documentation
2. Add user guide for interactive mode
3. Document implementation in progress log

## Testing the Implementation

### Manual Test Script
```bash
# Test 1: Missing all parameters
echo "analyze some data" | pflow run
# Should prompt for: input_file, output_file

# Test 2: Partial parameters
echo "analyze data.csv" | pflow run
# Should only prompt for: output_file

# Test 3: User cancellation
echo "process files" | pflow run
# Press Ctrl+C during prompt
# Should exit gracefully

# Test 4: Invalid input
echo "read a file" | pflow run
# Enter non-existent file path
# Should show error and retry
```

## Files to Modify

### Core Changes
- `src/pflow/planning/nodes.py` - ResultPreparationNode modifications
- `src/pflow/cli/main.py` - CLI integration and prompting
- `src/pflow/planning/flow.py` - Add resume_planner_flow()

### Test Updates
- `tests/test_planning/unit/test_result_preparation.py` - Test needs_user_input
- `tests/test_cli/test_main.py` - Test interactive prompting
- New: `tests/test_planning/integration/test_interactive_params.py`

## References

- **Detailed Design**: `interactive-parameter-collection-design.md`
- **Phase 1 Implementation**: `../validation-redesign-implementation-log.md`
- **Original Problem**: `../planner-validation-redesign.md`

## Important Notes

1. **Don't Break Phase 1**: The validation flow reordering must continue to work
2. **Backward Compatibility**: Non-interactive mode should still work
3. **Performance**: Don't call LLM again for parameter extraction during resumption
4. **Security**: Validate file paths and parameter values before use

## Definition of Done

- [ ] Interactive parameter collection works end-to-end
- [ ] All existing tests still pass
- [ ] New tests cover interactive scenarios
- [ ] Documentation updated
- [ ] Manual testing completed
- [ ] Progress logged in implementation log

## Your Next Steps

1. Read `interactive-parameter-collection-design.md` for detailed architecture
2. Start with Step 1 of the Implementation Workflow above
3. Ask questions if any requirements are unclear
4. Think carefully about state management and error handling
5. Test thoroughly with real user scenarios

Remember: The goal is to make the planner resilient and user-friendly when initial input lacks required details.