# Knowledge Synthesis for 7.3

## Relevant Patterns from Previous Tasks

### From Subtask 7.1 - Basic Metadata Extraction
- **Phased validation approach**: [7.1] - Clear error contexts make implementation clean and debuggable
- **Simple string parsing first**: [7.1] - Start simple, add complexity later
- **Test with real production code**: [7.1] - Synthetic examples often mislead
- **Safe attribute access with inspect**: [7.1] - Use `inspect.getdoc()` for docstring extraction

### From Subtask 7.2 - Interface Parsing
- **Regex pattern for multi-line handling**: [7.2] - Use `\n?` for optional newlines at pattern ends
- **Separate helper methods**: [7.2] - Each component type gets its own extraction method
- **Extract identifiers first**: [7.2] - Strip parenthetical content after extracting names
- **Real node integration tests**: [7.2] - Caught assumptions about output format

### From Knowledge Base (patterns.md)
- **Structured Logging with Phase Tracking**: Track phases like "docstring_parse", "field_extraction", "validation" - Mentioned in task spec
- **Layered Validation Pattern**: Implement three layers - parsing, schema validation, business logic validation
- **Graceful Configuration Loading**: Handle parsing failures gracefully with clear error messages

## Known Pitfalls to Avoid

### From Subtask 7.1
- **Relying on theoretical examples**: [7.1] - Always verify against real implementation first
- **Assuming docstring format**: [7.1] - Real nodes have varied description styles

### From Subtask 7.2
- **Missing optional newlines in regex**: [7.2] - Last item in patterns often lacks trailing newline
- **Over-engineering edge cases**: [7.2] - Empty component case was unrealistic
- **Wrong output assumptions**: [7.2] - Test output format against spec exactly

## Established Conventions

### From Task 7 Implementation
- **Error prefix**: [7.1, 7.2] - Use `"metadata_extractor:"` for all error messages
- **Output format**: [Project Context] - Return exact format: `{'description': str, 'inputs': list, 'outputs': list, 'params': list, 'actions': list}`
- **ValueError for validation**: [7.1, 7.2] - Use ValueError with `# noqa: TRY004` for validation errors
- **Test structure**: [7.1, 7.2] - Extend existing `TestInterfaceParsing` class

### From Handoff Memo
- **Working INTERFACE_PATTERN**: The regex with `\n?` is critical - DO NOT modify
- **Multi-line continuation handling**: Already works correctly - test but don't "fix"
- **Parameter stripping**: Remove ALL parenthetical content from params
- **Action parsing**: Split by comma FIRST, then extract names

## Codebase Evolution Context

### What Changed in 7.1 and 7.2
- **PflowMetadataExtractor created**: [7.1] - Basic class with validation and description extraction
- **Interface parsing added**: [7.2] - Complete regex-based parsing of all Interface components
- **22 tests already exist**: [7.1: 10 tests, 7.2: 10 tests] - Comprehensive coverage of basic functionality

### What's Actually Missing (from handoff)
- **Test coverage for move_file and delete_file nodes**: Only tested read/write/copy
- **Structured logging implementation**: Phase tracking not yet added
- **Edge case tests**: Non-English characters, extremely long docstrings, malformed Interface sections

### Current Implementation State
- Core functionality is SOLID - regex patterns work, multi-line handling works
- Just needs polish: logging, remaining node tests, edge cases
- NOT fixing broken code - adding robustness and observability
