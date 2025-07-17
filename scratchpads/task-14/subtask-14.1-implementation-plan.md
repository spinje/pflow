# Implementation Plan for Subtask 14.1

## IMMEDIATE: Fix the Multi-Item Comment Bug

**THE FIRST THING TO DO**: The implementation already started but hit a bug. Fix this before anything else.

### The Bug
```python
# Input:
"Writes: shared["key1"]: str, shared["key2"]: str  # shared comment"

# Current behavior: Both keys get "shared comment"
# Correct behavior: Only last key (key2) should get the comment
```

### Fix Strategy
1. Look at the regex pattern in `_parse_enhanced_interface_item()`
2. The pattern likely captures the entire line's comment
3. Need to split the line first, then parse each item individually
4. Only the last item on a line gets the trailing comment

## Step-by-Step Implementation Plan

### Step 1: Understand Current State (30 min)
1. Read `src/pflow/registry/metadata_extractor.py` completely
2. Find what's been added for enhanced parsing
3. Run the failing test to see exact behavior
4. Understand the regex pattern causing the issue

### Step 2: Fix Multi-Item Comment Bug (1 hour)
1. Modify parsing to handle comma-separated items correctly:
   ```python
   # Pseudocode approach:
   line = "Writes: shared["key1"]: str, shared["key2"]: str  # comment"
   items = split_by_comma_outside_brackets(line)
   for i, item in enumerate(items):
       if i == len(items) - 1:
           # Last item gets the comment
           parse_with_comment(item)
       else:
           # Other items parsed without comment
           parse_without_comment(item)
   ```

2. Test cases to verify:
   - Single item with comment
   - Multiple items, comment on last
   - Multiple items, no comment
   - Mixed simple and enhanced on same line

### Step 3: Complete Enhanced Parsing (2 hours)
1. Finish `_extract_enhanced_interface()` method
2. Ensure it returns rich format for ALL components:
   - Reads → inputs with type/description
   - Writes → outputs with type/description
   - Params → params with type/description

3. Format transformation:
   ```python
   # From: ["key1", "key2"]
   # To: [{"key": "key1", "type": "str", "description": ""}]
   ```

### Step 4: Implement Structure Parsing (3 hours)
This is the complex part - indentation-based parsing.

1. Create `_parse_structure()` method:
   ```python
   def _parse_structure(self, lines: List[str], start_idx: int) -> Tuple[dict, int]:
       """Parse indented structure starting at start_idx.
       Returns (structure_dict, next_line_idx).
       """
   ```

2. Algorithm:
   - Track base indentation level
   - Parse each line's field: type # description
   - If next line is more indented, recursively parse sub-structure
   - Build nested dictionary

3. Handle special cases:
   - `list[dict]` - structure defines item schema
   - Empty lines - skip
   - Inconsistent indentation - log warning, best effort

### Step 5: Update ALL Tests (2 hours)
The tests expect simple format. Update them for rich format:

1. Find all tests in `tests/test_registry/test_metadata_extractor.py`
2. Update expected outputs from:
   ```python
   assert metadata["outputs"] == ["content", "error"]
   ```
   To:
   ```python
   assert metadata["outputs"] == [
       {"key": "content", "type": "any", "description": ""},
       {"key": "error", "type": "any", "description": ""}
   ]
   ```

3. Add new tests for:
   - Enhanced format with types
   - Structure parsing
   - Comment extraction
   - Format detection
   - Mixed formats

### Step 6: Integration Testing (1 hour)
1. Test with real nodes:
   - `src/pflow/nodes/file/read_file.py` (simple)
   - Create a test node with complex structure

2. Run registry scanner:
   ```bash
   python -m src.pflow.registry.scanner src/pflow/nodes
   ```

3. Verify metadata files are created correctly

### Step 7: Update Logging (30 min)
Add structured logging with phases:
```python
logger.debug("Parsing interface", extra={"phase": "format_detection"})
logger.debug("Extracting types", extra={"phase": "type_extraction"})
logger.debug("Parsing structure", extra={"phase": "structure_parsing"})
```

### Step 8: Quality Checks (30 min)
1. Run all tests: `pytest tests/test_registry/test_metadata_extractor.py -xvs`
2. Run linting: `make check`
3. Check performance - parsing shouldn't slow startup

### Step 9: Manual Verification
1. Create a test node with complex structure
2. Run the metadata extractor on it
3. Verify the output JSON has correct structure
4. Check that simple nodes still work

## Code Snippets to Get You Started

### Format Detection
```python
def _detect_format(self, line: str) -> str:
    """Detect if line uses simple or enhanced format."""
    # Remove the "Reads:", "Writes:", etc. prefix
    content = line.split(":", 1)[1].strip() if ":" in line else ""

    # Check for type annotations
    if 'shared["' in content and ']: ' in content:
        return "enhanced"
    elif any(param + ": " in content for param in self._extract_param_names(content)):
        return "enhanced"
    return "simple"
```

### Structure Parsing Start
```python
def _get_indentation(self, line: str) -> int:
    """Get indentation level of a line."""
    return len(line) - len(line.lstrip())

def _parse_field_line(self, line: str) -> Tuple[str, str, str]:
    """Parse '- field: type  # description' format."""
    # Remove leading "- "
    line = line.strip().lstrip("-").strip()

    # Split by comment
    if "#" in line:
        main, desc = line.split("#", 1)
        desc = desc.strip()
    else:
        main, desc = line, ""

    # Split by colon
    if ":" in main:
        field, type_str = main.split(":", 1)
        return field.strip(), type_str.strip(), desc

    return main.strip(), "any", desc
```

## Testing Strategy

### Quick Test for Comment Bug
```python
def test_multiitem_comment_parsing():
    docstring = '''
    Interface:
    - Writes: shared["a"]: str, shared["b"]: str  # only b gets this
    '''
    metadata = extractor.extract_metadata(TestNode, docstring)
    assert metadata["outputs"][0]["description"] == ""  # a has no comment
    assert metadata["outputs"][1]["description"] == "only b gets this"
```

### Quick Test for Structure
```python
def test_structure_parsing():
    docstring = '''
    Interface:
    - Writes: shared["data"]: dict
        - id: int  # User ID
        - name: str  # Username
    '''
    metadata = extractor.extract_metadata(TestNode, docstring)
    assert metadata["outputs"][0]["structure"]["id"]["type"] == "int"
    assert metadata["outputs"][0]["structure"]["id"]["description"] == "User ID"
```

## Gotchas to Remember

1. **The handoff says `_extract_list_section()` but it doesn't exist** - Work with existing methods
2. **"Writes" means "outputs"** - Don't get confused by terminology
3. **All components get types** - Reads, Writes, AND Params
4. **Graceful degradation** - Never crash on bad input
5. **Rich format always** - Even simple input returns rich format
6. **Test the regex carefully** - One wrong character breaks everything

## Success Markers

You'll know you're done when:
1. All existing tests pass (updated for rich format)
2. New tests for enhanced features pass
3. Real nodes parse correctly (both simple and enhanced)
4. No performance regression
5. Context builder can display the type information

## Emergency Debugging

If things go wrong:
1. Add print statements in parsing methods
2. Test with minimal examples first
3. Check regex patterns with regex101.com
4. Look at Task 7's implementation for patterns
5. Remember: graceful degradation over perfect parsing

Good luck! You're implementing a critical piece that enables the entire planning system.
