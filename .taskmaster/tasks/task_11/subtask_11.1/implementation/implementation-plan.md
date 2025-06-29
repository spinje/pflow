# Implementation Plan for Subtask 11.1

## Objective
Implement foundational read-file and write-file nodes that establish robust file I/O patterns for the pflow system, using PocketFlow's Node base class with retry capabilities and Tutorial-Cursor's error handling patterns.

## Implementation Steps

1. [ ] Create directory structure and __init__.py
   - File: `src/pflow/nodes/file/__init__.py`
   - Change: Create directory and expose node classes
   - Test: Verify imports work correctly

2. [ ] Implement ReadFileNode
   - File: `src/pflow/nodes/file/read_file.py`
   - Change: Create Node-based class with tuple return pattern
   - Test: Unit tests for successful reads, missing files, encoding

3. [ ] Implement WriteFileNode
   - File: `src/pflow/nodes/file/write_file.py`
   - Change: Create Node-based class with directory creation
   - Test: Unit tests for writes, appends, directory creation

4. [ ] Create comprehensive test suite
   - File: `tests/test_file_nodes.py`
   - Change: Add unit and integration tests
   - Test: Run pytest to verify all scenarios

5. [ ] Verify registry discovery
   - File: N/A (manual verification)
   - Change: Import nodes and check registry
   - Test: Ensure nodes appear in scanner results

6. [ ] Run quality checks
   - File: All new files
   - Change: Fix any linting/typing issues
   - Test: `make check` passes

## Pattern Applications

### Cookbook Patterns
- **Tutorial-Cursor File Utils**: Adapting (result, success) tuple pattern
  - Specific code/approach: Return `(content, True)` on success, `(error_msg, False)` on failure
  - Modifications needed: Integrate with Node lifecycle methods

- **Line Number Formatting**: Direct application from Tutorial-Cursor
  - Specific code/approach: Add 1-indexed line numbers to file content
  - Modifications needed: None, use as-is

### Previous Task Patterns
- Using **Three-phase lifecycle** from Task 6 for clear separation of concerns
- Using **Natural shared store keys** from simple-nodes.md (`file_path`, `content`)
- Avoiding **"filename" in logging** pitfall from Task 4
- Following **test-as-you-go** pattern from all previous tasks

## Risk Mitigations
- **Import failures**: Use exact sys.path.insert pattern from other nodes
- **Registry discovery failure**: Ensure proper __init__.py exports
- **Encoding issues**: Default to UTF-8, document text-only limitation
- **Path security**: Document lack of validation in MVP clearly
