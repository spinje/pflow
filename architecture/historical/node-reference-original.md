> **HISTORICAL DOCUMENT**: Uses outdated parameter fallback pattern removed in Task 102.
>
> **Key inaccuracy**: This document shows the old pattern where nodes could read from
> both `self.params` AND `shared` store with fallback logic. After Task 102, nodes
> use **params-only** pattern - all input wiring is done via templates (`${var}`).
>
> **For current node implementation patterns, see:**
> - `architecture/reference/enhanced-interface-format.md` - Interface format
> - `architecture/features/simple-nodes.md` - Node design philosophy
> - `src/pflow/nodes/CLAUDE.md` - Implementation guide with retry patterns

---

# Node Implementation Reference

This document provides common patterns and best practices for implementing nodes in pflow. All nodes should follow these patterns for consistency and proper integration with the pflow architecture.

## Prerequisites

Before implementing any node, you should understand:
- [Simple Node Architecture](../features/simple-nodes.md) - Single-purpose node design philosophy
- [Shared Store Pattern](../core-concepts/shared-store.md) - Inter-node data flow and communication
- [Node Metadata Schema](./ir-schema.md#node-metadata-schema) - Interface format specification

## Common Implementation Patterns

### Parameter-Only Pattern

All nodes should read input values from `self.params`. The template system handles wiring shared store data into params before node execution:

```python
def prep(self, shared):
    # Read from params (template resolution handles shared store wiring)
    value = self.params.get("key")
    if not value:
        raise ValueError("key parameter is required")
    return value
```

This pattern allows nodes to:
- Receive template-resolved values via params (e.g., `"input": "${previous_node.output}"`)
- Accept static configuration when templates are not used
- Provide clear error messages when required inputs are missing

The template system (`${variable}`) provides explicit data flow declaration in the workflow IR, making data dependencies clear and predictable.

### Node Lifecycle Implementation

All nodes inherit from `pocketflow.BaseNode` (or `pocketflow.Node`) and implement the three-phase lifecycle:

```python
class MyNode(BaseNode):  # or Node
    """Brief description of what this node does.

    Interface:
    - Reads: shared["input_key"]: any  # Required input data
    - Reads: shared["optional_key"]: any  # Optional configuration
    - Writes: shared["output_key"]: any  # Processed output result
    - Writes: shared["error"]: str  # Error message if operation failed
    - Params: param1: any  # Additional parameter 1
    - Params: param2: any  # Additional parameter 2
    - Actions: default (success), error (failure)
    """

    def prep(self, shared):
        """Prepare phase: gather inputs from params."""
        # Read from params (template resolution handles shared store wiring)
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
    required_field = self.params.get("field")
    if not required_field:
        raise ValueError("Required parameter 'field' not provided")

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
- Reads: shared["config_path"]: str  # Path to the configuration file
- Reads: shared["schema_path"]: str  # Path to validation schema (optional)
- Writes: shared["config"]: dict  # Parsed configuration data
- Writes: shared["validation_error"]: str  # Validation error message if failed
- Params: strict_mode: bool  # Enable strict validation mode (default: false)
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

### Parameter-Only Pattern

Nodes read all input values from `self.params`. The template system resolves `${variable}` references from the shared store into params before node execution:

```python
def prep(self, shared):
    # Read from params (template-resolved values are already here)
    value = self.params.get("key")
    if not value:
        raise ValueError("Required parameter 'key' not provided")
```

## Node Type Reference

This section documents user-facing node types that can be used in workflows. For information about how workflows can execute other workflows as sub-components, see the [Nested Workflows Guide](../features/nested-workflows.md).

> **Note**: Workflow execution (using `type: "workflow"` in your JSON) is handled internally by the pflow runtime. Users simply specify `type: "workflow"` and the runtime handles the execution details.

## See Also

- [Simple Nodes](../features/simple-nodes.md) - Node design philosophy
- [Shared Store](../core-concepts/shared-store.md) - Inter-node data flow
- [Node Metadata](./ir-schema.md#node-metadata-schema) - Interface format
