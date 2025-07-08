# Test Structure Reorganization Plan

## Executive Summary

Reorganize pflow's test structure from a flat directory to a hierarchical structure that mirrors the source code organization. This will improve test discoverability, maintainability, and scalability as the project grows.

## Current State Analysis

### Test Files Inventory
```
tests/
├── __init__.py
├── test_cli_core.py              # ~300 lines - CLI tests
├── test_compiler_foundation.py    # Compiler basic tests
├── test_compiler_integration.py   # Compiler integration tests
├── test_dynamic_imports.py        # Node import tests
├── test_e2e_workflow.py          # End-to-end workflow tests
├── test_file_nodes.py            # 859 lines - ALL file node tests
├── test_file_nodes_retry.py      # 286 lines - Retry behavior tests
├── test_flow_construction.py      # Flow building tests
├── test_ir_schema.py             # IR validation tests
├── test_links.py                 # Documentation link tests
├── test_registry.py              # Registry functionality tests
├── test_scanner.py               # Node scanner tests
└── conftest.py                   # Shared fixtures
```

### Key Issues
1. `test_file_nodes.py` is too large (859 lines)
2. Flat structure becoming hard to navigate
3. No clear mapping to source structure
4. Difficult to run tests for specific components

## Target State Specification

### Proposed Structure
```
tests/
├── __init__.py
├── conftest.py                   # Root-level fixtures
├── test_cli/
│   ├── __init__.py
│   └── test_main.py              # From test_cli_core.py
├── test_core/
│   ├── __init__.py
│   └── test_ir_schema.py         # From test_ir_schema.py
├── test_nodes/
│   ├── __init__.py
│   ├── conftest.py               # Node-specific fixtures
│   └── test_file/
│       ├── __init__.py
│       ├── conftest.py           # File node fixtures
│       ├── test_read_file.py     # ~170 lines
│       ├── test_write_file.py    # ~160 lines
│       ├── test_copy_file.py     # ~130 lines
│       ├── test_move_file.py     # ~150 lines
│       ├── test_delete_file.py   # ~100 lines
│       ├── test_file_retry.py    # From test_file_nodes_retry.py
│       └── test_file_integration.py  # ~150 lines
├── test_registry/
│   ├── __init__.py
│   ├── test_registry.py          # From test_registry.py
│   └── test_scanner.py           # From test_scanner.py
├── test_runtime/
│   ├── __init__.py
│   ├── test_compiler_basic.py    # From test_compiler_foundation.py
│   ├── test_compiler_integration.py  # From test_compiler_integration.py
│   ├── test_dynamic_imports.py   # From test_dynamic_imports.py
│   └── test_flow_construction.py # From test_flow_construction.py
├── test_integration/
│   ├── __init__.py
│   └── test_e2e_workflow.py      # From test_e2e_workflow.py
└── test_docs/
    ├── __init__.py
    └── test_links.py             # From test_links.py
```

## Migration Strategy

### Phase 1: Preparation
1. **Backup current state**: Create a git branch `test-reorganization`
2. **Run all tests**: Ensure 100% pass rate before starting
3. **Document test count**: Record exact number of tests for verification

### Phase 2: Create Directory Structure
1. Create all new directories with `__init__.py` files
2. Do NOT move any files yet
3. Verify pytest can discover the empty directories

### Phase 3: Migrate Non-File Tests (Low Risk)
Start with simple, standalone test files:
1. Move `test_links.py` → `test_docs/test_links.py`
2. Run tests, verify same count
3. Move `test_ir_schema.py` → `test_core/test_ir_schema.py`
4. Continue with other non-file tests

### Phase 4: Split test_file_nodes.py (High Risk)
1. **Create extraction script** to split by test class
2. **Extract test classes**:
   - `TestReadFileNode` → `test_nodes/test_file/test_read_file.py`
   - `TestWriteFileNode` → `test_nodes/test_file/test_write_file.py`
   - `TestCopyFileNode` → `test_nodes/test_file/test_copy_file.py`
   - `TestMoveFileNode` → `test_nodes/test_file/test_move_file.py`
   - `TestDeleteFileNode` → `test_nodes/test_file/test_delete_file.py`
   - `TestIntegration` + `TestFileNodeIntegration` → `test_nodes/test_file/test_file_integration.py`
