# Task 14 Handoff: Structured Output Metadata Support

**⚠️ IMPORTANT**: Do NOT begin implementing yet. Read this handoff completely and confirm you understand before starting.

## Critical Context You Must Know

### Why This Task Exists (The Aha Moment)

The planner (Task 17) was initially designed to generate sophisticated proxy mappings like:
```json
{
  "input_mappings": {
    "author": "issue_data.user.login",
    "is_urgent": "issue_data.labels[?name=='urgent']"
  }
}
```

But there's a fundamental problem: **The planner can't generate paths it can't see**. Without knowing that `issue_data` has a `user` object with a `login` field, it's just guessing. This task fixes that.

### The Core Problem You're Solving

Currently, node metadata only provides:
```python
outputs: ["issue_data", "issue_number"]  # Just key names!
```

The planner needs:
```python
outputs: [
  {
    "key": "issue_data",
    "type": "dict",
    "description": "GitHub issue details",
    "structure": {
      "id": {"type": "int", "description": "Issue ID"},
      "title": {"type": "str", "description": "Issue title"},
      "user": {
        "type": "dict",
        "description": "Issue author",
        "structure": {
          "login": {"type": "str", "description": "GitHub username"},
          "id": {"type": "int", "description": "User ID"}
        }
      },
      "labels": {
        "type": "list[dict]",
        "description": "Issue labels",
        "structure": {
          "name": {"type": "str", "description": "Label name"},
          "color": {"type": "str", "description": "Hex color"}
        }
      }
    }
  },
  {
    "key": "issue_number",
    "type": "int",
    "description": "Issue number for API calls"
  }
]
```

Without this, path-based proxy mappings are limited to well-known APIs where the LLM already knows the structure. Your task enables them to work for ANY API.

## Key Files and Their Current State

1. **`src/pflow/registry/metadata_extractor.py`** ([link](../../../src/pflow/registry/metadata_extractor.py))
   - Currently extracts simple lists from docstrings
   - Look at the `_extract_list_section()` method - that's your starting point
   - The regex patterns are tricky - test thoroughly

2. **`src/pflow/planning/context_builder.py`** ([link](../../../src/pflow/planning/context_builder.py))
   - Already formats node metadata for LLM consumption
   - See `_format_node_section()` - you'll need to enhance this
   - Has a 50KB output limit - be mindful when adding structure info

3. **Example nodes to update** (priority order):
   - `github-get-issue` - Most complex structure, most important
   - `github-list-prs` - Array of structured objects
   - File operation nodes - Often return metadata objects

## Non-Obvious Insights

### 1. Backward Compatibility is Crucial
The existing simple format MUST continue to work:
```python
"""
Outputs: issue_data, issue_number
"""
```

Many nodes use this format. Don't break them. Your parser should detect which format is being used.

### 2. The Docstring Format Battle
I explored several formats. The winner needs to be:
- Human-readable (developers write these)
- Machine-parseable (your extractor reads them)
- Not too verbose (docstrings get long)
- Python-dict-like but not eval-dangerous

The suggested format uses an indentation-based syntax with types for all Interface components:
```python
"""
Interface:
- Reads: shared["issue_number"]: int, shared["repo"]: str
- Writes: shared["issue_data"]: dict
    - id: int  # Issue ID
    - title: str  # Issue title
    - user: dict  # Issue author
      - login: str  # GitHub username
- Writes: shared["simple_key"]: str  # Simple output
- Params: token: str  # API token
"""
```

### 3. Context Builder Integration Complexity
The context builder has two modes (see Task 15):
- Discovery context: Lightweight, no structures needed
- Planning context: Full details including structures

For Task 14, make only minimal changes to display the new type/structure information. Major redesigns (like splitting into two files) are future work. The existing context builder should show types and structures in its current format.

### 4. The LLM Comprehension Challenge
The planner needs to understand paths. Format structures with examples:
```markdown
### github-get-issue
**Outputs**:
- `issue_data`: Complex object
  - Access paths: `issue_data.id`, `issue_data.user.login`, `issue_data.labels[0].name`
```

This helps the LLM understand how to generate proxy mappings.

## Warnings and Gotchas

### 1. Regex Parsing Complexity
The metadata extractor uses regex to parse docstrings. Nested structures will be challenging. Consider:
- Using a state machine for brace matching
- Or a simple recursive descent parser
- Don't use `eval()` or `ast.literal_eval()` - security risk

### 2. Validation is Currently Simple
The validation pipeline (see `scratchpads/critical-user-decisions/task-17-planner-ambiguities.md`) can only validate root keys exist, not full paths. Your structure documentation enables future validation but doesn't implement it.

### 3. Not All Nodes Need Structures
Simple nodes like `read-file` that output primitive values don't need structure documentation. Focus on:
- API response nodes (GitHub, etc.)
- Nodes that output complex objects
- Anything that would benefit from nested access

### 4. Test the Integration Path
The flow is:
1. Docstring → Metadata Extractor → Registry
2. Registry → Context Builder → LLM Prompt
3. LLM uses structure info to generate proxy mappings

Test this entire path, not just the extractor in isolation.

## Hidden Dependencies

1. **Task 15 creates `build_planning_context()`** - That's where your structure formatting goes
2. **Task 17 depends on your structures** - The planner will fail to generate valid paths without this
3. **The proxy mapping examples in `examples/`** - Study these to understand what paths the planner needs to generate

## Performance Considerations

- Parsing happens at registry scan time (startup)
- Cache parsed structures if parsing is expensive
- The context builder output has a 50KB limit - structure info counts against this
- Consider abbreviated structure display (show only commonly used paths)

## The Most Important Thing

**This task is an enabler, not a feature**. You're giving the planner eyes to see data structures so it can generate valid proxy mappings. Without this, the planner is blind and can only work with well-known APIs.

## Files Most Relevant

1. `src/pflow/registry/metadata_extractor.py` - Your main work
2. `src/pflow/planning/context_builder.py` - Integration point
3. `tests/test_registry/test_metadata_extractor.py` - Extend tests
4. `scratchpads/critical-user-decisions/task-17-planner-ambiguities.md` - Section 2.1 explains why this matters
5. Node files in `src/pflow/nodes/` - For updating docstrings

## Final Notes

- The format in the task description is a suggestion - feel free to improve it
- Prioritize getting basic structure support working over perfect parsing
- Types and structures are stored directly in outputs/inputs/params arrays as objects
- Remember: backward compatibility with simple format is non-negotiable

**IMPORTANT REMINDER**: Read this entire handoff and confirm you understand the context before beginning implementation. Do not start coding until you've absorbed this knowledge.

Good luck! This task unlocks the full power of proxy mappings.
