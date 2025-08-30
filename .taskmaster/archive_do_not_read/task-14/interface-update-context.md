# Context and Instructions for Updating Interface Examples

## Background Context

### What is the Enhanced Interface Format?
The Enhanced Interface Format is an evolution of pflow's node Interface documentation that adds:
1. **Type annotations**: Every input, output, and parameter has a type (e.g., `: str`, `: int`, `: dict`)
2. **Semantic descriptions**: Inline comments with `#` that explain what each field means
3. **Multi-line support**: Each item on its own line for clarity
4. **Exclusive params pattern**: Parameters already in Reads are NOT repeated in Params

### Why This Update?
- The planner (LLM) needs type information to generate valid workflows
- Developers need clear documentation to implement nodes correctly
- All actual node implementations already use the enhanced format
- Documentation is inconsistent with reality

### Current State
- **Code**: All 7 nodes in `src/pflow/nodes/` use enhanced format ✅
- **Parser**: Supports both old and new formats ✅
- **Tests**: Comprehensive tests added for enhanced format ✅
- **Docs**: Still showing old format ❌ (this is what you're fixing)

## Key Concepts You Must Understand

### 1. The Exclusive Params Pattern
This is CRITICAL to get right:
```python
# WRONG - Duplicating inputs in params
Interface:
- Reads: shared["file_path"]: str  # Path to file
- Params: file_path: str  # WRONG! Already in Reads

# CORRECT - Only exclusive params
Interface:
- Reads: shared["file_path"]: str  # Path to file
- Params: append: bool  # Append mode (only params NOT in Reads)
```

**Rule**: Every input (Reads) is automatically a parameter fallback. Only list params that are NOT inputs.

### 2. Type Annotations
Always use Python built-in types:
- `str` - Text/string values
- `int` - Whole numbers
- `float` - Decimal numbers
- `bool` - True/false values
- `dict` - Dictionary/object structures
- `list` - Arrays/lists
- `any` - When type is unknown (avoid if possible)

### 3. Description Best Practices
```python
# GOOD - Semantic and helpful
- Reads: shared["timeout"]: int  # Request timeout in seconds

# BAD - Just repeats the name
- Reads: shared["timeout"]: int  # Timeout
```

### 4. Multi-line Format
Use it for clarity, especially with 3+ items:
```python
# Preferred for multiple items
Interface:
- Reads: shared["x"]: int  # First value
- Reads: shared["y"]: int  # Second value
- Writes: shared["sum"]: int  # Sum of x and y

# Acceptable for 1-2 items
Interface:
- Reads: shared["x"]: int, shared["y"]: int  # Input values
- Writes: shared["sum"]: int  # Result
```

## Common Patterns to Apply

### File Operations Pattern
```python
Interface:
- Reads: shared["file_path"]: str  # Path to the file
- Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
- Writes: shared["content"]: str  # File contents
- Writes: shared["error"]: str  # Error message if operation failed
- Actions: default (success), error (failure)
```

### API/Service Pattern
```python
Interface:
- Reads: shared["url"]: str  # API endpoint URL
- Reads: shared["headers"]: dict  # Request headers (optional)
- Writes: shared["response"]: dict  # API response data
- Writes: shared["status"]: int  # HTTP status code
- Writes: shared["error"]: str  # Error message if failed
- Params: timeout: int  # Request timeout in seconds (default: 30)
- Actions: default (success), error (failure)
```

### Data Processing Pattern
```python
Interface:
- Reads: shared["data"]: list  # Input data to process
- Reads: shared["config"]: dict  # Processing configuration
- Writes: shared["results"]: list  # Processed results
- Writes: shared["metrics"]: dict  # Processing statistics
- Actions: default
```

## Files to Update

You need to update Interface examples in these files:

### Priority 1 (Update First)
1. `architecture/reference/node-reference.md` - Primary reference documentation
2. `architecture/features/simple-nodes.md` - Node implementation guide
3. `architecture/implementation-details/metadata-extraction.md` - Parser documentation

### Priority 2 (Update Second)
4. `architecture/features/planner.md` - Shows why types matter
5. `architecture/features/cli-runtime.md` - CLI integration examples
6. `architecture/core-concepts/registry.md` - Registry examples

### Priority 3 (Update Last)
7. `architecture/features/mcp-integration.md` - Future MCP integration
8. `architecture/prd.md` - Product requirements
9. Files in `docs/future-version/` - Future features
10. Files in `docs/core-node-packages/` - Package specifications

## Step-by-Step Process

### 1. Search for Interface Examples
Use grep to find all occurrences:
```bash
grep -n "Interface:" architecture/**/*.md
```

### 2. For Each File
1. Open the file
2. Find each Interface example
3. Apply the transformation rules
4. Ensure consistency within the file
5. Save and move to next file

### 3. Transformation Checklist
For each Interface:
- [ ] Add type annotations to all Reads/Writes/Params
- [ ] Add helpful descriptions with #
- [ ] Remove duplicate params (exclusive params pattern)
- [ ] Use multi-line format if appropriate
- [ ] Ensure types are valid Python types
- [ ] Check Actions have descriptions if needed

## Special Cases

### Theoretical Examples
Some docs show examples for nodes that don't exist yet (like GitHub nodes). Make reasonable type choices:
```python
# For a theoretical GitHub node
Interface:
- Reads: shared["repo"]: str  # Repository name (owner/repo)
- Reads: shared["issue_number"]: int  # Issue number
- Writes: shared["issue_data"]: dict  # Issue information
- Writes: shared["error"]: str  # Error message if failed
- Params: token: str  # GitHub API token
- Actions: default (success), error (failure)
```

### Partial Examples
Some docs may show only part of an Interface. Still add types:
```python
# Even partial examples should have types
Interface:
- Writes: shared["result"]: dict  # Processing result
```

### Inline Examples
Examples within paragraphs should be updated too:
```
The node writes its output to `shared["data"]: dict`.
```

## Quality Assurance

### What Good Looks Like
```python
Interface:
- Reads: shared["source"]: str  # Source file path
- Reads: shared["pattern"]: str  # Search pattern (regex)
- Writes: shared["matches"]: list  # List of matching lines
- Writes: shared["count"]: int  # Number of matches found
- Writes: shared["error"]: str  # Error message if search failed
- Params: case_sensitive: bool  # Case-sensitive search (default: true)
- Actions: default (success), error (failure)
```

This example has:
- ✅ Clear type annotations
- ✅ Helpful semantic descriptions
- ✅ Exclusive params (not duplicating inputs)
- ✅ Multi-line format for readability
- ✅ Proper action documentation

### Common Mistakes to Avoid
1. **Forgetting types**: Every item needs a type
2. **Duplicating params**: Check the exclusive params pattern
3. **Vague descriptions**: Make them helpful
4. **Wrong types**: Use valid Python types only
5. **Inconsistency**: Similar nodes should use similar patterns

## Reference Implementation

Check these actual implementations for patterns:
- `/src/pflow/nodes/file/read_file.py` - File reading pattern
- `/src/pflow/nodes/file/write_file.py` - File writing pattern
- The mock GitHub node in tests shows complex type patterns

## Success Criteria

Your update is complete when:
1. All 23 Interface examples use type annotations
2. No duplicate parameters (exclusive params pattern applied)
3. Descriptions are meaningful and helpful
4. Format is consistent across all documentation
5. Examples would parse correctly with the metadata extractor

## Remember

- This is about improving developer experience
- Types help the planner generate better workflows
- Consistency matters more than perfection
- When in doubt, check the actual node implementations
- The goal is clarity and usability
