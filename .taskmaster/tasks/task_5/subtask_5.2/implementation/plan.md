# Implementation Plan for Subtask 5.2

## Objective
Implement a Registry class that persists scanner output to ~/.pflow/registry.json with proper JSON serialization and directory management.

## Implementation Steps

1. [ ] Create Registry class structure
   - File: src/pflow/registry/registry.py
   - Change: Create new file with Registry class, imports, and logging setup
   - Test: Verify class can be imported

2. [ ] Implement __init__ method
   - File: src/pflow/registry/registry.py
   - Change: Add initialization with default path handling
   - Test: Verify default path and custom path work

3. [ ] Implement load() method
   - File: src/pflow/registry/registry.py
   - Change: Add JSON loading with error handling
   - Test: Test missing file, corrupt JSON, valid JSON

4. [ ] Implement save() method
   - File: src/pflow/registry/registry.py
   - Change: Add directory creation and JSON writing
   - Test: Verify directory creation, JSON format

5. [ ] Implement update_from_scanner() method
   - File: src/pflow/registry/registry.py
   - Change: Convert list to dict, handle duplicates with warnings
   - Test: Test duplicate detection, conversion logic

6. [ ] Create comprehensive test suite
   - File: tests/test_registry.py
   - Change: Create test file with unit and integration tests
   - Test: All edge cases covered

7. [ ] Integration test with real scanner
   - File: tests/test_registry.py
   - Change: Add test that uses actual scanner output
   - Test: End-to-end workflow validation

## Pattern Applications

### Previous Task Patterns
- Using **Test-As-You-Go** from Task 1.3 - write tests immediately with each method
- Using **File-based Storage** pattern - simple JSON over complex databases
- Using **Graceful Error Handling** from Task 2.2 - handle missing files without crashing
- Following **Error Logging Convention** from Task 5.1 - logger.warning for non-critical issues

### Code Organization
- Separate file for Registry (registry.py) following scanner.py pattern
- Clear method names matching specification
- Comprehensive docstrings for each method

## Risk Mitigations
- **Permission Errors**: Handle gracefully with try/except and clear error messages
- **Corrupt JSON**: Catch JSONDecodeError and return empty dict with warning
- **Race Conditions**: Document that concurrent access not supported in MVP
- **Large Files**: Not a concern for MVP scope (limited nodes)
