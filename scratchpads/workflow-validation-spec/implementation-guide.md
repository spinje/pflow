# Implementation Guide for Workflow Validation

## Quick Reference

This guide provides practical implementation details for adding workflow validation to pflow.

## File Locations

### Files to Modify
1. **Primary**: `/Users/andfal/projects/pflow/src/pflow/core/workflow_manager.py`
2. **Bug fix**: `/Users/andfal/projects/pflow/src/pflow/planning/nodes.py` (line ~176)
3. **Tests**: `/Users/andfal/projects/pflow/tests/test_core/test_workflow_manager.py`

### Files to Reference
- Schema validation: `/Users/andfal/projects/pflow/src/pflow/core/ir_schema.py`
- Exceptions: `/Users/andfal/projects/pflow/src/pflow/core/exceptions.py`
- Context builder: `/Users/andfal/projects/pflow/src/pflow/planning/context_builder.py`

## Complete Implementation Code

### Step 1: Add validation methods to WorkflowManager

```python
# In workflow_manager.py, add these methods:

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
        # These characters are invalid in filenames on various OS
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        found_chars = [char for char in invalid_chars if char in data["name"]]
        if found_chars:
            errors.append(f"Field 'name' contains invalid characters: {found_chars}")

    return errors

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
    if hasattr(self, 'validate_ir_on_load') and self.validate_ir_on_load:
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
```

### Step 2: Update list_all() method

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
    # Safe to access 'name' - validated workflows always have it
    workflows.sort(key=lambda w: w["name"])

    return workflows
```

### Step 3: Update load() method

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

    logger.debug(f"Loaded workflow '{name}' from {file_path}")
    return workflow
```

### Step 4: Fix WorkflowDiscoveryNode bug

```python
# In /Users/andfal/projects/pflow/src/pflow/planning/nodes.py
# Around line 176 in the post() method:

# Find this code:
try:
    shared["found_workflow"] = workflow_manager.load(exec_res["workflow_name"])
    logger.debug(f"Loaded workflow: {exec_res['workflow_name']}")
    return "found_existing"
except WorkflowNotFoundError:
    # Workflow doesn't exist on disk despite LLM finding it
    logger.warning(f"Workflow '{exec_res['workflow_name']}' not found on disk")
    logger.info("Falling back to workflow generation (Path B)")
    return "not_found"

# Replace with:
try:
    shared["found_workflow"] = workflow_manager.load(exec_res["workflow_name"])
    logger.debug(f"Loaded workflow: {exec_res['workflow_name']}")
    return "found_existing"
except (WorkflowNotFoundError, WorkflowValidationError) as e:
    # Workflow doesn't exist or is invalid
    logger.warning(f"Workflow '{exec_res['workflow_name']}' not available: {e}")
    logger.info("Falling back to workflow generation (Path B)")
    return "not_found"
```

Don't forget to import WorkflowValidationError at the top:
```python
from pflow.core.exceptions import WorkflowNotFoundError, WorkflowValidationError
```

## Test Cases

### Test 1: Various invalid structures

```python
def test_list_all_skips_various_invalid_workflows(workflow_manager):
    """Test that list_all handles various types of invalid workflows."""
    # Create various invalid files
    invalid_files = {
        "no_name.json": {
            "ir": {"ir_version": "0.1.0", "nodes": [{"id": "test", "type": "echo"}]}
        },  # Missing name
        "no_ir.json": {
            "name": "test",
            "description": "Missing IR"
        },  # Missing ir
        "empty_name.json": {
            "name": "",
            "ir": {"ir_version": "0.1.0", "nodes": []}
        },  # Empty name
        "wrong_type_name.json": {
            "name": 123,
            "ir": {"ir_version": "0.1.0", "nodes": []}
        },  # Wrong type for name
        "not_object.json": [],  # Root is not an object
        "null_name.json": {
            "name": None,
            "ir": {"ir_version": "0.1.0", "nodes": []}
        },  # Null name
        "invalid_chars.json": {
            "name": "test/workflow",
            "ir": {"ir_version": "0.1.0", "nodes": []}
        },  # Invalid characters in name
    }

    for filename, content in invalid_files.items():
        file_path = workflow_manager.workflows_dir / filename
        with open(file_path, "w") as f:
            json.dump(content, f)

    # Add a corrupt JSON file
    corrupt_path = workflow_manager.workflows_dir / "corrupt.json"
    with open(corrupt_path, "w") as f:
        f.write("not valid json {")

    # Should return empty list and log warnings
    with patch("logging.Logger.warning") as mock_warning:
        workflows = workflow_manager.list_all()

    assert len(workflows) == 0
    # +1 for the corrupt JSON file
    assert mock_warning.call_count == len(invalid_files) + 1

    # Verify specific error messages
    warning_messages = [call[0][0] for call in mock_warning.call_args_list]
    assert any("Missing required field 'name'" in msg for msg in warning_messages)
    assert any("Missing required field 'ir'" in msg for msg in warning_messages)
    assert any("must be a non-empty string" in msg for msg in warning_messages)
    assert any("Invalid JSON" in msg for msg in warning_messages)
```

