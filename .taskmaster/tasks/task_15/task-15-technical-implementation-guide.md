# Task 15 Technical Implementation Guide

This document provides the technical implementation details for Task 15, complementing the ambiguities document with specific code locations, critical fixes, and implementation patterns.

## Critical Corrections to Documentation

### 1. Structure Parsing is FULLY IMPLEMENTED ✅
Contrary to documentation claiming it's "scaffolding only", the structure parser is complete and functional:
- **Location**: `metadata_extractor.py` lines 543-612
- **Implementation**: 70-line recursive parser with indentation counting
- **Tests confirm**: Handles nested structures correctly
- **Flag**: Sets `_has_structure` when complex types detected (line 397)

### 2. Actual Context Size Limit
- **Code shows**: `MAX_OUTPUT_SIZE = 200 * 1024` (200KB, not 50KB)
- **Location**: `context_builder.py` line 38
- **Origin**: User requested VERBOSE mode during Task 14.2

### 3. All Nodes Already Migrated
Task 14.3 migrated all 7 nodes to multi-line enhanced format:
- 5 file operation nodes (all with empty params arrays)
- 2 test nodes (test_node_retry has exclusive param)
- All follow exclusive params pattern

### 4. Context Builder Two-File Approach (from Task 14 discussions)
The context builder will create exactly **two markdown files**:
1. **Node Selection File** - Names and descriptions only
2. **Detailed Mapping File** - Full technical details for selected components

## Implementation Roadmap

### Phase 1: Two-Phase Context Split (Hours 1-4)

#### Discovery Context Implementation
```python
def build_discovery_context(registry_metadata, saved_workflows=None):
    """
    Implementation approach:
    1. Reuse existing _process_nodes() for metadata extraction
    2. Format as lightweight markdown (name + description only)
    3. Include workflows alongside nodes
    4. Group by category using existing logic
    """
```

#### Planning Context Implementation
```python
def build_planning_context(selected_components, registry_metadata, saved_workflows=None):
    """
    Implementation approach:
    1. Filter to only selected components
    2. Use existing _format_node_section() for full details
    3. Display structures using _format_structure()
    4. Maintain exclusive params pattern (line 416)
    """
```

### Phase 2: Workflow Discovery (Hours 5-6)

#### Workflow Loading
```python
def _load_saved_workflows():
    """
    Steps:
    1. Create ~/.pflow/workflows/ if missing
    2. Glob all *.json files
    3. Parse and validate (name, description required)
    4. Skip invalid files with warnings
    5. Return list of metadata dicts
    """
```

### Phase 3: Integration (Hours 7-8)

#### Backward Compatibility
```python
def build_context(registry_metadata):
    """Delegate to new functions while maintaining exact output format."""
    # Must pass all existing tests unchanged
```

## Critical Parser Fixes to Preserve

### 1. Multi-line Support (Lines 166, 170)
```python
# CORRECT - preserves all lines:
result["inputs"].extend(extracted_inputs)

# WRONG - only keeps last line:
result["inputs"] = extracted_inputs
```

**History**: Originally used assignment which only kept the last line. Fixed in 14.3 after discovering only the last Reads/Writes line was being preserved.

### 2. Comma-aware Splitting (Line 374)
```python
# Splits on commas ONLY before shared[
segments = re.split(r',\s*(?=shared\[)', content)
# Similar fix for params (line 444):
segments = re.split(r',\s*(?=\w+\s*:)', content)
```

**Limitation**: Still breaks descriptions with commas. Workaround: avoid commas in descriptions or use alternative phrasing.

### 3. Exclusive Params Pattern (Line 416)
```python
# Already implemented - DO NOT BREAK
param_names = [param.get("key", param) for param in params]
input_names = [inp.get("key", inp) for inp in inputs]
exclusive_params = [p for p in params if p.get("key", p) not in input_names]
```

**Critical**: All nodes migrated to use this pattern. Tests expect empty params arrays when all params are in Reads.

## Known Parser Limitations

### Issues and Workarounds

1. **Empty Components Break Parser**
   ```python
   # Breaks:
   - Reads:
   - Writes: shared["data"]: str

   # Fix: Always include content after declarations
   ```

2. **Single Quotes Not Supported**
   ```python
   shared["key"]  # ✅ Works
   shared['key']  # ❌ Fails
   ```

3. **Comma Handling in Descriptions**
   - Original: "File encoding (optional, default: utf-8)"
   - Gets truncated at comma
   - Workaround: "File encoding - optional with default utf-8"

4. **Line Length Limits**
   - Lines >1000 chars may hit regex limits
   - Keep descriptions reasonable

## Structure Parsing Details

### What Already Works
```python
- Writes: shared["issue_data"]: dict  # GitHub issue
    - number: int  # Issue number
    - user: dict  # Author information
      - login: str  # Username
      - id: int  # User ID
    - labels: list  # Issue labels
      - name: str  # Label name
```

### Implementation Details
- **Detection**: Line 397 sets `_has_structure` flag for dict/list types
- **Parsing**: Lines 543-612 implement recursive descent parser
- **Indentation tracking**: Uses `_get_indentation()` helper
- **Access**: via metadata's structure field
- **Display**: Use existing `_format_structure()` method
- **Purpose**: Enables proxy mappings like `issue_data.user.login`

### Parser Test Case That Works
From tests, this successfully parses:
```python
- Writes: shared["issue_data"]: dict  # GitHub issue
    - number: int  # Issue number
    - user: dict  # Author information
      - login: str  # Username
      - id: int  # User ID
```

## Testing Requirements

