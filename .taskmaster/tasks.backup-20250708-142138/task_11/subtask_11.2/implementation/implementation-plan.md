# Implementation Plan for Subtask 11.2

## Objective
Implement three file manipulation nodes (CopyFileNode, MoveFileNode, DeleteFileNode) following the patterns established in subtask 11.1, with appropriate safety mechanisms and comprehensive error handling.

## Implementation Steps

1. [ ] Implement CopyFileNode
   - File: `src/pflow/nodes/file/copy_file.py`
   - Change: Create new file with CopyFileNode class
   - Test: Verify copy operations, overwrite safety, directory creation

2. [ ] Implement MoveFileNode
   - File: `src/pflow/nodes/file/move_file.py`
   - Change: Create new file with MoveFileNode class
   - Test: Verify move operations, cross-filesystem handling, partial success

3. [ ] Implement DeleteFileNode
   - File: `src/pflow/nodes/file/delete_file.py`
   - Change: Create new file with DeleteFileNode class
   - Test: Verify delete operations, safety confirmation, idempotent behavior

4. [ ] Update __init__.py for registry discovery
   - File: `src/pflow/nodes/file/__init__.py`
   - Change: Import and export new node classes
   - Test: Verify nodes are discoverable by registry

5. [ ] Add comprehensive tests
   - File: `tests/test_file_nodes.py`
   - Change: Add test cases for all three new nodes
   - Test: Run full test suite with `make test`

6. [ ] Run quality checks
   - Command: `make check`
   - Fix any linting or type checking issues
   - Ensure all checks pass before completion

## Pattern Applications

### Cookbook Patterns
- **Tutorial-Cursor delete_file.py**: Tuple return pattern with (message, bool)
  - Specific code/approach: Consistent error handling and return format
  - Modifications needed: Add safety confirmation logic for DeleteFileNode

### Previous Task Patterns
- Using truthiness-safe parameter handling from Task 11.1
- Using Node base class with retry logic from Task 11.1
- Using comprehensive docstring format from existing nodes
- Using structured logging pattern from Task 4.1 (for delete operations)

## Risk Mitigations
- **Empty string parameters**: Use explicit key existence checking to avoid truthiness bug
- **Cross-filesystem moves**: Handle OSError for cross-device links gracefully
- **Destructive operations**: Implement explicit safety flags to prevent accidents
- **Directory permissions**: Handle permission errors as non-retryable failures
- **Path validation**: Check source existence before attempting operations