3. **Update imports** in each new file
4. **Move shared fixtures** to `test_nodes/test_file/conftest.py`
5. **Delete** original `test_file_nodes.py` only after all tests pass

### Phase 5: Update Import Paths
1. Update all `from src.pflow` imports if needed
2. Update any relative imports
3. Ensure all cross-test imports work

### Phase 6: Update Configuration
1. Update `pytest.ini` if it exists
2. Update any CI/CD test commands
3. Update Makefile test targets if needed
4. Update documentation references

## Risk Mitigation

### Risks and Mitigations
1. **Risk**: Lost tests during migration
   - **Mitigation**: Count tests before/after each step
   - **Mitigation**: Use git diff to verify no code lost

2. **Risk**: Broken imports
   - **Mitigation**: Run tests after each file move
   - **Mitigation**: Use find/replace for systematic updates

3. **Risk**: Pytest discovery issues
   - **Mitigation**: Ensure all `__init__.py` files exist
   - **Mitigation**: Test with `pytest --collect-only`

4. **Risk**: CI/CD pipeline breaks
   - **Mitigation**: Review all test commands in CI
   - **Mitigation**: Test in feature branch first

## Testing Strategy

### Verification Steps After Each Phase
1. Run `pytest --collect-only | grep -c "test_"` to count tests
2. Run `pytest -v` to ensure all pass
3. Run `pytest tests/test_nodes/test_file/` to test specific directories
4. Check coverage hasn't dropped: `pytest --cov=src/pflow`

### Final Verification
1. Total test count matches original
2. All tests pass
3. Coverage remains the same or better
4. CI/CD pipeline passes
5. Can run subsets of tests easily

## Rollback Plan

If issues arise:
1. **Git revert**: All changes in single branch
2. **Checkpoint**: Verify with make test and make check after each successful phase
3. **Recovery**: Can cherry-pick successful phases if needed

## Success Criteria

1. ✅ All 300+ tests still pass
2. ✅ No test code lost (verify with git diff)
3. ✅ Can run `pytest tests/test_nodes/test_file/` for file tests only
4. ✅ File node tests split into manageable files (<200 lines each)
5. ✅ Clear mapping: `src/pflow/X/Y` → `tests/test_X/test_Y/`
6. ✅ CI/CD pipeline continues to work
7. ✅ Other developers find structure intuitive

## Important Considerations

### Git History
- Use `git mv` to preserve file history where possible
- For split files, consider adding a commit message explaining the split

### Import Patterns
- Prefer absolute imports: `from src.pflow.nodes.file.read_file import ReadFileNode`
- Avoid relative imports in tests

### Shared Fixtures
- Root `conftest.py`: General fixtures (temp directories, etc.)
- `test_nodes/conftest.py`: Node-specific fixtures
- `test_nodes/test_file/conftest.py`: File node fixtures (test files, etc.)

### Naming Conventions
- Test files: `test_<module_name>.py`
- Test classes: `Test<ClassName>`
- Test methods: `test_<specific_behavior>`

### Future Considerations
- This structure scales well for future node types
- Easy to add `test_nodes/test_llm/` when LLM nodes are added
- Consider `test_utils/` directory for shared test utilities

## Implementation Timeline

- **Phase 1-2**: 30 minutes (setup)
- **Phase 3**: 1 hour (simple moves)
- **Phase 4**: 2 hours (complex split)
- **Phase 5-6**: 1 hour (cleanup)
- **Total**: ~4.5 hours of focused work

## Final Notes

This reorganization is a one-time investment that will pay dividends as the project grows. The new structure will make it easier to:
- Find relevant tests
- Run specific test suites
- Add new tests in the right location
- Maintain test code
- Onboard new developers

The key is to be methodical and verify each step before proceeding to the next.
