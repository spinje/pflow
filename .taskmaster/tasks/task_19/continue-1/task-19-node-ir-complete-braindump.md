# Task 19 Node IR Implementation - Complete Brain Dump

## CRITICAL: Implementation is 95% Complete!

### What This Task Is About
Task 19 is fixing a fundamental flaw in pflow's template validation. The validator was using hardcoded heuristics (a "magic list" of common variable names like "summary", "content", etc.) to guess which variables come from the shared store. This caused false validation failures when nodes wrote variables not in the magic list (e.g., `$api_config`).

The solution: Create a proper "Node IR" (Intermediate Representation) by moving interface parsing from runtime to scan-time, storing fully parsed metadata in the registry so the validator can check template variables against what nodes ACTUALLY write.

## What Has Been Done (95% Complete)

### 1. Scanner Enhancement ✅ COMPLETE
**File**: `src/pflow/registry/scanner.py`

Added singleton MetadataExtractor pattern and updated `extract_metadata()`:
```python
_metadata_extractor = None

def get_metadata_extractor():
    """Get or create singleton MetadataExtractor instance."""
    global _metadata_extractor
    if _metadata_extractor is None:
        from pflow.registry.metadata_extractor import PflowMetadataExtractor
        _metadata_extractor = PflowMetadataExtractor()
    return _metadata_extractor
```

The scanner now:
- Parses Interface docstrings at scan-time using MetadataExtractor
- Stores complete parsed metadata in the "interface" field
- Fails fast with clear error messages if parsing fails
- Handles the circular import issue with lazy loading

**Verified**: Registry now contains interface data with full parsed metadata

### 2. Context Builder Simplification ✅ COMPLETE
**File**: `src/pflow/planning/context_builder.py`

Removed ~75 lines of code:
- Removed imports: `importlib`, `types`, `PflowMetadataExtractor`
- Updated `_process_nodes()` to use pre-parsed interface data from registry
- Now requires all nodes to have interface field (fail fast approach)
- Maintains exact output format for planner compatibility

**Tests Fixed**: All 33 context builder tests passing

### 3. Template Validator Rewrite ✅ COMPLETE
**File**: `src/pflow/runtime/template_validator.py`

Complete rewrite of validation logic:
- Added Registry import and required parameter
- Implemented `_extract_node_outputs()` - extracts outputs from registry interface data
- Implemented `_validate_template_path()` - full path traversal validation (e.g., `$api_config.endpoint.url`)
- Removed `_categorize_templates()` heuristic method
- Handles both simple and rich output formats from MetadataExtractor

Key implementation details:
- Checks initial_params before node outputs (higher priority)
- Validates complete nested paths through structures
- Fails if trying to traverse non-dict types

### 4. Compiler Integration ✅ COMPLETE
**File**: `src/pflow/runtime/compiler.py`

One line change at line 511:
```python
errors = TemplateValidator.validate_workflow_templates(ir_dict, initial_params, registry)
```

### 5. Test Updates ✅ COMPLETE
Fixed ALL failing tests (611 tests now passing):

**Template Validator Tests** (`tests/test_runtime/test_template_validator.py`):
- Created `create_mock_registry()` helper with proper interface data
- Updated all test calls to include registry parameter
- Fixed error message assertions (e.g., "Missing required parameter: --url" → "Template variable $url has no valid source")

**Template Integration Tests** (`tests/test_runtime/test_template_integration.py`):
- Updated all mock_registry fixtures to include interface data and `get_nodes_metadata()` method
- Fixed tests expecting old heuristic behavior (e.g., "$summary" was magically allowed before)
- Updated multi_node_registry and real_registry fixtures

**Context Builder Performance Tests** (`tests/test_integration/test_context_builder_performance.py`):
- Added interface field to registry metadata in performance tests

## What's Left to Do (5%)

### 1. Clean Up Old Heuristic Code ⏳
**File**: `src/pflow/runtime/template_validator.py`

