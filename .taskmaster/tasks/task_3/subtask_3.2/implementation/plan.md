# Implementation Plan for 3.2

## Objective
Capture and handle node execution results from flow.run() to provide accurate success/failure feedback and optional execution visibility.

## Implementation Steps

1. [ ] Add --verbose flag to CLI
   - File: src/pflow/cli/main.py
   - Change: Add @click.option for --verbose flag
   - Test: Verify flag is recognized and stored in context

2. [ ] Capture flow.run() result
   - File: src/pflow/cli/main.py (execute_json_workflow function)
   - Change: Store result = flow.run(shared_storage) instead of just calling it
   - Test: Print result to verify format

3. [ ] Add error checking for node failures
   - File: src/pflow/cli/main.py (execute_json_workflow function)
   - Change: Check if result starts with "error" and show appropriate message
   - Test: Run with missing file to trigger error

4. [ ] Add try/except for unexpected failures
   - File: src/pflow/cli/main.py (execute_json_workflow function)
   - Change: Wrap flow.run() in try/except block
   - Test: Force an exception to verify handling

5. [ ] Add verbose execution tracing
   - File: src/pflow/cli/main.py (execute_json_workflow function)
   - Change: If verbose, show node entry/exit messages
   - Test: Run with --verbose flag

6. [ ] Verify registry error output
   - File: src/pflow/cli/main.py
   - Change: Check if double error still exists, fix if needed
   - Test: Remove registry and test error message

7. [ ] Add tests for node failures
   - File: tests/test_integration/test_e2e_workflow.py
   - Change: Add test cases for error actions and exceptions
   - Test: Run pytest to verify new tests pass

## Pattern Applications

### Previous Task Patterns
- Using **Error Namespace Convention** from Task 2 for all CLI messages
- Following **Professional Error Messages** pattern with context + error + suggestion
- Maintaining **Click Exit Code Pattern** for proper shell integration
- Avoiding **Silent Failures** pitfall discovered in Subtask 3.1

## Risk Mitigations
- **Breaking existing tests**: Run tests after each change to ensure compatibility
- **Verbose output too noisy**: Keep verbose messages minimal and focused
- **Error message inconsistency**: Follow established "cli:" prefix pattern
