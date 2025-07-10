# Refined Specification for Subtask 16.1

## Clear Objective
Create a context builder that transforms node registry metadata into LLM-optimized markdown documentation, enabling the workflow planner to discover and compose nodes with 95% success rate.

## Context from Knowledge Base
- Building on: Registry system (Task 5), Metadata extraction (Task 7), Shared store parameter pattern
- Avoiding: Parameter redundancy, test node pollution, import failures crashing the system
- Following: Phased implementation, defensive error handling, component-specific logging
- **Cookbook patterns to apply**: Not applicable (this is not a PocketFlow node implementation)

## Technical Specification

### Function Signature
```python
def build_context(registry_metadata: dict[str, dict[str, Any]]) -> str:
    """Build LLM-friendly context from registry metadata.

    Args:
        registry_metadata: Dict mapping node types to metadata dicts
                          (as returned by Registry.load())

    Returns:
        Formatted markdown string describing available nodes
    """
```

### Inputs
- `registry_metadata`: Pre-loaded dict from Registry.load() containing:
  - Keys: Node type strings (e.g., "read-file", "write-file")
  - Values: Metadata dicts with fields:
    - `module`: Python module path
    - `class_name`: Node class name
    - `docstring`: Full unparsed docstring
    - `file_path`: Source file path
    - Additional metadata if available

### Outputs
- Markdown-formatted string with structure:
  ```markdown
  ## Category Name

  ### node-type
  Brief description from metadata.

  **Inputs**: `key1`, `key2` (optional)
  **Outputs**: `output1` (success), `error` (failure)
  **Parameters**: `config_param1`, `config_param2`
  ```

### Implementation Constraints
- Must use: `import_node_class()` from runtime.compiler for dynamic imports
- Must use: `PflowMetadataExtractor` for extracting Interface information
- Must avoid: Direct imports of node classes
- Must maintain: Exclusive parameter filtering (params not in inputs)

## Implementation Steps

1. **Setup Phase**
   - Create `src/pflow/planning/__init__.py` (empty file)
   - Import required components (import_node_class, PflowMetadataExtractor, logger)

2. **Processing Phase**
   - Initialize extractor and results storage
   - For each node in registry_metadata:
     - Skip if "test" in file_path
     - Try to import node class using import_node_class()
     - Try to extract metadata using extractor
     - Skip node if either step fails (with logging)
     - Store successful extractions with node type

3. **Formatting Phase**
   - Group nodes by category (simple pattern matching)
   - For each category and node:
     - Format description (first line of docstring)
     - Format inputs with optional indicators
     - Format outputs with action indicators
     - Format only exclusive parameters
     - Build markdown section

4. **Output Phase**
   - Join all sections into final markdown
   - Log summary statistics (nodes processed, skipped, categories)

## Success Criteria
- [x] Creates `src/pflow/planning/` directory with proper structure
- [x] Function handles all import failures gracefully with logging
- [x] Skips test nodes based on file path detection
- [x] Shows only exclusive parameters (not duplicating inputs)
- [x] Groups nodes by logical categories
- [x] Produces clean, readable markdown for LLM consumption
- [x] All tests pass
- [x] No regressions in existing functionality

## Test Strategy
- Unit tests:
  - Test with mock registry data
  - Test import failure handling
  - Test metadata extraction failures
  - Test parameter filtering logic
  - Test category grouping
  - Test output format consistency
- Integration tests:
  - Test with real registry data
  - Verify format works with Task 17's planner
- Manual verification:
  - Run on actual registry and review output
  - Check readability and completeness

## Dependencies
- Requires: Registry system (Task 5) to be functional
- Requires: Metadata extractor (Task 7) to be functional
- Requires: Runtime compiler with import_node_class()
- Impacts: Task 17 (workflow planner) will consume this output

## Decisions Made
- Skip nodes that fail import or metadata extraction (User confirmed via decisions doc)
- Use simple pattern matching for categories (Per handoff: "Don't over-engineer")
- Show only exclusive parameters to reduce redundancy (Key insight from handoff)
- Filter test nodes by path pattern (Standard Python convention)
