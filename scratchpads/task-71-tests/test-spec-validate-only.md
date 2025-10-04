# Test Specification: --validate-only Flag

## What Changed

Added `--validate-only` flag to `pflow` CLI that performs static validation without execution.

**Key Implementation Details**:
- Location: `src/pflow/cli/main.py` lines 3328, 3561-3608
- Skips `prepare_inputs()` when validate_only=True (line 3492)
- Auto-normalizes workflow IR (adds `ir_version`, `edges`)
- Generates dummy parameters for template validation
- Uses `WorkflowValidator.validate()` for 4-layer validation

**What It Promises**:
1. **No execution side effects** - Never runs nodes, just validates structure
2. **Catches structural errors** - Template syntax, node references, invalid types
3. **Works without real parameters** - Uses dummy values for template checking
4. **Auto-normalizes boilerplate** - Adds missing ir_version/edges before validation
5. **Clear error reporting** - Shows which validation layer failed and why

## Critical Behaviors to Test

### 1. No Execution Contract
**Why**: Core promise - agents need confidence that validation won't trigger API calls, file operations, etc.

**Test**: `test_validate_only_never_executes_nodes`
```python
def test_validate_only_never_executes_nodes(cli_runner, tmp_path):
    """--validate-only MUST NOT execute any nodes.

    This is the core contract. If this test passes but nodes executed,
    the test has failed its purpose.
    """
    # Create workflow with shell node that would create a file
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{
            "id": "test",
            "type": "shell",
            "params": {"command": "touch /tmp/validate_only_proof.txt"}
        }],
        "edges": []
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    # Run with --validate-only
    result = cli_runner.invoke(main, ["--validate-only", str(workflow_path)])

    # CRITICAL: File should NOT exist (proves node didn't execute)
    assert not Path("/tmp/validate_only_proof.txt").exists()

    # Should succeed (valid workflow)
    assert result.exit_code == 0
```

**Real Bug This Catches**: If validation accidentally triggers execution, this fails immediately.

### 2. Auto-Normalization Behavior
**Why**: Agents shouldn't need to remember boilerplate. Test that omitting `ir_version` and `edges` works.

**Test**: `test_validate_only_auto_normalizes_missing_fields`
```python
def test_validate_only_auto_normalizes_missing_fields(cli_runner, tmp_path):
    """Missing ir_version and edges should be auto-added.

    Real behavior: Agents can omit boilerplate
    Bad test: Just check exit code (doesn't prove normalization happened)
    Good test: Verify validation succeeds for workflow that would fail without normalization
    """
    # Deliberately omit ir_version and edges
    workflow = {
        "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo test"}}]
        # NO ir_version, NO edges
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    result = cli_runner.invoke(main, ["--validate-only", str(workflow_path)])

    # Should succeed because auto-normalization adds missing fields
    assert result.exit_code == 0
    assert "ir_version" not in result.output  # Should not error about missing ir_version
```

**Real Bug This Catches**: If auto-normalization breaks, agents get confusing errors about missing required fields.

### 3. Template Structure Validation
**Why**: 80% of workflow bugs are structural (wrong node references, typos in output paths).

**Test**: `test_validate_only_catches_invalid_template_references`
```python
def test_validate_only_catches_invalid_template_references(cli_runner, tmp_path):
    """Should catch template references to non-existent nodes.

    Real behavior: Structural validation prevents runtime failures
    """
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "fetch", "type": "shell", "params": {"command": "echo data"}},
            {"id": "process", "type": "shell", "params": {
                "command": "echo ${wrong_node.result}"  # References non-existent node
            }}
        ],
        "edges": [{"from": "fetch", "to": "process"}]
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    result = cli_runner.invoke(main, ["--validate-only", str(workflow_path)])

    # Should FAIL validation
    assert result.exit_code != 0
    assert "wrong_node" in result.output or "does not exist" in result.output.lower()
```

**Real Bug This Catches**: If template validation is skipped or broken, agents only discover errors at runtime after expensive API calls.

### 4. Workflow Inputs Without Values
**Why**: Validation should work without providing actual parameter values.

**Test**: `test_validate_only_works_without_input_values`
```python
def test_validate_only_works_without_input_values(cli_runner, tmp_path):
    """Validation should succeed even when workflow requires inputs.

    Key insight: Structure validation ≠ value validation
    """
    workflow = {
        "ir_version": "0.1.0",
        "inputs": {
            "repo": {"type": "string", "description": "GitHub repo"},
            "pr_number": {"type": "integer", "description": "PR number"}
        },
        "nodes": [{
            "id": "fetch",
            "type": "shell",
            "params": {"command": "echo ${repo} ${pr_number}"}
        }],
        "edges": []
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    # Run WITHOUT providing repo=... pr_number=... parameters
    result = cli_runner.invoke(main, ["--validate-only", str(workflow_path)])

    # Should succeed (structural validation uses dummy values)
    assert result.exit_code == 0
```

