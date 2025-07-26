# Feature: node_ir_template_validation

## Objective

Store parsed interface metadata in registry for accurate template validation.

## Requirements

- Must parse node Interface docstrings during scanning
- Must store full metadata including types and structures
- Must validate template paths against actual node outputs
- Must eliminate heuristic-based validation
- Must preserve exact context builder output format
- Must handle both simple and rich metadata formats

## Scope

- Does not modify node implementations
- Does not change workflow IR structure
- Does not add backward compatibility
- Does not implement lazy registry loading
- Does not validate data flow order

## Inputs

- `node_class`: type - Node class to extract metadata from
- `workflow_ir`: dict[str, Any] - Workflow IR for validation
- `initial_params`: dict[str, Any] - Parameters from planner/CLI
- `registry`: Registry - Registry instance with node metadata

## Outputs

Returns: Modified registry with interface field per node containing:
- `description`: str - Node description
- `inputs`: list[dict[str, Any]] - Input specifications
- `outputs`: list[dict[str, Any]] - Output specifications
- `params`: list[dict[str, Any]] - Parameter specifications
- `actions`: list[str] - Available actions

Side effects:
- Registry JSON file updated with parsed interfaces
- Context builder simplified to use pre-parsed data
- Validator uses actual node outputs instead of heuristics

## Structured Formats

```json
{
  "registry_entry": {
    "class_name": "str",
    "module": "str",
    "file_path": "str",
    "docstring": "str",
    "interface": {
      "description": "str",
      "inputs": [{"key": "str", "type": "str", "description": "str"}],
      "outputs": [{"key": "str", "type": "str", "description": "str", "structure": {}}],
      "params": [{"key": "str", "type": "str", "description": "str"}],
      "actions": ["str"]
    }
  }
}
```

## State/Flow Changes

- `scanning` → `parsing` when MetadataExtractor processes docstring
- `parsing` → `storing` when interface extracted successfully
- `storing` → `complete` when registry entry written
- `loading` → `validating` when validator accesses interface data

## Constraints

- Registry file size ≤ 2MB for MVP
- Scanning time ≤ 20 seconds for 100 nodes
- Import failures must raise with actionable errors
- No silent parsing failures allowed

## Rules

1. Scanner must use dependency injection for MetadataExtractor
2. Scanner must call extractor.extract_metadata on each node class
3. Scanner must store result in interface field of registry entry
4. Scanner must fail with clear error if parsing fails
5. Scanner must preserve all metadata including nested structures
6. Context builder must use interface field directly
7. Context builder must not import nodes dynamically
8. Context builder must return 0 skipped nodes
9. Validator must require registry parameter
10. Validator must extract output keys from interface.outputs
11. Validator must handle both string and dict output formats
12. Validator must traverse structure for nested path validation
13. Validator must check initial_params before node outputs
14. Compiler must pass registry to validator
15. All heuristic validation code must be deleted

## Edge Cases

- Node has no docstring → interface contains empty lists
- Node has malformed Interface → scanner fails with file:line error
- Output is simple string format → validator creates type "any"
- Output is rich dict format → validator uses provided type
- Template path traverses non-dict → validation fails
- Template base not in any source → validation fails with specific error
- Registry file corrupted → scanner regenerates from scratch
- Import side effects occur → scanner fails with clear error

## Error Handling

- Import failure → raise with module path and actionable error
- Parse failure → raise with file path and line reference
- Missing interface field → treat as bug and fail fast
- Unknown node type in workflow → raise ValueError
- Registry write failure → raise with filesystem error

## Non-Functional Criteria

- Parse time per node ≤ 200ms P95
- Registry load time ≤ 100ms for 1MB file
- Memory usage ≤ 50MB during scanning
- Zero runtime parsing after registry update

## Examples

### Scanner with interface parsing:
```python
metadata = {
    "module": "pflow.nodes.file.read_file",
    "class_name": "ReadFileNode",
    "interface": {
        "inputs": [{"key": "file_path", "type": "str", "description": "Path to file"}],
        "outputs": [{"key": "content", "type": "str", "description": "File contents"}]
    }
}
```

