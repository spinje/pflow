# Task 37: Implement API Error Handling with User-Friendly Messages

## Description
Create a comprehensive error handling system for the pflow planning system that transforms cryptic API errors into actionable user guidance, implements intelligent retry mechanisms, and prevents invalid workflow generation when critical nodes fail. This will significantly improve user experience when dealing with API overload scenarios and other LLM-related failures.

## Status
done

## Completed
2025-08-21

## Dependencies
- Task 17: Implement Natural Language Planner System - Error handling system needs to integrate with the existing planning flow and node architecture
- Task 27: Implement intuitive debugging capabilities and tracing system - Error messages need to be captured in debug traces for troubleshooting

## Priority
high

## Details
This task addresses a critical issue where API overload errors were displaying cryptic technical messages to users, making the system difficult to use when the AI service was under load. The implementation evolved beyond the initial scope to fix fundamental architectural issues in error handling.

### What Was Implemented

1. **Error Classification System**: Created `error_handler.py` with intelligent error categorization (authentication, rate limit, network, overload, etc.) that provides actionable user guidance for each error type.

2. **Error Context Preservation**: Fixed the root cause where `llm_helpers.py` was wrapping all API errors as `ValueError`, destroying critical error context. Now API errors maintain their original type through the stack.

3. **Critical Node Failure Detection**: Implemented `CriticalPlanningError` to abort the planning flow when essential nodes (WorkflowDiscoveryNode, ComponentBrowsingNode, WorkflowGeneratorNode, ParameterMappingNode) can't get LLM responses, preventing the generation of invalid workflows.

4. **Retry Mechanism Fix**: Discovered and fixed a critical bug where `DebugWrapper` was calling `exec()` directly instead of `_exec()`, completely bypassing PocketFlow's retry mechanism.

5. **User-Friendly Messaging**: Replaced technical error messages with clear, actionable guidance:
   - API overload: "Wait a few moments and try again"
   - Auth errors: "Run: llm keys set anthropic"
   - Rate limits: "Wait X minutes for reset"

### Key Technical Decisions

- **Error Preservation vs Wrapping**: Chose to preserve original API errors rather than wrapping them, maintaining context for intelligent handling downstream.

- **Critical vs Non-Critical Nodes**: Defined which nodes must abort on failure (critical) vs those that can use fallbacks (non-critical like ParameterDiscoveryNode).

- **Logging Levels**: Changed error classification logs from ERROR to DEBUG level to avoid confusing users during successful retries.

### Integration Points

- All planning nodes now use `classify_error()` and `create_fallback_response()` from the error handler
- CLI enhanced to handle `CriticalPlanningError` with special messaging
- Timeout handling improved to not fail workflows that complete successfully but take >60s

## Test Strategy
Comprehensive testing ensures the error handling system works correctly across all scenarios:

### Unit Tests
- Created `test_error_classification.py` with 12+ test cases covering all error categories
- Tests for each node's `exec_fallback` behavior (critical nodes raise, non-critical return fallbacks)
- Validation of error message formatting and user guidance

### Integration Tests
- Updated existing planning tests to work with new error handling
- Fixed test expectations to match new error messages and logging levels
- Tests for error propagation through the planning flow

### Key Test Scenarios
- API overload errors are classified correctly and show user-friendly messages
- Critical nodes abort the flow instead of continuing with invalid data
- Successful retries don't show error messages to users
- Timeout after successful completion is handled gracefully
- Error information is preserved in debug traces for troubleshooting
