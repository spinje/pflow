# Knowledge Synthesis for 3.2

## Relevant Patterns from Previous Tasks

### Error Handling Patterns
- **Error Namespace Convention**: All errors prefixed with source (e.g., "cli:") - [Task 2] - Provides clear source identification
- **Professional Error Messages**: Context + specific error + suggestion pattern - [Task 2] - Users need actionable guidance
- **Click Exit Code Pattern**: Proper exit codes for different failure types - [Task 1] - Important for shell scripting

### Result Handling Patterns
- **Flow Result Tuple**: flow.run() returns (action, result) tuple - [Subtask 3.1 Review] - CRITICAL: Currently ignored in implementation
- **Node Action Pattern**: Nodes return "default" or "error" action - [Subtask 3.1 Review] - Must check for error actions

### Testing Patterns
- **Node Failure Testing**: Tests must cover runtime errors, not just happy paths - [Subtask 3.1] - Current tests miss this
- **Manual Testing Reveals Issues**: Automated tests don't catch all runtime scenarios - [Subtask 3.1] - Need comprehensive test scenarios

## Known Pitfalls to Avoid

### Silent Failures
- **Node Failures Don't Propagate**: ReadFileNode fails but CLI shows success - [Subtask 3.1] - Users think workflow succeeded when it didn't
- **Partial Workflow Failures**: Some nodes succeed before one fails - [Subtask 3.1] - Need to handle mixed success/failure states

### Error Message Confusion
- **Double Error Messages**: ctx.exit(1) can cause "Unexpected error - 1" message - [Handoff Memo] - Need careful error handling
- **Registry Error Messaging**: Missing registry shows extra confusing line - [Subtask 3.1] - Clean up error output

## Established Conventions

### CLI Error Format
- **Pattern**: "cli: [Phase] failed - [Specific error]\ncli: [Additional context]\ncli: Suggestion: [Action]" - [Task 2] - Must maintain consistency
- **Prefix Convention**: All CLI messages use "cli:" prefix - [Task 2] - Distinguishes from node output

### Testing Standards
- **100% Coverage Goal**: All new code needs tests - [Task 1, 2] - Include failure scenarios
- **Test-as-you-go**: Tests created alongside implementation - [CLAUDE.md] - Not as separate task

## Codebase Evolution Context

### Recent Changes
- **Task 3 Integration Complete**: Commit dff02c3 made workflow execution functional - [Project Context] - Focus shifts to polish
- **PocketFlow Modification**: Lines 101-107 modified to preserve params - [Project Context] - Temporary change documented

### Architecture Maturity
- **Core Pipeline Works**: All Phase 1 components integrated - [Project Context] - Foundation is solid
- **Missing Observability**: Can't tell if nodes succeeded/failed - [Subtask 3.1] - Major gap to address
