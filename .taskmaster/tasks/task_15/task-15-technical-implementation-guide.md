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

### 4. Task 15 is Now Complete ✅
All subtasks have been implemented:
- 15.1: Workflow loading infrastructure
- 15.2: Two-phase context builder functions
- 15.3: Structure display enhancement (via _format_structure_combined)
- 15.4: Integration of all components with testing

### 5. Context Builder Two-Phase Approach (from Task 14 discussions)
The context builder will create exactly **two markdown strings** (not files):
1. **Discovery Context** - Names and descriptions only (returned from `build_discovery_context()`)
2. **Planning Context** - Full technical details for selected components (returned from `build_planning_context()`)

## Implementation Status ✅ COMPLETE

### What Was Actually Implemented

#### Discovery Context Implementation ✅
```python
def build_discovery_context(
    node_ids: Optional[list[str]] = None,
    workflow_names: Optional[list[str]] = None,
    registry_metadata: Optional[dict[str, dict[str, Any]]] = None,
) -> str:
    """
    IMPLEMENTED with:
    - Input validation for all parameters
    - Reuses _process_nodes() for metadata extraction
    - Groups by category using _group_nodes_by_category()
    - Includes workflow discovery from _load_saved_workflows()
    - Helper functions to reduce complexity
    """
```

#### Planning Context Implementation ✅
```python
def build_planning_context(
    selected_node_ids: list[str],
    selected_workflow_names: list[str],
    registry_metadata: dict[str, dict[str, Any]],
    saved_workflows: Optional[list[dict[str, Any]]] = None,
) -> str | dict[str, Any]:
    """
    IMPLEMENTED with:
    - Input validation for all parameters
    - Returns error dict if components missing
    - Uses _format_node_section_enhanced() (NOT the old _format_node_section)
    - Displays structures using _format_structure_combined() (NOT _format_structure)
    - Helper functions to reduce complexity
    """
```

#### Workflow Loading ✅
```python
def _load_saved_workflows():
    """
    IMPLEMENTED exactly as specified:
    - Creates ~/.pflow/workflows/ if missing
    - Validates required fields (name, description, inputs, outputs, ir)
    - Skips invalid files with warnings
    - Returns list of workflow metadata
    """
```