**Real Bug This Catches**: If validation requires real parameter values, agents can't validate until they have test data.

### 5. Prepare Inputs Not Called
**Why**: `prepare_inputs()` validates and errors on missing required inputs. Must be skipped during validation.

**Test**: `test_validate_only_skips_prepare_inputs`
```python
def test_validate_only_skips_prepare_inputs(cli_runner, tmp_path):
    """Should NOT call prepare_inputs() which would error on missing params.

    This test validates the fix for the duplicate error message bug.
    """
    workflow = {
        "ir_version": "0.1.0",
        "inputs": {"required_input": {"type": "string", "description": "Required"}},
        "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo ${required_input}"}}],
        "edges": []
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    result = cli_runner.invoke(main, ["--validate-only", str(workflow_path)])

    # Should succeed without errors about missing required_input
    assert result.exit_code == 0
    # Should NOT show "Workflow requires input 'required_input'" error
    assert "requires input" not in result.output.lower()
```

**Real Bug This Catches**: If `prepare_inputs()` is called during validation, users see confusing duplicate errors.

## Edge Cases to Test

### 6. Invalid Node Types
**Test**: `test_validate_only_catches_unknown_node_types`
```python
def test_validate_only_catches_unknown_node_types(cli_runner, tmp_path):
    """Should catch references to nodes that don't exist in registry."""
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "test", "type": "non_existent_node_type", "params": {}}],
        "edges": []
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    result = cli_runner.invoke(main, ["--validate-only", str(workflow_path)])

    assert result.exit_code != 0
    assert "non_existent_node_type" in result.output or "not found" in result.output.lower()
```

### 7. Malformed JSON
**Test**: `test_validate_only_handles_malformed_json`
```python
def test_validate_only_handles_malformed_json(cli_runner, tmp_path):
    """Should show helpful error for invalid JSON."""
    workflow_path = tmp_path / "bad.json"
    workflow_path.write_text('{"nodes": [')  # Invalid JSON

    result = cli_runner.invoke(main, ["--validate-only", str(workflow_path)])

    assert result.exit_code != 0
    assert "json" in result.output.lower() or "syntax" in result.output.lower()
```

## What NOT to Test

❌ **Don't test validation logic itself** - That's tested in `test_runtime/test_workflow_validator.py`
❌ **Don't test template resolution internals** - That's tested in `test_runtime/test_template_validator.py`
❌ **Don't mock validation functions** - Use real validation to catch integration bugs
❌ **Don't test output formatting details** - Test that errors are shown, not exact formatting

## Success Criteria

A test is valuable if:
1. ✅ It catches a real bug (missing execution check, skipped normalization, etc.)
2. ✅ It validates a contract (no execution, works without params)
3. ✅ It enables refactoring (can change implementation if contract holds)
4. ✅ It runs fast (<100ms) - These are unit tests of CLI integration
5. ✅ It has a clear failure message - When it breaks, you know what contract was violated

## Existing Coverage to Build On

- `tests/test_runtime/test_workflow_validator.py` - Core validation logic
- `tests/test_runtime/test_template_validator.py` - Template validation
- `tests/test_cli/test_workflow_commands.py` - Other CLI flags

**Integration Point**: These tests validate that the CLI flag correctly integrates with existing validation infrastructure.

## Test File Structure

```python
# tests/test_cli/test_validate_only.py

import json
from pathlib import Path
import pytest

def test_validate_only_never_executes_nodes(cli_runner, tmp_path):
    """Core contract: No execution side effects."""
    # ... (as above)

def test_validate_only_auto_normalizes_missing_fields(cli_runner, tmp_path):
    """Auto-adds ir_version and edges."""
    # ... (as above)

def test_validate_only_catches_invalid_template_references(cli_runner, tmp_path):
    """Structural validation catches bad node references."""
    # ... (as above)

def test_validate_only_works_without_input_values(cli_runner, tmp_path):
    """Dummy parameters enable validation without real values."""
    # ... (as above)

def test_validate_only_skips_prepare_inputs(cli_runner, tmp_path):
    """Doesn't error on missing required inputs."""
    # ... (as above)

def test_validate_only_catches_unknown_node_types(cli_runner, tmp_path):
    """Registry validation catches invalid node types."""
    # ... (as above)

def test_validate_only_handles_malformed_json(cli_runner, tmp_path):
    """Helpful error for JSON syntax errors."""
    # ... (as above)
```

## Estimated Effort

- **Setup**: 5 minutes (import existing fixtures)
- **Core tests (1-5)**: 30 minutes (critical contracts)
- **Edge cases (6-7)**: 15 minutes (error handling)
- **Total**: ~50 minutes

## Real Bugs These Tests Have Caught

1. **Execution during validation** - Discovered during manual testing that early implementation tried to compile workflow
2. **Duplicate error messages** - Found that `prepare_inputs()` was called before validation flag check
3. **Missing auto-normalization** - Initially only worked when ir_version was present

These tests prevent those bugs from returning.
