# node_ir_template_validation

## Objective

Fix template validation failures by creating a proper "Node IR" that stores fully parsed interface metadata in the registry. Currently, the template validator uses hardcoded heuristics to guess which variables come from the shared store (e.g., assuming "content", "result" are outputs), causing false validation failures when nodes write variables not in the magic list. This implementation moves interface parsing from runtime to scan-time, storing structured metadata that enables accurate validation of template variables against actual node outputs. The solution eliminates redundant parsing, creates a single source of truth for node capabilities, and provides rich metadata for future features like type checking.

## Requirements

- Parse node Interface docstrings during scanning using MetadataExtractor
- Store complete interface metadata including keys, types, descriptions, and nested structures
- Validate template variable paths against actual node outputs from registry
- Handle both simple string and rich dict output formats from MetadataExtractor
- Preserve exact context builder output format for planner compatibility
- Fail fast with actionable errors showing file:line references
- Support full path validation (e.g., $api_config.endpoint.url)

## Scope

- Updates scanner.py to parse and store interface metadata
- Updates context_builder.py to use pre-parsed data
- Updates template_validator.py to use registry for validation
- Updates compiler.py to pass registry to validator
- Does not modify node implementations or behavior
- Does not change workflow IR structure
- Does not add backward compatibility for old registry format
- Does not implement registry lazy loading or caching
- Does not validate execution order or data flow dependencies

## Inputs

Scanner.extract_metadata:
- `cls`: type - Node class to extract metadata from
- `module_path`: str - Module path for the node
- `file_path`: Path - File path where node is defined
- `extractor`: Optional[MetadataExtractor] - Injected extractor instance

TemplateValidator.validate_workflow_templates:
- `workflow_ir`: dict[str, Any] - Workflow IR containing nodes and templates
- `available_params`: dict[str, Any] - Parameters from planner/CLI
- `registry`: Registry - Registry instance with parsed node metadata

## Outputs

Scanner.extract_metadata returns:
```python
{
    "module": str,
    "class_name": str,
    "name": str,
    "docstring": str,
    "file_path": str,
    "interface": {
        "description": str,
        "inputs": list[dict[str, Any]],
        "outputs": list[dict[str, Any]],
        "params": list[dict[str, Any]],
        "actions": list[str]
    }
}
```

TemplateValidator.validate_workflow_templates returns:
- `list[str]` - Empty list if valid, error messages if invalid

Side effects:
- Registry JSON file grows from ~50KB to ~500KB-1MB
- Context builder removes ~100 lines of parsing code
- Validator replaces heuristics with registry lookups
- Startup time increases by ~50ms due to larger registry

## Structured Formats

Registry entry with interface:
```json
{
  "node-type": {
    "module": "pflow.nodes.category.node_name",
    "class_name": "NodeNameNode",
    "name": "node-type",
    "docstring": "Original docstring text...",
    "file_path": "/absolute/path/to/node.py",
    "interface": {
      "description": "First line of docstring",
      "inputs": [
        {
          "key": "input_name",
          "type": "str",
          "description": "Input description"
        }
      ],
      "outputs": [
        {
          "key": "output_name",
          "type": "dict",
          "description": "Output description",
          "structure": {
            "field1": {
              "type": "str",
              "description": "Field description"
            },
            "nested": {
              "type": "dict",
              "description": "Nested structure",
              "structure": {
                "subfield": {
                  "type": "int",
                  "description": "Nested field"
                }
              }
            }
          }
        }
      ],
      "params": [
        {
          "key": "param_name",
          "type": "any",
          "description": "Parameter description"
        }
      ],
      "actions": ["default", "error", "retry"]
    }
  }
}
```

## State/Flow Changes

Scanner states:
- `idle` → `importing` when scan_for_nodes called
- `importing` → `extracting` when node class imported successfully
- `extracting` → `storing` when interface parsed successfully
- `storing` → `idle` when registry entry saved
- Any state → `failed` on error with clear message

Validator states:
- `idle` → `loading` when validate_workflow_templates called
- `loading` → `checking` when registry nodes loaded
- `checking` → `traversing` when validating nested paths
- `traversing` → `complete` when all templates validated
- Any state → `invalid` when template has no source

## Constraints

- Registry file size must not exceed 10MB
- Total scan time must not exceed 30 seconds for 200 nodes
- Each node parse time must not exceed 500ms
- Registry load time must not exceed 200ms
- Import failures must include file path and line number
- Parse failures must include docstring line reference

## Rules

1. Scanner must inject MetadataExtractor via parameter with singleton fallback
2. Scanner must store both module path and file path in metadata
3. Scanner must convert Path objects to strings before JSON serialization
4. Scanner must handle None docstrings by passing empty string to extractor
5. Scanner must fail immediately on parse errors with actionable message
6. Scanner must preserve complete nested structures in outputs
7. Context builder must use interface field without any parsing
8. Context builder must maintain exact output format structure
9. Context builder must return zero skipped nodes
10. Validator must make registry parameter required not optional
11. Validator must handle simple string outputs by creating type "any"
12. Validator must handle rich dict outputs by preserving all fields
13. Validator must validate complete paths not just base variables
14. Validator must check initial_params before checking node outputs
15. Validator must fail if path traverses non-dict type
16. Compiler must pass existing registry parameter to validator
17. All heuristic code must be removed from validator

