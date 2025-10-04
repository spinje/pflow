# Test Specification: `pflow workflow save` Command

## What Changed

Added `pflow workflow save` command to save draft workflows to the global library.

**Key Implementation Details**:
- Location: `src/pflow/cli/commands/workflow.py` lines 301-453
- Auto-normalizes IR before saving (adds `ir_version`, `edges`)
- Validates workflow structure before saving
- Optional metadata generation with `--generate-metadata` flag
- Optional draft deletion with `--delete-draft` flag
- Strict workflow name validation (line 282: `^[a-z0-9-]+$`)
- Reserved names blocking (should be added per code review)
- Safety checks for file deletion (only .pflow/workflows/)

**What It Promises**:
1. **Atomic save operation** - Either saves completely or fails cleanly
2. **Validation before save** - Never saves invalid workflows
3. **Auto-normalization** - Adds missing boilerplate fields
4. **Safe file deletion** - Only deletes from .pflow/workflows/ directories
5. **Name validation** - Prevents invalid or reserved workflow names

## Critical Behaviors to Test

### 1. Save Success Path
**Why**: Core functionality - must save valid workflows correctly.

**Test**: `test_workflow_save_basic_success`
```python
def test_workflow_save_basic_success(cli_runner, tmp_path):
    """Valid workflow should save to global library.

    Real behavior: Creates workflow file in ~/.pflow/workflows/
    Bad test: Mock WorkflowManager and assert it was called
    Good test: Verify actual file exists with correct content
    """
    # Setup
    home_pflow = tmp_path / ".pflow" / "workflows"
    home_pflow.mkdir(parents=True)

    draft = tmp_path / "draft.json"
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}],
        "edges": []
    }
    draft.write_text(json.dumps(workflow))

    # Run command
    result = cli_runner.invoke(
        workflow_cmd,
        ["save", str(draft), "my-workflow", "Test workflow"],
        env={"HOME": str(tmp_path)}
    )

    # Verify real behavior
    assert result.exit_code == 0
    saved_file = home_pflow / "my-workflow.json"
    assert saved_file.exists(), "Workflow file should be created"

    # Verify content is correct
    saved_data = json.loads(saved_file.read_text())
    assert saved_data["nodes"][0]["id"] == "test"
```

**Real Bug This Catches**: If save operation fails silently or saves to wrong location.

### 2. Auto-Normalization Before Save
**Why**: Agents shouldn't need to add boilerplate manually.

**Test**: `test_workflow_save_auto_normalizes`
```python
def test_workflow_save_auto_normalizes(cli_runner, tmp_path):
    """Missing ir_version and edges should be auto-added.

    Key insight: Same as --validate-only, saves should auto-normalize
    """
    home_pflow = tmp_path / ".pflow" / "workflows"
    home_pflow.mkdir(parents=True)

    draft = tmp_path / "draft.json"
    workflow = {
        "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}]
        # NO ir_version, NO edges
    }
    draft.write_text(json.dumps(workflow))

    result = cli_runner.invoke(
        workflow_cmd,
        ["save", str(draft), "test-workflow", "Test"],
        env={"HOME": str(tmp_path)}
    )

    assert result.exit_code == 0

    # Verify saved file has normalized fields
    saved_file = home_pflow / "test-workflow.json"
    saved_data = json.loads(saved_file.read_text())
    assert "ir_version" in saved_data
    assert "edges" in saved_data
```

**Real Bug This Catches**: If normalization is skipped, saved workflows fail validation when loaded.

### 3. Validation Before Save
**Why**: Must never save invalid workflows to library.

**Test**: `test_workflow_save_rejects_invalid_workflow`
```python
def test_workflow_save_rejects_invalid_workflow(cli_runner, tmp_path):
    """Invalid workflows should be rejected before saving.

    Critical contract: Library should only contain valid workflows
    """
    home_pflow = tmp_path / ".pflow" / "workflows"
    home_pflow.mkdir(parents=True)

    draft = tmp_path / "bad.json"
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "test", "type": "non_existent_type", "params": {}}],
        "edges": []
    }
    draft.write_text(json.dumps(workflow))

    result = cli_runner.invoke(
        workflow_cmd,
        ["save", str(draft), "bad-workflow", "Test"],
        env={"HOME": str(tmp_path)}
    )

    # Should FAIL
    assert result.exit_code != 0

    # Should NOT create file
    saved_file = home_pflow / "bad-workflow.json"
    assert not saved_file.exists(), "Invalid workflow should not be saved"
```

