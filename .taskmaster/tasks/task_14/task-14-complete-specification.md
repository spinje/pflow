# Task 14: Complete Specification - Output Type, Structure, and Semantic Documentation

## Executive Summary

Task 14 enhances the pflow metadata system to provide complete type information for all Interface components (Reads, Writes, Params), enabling the planner to generate valid proxy mapping paths and understand node interfaces comprehensively.

## Why This Task Exists (The Aha Moment)

The planner (Task 17) was designed to generate sophisticated proxy mappings like:
```json
{
  "input_mappings": {
    "author": "issue_data.user.login",
    "is_urgent": "issue_data.labels[?name=='urgent']"
  }
}
```

But there's a fundamental problem: **The planner can't generate paths it can't see**. Without knowing that `issue_data` has a `user` object with a `login` field, it's just guessing. This task fixes that by making data structures visible.

## The Core Problem

Currently, node metadata only provides:
```python
outputs: ["issue_data", "issue_number"]  # Just key names!
inputs: ["repo", "issue_number"]  # No types!
params: ["token"]  # What type is token?
```

The planner needs:
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

## Final Format Specification

### Interface Documentation Format

```python
"""
Interface:
- Reads: shared["issue_number"]: int, shared["repo"]: str  # Inline types
- Writes: shared["issue_data"]: dict
    - number: int  # Issue number (use for API calls)
    - state: str  # Issue state (typically "open" or "closed")
    - user: dict  # Issue author
      - login: str  # GitHub username
      - id: int  # User ID
    - labels: list[dict]  # Issue labels
      - name: str  # Label text
      - color: str  # Hex color code
- Writes: shared["error"]: str  # Error message if failed
- Params: token: str, timeout: int  # API token and timeout in seconds
- Actions: default, error
"""
```

### Key Format Rules

1. **Types for ALL Interface components** - Reads, Writes, and Params all get types
2. **Backward compatibility** - Old format without types still works
3. **Inline types for simple values** - `shared["key"]: type` or `param: type`
4. **Indentation for structures** - Nested fields use consistent indentation
5. **Optional descriptions** - Using `# comment` syntax for semantic clarity
6. **Full documentation** - Always document complete structures (no partial)

## Storage Format

Types are stored directly in the arrays, not in separate structure dictionaries:

```python
metadata = {
    "outputs": [
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
        },
        {
            "key": "error",
            "type": "str",
            "description": "Error message if failed"
        }
    ],
    "inputs": [
        {
            "key": "repo",
            "type": "str",
            "description": "Repository name"
        }
    ],
    "params": [
        {
            "key": "token",
            "type": "str",
            "description": "GitHub API token"
        }
    ]
}
```

## Key Implementation Files

### 1. `src/pflow/registry/metadata_extractor.py`
- Currently extracts simple lists from docstrings
- Look at the `_extract_list_section()` method - that's your starting point
- The regex patterns are tricky - test thoroughly
- Must be extended to parse types, structures, and descriptions

### 2. `src/pflow/planning/context_builder.py`
- Already formats node metadata for LLM consumption
- See `_format_node_section()` - needs enhancement to show types
- Has a 50KB output limit - be mindful when adding structure info
- **Minimal changes only** - just display the new information

### 3. Node Files to Update (ALL of them)
Priority order:
- `github-get-issue` - Most complex structure, most important
- `github-list-prs` - Array of structured objects
- All file operation nodes - Often return metadata objects
- `llm` and `claude-code` nodes
- **Every node in `src/pflow/nodes/`** must be migrated

### 4. Examples to Update
- All workflow examples in `examples/` folder must use typed nodes
- Show proxy mapping with documented structures

## Implementation Warnings and Insights

### Backward Compatibility is Crucial
The existing simple format MUST continue to work:
```python
# Old format (must still work):
"""
Interface:
- Reads: shared["issue_data"], shared["repo"]
- Writes: shared["content"], shared["error"]
- Params: encoding
"""
```

Many nodes use this format. Your parser should detect which format is being used based on the presence of `:` after keys.

### Regex Parsing Complexity
The metadata extractor uses regex to parse docstrings. Nested structures will be challenging. Consider:
- Using indentation-based parsing (recommended approach)
- State machine for tracking nesting levels
- Don't use `eval()` or `ast.literal_eval()` - security risk
- Handle `#` comments carefully in parsing

### Context Builder Scope
**IMPORTANT**: Task 14 includes only minimal context builder updates:
- Display type information in existing format
- Show structures when available
- Ensure tests pass with new metadata format
- Major redesigns (like two-file approach) are future work

