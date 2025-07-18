# Task 15 Knowledge Extraction from Handover Documents

This document extracts and consolidates knowledge from the four Task 15 handover documents, preserving all relevant information while removing duplicates and correcting obvious errors.

## Critical Context from Task 14

### Enhanced Interface Format Implementation
- Task 14 implemented Enhanced Interface Format with type annotations and semantic descriptions
- Format example:
  ```python
  Interface:
  - Reads: shared["file_path"]: str  # Path to the file to read
  - Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
  - Writes: shared["content"]: str  # File contents with line numbers
  - Writes: shared["error"]: str  # Error message if operation failed
  - Actions: default (success), error (failure)
  ```

### Structure Parsing - CRITICAL DISCOVERY
**The structure parser IS ALREADY IMPLEMENTED** (contrary to what some docs suggest):
- `_parse_structure()` method exists in `metadata_extractor.py` (lines 543-612)
- Full 70-line recursive implementation
- Sets `_has_structure` flag for complex types
- Successfully parses indented structures:
  ```python
  - Writes: shared["data"]: dict  # User data
      - name: str  # User name
      - age: int  # User age
  ```
- Tests confirm it works for nested structures

### Parser Limitations and Bugs
1. **Comma handling bug**:
   - Splits on ALL commas including those in descriptions
   - Line 374: `segments = re.split(r',\s*(?=shared\[)', content)`
   - Descriptions like "File encoding (optional, default: utf-8)" get truncated
   - Workaround: Use awkward phrasing like "optional with default utf-8"

2. **Multi-line handling fix** (lines 166, 170):
   - Must use `.extend()` to combine multiple Reads/Writes lines
   - Without this, only the LAST line of each type is kept

3. **Single quote support broken**:
   - Only `shared["key"]` works, not `shared['key']`

4. **Empty component bug**:
   - Empty Reads/Writes (like `- Reads:` with no content) breaks parser
   - Following lines get misaligned

5. **Very long lines** (>1000 chars) may not parse due to regex limits

6. **Malformed format handling**:
   - Creates nested dicts when format is malformed
   - Example: `param_name: type: extra` → `{"key": {"key": "param_name", ...}, ...}`

### Exclusive Params Pattern
- ALL nodes now have empty params arrays if all params are in Reads
- Context builder MUST filter: `exclusive_params = [p for p in params if p not in inputs]`
- Tests expect this pattern

### Context Builder Current State
The context builder (modified in Task 14.2) already has:
- Type information display: `file_path: str`
- Description display: `Path to the file to read`
- `_format_structure()` method for hierarchical structures
- `_process_nodes()` to extract metadata (ready for splitting)
- MAX_OUTPUT_SIZE = 200KB (not 50KB as some docs suggest)

### Node Migration Status
All 7 nodes in `/src/pflow/nodes/` use multi-line enhanced format:
- `file/read_file.py` - No Params section (all are fallbacks)
- `file/write_file.py` - Only `append` param (exclusive)
- `file/copy_file.py` - No Params section
- `file/move_file.py` - No Params section
- `file/delete_file.py` - No Params section
- `test_node.py` - Basic enhanced format
- `test_node_retry.py` - Has `max_retries` param (exclusive)

## Two-Phase Context Building Architecture

### Phase 1: Discovery Context
- Lightweight context for finding relevant nodes
- Contains ONLY node names and descriptions
- No technical details, interface info, or structure
- Optimized for quick LLM processing
- Example:
  ```markdown
  ### github-get-issue
  Fetches issue details from GitHub

  ### read-file
  Reads content from a file
  ```

### Phase 2: Planning Context (Implementation Context)
- Detailed context for selected nodes only
- Full interface details with types and descriptions
- Structure information for nested data
- Everything needed for workflow generation and proxy mappings
- Clearly distinguish workflows vs nodes

## Critical Implementation Details

### File Locations and Line Numbers
1. `/src/pflow/registry/metadata_extractor.py`:
   - Lines 543-612: `_parse_structure()` - FULLY IMPLEMENTED
   - Line 397: Sets `_has_structure` flag
   - Lines 166, 170: Multi-line support fix
   - Line 374: Comma-aware regex for shared keys
   - Line 444: Similar fix for params
   - Lines 261-293: Format detection logic

2. `/src/pflow/planning/context_builder.py`:
   - Lines 58-199: `_process_nodes()` - ready for reuse
   - Lines 200-228: `_format_structure()` - can display hierarchical data
   - Lines 255-404: `_format_node_section()` - shows types and descriptions
   - Line 416: Exclusive params filtering already implemented
   - Line 38: MAX_OUTPUT_SIZE = 200KB

### Two-Phase Implementation Strategy
```python
def build_discovery_context(registry_metadata, saved_workflows=None):
    # Reuse _process_nodes() but format differently
    # Just: "### node-name\nOne line description"
    # DO NOT include types, params, structure

def build_planning_context(selected_components, registry_metadata, saved_workflows=None):
    # Full current format but ONLY for selected
    # This is where structure would be shown

def build_context(registry_metadata):
    # KEEP THIS! Maintain backward compatibility
    # Maybe call both functions internally
```

