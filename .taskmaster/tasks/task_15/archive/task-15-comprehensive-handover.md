# Task 15 Comprehensive Handover Document

This document synthesizes all knowledge from the four Task 15 handover documents, providing a complete and accurate picture for implementing Task 15. It complements the ambiguities document by providing technical implementation details and historical context.

## Executive Summary

Task 15 extends the context builder with two-phase discovery to prevent LLM overwhelm. The key insight: **structure parsing is already implemented** (contrary to some documentation), so Task 15 can focus on the two-phase split and workflow discovery.

## Critical Discoveries and Corrections

### 1. Structure Parsing IS Implemented ✅
Despite documentation claiming it's "scaffolding only", the structure parser is FULLY FUNCTIONAL:
- Location: `metadata_extractor.py` lines 543-612
- Implementation: 70-line recursive parser
- Capability: Handles nested dictionaries and lists
- Status: Tests confirm it works correctly

**Example that already works:**
```python
- Writes: shared["issue_data"]: dict  # GitHub issue
    - number: int  # Issue number
    - user: dict  # Author information
      - login: str  # Username
      - id: int  # User ID
```

### 2. Context Size Limit is 200KB (not 50KB)
- Code shows: `MAX_OUTPUT_SIZE = 200 * 1024`
- Location: `context_builder.py` line 38
- Use 200KB as the actual limit for implementation

### 3. All Nodes Already Use Enhanced Format
Task 14.3 migrated all 7 nodes to multi-line enhanced format:
- File operation nodes (5 total)
- Test nodes (2 total)
- All follow the exclusive params pattern

## Implementation Roadmap

### Phase 1: Two-Phase Context Split (Hours 1-4)

#### Discovery Context Function
```python
def build_discovery_context(registry_metadata, saved_workflows=None):
    """
    Lightweight context for component selection.

    Key requirements:
    - Reuse _process_nodes() but format differently
    - Output: "### node-name\nOne line description"
    - NO types, params, or structure information
    - Include both nodes AND workflows
    - Group by category (reuse existing logic)
    """
```

**Expected Output:**
```markdown
## Available Nodes

### File Operations
### read-file
Read content from a file and add line numbers for display

### write-file
Write content to a file with automatic directory creation

## Available Workflows

### fix-issue-workflow
Analyzes and fixes GitHub issues automatically
```

#### Planning Context Function
```python
def build_planning_context(selected_components, registry_metadata, saved_workflows=None):
    """
    Detailed context for selected components only.

    Key requirements:
    - Filter to only selected components
    - Include FULL interface details
    - Show structure information (use existing _format_structure())
    - Distinguish workflows vs nodes
    - Maintain exclusive params pattern
    """
```

### Phase 2: Workflow Discovery (Hours 5-6)

#### Workflow Loading Implementation
```python
def _load_saved_workflows():
    """
    Load workflows from ~/.pflow/workflows/*.json

    Implementation steps:
    1. Create directory if missing
    2. Glob all *.json files
    3. Parse and validate each file
    4. Skip invalid files with warning
    5. Return list of workflow metadata
    """
```

**Workflow Schema:**
```json
{
  "name": "fix-github-issue",
  "description": "Analyzes a GitHub issue and creates a PR with the fix",
  "inputs": ["issue_number"],
  "outputs": ["pr_number", "fix_summary"],
  "created_at": "2024-01-15T10:30:00Z",
  "ir_version": "0.1.0",
  "ir": { /* Full workflow IR */ }
}
```

### Phase 3: Integration and Testing (Hours 7-8)

#### Backward Compatibility
```python
def build_context(registry_metadata):
    """
    Existing function - MUST maintain compatibility.

    Implementation:
    - Delegate to new functions internally
    - Return combined output
    - All existing tests must pass
    """
```

## Critical Parser Details to Preserve

### Multi-line Support Fix (CRITICAL)
```python
# Lines 166, 170 in metadata_extractor.py
# Must use .extend() not assignment:
result["inputs"].extend(extracted_inputs)  # ✅ Correct
# NOT: result["inputs"] = extracted_inputs  # ❌ Wrong - loses previous lines
```

### Comma Handling in Descriptions
```python
# Line 374: Regex that preserves commas in descriptions
segments = re.split(r',\s*(?=shared\[)', content)
# BUT still has issues - descriptions with commas need careful handling
```

### Exclusive Params Pattern
```python
# Line 416 in context_builder.py - already implemented
param_names = [param.get("key", param) for param in params]
input_names = [inp.get("key", inp) for inp in inputs]
exclusive_params = [p for p in params if p.get("key", p) not in input_names]
```

## Known Parser Limitations and Workarounds

### 1. Empty Components Break Parser
```python
# This breaks:
- Reads:
- Writes: shared["data"]: str

# Workaround: Always have content after component declarations
```

### 2. Single Quotes Not Supported
```python
shared["key"]  # ✅ Works
shared['key']  # ❌ Doesn't work
```

### 3. Comma Handling Issues
```python
# Original: "File encoding (optional, default: utf-8)"
# Gets truncated due to comma splitting
# Workaround: "File encoding - optional with default utf-8"
```

