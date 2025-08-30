# Task 15 Handoff Memo - Enhanced Edition

**⚠️ CRITICAL**: Do NOT begin implementing yet. Read this ENTIRE handoff first, absorb all the context, and confirm you understand before starting. This is your only chance to get the full picture.

## Critical Context from Task 14

### What We Built (and What We REALLY Didn't)

Task 14 implemented the **Enhanced Interface Format** with type annotations and semantic descriptions:

```python
Interface:
- Reads: shared["file_path"]: str  # Path to the file to read
- Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
- Writes: shared["content"]: str  # File contents with line numbers
- Writes: shared["error"]: str  # Error message if operation failed
- Actions: default (success), error (failure)
```

**CRITICAL CONTEXT #1**: Structure parsing IS implemented. The parser sets a `_has_structure` flag for complex types and DOES parse the indented structure:

```python
# This is recognized AND parsed:
- Writes: shared["data"]: dict  # User data
    - name: str  # User name
    - age: int  # User age
```

The `_parse_structure()` method exists in `metadata_extractor.py` (lines 543-612) with a full 70-line recursive implementation. Tests confirm it works for nested structures.

**CRITICAL LIMITATION #2**: The parser has SEVERE limitations with comma handling:
- Splits on ALL commas, including those in descriptions
- Line 374 in metadata_extractor.py: `segments = re.split(r',\s*(?=shared\[)', content)`
- This means descriptions like "File encoding (optional, default: utf-8)" get truncated
- We had to use awkward phrasing like "optional with default utf-8" to work around this

### Parser Fixes from 14.3 That You MUST Preserve

During 14.3, I discovered and fixed critical parser bugs:

1. **Multi-line handling bug** (lines 166, 170):
   - OLD: `result["inputs"] = self._extract_interface_component(...)` (replaced list)
   - NEW: Uses `.extend()` to combine multiple Reads/Writes lines
   - Without this, only the LAST line of each type was kept!

2. **Comma splitting fix** (line 374):
   - Uses lookahead regex to only split on commas before `shared[`
   - BUT still breaks descriptions with commas
   - Params splitting (line 444) has similar fix

3. **Exclusive Params Pattern**:
   - ALL nodes now have empty params arrays if all params are in Reads
   - Context builder MUST filter: `exclusive_params = [p for p in params if p not in inputs]`
   - Tests expect this! See test changes in commit history

### Current Context Builder State

The context builder (modified in 14.2) already:
- Shows type information: `file_path: str`
- Shows descriptions: `Path to the file to read`
- Has `_format_structure()` method that can display hierarchical structures
- Uses `_process_nodes()` to extract metadata (ready for splitting)
- **MAX_OUTPUT_SIZE = 200 * 1024** (200KB limit, not 50KB!)

**Key insight from 14.2**: During implementation, the user revealed Task 15 plans, causing a major pivot from "navigation hints" to "full structure display". The groundwork is there.

## Critical Files and Their EXACT State

### 1. `/src/pflow/registry/metadata_extractor.py`
- **Lines 543-612**: `_parse_structure()` method - FULLY IMPLEMENTED with recursive parsing
- **Line 397**: Sets `_has_structure` flag for dict/list types
- **Lines 166, 170**: Multi-line support via `.extend()` - CRITICAL FIX
- **Line 374**: Comma-aware regex for shared keys: `r',\s*(?=shared\[)'`
- **Line 444**: Similar comma fix for params: `r',\s*(?=\w+\s*:)'`
- **Lines 261-293**: Format detection logic (looks for `:` after keys)

### 2. `/src/pflow/planning/context_builder.py`
- **Lines 58-199**: `_process_nodes()` extracts all metadata
- **Lines 200-228**: `_format_structure()` can display hierarchical data
- **Lines 255-404**: `_format_node_section()` shows types and descriptions
- **Line 416**: Exclusive params filtering already implemented!
- **Line 38**: MAX_OUTPUT_SIZE = 200KB (not 50KB as docs suggest)

### 3. Node Migration State (ALL 7 nodes updated)
All nodes in `/src/pflow/nodes/` now use multi-line enhanced format:
- `file/read_file.py` - No Params section (all are fallbacks)
- `file/write_file.py` - Only `append` param (exclusive)
- `file/copy_file.py` - No Params section
- `file/move_file.py` - No Params section
- `file/delete_file.py` - No Params section
- `test_node.py` - Basic enhanced format
- `test_node_retry.py` - Has `max_retries` param (exclusive)

