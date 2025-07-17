# Parser Issue: Multiple Lines of Same Type

## Issue Description

The current metadata extractor in `src/pflow/registry/metadata_extractor.py` cannot handle multiple lines of the same component type in the Interface section.

### Current Behavior
When an Interface has multiple lines like:
```
- Reads: shared["file_path"]: str  # Path to file
- Reads: shared["encoding"]: str  # Encoding
```

Only the LAST line is preserved. The parser replaces instead of appending.

### Expected Behavior
All lines should be combined into a single list of inputs.

### Root Cause
In `_extract_interface` method (line 178), each new "Reads:" line REPLACES the previous:
```python
if item_type == "reads":
    result["inputs"] = self._extract_interface_component(item_content, "inputs")
```

### Potential Fix
The parser should extend/append instead of replace:
```python
if item_type == "reads":
    new_inputs = self._extract_interface_component(item_content, "inputs")
    if isinstance(result["inputs"], list) and isinstance(new_inputs, list):
        result["inputs"].extend(new_inputs)
    else:
        result["inputs"] = new_inputs
```

### Workaround for Now
Put all items on a single line:
```
- Reads: shared["file_path"]: str  # Path, shared["encoding"]: str  # Encoding
```

But this reduces readability significantly.

## Decision Needed

Should we:
1. Fix the parser to handle multiple lines (recommended)
2. Update all nodes to use single-line format
3. Document this as a known limitation

This affects the entire task 14.3 implementation.