## Workflow Discovery Requirements

### Workflow Storage Format
Location: `~/.pflow/workflows/*.json`

Schema:
```json
{
  "name": "fix-github-issue",
  "description": "Analyzes a GitHub issue and creates a PR with the fix",
  "inputs": ["issue_number"],
  "outputs": ["pr_number", "fix_summary"],
  "created_at": "2024-01-15T10:30:00Z",
  "ir_version": "0.1.0",
  "ir": {
    // Full workflow IR
  }
}
```

### Implementation Requirements
1. Create directory if it doesn't exist
2. Load all *.json files from ~/.pflow/workflows/
3. Validate basic structure (name, description required)
4. Handle invalid JSON gracefully (log warning, skip file)
5. Workflows need clear visual distinction from nodes in context

## Structure Documentation Requirements

### Current State CORRECTION
The documentation states structure parsing is "scaffolding only" but this is INCORRECT:
- `_parse_structure()` is FULLY IMPLEMENTED (70 lines of recursive parsing)
- It uses indentation-based parsing with recursion
- Handles nested structures successfully
- Tests confirm it works

### What Task 15 Needs to Do
1. Use the existing structure parser (don't reimplement!)
2. Test edge cases if any are discovered
3. Format the parsed structure for display in planning context
4. Enable proxy mappings like `data.user.login`

### Example That Already Works
```python
- Writes: shared["issue_data"]: dict  # GitHub issue
    - number: int  # Issue number
    - user: dict  # Author information
      - login: str  # Username
      - id: int  # User ID
```

## Critical Warnings and Edge Cases

### Parser Fragility
- One wrong regex can break everything
- Test data vs real data differs significantly
- Backward compatibility makes changes complex
- The parser fixes from 14.3 are "held together with duct tape"

### Testing Considerations
- Tests are brittle - one change can break 20 tests
- Tests expect empty params arrays for nodes with all params as fallbacks
- Many tests adjusted for parser limitations
- The metadata flow affects entire pipeline: Docstring → Extractor → Registry → Context Builder → Planner

### Context Size Considerations
- 50KB limit mentioned in specs but code shows 200KB
- Two-phase split is about cognitive load, not just token limits
- Discovery phase: Names and descriptions ONLY
- Planning phase: Full details for selected components only

### Dynamic Import Issues
- Context builder uses `__import__` (line 192) which makes testing hard
- Category detection uses module path parsing

## Key Insights from Discussions

### Context Builder Ownership
**The context builder is responsible for preparing and splitting the information.** Task 14 only provides enriched metadata - Task 15 decides how to present it.

### Two Markdown Files Strategy
The context builder will create exactly two markdown files:
1. **Node Selection File** (discovery phase) - Names and descriptions only
2. **Detailed Mapping File** (planning phase) - Full technical details

### Benefits of Two-Phase Approach
1. Improved Planning Accuracy - LLM focuses on relevant information
2. Better Performance - Reduced token usage
3. Scalability - Efficient as node library grows
4. Flexibility - Different strategies can use different contexts

### Evolution Path
- Dynamic context generation based on user input
- Caching of common planning patterns
- Integration with vector search for large libraries
- Potential for learned context selection

## Implementation Order and Priorities

1. **Start with two-phase split** (easiest win)
2. **Add workflow discovery** (medium difficulty)
3. **Use existing structure parsing** (already implemented!)
4. **Maintain backward compatibility** (keep build_context() working)
5. **Handle edge cases gracefully**

## Success Criteria

### Discovery Context
- Super lightweight (names and descriptions only)
- No types, params, or structure information
- Include both nodes AND workflows
- Group by category
- Under 50KB for 100+ components

### Planning Context
- Detailed, but ONLY for selected components
- Full interface details with types
- Structure information displayed
- Clear workflow vs node distinction

### Overall
- Backward compatibility maintained
- All existing tests pass
- Performance not degraded
- Workflows are first-class citizens alongside nodes

## Historical Context from Task 14

### Format Evolution
1. Started with simple format, enhanced format added later
2. Initially tried multi-line format but parser couldn't handle
3. Switched to comma-separated (ugly but worked)
4. Then fixed parser to support multi-line again
5. This history explains some of the complexity

### User Feedback During 14.2
- User wanted VERBOSE mode to show everything
- Pivot from "navigation hints" to "full structure display"
- This changed implementation mid-task
- The groundwork for Task 15 was laid during this pivot

## Notes on Ambiguities and Conflicts

### Structure Parsing Status
- Multiple docs contradict on whether structure parsing is implemented
- **TRUTH**: It IS implemented (lines 543-612 in metadata_extractor.py)
- The "scaffolding only" comment is outdated

### Context Size Limits
- Specs mention 50KB but code shows 200KB
- **Use 200KB** as the actual limit

### Workflow Storage
- No standard location exists yet - Task 15 defines it
- Suggested: `~/.pflow/workflows/`
- Need to handle version conflicts and invalid files

### GitHub Nodes
- Used as examples everywhere but don't exist yet (Task 13)
- Use test nodes for actual testing