The old heuristic code is already effectively disabled but still present in the file:
- Lines 106-118: The `common_outputs` magic list
- The old categorization logic that's no longer called

This cleanup is low priority since the code is already bypassed, but should be done for cleanliness.

### 2. Update Progress Log and Documentation
- Final update to `.taskmaster/tasks/task_19/implementation/progress-log.md`
- Update any affected documentation about validation behavior

## Critical Implementation Details

### 1. MetadataExtractor Output Format
**ALWAYS returns rich format** after normalization:
```python
[{"key": "output1", "type": "str", "description": "..."}, ...]
```
Never returns simple strings in the output, only in the input docstrings.

### 2. Registry Format Change
Old format:
```json
{
  "node-type": {
    "module": "...",
    "class_name": "...",
    "docstring": "..."
  }
}
```

New format:
```json
{
  "node-type": {
    "module": "...",
    "class_name": "...",
    "docstring": "...",
    "interface": {
      "description": "...",
      "inputs": [...],
      "outputs": [...],
      "params": [...],
      "actions": [...]
    }
  }
}
```

### 3. Path Traversal Implementation
The validator can now validate complex paths like `$api_config.endpoint.url`:
1. Check if "api_config" exists in initial_params or node_outputs
2. If from node_outputs, traverse the structure to verify path exists
3. If type is primitive (str, int), path traversal fails

### 4. Test Pattern for Mock Registries
All tests need this pattern:
```python
registry.load.return_value = {
    "node-type": {
        "module": "...",
        "class_name": "...",
        "interface": {
            "inputs": [...],
            "outputs": [...],
            "params": [...],
            "actions": [...]
        }
    }
}

def get_nodes_metadata(node_types):
    result = {}
    for node_type in node_types:
        if node_type in registry.load.return_value:
            result[node_type] = registry.load.return_value[node_type]
    return result

registry.get_nodes_metadata = Mock(side_effect=get_nodes_metadata)
```

## Key Files Modified

1. `src/pflow/registry/scanner.py` - Added interface parsing
2. `src/pflow/planning/context_builder.py` - Removed dynamic imports
3. `src/pflow/runtime/template_validator.py` - Complete rewrite
4. `src/pflow/runtime/compiler.py` - One line change
5. `tests/test_runtime/test_template_validator.py` - Updated all tests
6. `tests/test_runtime/test_template_integration.py` - Fixed fixtures
7. `tests/test_integration/test_context_builder_performance.py` - Added interface field

## Success Metrics Achieved

✅ Scanner extracts and stores interface in registry
✅ Context builder uses registry without imports (~75 lines removed)
✅ Validator uses actual node outputs (no more heuristics)
✅ Full path validation works (e.g., $config.api.url)
✅ All 611 tests pass
✅ Performance acceptable
✅ Error messages show clear validation failures

## Next Agent Instructions

1. Read this brain dump first
2. Check current test status: `make test`
3. If all tests pass (they should), proceed to cleanup:
   - Remove the `common_outputs` magic list from template_validator.py
   - Remove any other heuristic code that's no longer called
4. Update the progress log with final completion
5. Consider documenting the breaking change for users (though spec says no users yet)

## Important Context

- This is an MVP with no users - no backward compatibility needed
- The registry format change is breaking but intentional
- All nodes MUST have interface field now (no fallbacks)
- The template system from Task 18 established patterns we followed
- PocketFlow framework understanding was crucial (Node lifecycle, Flow orchestration)

## Commands to Verify Success

```bash
# Check all tests pass
make test

# Check registry has interface data
cat ~/.pflow/registry.json | jq '."read-file".interface'

# Run the populate script if needed
uv run python scripts/populate_registry.py
```

The implementation is essentially complete and working correctly. The validator now uses actual node outputs instead of guessing, which fixes the core problem that was frustrating users.
