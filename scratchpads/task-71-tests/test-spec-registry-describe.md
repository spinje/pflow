# Test Specification: `pflow registry describe` Command

## What Changed

Added `pflow registry describe` command to get detailed specifications for specific nodes.

**Key Implementation Details**:
- Location: `src/pflow/cli/registry.py` lines 760-871
- Uses `build_planning_context()` directly (not through planning nodes)
- Accepts multiple node IDs at once
- Returns full interface specifications (inputs, outputs, descriptions)
- Includes MCP tool normalization for easy copy-paste from `registry list`

**What It Promises**:
1. **Complete node specifications** - All inputs, outputs, types, descriptions
2. **Multi-node support** - Describe multiple nodes in one command
3. **Name normalization** - Handles various node name formats (hyphens, underscores, MCP prefixes)
4. **Clear error handling** - Helpful messages for unknown nodes
5. **Consistent with planner** - Same context used by workflow generator

## Critical Behaviors to Test

### 1. Single Node Description
**Why**: Core functionality - must show complete node specification.

**Test**: `test_registry_describe_single_node`
```python
def test_registry_describe_single_node(cli_runner):
    """Should show complete specification for a single node.

    Real behavior: Uses build_planning_context() to get full interface
    Bad test: Mock the registry and assert function called
    Good test: Verify actual output contains expected fields
    """
    # Use a known platform node that should always exist
    result = cli_runner.invoke(["registry", "describe", "shell"])

    assert result.exit_code == 0

    # Should show node name
    assert "shell" in result.output.lower()

    # Should show description
    assert "description" in result.output.lower() or "execute" in result.output.lower()

    # Should show inputs section
    assert "input" in result.output.lower() or "param" in result.output.lower()

    # Should show command parameter (shell node has 'command' input)
    assert "command" in result.output.lower()
```

**Real Bug This Catches**: If build_planning_context integration breaks or output formatting fails.

### 2. Multiple Nodes Description
**Why**: Agents want to compare multiple nodes at once.

**Test**: `test_registry_describe_multiple_nodes`
```python
def test_registry_describe_multiple_nodes(cli_runner):
    """Should show specifications for multiple nodes in one command."""
    result = cli_runner.invoke(["registry", "describe", "shell", "read-file"])

    assert result.exit_code == 0

    # Should show both nodes
    assert "shell" in result.output.lower()
    assert "read-file" in result.output.lower() or "read_file" in result.output.lower()

    # Should have clear separation between nodes
    # (exact format depends on implementation, but should be readable)
```

**Real Bug This Catches**: If loop over node IDs breaks or output gets jumbled.

### 3. Node Name Normalization
**Why**: Critical for UX - agents copy names from `registry list` which uses hyphens.

**Test**: `test_registry_describe_normalizes_node_names`
```python
def test_registry_describe_normalizes_node_names(cli_runner):
    """Should handle different node name formats (hyphens vs underscores).

    Registry stores: read_file
    Users type: read-file (from registry list output)
    Should work: both formats
    """
    # Try hyphen format (what users see in registry list)
    result_hyphen = cli_runner.invoke(["registry", "describe", "read-file"])

    # Try underscore format (internal storage)
    result_underscore = cli_runner.invoke(["registry", "describe", "read_file"])

    # Both should succeed
    assert result_hyphen.exit_code == 0
    assert result_underscore.exit_code == 0

    # Both should show the same node
    assert "read" in result_hyphen.output.lower()
    assert "read" in result_underscore.output.lower()
```

**Real Bug This Catches**: If normalization from task 71 isn't applied to describe command.

### 4. MCP Tool Name Handling
**Why**: MCP tools have complex names that need special normalization.

**Test**: `test_registry_describe_mcp_tool_normalization`
```python
def test_registry_describe_mcp_tool_normalization(cli_runner, tmp_path):
    """Should handle MCP tool name formats.

    Registry stores: mcp-server-composio-TOOL_NAME
    List shows: TOOL-NAME (hyphens for readability)
    Describe should accept: both formats
    """
    # This test requires an MCP server to be configured
    # For testing, we can mock the registry to include an MCP tool

    # Setup: Create a mock registry with MCP tool
    home_pflow = tmp_path / ".pflow"
    home_pflow.mkdir()

    registry_data = {
        "nodes": {
            "mcp-slack-composio-SEND_MESSAGE": {
                "module": "pflow.nodes.mcp.mcp_node",
                "class_name": "MCPNode",
                "metadata": {
                    "description": "Send Slack message",
                    "inputs": {"message": {"type": "string"}},
                    "outputs": {"result": {"type": "object"}}
                }
            }
        }
    }

    (home_pflow / "registry.json").write_text(json.dumps(registry_data))

    # Try both formats
    result_hyphens = cli_runner.invoke(
        ["registry", "describe", "SEND-MESSAGE"],
        env={"HOME": str(tmp_path)}
    )

    result_underscores = cli_runner.invoke(
        ["registry", "describe", "SEND_MESSAGE"],
        env={"HOME": str(tmp_path)}
    )

    # At least one should succeed (depending on normalization strategy)
    # The key is that users shouldn't have to remember the exact format
    assert result_hyphens.exit_code == 0 or result_underscores.exit_code == 0

    # Successful one should show the node
    successful_output = result_hyphens.output if result_hyphens.exit_code == 0 else result_underscores.output
    assert "send" in successful_output.lower() or "message" in successful_output.lower()
```

**Real Bug This Catches**: If MCP normalization from test_registry_normalization.py isn't applied here.

### 5. Unknown Node Error
**Why**: Must give helpful feedback when node doesn't exist.

