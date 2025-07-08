# Refined Specification for 7.3

## Clear Objective
Add comprehensive tests for all remaining nodes (move_file, delete_file, test nodes), implement structured logging with phase tracking, and test edge cases including non-English characters and extremely long docstrings.

## Context from Knowledge Base
- Building on: Working Interface parsing from 7.2, established test structure
- Avoiding: Over-engineering unrealistic edge cases, breaking working regex patterns
- Following: Module-level logger pattern, phase tracking with extra dict, existing error conventions
- **Cookbook patterns to apply**: None - this is testing and logging enhancement

## Technical Specification

### Inputs
- Existing `PflowMetadataExtractor` class from subtasks 7.1 and 7.2
- Working regex patterns (DO NOT MODIFY)
- 22 existing tests in `TestInterfaceParsing` class

### Outputs
- Enhanced `PflowMetadataExtractor` with structured logging
- Comprehensive test coverage for ALL nodes in codebase
- Edge case handling for malformed inputs

### Implementation Constraints
- Must use: Module-level logger pattern (`logger = logging.getLogger(__name__)`)
- Must avoid: Modifying working regex patterns, changing error types
- Must maintain: Existing test structure, error prefix convention

## Success Criteria
- [ ] Tests added for move_file and delete_file nodes
- [ ] Tests added for test nodes (NoDocstringNode, NamedNode)
- [ ] Structured logging implemented with phases: init, validation, docstring_parsing, interface_extraction, complete
- [ ] Edge case tests: non-English chars, 1000+ line docstrings, malformed Interface
- [ ] All tests pass with no regressions
- [ ] Logging follows established patterns from compiler.py

## Test Strategy

### Unit Tests to Add:
1. **test_move_file_node** - Test multi-line Writes section (3 lines)
2. **test_delete_file_node** - Test Safety Note handling
3. **test_no_docstring_node** - Using actual NoDocstringNode class
4. **test_named_node** - Node with name but no Interface
5. **test_non_english_characters** - Japanese/emoji in docstrings
6. **test_extremely_long_docstring** - 1000+ lines programmatically generated
7. **test_malformed_interface** - Broken formatting, missing colons, etc.

### Integration Tests:
- Verify all production nodes work correctly
- Ensure logging doesn't break functionality
- Performance remains acceptable

### Manual Verification:
- Check log output format matches compiler pattern
- Verify phase tracking provides useful debugging info

## Dependencies
- Requires: Completed subtasks 7.1 and 7.2
- Impacts: No breaking changes - only enhancements

## Decisions Made
- **Logging detail**: Phase transitions and key results only (from evaluation)
- **"Extremely long"**: 1000+ lines for stress testing (from evaluation)
- **Logger pattern**: Module-level following compiler.py (from codebase analysis)
