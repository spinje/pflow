# Implementation Plan for 7.2

## Objective
Extend PflowMetadataExtractor to parse Interface sections from node docstrings, extracting Reads, Writes, Params, and Actions into simple lists of key names.

## Implementation Steps
1. [ ] Add Interface parsing method to PflowMetadataExtractor
   - File: /src/pflow/registry/metadata_extractor.py
   - Change: Add `_parse_interface_section()` method with enhanced regex patterns
   - Test: Verify it extracts the Interface section correctly including multi-line

2. [ ] Add component extraction methods
   - File: /src/pflow/registry/metadata_extractor.py
   - Change: Add helper methods for parsing each Interface component
   - Test: Unit test each helper method with various formats

3. [ ] Integrate Interface parsing into extract_metadata
   - File: /src/pflow/registry/metadata_extractor.py
   - Change: Call Interface parser and populate the lists
   - Test: Verify complete metadata extraction works

4. [ ] Add comprehensive unit tests
   - File: /tests/test_registry/test_metadata_extractor.py
   - Change: Add test cases for all Interface parsing scenarios
   - Test: Run pytest to ensure all tests pass

5. [ ] Test with real nodes
   - File: /tests/test_registry/test_metadata_extractor.py
   - Change: Update integration tests to verify Interface extraction
   - Test: Ensure all file nodes parse correctly

6. [ ] Run quality checks
   - File: All modified files
   - Change: Fix any linting or type checking issues
   - Test: Run `make check` to ensure code quality

## Pattern Applications

### Cookbook Patterns
- **None applicable**: PocketFlow has no metadata extraction patterns to leverage

### Previous Task Patterns
- Using **Phased validation approach** from Task 7.1 for clear error tracking
- Using **Real code verification** from Task 7.1 - testing with actual nodes first
- Avoiding **Initial test assumptions** pitfall - using real docstrings from the start

## Risk Mitigations
- **Multi-line regex complexity**: Test regex patterns incrementally, verify with regex101
- **Edge case handling**: Start with nodes known to have Interface sections
- **Breaking existing tests**: Run tests after each change to catch regressions early
