# PocketFlow Patterns for Task 4: Implement IR-to-PocketFlow Object Converter

## Overview

This task converts JSON IR (Intermediate Representation) into executable pocketflow.Flow objects. It's the bridge between workflow definitions and execution, using PocketFlow's operators and patterns.

## Relevant Cookbook Examples

- `cookbook/pocketflow-flow`: Flow construction with >> operator and actions
- `cookbook/pocketflow-workflow`: Multi-stage flow assembly
- `cookbook/pocketflow-agent`: Complex flow with conditional routing

## Patterns to Adopt

### Pattern: Direct Flow Construction
**Source**: `cookbook/pocketflow-flow/`
**Compatibility**: ✅ Direct
**Description**: Use PocketFlow operators directly instead of building a "compiler"

**Original PocketFlow Pattern**:
```python
# Direct node connection
menu_node >> transform_node >> menu_node
menu_node - "exit" >> exit_node

# Create flow
flow = Flow(start=menu_node)
```

**Adapted for pflow**:
```python
from pocketflow import Flow
from pflow.registry import get_node_class

def compile_ir_to_flow(ir_json):
    """Convert JSON IR to pocketflow.Flow - NOT a compiler, just object wiring."""

    # 1. Create node instances
    nodes = {}
    for node_spec in ir_json["nodes"]:
        NodeClass = get_node_class(node_spec["type"])
        node = NodeClass()

        if "params" in node_spec:
            node.set_params(node_spec["params"])

        nodes[node_spec["id"]] = node

    # 2. Connect nodes using PocketFlow operators
    for edge in ir_json["edges"]:
        from_node = nodes[edge["from"]]
        to_node = nodes[edge["to"]]
        action = edge.get("action", "default")

        if action == "default":
            from_node >> to_node
        else:
            from_node - action >> to_node

    # 3. Create flow with start node
    start_node = nodes[ir_json["start_node"]]
    return Flow(start=start_node)
```

**Key Adaptations**:
- Direct use of >> operator
- No code generation or string manipulation
- Simple object instantiation and wiring

### Pattern: Action-Based Routing
**Source**: `cookbook/pocketflow-agent/`
**Compatibility**: ✅ Direct
**Description**: Support conditional transitions via action strings

**Original PocketFlow Pattern**:
```python
decide_node - "search" >> search_node
decide_node - "answer" >> answer_node
decide_node - "clarify" >> clarify_node
```

**Implementation for pflow IR**:
```json
{
  "edges": [
    {"from": "validator", "to": "processor", "action": "valid"},
    {"from": "validator", "to": "error_handler", "action": "invalid"},
    {"from": "error_handler", "to": "validator", "action": "retry"}
  ]
}
```

**Converter handles actions**:
```python
# In compile_ir_to_flow
if edge.get("action") and edge["action"] != "default":
    from_node - edge["action"] >> to_node
else:
    from_node >> to_node
```

### Pattern: Node Registry Integration
**Source**: Integration with Task 5 patterns
**Compatibility**: ✅ Direct
**Description**: Dynamic node class lookup from registry

**Implementation**:
```python
def get_node_class(node_type):
    """Get node class from registry by type name."""
    # Registry populated by filesystem scanning (Task 5)
    registry = get_node_registry()

    if node_type not in registry:
        raise ValueError(f"Unknown node type: {node_type}")

    return registry[node_type]

# Usage in converter
NodeClass = get_node_class("read-file")  # Returns ReadFileNode class
```

### Pattern: IR Validation
**Source**: Best practices from various examples
**Compatibility**: ✅ Direct
**Description**: Validate IR structure before attempting compilation

**Implementation**:
```python
def validate_ir(ir_json):
    """Validate IR structure and references."""
    # Check required fields
    assert "nodes" in ir_json and ir_json["nodes"]
    assert "start_node" in ir_json

    # Collect node IDs
    node_ids = {node["id"] for node in ir_json["nodes"]}

    # Validate start node exists
    if ir_json["start_node"] not in node_ids:
        raise ValueError(f"Start node '{ir_json['start_node']}' not found")

    # Validate edges reference existing nodes
    for edge in ir_json.get("edges", []):
        if edge["from"] not in node_ids:
            raise ValueError(f"Edge source '{edge['from']}' not found")
        if edge["to"] not in node_ids:
            raise ValueError(f"Edge target '{edge['to']}' not found")

    # Validate node types exist in registry
    registry = get_node_registry()
    for node in ir_json["nodes"]:
        if node["type"] not in registry:
            raise ValueError(f"Unknown node type: {node['type']}")
```

## Patterns to Avoid

### Pattern: Code Generation
**Issue**: Generating Python code strings is complex and error-prone
**Alternative**: Direct object instantiation using PocketFlow classes

### Pattern: Custom Execution Engine
**Issue**: PocketFlow already provides complete execution
**Alternative**: Return standard Flow object, let PocketFlow handle execution

### Pattern: Complex Compiler Infrastructure
**Issue**: Over-engineering for a simple object wiring task
**Alternative**: Keep it simple - lookup, instantiate, connect

## Implementation Guidelines

1. **This is NOT a compiler**: It's a simple object factory and wiring function
2. **Use PocketFlow directly**: Don't wrap or abstract the framework
3. **Clear error messages**: Help users understand IR problems
4. **Support all PocketFlow features**: Actions, params, standard flow
5. **Keep it testable**: Pure function that returns Flow objects

## Example IR Structures

### Simple Linear Flow
```json
{
  "nodes": [
    {"id": "n1", "type": "read-file", "params": {"file_path": "input.txt"}},
    {"id": "n2", "type": "llm", "params": {"temperature": 0.7}},
    {"id": "n3", "type": "write-file", "params": {"file_path": "output.txt"}}
  ],
  "edges": [
    {"from": "n1", "to": "n2"},
    {"from": "n2", "to": "n3"}
  ],
  "start_node": "n1"
}
```

### Flow with Actions
```json
{
  "nodes": [
    {"id": "check", "type": "validator"},
    {"id": "process", "type": "processor"},
    {"id": "handle_error", "type": "error-handler"}
  ],
  "edges": [
    {"from": "check", "to": "process", "action": "pass"},
    {"from": "check", "to": "handle_error", "action": "fail"},
    {"from": "handle_error", "to": "check", "action": "retry"}
  ],
  "start_node": "check"
}
```

## Testing Approach

```python
def test_ir_compilation():
    ir = {
        "nodes": [
            {"id": "n1", "type": "test-node", "params": {"value": 42}},
            {"id": "n2", "type": "test-node", "params": {"value": 43}}
        ],
        "edges": [{"from": "n1", "to": "n2"}],
        "start_node": "n1"
    }

    flow = compile_ir_to_flow(ir)

    # Verify flow structure
    assert isinstance(flow, Flow)
    assert flow.start_node is not None
    assert flow.start_node.params["value"] == 42

    # Test execution
    shared = {}
    flow.run(shared)
    assert "n1_output" in shared
    assert "n2_output" in shared
```

This converter is the heart of pflow's "Plan Once, Run Forever" philosophy - converting planned workflows into executable objects.
