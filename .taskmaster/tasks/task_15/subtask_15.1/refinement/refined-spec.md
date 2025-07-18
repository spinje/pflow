# Refined Specification for Subtask 15.1

## Clear Objective
Create the workflow loading infrastructure that reads saved workflow JSON files from `~/.pflow/workflows/` directory, validates essential fields, and returns workflow metadata for use by the context builder.

## Context from Knowledge Base
- Building on: Registry's JSON loading pattern with graceful error handling
- Avoiding: Catching exceptions in critical paths that would disable retry mechanisms
- Following: Path handling conventions using Path objects for cross-platform compatibility
- **Cookbook patterns to apply**:
  - pocketflow-map-reduce for directory reading
  - pocketflow-structured-output for validation patterns

## Technical Specification

### Function Signature
```python
def _load_saved_workflows() -> list[dict[str, Any]]:
    """Load all workflow JSON files from ~/.pflow/workflows/ directory.

    Returns:
        List of workflow metadata dicts with at least:
        - name: str
        - description: str
        - inputs: list[str]
        - outputs: list[str]
        - ir: dict (full workflow IR)

        Additional fields preserved if present:
        - ir_version, version, tags, created_at, updated_at
    """
```

### Inputs
- No parameters (hard-coded to `~/.pflow/workflows/` directory)
- Reads all `*.json` files in the directory

### Outputs
- List of workflow metadata dictionaries
- Empty list if directory doesn't exist or is empty
- Skips invalid files (returns partial results)

### Implementation Constraints
- Must use: `Path.home() / '.pflow' / 'workflows'` for cross-platform compatibility
- Must avoid: Raising exceptions for individual file failures
- Must maintain: Consistent error handling pattern with Registry

### Directory Creation
- Create `~/.pflow/workflows/` if it doesn't exist
- Use `os.makedirs(path, exist_ok=True)`
- No error if directory already exists

### Validation Requirements
Only validate essential fields:
- `name` (string, required)
- `description` (string, required)
- `inputs` (list, required)
- `outputs` (list, required)
- `ir` (dict, required)

Optional fields are preserved but not validated:
- `ir_version`, `version`, `tags`, `created_at`, `updated_at`

### Error Handling
| Error Type | Action | Logging Level |
|------------|--------|---------------|
| Directory doesn't exist | Create it, return [] | Debug |
| Invalid JSON syntax | Skip file | Warning |
| Missing required field | Skip file | Warning |
| Permission error | Skip file | Warning |
| Non-JSON file | Skip file | Debug |

## Success Criteria
- [ ] Function creates workflow directory if missing
- [ ] Loads all valid JSON files from the directory
- [ ] Validates required fields (name, description, inputs, outputs, ir)
- [ ] Skips invalid files with appropriate warnings
- [ ] Returns empty list for empty directory
- [ ] All tests pass
- [ ] No exceptions escape the function

## Test Strategy

### Unit Tests (`tests/test_planning/test_workflow_loading.py`)
- Test directory creation when missing
- Test loading valid workflows
- Test handling invalid JSON
- Test missing required fields
- Test empty directory
- Test permission errors (if possible to mock)
- Test non-JSON files are ignored

### Test Workflow Files
Create 2-3 valid test workflows using test nodes:
1. **test-data-pipeline.json**: Multi-node workflow with test_node_structured
2. **test-simple-workflow.json**: Single test_node workflow
3. **test-retry-workflow.json**: Workflow using test_node_retry

Create 1-2 invalid test workflows:
1. **invalid-missing-name.json**: Missing required name field
2. **invalid-bad-json.json**: Malformed JSON syntax

### Integration Tests
- Test with context_builder integration (if time permits)
- Verify workflow metadata format matches expectations

## Dependencies
- Requires: `~/.pflow/` directory exists (parent directory)
- Impacts: Will be called by `build_discovery_context()` and `build_planning_context()`

## Decisions Made
- [Decision]: Use hard-coded `~/.pflow/workflows/` path (Consistent with Registry pattern)
- [Decision]: Trust internal `name` field over filename (Single source of truth)
- [Decision]: Skip invalid files rather than fail entirely (Graceful degradation)

## Implementation Notes
1. Follow Registry.load() pattern for consistency
2. Use logging for debugging and error tracking
3. Return list of dicts, not dict (as specified in handoff)
4. Workflow names in list should match `name` field, not filename
5. Function should be private (underscore prefix)