**Real Bug This Catches**: If validation is skipped or broken, invalid workflows pollute library.

### 4. Name Validation
**Why**: Prevents filesystem issues and reserved name conflicts.

**Test**: `test_workflow_save_validates_name_format`
```python
def test_workflow_save_validates_name_format(cli_runner, tmp_path):
    """Workflow names must match allowed pattern.

    After fix: ^[a-z0-9]+(?:-[a-z0-9]+)*$
    (lowercase, alphanumeric, single hyphens, must start/end with alphanumeric)
    """
    home_pflow = tmp_path / ".pflow" / "workflows"
    home_pflow.mkdir(parents=True)

    draft = tmp_path / "test.json"
    workflow = {"ir_version": "0.1.0", "nodes": [], "edges": []}
    draft.write_text(json.dumps(workflow))

    invalid_names = [
        "My-Workflow",  # Uppercase
        "-myworkflow",  # Starts with hyphen
        "my--workflow",  # Double hyphen
        "workflow_name",  # Underscore
        "my.workflow",  # Dot
        "",  # Empty
    ]

    for invalid_name in invalid_names:
        result = cli_runner.invoke(
            workflow_cmd,
            ["save", str(draft), invalid_name, "Test"],
            env={"HOME": str(tmp_path)}
        )

        assert result.exit_code != 0, f"Should reject invalid name: {invalid_name}"
        assert "name" in result.output.lower() or "invalid" in result.output.lower()

    # Valid names should work
    valid_names = ["myworkflow", "my-workflow", "workflow-123", "test1"]
    for valid_name in valid_names:
        result = cli_runner.invoke(
            workflow_cmd,
            ["save", str(draft), valid_name, "Test"],
            env={"HOME": str(tmp_path)}
        )

        assert result.exit_code == 0, f"Should accept valid name: {valid_name}"
```

**Real Bug This Catches**: If regex is weak (current bug), names like `-test` or `my--workflow` get saved.

### 5. Reserved Names Protection
**Why**: Prevents conflicts with system workflows or commands.

**Test**: `test_workflow_save_blocks_reserved_names`
```python
def test_workflow_save_blocks_reserved_names(cli_runner, tmp_path):
    """Should reject reserved workflow names."""
    home_pflow = tmp_path / ".pflow" / "workflows"
    home_pflow.mkdir(parents=True)

    draft = tmp_path / "test.json"
    workflow = {"ir_version": "0.1.0", "nodes": [], "edges": []}
    draft.write_text(json.dumps(workflow))

    reserved_names = ["null", "undefined", "none", "test", "settings", "registry", "workflow", "mcp"]

    for reserved in reserved_names:
        result = cli_runner.invoke(
            workflow_cmd,
            ["save", str(draft), reserved, "Test"],
            env={"HOME": str(tmp_path)}
        )

        assert result.exit_code != 0, f"Should reject reserved name: {reserved}"
        assert "reserved" in result.output.lower()
```

**Real Bug This Catches**: If reserved names aren't blocked, users create workflows that conflict with commands.

### 6. Delete Draft Flag
**Why**: Agents want to clean up after successful save.

**Test**: `test_workflow_save_delete_draft_flag`
```python
def test_workflow_save_delete_draft_flag(cli_runner, tmp_path):
    """--delete-draft should remove source file after successful save."""
    home_pflow = tmp_path / ".pflow" / "workflows"
    home_pflow.mkdir(parents=True)

    # Create draft in safe location
    draft_dir = tmp_path / ".pflow" / "workflows"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft = draft_dir / "draft.json"

    workflow = {"ir_version": "0.1.0", "nodes": [], "edges": []}
    draft.write_text(json.dumps(workflow))

    assert draft.exists(), "Draft should exist before save"

    result = cli_runner.invoke(
        workflow_cmd,
        ["save", str(draft), "saved-workflow", "Test", "--delete-draft"],
        env={"HOME": str(tmp_path)}
    )

    assert result.exit_code == 0
    assert not draft.exists(), "Draft should be deleted after successful save"

    # Saved file should exist
    saved_file = home_pflow / "saved-workflow.json"
    assert saved_file.exists()
```