### Validator with path traversal:
```python
# Template: $api_config.endpoint.url
# Output: {"key": "api_config", "type": "dict", "structure": {"endpoint": {"url": "str"}}}
# Result: validation passes
```

## Test Criteria

1. Scanner stores interface field for node with Interface section
2. Scanner stores empty interface for node without Interface
3. Scanner fails with clear error for malformed Interface
4. Context builder uses interface data without parsing
5. Context builder returns exact same format as before
6. Validator requires registry parameter
7. Validator extracts simple string outputs correctly
8. Validator extracts rich dict outputs correctly
9. Validator validates base variable exists
10. Validator validates nested paths in structures
11. Validator fails for path through non-dict type
12. Validator prioritizes initial_params over node outputs
13. Compiler passes registry to validator
14. No heuristic code remains in validator
15. End-to-end workflow validation works correctly
16. Scanner regenerates registry when file corrupted
17. Scanner fails with actionable error on import failure
18. Validation fails with specific error for missing template source

## Notes (Why)

- Parsing at scan time eliminates redundant runtime work
- Full metadata enables future type checking and documentation
- Path validation catches type mismatches early
- Fail-fast philosophy surfaces problems during development
- Single source of truth simplifies maintenance

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 1                          |
| 3      | 1                          |
| 4      | 3                          |
| 5      | 1, 10                      |
| 6      | 4                          |
| 7      | 4                          |
| 8      | 5                          |
| 9      | 6                          |
| 10     | 7, 8                       |
| 11     | 7, 8                       |
| 12     | 10, 11                     |
| 13     | 12                         |
| 14     | 13                         |
| 15     | 14                         |

## Versioning & Evolution

- **Version:** 1.0.1
- **Changelog:**
  - **1.0.1** — Updated Rule 1 for clarity, added missing test criteria for edge cases, clarified error handling
  - **1.0.0** — Initial specification for Node IR implementation

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes all nodes follow PocketFlow base class pattern
- Assumes MetadataExtractor handles all docstring formats correctly
- Unknown: Exact performance impact of 1MB registry load
- Unknown: Whether all nodes will parse successfully

### Conflicts & Resolutions

- Template validation fix document suggested runtime parsing → Resolution: Use scan-time parsing per architectural principles
- Context builder currently catches import errors → Resolution: Let scanner handle all import errors for consistency
- Original spec said "import inside function" but implementation guide shows dependency injection → Resolution: Use dependency injection pattern to avoid circular imports

### Decision Log / Tradeoffs

- Chose full metadata storage over minimal keys for future extensibility
- Chose fail-fast over graceful degradation for MVP quality
- Chose dependency injection for MetadataExtractor to avoid circular imports
- Chose to preserve exact context builder format to avoid breaking planner

### Ripple Effects / Impact Map

- Scanner: Major changes to extract_metadata function
- Registry: New interface field changes JSON structure
- Context builder: Simplified to ~10 lines
- Validator: Complete rewrite of validation logic
- All tests using validator must add registry parameter
- Performance: One-time 10s cost, ongoing 50ms overhead per command

### Residual Risks & Confidence

- Risk: Some nodes may have unparseable docstrings. Mitigation: Fail with clear errors.
- Risk: 1MB registry impacts startup time. Mitigation: Profile and optimize if needed.
- Risk: Breaking planner with format changes. Mitigation: Extensive testing.
- Confidence: High for correctness, Medium for performance.

### Epistemic Audit (Checklist Answers)

1. Assumed nodes follow patterns; assumed extractor is comprehensive
2. Wrong patterns break scanning; wrong extractor breaks parsing
3. Robustness over elegance: fail-fast, full storage, no fallbacks
4. All rules covered by tests (see matrix)
5. Touches scanner, registry, context builder, validator, all their tests
6. Performance impact uncertain; confident in correctness approach
