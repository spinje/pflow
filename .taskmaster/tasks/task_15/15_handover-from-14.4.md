# Task 15 Handoff Memo

**⚠️ IMPORTANT**: Do NOT begin implementing yet. Read this entire handoff first and confirm you understand before starting.

## Critical Context from Task 14

### What We Built (and What We Didn't)

Task 14 implemented the **Enhanced Interface Format** with type annotations and semantic descriptions:

```python
Interface:
- Reads: shared["file_path"]: str  # Path to the file to read
- Writes: shared["content"]: str  # File contents
```

**BUT HERE'S THE CRITICAL PART**: Structure parsing is NOT implemented. The parser sets a `_has_structure` flag for complex types but does NOT parse the indented structure:

```python
# This is recognized but NOT parsed:
- Writes: shared["data"]: dict  # User data
    - name: str  # User name
    - age: int  # User age
```

The `_parse_structure()` method exists in `metadata_extractor.py` but returns empty dict. This is a **known limitation** documented everywhere as "future enhancement".

### Current Context Builder State

The context builder (modified in 14.2) already:
- Shows type information: `file_path: str`
- Shows descriptions: `Path to the file to read`
- Has `_format_structure()` method that can display hierarchical structures
- Uses `_process_nodes()` to extract metadata (ready for splitting)

**Key insight from 14.2**: During implementation, the user revealed Task 15 plans, causing a major pivot from "navigation hints" to "full structure display". The groundwork is there.

## Critical Files and Their State

### 1. `/src/pflow/registry/metadata_extractor.py`
- **Lines 543-591**: `_parse_structure()` method exists but is EMPTY SCAFFOLDING
- **Line 250**: Sets `_has_structure` flag for dict/list types
- **Lines 177-211**: Multi-line support via `.extend()` (critical fix from 14.3)
- **Line 376**: Comma-aware regex splitting (preserves commas in descriptions)

### 2. `/src/pflow/planning/context_builder.py`
- **Lines 58-199**: `_process_nodes()` already extracts all metadata
- **Lines 200-228**: `_format_structure()` can display hierarchical data
- **Lines 255-404**: `_format_node_section()` shows types and descriptions
- Already displays: `input_key: type` - Description

### 3. What Task 15 Must Build On

1. **Two-phase split**: The `_process_nodes()` method makes this easy - just format differently
2. **Workflow discovery**: No workflow loading exists yet - you'll build from scratch
3. **Structure parsing**: The hooks are there, but you need to implement actual parsing

## Warnings and Gotchas

### 1. Structure Parsing is Harder Than It Looks
The regex-based approach won't work well for nested structures. Consider:
- Indentation-based parsing (like YAML)
- Recursive descent parser
- Don't try to extend the regex patterns - they're already at their limit

### 2. The User Expects Structure Support
Task 15's description assumes structure parsing works. You'll need to either:
- Implement it properly (recommended)
- Clearly scope it out and document why
- The planner NEEDS this for proxy mappings like `data.user.login`

### 3. Backward Compatibility is Sacred
The current `build_context()` must keep working. When you split into two functions:
- Keep the original function
- Maybe have it call both new functions for compatibility
- All existing tests must pass

### 4. Context Size Matters
The whole point of two-phase is to avoid overwhelming the LLM:
- Discovery phase: Names and one-line descriptions ONLY
- Planning phase: Full details for selected components only
- Remember the 50KB limit mentioned in the codebase

## Hidden Knowledge from Previous Tasks

### From 14.2 Pivot
The user's feedback during 14.2 revealed important context:
- They want discovery to be lightweight to prevent LLM confusion
- Full interface details should only appear for selected components
- This is about managing cognitive load, not just token limits

### From 14.3 Parser Fixes
The parser is fragile. Key fixes that must be preserved:
- Multi-line support uses `.extend()` not assignment
- Comma splitting uses lookahead regex: `r',\s*(?=shared\[)'`
- Empty components (like `- Reads:` with no content) break things

### From Integration Tests
The metadata flow is: Docstring → Extractor → Registry → Context Builder → Planner
Your changes affect this entire pipeline. Test end-to-end.

## Implementation Recommendations

### 1. Start with Two-Phase Split
This is the easiest part:
```python
def build_discovery_context(self, registry_metadata, saved_workflows=None):
    # Just names and descriptions

def build_planning_context(self, selected_components):
    # Full details for selected only
```

### 2. Add Workflow Discovery
- Check if `~/.pflow/workflows/` exists before trying to read
- Handle malformed JSON gracefully
- Workflows need clear visual distinction from nodes

### 3. Tackle Structure Parsing Last
It's the hardest part. Consider:
- Start with single-level structures
- Use indentation counting, not regex
- Test with the GitHub example everyone expects to work

## Files You'll Need

- `/src/pflow/planning/context_builder.py` - Main work here
- `/src/pflow/registry/metadata_extractor.py` - Structure parsing
- `/tests/test_planning/test_context_builder.py` - Already has good examples
- `/docs/reference/enhanced-interface-format.md` - Shows the structure format
- `/.taskmaster/tasks/task_14/subtask_14.3/implementation/subtask-review.md` - Parser insights

## What Success Looks Like

1. **Discovery Context** (lightweight):
```markdown
### github-get-issue
Fetches issue details from GitHub

### fix-issue-workflow
Analyzes and fixes GitHub issues automatically
```

2. **Planning Context** (detailed, selected only):
```markdown
### github-get-issue
**Inputs**: `issue_number: int` - Issue number, `repo: str` - Repository
**Outputs**: `issue_data: dict` - Issue information
  Structure of issue_data:
    - id: int - Issue ID
    - user: dict - Author info
      - login: str - Username
```

3. **Planner can generate**: `proxy_map: {"author": "issue_data.user.login"}`

## Don't Forget

- All 7 nodes already use enhanced format (Task 14.3)
- The exclusive params pattern is fully implemented
- Tests expect empty params arrays for nodes where all params are fallbacks
- The context builder already filters exclusive params

## Your First Steps

1. Read the files I've listed to understand current state
2. Run existing tests to see what's working
3. Start with the easy win: two-phase split
4. Leave structure parsing for last (it's the hardest)

**Remember**: Do NOT start implementing until you've absorbed this context and confirmed you're ready. The structure parsing everyone expects is NOT implemented despite all the setup.

Good luck\! Task 15 is crucial for making the planner actually useful.