## Edge Cases

- Node class has None docstring → extractor receives empty string
- Node has no Interface section → interface contains empty lists/description only
- Node has malformed Interface → scanner fails with ParseError and location
- Import has side effects → scanner logs but continues with clear error
- Output uses simple format ["key1", "key2"] → converted to rich format
- Output uses rich format [{"key": "k1", "type": "str"}] → preserved as-is
- Template has dot path $var.field.subfield → validator traverses structure
- Path component missing from structure → validation fails with path detail
- Base variable not in any source → error specifies sources checked
- Registry file is corrupted JSON → scanner logs error and regenerates
- Node cannot be imported → scanner fails with import error and continues
- Structure has circular reference → parser handles up to depth 10

## Error Handling

Import errors:
- `ImportError` → "Failed to import module 'X' at /path/file.py: [error detail]"
- `AttributeError` → "Module 'X' has no class 'Y' at /path/file.py"

Parse errors:
- `ParseError` → "Failed to parse interface for NodeName at /path/file.py line N: [detail]"
- `ValueError` → "Invalid Interface format at line N: expected 'key: type' got '[actual]'"

Validation errors:
- `ValueError` → "Unknown node type 'X' in workflow"
- Template error → "Template variable $X.Y.Z has no valid source - not in initial_params and path 'Y.Z' not found in outputs of node type 'X'"

Registry errors:
- `JSONDecodeError` → "Registry corrupted at ~/.pflow/registry.json - regenerating"
- `PermissionError` → "Cannot write registry: [permission detail]"

## Non-Functional Criteria

Performance:
- Node metadata extraction: P50 < 100ms, P95 < 200ms, P99 < 500ms
- Full registry scan (100 nodes): P50 < 5s, P95 < 10s, P99 < 15s
- Registry JSON load (1MB): P50 < 30ms, P95 < 50ms, P99 < 100ms
- Template validation (10 nodes): P50 < 10ms, P95 < 20ms, P99 < 50ms

Resource usage:
- Memory during scan: Peak < 100MB for 200 nodes
- Registry file size: < 10KB per node average
- CPU during validation: < 5% for typical workflow

## Examples

Scanner handling both output formats:
```python
# Simple format in docstring:
# - Writes: shared["result"], shared["status"]
outputs = ["result", "status"]  # From extractor

# Stored as rich format:
"outputs": [
    {"key": "result", "type": "any", "description": ""},
    {"key": "status", "type": "any", "description": ""}
]

# Rich format in docstring:
# - Writes: shared["api_data"]: dict  # API response
#     - user: str
#     - token: str
"outputs": [
    {
        "key": "api_data",
        "type": "dict",
        "description": "API response",
        "structure": {
            "user": {"type": "str", "description": ""},
            "token": {"type": "str", "description": ""}
        }
    }
]
```

Validator path traversal:
```python
# Node outputs api_config with structure
node_outputs = {
    "api_config": {
        "type": "dict",
        "structure": {
            "endpoint": {
                "type": "dict",
                "structure": {
                    "url": {"type": "str"},
                    "method": {"type": "str"}
                }
            }
        }
    }
}

# Valid: $api_config.endpoint.url
# Invalid: $api_config.endpoint.timeout (not in structure)
# Invalid: $api_config.endpoint.url.host (url is string, cannot traverse)
```

## Test Criteria

1. Scanner extracts and stores interface for node with simple format outputs
2. Scanner extracts and stores interface for node with rich format outputs
3. Scanner handles node with no docstring by storing empty interface
4. Scanner handles node with no Interface section by storing description only
5. Scanner fails with ParseError for malformed Interface syntax
6. Scanner includes file path and line number in parse error messages
7. Scanner continues after import error with clear error log
8. Scanner converts Path to string in file_path field
9. Context builder uses interface data without importing nodes
10. Context builder output format exactly matches current format
11. Context builder processes all nodes without skipping
12. Validator requires registry parameter (not optional)
13. Validator creates type "any" for simple string outputs
14. Validator preserves all fields for rich dict outputs
15. Validator validates base template variable exists
16. Validator validates full nested paths through structures
17. Validator fails when path tries to traverse non-dict type
18. Validator checks initial_params before node outputs
19. Validator error message includes full path and source details
20. Compiler passes registry to validator successfully
21. No heuristic code remains in validator module
22. End-to-end workflow with nested paths validates correctly
23. Registry regenerates when JSON is corrupted
24. Performance meets all P95 targets under load

## Notes (Why)

