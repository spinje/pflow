# Task 14 Implementation Recommendations

## Updated Task Scope

Based on thorough analysis, Task 14 needs to be expanded from "structured output metadata" to **"Output Type, Structure, and Semantic Documentation"**.

## Why This Expansion is Necessary

1. **The planner needs types for ALL outputs**, not just complex ones:
   - Is `error` a string message or error object?
   - Is `content` text to display or data to process?
   - Without types, the planner cannot generate appropriate handling

2. **Semantic understanding is crucial** for correct workflow generation:
   - What does `id` mean - issue ID, user ID, or something else?
   - What values can `state` have - "open", "closed", other?
   - Is `login` a username, email, or display name?
   - Without semantics, the planner is just guessing

3. **Unified approach is cleaner**:
   - Same syntax for types, structures, and descriptions
   - One migration instead of multiple
   - Comprehensive solution for planner needs

## Recommended Format

### Before (current)
```python
"""
Interface:
- Reads: shared["file_path"], shared["encoding"]
- Writes: shared["content"], shared["error"]
"""
```

### After (with types and descriptions)
```python
"""
Interface:
- Reads: shared["file_path"]: str, shared["encoding"]: str  # Types for all components
- Writes: shared["content"]: str  # File contents
- Writes: shared["error"]: str  # Error message if read fails
"""
```

### With complex structures and semantic descriptions
```python
"""
Interface:
- Reads: shared["issue_number"]: int, shared["repo"]: str
- Writes: shared["issue_data"]: dict
    - number: int  # Issue number (use for API calls)
    - state: str  # "open" or "closed"
    - title: str  # Issue title
    - user: dict  # Issue author
      - login: str  # GitHub username
      - id: int  # User ID
    - labels: list[dict]  # Issue labels
      - name: str  # Label text
      - color: str  # Hex color code
    - ...: Any  # More fields exist
- Writes: shared["error"]: str  # Error message if API call fails
"""
```

## Implementation Plan

### 1. Parser Implementation
- Extend metadata_extractor.py to recognize `: type` syntax
- Add comment parsing for descriptions (handle `# description`)
- Use indentation-based parsing for nested structures
- Support both old format (no types) and new format
- Store types, structures, and descriptions directly in outputs/inputs/params arrays as objects

### 2. Backward Compatibility
- Old format: `Writes: shared["key"]` → type is 'Any' or unspecified
- New format: `Writes: shared["key"]: type` → explicit type
- Detection: presence of colon after `shared["key"]` or after param name
- Applies to all Interface components: Reads, Writes, Params

### 3. Context Builder Updates (Minimal Scope)
Task 14 includes only minimal updates to ensure the context builder displays the new information:
- Show types in the existing format: `**Outputs**: content (str), error (str)`
- Display descriptions when available
- Show structure information for complex types
- **Major redesigns (like two-file approach) are future work**
- Focus: Make enriched metadata visible without breaking existing functionality

### 4. Node Migration Scope
**ALL existing nodes must be migrated as part of Task 14**:
1. **github-get-issue** - Most complex structure
2. **github-list-prs** - Array of structures
3. **All file operation nodes** - read-file, write-file, etc.
4. **llm** - Variable output types
5. **claude-code** - Structured reports
6. **Any other nodes in src/pflow/nodes/**

Additionally:
- Update all examples in `examples/` folder
- Ensure consistency across entire codebase

### 5. Testing Strategy
- Unit tests for parser with various formats
- Integration tests with context builder
- End-to-end test with planner using type info
- Backward compatibility tests

## Key Decisions

1. **Indentation-based format** - Clean and Pythonic
2. **Python built-in types** - Familiar to developers
3. **Optional inline descriptions** - Using `# comment` syntax
4. **Full documentation required** - Always document complete structures
5. **Syntax validation only** - Don't validate runtime behavior
6. **Separate Writes lines** - One output per line for clarity
7. **Descriptions focus on semantics** - What fields mean, valid values, constraints

## Success Metrics

1. Planner generates valid proxy paths on first attempt
2. All existing nodes continue working
3. Clear type information for all outputs
4. Easy migration path for developers

## Risks and Mitigations

1. **Risk**: Breaking existing nodes
   - **Mitigation**: Full backward compatibility, extensive testing

2. **Risk**: Complex parsing logic
   - **Mitigation**: Simple indentation-based approach, clear error messages

3. **Risk**: Developer adoption
   - **Mitigation**: Clear documentation, gradual migration

## Example: How Descriptions Help the Planner

Without descriptions:
```
User: "Get issues created by john"
Planner sees: issue_data.user (dict with unknown fields)
Result: Planner guesses field names
```

With descriptions:
```
User: "Get issues created by john"
Planner sees: issue_data.user (dict) # Issue author
              - login: str # GitHub username
Result: Planner correctly uses issue_data.user.login == "john"
```

## Recommendation

Proceed with implementation using the indentation-based format with type annotations and optional descriptions for all outputs. This provides the planner with complete understanding - not just structure, but meaning - while maintaining simplicity and backward compatibility.
