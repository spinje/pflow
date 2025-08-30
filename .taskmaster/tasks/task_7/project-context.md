# Project Context: Task 7 - Extract Node Metadata from Docstrings

## Task Overview

Task 7 creates a metadata extractor that parses node docstrings to extract structured interface information. This is a **runtime introspection tool** that takes a node CLASS as input (after dynamic import) and returns parsed metadata for use by other components.

## Domain Understanding

### Purpose and Consumers

The metadata extractor serves several consumers:
1. **Task 17 (Natural Language Planner)** - PRIMARY CONSUMER: Needs to understand what nodes read/write for intelligent workflow chaining
2. **Task 10 (Registry CLI)** - Shows detailed node information to users
3. **Future tooling** - IDE support, documentation generation, validation

### Architectural Context

Task 7 builds on the foundation laid by Task 5:
- **Task 5 (Registry Scanner)**: Discovers nodes, extracts basic metadata including raw docstrings
- **Task 7 (Metadata Extractor)**: Parses docstrings deeply to extract structured interface information

Key distinction: Task 5 handles discovery and stores metadata for dynamic imports. Task 7 is called AFTER import when you have the actual class object.

### The ACTUAL Docstring Format

All implemented nodes in the codebase use this **single-line bullet format**:

```python
"""One-line description.

Detailed description paragraph.

Interface:
- Reads: shared["file_path"] (required), shared["encoding"] (optional)
- Writes: shared["content"] on success, shared["error"] on failure
- Params: file_path, encoding (as fallbacks if not in shared)
- Actions: default (success), error (failure)

Security Note: Optional security warnings.
Performance Note: Optional performance notes.
"""
```

Real examples:
- `/src/pflow/nodes/file/read_file.py` (lines 18-32)
- `/src/pflow/nodes/file/write_file.py` (lines 21-39)
- `/src/pflow/nodes/file/copy_file.py` (lines 21-36)

**Critical**: This is NOT the indented YAML-like format shown in some theoretical docs. Parse what's actually there!

### Node Patterns in pflow

1. **Inheritance Pattern**:
   - Production nodes inherit from `Node` (for retry support)
   - Test nodes may inherit from `BaseNode` (simpler)
   - Both are valid pflow nodes

2. **Parameter Handling**:
   Nodes have a unique pattern where parameters can come from:
   - Shared store keys (listed under Reads/Writes)
   - Node parameters (set via `node.set_params()`)

   The "Params:" line lists which parameters the node accepts as fallbacks.

## Key Technical Decisions

### Library Choice
- **Decision**: Use regex-only approach
- **Rationale**:
  - `docstring_parser` library is NOT installed
  - Our Interface format is custom and simple
  - Adding dependencies for simple parsing is overkill

### Output Format
The task specifies this exact format:
```python
{
    'description': 'Get GitHub issue',      # First line of docstring
    'inputs': ['issue_number', 'repo'],     # From "Reads:" line
    'outputs': ['issue'],                   # From "Writes:" line
    'params': ['token'],                    # From "Params:" line
    'actions': ['default', 'not_found']     # From "Actions:" line
}
```

### Error Handling Strategy
- Be forgiving and extract what's available
- No docstring → Return `{'description': 'No description', 'inputs': [], ...}`
- Missing sections → Return empty lists
- Not a node → Raise clear `ValueError`

## Applied Knowledge from Previous Tasks

### From Knowledge Base

1. **Layered Validation Pattern**: Implement three layers - parsing, schema validation, business logic validation
2. **Graceful Configuration Loading**: Handle parsing failures gracefully with clear error messages
3. **Structured Logging with Phase Tracking**: Track phases like "docstring_parse", "field_extraction", "validation"
4. **Registry Compatibility**: Design output for easy registry integration

### From Task Reviews

1. **Task 5 Insights**:
   - Already captures raw docstrings - don't duplicate
   - Uses context manager for safe imports
   - Detects all BaseNode subclasses correctly

2. **Task 6 Insights**:
   - Layered validation works well
   - Error message quality matters for users
   - Keep field names simple

3. **General Patterns**:
   - Test-as-you-go development
   - Write comprehensive tests for edge cases
   - Support format variations gracefully

## Constraints and Requirements

### Must Have
- Accept node CLASS as input (not registry data)
- Verify node inherits from `pocketflow.BaseNode`
- Parse the actual single-line Interface format
- Return exact specified output format
- Handle both `Node` and `BaseNode` inheritance

### Must NOT Do
- Duplicate Task 5's registry work
- Modify the registry
- Import all nodes
- Enforce strict formatting
- Use `docstring_parser` for Interface sections

### Edge Cases to Handle
- No docstring
- No Interface section
- Partial Interface (only some lines present)
- Malformed content
- Non-node classes
- Multi-line descriptions in Interface

## Implementation Guidance

### Recommended Approach
1. Create `PflowMetadataExtractor` class
2. Main method: `extract_metadata(node_class: type) -> Dict[str, Any]`
3. Use regex patterns for Interface parsing:
   ```python
   INTERFACE_PATTERN = r'Interface:\s*\n((?:[ \t]*-[^\n]+\n)*)'
   SHARED_KEY_PATTERN = r'shared\["([^"]+)"\]'
   ACTIONS_PATTERN = r'(\w+)(?:\s*\([^)]+\))?'
   ```
4. Implement graceful fallbacks for all extraction steps
5. Add comprehensive logging for debugging

### Testing Focus
- Test with all actual file nodes
- Test edge cases extensively
- Test both inheritance patterns
- Use real node imports, not mocks
- Verify exact output format

## References

### Essential Documentation
- `/architecture/implementation-details/metadata-extraction.md` - Task specification
- `/architecture/features/simple-nodes.md#interface-pattern` - Interface pattern philosophy

### Code Examples
- `/src/pflow/nodes/file/*.py` - Production nodes with proper docstrings
- `/src/pflow/nodes/test_node.py` - BaseNode inheritance example
- `/src/pflow/nodes/test_node_retry.py` - Node inheritance example

### Related Components
- `/src/pflow/registry/scanner.py` - Task 5's implementation
- Future: Task 17 (Natural Language Planner) - Primary consumer

## Summary

Task 7 is a focused utility that parses pflow node docstrings to extract structured metadata. It operates on already-imported node classes and produces standardized output for use by the planner and other tools. The implementation should be robust, forgiving in parsing, and well-tested against real nodes in the codebase.
