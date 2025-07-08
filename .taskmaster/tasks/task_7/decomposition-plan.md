# Task 7 Decomposition Plan

**File Location**: `.taskmaster/tasks/task_7/decomposition-plan.md`

*Created on: 2025-07-08*
*Purpose: Comprehensive prompt for task-master expand command*

## Task Overview
Task 7 creates a metadata extractor that parses pflow node docstrings to extract structured interface information. This utility takes a node CLASS as input (after dynamic import) and returns parsed metadata for use by the Natural Language Planner (Task 17) and other components. The extractor must parse the actual docstring format used in pflow nodes, not theoretical formats.

## Decomposition Pattern
**Pattern**: Foundation-Integration-Polish

**Reasoning**: This pattern fits well because we need to:
1. Build the core parsing foundation with proper architecture
2. Integrate with existing node patterns and handle edge cases
3. Polish with comprehensive tests and error handling

## Complexity Analysis
- **Complexity Score**: 4/10
- **Reasoning**: Clear requirements, well-defined input/output format, but requires careful regex parsing and robust error handling
- **Total Subtasks**: 3

## Planned Subtasks

### Subtask 1: Implement Core Metadata Extractor
**Description**: Create the foundational metadata extractor class with basic docstring parsing functionality. Implement the main `extract_metadata()` method that validates node inheritance and extracts the description from docstrings.
**Dependencies**: None
**Estimated Hours**: 3-4
**Implementation Details**:
- Create `src/pflow/registry/metadata_extractor.py`
- Implement `PflowMetadataExtractor` class
- Add node validation (check BaseNode inheritance)
- Extract description (first line of docstring)
- Set up basic structure for Interface parsing
- Return specified output format with empty lists for unparsed sections

**Test Requirements**:
- Test node inheritance validation (both Node and BaseNode)
- Test description extraction from various docstring formats
- Test handling of missing docstrings
- Test rejection of non-node classes

### Subtask 2: Implement Interface Section Parsing
**Description**: Add regex-based parsing for the Interface section of docstrings. Parse the bullet-list format used in actual pflow nodes to extract Reads, Writes, Params, and Actions.
**Dependencies**: [7.1]
**Estimated Hours**: 4-5
**Implementation Details**:
- Implement regex patterns for Interface section extraction
- Parse "- Reads:" lines to extract shared store keys
- Parse "- Writes:" lines for output keys
- Parse "- Params:" lines for node parameters
- Parse "- Actions:" lines for action names
- Handle multi-line continuations in Interface sections
- Gracefully handle missing or partial Interface sections

**Test Requirements**:
- Test with actual node docstrings from `/src/pflow/nodes/file/*.py`
- Test extraction of shared["key"] patterns
- Test parameter parsing with optional/required markers
- Test action parsing with descriptions
- Test partial Interface sections (only some lines present)

### Subtask 3: Add Comprehensive Tests and Edge Case Handling
**Description**: Create a comprehensive test suite covering all edge cases and ensure the extractor works with all existing pflow nodes. Polish error messages and logging for debugging.
**Dependencies**: [7.2]
**Estimated Hours**: 3-4
**Implementation Details**:
- Create `tests/test_registry/test_metadata_extractor.py`
- Test all file nodes (read_file, write_file, copy_file, move_file, delete_file)
- Test with test nodes (test_node.py, test_node_retry.py)
- Add structured logging with phase tracking
- Implement graceful fallbacks for all edge cases
- Ensure exact output format compliance
- Add performance considerations for large docstrings

**Test Requirements**:
- 100% test coverage of metadata extractor
- Test malformed docstrings and recovery
- Test non-English characters in docstrings
- Test extremely long docstrings
- Verify all existing nodes can be parsed successfully
- Test error messages are clear and actionable

## Relevant pflow Documentation

### Core Documentation
- `docs/implementation-details/metadata-extraction.md` - Complete specification
  - Relevance: Defines the exact requirements and output format
  - Key concepts: Runtime introspection, not registry enhancement
  - Applies to subtasks: All subtasks

- `docs/features/simple-nodes.md#interface-pattern` - Interface philosophy
  - Relevance: Explains the rationale behind the Interface format
  - Key concepts: Natural interfaces, shared store communication
  - Applies to subtasks: 2 (parsing logic must understand this pattern)

### Architecture Documentation
- `docs/core-concepts/registry.md` - Registry architecture
  - Critical for: Understanding how metadata will be used
  - Must follow: Separation between discovery (Task 5) and parsing (Task 7)

## Key Architectural Considerations
- Task 7 operates on already-imported node classes (NOT registry data)
- Must handle both `Node` and `BaseNode` inheritance patterns
- Parse ACTUAL docstring format (bullet lists), not theoretical formats
- Do NOT duplicate Task 5's work (it handles discovery and raw docstring storage)
- Primary consumer is Task 17 (Natural Language Planner)
- Must be forgiving in parsing but strict about output format

## Dependencies Between Subtasks
- 7.2 requires 7.1 because it builds on the core extractor structure
- 7.3 requires 7.2 because comprehensive tests need full functionality

## Success Criteria
- [ ] Extractor correctly parses all existing pflow node docstrings
- [ ] Output format exactly matches specification
- [ ] Graceful handling of edge cases and malformed docstrings
- [ ] Clear error messages for debugging
- [ ] All subtasks have clear implementation paths
- [ ] Test coverage for all new functionality

## Special Instructions for Expansion
- Each subtask should focus on test-as-you-go development
- Include specific regex patterns in implementation details
- Reference actual node files as test cases
- Emphasize error handling and graceful degradation
- Ensure subtask descriptions mention the actual docstring format (bullet lists)

## Applied Knowledge from Previous Tasks
From the knowledge base analysis:
- Use layered validation pattern (parsing → schema → business logic)
- Implement structured logging with phase tracking ("docstring_parse", "field_extraction", "validation")
- Follow graceful configuration loading pattern for parsing failures
- Design for registry compatibility without key duplication

From Task 5 insights:
- The scanner already extracts raw docstrings - Task 7 only parses them
- Both Node and BaseNode inheritance must be supported
- Use similar error handling patterns as the scanner

---

**Note**: This file will be passed directly to `task-master expand` as the prompt. It emphasizes parsing the ACTUAL docstring format used in pflow nodes (simple bullet lists) using regex patterns, not complex structured formats or external libraries.