**Real Bug This Catches**: If deletion flag is ignored or fails silently.

### 7. Delete Draft Safety
**Why**: Must not delete files outside .pflow/workflows/ directories.

**Test**: `test_workflow_save_delete_draft_safety`
```python
def test_workflow_save_delete_draft_safety(cli_runner, tmp_path):
    """Should refuse to delete files outside .pflow/workflows/ for safety.

    Critical: Prevents accidental deletion of user files
    """
    home_pflow = tmp_path / ".pflow" / "workflows"
    home_pflow.mkdir(parents=True)

    # Create draft in unsafe location (project root)
    unsafe_draft = tmp_path / "important-file.json"
    workflow = {"ir_version": "0.1.0", "nodes": [], "edges": []}
    unsafe_draft.write_text(json.dumps(workflow))

    result = cli_runner.invoke(
        workflow_cmd,
        ["save", str(unsafe_draft), "test-workflow", "Test", "--delete-draft"],
        env={"HOME": str(tmp_path)}
    )

    # Should save successfully
    assert result.exit_code == 0

    # But should NOT delete the unsafe file
    assert unsafe_draft.exists(), "File outside .pflow/workflows/ should NOT be deleted"

    # Should show warning
    assert "not deleting" in result.output.lower() or "warning" in result.output.lower()
```

**Real Bug This Catches**: If path safety check uses `in parts` (current bug), could match unintended paths.

### 8. Generate Metadata Flag
**Why**: Enables workflow discovery by future agents.

**Test**: `test_workflow_save_generate_metadata_flag`
```python
def test_workflow_save_generate_metadata_flag(cli_runner, tmp_path, monkeypatch):
    """--generate-metadata should add rich metadata to saved workflow.

    Note: Requires LLM mock to avoid API calls in tests
    """
    home_pflow = tmp_path / ".pflow" / "workflows"
    home_pflow.mkdir(parents=True)

    draft = tmp_path / "draft.json"
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "fetch", "type": "shell", "params": {"command": "curl https://api.github.com"}}],
        "edges": []
    }
    draft.write_text(json.dumps(workflow))

    # Mock LLM response for metadata generation
    def mock_llm_call(*args, **kwargs):
        return type('Response', (), {
            'parsed': type('Parsed', (), {
                'description': 'Fetches data from GitHub API',
                'capabilities': ['API calls', 'Data retrieval'],
                'use_cases': ['GitHub integration']
            })()
        })()

    monkeypatch.setattr("pflow.planning.nodes.MetadataGenerationNode.exec",
                       lambda self, shared: shared.update({
                           'metadata': {
                               'description': 'Test metadata',
                               'capabilities': ['test']
                           }
                       }))

    result = cli_runner.invoke(
        workflow_cmd,
        ["save", str(draft), "test-workflow", "Test", "--generate-metadata"],
        env={"HOME": str(tmp_path)}
    )

    assert result.exit_code == 0

    # Verify metadata was added
    saved_file = home_pflow / "test-workflow.json"
    saved_data = json.loads(saved_file.read_text())
    assert "metadata" in saved_data, "Should have metadata field"
```

**Real Bug This Catches**: If metadata generation is skipped or LLM integration breaks.

## Edge Cases to Test

### 9. Overwrite Existing Workflow
**Test**: `test_workflow_save_overwrites_existing`
```python
def test_workflow_save_overwrites_existing(cli_runner, tmp_path):
    """Saving with existing name should overwrite (after code review fix)."""
    home_pflow = tmp_path / ".pflow" / "workflows"
    home_pflow.mkdir(parents=True)

    # Create existing workflow
    existing = home_pflow / "my-workflow.json"
    existing.write_text(json.dumps({"ir_version": "0.1.0", "nodes": [], "edges": []}))

    # Save new version
    draft = tmp_path / "draft.json"
    new_workflow = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "new", "type": "shell", "params": {"command": "echo new"}}],
        "edges": []
    }
    draft.write_text(json.dumps(new_workflow))

    result = cli_runner.invoke(
        workflow_cmd,
        ["save", str(draft), "my-workflow", "Updated workflow"],
        env={"HOME": str(tmp_path)}
    )

    assert result.exit_code == 0

    # Verify overwrite happened
    saved_data = json.loads(existing.read_text())
    assert saved_data["nodes"][0]["id"] == "new"
```

