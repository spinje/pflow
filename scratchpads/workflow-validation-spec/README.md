# Workflow Validation Specification

## Executive Summary

This specification defines how pflow should validate workflow files when loading them from disk. Currently, the system only validates JSON syntax but not the structure of workflow metadata. This has led to runtime failures when malformed workflows (like the `test-suite.json` incident) are encountered.

## Problem Statement

### Current Issues
1. **No structural validation**: WorkflowManager loads any valid JSON file without checking required fields
2. **Runtime crashes**: Missing fields like `name` cause KeyErrors in downstream components
3. **Silent failures**: Invalid workflows can cause confusing errors far from the source
4. **Poor user experience**: Users don't know their workflow files are malformed until runtime

### The Incident
A workflow file (`test-suite.json`) was saved with only the IR structure, missing the required metadata wrapper:
```json
// Invalid - missing wrapper
{
  "ir_version": "0.1.0",
  "nodes": [...]
}

// Valid - has metadata wrapper
{
  "name": "test-suite",
  "description": "...",
  "ir": {
    "ir_version": "0.1.0",
    "nodes": [...]
  }
}
```

This caused `KeyError: 'name'` throughout the system when code assumed `workflow["name"]` would exist.

## Design Principles

### 1. Validate at System Boundaries
- **External input requires validation**: Files on disk are external input that users can modify
- **Internal data is trusted**: Once validated, workflows can be assumed valid internally
- **Test mocks are different**: Test code should provide valid data structures

### 2. Fail Fast with Clear Messages
- **Detect problems early**: Validate when loading, not when using
- **Provide actionable errors**: Tell users exactly what's wrong and how to fix it
- **Log warnings for recovery**: When skipping files, log why

### 3. Graceful Degradation
- **list_all() should be resilient**: Skip invalid files with warnings, return valid ones
- **load() should be strict**: Raise clear exceptions for invalid files
- **Never crash the system**: One bad file shouldn't break everything

## Technical Specification

### Validation Levels

#### Level 1: JSON Validity (Current)
- File must be valid JSON
- **Status**: Already implemented

#### Level 2: Metadata Structure (Required)
- Required fields in metadata wrapper:
  - `name` (string, non-empty)
  - `ir` (object)
- Optional but expected fields:
  - `description` (string)
  - `created_at` (ISO timestamp string)
  - `updated_at` (ISO timestamp string)
  - `version` (string)

#### Level 3: IR Validity (Recommended)
- Validate `ir` field using existing `validate_ir()` function
- Ensures IR conforms to schema
- Catches structural issues early

#### Level 4: Registry Validation (Future)
- Verify all node types exist in registry
- Check parameter compatibility
- **Not in scope for this implementation**

### Implementation Requirements

#### 1. Update WorkflowManager.list_all()
```python
def list_all(self) -> list[dict[str, Any]]:
    """List all valid workflows in the directory.

    Skips invalid workflow files with warnings.

    Returns:
        List of valid workflow metadata dicts
    """
    workflows = []

    for file_path in self.workflows_dir.glob("*.json"):
        workflow = self._load_and_validate_file(file_path, strict=False)
        if workflow:
            workflows.append(workflow)

    # Sort by name for consistent ordering
    workflows.sort(key=lambda w: w["name"])  # Safe - validated workflows have name

    return workflows
```

#### 2. Update WorkflowManager.load()
```python
def load(self, name: str) -> dict[str, Any]:
    """Load and validate a workflow by name.

    Args:
        name: Workflow name

    Returns:
        Validated workflow metadata dict

    Raises:
        WorkflowNotFoundError: If workflow doesn't exist
        WorkflowValidationError: If workflow is invalid
    """
    file_path = self.workflows_dir / f"{name}.json"

    if not file_path.exists():
        raise WorkflowNotFoundError(f"Workflow '{name}' not found")

    workflow = self._load_and_validate_file(file_path, strict=True)
    if not workflow:
        # Should not happen with strict=True, but be defensive
        raise WorkflowValidationError(f"Workflow '{name}' failed validation")

    return workflow
```