#### CRITICAL CHANGE: build_context() Was REMOVED ❌
```python
# build_context() was NOT refactored - it was completely REMOVED
# Along with its helper _format_node_section()
# The old _format_structure() is deprecated but kept for reference

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
- **Display**: Use `_format_structure_combined()` method (NOT the deprecated `_format_structure()`)
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
3. **Updated functionality**: Tests may need updates for refactored build_context()

### Test Coverage (Complete ✅)

**Primary Test File**: `tests/test_planning/test_context_builder_phases.py` (33 tests)
- Discovery context tests (7 tests including input validation)
- Planning context tests (7 tests including input validation)
- Structure combined format tests (4 tests)
- Shared functionality tests (4 tests for _process_nodes error handling)
- Helper function tests (4 tests for category grouping)
- Enhanced formatter tests (7 tests for edge cases)

**Integration Tests**: `tests/test_integration/test_context_builder_integration.py`
- Full discovery → planning flow
- Real node loading and formatting
- Workflow integration

**Performance Tests**: `tests/test_integration/test_context_builder_performance.py`
- 100+ nodes performance benchmarks
- Context size validation

**REMOVED**: `tests/test_planning/test_context_builder.py` (old tests file)

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
  - Note: Line numbers have changed after refactoring for complexity
  - build_discovery_context() and build_planning_context() are the main entry points
  - Helper functions added: _validate_discovery_inputs(), _format_discovery_nodes(), etc.
  - _format_structure_combined() is the preferred structure formatter
  - _format_node_section_enhanced() replaced the old formatter

### Methods Still in Use
- `_process_nodes()` - Metadata extraction and categorization (used by both discovery and planning)
- `_format_structure_combined()` - Combined JSON + paths format (PREFERRED for structure display)
- `_parse_structure()` - Structure parser in metadata_extractor.py
- `_group_nodes_by_category()` - Category logic
- `_format_node_section_enhanced()` - Enhanced node formatting (replaced _format_node_section)

### Deprecated/Removed Methods
- `build_context()` - REMOVED completely
- `_format_structure()` - DEPRECATED, use `_format_structure_combined()` instead
- `_format_node_section()` - REMOVED, use `_format_node_section_enhanced()` instead

### Critical Line Numbers Summary
Note: These line numbers are from the original implementation and may have shifted:
- metadata_extractor.py remains unchanged:
  - Lines 166, 170: Multi-line fix (.extend())
  - Line 374: Comma-aware regex for shared keys
  - Line 397: _has_structure flag setting
  - Line 444: Comma-aware regex for params
  - Lines 543-612: Structure parser implementation
- context_builder.py line numbers have changed due to refactoring

## Implementation Summary (Task 15 Complete ✅)

### What Was Completed
- [x] Created workflow directory structure (`~/.pflow/workflows/`)
- [x] Implemented three main functions (discovery, planning, load)
- [x] REMOVED build_context() entirely (not refactored)
- [x] Created NEW _format_structure_combined() for JSON + paths format
- [x] Added input validation to both new functions
- [x] Added helper functions to reduce complexity (C901 compliance)
- [x] Maintained all parser fixes
- [x] Added comprehensive tests (33 tests in test_context_builder_phases.py)
- [x] Added integration tests (test_context_builder_integration.py)
- [x] Added performance tests (test_context_builder_performance.py)

### Key Implementation Decisions
1. **build_context() was REMOVED, not refactored** - Cleaner approach
2. **_format_structure() remains but is DEPRECATED** - Use _format_structure_combined()
3. **Input validation added** - Prevents unclear errors deep in code
4. **Complexity reduced** - Helper functions extracted for ruff C901 compliance
5. **Comprehensive test migration** - All critical tests moved to new file

## Success Verification

### Functionality Tests
- Two-phase split reduces context size appropriately
- Workflows appear in discovery
- Structure information displays correctly
- Missing components handled gracefully
- All existing tests pass

### Integration Tests
- Discovery → Planning flow works
- build_context() properly refactored
- Performance acceptable (<1s for 100 nodes)

## Additional Critical Details

### From Task 14 Discussions
- **Two-phase approach**: Context builder creates discovery context + planning context
- **Purpose split**: Discovery for component selection, planning for implementation details
- **Task 14 provides metadata**: Task 15 creates smart views of it
- **Gradual migration**: New two-phase approach supplements existing initially
- **Important**: No placeholder text for missing descriptions - just omit them

### Node Examples Reference
- **GitHub nodes don't exist yet** (Task 13) but used in all examples
- **/src/pflow/nodes/CLAUDE.md** lines 119-136: Shows ideal enhanced format
- **Test nodes available**: test_node.py, test_node_retry.py, test_node_structured.py (already exists with nested structure outputs)

### Workflow Discovery Context
- No standard location exists yet - Task 15 defines it as `~/.pflow/workflows/`
- Need to handle version conflicts (same name, different content)
- Distinguish workflows from nodes in discovery (mark as "workflow")
- Workflows are building blocks that can be used in other workflows

### A possible Path
-  1. Read all files, run tests, understand current state
-  2. Implement two-phase split (easy win)
-  3. Add workflow discovery (medium difficulty)
-  4. Test structure parsing with proxy mappings

Remember: The parser works, structure handling exists, exclusive params pattern is implemented. The foundation is solid but fragile - build on it carefully. One wrong regex change can break 20 tests.

## Key Differences from Ambiguities Document

This technical guide focuses on:
- **Exact line numbers** for critical code locations
- **Specific code patterns** to preserve or avoid
- **Test expectations** and brittle points
- **Implementation checklist** with concrete steps

The ambiguities document focuses on:
- **Decision rationale** and why choices were made
- **Conceptual understanding** of the system
- **Integration with planner** (Task 17)
- **Example outputs** and usage scenarios

Use both documents together for complete understanding.

## Suggested Implementation Approach

**Note**: This is just one suggested approach. Feel free to adapt based on what makes sense as you implement.

**⚠️ CRITICAL REMINDER**: This list is NOT exhaustive! As the implementing agent, you must:
- Verify every detail from both this guide and the ambiguities document
- Think through edge cases and error scenarios
- Add any missing steps discovered during implementation
- Double-check that nothing is forgotten or omitted
- Be prepared for unexpected complexities that may require additional work
- Read the actual code to understand current implementation details
- Run existing tests to see what's expected

Remember: These documents provide guidance, but YOU are responsible for ensuring completeness and correctness of the implementation.

### Subtask 1: Workflow Infrastructure Foundation
**Rationale**: Other features depend on being able to load workflows. Start here to unblock everything else.

**Components to implement**:
- Workflow directory utilities
  - Create `~/.pflow/workflows/` if missing
  - Safe path operations

- `_load_saved_workflows()` function
  - Parse JSON files from workflow directory
  - Validate essential fields only (name, description, inputs, outputs, ir) - ignore optional fields for MVP
  - Skip invalid files with warnings (don't crash)
  - Return consistent format for use by context builders

- Test workflow creation
  - Use test nodes (test_node, test_node_structured)
  - Create 2-3 valid test workflows
  - Create 1-2 invalid ones for error case testing

### Subtask 2: Two-Phase Context Builder Functions
**Rationale**: These are the main deliverables. Build on workflow loading from Subtask 1.

**Components to implement**:
- `build_discovery_context()` function
  - Extract just names/descriptions from nodes
  - Include workflows from `_load_saved_workflows()`
  - Group by categories using existing logic
  - Omit missing descriptions (no placeholders)

- `build_planning_context()` function
  - Check for missing components first
  - Return error dict if any missing (for discovery retry)
  - Filter to selected components only
  - Display full details with combined JSON + paths format
  - Leverage existing `_format_structure()` for hierarchical data

- Refactor `build_context()`
  - No backward compatibility needed
  - Can rewrite to match `build_planning_context()` approach
  - Update tests as needed

### Subtask 3: Comprehensive Testing
**Rationale**: Verify everything works together and catches edge cases.

**Components to implement**:
- Unit tests for new functions
  - Workflow loading edge cases (invalid JSON, missing fields)
  - Discovery with various component counts (0, 10, 100)
  - Planning with missing components
  - Structure display formatting

- Integration tests
  - Full discovery → planning flow
  - Error recovery scenarios
  - Backward compatibility verification

- Final verification
  - All existing tests still pass
  - Performance acceptable with realistic data
  - Structure parsing still works correctly

## Why This Order?

1. **Workflow loading is independent** - Can be built and tested in isolation
2. **Discovery is simpler than planning** - Good warmup for the pattern
3. **Backward compatibility is easier** - Once new functions work, delegation is straightforward
4. **Testing throughout is critical** - But comprehensive suite at end catches integration issues

Remember: Reuse existing methods, don't modify the fragile parser, keep it simple for MVP.

## Notes

*This document has been updated to reflect the completed implementation of Task 15. Key clarifications:*
- *build_context() was REMOVED entirely, not refactored*
- *_format_structure() is DEPRECATED - use _format_structure_combined() instead*
- *All functionality is now complete with comprehensive test coverage*
- *Line numbers in context_builder.py have changed due to refactoring*

*This document now serves as a reference for understanding what was implemented in Task 15.*
