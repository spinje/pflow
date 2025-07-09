# Refined Specification for Subtask 8.4

## Clear Objective
Enhance stdin handling to detect binary data and stream large files to temporary storage, preventing memory exhaustion while maintaining backward compatibility.

## Context from Knowledge Base
- Building on: Shell integration utilities from 8.1, dual-mode stdin from 8.2
- Avoiding: Breaking empty stdin handling, memory exhaustion, temp file leaks
- Following: Utility module pattern, explicit error handling, comprehensive testing
- **Cookbook patterns to apply**: N/A - this is a utility enhancement, not a PocketFlow node

## Technical Specification

### Inputs
- stdin data stream (text or binary)
- Environment variable: `PFLOW_STDIN_MEMORY_LIMIT` (optional, defaults to 10MB)

### Outputs
Enhanced `read_stdin()` function that returns:
- For text data < limit: String (current behavior)
- For binary data < limit: None (with data in `shared["stdin_binary"]`)
- For any data > limit: None (with path in `shared["stdin_path"]`)

### New Functions in shell_integration.py

1. **`detect_binary_content(sample: bytes) -> bool`**
   - Check first 8KB for null bytes
   - Return True if binary detected

2. **`read_stdin_with_limit(max_size: int = 10_000_000) -> Union[str, bytes, str]`**
   - Read stdin up to max_size
   - Return (content, is_binary, temp_path) tuple
   - Handle streaming to temp file if needed

3. **Modified `read_stdin() -> Optional[str]`**
   - Use new functions for detection/streaming
   - Maintain backward compatible return type

### CLI Integration Changes

Modify `main.py` line 124 to handle new stdin types:
```python
if stdin_data is not None:
    shared_storage["stdin"] = stdin_data
elif hasattr(stdin_data, 'binary_data'):
    shared_storage["stdin_binary"] = stdin_data.binary_data
elif hasattr(stdin_data, 'temp_path'):
    shared_storage["stdin_path"] = stdin_data.temp_path
```

### Implementation Constraints
- Must use: Standard library only (tempfile, os, sys)
- Must avoid: Loading large files into memory
- Must maintain: Backward compatibility for text stdin

## Success Criteria
- [x] Binary files detected correctly (null byte heuristic)
- [x] Large files (>10MB) streamed to temp files
- [x] Temp files cleaned up properly (even on errors)
- [x] All existing tests continue to pass
- [x] New tests cover binary and large file scenarios
- [x] Memory usage stays constant for large inputs
- [x] Environment variable controls memory threshold

## Test Strategy
- Unit tests:
  - Binary detection with various data samples
  - Streaming threshold behavior
  - Temp file cleanup in normal and error cases
- Integration tests:
  - Real binary files through subprocess
  - Large file handling through pipes
  - Cleanup verification
- Manual verification:
  - `cat large.bin | pflow --file workflow.json`
  - Memory usage monitoring during large transfers

## Dependencies
- Requires: Python tempfile module, environment variable support
- Impacts: CLI stdin injection logic, nodes expecting stdin data

## Decisions Made
- Binary Detection: Null byte detection in first 8KB (User confirmed via evaluation.md)
- Memory Threshold: 10MB default with PFLOW_STDIN_MEMORY_LIMIT override (User confirmed)
- Cleanup: Context managers with explicit finally blocks (User confirmed)
- Shared Store: Separate keys - stdin, stdin_binary, stdin_path (User confirmed)

## Example Usage
```bash
# Binary data
cat image.jpg | pflow --file process-image.json
# Creates shared["stdin_binary"] with bytes data

# Large text file
cat 100mb.log | pflow --file analyze.json
# Creates shared["stdin_path"] with temp file path

# Regular text (unchanged)
echo "hello" | pflow --file transform.json
# Creates shared["stdin"] with string data
```

## Error Handling
- Binary data in workflow mode: Clear error message
- Temp file creation failure: Graceful fallback with error
- Cleanup failure: Log warning but don't fail workflow

## Implementation Notes
1. Keep changes minimal - enhance existing functions
2. Use try/finally for cleanup reliability
3. Add debug logging for binary/streaming decisions
4. Document the new shared store keys clearly
5. Consider making the 8KB detection sample size configurable later