### Test 2: Strict validation in load()

```python
def test_load_validates_structure_strictly(workflow_manager):
    """Test that load() strictly validates workflow structure."""
    test_cases = [
        ("no_name", {"ir": {}}, "Missing required field 'name'"),
        ("no_ir", {"name": "test"}, "Missing required field 'ir'"),
        ("empty_name", {"name": "", "ir": {}}, "must be a non-empty string"),
        ("bad_chars", {"name": "test/bad", "ir": {}}, "invalid characters"),
    ]

    for filename, content, expected_error in test_cases:
        file_path = workflow_manager.workflows_dir / f"{filename}.json"
        with open(file_path, "w") as f:
            json.dump(content, f)

        with pytest.raises(WorkflowValidationError) as exc_info:
            workflow_manager.load(filename)

        assert expected_error in str(exc_info.value)
```

### Test 3: Mixed valid and invalid workflows

```python
def test_list_all_returns_valid_skips_invalid(workflow_manager, sample_ir):
    """Test that list_all returns valid workflows and skips invalid ones."""
    # Save two valid workflows
    workflow_manager.save("valid1", sample_ir, "First valid workflow")
    workflow_manager.save("valid2", sample_ir, "Second valid workflow")

    # Create various invalid workflows
    invalid_workflows = [
        ("invalid1.json", {"no_name": True}),
        ("invalid2.json", {"name": "test"}),  # Missing ir
        ("invalid3.json", "not even json"),
    ]

    for filename, content in invalid_workflows:
        file_path = workflow_manager.workflows_dir / filename
        with open(file_path, "w") as f:
            if isinstance(content, str):
                f.write(content)
            else:
                json.dump(content, f)

    # List should return only valid workflows
    workflows = workflow_manager.list_all()

    assert len(workflows) == 2
    assert {w["name"] for w in workflows} == {"valid1", "valid2"}

    # Verify all workflows have required fields
    for workflow in workflows:
        assert "name" in workflow
        assert "ir" in workflow
        assert isinstance(workflow["name"], str)
        assert isinstance(workflow["ir"], dict)
```

### Test 4: Validate IR option

```python
def test_validate_ir_option(workflow_manager):
    """Test optional IR validation."""
    # Create workflow with invalid IR
    workflow_with_bad_ir = {
        "name": "bad-ir",
        "description": "Workflow with invalid IR",
        "ir": {
            # Missing required ir_version
            "nodes": []
        },
        "created_at": "2024-01-01T00:00:00Z",
        "version": "1.0.0"
    }

    file_path = workflow_manager.workflows_dir / "bad-ir.json"
    with open(file_path, "w") as f:
        json.dump(workflow_with_bad_ir, f)

    # Without IR validation, should load successfully
    workflow_manager.validate_ir_on_load = False
    workflow = workflow_manager.load("bad-ir")
    assert workflow["name"] == "bad-ir"

    # With IR validation, should fail
    workflow_manager.validate_ir_on_load = True
    with pytest.raises(WorkflowValidationError) as exc_info:
        workflow_manager.load("bad-ir")
    assert "Invalid IR" in str(exc_info.value)
```

## Edge Cases to Consider

### 1. Unicode in workflow names
```python
def test_unicode_workflow_names(workflow_manager):
    """Test handling of unicode characters in workflow names."""
    workflow = {
        "name": "测试-workflow-🚀",
        "ir": {"ir_version": "0.1.0", "nodes": []},
        "description": "Unicode test"
    }

    # Should handle unicode properly
    file_path = workflow_manager.workflows_dir / "unicode.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(workflow, f, ensure_ascii=False)

    workflows = workflow_manager.list_all()
    assert len(workflows) == 1
    assert workflows[0]["name"] == "测试-workflow-🚀"
```

