# Refined Specification for Subtask 7.1

## Clear Objective
Implement a core metadata extractor that validates node classes and extracts basic metadata from their docstrings, focusing on description extraction and structure setup.

## Context from Knowledge Base
- Building on: Task 5's dynamic import patterns and two-tier naming approach
- Avoiding: Over-engineering (Task 5 lesson) and complex parsing for simple formats
- Following: Phased error handling (Task 4), structured docstring format (Task 11), error namespace convention (Task 2)
- **Cookbook patterns to apply**: Node inheritance validation patterns from PocketFlow core

## Technical Specification

### Inputs
- `node_class`: A Python class object (type) that should be a PocketFlow node

### Outputs
- Dictionary with structure:
  ```python
  {
      'description': str,  # First line of docstring or 'No description'
      'inputs': [],       # Empty list for subtask 7.1
      'outputs': [],      # Empty list for subtask 7.1
      'params': [],       # Empty list for subtask 7.1
      'actions': []       # Empty list for subtask 7.1
  }
  ```

### Implementation Constraints
- Must use: `pocketflow.BaseNode` for inheritance validation
- Must avoid: External parsing libraries, complex regex in 7.1
- Must maintain: Simple implementation focusing on validation and basic extraction
- Must handle: Both `Node` and `BaseNode` inheritance patterns

## Success Criteria
- [x] Validates that input is a class (not instance)
- [x] Validates that class inherits from `pocketflow.BaseNode`
- [x] Raises clear `ValueError` for non-node classes
- [x] Extracts first line of docstring as description
- [x] Returns proper structure with empty lists for unparsed fields
- [x] Handles missing docstrings gracefully
- [x] All tests pass including edge cases
- [x] No dependencies on external parsing libraries

## Test Strategy
- Unit tests:
  - Valid nodes (Node and BaseNode subclasses)
  - Invalid inputs (non-nodes, instances, None)
  - Docstring variations (no docstring, empty, multiline)
  - Real node imports from /src/pflow/nodes/file/
- Integration tests: Not needed for 7.1 (utility function)
- Manual verification: Import and test with actual node classes

## Dependencies
- Requires: `pocketflow` module for BaseNode class
- Impacts: Future subtasks (7.2 will extend parsing functionality)

## Decisions Made
- Use BaseNode for validation to accept both test and production nodes (confirmed via evaluation)
- Implement basic structure in 7.1 with full parsing in 7.2 (scope clarification)
- Follow handoff memo guidance on actual vs theoretical formats (reality-based approach)

## Implementation Notes
- Create `PflowMetadataExtractor` class with single public method
- Use simple string operations for description extraction in 7.1
- Prepare structure for regex-based Interface parsing in 7.2
- Include clear error messages with "metadata_extractor:" prefix
- Focus on robustness over features for MVP