Moving parsing to scan-time follows the principle of "parse once, use many times" which eliminates redundant CPU cycles and creates consistency. The fail-fast philosophy with actionable errors accelerates development by surfacing problems immediately rather than hiding them. Full metadata storage enables future type checking, better documentation, and richer error messages. Path validation at compile time catches type mismatches before runtime failures. The dependency injection pattern for MetadataExtractor avoids the circular import issues that plagued the template implementation.

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | Implementation detail      |
| 2      | 8                          |
| 3      | 8                          |
| 4      | 3                          |
| 5      | 5, 6                       |
| 6      | 1, 2, 16                   |
| 7      | 9                          |
| 8      | 10                         |
| 9      | 11                         |
| 10     | 12                         |
| 11     | 13                         |
| 12     | 14                         |
| 13     | 15, 16                     |
| 14     | 18                         |
| 15     | 17                         |
| 16     | 20                         |
| 17     | 21                         |

## Versioning & Evolution

- **Version:** 1.1.0
- **Breaking changes:** validate_workflow_templates signature change
- **Migration:** Run `pflow registry update` after deployment
- **Changelog:**
  - **1.1.0** — Complete rewrite based on implementation guides and critical context
  - **1.0.1** — Updated Rule 1 for clarity, added missing test criteria
  - **1.0.0** — Initial specification for Node IR implementation

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes MetadataExtractor._normalize_to_rich_format handles all legacy formats
- Assumes all nodes inherit from pocketflow.BaseNode or compatible base
- Unknown: Exact memory overhead of keeping MetadataExtractor singleton
- Unknown: Whether all existing nodes will parse without modification
- Unknown: Full performance impact of 1MB registry on CLI startup

### Conflicts & Resolutions

1. Spec suggested "import inside function" vs guide shows dependency injection
   - Resolution: Use dependency injection pattern per critical context doc
   - Rationale: Avoids circular imports that plagued template implementation

2. Original context builder catches import errors vs scanner should handle all imports
   - Resolution: Scanner handles imports and fails fast with clear errors
   - Rationale: Single responsibility and better error locality

3. Validator optional registry parameter vs required parameter
   - Resolution: Make registry required for MVP simplicity
   - Rationale: No valid use case for validation without registry in new design

### Decision Log / Tradeoffs

1. Store full metadata vs minimal keys
   - Decision: Store complete parsed metadata
   - Tradeoff: Larger registry (1MB) for richer features
   - Rationale: Enables type checking and better errors

2. Fail fast vs graceful degradation
   - Decision: Fail immediately with clear errors
   - Tradeoff: Development disruption for long-term quality
   - Rationale: MVP should surface problems not hide them

3. Parse at scan time vs runtime
   - Decision: Parse during scanning only
   - Tradeoff: Slower scan for faster runtime
   - Rationale: Eliminates redundant work

4. Support both output formats vs force migration
   - Decision: Handle both simple and rich formats
   - Tradeoff: More complex validator code
   - Rationale: Avoid breaking existing nodes

### Ripple Effects / Impact Map

1. Scanner changes impact:
   - Registry update command becomes slower (5s → 15s)
   - Registry JSON structure changes (breaking)
   - All registry consumers must handle interface field

2. Context builder changes impact:
   - 100 lines removed (major simplification)
   - No more dynamic imports (security improvement)
   - Faster planning operations

3. Validator API change impacts:
   - All direct callers must add registry parameter
   - Test suites need updates
   - Breaking change for any external tools

4. Performance impacts:
   - Every CLI command loads larger registry (+50ms)
   - Shell completion may become slower
   - LLM context size increases for planner

### Residual Risks & Confidence

High confidence:
- Correctness of validation logic (well understood)
- Scanner implementation (clear patterns)
- Context builder simplification (removing code)

Medium confidence:
- Performance at scale (needs profiling)
- All nodes parsing successfully (needs testing)
- Registry size growth over time (needs monitoring)

Low confidence:
- Impact on shell completion speed
- Memory usage with many concurrent commands
- Behavior with corrupted partial registries

Mitigations:
- Add performance benchmarks to test suite
- Consider registry compression for v2
- Add registry validation on load
- Profile memory usage under load

### Epistemic Audit (Checklist Answers)

1. Which assumptions did I make that weren't explicit?
   - Assumed singleton pattern for MetadataExtractor is thread-safe
   - Assumed JSON serialization preserves all metadata correctly
   - Assumed file system has atomic writes for registry

2. What would break if they're wrong?
   - Thread safety: Concurrent scans could corrupt parser state
   - JSON: Complex structures might serialize incorrectly
   - Atomicity: Partial writes could corrupt registry

3. Did I optimize elegance over robustness?
   - No: Chose explicit failures over elegant fallbacks
   - No: Kept both output formats despite complexity
   - No: Added extensive error context despite verbosity

4. Did every Rule map to at least one Test (and vice versa)?
   - Yes: See compliance matrix, all rules covered
   - Test criteria cover additional edge cases beyond rules

5. What ripple effects or invariants might this touch?
   - Registry consumers must handle new structure
   - Startup time regression affects all commands
   - API change breaks external validator users
   - Planner depends on exact context builder format

6. What remains uncertain, and how confident am I?
   - Uncertain: Performance at scale (medium confidence)
   - Uncertain: Thread safety of singleton (low confidence)
   - Certain: Correctness of validation (high confidence)
   - Certain: Improvement over heuristics (high confidence)
