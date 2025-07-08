# Knowledge Synthesis for 11.3

## Relevant Patterns from Previous Tasks

- **Truthiness-Safe Parameter Fallback**: [11.1] - Critical for handling empty strings and falsy values correctly in file operations
- **Safety Flags Must Be Explicitly Set in Shared Store**: [11.2] - Essential pattern for DeleteFileNode that prevents accidental destructive operations
- **Structured Logging with Phase Tracking**: [4.1] - Use logging extra dict with phase information for debugging multi-step operations
- **Avoid Reserved Logging Field Names**: [4.2] - Use "file_path" instead of "filename" in logging extra dict
- **Test-As-You-Go Development**: [1.3] - Write comprehensive tests immediately with implementation
- **Graceful JSON Configuration Loading**: [5.2] - Shows robust error handling patterns for file operations

## Known Pitfalls to Avoid

- **Empty String Bug**: [11.1] - Using `or` operator for parameter fallback treats empty strings as missing
- **Reserved Logging Fields**: [4.2] - Python's logging has reserved field names that cause KeyError if used in extra dict
- **Cross-Filesystem Move Complexity**: [11.2] - Move operations can fail with OSError on cross-device moves, need fallback

## Established Conventions

- **Node Base Class**: [11.1] - Use `Node` (not BaseNode) for retry logic on I/O operations
- **Tuple Return Pattern**: [11.1/11.2] - All exec methods return (result, success_bool) tuples
- **Error Differentiation**: [11.1] - FileNotFoundError and PermissionError return tuples immediately, other exceptions raise RuntimeError for retry
- **Idempotent Delete**: [11.2] - DeleteFileNode treats "file not found" as success for workflow robustness
- **Comprehensive Docstrings**: [11.1] - Include Interface section with Reads/Writes/Actions/Params

## Codebase Evolution Context

- **File Nodes Foundation**: [11.1] - ReadFileNode and WriteFileNode established core patterns
- **File Manipulation Nodes**: [11.2] - CopyFileNode, MoveFileNode, DeleteFileNode added with safety mechanisms
- **Current State**: All basic file operations implemented with good test coverage, now need polish for edge cases

## Key Implementation Details from Handoff

- **Safety Flag Pattern**: DeleteFileNode requires `confirm_delete` explicitly in shared store with no param fallback
- **Cross-Device Move**: MoveFileNode has string matching for "cross-device link" error but could be more robust
- **Warning Propagation**: Partial implementation exists but could be more systematic
- **Boolean Parameters**: Safe to use standard get() with default for booleans (not affected by truthiness bug)

## Areas Identified for Polish (from handoff)

1. **Better cross-platform handling** - Windows vs Unix path differences
2. **Symbolic link handling** - Currently just follows them (shutil default)
3. **Large file handling** - No progress indication for big operations
4. **Better error messages** - Some are generic like "Error: {e!s}"
5. **Race conditions** - File could be deleted between existence check and operation
6. **Disk space checks** - No verification before copy operations
7. **Atomic operations** - Copy isn't atomic, could leave partial files
8. **Warning system** - Current string parsing approach is fragile

## Testing Considerations

- **All existing tests pass** - 34 tests in test_file_nodes.py
- **Untested areas**: Cross-filesystem moves, concurrent access, large files, network drives, permission edge cases
- **Test pattern**: Use tempfile.TemporaryDirectory() for isolation
