# Feature: workflow_manager

## Objective

Centralize workflow lifecycle management with format standardization.

## Requirements

- Must provide save functionality for workflows
- Must handle name-to-path resolution
- Must bridge format gap between components
- Must consolidate scattered loading implementations
- Must leverage Task 21 input/output declarations

## Scope

- Does not modify existing workflow IR schema
- Does not implement workflow versioning
- Does not handle workflow execution
- Does not manage node registry

## Inputs

- name: str - Workflow name (snake_case, max 50 chars)
- workflow_ir: dict - Workflow IR with inputs/outputs from Task 21
- description: Optional[str] - Human-readable workflow description

## Outputs

Returns: WorkflowManager instance with methods:
- save(name, workflow_ir, description) -> str (path)
- load(name) -> dict (full metadata)
- load_ir(name) -> dict (raw IR only)
- get_path(name) -> str
- list_all() -> List[WorkflowMetadata]
- exists(name) -> bool
- delete(name) -> None

Side effects:
- Creates ~/.pflow/workflows/ directory if missing
- Writes workflow JSON files to disk
- Maintains consistent storage format

## Structured Formats

```json
{
  "storage_format": {
    "name": "string",
    "description": "string",
    "ir": {
      "ir_version": "string",
      "inputs": "object",
      "outputs": "object",
      "nodes": "array",
      "edges": "array"
    },
    "created_at": "string (ISO 8601)",
    "updated_at": "string (ISO 8601)",
    "version": "string (semver)"
  },
  "workflow_metadata": {
    "name": "string",
    "description": "string",
    "inputs": "array[string]",
    "outputs": "array[string]",
    "created_at": "string",
    "version": "string"
  }
}
```

## State/Flow Changes

- None

## Constraints

- Workflow names must be unique
- Workflow names follow snake_case convention
- Storage directory is ~/.pflow/workflows/
- Files use .json extension

## Rules

1. save() wraps IR with metadata before persisting
2. save() adds created_at timestamp in ISO 8601 format
3. save() adds version "1.0.0" to new workflows
4. save() raises WorkflowExistsError if name exists
5. load() returns full metadata-wrapped format
6. load_ir() returns only the ir field contents
7. get_path() returns absolute expanded path
8. list_all() reads all valid workflow files
9. exists() checks file existence by name
10. delete() removes workflow file from disk
11. All methods expand tilde in paths
12. Invalid JSON files are skipped with warning
13. Missing required fields cause ValidationError
14. Workflow names convert hyphens to underscores

## Edge Cases

- save() with existing name → WorkflowExistsError
- load() with missing name → WorkflowNotFoundError
- load_ir() with missing name → WorkflowNotFoundError
- delete() with missing name → WorkflowNotFoundError
- Empty workflow directory → list_all() returns []
- Corrupted JSON file → skip with warning log
- Missing ir field in file → ValidationError
- Missing required metadata fields → ValidationError
- Permission error reading file → skip with warning
- Workflow name with spaces → replace with underscores

## Error Handling

- WorkflowExistsError for duplicate names
- WorkflowNotFoundError for missing workflows
- ValidationError for invalid workflow structure
- PermissionError bubbles up from filesystem

## Non-Functional Criteria

- None

## Examples

```python
# Save new workflow
manager = WorkflowManager()
path = manager.save("fix_issue", workflow_ir, "Fixes GitHub issues")
# Returns: "/Users/name/.pflow/workflows/fix_issue.json"

# Load for discovery
metadata = manager.load("fix_issue")
# Returns: {"name": "fix_issue", "description": "...", "ir": {...}}

# Load for execution
ir = manager.load_ir("fix_issue")
# Returns: {"ir_version": "0.1.0", "nodes": [...], ...}

# List all workflows
workflows = manager.list_all()
# Returns: [{"name": "fix_issue", "description": "...", ...}]
```

## Test Criteria

1. save() with new name creates file with metadata wrapper
2. save() with existing name raises WorkflowExistsError
3. save() adds required timestamps and version
4. load() returns complete metadata structure
5. load() with missing name raises WorkflowNotFoundError
6. load_ir() returns only IR contents
7. get_path() returns expanded absolute path
8. list_all() returns all valid workflows
9. list_all() skips invalid JSON with warning
10. exists() returns True for saved workflow
11. exists() returns False for missing workflow
12. delete() removes existing workflow file
13. delete() with missing name raises WorkflowNotFoundError
14. Workflow name "fix-issue" becomes "fix_issue"
15. Empty directory returns empty list
16. Missing ir field raises ValidationError
17. Permission error logs warning and continues

## Notes (Why)

- Metadata wrapper preserves workflow identity and enables discovery
- Separate load/load_ir handles format mismatch between components
- Centralization eliminates code duplication across system
- Name-based API simplifies planner integration
- Validation ensures data consistency

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1, 4                       |
| 2      | 3                          |
| 3      | 3                          |
| 4      | 2                          |
| 5      | 4                          |
| 6      | 6                          |
| 7      | 7                          |
| 8      | 8, 9                       |
| 9      | 10, 11                     |
| 10     | 12, 13                     |
| 11     | 7                          |
| 12     | 9                          |
| 13     | 16                         |
| 14     | 14                         |

## Versioning & Evolution

- v1.0.0 - Initial workflow manager implementation

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes ~/.pflow/workflows/ as standard location
- Assumes synchronous file I/O is acceptable
- Unknown: concurrent access patterns
- Unknown: workflow size limits

### Conflicts & Resolutions

- Context Builder expects metadata wrapper, WorkflowExecutor expects raw IR
- Resolution: Provide both load() and load_ir() methods
- Multiple workflow loading implementations exist
- Resolution: Consolidate into WorkflowManager

### Decision Log / Tradeoffs

- Chose metadata wrapper for storage over raw IR to preserve workflow identity
- Chose exception raising over None returns for clearer error handling
- Chose file-based storage over database for simplicity
- Chose name uniqueness enforcement over versioning for MVP

### Ripple Effects / Impact Map

- Context Builder must use WorkflowManager instead of direct loading
- CLI must implement save functionality using WorkflowManager
- WorkflowExecutor enhancement to support workflow_name parameter
- Natural Language Planner can use workflow names directly

### Residual Risks & Confidence

- Risk: File system race conditions under concurrent access
- Risk: Large workflow files impacting performance
- Risk: Breaking existing workflow file compatibility
- Confidence: High for single-user scenarios

### Epistemic Audit (Checklist Answers)

1. Assumed single-user file access patterns
2. Concurrent access could cause data corruption
3. Prioritized robustness with validation over performance
4. All rules mapped to test criteria
5. Touches Context Builder, CLI, WorkflowExecutor, Planner
6. Uncertainty: concurrent access handling; Confidence: High for MVP scope
