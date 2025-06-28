# PocketFlow Patterns for Task 4: Implement IR-to-PocketFlow Object Converter

## Task Context

- **Goal**: Convert JSON IR to executable pocketflow.Flow objects
- **Dependencies**: Tasks 5 (node registry), 6 (IR schema)
- **Constraints**: NOT a compiler - just object instantiation and wiring

## Overview

This task converts JSON IR (Intermediate Representation) into executable pocketflow.Flow objects. It's the bridge between workflow definitions and execution, using PocketFlow's operators and patterns.

## Core Patterns from Advanced Analysis

### Pattern: Flow Factory Functions
**Found in**: ALL 7 repositories (especially Danganronpa Simulator)
**Why It Applies**: Shows how to programmatically build flows

```python
def create_flow_from_components(components):
    """Pattern from Danganronpa - programmatic flow creation"""
    # Start with first component
    flow_start = components[0]

    # Chain components
    current = flow_start
    for next_component in components[1:]:
        current >> next_component
        current = next_component

    return Flow(start=flow_start)

# Applied to IR conversion:
def compile_ir_to_flow(ir_json):
    """Simple factory pattern - no complex compilation"""
    nodes = instantiate_nodes(ir_json["nodes"])
    connect_nodes(nodes, ir_json["edges"])
    return Flow(start=nodes[ir_json["start_node"]])
```

### Pattern: Template Variable Handling
**Found in**: Cold Email Personalization, Website Chatbot
**Why It Applies**: IR may contain template variables that need preservation

```python
def handle_template_params(params):
    """Preserve template variables for runtime resolution"""
    # Template variables like $issue_data are preserved as-is
    # They'll be resolved during execution, not compilation
    return params  # Pass through unchanged

# In node instantiation:
if "params" in node_spec:
    # Don't resolve templates here - that's runtime's job
    node.set_params(handle_template_params(node_spec["params"]))
```

### Pattern: Deterministic Node Instantiation
**Found in**: All repositories
**Why It Applies**: Same IR must always produce same Flow

```python
def instantiate_node_deterministically(node_spec):
    """Ensure reproducible node creation"""
    # Always use same order, same defaults
    NodeClass = get_node_class(node_spec["type"])
    node = NodeClass()

    # Set ID for debugging/tracing
    node.id = node_spec["id"]

    # Apply params in consistent order
    if "params" in node_spec:
        node.set_params(dict(sorted(node_spec["params"].items())))

    return node
```

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

### Anti-Pattern: Dynamic Flow Modification
**Found in**: Tutorial-Cursor (agent loops modify flow)
**Issue**: Breaks deterministic execution promise
**Alternative**: All flow structure defined in IR upfront

### Anti-Pattern: Resolving Templates During Compilation
**Found in**: Early versions of several tutorials
**Issue**: Compilation should be pure transformation
**Alternative**: Pass templates through, let runtime resolve them

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

## Integration Points

### Connection to Task 3 (Hello World)
Task 4 enables Task 3's execution:
```python
# Task 3 calls this function
flow = compile_ir_to_flow(workflow_json)
result = flow.run(shared)
```

### Connection to Task 5 (Node Discovery)
Task 4 depends on the node registry:
```python
# Task 5 provides this
NodeClass = get_node_class(node_spec["type"])
```

### Connection to Task 6 (IR Schema)
Task 4 assumes valid IR structure:
```python
# Task 6 defines this structure
validate_ir_against_schema(ir_json)  # Task 6
compile_ir_to_flow(ir_json)          # Task 4
```

### Connection to Task 9 (Shared Store)
Task 4 sets up nodes that will use natural keys:
```python
# Nodes created here will follow natural key patterns
node = LLMNode()  # Will use shared["prompt"], shared["response"]
```

## Minimal Test Case

```python
# Save as test_ir_converter.py and run with pytest
from pocketflow import Node, Flow

# Mock registry for testing
TEST_REGISTRY = {}

class TestNode(Node):
    """Minimal test node"""
    def prep(self, shared):
        self.value = self.params.get("value", 0)

    def exec(self, prep_res):
        return self.value * 2

    def post(self, shared, prep_res, exec_res):
        shared[f"{self.id}_result"] = exec_res
        return "default"

# Register test node
TEST_REGISTRY["test-node"] = TestNode

def get_node_class(node_type):
    """Mock registry lookup"""
    return TEST_REGISTRY[node_type]

def compile_ir_to_flow(ir_json):
    """Minimal IR converter following all patterns"""
    # Instantiate nodes
    nodes = {}
    for node_spec in ir_json["nodes"]:
        NodeClass = get_node_class(node_spec["type"])
        node = NodeClass()
        node.id = node_spec["id"]  # For tracing

        if "params" in node_spec:
            # Preserve order for determinism
            node.set_params(dict(sorted(node_spec["params"].items())))

        nodes[node_spec["id"]] = node

    # Connect nodes
    for edge in ir_json.get("edges", []):
        from_node = nodes[edge["from"]]
        to_node = nodes[edge["to"]]

        if edge.get("action", "default") == "default":
            from_node >> to_node
        else:
            from_node - edge["action"] >> to_node

    # Return flow
    return Flow(start=nodes[ir_json["start_node"]])

def test_flow_factory_pattern():
    # Test IR
    ir = {
        "nodes": [
            {"id": "n1", "type": "test-node", "params": {"value": 5}},
            {"id": "n2", "type": "test-node", "params": {"value": 10}}
        ],
        "edges": [
            {"from": "n1", "to": "n2"}
        ],
        "start_node": "n1"
    }

    # Convert to flow
    flow = compile_ir_to_flow(ir)

    # Execute
    shared = {}
    result = flow.run(shared)

    # Verify results
    assert "n1_result" in shared
    assert shared["n1_result"] == 10  # 5 * 2
    assert "n2_result" in shared
    assert shared["n2_result"] == 20  # 10 * 2

    print("✓ Flow factory pattern validated")

if __name__ == "__main__":
    test_flow_factory_pattern()
```

## Summary

Task 4's converter demonstrates that complex behavior (workflow execution) emerges from simple patterns (object instantiation and wiring). The key insights from advanced analysis:

1. **Keep it simple** - No code generation or complex compilation
2. **Preserve templates** - Don't resolve during compilation
3. **Ensure determinism** - Same IR always produces same Flow
4. **Use PocketFlow directly** - The framework does the hard work
