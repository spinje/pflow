# Refined Specification for Subtask 8.2

## Clear Objective
Validate, enhance, and document the existing dual-mode stdin implementation to ensure it fully meets requirements and is production-ready.

## Context from Knowledge Base
- Building on: Shell integration utilities from 8.1, existing CLI patterns from Task 2
- Avoiding: Breaking backward compatibility, over-engineering beyond MVP
- Following: Click context patterns, shared store conventions, test-as-you-go strategy
- **Note**: Core implementation already exists - focus is on validation and enhancement

## Technical Specification

### Inputs
- Existing implementation in `src/pflow/cli/main.py`
- Shell integration module at `src/pflow/core/shell_integration.py`
- Test files: `tests/test_cli/test_dual_mode_stdin.py`, `tests/test_shell_integration.py`

### Outputs
- Validated dual-mode stdin functionality
- All tests passing (including fixed backward compatibility test)
- Updated documentation explaining dual-mode behavior
- Edge case documentation for future work

### Implementation Constraints
- Must use: Existing shell_integration module functions
- Must avoid: Breaking existing stdin-as-workflow pattern
- Must maintain: Current CLI interface and error messages

## Success Criteria
- [x] Dual-mode stdin implementation exists and works
- [ ] All tests pass including backward compatibility test
- [ ] Manual validation confirms all patterns work:
  - `echo '{"ir_version": "1.0"}' | pflow` (stdin as workflow)
  - `cat data.txt | pflow --file workflow.json` (stdin as data)
  - `cat data.txt | pflow some-args` (stdin as data with args)
- [ ] Documentation updated with dual-mode behavior
- [ ] Edge cases documented for future implementation
- [ ] Validation report created

## Test Strategy
- Unit tests: Fix failing backward compatibility test
- Integration tests: Manually verify all dual-mode patterns
- Manual verification: Test with real files and workflows
- Documentation: Verify CLI help text explains dual-mode

## Dependencies
- Requires: Shell integration module from 8.1 (complete)
- Impacts: Future subtasks 8.3-8.5 that build on dual-mode

## Decisions Made
- **Validation over re-implementation**: Since code exists, focus on quality (Evaluation decided)
- **Fix test with simpler workflow**: Use empty nodes array for test (Evaluation decided)
- **Document edge cases**: Binary data, large files noted for future (Evaluation decided)

## Detailed Work Items

### 1. Fix Backward Compatibility Test
```python
# Update test to use self-contained workflow
workflow = {
    "ir_version": "1.0",
    "nodes": [],  # Empty, no dependencies
    "edges": [],
    "start_node": None
}
```

### 2. Manual Validation Plan
Test each scenario and document results:
1. Stdin as workflow: `echo '{"ir_version": "1.0", "nodes": []}' | pflow`
2. Stdin as data with file: `echo "test data" | pflow --file simple.json`
3. Stdin as data with args: `echo "test data" | pflow 'node1 >> node2'`
4. No stdin with file: `pflow --file workflow.json`
5. Error cases: Invalid combinations

### 3. Documentation Updates
- Add section to CLI help about dual-mode stdin
- Update README if needed
- Create example in documentation

### 4. Edge Case Documentation
Create list of future enhancements:
- Binary data handling (stdin_binary key)
- Large file streaming (>10MB)
- Performance optimization
- Thread safety considerations

### 5. Validation Report
Document:
- What was tested
- Results of each test
- Any limitations found
- Recommendations for 8.3-8.5
