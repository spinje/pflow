# Comprehensive Braindump for Subtask 14.1 Implementation

## CRITICAL CONTEXT: What You're Implementing

You are implementing **subtask 14.1**: Enhanced Interface Parser with Type Support. This is THE MOST CRITICAL piece of Task 14 because it creates the parser that extracts type information, structures, and descriptions from node docstrings. Without this, the planner (Task 17) cannot generate valid proxy mapping paths like `issue_data.user.login`.

## The Core Problem You're Solving

Currently, the planner can only see:
```python
outputs: ["issue_data", "error"]  # Just key names!
```

After your implementation, it will see:
```python
outputs: [
    {
        "key": "issue_data",
        "type": "dict",
        "description": "GitHub issue details",
        "structure": {
            "number": {"type": "int", "description": "Issue number"},
            "user": {
                "type": "dict",
                "description": "Issue author",
                "structure": {
                    "login": {"type": "str", "description": "GitHub username"}
                }
            }
        }
    }
]
```

## CRITICAL DISCOVERY: Documentation vs Reality Mismatch

**IMPORTANT**: The documentation in `architecture/implementation-details/metadata-extraction.md` describes a rich schema that DOES NOT EXIST in the code. The docs mention an `InterfaceSectionParser` class that is NOT IMPLEMENTED.

**Current Reality**:
- File: `src/pflow/registry/metadata_extractor.py`
- Class: `PflowMetadataExtractor`
- Returns: Simple format `{"outputs": ["key1", "key2"], "inputs": ["key3"]}`
- NO `_extract_list_section()` method exists (task description is wrong)

**Decision Made**: Enhance the existing `PflowMetadataExtractor` class (user confirmed).

## The Two Formats You Must Support

### 1. Simple Format (Current - MUST REMAIN WORKING)
```python
"""
Interface:
- Reads: shared["file_path"], shared["encoding"]
- Writes: shared["content"], shared["error"]
- Params: timeout
"""
```

### 2. Enhanced Format (New - YOU'RE ADDING THIS)
```python
"""
Interface:
- Reads: shared["file_path"]: str  # Path to file
- Writes: shared["issue_data"]: dict
    - number: int  # Issue number
    - user: dict  # Author
      - login: str  # GitHub username
- Params: timeout: int  # Timeout in seconds
"""
```

## Format Detection Logic (CRITICAL)

Detection is based on **colon presence**:
- `shared["key"]` → Simple format
- `shared["key"]: type` → Enhanced format
- `param` → Simple format
- `param: type` → Enhanced format

## What's Already Been Started

From the progress log, implementation began but hit issues:

1. **✅ Format detection and routing logic** - Already implemented
2. **❌ Multi-item line parsing** - Has a bug with shared comments:
   - Problem: `shared["key1"]: str, shared["key2"]: str  # comment` applies comment to both
   - Need to fix regex to handle individual vs shared comments
3. **❌ Tests need updating** - All tests expect simple format, need rich format
4. **❌ Structure parsing** - Not started
5. **❌ Real node testing** - Not started

## Critical Implementation Details

### 1. Always Return Rich Format
Even for simple input, return rich format with defaults:
```python
# Simple input: shared["key"]
# Rich output: {"key": "key", "type": "any", "description": ""}
```

### 2. The Regex Patterns (DO NOT BREAK THESE)
From Task 7 review: The INTERFACE_PATTERN is fragile. Optional newlines (`\n?`) are critical.
```python
INTERFACE_PATTERN = re.compile(
    r"Interface:\s*\n((?:[-\s]*(?:Reads|Writes|Params|Actions):.*(?:\n|$))+)",
    re.MULTILINE
)
```

### 3. Indentation-Based Structure Parsing
For nested structures, DO NOT use regex. Track indentation levels:
```python
# When you see type ending in "dict" or "list", next lines may have structure
- Writes: shared["data"]: dict
    - field1: str  # 4 spaces = level 1
    - field2: dict
      - nested: int  # 6 spaces = level 2
```

### 4. Comment Parsing Rules
- Individual: `shared["key"]: type  # This comment`
- End of line: `shared["k1"]: str, shared["k2"]: str  # Shared comment`
- Structure: `- field: type  # Field comment`

