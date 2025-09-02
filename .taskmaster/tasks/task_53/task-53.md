# Task 53: Add Rerun Command Display

## ID
53

## Title
Add Rerun Command Display

## Description
Display the exact `pflow run` command with parameters after creating or reusing a workflow, making it easy for users to run the same workflow again without needing the planner. This teaches users the system and enables quick re-execution.

## Status
not started

## Dependencies
- Task 22: Named Workflow Execution - The rerun command requires named workflows to be implemented

## Priority
high

## Details
After a workflow is created or discovered through natural language, pflow should display two helpful commands:
1. The exact `pflow run` command with all parameters to execute the same workflow
2. The `pflow workflow describe` command to learn more about the workflow

This creates a learning loop where users:
- Start with natural language (discovery)
- See the exact command (learning)
- Can explore the workflow structure (understanding)
- Eventually bypass the planner entirely (mastery)

### Implementation Details
The feature should:
- Extract the workflow name and input parameters after planning
- Format them as a runnable command with proper escaping
- Display both the run and describe commands clearly
- Work for both new workflow creation and existing workflow reuse

### Display Format
```
💾 Workflow saved as 'commit-analyzer'

✨ Run again with:
  $ pflow run commit-analyzer --time_period="last week" --author="me"

📖 Learn more:
  $ pflow workflow describe commit-analyzer
```

### Integration Points
- Hook into the workflow creation/discovery flow
- Extract parameters from the planner's output
- Format command with proper shell escaping for complex values
- Ensure consistency with the actual CLI argument parsing

### User Journey Impact
This transforms pflow from a black-box AI tool into a teaching system:
1. Monday: User uses natural language
2. Tuesday: User copies the displayed command
3. Wednesday: Command is in bash history
4. Thursday: User creates an alias
5. Friday: User understands the system

## Test Strategy
Test that the displayed commands actually work:

- Unit tests for command formatting with various parameter types
- Test shell escaping for strings with spaces, quotes, special characters
- Integration test: Run displayed command and verify same result
- Test both workflow creation and reuse paths
- Verify the describe command shows accurate information
- Test with complex workflows having multiple parameters

Key scenarios:
- Simple string parameters
- Parameters with spaces and special characters
- Boolean and numeric parameters
- Optional vs required parameters
- Workflows with no parameters