# Task 14 Ambiguities Update Summary

## Changes Made Based on User Feedback

### 1. Context Builder Integration (Ambiguity #9)
**Changed to Option A**: Extract full structure information
- The metadata extractor captures complete structures
- Context builder handles intelligent presentation via two markdown files:
  - Node selection file (names and descriptions only)
  - Mapping details file (full structures and paths)

### 2. Storage Format (Ambiguity #8)
**Revised to Option A with integrated storage**:
```python
"outputs": [
    {
        "key": "issue_data",
        "type": "dict",
        "description": "GitHub issue details",
        "structure": {...}
    }
]
```
- Types stored directly in arrays rather than separate structure dict
- Cleaner, more intuitive format

### 3. Interface Consistency (Ambiguity #11)
**Extended to ALL components**:
- Reads get types: `shared["repo"]: str`
- Writes get types: `shared["data"]: dict`
- Params get types: `timeout: int`
- Complete consistency across Interface section

### 4. Partial Documentation (Ambiguity #12)
**Changed to Option A**: Always document full structures
- Aligns with decision #9
- Context builder handles abbreviation if needed

### 5. Simple Output Types (Ambiguity #15)
**Changed to Option A**: Optional inline types
- Support both formats for compatibility:
  - Old: `Writes: shared["content"], shared["error"]`
  - New: `Writes: shared["content"]: str, shared["error"]: str`

### 6. Field Descriptions (Ambiguity #16)
**Clarified MVP scope**:
- Keep inline comment descriptions
- No enum types for MVP (descriptions may mention common values)
- Focus on semantic clarity

### 7. Documentation and Migration (Ambiguity #17)
**Expanded scope**:
- Migrate ALL existing nodes as part of Task 14
- Update examples/ folder with typed interfaces
- Not deferred to future work

## Final Format

### Complete Interface Example:
```python
"""
Interface:
- Reads: shared["issue_number"]: int, shared["repo"]: str
- Writes: shared["issue_data"]: dict
    - number: int  # Issue number (use for API calls)
    - state: str  # Issue state (typically "open" or "closed")
    - user: dict  # Issue author
      - login: str  # GitHub username
- Writes: shared["error"]: str  # Error message if failed
- Params: token: str  # GitHub API token
"""
```

## Key Principles

1. **Consistency**: Types for ALL Interface components
2. **Completeness**: Full structure documentation
3. **Flexibility**: Context builder handles presentation
4. **Compatibility**: Old format still works
5. **Semantics**: Descriptions clarify meaning
6. **Migration**: Update all nodes and examples

## Implementation Impact

- Parser must handle types for Reads, Writes, and Params
- Storage format uses integrated arrays with type info
- Context builder creates two presentation formats
- All existing nodes need migration
- Examples folder needs updates

This comprehensive approach ensures the planner has complete information for generating valid workflows while maintaining backward compatibility.
