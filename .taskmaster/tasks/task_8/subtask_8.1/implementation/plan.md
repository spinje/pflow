# Implementation Plan for Subtask 8.1

## Objective
Create a standalone shell integration utility module that provides core functions for detecting, reading, and categorizing stdin input, enabling dual-mode stdin handling in pflow.

## Implementation Steps

1. [ ] Create the core module structure
   - File: `src/pflow/core/shell_integration.py`
   - Change: Create new file with imports and module docstring
   - Test: Verify no import side effects

2. [ ] Implement detect_stdin() function
   - File: `src/pflow/core/shell_integration.py`
   - Change: Add function using sys.stdin.isatty()
   - Test: Mock stdin states and verify detection

3. [ ] Implement read_stdin() function
   - File: `src/pflow/core/shell_integration.py`
   - Change: Add function with UTF-8 reading and empty string handling
   - Test: Test with various stdin states including empty

4. [ ] Implement determine_stdin_mode() function
   - File: `src/pflow/core/shell_integration.py`
   - Change: Add JSON parsing logic with ir_version check
   - Test: Test with valid/invalid JSON and missing keys

5. [ ] Implement populate_shared_store() function
   - File: `src/pflow/core/shell_integration.py`
   - Change: Simple setter for shared["stdin"]
   - Test: Verify shared store mutation

6. [ ] Create comprehensive test suite
   - File: `tests/test_shell_integration.py`
   - Change: Create test file with all test cases from spec
   - Test: Run pytest and ensure all pass

7. [ ] Update core __init__.py to export functions
   - File: `src/pflow/core/__init__.py`
   - Change: Add exports for the four functions
   - Test: Verify clean imports from pflow.core

8. [ ] Run quality checks
   - File: All created files
   - Change: Run make check and fix any issues
   - Test: Ensure all checks pass

## Pattern Applications

### Previous Task Patterns
- Using **Truthiness-Safe Parameter Handling** from Task 11 for empty string checks
- Avoiding **Empty String vs None Confusion** pitfall by explicit checks
- Following **Module Organization Pattern** from Task 1 with minimal exports
- Applying **Test-as-you-go Strategy** - creating tests alongside implementation
- Using **Direct Testing Pattern** from Task 3 - testing module directly

## Risk Mitigations
- **CliRunner quirks**: Will test both with real subprocess and mocked stdin
- **Empty string handling**: Explicit checks for empty vs None throughout
- **Import side effects**: Keep module pure with no top-level code execution
- **Encoding issues**: Proper error handling for UnicodeDecodeError
