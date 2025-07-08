# Refined Specification for 7.2

## Clear Objective
Extend PflowMetadataExtractor to parse Interface sections from node docstrings, extracting Reads, Writes, Params, and Actions into simple lists of key names.

## Context from Knowledge Base
- Building on: Subtask 7.1's validated extractor foundation with phased validation
- Avoiding: Wrong assumptions about docstring format - using real node examples
- Following: Error prefix convention "PflowMetadataExtractor:", structured phases
- **Cookbook patterns to apply**: None directly applicable - PocketFlow has no metadata extraction patterns

## Technical Specification

### Inputs
- Node class object (already validated by 7.1's implementation)
- Docstring containing Interface section (may be missing or malformed)

### Outputs
Update the metadata dictionary to populate the empty lists:
```python
{
    'description': 'Write content...',  # Already extracted in 7.1
    'inputs': ['content', 'file_path', 'encoding'],  # From Reads: line
    'outputs': ['written', 'error'],  # From Writes: line
    'params': ['content', 'file_path', 'encoding', 'append'],  # From Params: line
    'actions': ['default', 'error']  # From Actions: line
}
```

### Implementation Constraints
- Must use: Regex patterns for parsing (no external parsing libraries)
- Must avoid: Assuming single-line format - handle multi-line continuations
- Must maintain: Graceful handling of missing sections (return empty lists)

### Interface Format to Parse
```
Interface:
- Reads: shared["key1"] (required), shared["key2"] (optional),
        shared["key3"] (optional)
- Writes: shared["output"] on success, shared["error"] on failure
- Params: param1, param2, param3 (as fallbacks if not in shared)
- Actions: default (success), error (failure), retry_failed
```

### Enhanced Regex Patterns
```python
# Capture Interface section including multi-line items
INTERFACE_PATTERN = r'Interface:\s*\n((?:[ \t]*-[^\n]+(?:\n(?![ \t]*-)[ \t]+[^\n]+)*\n)*)'

# Extract individual items (handles multi-line)
INTERFACE_ITEM_PATTERN = r'-\s*(\w+):\s*([^\n]+(?:\n(?![ \t]*-)[ \t]+[^\n]+)*)'

# Extract shared keys
SHARED_KEY_PATTERN = r'shared\["([^"]+)"\]'

# Extract action names
ACTIONS_PATTERN = r'(\w+)(?:\s*\([^)]+\))?'
```

## Success Criteria
- [x] Parse all four Interface components (Reads, Writes, Params, Actions)
- [x] Handle multi-line continuations in Reads/Writes sections
- [x] Extract just key names (no descriptions or metadata)
- [x] Return empty lists for missing sections (don't crash)
- [x] All existing tests continue to pass
- [x] New tests cover Interface parsing edge cases
- [x] Works with all real nodes in /src/pflow/nodes/

## Test Strategy
- Unit tests: Interface parsing with various formats
  - Complete Interface sections
  - Missing sections
  - Multi-line continuations
  - Empty values
  - Malformed content
- Integration tests: All real nodes parse correctly
  - All file nodes (read, write, copy, move, delete)
  - Test nodes with intentionally missing sections
- Manual verification: Compare output against expected values

## Dependencies
- Requires: Phase 1 validation from extract_metadata() method
- Impacts: Task 17 (Planner) will use this metadata for workflow generation

## Decisions Made
- Use enhanced regex patterns to handle multi-line continuations (evaluated in evaluation.md)
- Start with documentation implementation and enhance it (best of both worlds approach)
- Parse the actual single-line bullet format, not theoretical YAML-like formats
