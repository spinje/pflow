# Prompt to Continue PocketFlow Anti-Pattern Refactoring

## Context Loading Prompt

I need you to continue an important refactoring task that fixes critical anti-pattern violations in the pflow project. This refactoring ensures proper retry behavior for file operations by aligning with PocketFlow framework patterns.

**CRITICAL: Read these files in order:**

1. First, read the comprehensive context document:
   - `/Users/andfal/projects/pflow/scratchpads/pocketflow-antipattern-refactoring-context.md`

2. Then, read the detailed action plan:
   - `/Users/andfal/projects/pflow/scratchpads/pocketflow-antipattern-next-steps-plan.md`

## Current Situation

I've already refactored all 5 file operation nodes in `/src/pflow/nodes/file/` to follow PocketFlow patterns correctly. The refactoring changes how errors are handled:

- **OLD**: `exec()` methods caught exceptions and returned `(error_message, False)` tuples
- **NEW**: `exec()` methods let exceptions bubble up, enabling PocketFlow's retry mechanism

However, this broke:
1. **Linting** - Import order issues and missing `errno` import
2. **Tests** - 8 tests expect old behavior with error tuples
3. **Coverage** - No tests for the new retry behavior

## Your Task

Execute the plan in the "next-steps" document to:

1. **Fix immediate breaking issues** (linting errors)
2. **Update the 8 failing tests** to work with the new exception-based pattern
3. **Add comprehensive test coverage** for retry behavior
4. **Ensure all quality checks pass** (`make check` and `make test`)

## Key Information You Must Understand

1. **PocketFlow's Retry Mechanism**: When exceptions bubble up from `exec()`, the framework automatically retries up to `max_retries` times before calling `exec_fallback()`

2. **NonRetriableError**: A new exception class for validation errors that should fail immediately without retries (e.g., wrong file type, missing confirmation)

3. **The Double Return Pattern**:
   - `exec()` now returns just the success value (not a tuple)
   - `exec_fallback()` returns error messages after all retries fail
   - `post()` checks if result starts with "Error:" to detect failures

4. **Test Update Patterns**: The plan document shows 3 patterns for updating tests:
   - Pattern A: Use `pytest.raises()` for exception testing
   - Pattern B: Direct calls still work for success cases
   - Pattern C: Use `node.run()` for full lifecycle testing

## Expected Outcome

When complete:
- All file operations will properly retry transient errors (like temporary file locks)
- Tests will validate both success and retry behavior
- Code will be fully compliant with PocketFlow patterns
- All quality checks will pass

## Important Files

- **Nodes to verify**: `/src/pflow/nodes/file/*.py` (5 files)
- **Tests to update**: `/Users/andfal/projects/pflow/tests/test_file_nodes.py`
- **Example of correct pattern**: `/Users/andfal/projects/pflow/pocketflow/tests/test_fall_back.py`

Start by reading the two scratchpad documents, then execute the plan systematically. The refactoring is already done - you just need to fix the tests and linting issues.

## Quick Command Reference

```bash
# Check current test failures
make test

# Check linting errors
make check

# Run specific test file
pytest tests/test_file_nodes.py -xvs

# See what's in the nodes directory
ls -la src/pflow/nodes/file/
```

This is a critical refactoring that significantly improves pflow's reliability. Good luck!