### 4. Very Long Lines (>1000 chars)
- May hit regex engine limits
- Keep descriptions reasonably sized

## Structure Parsing Usage

### What Already Works
The parser successfully handles:
```python
- Writes: shared["issue_data"]: dict  # GitHub issue
    - number: int  # Issue number
    - user: dict  # Author information
      - login: str  # Username
      - id: int  # User ID
    - labels: list  # Issue labels
      - name: str  # Label name
```

### How to Use in Planning Context
1. The parser sets `_has_structure` flag when it detects nested structures
2. Access parsed structure via metadata's structure field
3. Use existing `_format_structure()` method to display
4. This enables proxy mappings like `issue_data.user.login`

## Testing Strategy

### Critical Test Files
1. `/tests/test_registry/test_metadata_extractor.py`
   - Lines 173, 391, 443, 461: Expect empty params arrays
   - Line 166: Expects full descriptions with commas preserved
   - Many tests adjusted for parser limitations

2. `/tests/test_planning/test_context_builder.py`
   - Must add tests for new two-phase functions
   - Ensure backward compatibility tests pass

### Test Scenarios
1. **Discovery Context**
   - Empty registry
   - Nodes only
   - Nodes + workflows
   - Large registry (100+ components)

2. **Planning Context**
   - Single component selection
   - Multiple components
   - Missing components
   - Structure display formatting

3. **Workflow Loading**
   - Valid workflows
   - Invalid JSON
   - Missing required fields
   - Empty directory
   - Directory doesn't exist

## Edge Cases and Error Handling

### Workflow Discovery
- Directory might not exist → Create it
- Invalid JSON files → Skip with warning
- Missing required fields → Skip with warning
- Duplicate names → Last one wins
- Version conflicts → Not handled in MVP

### Component Selection
- Selected components might not exist
- Could be typos or hallucinations
- Log warnings but don't crash
- Return partial context if some components found

### Structure Parsing
- Already handles most cases well
- Fallback to string representation on errors
- Limit recursion depth for safety

## Performance Considerations

### Current Performance Characteristics
- Dynamic imports can be slow (`__import__`)
- Category detection uses module path parsing
- Structure parsing uses recursion (limit depth)

### Optimization Opportunities (Post-MVP)
- Cache parsed structures
- Lazy load workflow files
- Pre-compute category mappings

## Historical Context and Lessons Learned

### Format Evolution Journey
1. **Simple format first** → Enhanced format added later
2. **Multi-line attempt** → Parser couldn't handle
3. **Comma-separated workaround** → Ugly but functional
4. **Parser fixes** → Back to multi-line
5. **Task 14.3** → All nodes migrated

### Key Insights from Task 14
- User wanted VERBOSE mode (hence 200KB limit)
- Pivot from "navigation hints" to "full structure display"
- Exclusive params pattern is non-negotiable
- Tests are extremely brittle

### Why Two-Phase Matters
- Not just about tokens - it's about cognitive load
- Discovery needs breadth (all components, minimal info)
- Planning needs depth (selected only, full details)
- Enables better LLM decision making

## Success Metrics

### Must Have
- ✅ Two-phase functions work correctly
- ✅ Workflow discovery functional
- ✅ Backward compatibility maintained
- ✅ All existing tests pass
- ✅ Structure information displayed in planning context

### Nice to Have
- Performance improvements
- Enhanced error messages
- Workflow validation beyond basic fields
- Structure parsing enhancements

## Common Pitfalls to Avoid

1. **Don't reimplement structure parsing** - It already works!
2. **Don't break the exclusive params pattern** - Tests depend on it
3. **Don't modify parser regex carelessly** - Very fragile
4. **Don't forget empty params arrays** - Expected by tests
5. **Don't ignore backward compatibility** - build_context() must work

## Quick Reference

### File Locations
- Parser: `/src/pflow/registry/metadata_extractor.py` (lines 543-612)
- Context Builder: `/src/pflow/planning/context_builder.py`
- Tests: `/tests/test_planning/test_context_builder.py`

### Key Methods to Reuse
- `_process_nodes()` - Extract and categorize metadata
- `_format_structure()` - Display hierarchical structures
- `_parse_structure()` - Already parses nested structures!

### Critical Line Numbers
- Line 38: MAX_OUTPUT_SIZE = 200KB
- Line 166, 170: Multi-line fix (.extend())
- Line 374: Comma-aware regex
- Line 416: Exclusive params filtering
- Lines 543-612: Structure parser implementation

## Final Implementation Checklist

- [ ] Create `~/.pflow/workflows/` directory structure
- [ ] Implement `_load_saved_workflows()`
- [ ] Implement `build_discovery_context()`
- [ ] Implement `build_planning_context()`
- [ ] Update `build_context()` to delegate
- [ ] Add comprehensive tests
- [ ] Verify structure display works
- [ ] Test with real workflow files
- [ ] Ensure all existing tests pass
- [ ] Document new functions

Remember: The foundations are solid. Structure parsing works. Focus on the two-phase split and workflow discovery. The planner's success depends on getting this right!