### Critical Test Expectations
1. **Empty params arrays**: Lines 173, 391, 443, 461 in test_metadata_extractor.py
2. **Full descriptions preserved**: Including commas (line 166)
3. **Backward compatibility**: All existing tests must pass

### New Test Coverage
1. **Discovery Context**
   - Empty registry, nodes only, with workflows
   - Large registry performance

2. **Planning Context**
   - Component filtering
   - Missing components handling
   - Structure display

3. **Workflow Loading**
   - Valid/invalid JSON
   - Missing fields
   - Directory creation

## Performance Characteristics

### Current Bottlenecks
- Dynamic imports via `__import__` (line 192)
- Category detection using module path parsing
- Recursive structure parsing

### Optimization Opportunities (Post-MVP)
- Cache parsed structures
- Pre-compute categories
- Batch workflow loading

## Historical Context

### Format Evolution Journey
1. **Simple format first** → Enhanced format added for type support
2. **Multi-line attempt** → Parser couldn't handle multiple lines
3. **Comma-separated workaround** → Ugly but functional:
   ```python
   # Had to use:
   - Reads: shared["path"]: str  # Path, shared["encoding"]: str  # Encoding
   ```
4. **Parser fixes in 14.3** → Back to clean multi-line format
5. **All nodes migrated** → 7 nodes now use enhanced format

### Key Lessons from Task 14
- **14.1**: Parser designed for backward compatibility made it complex
- **14.2**: User wanted VERBOSE mode (hence 200KB limit)
- **14.2**: Mid-implementation pivot from "navigation hints" to "full structure display"
- **14.3**: Exclusive params pattern is non-negotiable
- **14.4**: Tests are extremely brittle - one change breaks many

### Edge Cases Discovered
- Empty descriptions: `key: type  #` (no text after #)
- Trailing commas: `param1: str, param2: int,`
- Mixed formats in same Interface section
- Unicode in descriptions (works but be careful)
- Malformed input creates nested dicts: `{"key": {"key": "param_name", ...}}`

## Quick Reference

### File Locations
- **Metadata Extractor**: `/src/pflow/registry/metadata_extractor.py`
  - Structure parser: lines 543-612 (recursive implementation)
  - Multi-line fix: lines 166, 170 (.extend() not assignment)
  - Comma regex: line 374 (shared keys), line 444 (params)
  - _has_structure flag: line 397
  - Format detection: lines 261-293

- **Context Builder**: `/src/pflow/planning/context_builder.py`
  - MAX_OUTPUT_SIZE: line 38 (200KB)
  - Exclusive params: line 416
  - _process_nodes(): lines 58-199 (reuse for discovery)
  - _format_structure(): lines 200-228 (ready for structures)
  - _format_node_section(): lines 255-404 (full details)
  - Dynamic imports: line 192 (`__import__`)
  - Category detection: line 119 (module path parsing)

### Methods to Reuse
- `_process_nodes()` - Metadata extraction and categorization
- `_format_structure()` - Structure display (already handles hierarchical data)
- `_parse_structure()` - Already works with tests!
- `_group_nodes_by_category()` - Category logic
- `_get_indentation()` - Helper for structure parsing

### Critical Line Numbers Summary
- Line 38: MAX_OUTPUT_SIZE = 200KB
- Lines 166, 170: Multi-line fix (.extend())
- Line 374: Comma-aware regex for shared keys
- Line 397: _has_structure flag setting
- Line 416: Exclusive params filtering
- Line 444: Comma-aware regex for params
- Lines 543-612: Structure parser implementation

## Implementation Checklist

### Must Complete
- [ ] Create workflow directory structure
- [ ] Implement three functions (discovery, planning, load)
- [ ] Update build_context() delegation
- [ ] Maintain all parser fixes
- [ ] Add comprehensive tests
- [ ] Verify structure display works

### Common Pitfalls
1. **Don't reimplement structure parsing** - Use existing
2. **Don't break exclusive params** - Tests depend on it
3. **Don't modify regex carelessly** - Very fragile
4. **Don't forget empty params arrays** - Expected by tests
5. **Don't skip backward compatibility** - Critical

## Success Verification

### Functionality Tests
- Two-phase split reduces context size appropriately
- Workflows appear in discovery
- Structure information displays correctly
- Missing components handled gracefully
- All existing tests pass

### Integration Tests
- Discovery → Planning flow works
- Backward compatibility maintained
- Performance acceptable (<1s for 100 nodes)

## Additional Critical Details

### From Task 14 Discussions
- **Two markdown files approach**: Context builder creates selection file + mapping file
- **Purpose split**: First file for component selection, second for implementation details
- **Task 14 provides metadata**: Task 15 creates smart views of it
- **Gradual migration**: New two-file approach supplements existing initially

### Node Examples Reference
- **GitHub nodes don't exist yet** (Task 13) but used in all examples
- **/src/pflow/nodes/CLAUDE.md** lines 119-136: Shows ideal enhanced format
- **Test nodes available**: test_node.py, test_node_retry.py for testing

### Workflow Discovery Context
- No standard location exists yet - Task 15 defines it as `~/.pflow/workflows/`
- Need to handle version conflicts (same name, different content)
- Distinguish workflows from nodes in discovery (mark as "workflow")
- Workflows are building blocks that can be used in other workflows

### Your Critical Path (Time Estimates)
1. **Hour 1-2**: Read all files, run tests, understand current state
2. **Hour 3-4**: Implement two-phase split (easy win)
3. **Hour 5-6**: Add workflow discovery (medium difficulty)
4. **Hour 7-8**: Test structure parsing with proxy mappings

Remember: The parser works, structure handling exists, exclusive params pattern is implemented. The foundation is solid but fragile - build on it carefully. One wrong regex change can break 20 tests.