### 5. No eval() or ast.literal_eval()
Security requirement - parse everything manually with string operations.

## Key Files to Study/Modify

1. **Main file**: `src/pflow/registry/metadata_extractor.py`
   - Class: `PflowMetadataExtractor`
   - Methods to enhance: `_parse_interface_section()`, `_extract_shared_keys()`, `_extract_params()`
   - Add new methods for enhanced parsing

2. **Tests**: `tests/test_registry/test_metadata_extractor.py`
   - Has 29 tests that will need updating for rich format
   - Good examples of current format expectations

3. **Real nodes to test**:
   - `src/pflow/nodes/file/read_file.py` - Simple format
   - `src/pflow/nodes/github/get_issue.py` - Will need complex structure

## Pattern: Shared Store Inputs as Automatic Parameter Fallbacks

From knowledge base - CRITICAL understanding:
- Every "Reads" value automatically works as a parameter
- Don't list them twice in "Params"
- Context builder filters: `exclusive_params = [p for p in params if p not in inputs]`

## Error Handling Requirements

From Task 7 pattern:
- Extract what's available, don't fail on malformed sections
- Log warnings with specific errors
- Fall back to simple format on parse errors
- Never crash the registry scanner

## The Bug You Need to Fix First

The progress log shows a parsing issue with multi-item lines:
```python
# Current problem:
"Writes: shared["key1"]: str, shared["key2"]: str  # shared comment"
# Both key1 and key2 get "shared comment" as description

# Should be:
# key1: description = ""
# key2: description = "shared comment" (or both get it?)
```

## Success Criteria Checklist

- [ ] Simple format nodes continue working (backward compatibility)
- [ ] Format detection works correctly (colon-based)
- [ ] Inline types parsed: `shared["key"]: str`
- [ ] Structures parsed with indentation
- [ ] Comments extracted as descriptions
- [ ] All tests updated and passing
- [ ] Tested with real nodes from codebase
- [ ] No performance regression

## Common Pitfalls to Avoid

1. **Don't modify INTERFACE_PATTERN** - It's fragile (Task 7 warning)
2. **Don't trust documentation** - Test against real nodes
3. **Don't use eval()** - Security requirement
4. **Don't break simple format** - Backward compatibility critical
5. **Don't assume theoretical formats** - Real nodes use single-line format

## What "Writes" Really Means

CRITICAL: In the Interface section, "Writes:" means outputs. It's stored as "outputs" in metadata. There is NO separate "Outputs:" section. Don't create one.

## Integration Points

1. **Registry** - Will store your enhanced metadata
2. **Context Builder** - Task 14.2 will update it to display types (minimal changes)
3. **Planner** - Task 17 depends on your structures for proxy mapping

## References You'll Need

1. **Handoff**: `.taskmaster/tasks/task_14/14_handover.md` - Critical implementation notes
2. **Specification**: `.taskmaster/tasks/task_14/task-14-complete-specification.md` - Format examples
3. **Ambiguities**: `.taskmaster/tasks/task_14/14_ambiguities.md` - All design decisions
4. **Refined spec**: `.taskmaster/tasks/task_14/subtask_14.1/refinement/refined-spec.md` - Your implementation guide
5. **Task 7 review**: `.taskmaster/tasks/task_7/task-review.md` - Original parser insights

## The Implementation Approach

Based on Task 7's successful phased approach:

1. **Phase 1**: Format detection (DONE but needs testing)
2. **Phase 2**: Enhanced parsing methods (PARTIALLY DONE - has bug)
3. **Phase 3**: Structure parsing (NOT STARTED)
4. **Phase 4**: Update all tests (NOT STARTED)

## Memory Joggers

- Task 7 created the original parser - study it
- Task 16 enhanced context builder - it works with metadata
- `inspect.getdoc()` handles docstring indentation automatically
- Unicode support comes free with Python regex
- The 50KB context limit matters for structure size
- Performance matters - this runs at startup

Remember: You're not creating something new. You're carefully enhancing an existing, working system that's already in production use.
