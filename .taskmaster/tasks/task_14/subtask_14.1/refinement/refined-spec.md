# Refined Specification for 14.1

## Clear Objective
Enhance the existing `PflowMetadataExtractor` class to parse type annotations, nested structures, and semantic descriptions from node Interface sections while maintaining full backward compatibility with the current simple format.

## Context from Knowledge Base
- Building on: Task 7's phased parsing approach and forgiving parser design
- Avoiding: Regex complexity explosion by using indentation-based parsing for structures
- Following: Structured logging with phase tracking, test-as-you-go development
- **Cookbook patterns to apply**: Not applicable - this is core infrastructure enhancement, not a PocketFlow node

## Technical Specification

### Inputs
- Node class instance (subclass of BaseNode or Node)
- Node docstring containing Interface section in either:
  - Simple format: `Writes: shared["key1"], shared["key2"]`
  - Enhanced format: `Writes: shared["key1"]: str, shared["key2"]: dict`

### Outputs
- Enhanced metadata dictionary with rich format:
  ```python
  {
      "description": str,  # First line of docstring
      "inputs": [
          {"key": "file_path", "type": "str", "description": "Path to file"},
          {"key": "encoding", "type": "str", "description": ""}  # Empty for simple format
      ],
      "outputs": [
          {"key": "content", "type": "str", "description": "File contents"},
          {"key": "error", "type": "str", "description": "Error message"}
      ],
      "params": [
          {"key": "timeout", "type": "int", "description": "Timeout in seconds"}
      ],
      "actions": ["default", "error"]  # Unchanged
  }
  ```

### Implementation Constraints
- Must use: Existing `PflowMetadataExtractor` class structure
- Must avoid: `eval()` or `ast.literal_eval()` for security
- Must maintain: Full backward compatibility with simple format
- Python types only: str, int, float, bool, dict, list, None

## Success Criteria
- [x] Simple format nodes continue to work (type defaults to "any", description to "")
- [x] Enhanced format with inline types is parsed correctly
- [x] Nested structures with indentation are extracted
- [x] Inline comments (# descriptions) are captured
- [x] Malformed structures fall back gracefully to simple format
- [x] All existing tests continue to pass
- [x] New tests cover all format variations
- [x] No performance regression at startup

## Test Strategy
- Unit tests: Format detection, type parsing, structure parsing, comment extraction
- Integration tests: Real node docstrings from codebase, context builder compatibility
- Manual verification: Registry scan with mixed format nodes

## Implementation Details

### Phase 1: Format Detection
- Add `_detect_format()` method to check for colons after shared["key"] or param names
- Route to appropriate parser based on detection

### Phase 2: Enhanced Parsing Methods
- Create `_extract_enhanced_interface()` for new format
- Add `_parse_inline_types()` for `shared["key"]: type` syntax
- Add `_parse_structure()` for indentation-based nested structures
- Add `_extract_comments()` for `# description` syntax

### Phase 3: Structure Parsing
- Track indentation levels for nested structures
- Build nested dictionaries based on indentation
- Handle list[dict] syntax for arrays

### Phase 4: Storage Format Update
- Transform all outputs to rich format (even simple inputs)
- Add default type "any" for simple format
- Add empty description for simple format

### Key Parsing Rules
1. **Format Detection**: Presence of `:` after `]` in shared["key"] or after param name
2. **Type Extraction**: Everything between `:` and `,` or `#` or line end
3. **Structure Indicator**: Type ending with `dict` or `list` means structure follows
4. **Indentation Parsing**: Consistent spaces/tabs indicate nesting level
5. **Comment Extraction**: Everything after `#` is description

### Error Handling
- Log warnings for malformed structures with specific error details
- Fall back to simple string extraction on parse errors
- Never raise exceptions that would break registry scanning
- Use structured logging with phase tracking

## Dependencies
- Requires: Current metadata extractor infrastructure
- Impacts: Registry storage format (but JSON can handle rich format)
- Affects: Context builder (needs minor update to display types)

## Decisions Made
- Enhanced existing class rather than creating new one (User confirmed on 2025-01-16)
- Always return rich format with defaults for backward compatibility
- Use indentation-based parsing for structures
- Support all Interface components (Reads, Writes, Params) with types

## Example Transformations

### Simple to Rich (Backward Compatibility)
Input:
```python
"""
Interface:
- Reads: shared["file_path"], shared["encoding"]
- Writes: shared["content"], shared["error"]
"""
```

Output:
```python
{
    "inputs": [
        {"key": "file_path", "type": "any", "description": ""},
        {"key": "encoding", "type": "any", "description": ""}
    ],
    "outputs": [
        {"key": "content", "type": "any", "description": ""},
        {"key": "error", "type": "any", "description": ""}
    ]
}
```

### Enhanced Format
Input:
```python
"""
Interface:
- Reads: shared["repo"]: str  # Repository name
- Writes: shared["issue_data"]: dict
    - number: int  # Issue number
    - user: dict  # Author info
      - login: str  # GitHub username
"""
```

Output:
```python
{
    "inputs": [
        {"key": "repo", "type": "str", "description": "Repository name"}
    ],
    "outputs": [
        {
            "key": "issue_data",
            "type": "dict",
            "description": "",
            "structure": {
                "number": {"type": "int", "description": "Issue number"},
                "user": {
                    "type": "dict",
                    "description": "Author info",
                    "structure": {
                        "login": {"type": "str", "description": "GitHub username"}
                    }
                }
            }
        }
    ]
}
```
