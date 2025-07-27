# Task 19 Node IR Implementation - Brain Dump

## What's Been Done

### Scanner Changes (COMPLETE)
- Modified `src/pflow/registry/scanner.py`:
  - Added singleton MetadataExtractor with lazy loading to avoid circular imports
  - Updated `extract_metadata()` to parse interface at scan-time
  - Stores full parsed interface in metadata["interface"] field
  - Fail-fast approach with clear error messages

### Context Builder Changes (90% COMPLETE)
- Modified `src/pflow/planning/context_builder.py`:
  - Removed imports: importlib, types, PflowMetadataExtractor
  - Updated `_process_nodes()` to use pre-parsed interface data from registry
  - Now requires all nodes to have interface field (no fallback)
  - Maintains exact output format for planner compatibility

### Test Updates
- Scanner tests: All 34 passing with mocks
- Context builder tests: Need to update 3 tests that expect old behavior:
  1. `test_process_nodes_handles_import_failures` - no longer relevant
  2. `test_process_nodes_handles_attribute_error` - no longer relevant
  3. `test_process_nodes_module_caching` - no longer relevant

## Key Files Modified
- `src/pflow/registry/scanner.py` - Added interface parsing
- `src/pflow/planning/context_builder.py` - Removed dynamic imports
- `tests/test_registry/test_scanner.py` - Updated with mocks

## Next Steps
1. Fix remaining context builder tests
2. Update template validator to use registry
3. Update compiler to pass registry to validator
4. Run full test suite

## Important Notes
- Registry now contains interface field with full metadata
- No backward compatibility needed (MVP, no users)
- All parsing happens at scan-time now
- Context builder ~100 lines simpler

## Critical Implementation Details

### MetadataExtractor Output Format
- ALWAYS returns rich format: `[{"key": "x", "type": "str", "description": "..."}]`
- Never returns simple strings in output
- Handle both formats in validator even though extractor normalizes

### Circular Import Solution
```python
# In scanner.py
_metadata_extractor = None

def get_metadata_extractor():
    global _metadata_extractor
    if _metadata_extractor is None:
        from pflow.registry.metadata_extractor import PflowMetadataExtractor
        _metadata_extractor = PflowMetadataExtractor()
    return _metadata_extractor
```

### Context Builder Key Change
```python
# OLD: Dynamic imports and parsing
metadata = extractor.extract_metadata(node_class)

# NEW: Just use pre-parsed data
interface = node_info.get("interface")
if not interface:
    raise ValueError(f"Node '{node_type}' missing interface data")
```

### Files That Still Need Changes
1. `src/pflow/runtime/template_validator.py` - Add registry parameter, implement path validation
2. `src/pflow/runtime/compiler.py` - Pass registry to validator (line ~511)
3. Tests that need updates for new signatures
