# Node Metadata Extraction Infrastructure

## Executive Summary

**Chosen Approach**: Structured docstring parsing with hybrid extraction
**Primary Format**: Interface sections in Python docstrings
**Parsing Strategy**: Custom regex patterns with support for both simple and enhanced formats
**Purpose**: Enable metadata-driven planner selection from static node library

This document defines the infrastructure for extracting structured metadata from developer-written pflow nodes to support the planner's discovery and validation capabilities. The system now supports an enhanced format with type annotations and semantic descriptions while maintaining backward compatibility.

---

## Why This Approach

### Integration with Static Node Architecture

**Established Reality**: Developers write static, reusable node classes
**Our Solution**: Extract rich metadata to enable intelligent planner selection
**Key Benefit**: Bridge between human-written nodes and AI-driven flow planning

### Technical Benefits

1. **Zero Runtime Overhead** - Pre-extracted JSON for fast planner access
2. **Source of Truth** - Metadata extracted from actual node code
3. **Framework Integration** - Works with established pocketflow patterns
4. **Registry Compatible** - Integrates with versioning and discovery systems
5. **Planner Ready** - Enables metadata-driven LLM selection and validation
6. **Type Aware** - Enhanced format provides type information for better planning

---

## Integration with pflow Architecture

This metadata extraction infrastructure directly supports several core pflow systems:

### Planner Discovery Integration
>
> **See**: [Planner Responsibility Spec](../features/planner.md#node-discovery)

The extraction process feeds the planner's metadata-driven selection:

- Builds registry of available nodes with natural language descriptions
- Provides interface compatibility data with type information for validation
- Enables LLM context generation for intelligent selection
- Supports both natural language and CLI pipe syntax validation
- Type annotations enable better proxy mapping generation

### Registry Integration
>
> **See**: [Node Discovery & Versioning](../core-concepts/registry.md#registry-management)

Metadata extraction occurs during node installation:

- `pflow registry install node.py` triggers automatic metadata extraction
- Version changes invalidate cached metadata for re-extraction
- Registry commands use pre-extracted metadata for rich CLI experience
- Supports namespace and versioning requirements
- Enhanced format metadata stored in same JSON structure

### Shared Store Compatibility
>
> **See**: [Shared Store Pattern](../core-concepts/shared-store.md#natural-interfaces)

Extracted interface data preserves natural shared store access patterns:

- Documents `shared["key"]` usage from actual node code
- Type information enables proxy mapping generation for complex flows
- Validates interface consistency across flow components
- Maintains natural interface simplicity for node writers
- Exclusive params pattern reduces redundancy

---

## Docstring Format Standards

The metadata extractor supports both the simple format (for backward compatibility) and the enhanced format (recommended for new nodes).

### Enhanced Format (Recommended)

All new nodes should use the enhanced format with type annotations and descriptions:

```python
class ReadFileNode(Node):
    """
    Read content from a file and add line numbers for display.

    This node reads a text file and formats it with 1-indexed line numbers,
    following the Tutorial-Cursor pattern for file display.

    Interface:
    - Reads: shared["file_path"]: str  # Path to the file to read
    - Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
    - Writes: shared["content"]: str  # File contents with line numbers
    - Writes: shared["error"]: str  # Error message if operation failed
    - Actions: default (success), error (failure)

    Security Note: This node can read ANY accessible file on the system.
    Do not expose to untrusted input without proper validation.
    """

    def prep(self, shared):
        # Read from params (template resolution handles shared store wiring)
        file_path = self.params.get("file_path")
        encoding = self.params.get("encoding", "utf-8")
        return (file_path, encoding)

    def exec(self, prep_res):
        file_path, encoding = prep_res
        with open(file_path, encoding=encoding) as f:
            content = f.read()
        return content

    def post(self, shared, prep_res, exec_res):
        shared["content"] = exec_res
        return "default"
```

### Simple Format (Legacy/Backward Compatible)

The original format without type annotations is still supported:

```python
Interface:
- Reads: shared["file_path"], shared["encoding"]
- Writes: shared["content"], shared["error"]
- Params: file_path, encoding (as fallbacks)
- Actions: default (success), error (failure)
```

### Key Format Characteristics

1. **Multi-line support**: Each Interface component can be on its own line
2. **Type annotations**: Use `: type` after shared keys or param names
3. **Semantic descriptions**: Use `# comment` for descriptions
4. **Exclusive params pattern**: Only list params NOT already in Reads
5. **Action descriptions**: Use parentheses to describe when actions trigger

### Interface Components

- **Reads**: `shared["key"]: type  # description` - inputs from shared store
- **Writes**: `shared["key"]: type  # description` - outputs to shared store
- **Params**: `param: type  # description` - configuration parameters (exclusive)
- **Actions**: `action_name (description)` - transition strings

For complete format specification, see [Enhanced Interface Format](../reference/enhanced-interface-format.md).

---

## Extraction Implementation

### Core Architecture

The metadata extractor has been enhanced to support both simple and enhanced formats with automatic detection:

```python
import re
import inspect
from typing import Dict, Any, List
import pocketflow

class PflowMetadataExtractor:
    """Extract metadata from pflow node docstrings.

    Supports both simple and enhanced formats with automatic detection.
    Enhanced format includes type annotations and semantic descriptions.
    """

    # Regex patterns for Interface parsing
    INTERFACE_PATTERN = r"Interface:\s*\n((?:[ \t]*-[^\n]+(?:\n(?![ \t]*-)[ \t]+[^\n]+)*\n?)*)"
    INTERFACE_ITEM_PATTERN = r"-\s*(\w+):\s*([^\n]*(?:\n(?![ \t]*-)[ \t]+[^\n]+)*)"
    SHARED_KEY_PATTERN = r'shared\["([^"]+)"\]'
    ACTIONS_PATTERN = r"(\w+)(?:\s*\([^)]+\))?"

    def extract_metadata(self, node_class: type) -> Dict[str, Any]:
        """Extract metadata from a node class.

        Returns rich format with type information when available.
        Falls back gracefully for simple format nodes.
        """
        # Validate it's a node
        if not issubclass(node_class, pocketflow.BaseNode):
            raise ValueError(f"{node_class.__name__} is not a pflow node")

        docstring = inspect.getdoc(node_class) or ""

        # Extract components
        description = self._extract_description(docstring)
        interface_data = self._parse_interface_section(docstring)

        return {
            'description': description,
            'inputs': interface_data.get('inputs', []),
            'outputs': interface_data.get('outputs', []),
            'params': interface_data.get('params', []),
            'actions': interface_data.get('actions', [])
        }

    def _detect_interface_format(self, content: str, component_type: str) -> bool:
        """Detect if content uses enhanced format with type annotations."""
        if component_type in ("inputs", "outputs"):
            # Check for colon after shared["key"]
            if re.search(r'shared\["[^"]+"\]\s*:', content):
                return True
        elif component_type == "params":
            # Check for colon after param name (not within parentheses)
            content_no_parens = re.sub(r"\([^)]+\)", "", content)
            if re.search(r"\b\w+\s*:\s*\w+", content_no_parens):
                return True
        return False

    def _extract_enhanced_shared_keys(self, content: str) -> List[Dict[str, Any]]:
        """Extract shared store keys with type annotations and descriptions.

        Uses comma-aware splitting to preserve commas in descriptions.
        """
        results = []

        # Check for shared comment at end of line
        shared_comment = ""
        comment_match = re.search(r"#\s*([^\n]+)$", content)
        if comment_match:
            before_comment = content[:comment_match.start()].strip()
            if "," in before_comment:
                shared_comment = comment_match.group(1).strip()
                content = before_comment

        # Split by comma only when followed by shared["..."] pattern
        # This preserves commas inside descriptions
        segments = re.split(r',\s*(?=shared\[)', content)

        for segment in segments:
            if not segment.strip():
                continue

            # Pattern: shared["key"]: type  # description
            item_pattern = r'shared\["([^"]+)"\]\s*:\s*([^\s#]+)(?:\s*#\s*(.*))?'
            match = re.match(item_pattern, segment.strip())

            if match:
                key = match.group(1)
                type_str = match.group(2).strip()
                individual_comment = match.group(3).strip() if match.group(3) else ""
                description = individual_comment if individual_comment else shared_comment

                result = {"key": key, "type": type_str, "description": description}

                # Mark complex types for structure parsing (future enhancement)
                if type_str in ("dict", "list", "list[dict]"):
                    result["_has_structure"] = True

                results.append(result)

        return results

    def _extract_enhanced_params(self, content: str) -> List[Dict[str, Any]]:
        """Extract parameters with type annotations and descriptions.

        Uses specialized regex to handle commas in descriptions.
        """
        results = []

        # Split params properly, preserving commas in descriptions
        param_segments = re.split(r',\s*(?=\w+\s*:)', content)

        for segment in param_segments:
            segment = segment.strip()
            if not segment:
                continue

            # Pattern: param_name: type  # description
            param_pattern = r"(\w+)\s*:\s*([^#\n]+)(?:\s*#\s*(.*))?$"
            match = re.match(param_pattern, segment)

            if match:
                key = match.group(1)
                type_str = match.group(2).strip()
                description = match.group(3).strip() if match.group(3) else ""

                results.append({"key": key, "type": type_str, "description": description})

        return results

    def _process_interface_item(self, item_type: str, item_content: str, result: dict):
        """Process a single interface item with multi-line support.

        Critical fix: Uses extend() instead of replace to support multiple
        lines of the same type (e.g., multiple Reads: lines).
        """
        type_map = {"reads": "inputs", "writes": "outputs", "params": "params"}
        result_key = type_map[item_type]

        # Extract component based on format
        is_enhanced = self._detect_interface_format(item_content, result_key)

        if result_key in ("inputs", "outputs"):
            if is_enhanced:
                new_items = self._extract_enhanced_shared_keys(item_content)
            else:
                # Simple format - convert to rich format
                keys = self._extract_shared_keys(item_content)
                new_items = [{"key": k, "type": "any", "description": ""} for k in keys]
        else:  # params
            if is_enhanced:
                new_items = self._extract_enhanced_params(item_content)
            else:
                # Simple format - convert to rich format
                params = self._extract_params(item_content)
                new_items = [{"key": p, "type": "any", "description": ""} for p in params]

        # Multi-line support: extend instead of replace
        if isinstance(result[result_key], list) and isinstance(new_items, list):
            result[result_key].extend(new_items)
        else:
            result[result_key] = new_items
```

### Parser Implementation Details

#### Format Detection Logic

The parser automatically detects which format is being used:

1. **For Reads/Writes**: Looks for `:` after `shared["key"]`
2. **For Params**: Looks for `:` after parameter name (ignoring colons in parentheses)

#### Multi-line Support Fix

A critical bug was fixed in subtask 14.3 to support multiple lines of the same type:

```python
# OLD (broken) - replaced data:
result["inputs"] = self._extract_interface_component(...)

# NEW (fixed) - extends data:
result["inputs"].extend(self._extract_interface_component(...))
```

This allows nodes to have multiple `Reads:` or `Writes:` lines that combine properly.

#### Comma-aware Splitting

Another critical fix handles commas in descriptions:

```python
# OLD (broken on commas in descriptions):
content.split(",")

# NEW (preserves commas in descriptions):
re.split(r',\s*(?=shared\[)', content)  # For shared keys
re.split(r',\s*(?=\w+\s*:)', content)   # For params
```

This regex uses positive lookahead to split only on commas followed by the expected pattern.

---

## The Exclusive Params Pattern

A key feature of the enhanced format is the exclusive params pattern, which eliminates redundancy:

### Pattern Description

Parameters that are already listed in `Reads` are automatically available as fallbacks and should NOT be repeated in `Params`.

### Implementation

```python
def _apply_exclusive_params_pattern(self, result: dict) -> dict:
    """Apply exclusive params pattern to filter redundant parameters."""
    # Get all input keys
    input_keys = set()
    for inp in result.get("inputs", []):
        if isinstance(inp, dict):
            input_keys.add(inp["key"])
        else:
            input_keys.add(inp)

    # Filter params to only exclusive ones
    exclusive_params = []
    for param in result.get("params", []):
        if isinstance(param, dict):
            if param["key"] not in input_keys:
                exclusive_params.append(param)
        else:
            if param not in input_keys:
                exclusive_params.append(param)

    result["params"] = exclusive_params
    return result
```

### Example

```python
# Before exclusive params pattern:
Interface:
- Reads: shared["file_path"]: str  # Path to file
- Params: file_path: str, encoding: str, append: bool

# After exclusive params pattern:
Interface:
- Reads: shared["file_path"]: str  # Path to file
- Params: encoding: str, append: bool  # file_path removed as redundant
```

---

## Known Limitations

The current parser has some MVP-acceptable limitations:

### 1. Empty Components Bug
Empty lines like `- Reads:` with no content can cause parsing misalignment.

### 2. Long Line Handling
Very long lines (>500 characters) may not parse completely due to regex limitations.

### 3. Malformed Enhanced Format
Invalid syntax may create unexpected nested structures in the output.

### 4. Structure Parsing Not Implemented
While the parser recognizes complex types (`dict`, `list`) and sets a `_has_structure` flag, it does not yet parse the indented structure documentation:

```python
# Recognized but not parsed:
- Writes: shared["data"]: dict  # User data
    - name: str  # User name
    - age: int  # User age
```

### 5. Mixed Format Limitations
Mixing simple and enhanced format in the same Interface section may produce inconsistent results.

These limitations are documented and acceptable for the MVP as they don't affect normal usage patterns.

---

## Registry Integration

### Metadata Storage Schema

The enhanced format data is stored in the same JSON structure, now with type information:

```json
{
  "node": {
    "id": "read-file",
    "namespace": "core",
    "version": "1.0.0",
    "python_file": "nodes/file/read_file.py",
    "class_name": "ReadFileNode"
  },
  "interface": {
    "inputs": [
      {
        "key": "file_path",
        "type": "str",
        "description": "Path to the file to read"
      },
      {
        "key": "encoding",
        "type": "str",
        "description": "File encoding (optional, default: utf-8)"
      }
    ],
    "outputs": [
      {
        "key": "content",
        "type": "str",
        "description": "File contents with line numbers"
      },
      {
        "key": "error",
        "type": "str",
        "description": "Error message if operation failed"
      }
    ],
    "params": [],  // Empty due to exclusive params pattern
    "actions": ["default", "error"]
  },
  "documentation": {
    "description": "Read content from a file and add line numbers for display"
  }
}
```

---

## Integration with Context Builder

The context builder has been updated to display the enhanced metadata:

### Context Builder Flow

1. **Metadata Extraction**: Parser extracts types and descriptions
2. **Registry Storage**: Enhanced metadata stored in JSON
3. **Context Building**: Formats metadata for planner consumption
4. **Type Display**: Shows types inline with keys
5. **Description Display**: Includes semantic descriptions
6. **Structure Hints**: For complex types, shows hierarchical structure

### Example Context Output

```markdown
### read-file
Read content from a file and add line numbers for display

**Inputs**: `file_path: str` - Path to the file to read, `encoding: str` - File encoding (optional, default: utf-8)
**Outputs**: `content: str` - File contents with line numbers, `error: str` - Error message if operation failed
**Actions**: default (success), error (failure)
```

### Exclusive Params in Context

The context builder also implements the exclusive params pattern:

```python
# Build input keys set
input_keys = set()
for inp in inputs:
    if isinstance(inp, dict):
        input_keys.add(inp["key"])
    else:
        input_keys.add(inp)

# Filter to exclusive params only
exclusive_params = []
for param in params:
    if isinstance(param, dict):
        key = param["key"]
        if key not in input_keys:
            exclusive_params.append(param)
```

This ensures the planner only sees truly exclusive parameters, reducing confusion.

---

## Testing Approach

The enhanced metadata extraction system has comprehensive test coverage:

### Test Categories

1. **Format Detection Tests**: Verify correct format identification
2. **Enhanced Parsing Tests**: Test type and description extraction
3. **Multi-line Tests**: Verify multiple lines combine correctly
4. **Comma Handling Tests**: Test descriptions with complex punctuation
5. **Backward Compatibility Tests**: Ensure simple format still works
6. **Edge Case Tests**: Malformed input, empty components, long lines
7. **Integration Tests**: Full flow from docstring to context output

### Example Test Cases

```python
def test_enhanced_format_comma_handling(self):
    """Test that commas in descriptions are preserved."""
    class CommaNode(pocketflow.Node):
        """
        Interface:
        - Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
        """

    result = self.extractor.extract_metadata(CommaNode)
    assert result["inputs"][0]["description"] == "File encoding (optional, default: utf-8)"

def test_exclusive_params_pattern(self):
    """Test that params already in Reads are filtered out."""
    class ExclusiveNode(pocketflow.Node):
        """
        Interface:
        - Reads: shared["input"]: str
        - Params: input: str, extra: bool  # input should be filtered
        """

    result = self.extractor.extract_metadata(ExclusiveNode)
    param_keys = [p["key"] for p in result["params"]]
    assert "input" not in param_keys  # Filtered out
    assert "extra" in param_keys      # Kept as exclusive
```

---

## Migration Guide Summary

For developers updating nodes to the enhanced format:

1. **Add type annotations**: `shared["key"]` → `shared["key"]: str`
2. **Add descriptions**: Use `# comment` after the type
3. **Use multi-line format**: Each item on its own line for clarity
4. **Apply exclusive params**: Remove params that duplicate Reads
5. **Test extraction**: Verify metadata extracts correctly

For the complete migration guide, see [Interface Migration Guide](../reference/interface-migration-guide.md).

---

## Future Enhancements

The following features are planned for future versions:

1. **Full Structure Parsing**: Parse indented structure documentation for complex types
2. **Type Validation**: Validate that specified types are valid Python types
3. **Enum Support**: Handle enumerated values like `Literal['fast', 'slow']`
4. **Advanced Type Syntax**: Support for `Optional[str]`, `Union[str, int]`, etc.
5. **Performance Optimization**: Cached parsing for large registries

---

## Conclusion

The enhanced metadata extraction infrastructure provides rich type information while maintaining perfect backward compatibility. This enables:

- **Better Planning**: Type-aware workflow generation with valid proxy mappings
- **Clearer Documentation**: Semantic descriptions for all interface components
- **Reduced Redundancy**: Exclusive params pattern eliminates duplication
- **Future Ready**: Foundation for advanced type features

The infrastructure continues to enable intelligent flow planning while preserving the simplicity and reliability of pflow's curated node ecosystem.

## See Also

- **Specification**: [Enhanced Interface Format](../reference/enhanced-interface-format.md) - Complete format specification
- **Migration**: [Interface Migration Guide](../reference/interface-migration-guide.md) - Step-by-step migration guide
- **Architecture**: [JSON Schemas](../core-concepts/schemas.md) - Node metadata schema definitions
- **Architecture**: [Registry System](../core-concepts/registry.md) - How metadata integrates with node discovery
- **Patterns**: [Simple Nodes](../features/simple-nodes.md) - Node design patterns that guide metadata extraction
- **Components**: [Planner](../features/planner.md) - How planner uses extracted metadata for node selection
- **Related Features**: [Shared Store](../core-concepts/shared-store.md) - Natural interface patterns documented in metadata
- **Future Features**: [LLM Node Generation](../future-version/llm-node-gen.md) - Future LLM-assisted development using metadata