### Not All Nodes Need Complex Structures
Simple nodes that output primitive values need only type annotations:
```python
# Simple node - just add types:
"""
Interface:
- Reads: shared["file_path"]: str
- Writes: shared["content"]: str, shared["error"]: str
"""
```

Focus complex structure documentation on:
- API response nodes (GitHub, etc.)
- Nodes that output complex objects
- Anything that benefits from nested access

## Hidden Dependencies and Integration

### Task Dependencies
1. **Task 15's planning context** - That's where structure formatting may be enhanced later
2. **Task 17 depends on your structures** - The planner will fail to generate valid paths without this
3. **Proxy mapping examples in `examples/`** - Study these to understand what paths the planner needs

### Integration Flow to Test
1. Docstring → Metadata Extractor → Registry
2. Registry → Context Builder → LLM Prompt
3. LLM uses structure info to generate proxy mappings

Test this entire path, not just the extractor in isolation.

### Performance Considerations
- Parsing happens at registry scan time (startup)
- Cache parsed structures if parsing is expensive
- The context builder output has a 50KB limit - structure info counts against this
- Full structures are extracted; context builder handles presentation

## Validation Scope

**Current validation is simple** - The validation pipeline can only validate root keys exist, not full paths. Your structure documentation enables future validation but doesn't implement it. For MVP:
- Syntax validation only
- Ensure types are valid Python built-ins
- Don't validate paths at runtime
- No enum type validation

## Why Descriptions Matter

Descriptions solve the semantic understanding problem:

```python
# Without descriptions - planner guesses:
- Writes: shared["data"]: dict
    - id: int        # Which ID? Issue? User?
    - state: str     # What values?
    - login: str     # Username? Email?

# With descriptions - planner understands:
- Writes: shared["data"]: dict
    - id: int        # Issue number (use for API calls)
    - state: str     # Issue state (typically "open" or "closed")
    - login: str     # GitHub username of the author
```

### Description Guidelines
1. Focus on semantics - what does this field represent?
2. Include formats - date formats, ID formats, units
3. Keep it concise - one line, essential info only
4. Don't include enum types in MVP - just mention common values in descriptions

## Implementation Checklist

- [ ] **Parser Implementation**
  - [ ] Extend metadata_extractor.py for type parsing
  - [ ] Support inline types for all Interface components
  - [ ] Handle indentation-based structure parsing
  - [ ] Implement comment parsing for descriptions
  - [ ] Maintain backward compatibility

- [ ] **Storage Updates**
  - [ ] Store types directly in outputs/inputs/params arrays
  - [ ] Include type, description, and structure fields
  - [ ] Remove any separate structure dictionaries

- [ ] **Context Builder Updates (Minimal)**
  - [ ] Display types in existing format
  - [ ] Show descriptions when available
  - [ ] Ensure tests pass with enriched metadata

- [ ] **Node Migration (ALL nodes)**
  - [ ] Update every node in `src/pflow/nodes/`
  - [ ] Priority: github nodes, file ops, llm nodes
  - [ ] Add types to Reads, Writes, and Params
  - [ ] Add descriptions for clarity

- [ ] **Examples Update**
  - [ ] Update all workflows in `examples/`
  - [ ] Show typed interfaces in action
  - [ ] Demonstrate proxy mappings with structures

- [ ] **Testing**
  - [ ] Unit tests for all parser variations
  - [ ] Backward compatibility tests
  - [ ] Integration tests with context builder
  - [ ] End-to-end with planner using structures

## Success Criteria

1. **Planner can generate valid proxy paths on first attempt**
   - No more guessing at structure
   - Works for custom APIs, not just well-known ones

2. **Complete type visibility**
   - All inputs, outputs, and params have types
   - Complex structures are fully documented

3. **Backward compatibility maintained**
   - Old nodes continue working
   - Gradual migration possible

4. **Developer experience improved**
   - Clear examples and documentation
   - Intuitive format for adding types

## The Most Important Thing

**This task is an enabler, not a feature**. You're giving the planner eyes to see data structures so it can generate valid proxy mappings. Without this, the planner is blind and can only work with well-known APIs. With this, ANY API with documented structure can be used effectively in pflow workflows.

The implementation should focus on:
1. Getting the parser working correctly
2. Maintaining strict backward compatibility
3. Migrating all nodes to showcase the new format
4. Keeping context builder changes minimal

Remember: The format must be both human-writable and machine-parseable. Developers need to easily document their nodes, and the system needs to reliably extract that documentation.
