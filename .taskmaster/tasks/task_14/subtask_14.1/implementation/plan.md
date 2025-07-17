# Implementation Plan for 14.1

## Objective
Enhance the existing `PflowMetadataExtractor` class to parse type annotations, nested structures, and semantic descriptions from node Interface sections while maintaining full backward compatibility with the current simple format.

## Implementation Steps

1. [ ] Study current implementation structure
   - File: `src/pflow/registry/metadata_extractor.py`
   - Change: Understand current flow and identify extension points
   - Test: Run existing tests to ensure they pass

2. [ ] Add format detection logic
   - File: `src/pflow/registry/metadata_extractor.py`
   - Change: Add `_detect_interface_format()` method to check for colons
   - Test: Unit test with both simple and enhanced formats

3. [ ] Create enhanced parsing infrastructure
   - File: `src/pflow/registry/metadata_extractor.py`
   - Change: Add `_extract_enhanced_interface()` method for new format
   - Test: Basic extraction of enhanced format

4. [ ] Implement inline type parsing
   - File: `src/pflow/registry/metadata_extractor.py`
   - Change: Add `_parse_inline_types()` for `shared["key"]: type` syntax
   - Test: Parse types from Reads, Writes, and Params

5. [ ] Implement comment extraction
   - File: `src/pflow/registry/metadata_extractor.py`
   - Change: Add `_extract_description()` for `# description` syntax
   - Test: Extract descriptions from inline comments

6. [ ] Implement structure parsing
   - File: `src/pflow/registry/metadata_extractor.py`
   - Change: Add `_parse_indented_structure()` for nested dict/list structures
   - Test: Parse complex nested structures with indentation

7. [ ] Update output format transformation
   - File: `src/pflow/registry/metadata_extractor.py`
   - Change: Transform all outputs to rich format with defaults
   - Test: Verify backward compatibility with simple format

8. [ ] Add comprehensive test coverage
   - File: `tests/test_registry/test_metadata_extractor.py`
   - Change: Add tests for all new functionality
   - Test: Run full test suite

9. [ ] Test with real nodes
   - File: Various nodes in `src/pflow/nodes/`
   - Change: Verify extraction works with actual node docstrings
   - Test: Integration test with registry scanner

10. [ ] Run quality checks
    - File: All modified files
    - Change: Fix any lint/type issues
    - Test: `make check` passes

## Pattern Applications

### Previous Task Patterns
- Using **Phased Implementation** from Task 7 for clear separation of parsing phases
- Using **Structured Logging with Phase Tracking** from Task 7 for debugging
- Using **Test-As-You-Go** pattern to validate each parsing component immediately
- Avoiding **Regex Complexity Explosion** by using indentation parsing for structures

## Risk Mitigations
- **Breaking existing functionality**: Run existing tests frequently, maintain backward compatibility
- **Complex regex patterns**: Keep regex simple, use line-by-line parsing for structures
- **Performance regression**: Profile parsing time, optimize only if needed
- **Security issues**: Never use eval(), parse everything manually