#### 3. Add validation helper method
```python
def _load_and_validate_file(self, file_path: Path, strict: bool = True) -> Optional[dict[str, Any]]:
    """Load and validate a workflow file.

    Args:
        file_path: Path to workflow JSON file
        strict: If True, raise exceptions; if False, return None on error

    Returns:
        Validated workflow dict or None if invalid and not strict

    Raises:
        WorkflowValidationError: If strict=True and validation fails
    """
    try:
        # Level 1: JSON validation
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)

    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON in {file_path.name}: {e}"
        if strict:
            raise WorkflowValidationError(error_msg) from e
        logger.warning(error_msg)
        return None

    except Exception as e:
        error_msg = f"Failed to read {file_path.name}: {e}"
        if strict:
            raise WorkflowValidationError(error_msg) from e
        logger.warning(error_msg)
        return None

    # Level 2: Metadata structure validation
    validation_errors = self._validate_metadata_structure(data)
    if validation_errors:
        error_msg = f"Invalid workflow structure in {file_path.name}: {'; '.join(validation_errors)}"
        if strict:
            raise WorkflowValidationError(error_msg)
        logger.warning(error_msg)
        return None

    # Level 3: IR validation (optional, controlled by setting)
    if self.validate_ir_on_load:  # New optional setting
        try:
            from pflow.core.ir_schema import validate_ir
            validate_ir(data["ir"])
        except Exception as e:
            error_msg = f"Invalid IR in {file_path.name}: {e}"
            if strict:
                raise WorkflowValidationError(error_msg) from e
            logger.warning(error_msg)
            return None

    logger.debug(f"Successfully validated workflow from {file_path}")
    return data

def _validate_metadata_structure(self, data: dict) -> list[str]:
    """Validate the metadata wrapper structure.

    Args:
        data: Loaded JSON data

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Check required fields
    if not isinstance(data, dict):
        errors.append("Root must be an object")
        return errors  # Can't check further

    if "name" not in data:
        errors.append("Missing required field 'name'")
    elif not isinstance(data["name"], str) or not data["name"].strip():
        errors.append("Field 'name' must be a non-empty string")

    if "ir" not in data:
        errors.append("Missing required field 'ir'")
    elif not isinstance(data["ir"], dict):
        errors.append("Field 'ir' must be an object")

    # Validate name doesn't contain invalid characters (for filesystem)
    if "name" in data and isinstance(data["name"], str):
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        if any(char in data["name"] for char in invalid_chars):
            errors.append(f"Field 'name' contains invalid characters: {invalid_chars}")

    return errors
```

#### 4. Fix downstream bug in WorkflowDiscoveryNode
```python
# In WorkflowDiscoveryNode.post()
try:
    shared["found_workflow"] = workflow_manager.load(exec_res["workflow_name"])
    logger.debug(f"Loaded workflow: {exec_res['workflow_name']}")
    return "found_existing"
except (WorkflowNotFoundError, WorkflowValidationError) as e:
    # Workflow doesn't exist or is invalid, fall back to generation
    logger.warning(f"Workflow '{exec_res['workflow_name']}' not available: {e}")
    logger.info("Falling back to workflow generation (Path B)")
    return "not_found"
```

### Configuration Options

Add to WorkflowManager initialization:
```python
def __init__(self, workflows_dir: Optional[Path] = None, validate_ir_on_load: bool = False):
    """Initialize WorkflowManager.

    Args:
        workflows_dir: Directory for workflow files
        validate_ir_on_load: If True, validate IR structure when loading workflows
    """
    self.workflows_dir = workflows_dir or (Path.home() / ".pflow" / "workflows")
    self.validate_ir_on_load = validate_ir_on_load
    self.workflows_dir.mkdir(parents=True, exist_ok=True)
```

### Error Messages

#### User-facing error messages should be:
1. **Specific**: "Missing required field 'name'" not "Invalid structure"
2. **Actionable**: "Add a 'name' field to the workflow file"
3. **Located**: Include the filename in the error

#### Example error messages:
```
WARNING: Skipping invalid workflow 'test-suite.json': Missing required field 'name'
ERROR: Workflow 'my-workflow' failed validation: Field 'name' must be a non-empty string
WARNING: Invalid IR in 'broken.json': Node 'start' references undefined node 'missing'
```

### Testing Requirements