### 10. Nonexistent Draft File
**Test**: `test_workflow_save_handles_missing_draft`
```python
def test_workflow_save_handles_missing_draft(cli_runner, tmp_path):
    """Should show helpful error for nonexistent draft file."""
    result = cli_runner.invoke(
        workflow_cmd,
        ["save", "/nonexistent/draft.json", "test", "Test"],
        env={"HOME": str(tmp_path)}
    )

    assert result.exit_code != 0
    assert "not found" in result.output.lower() or "does not exist" in result.output.lower()
```

## What NOT to Test

❌ **Don't test WorkflowManager internals** - That's tested in `test_core/test_workflow_manager.py`
❌ **Don't test validation logic** - That's tested in `test_runtime/test_workflow_validator.py`
❌ **Don't mock file operations** - Use real tmp_path to catch filesystem bugs
❌ **Don't test exact error message wording** - Test that appropriate error is shown

## Success Criteria

A test is valuable if:
1. ✅ Validates atomic save contract (all-or-nothing)
2. ✅ Catches safety issues (deletion, overwrite, validation)
3. ✅ Enables refactoring (can change implementation details)
4. ✅ Tests real behavior (actual files created/deleted)
5. ✅ Clear failure indication (which contract was violated)

## Existing Coverage to Build On

- `tests/test_cli/test_workflow_save.py` - Basic workflow save tests (already exists!)
- `tests/test_core/test_workflow_manager.py` - WorkflowManager.save() logic
- Need to check what's already tested to avoid duplication

## Test File Structure

```python
# tests/test_cli/test_workflow_save_cli.py

import json
from pathlib import Path
import pytest

def test_workflow_save_basic_success(cli_runner, tmp_path):
    """Valid workflow saves to library."""
    # ...

def test_workflow_save_auto_normalizes(cli_runner, tmp_path):
    """Auto-adds missing fields."""
    # ...

def test_workflow_save_rejects_invalid_workflow(cli_runner, tmp_path):
    """Never saves invalid workflows."""
    # ...

def test_workflow_save_validates_name_format(cli_runner, tmp_path):
    """Enforces name validation rules."""
    # ...

def test_workflow_save_blocks_reserved_names(cli_runner, tmp_path):
    """Prevents reserved name conflicts."""
    # ...

def test_workflow_save_delete_draft_flag(cli_runner, tmp_path):
    """--delete-draft removes source."""
    # ...

def test_workflow_save_delete_draft_safety(cli_runner, tmp_path):
    """Only deletes from safe locations."""
    # ...

def test_workflow_save_generate_metadata_flag(cli_runner, tmp_path, monkeypatch):
    """--generate-metadata adds discovery metadata."""
    # ...

def test_workflow_save_overwrites_existing(cli_runner, tmp_path):
    """Overwrites existing workflows."""
    # ...

def test_workflow_save_handles_missing_draft(cli_runner, tmp_path):
    """Helpful error for missing files."""
    # ...
```

## Estimated Effort

- **Check existing tests**: 10 minutes
- **Core save tests (1-3)**: 20 minutes
- **Name validation (4-5)**: 20 minutes
- **Flags (6-8)**: 30 minutes
- **Edge cases (9-10)**: 15 minutes
- **Total**: ~1.5 hours

## Real Bugs These Tests Prevent

1. **Weak regex allowing `-name`** - Discovered in code review
2. **Path safety using `in parts`** - Discovered in code review, could delete wrong files
3. **Missing reserved names check** - Prevents `pflow test` conflict
4. **Validation skipped** - Would save broken workflows to library

These tests make the save command production-ready.