### 2. Very large workflow files
```python
def test_large_workflow_handling(workflow_manager):
    """Test handling of very large workflow files."""
    # Create a workflow with many nodes
    large_workflow = {
        "name": "large",
        "ir": {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": f"node_{i}", "type": "echo"}
                for i in range(10000)
            ]
        }
    }

    file_path = workflow_manager.workflows_dir / "large.json"
    with open(file_path, "w") as f:
        json.dump(large_workflow, f)

    # Should handle large files
    workflows = workflow_manager.list_all()
    assert len(workflows) == 1
    assert len(workflows[0]["ir"]["nodes"]) == 10000
```

### 3. Symlinks and special files
```python
def test_skip_non_regular_files(workflow_manager):
    """Test that non-regular files are skipped."""
    import os

    # Create a symlink (if supported)
    if hasattr(os, 'symlink'):
        symlink_path = workflow_manager.workflows_dir / "symlink.json"
        try:
            os.symlink("/dev/null", symlink_path)
        except OSError:
            pytest.skip("Cannot create symlinks")

    # Create a directory with .json extension
    dir_path = workflow_manager.workflows_dir / "directory.json"
    dir_path.mkdir(exist_ok=True)

    # Should skip non-regular files
    workflows = workflow_manager.list_all()
    assert len(workflows) == 0
```

## Performance Considerations

### Benchmark validation overhead
```python
def test_validation_performance(workflow_manager, benchmark):
    """Benchmark validation overhead."""
    # Create a typical workflow
    workflow = {
        "name": "perf-test",
        "description": "Performance test workflow",
        "ir": {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": f"node_{i}", "type": "echo", "params": {"message": f"Test {i}"}}
                for i in range(100)
            ],
            "edges": [
                {"from": f"node_{i}", "to": f"node_{i+1}"}
                for i in range(99)
            ]
        },
        "created_at": "2024-01-01T00:00:00Z",
        "version": "1.0.0"
    }

    file_path = workflow_manager.workflows_dir / "perf-test.json"
    with open(file_path, "w") as f:
        json.dump(workflow, f)

    # Benchmark loading with validation
    result = benchmark(workflow_manager.load, "perf-test")
    assert result["name"] == "perf-test"

    # Validation should add < 5ms overhead for typical workflows
    assert benchmark.stats["mean"] < 0.005  # 5ms
```

## Rollback Plan

If validation causes issues in production:

1. **Quick disable**: Add environment variable to skip validation
```python
if os.getenv("PFLOW_SKIP_WORKFLOW_VALIDATION"):
    return data  # Skip validation
```

2. **Gradual rollout**: Start with warnings only, then enforce
```python
if os.getenv("PFLOW_VALIDATION_MODE") == "warn":
    # Log warnings but don't fail
    if validation_errors:
        logger.warning(f"Validation would fail: {validation_errors}")
    return data
```

3. **Recovery mode**: Add command to fix workflows
```bash
pflow repair-workflows --backup
```

## Checklist for Implementation

- [ ] Add `_validate_metadata_structure()` method
- [ ] Add `_load_and_validate_file()` method
- [ ] Update `list_all()` to use validation
- [ ] Update `load()` to use validation
- [ ] Fix WorkflowDiscoveryNode bug
- [ ] Add import for WorkflowValidationError
- [ ] Write comprehensive tests
- [ ] Test with existing workflows
- [ ] Update documentation
- [ ] Consider adding migration script
- [ ] Performance testing
- [ ] Add logging for debugging

## Common Mistakes to Avoid

1. **Don't forget the import**: Add `WorkflowValidationError` import in nodes.py
2. **Don't validate in context_builder**: It uses list_all() which already validates
3. **Don't break backward compatibility**: Ensure valid existing workflows still work
4. **Don't log sensitive data**: Don't include workflow content in error messages
5. **Don't forget edge cases**: Handle unicode, large files, symlinks
6. **Don't make it too strict**: Focus on required fields, not optional ones

## Questions for Reviewer

1. Should we validate IR by default or make it optional?
2. Should we add a migration script for old workflows?
3. Should we add metrics/telemetry for validation failures?
4. Should we cache validation results for performance?
5. What's the maximum acceptable file size for workflows?