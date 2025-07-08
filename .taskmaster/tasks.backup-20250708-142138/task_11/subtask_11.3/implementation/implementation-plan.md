# Implementation Plan for 11.3

## Objective
Polish all five file nodes with comprehensive error handling, consistent logging, atomic operations where appropriate, and improved user experience through better error messages and edge case handling.

## Implementation Steps

1. [ ] Add logging setup to all file nodes
   - File: All files in src/pflow/nodes/file/
   - Change: Import logging, create logger at module level
   - Test: Verify logging output appears correctly

2. [ ] Implement atomic writes for write_file.py
   - File: src/pflow/nodes/file/write_file.py
   - Change: Replace direct write with temp file + rename pattern
   - Test: Verify atomicity with interrupted writes

3. [ ] Add path normalization to all nodes
   - File: All file nodes
   - Change: Add expanduser, abspath, normpath in prep methods
   - Test: Test with ~/, relative paths, .. paths

4. [ ] Enhance error messages in read_file.py
   - File: src/pflow/nodes/file/read_file.py
   - Change: Add file path context to all error messages
   - Test: Verify error messages are helpful

5. [ ] Add exec_fallback to all nodes
   - File: All file nodes
   - Change: Implement exec_fallback method for graceful degradation
   - Test: Verify behavior after retries exhausted

6. [ ] Add comprehensive logging to copy_file.py
   - File: src/pflow/nodes/file/copy_file.py
   - Change: Add debug/info/error logs with structured data
   - Test: Check log output for all scenarios

7. [ ] Implement disk space checks
   - File: write_file.py, copy_file.py
   - Change: Check available space before operations
   - Test: Handle out-of-space gracefully

8. [ ] Improve cross-device move handling
   - File: src/pflow/nodes/file/move_file.py
   - Change: Better error detection and atomic fallback
   - Test: Verify cross-device scenarios

9. [ ] Add progress logging for large files
   - File: All file operations
   - Change: Log when handling files > 1MB
   - Test: Verify with large file operations

10. [ ] Update all error messages
    - File: All nodes
    - Change: Replace generic messages with context-rich ones
    - Test: All error paths have helpful messages

11. [ ] Create/update tests
    - File: tests/test_file_nodes.py
    - Change: Add tests for new functionality
    - Test: All tests pass, including existing 34 tests

## Pattern Applications

### Cookbook Patterns

- **Structured Logging Pattern**: From Cold Email Personalization
  - Specific code/approach: Logger setup, debug/info/error with extra dict
  - Modifications needed: Use "file_path" not "filename", add phase tracking

- **exec_fallback Pattern**: From Supervisor/Node docs
  - Specific code/approach: Override exec_fallback for post-retry behavior
  - Modifications needed: Return tuple format, include helpful error context

- **Atomic Write Pattern**: From Database resource management
  - Specific code/approach: tempfile.mkstemp + rename approach
  - Modifications needed: Handle same-directory requirement, cleanup on failure

### Previous Task Patterns

- Using **Truthiness-Safe Parameter Handling** from Task 11.1 for all parameter access
- Using **Safety Flag Pattern** from Task 11.2 (already in delete_file)
- Avoiding **Reserved Logging Fields** discovered in Task 4.2
- Using **Structured Logging with Phase Tracking** from Task 4.1

## Risk Mitigations

- **Breaking existing tests**: Run tests after each change to ensure compatibility
- **Performance impact**: Only add logging/checks that don't significantly slow operations
- **Cross-platform issues**: Test path normalization on both Unix and Windows patterns
- **Atomic write failures**: Ensure temp files are cleaned up in all error paths
- **Backwards compatibility**: Keep all interfaces exactly the same
