# Node Implementation Reference

This document provides common patterns and best practices for implementing nodes in pflow. All nodes should follow these patterns for consistency and proper integration with the pflow architecture.

## Prerequisites

Before implementing any node, you should understand:
- [Simple Node Architecture](../features/simple-nodes.md) - Single-purpose node design philosophy
- [Shared Store Pattern](../core-concepts/shared-store.md) - Inter-node data flow and communication
- [Node Metadata Schema](../core-concepts/schemas.md#node-metadata-schema) - Interface format specification

## Common Implementation Patterns

### Check Shared Store First Pattern

All nodes should check the shared store for input values before falling back to parameters. This enables dynamic data flow between nodes:

```python
def prep(self, shared):
    # Check shared store first (dynamic), then params (static)
    value = shared.get("key") or self.params.get("key")
    if not value:
        raise ValueError("key must be in shared store or params")
    return value
```

This pattern allows nodes to:
- Accept dynamic input from previous nodes via shared store
- Fall back to static CLI parameters when run independently
- Provide clear error messages when required inputs are missing

### Node Lifecycle Implementation

All nodes inherit from `pocketflow.BaseNode` (or `pocketflow.Node`) and implement the three-phase lifecycle:

```python
class MyNode(BaseNode):  # or Node
    """Brief description of what this node does.

    Interface:
    - Reads: shared["input_key"] (required), shared["optional_key"] (optional)
    - Writes: shared["output_key"] on success, shared["error"] on failure
    - Params: param1, param2 (as fallbacks if not in shared)
    - Actions: default (success), error (failure)
    """

    def prep(self, shared):
        """Prepare phase: gather inputs from shared store and params."""
        # Implement shared store first pattern
        pass

    def exec(self, prep_res):
        """Execute phase: perform the node's core functionality."""
        # Main business logic here
        pass

    def post(self, shared, prep_res, exec_res):
        """Post phase: write results to shared store."""
        shared["output_key"] = exec_res
        return "default"  # transition action
```

### Error Handling

Nodes should provide clear, actionable error messages:

```python
def prep(self, shared):
    required_field = shared.get("field") or self.params.get("field")
    if not required_field:
        raise ValueError("field must be in shared store or params")

    # Validate input format
    if not isinstance(required_field, str):
        raise TypeError(f"field must be string, got {type(required_field)}")

    return required_field
```

### Testing Pattern

All nodes should have comprehensive tests:

```python
def test_node_basic():
    node = MyNode()
    node.set_params({"param1": "value"})

    shared = {"input_key": "test_input"}
    node.run(shared)

    assert "output_key" in shared
    assert shared["output_key"] == expected_output

def test_node_shared_store_priority():
    """Test that shared store values take precedence over params."""
    node = MyNode()
    node.set_params({"field": "param_value"})

    shared = {"field": "shared_value"}
    result = node.prep(shared)

    assert result == "shared_value"  # shared store wins
```

## Interface Format Details

The Interface section in node docstrings follows a specific format:

### Complete Example

```python
"""
Read and process configuration files.

This node reads YAML or JSON configuration files and validates
them against a schema before making them available to other nodes.

Interface:
- Reads: shared["config_path"] (required), shared["schema_path"] (optional)
- Writes: shared["config"] on success, shared["validation_error"] on failure
- Params: config_path, schema_path, strict_mode (as fallbacks if not in shared)
- Actions: default (success), invalid (validation failed), missing (file not found)

Performance Note: Large config files (>10MB) may cause slowdowns.
Security Note: Config files can contain sensitive data - handle with care.
"""
```

### Format Rules

1. **Reads line**: Lists all shared store keys the node reads
   - Format: `shared["key"]` with optional `(required)` or `(optional)` modifier
   - Multiple keys separated by commas

2. **Writes line**: Lists all shared store keys the node writes
   - Can include conditions like `on success` or `on failure`
   - Multiple outputs separated by commas

3. **Params line**: Lists node parameters (set via `node.set_params()`)
   - These serve as fallbacks when values aren't in the shared store
   - Always includes the note "(as fallbacks if not in shared)"

4. **Actions line**: Lists transition strings the node can return
   - Format: `action_name (description)`
   - Default action should always be included

### Parameter Priority Pattern

Parameters can come from either the shared store OR node params, with shared store taking priority:

```python
def prep(self, shared):
    # Shared store value takes precedence
    value = shared.get("key") or self.params.get("key")
    if not value:
        raise ValueError("key must be in shared store or params")
```

## See Also

- [Simple Nodes Pattern](../features/simple-nodes.md) - Understanding single-purpose node design
- [Shared Store Pattern](../core-concepts/shared-store.md) - Inter-node data flow
- [Node Metadata Schema](../core-concepts/schemas.md#node-metadata-schema) - Interface format
- **Node Package Specifications**:
  - [GitHub Nodes](../core-node-packages/github-nodes.md)
  - [Claude Nodes](../core-node-packages/claude-nodes.md)
  - [CI Nodes](../core-node-packages/ci-nodes.md)
  - [LLM Node](../core-node-packages/llm-nodes.md)
