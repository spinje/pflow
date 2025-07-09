# Implementation Plan for Subtask 8.4

## Objective
Enhance stdin handling to detect binary data and stream large files to temporary storage, preventing memory exhaustion while maintaining backward compatibility.

## Implementation Steps

1. [ ] Add helper functions to shell_integration.py
   - File: `src/pflow/core/shell_integration.py`
   - Change: Add `detect_binary_content()` and `read_stdin_with_limit()` functions
   - Test: Unit tests for binary detection and size limits

2. [ ] Enhance read_stdin() function
   - File: `src/pflow/core/shell_integration.py`
   - Change: Modify to use new helpers, return structured data for binary/large files
   - Test: Ensure backward compatibility with existing tests

3. [ ] Create StdinData class for type safety
   - File: `src/pflow/core/shell_integration.py`
   - Change: Add dataclass to represent different stdin types
   - Test: Type hints work correctly

4. [ ] Update CLI stdin injection
   - File: `src/pflow/cli/main.py`
   - Change: Modify line 124 area to handle StdinData types
   - Test: Integration tests with different stdin types

5. [ ] Add comprehensive tests
   - File: `tests/test_shell_integration.py`
   - Change: Add binary detection, streaming, and cleanup tests
   - Test: All edge cases covered

6. [ ] Add integration tests
   - File: `tests/test_cli/test_dual_mode_stdin.py`
   - Change: Add subprocess tests for binary and large files
   - Test: Real-world usage patterns work

## Pattern Applications

### Cookbook Patterns
N/A - This is a utility module enhancement, not a PocketFlow node implementation.

### Previous Task Patterns
- Using **Utility Module Pattern** from 8.1 for pure functions
- Using **Explicit Empty Handling Pattern** from 8.1 for string checks
- Using **Test Workflow Pattern** from 8.2 for self-contained tests
- Following **Clean Module Boundaries** from 8.1 for minimal exports

## Risk Mitigations
- **Risk**: Breaking backward compatibility
  - **Mitigation**: Keep read_stdin() return type, add new behavior only for binary/large
- **Risk**: Temp file leaks
  - **Mitigation**: Use context managers and try/finally blocks
- **Risk**: Memory exhaustion during detection
  - **Mitigation**: Read only first 8KB for binary detection
- **Risk**: Platform differences (Windows vs Unix)
  - **Mitigation**: Use Python's tempfile module for cross-platform support