### 4. Test Expectations Have Changed!
- `/tests/test_registry/test_metadata_extractor.py`:
  - Lines 173, 391, 443, 461: Tests expect empty params arrays
  - Line 166: Tests expect full descriptions with commas preserved
  - Many tests adjusted for parser limitations (see lines 245-254)

## Warnings and Gotchas - EXPANDED

### 1. Structure Parsing Complexity - ALREADY IMPLEMENTED
The parser uses an indentation-based approach that works well. However:
- Current implementation handles nested structures via recursion
- Edge cases with complex punctuation may still exist
- The 7+ regex patterns handle different format variations
- Implementation is functional but could be refined for edge cases

**Specific example that WILL break**:
```python
- Writes: shared["data"]: dict  # Data (with notes, and commas)
    - field: str  # Description (breaks: here)
```

### 2. The Empty Component Bug
If a node has empty Reads/Writes (like `- Reads:` with no content), the parser BREAKS:
- Following lines get misaligned
- See test_empty_components_without_content (line 245)
- This is a KNOWN BUG we just work around

### 3. Single Quote Support is Broken
The parser only supports double quotes in shared keys:
- `shared["key"]` ✓ Works
- `shared['key']` ✗ Not extracted
- See test at line 198 with comment about single quotes

### 4. Very Long Lines Cause Issues
Lines over ~1000 chars may not parse at all (regex engine limits)
See test_very_long_lines_edge_case (line 306)

### 5. Parser Creates Malformed Structures
When enhanced format is malformed, parser creates nested dicts:
```python
# Input: param_name: type: extra
# Output: {"key": {"key": "param_name", ...}, ...}
```
See test_malformed_input_recovery (line 332)

## Hidden Knowledge from Previous Tasks - EXPANDED

### From 14.1 Parser Implementation
- The parser was designed for simple format first, enhanced added later
- Backward compatibility made everything 10x more complex
- The "rich format" internal representation helped but added conversion overhead
- Detection logic (has colons?) is fragile