**Test**: `test_registry_describe_unknown_node`
```python
def test_registry_describe_unknown_node(cli_runner):
    """Should show helpful error for unknown nodes."""
    result = cli_runner.invoke(["registry", "describe", "nonexistent-node"])

    assert result.exit_code != 0
    assert "not found" in result.output.lower() or "unknown" in result.output.lower()
    assert "nonexistent-node" in result.output
```

**Real Bug This Catches**: If error handling swallows helpful context or crashes.

### 6. Mixed Valid and Invalid Nodes
**Why**: Partial success should be handled gracefully.

**Test**: `test_registry_describe_mixed_valid_invalid`
```python
def test_registry_describe_mixed_valid_invalid(cli_runner):
    """Should handle mix of valid and invalid node names.

    Options:
    1. Show valid nodes and error for invalid
    2. Fail fast on first invalid
    3. Show what was found and what wasn't

    Test validates chosen behavior is consistent
    """
    result = cli_runner.invoke(["registry", "describe", "shell", "nonexistent", "read-file"])

    # Should show some indication of partial success/failure
    # Exact behavior depends on implementation choice
    # At minimum: should not crash silently

    # Verify shell info appears
    if result.exit_code == 0:
        # Partial success approach
        assert "shell" in result.output.lower()
        assert "nonexistent" in result.output  # Mentioned as not found
    else:
        # Fail fast approach
        assert "nonexistent" in result.output or "not found" in result.output.lower()
```

**Real Bug This Catches**: If error handling doesn't account for mixed inputs.

### 7. No Arguments Error
**Why**: Command requires at least one node ID.

**Test**: `test_registry_describe_no_arguments`
```python
def test_registry_describe_no_arguments(cli_runner):
    """Should show helpful error when no node IDs provided."""
    result = cli_runner.invoke(["registry", "describe"])

    assert result.exit_code != 0
    # Should show usage help
    assert "usage" in result.output.lower() or "describe" in result.output.lower()
```

**Real Bug This Catches**: If Click argument handling doesn't validate required parameters.

## Edge Cases to Test

### 8. Node With Complex Interface
**Test**: `test_registry_describe_complex_node_interface`
```python
def test_registry_describe_complex_node_interface(cli_runner):
    """Should handle nodes with complex input/output schemas.

    Tests that nested types, optional fields, etc. are displayed
    """
    # Use a node known to have complex interface (like llm node)
    result = cli_runner.invoke(["registry", "describe", "llm"])

    assert result.exit_code == 0

    # Should show the node
    assert "llm" in result.output.lower()

    # Should show inputs (llm has prompt, model, etc.)
    assert "prompt" in result.output.lower()

    # Output should be readable (not truncated or mangled)
```

### 9. Output Format Consistency
**Test**: `test_registry_describe_output_format`
```python
def test_registry_describe_output_format_consistency(cli_runner):
    """Output should be consistently formatted across nodes.

    Validates that describe output matches planner context format
    """
    result = cli_runner.invoke(["registry", "describe", "shell", "llm"])

    assert result.exit_code == 0

    # Both nodes should have similar structure
    # (Headers, descriptions, inputs, outputs sections)

    # Count sections - should have at least description and inputs for each
    # Exact validation depends on output format
```

## What NOT to Test

❌ **Don't test build_planning_context() internals** - That's tested in `test_planning/`
❌ **Don't test registry loading** - That's tested in `test_registry/`
❌ **Don't test metadata extraction** - That's tested in `test_registry/test_metadata_extractor.py`
❌ **Don't test exact output formatting** - Test that key info appears, not exact layout

## Success Criteria

A test is valuable if:
1. ✅ Validates CLI-to-context-builder integration
2. ✅ Tests normalization works for all name formats
3. ✅ Verifies error handling for unknown nodes
4. ✅ Ensures output contains required information
5. ✅ Fast execution (<100ms per test)

## Existing Coverage to Build On

- `tests/test_cli/test_registry_normalization.py` - Name normalization logic (comprehensive!)
- `tests/test_planning/test_context_builder_*.py` - Context building logic
- Focus on CLI command behavior, not underlying functions

## Test File Structure

```python
# tests/test_cli/test_registry_describe.py

import json
import pytest

def test_registry_describe_single_node(cli_runner):
    """Shows complete node specification."""
    # ...

def test_registry_describe_multiple_nodes(cli_runner):
    """Handles multiple node IDs."""
    # ...

def test_registry_describe_normalizes_node_names(cli_runner):
    """Accepts hyphen and underscore formats."""
    # ...

def test_registry_describe_mcp_tool_normalization(cli_runner, tmp_path):
    """Handles MCP tool name formats."""
    # ...

def test_registry_describe_unknown_node(cli_runner):
    """Helpful error for unknown nodes."""
    # ...

def test_registry_describe_mixed_valid_invalid(cli_runner):
    """Handles mix of valid and invalid inputs."""
    # ...

def test_registry_describe_no_arguments(cli_runner):
    """Error when no node IDs provided."""
    # ...

def test_registry_describe_complex_node_interface(cli_runner):
    """Displays complex interfaces correctly."""
    # ...

def test_registry_describe_output_format_consistency(cli_runner):
    """Consistent format across nodes."""
    # ...
```

## Estimated Effort

- **Setup and basic tests (1-3)**: 30 minutes
- **Normalization tests (4)**: 20 minutes (reuse patterns from test_registry_normalization.py)
- **Error handling (5-7)**: 25 minutes
- **Edge cases (8-9)**: 20 minutes
- **Total**: ~1.5 hours

## Real Bugs These Tests Prevent

1. **Name normalization missing** - Users copy from `registry list` but describe doesn't normalize
2. **MCP tool names unsupported** - Complex MCP names break describe command
3. **Partial failure silent** - Mix of valid/invalid nodes fails silently
4. **Incomplete output** - Important fields missing from description

These tests ensure describe command works seamlessly with the rest of the registry system.
