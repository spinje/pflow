# Knowledge Synthesis for Subtask 14.2

## Relevant Patterns from Previous Tasks

### From Task 14.1 (Sibling Subtask)
- **Rich Format Transformation**: Metadata extractor now returns all data in rich format (dicts with key/type/description)
- **Format Detection Pattern**: Check for type indicators (colons) to detect enhanced format
- **Graceful Enhancement**: Always return enhanced format even for simple input
- **Split-by-comma Comment Parsing**: Handle multi-item lines with shared comments correctly
- **Indentation-Based Structure Parsing**: Clean recursive approach for nested structures

### From Knowledge Base
- **Shared Store Inputs as Automatic Parameter Fallbacks**: Filter out params that are already inputs (exclusive params only)
- **Format Detection with Graceful Enhancement**: Support both old and new formats without breaking existing users
- **Truthiness-Safe Parameter Fallback**: Explicitly check for key existence when empty values are valid
- **Structured Logging with Phase Tracking**: Use extra dict for structured metadata

## Known Pitfalls to Avoid
- **Regex Complexity Explosion** (from Task 14.1): INTERFACE_PATTERN is fragile and must not be modified
- **Line-by-line vs Multi-line Regex**: INTERFACE_ITEM_PATTERN expects multi-line matching
- **Assuming Documentation Accuracy**: Always verify against actual code behavior
- **Breaking Backward Compatibility**: Ensure nodes without types still work

## Established Conventions
- **Interface Format**: Single-line format `Writes: shared["key1"], shared["key2"]`
- **Metadata Storage**: JSON format alongside node files in registry
- **Error Handling**: Graceful degradation - extract what's available, log warnings
- **Testing**: Use real node imports, not mocks; test with actual codebase files
- **50KB Context Limit**: Must respect output size limit in context builder

## Codebase Evolution Context
- **What changed in 14.1**: Metadata extractor now returns rich format with type/description/structure
- **When**: Just completed (2025-01-16)
- **Impact on this task**: Context builder receives dict format instead of simple strings
- **Key insight**: The parser already handles backward compatibility, so context builder gets consistent rich format

## Implementation Insights from 14.1

### Rich Format Structure
The metadata extractor now returns:
```python
{
    "inputs": [
        {"key": "file_path", "type": "str", "description": "Path to file"},
        {"key": "data", "type": "dict", "description": "", "structure": {...}}
    ],
    "outputs": [...],
    "params": [...],
    "actions": ["default", "error"]  # Actions remain as simple list
}
```

### Exclusive Params Pattern
From the knowledge base pattern:
```python
# Before filtering (what metadata extractor returns)
metadata["params"] = [
    {"key": "file_path", "type": "str", "description": ""},
    {"key": "append", "type": "bool", "description": "Append mode"}
]

# After filtering in context builder
input_keys = {item["key"] for item in metadata["inputs"]}
exclusive_params = [p for p in metadata["params"] if p["key"] not in input_keys]
# Result: only "append" shown as parameter
```

### Structure Navigation
For complex types with structures, need to generate navigation hints:
- Dict with structure: Show common access paths
- List types: Indicate iteration pattern
- Nested structures: Limit depth to 2-3 levels for clarity

## Key Questions for Refinement
1. How to format type information for optimal LLM understanding?
2. What navigation hints are most helpful for complex structures?
3. How to handle the 50KB limit when structures add significant size?
4. Should descriptions be shown inline or separately?
5. How to indicate optional vs required inputs?

## Testing Considerations
- Need to update context builder tests to expect type information
- Verify backward compatibility with nodes that don't have types
- Test with real node imports from the codebase
- Ensure 50KB limit is respected with structure information
