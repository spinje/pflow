# Patterns Discovered

## Pattern: Format Detection with Graceful Enhancement
**Context**: When you need to support both old and new input formats in a parser
**Solution**:
```python
def _detect_format(self, content: str, component_type: str) -> bool:
    """Detect format based on presence of type indicators."""
    if component_type in ("inputs", "outputs"):
        # Check for new format indicator (colon after key)
        if re.search(r'shared\["[^"]+"\]\s*:', content):
            return True  # Enhanced format
    # Default to simple format
    return False

def _extract_component(self, content: str, component_type: str):
    """Route to appropriate parser based on format."""
    if self._detect_format(content, component_type):
        return self._extract_enhanced_format(content)
    else:
        return self._extract_simple_format(content)
```
**Why it works**: Allows gradual migration without breaking existing users
**When to use**: Adding optional enhancements to existing parsers
**Example**: See `_detect_interface_format()` in metadata_extractor.py

## Pattern: Split-First Comment Parsing
**Context**: When parsing lines with multiple items that may have individual or shared comments
**Solution**:
```python
# First check for shared comment at end of line
shared_comment = ""
comment_match = re.search(r'#\s*([^\n]+)$', content)
if comment_match and ',' in content[:comment_match.start()]:
    shared_comment = comment_match.group(1).strip()
    content = content[:comment_match.start()].strip()

# Then split and parse each item
segments = [seg.strip() for seg in content.split(',')]
for segment in segments:
    # Parse with individual comment check
    match = re.match(r'pattern(?:\s*#\s*(.*))?', segment)
    description = match.group(1) if match.group(1) else shared_comment
```
**Why it works**: Correctly handles both individual and shared comments
**When to use**: Parsing comma-separated lists with optional comments

## Pattern: Indentation-Based Structure Parsing
**Context**: When you need to parse nested structures defined by indentation (like YAML)
**Solution**:
```python
def _parse_structure(self, lines: list[str], start_idx: int) -> tuple[dict, int]:
    structure = {}
    base_indent = None
    idx = start_idx

    while idx < len(lines):
        line = lines[idx]
        current_indent = len(line) - len(line.lstrip())

        if base_indent is None:
            base_indent = current_indent

        if current_indent < base_indent:
            break  # End of this structure level

        if current_indent == base_indent:
            # Parse field at this level
            field_info = parse_field(line)
            # Check for nested structure
            if has_nested_type(field_info) and idx + 1 < len(lines):
                if get_indent(lines[idx + 1]) > current_indent:
                    nested, new_idx = _parse_structure(lines, idx + 1)
                    field_info["structure"] = nested
                    idx = new_idx - 1

        idx += 1

    return structure, idx
```
**Why it works**: Natural recursive structure matches indented data
**When to use**: Parsing hierarchical data with consistent indentation
