# Implementation Plan for 7.3

## Objective
Add comprehensive tests for all remaining nodes (move_file, delete_file, test nodes), implement structured logging with phase tracking, and test edge cases including non-English characters and extremely long docstrings.

## Implementation Steps

1. [ ] Add structured logging to PflowMetadataExtractor
   - File: `/src/pflow/registry/metadata_extractor.py`
   - Change: Add module-level logger and phase tracking in all methods
   - Test: Verify log output contains phase information

2. [ ] Add test for move_file node
   - File: `/tests/test_registry/test_metadata_extractor.py`
   - Change: Add test_move_file_node method
   - Test: Verify multi-line Writes section parsing (3 lines)

3. [ ] Add test for delete_file node
   - File: `/tests/test_registry/test_metadata_extractor.py`
   - Change: Add test_delete_file_node method
   - Test: Verify handling of Safety Note section

4. [ ] Add tests for test nodes
   - File: `/tests/test_registry/test_metadata_extractor.py`
   - Change: Add test_no_docstring_node and test_named_node methods
   - Test: Verify NoDocstringNode returns default, NamedNode has no Interface

5. [ ] Add edge case tests
   - File: `/tests/test_registry/test_metadata_extractor.py`
   - Change: Add tests for non-English chars, long docstrings, malformed Interface
   - Test: Verify graceful handling without crashes

6. [ ] Run all tests and quality checks
   - File: N/A
   - Change: Execute `make test` and `make check`
   - Test: All tests pass, no linting issues

## Pattern Applications

### Cookbook Patterns
- None applicable - this is testing and logging enhancement

### Previous Task Patterns
- Using **Structured Logging with Phase Tracking** from compiler.py
- Using **Module-level logger** pattern from all pflow components
- Avoiding **Over-engineering edge cases** discovered in Task 7.2

## Risk Mitigations
- **Regex modification risk**: Will NOT modify working patterns, only add logging
- **Test fragility risk**: Will use actual node imports, not mocks
- **Performance risk**: Logging at DEBUG level only for detailed tracking
