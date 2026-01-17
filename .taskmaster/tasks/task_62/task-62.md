# Task 62: Enhance Parameter Discovery to Route stdin to Workflow Inputs

## Description
Update the parameter discovery system in the planner to intelligently map stdin content to appropriate workflow input parameters when users pipe data but don't specify explicit file paths. This enables workflows to seamlessly work with both piped stdin data and file paths without requiring changes to individual nodes, maintaining their atomic nature.

## Status
not started

## Dependencies
- Task 17: Implement Natural Language Planner System - The parameter discovery is part of the planner's meta-workflow
- Task 33: Extract planner prompts to markdown files - Parameter discovery prompt is already extracted and needs to be modified

## Priority
medium

## Details
Currently, when users pipe data through stdin but a workflow expects a file path parameter, there's a semantic mismatch that causes workflows to fail. The user's intent is clear (process this piped data), but the workflow rigidly expects a file path. This task will enhance the parameter discovery intelligence to automatically route stdin content to appropriate workflow inputs.

### Current Behavior
- stdin content goes to `shared["stdin"]`
- Workflows expecting `file_path` parameters ignore stdin completely
- No automatic adaptation between piped data and file parameters
- Results in workflow failures when users pipe data

### Proposed Solution
Enhance the parameter discovery prompt (`src/pflow/planning/prompts/parameter_discovery.md`) to:

1. **Detect stdin context**: When stdin contains data and the user mentions "the data" or "the file" without specifying a path
2. **Map stdin to parameters**: Automatically set appropriate input parameters to reference stdin content
3. **Use template variables**: Set parameters like `input_file: "${stdin}"` instead of expecting a file path

### Implementation Approach
- Update the parameter discovery prompt to include stdin routing rules
- Add examples showing how to map stdin to workflow inputs
- Ensure the parameter mapper understands these stdin references
- No changes needed to individual nodes (maintaining atomicity)

### Key Design Decisions
- Keep nodes atomic - they shouldn't know or care where data comes from
- Intelligence happens at the planning/parameter discovery level
- Use existing template variable system (`${stdin}`)
- Workflows become data-source agnostic

### Example Scenarios
**Before**:
```bash
cat data.csv | pflow "analyze the data"  # FAILS - workflow expects file_path
```

**After**:
```bash
cat data.csv | pflow "analyze the data"  # WORKS - parameter discovery maps stdin to input
```

The parameter discovery would return:
```json
{
  "data_file": "${stdin}"  // Instead of expecting a file path
}
```

## Test Strategy
Testing will focus on the parameter discovery prompt's ability to correctly identify and route stdin:

### Unit Tests
- Test parameter discovery with stdin present and various user phrasings
- Test that explicit file paths override stdin routing
- Test edge cases where both stdin and file paths are mentioned

### Integration Tests
- Test full planner flow with piped stdin data
- Verify generated workflows use stdin content correctly
- Test with different node types that expect file inputs

### Test Scenarios
1. "Process the data" with stdin present → maps to stdin
2. "Process data.csv" with stdin present → uses explicit file path
3. "Analyze the piped data" → explicitly references stdin
4. No stdin present but user says "the data" → should request clarification

### Prompt Accuracy Testing
- Use existing prompt testing framework (`uv run python tools/test_prompt_accuracy.py parameter_discovery`)
- Add test cases for stdin routing scenarios
- Maintain >90% accuracy target