#### 1. Test validation of various invalid structures
```python
def test_list_all_skips_various_invalid_workflows(workflow_manager):
    """Test that list_all handles various types of invalid workflows."""
    # Create various invalid files
    invalid_files = {
        "no_name.json": {"ir": {"ir_version": "0.1.0", "nodes": []}},  # Missing name
        "no_ir.json": {"name": "test"},  # Missing ir
        "empty_name.json": {"name": "", "ir": {}},  # Empty name
        "wrong_type.json": {"name": 123, "ir": {}},  # Wrong type for name
        "not_object.json": [],  # Not an object
        "corrupt.json": "not valid json",  # Invalid JSON
    }

    for filename, content in invalid_files.items():
        file_path = workflow_manager.workflows_dir / filename
        with open(file_path, "w") as f:
            if filename == "corrupt.json":
                f.write(content)
            else:
                json.dump(content, f)

    # Should return empty list and log warnings
    with patch("logging.Logger.warning") as mock_warning:
        workflows = workflow_manager.list_all()

    assert len(workflows) == 0
    assert mock_warning.call_count == len(invalid_files)
```

#### 2. Test strict validation in load()
```python
def test_load_validates_structure(workflow_manager):
    """Test that load() validates workflow structure."""
    # Save invalid workflow
    invalid_path = workflow_manager.workflows_dir / "invalid.json"
    with open(invalid_path, "w") as f:
        json.dump({"ir": {}}, f)  # Missing name

    with pytest.raises(WorkflowValidationError) as exc_info:
        workflow_manager.load("invalid")

    assert "Missing required field 'name'" in str(exc_info.value)
```

#### 3. Test mixed valid/invalid workflows
```python
def test_list_all_returns_valid_skips_invalid(workflow_manager, sample_ir):
    """Test that list_all returns valid workflows and skips invalid ones."""
    # Save valid workflow
    workflow_manager.save("valid", sample_ir, "Valid workflow")

    # Create invalid workflow
    invalid_path = workflow_manager.workflows_dir / "invalid.json"
    with open(invalid_path, "w") as f:
        json.dump({"no_name": True}, f)

    workflows = workflow_manager.list_all()

    assert len(workflows) == 1
    assert workflows[0]["name"] == "valid"
```

### Migration Guide

#### For existing users:
1. Run validation script to check existing workflows:
```bash
pflow validate-workflows
```

2. Fix any reported issues:
   - Add missing `name` fields
   - Wrap bare IR in metadata structure
   - Fix invalid characters in names

#### For developers:
1. Update any code that creates workflow files directly
2. Use WorkflowManager.save() instead of manual JSON writing
3. Catch `WorkflowValidationError` where appropriate

### Performance Considerations

- **Validation overhead**: Minimal for Level 1-2 (< 1ms per file)
- **IR validation**: Can be slower for large workflows (5-50ms)
- **Caching**: Consider caching validation results by file mtime
- **Lazy loading**: Could defer full validation until workflow is actually used

### Security Considerations

- **Path traversal**: Validate that workflow names don't contain path separators
- **File size limits**: Consider rejecting extremely large files (> 10MB)
- **JSON bombs**: Use streaming parser for large files
- **Sensitive data**: Don't log full workflow content in errors

## Implementation Plan

### Phase 1: Core Validation (Required)
1. Implement `_validate_metadata_structure()`
2. Implement `_load_and_validate_file()`
3. Update `list_all()` to use validation
4. Update `load()` to use validation
5. Add comprehensive tests

### Phase 2: Bug Fixes (Required)
1. Fix WorkflowDiscoveryNode to catch WorkflowValidationError
2. Update any other components that call load()

### Phase 3: Enhanced Validation (Optional)
1. Add `validate_ir_on_load` configuration option
2. Implement IR validation integration
3. Add performance optimizations

### Phase 4: User Tools (Future)
1. Add `pflow validate-workflows` CLI command
2. Add migration script for old workflows
3. Add workflow repair suggestions

## Success Criteria

1. **No KeyErrors**: System never crashes due to missing workflow fields
2. **Clear errors**: Users understand exactly what's wrong with invalid workflows
3. **Resilient operation**: One bad workflow doesn't affect others
4. **Backward compatible**: Existing valid workflows continue to work
5. **Performance neutral**: No significant performance impact for valid workflows

## References

- Current implementation: `/Users/andfal/projects/pflow/src/pflow/core/workflow_manager.py`
- IR schema: `/Users/andfal/projects/pflow/src/pflow/core/ir_schema.py`
- Related tests: `/Users/andfal/projects/pflow/tests/test_core/test_workflow_manager.py`
- Example workflows: `/Users/andfal/projects/pflow/examples/`

## Author

Written by Claude, Session ID: `2946a00a-da06-4adb-a5ca-2d0fe0de97e9`
