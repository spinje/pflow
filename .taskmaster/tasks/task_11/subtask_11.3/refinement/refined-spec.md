# Refined Specification for 11.3

## Clear Objective
Polish all five file nodes with comprehensive error handling, consistent logging, atomic operations where appropriate, and improved user experience through better error messages and edge case handling.

## Context from Knowledge Base
- Building on: Established file node patterns from 11.1/11.2, tuple return pattern, safety flag pattern
- Avoiding: Reserved logging field names, truthiness bugs, generic error messages
- Following: Test-as-you-go development, structured logging pattern, Node base class for retry
- **Cookbook patterns to apply**:
  - Structured logging from Cold Email Personalization example
  - Atomic operations from Database resource management pattern
  - exec_fallback for graceful degradation

## Technical Specification

### Inputs
- All existing node interfaces remain unchanged (backwards compatible)
- No new parameters added to maintain interface stability

### Outputs
- Same shared store keys as before
- Enhanced error messages with full context
- Structured logging output for debugging

### Implementation Constraints
- Must use: Node base class, tuple return pattern, established interfaces
- Must avoid: Breaking changes to interfaces, reserved logging fields
- Must maintain: Backwards compatibility, existing test suite passing

## Success Criteria
- [ ] All 34 existing tests continue to pass
- [ ] Comprehensive logging added to all five nodes
- [ ] Atomic write operations implemented for write_file
- [ ] All error messages include relevant context (paths, operations)
- [ ] Cross-platform path normalization implemented
- [ ] Race condition mitigation for file existence checks
- [ ] exec_fallback implemented for graceful degradation
- [ ] Disk space pre-check for write/copy operations
- [ ] Progress logging for operations over 1MB
- [ ] Consistent error message format across all nodes
- [ ] No generic catch-all error messages remain

## Test Strategy
- Unit tests: Add tests for new error scenarios, atomic writes, path normalization
- Integration tests: Verify logging output, test exec_fallback behavior
- Manual verification: Test with large files, cross-platform paths, concurrent access

## Dependencies
- Requires: Existing file nodes from 11.1/11.2
- Impacts: No breaking changes, only internal improvements

## Decisions Made
- Progress indicators via structured logging (User confirmed: simple approach preferred)
- Atomic writes using temp file pattern (User confirmed: data integrity important)
- Basic cross-platform normalization only (User confirmed: MVP scope appropriate)

## Specific Enhancements Per Node

### read_file.py
1. Add comprehensive logging (start, success, failure)
2. Improve error messages with file path context
3. Add file size logging for large files
4. Implement exec_fallback for post-retry handling
5. Path normalization (expand ~, resolve ..)

### write_file.py
1. Implement atomic writes (temp file + rename)
2. Add disk space check before writing
3. Comprehensive logging with phases
4. Better error messages for all failure modes
5. Path normalization and directory creation logging

### copy_file.py
1. Add logging (currently missing entirely)
2. Disk space pre-check for destination
3. Progress logging for large files (>1MB)
4. Improve error messages to include both paths
5. Add file size to completion log

### move_file.py
1. Enhance cross-device move handling
2. Make move operation more atomic
3. Improve warning system (not string parsing)
4. Add source/dest to all error messages
5. Log operation phases

### delete_file.py
1. Add more detailed logging of what was deleted
2. Improve error messages with path context
3. Handle race conditions gracefully
4. Log safety flag status

## Code Patterns to Follow

### Logging Pattern
```python
logger = logging.getLogger(__name__)

# In prep
logger.debug(f"Reading file", extra={"file_path": file_path, "phase": "prep"})

# In exec
logger.info(f"File read successfully", extra={"file_path": file_path, "size_bytes": len(content), "phase": "exec"})

# On error
logger.error(f"Failed to read file", extra={"file_path": file_path, "error": str(e), "phase": "exec"})
```

### Atomic Write Pattern
```python
import tempfile
import shutil

temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(file_path))
try:
    with os.fdopen(temp_fd, 'w', encoding=encoding) as f:
        f.write(content)
    shutil.move(temp_path, file_path)  # Atomic on same filesystem
except Exception:
    if os.path.exists(temp_path):
        os.unlink(temp_path)
    raise
```

### Path Normalization Pattern
```python
# Normalize user input paths
file_path = os.path.expanduser(file_path)  # Expand ~
file_path = os.path.abspath(file_path)     # Resolve .. and make absolute
file_path = os.path.normpath(file_path)    # Clean up separators
```
