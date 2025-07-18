# Implementation Plan for Subtask 15.1

## Objective
Create the workflow loading infrastructure that reads saved workflow JSON files from `~/.pflow/workflows/` directory, validates essential fields, and returns workflow metadata for use by the context builder.

## Implementation Steps

1. [ ] Add _load_saved_workflows() function to context_builder.py
   - File: `src/pflow/planning/context_builder.py`
   - Change: Add new private function after existing helper functions
   - Test: Verify function signature and basic structure

2. [ ] Implement directory creation logic
   - File: `src/pflow/planning/context_builder.py`
   - Change: Use `os.makedirs(Path.home() / '.pflow' / 'workflows', exist_ok=True)`
   - Test: Directory exists after function call

3. [ ] Implement JSON file discovery and loading
   - File: `src/pflow/planning/context_builder.py`
   - Change: List all *.json files and load each one
   - Test: Valid JSON files are loaded correctly

4. [ ] Add validation for required fields
   - File: `src/pflow/planning/context_builder.py`
   - Change: Check for name, description, inputs, outputs, ir fields
   - Test: Invalid files are skipped with warnings

5. [ ] Implement error handling and logging
   - File: `src/pflow/planning/context_builder.py`
   - Change: Add try/except blocks with appropriate logging
   - Test: Errors are logged but don't crash the function

6. [ ] Create comprehensive test suite
   - File: `tests/test_planning/test_workflow_loading.py`
   - Change: Create new test file with multiple test cases
   - Test: All edge cases covered

7. [ ] Create test workflow JSON files
   - Files: Various JSON files in test fixtures
   - Change: Create valid and invalid test workflows
   - Test: Test workflows work with the loader

## Pattern Applications

### Previous Task Patterns
- Using **Graceful JSON Loading** from Task 5.2 for error handling
- Following **Path Handling** conventions for cross-platform compatibility
- Applying **Test-As-You-Go** strategy from CLAUDE.md
- Using **Registry Pattern** as reference for JSON loading implementation

## Risk Mitigations
- **Risk**: Function might raise exceptions
  - **Mitigation**: Wrap all operations in try/except, return empty list on failure
- **Risk**: Cross-platform path issues
  - **Mitigation**: Use Path objects consistently, test on different platforms if possible
- **Risk**: Large directories might be slow
  - **Mitigation**: Log file count, but keep simple for MVP (no optimization needed yet)