### From 14.2 Context Builder
- Dynamic imports make testing hard (line 192 uses `__import__`)
- User wanted VERBOSE mode to show everything (that's why 200KB limit)
- Category detection uses module path parsing (line 119)
- The pivot to showing structures changed everything mid-implementation

### From 14.3 Format Migration
**CRITICAL**: I tried multi-line format first:
```python
# IDEAL but parser couldn't handle:
- Reads: shared["path"]: str  # Path
- Reads: shared["encoding"]: str  # Encoding
```

Had to use comma-separated:
```python
# UGLY but works:
- Reads: shared["path"]: str  # Path, shared["encoding"]: str  # Encoding
```

Then went BACK to multi-line after fixing parser! This history matters.

### From 14.4 Testing
Edge cases that broke during testing:
- Empty descriptions: `key: type  #` (no description after #)
- Trailing commas: `param1: str, param2: int,`
- Mixed formats in same Interface section
- Unicode in descriptions (works but be careful)

## Implementation Recommendations - DETAILED

### 1. Two-Phase Split Strategy
```python
def build_discovery_context(self, registry_metadata, saved_workflows=None):
    # Reuse _process_nodes() but format differently
    # Just: "### node-name\nOne line description"
    # DO NOT include types, params, structure - too heavy

def build_planning_context(self, selected_components):
    # Full current format but ONLY for selected
    # This is where structure would be shown

def build_context(self, registry_metadata):
    # KEEP THIS! Maybe call both functions for compatibility
    # Or add a mode parameter
```

### 2. Workflow Discovery Challenges
- No standard location exists yet - you define it
- Consider: `~/.pflow/workflows/`, `./workflows/`, or config-based
- Need to handle version conflicts (same name, different content)
- JSON parsing errors WILL happen - handle gracefully
- How to distinguish workflow from node in discovery?

### 3. Structure Parsing - Already Working
The implementation uses:
1. **Recursive parsing**: Handles multiple indent levels
2. **Line-by-line with indent counting**: Tracks indentation via `_get_indentation()`
3. **Recursive descent**: Implemented in `_parse_structure()`
4. **Tests confirm**: Nested structures work as expected

**Test case that DOES work**:
```python
- Writes: shared["issue_data"]: dict  # GitHub issue
    - number: int  # Issue number
    - user: dict  # Author information
      - login: str  # Username
      - id: int  # User ID
```

### 4. Exclusive Params Pattern Preservation
The context builder already does this (line 416):
```python
# Only show params not in inputs
param_names = [param.get("key", param) for param in params]
input_names = [inp.get("key", inp) for inp in inputs]
exclusive_params = [p for p in params if p.get("key", p) not in input_names]
```

DO NOT break this - all nodes depend on it!

## Files You'll Need - WITH LINE NUMBERS

- `/src/pflow/planning/context_builder.py`:
  - Lines 58-199: `_process_nodes()` - reuse for discovery
  - Line 416: Exclusive params filtering
  - Lines 200-228: `_format_structure()` - ready for structures

- `/src/pflow/registry/metadata_extractor.py`:
  - Lines 543-612: `_parse_structure()` - already implemented, works with tests
  - Line 370: Where `_has_structure` is set
  - Lines 375-376: Comma splitting logic

- `/tests/test_planning/test_context_builder.py`:
  - Existing tests must pass!
  - Add tests for two-phase functions

- `/architecture/reference/enhanced-interface-format.md`:
  - Documents the structure format (including nested structures)
  - Has examples that the parser can handle

- `/.taskmaster/knowledge/patterns.md`:
  - "Exclusive Params Pattern" - critical context

- `/src/pflow/nodes/CLAUDE.md`:
  - Lines 119-136: Shows ideal enhanced format

## What Success REALLY Looks Like

### 1. Discovery Context (super lightweight):
```markdown
## Available Nodes

### file/read-file
Read content from a file and add line numbers for display

### file/write-file
Write content to a file with automatic directory creation

### github/get-issue
Fetches issue details from GitHub

## Available Workflows

### fix-issue-workflow
Analyzes and fixes GitHub issues automatically
```

NO types, NO params, NO structure - just names and one-liners!

### 2. Planning Context (detailed, ONLY selected):
```markdown
### github-get-issue
Fetches issue details from GitHub

**Inputs**:
- `issue_number: int` - GitHub issue number to fetch
- `repo: str` - Repository name in owner/repo format

**Outputs**:
- `issue_data: dict` - Complete issue data from GitHub API
  Structure of issue_data:
    - number: int - Issue number
    - title: str - Issue title
    - user: dict - Author information
      - login: str - GitHub username
      - id: int - User ID
    - labels: list - Issue labels

**Actions**: default (success), error (API failure)
```

### 3. Planner Output:
```json
{
  "nodes": [{
    "name": "github-get-issue",
    "proxy_map": {
      "author_name": "issue_data.user.login",
      "issue_title": "issue_data.title"
    }
  }]
}
```

## Critical Things I Learned The Hard Way

1. **The parser is more fragile than it looks** - One wrong regex and everything breaks
2. **Test data vs real data differs** - Real nodes have messy descriptions
3. **Backward compatibility is a nightmare** - Every change breaks something
4. **The exclusive params pattern is non-negotiable** - User is adamant about this
5. **Structure parsing uses indentation-based approach** - Pure regex doesn't work, recursion does
6. **Empty components break everything** - Always have content after `- Reads:`
7. **Commas in descriptions need escaping** - Or just avoid them

## Your Critical Path

1. **Hour 1-2**: Read all the files, run tests, understand current state
2. **Hour 3-4**: Implement two-phase split (easy win)
3. **Hour 5-6**: Add workflow discovery (medium difficulty)
4. **Hour 7-8**: Test structure parsing with proxy mappings (already implemented)

## Final Warnings

- The user correctly expects structure parsing to work (and it does)
- GitHub nodes don't exist yet (Task 13) but everyone uses them as examples
- The 50KB limit in specs is actually 200KB in code
- Tests are brittle - one change can break 20 tests
- The parser fixes from 14.3 are held together with duct tape

## Most Important Thing

**Structure parsing is already implemented and working**. The planner can generate proxy mappings using the existing functionality. Tests show it handles nested structures correctly. Focus on:
1. Using the existing structure parsing for proxy mappings
2. Testing edge cases if any are discovered
3. Building the two-phase context split on top of this foundation

The foundations are all there from Task 14, including the structure parsing that tests confirm is functional.

**Remember**: Confirm you understand ALL of this before starting. The success of the planner depends on getting Task 15 right.

Good luck! You're building on a complex foundation with many hidden gotchas.
