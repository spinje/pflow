# Implementation Briefing for Subtask 4.3: Build Flow Construction and Wiring

## Your Foundation (From 4.1 and 4.2)

You're building on a solid foundation:
- **From 4.1**: `CompilationError` class with rich context (phase, node_id, node_type, details, suggestion)
- **From 4.2**: `import_node_class()` function that returns node classes ready for instantiation
- **Architecture**: Traditional functions in `src/pflow/runtime/compiler.py` (NOT PocketFlow nodes)
- **Current state**: `compile_ir_to_flow()` exists but raises NotImplementedError

## Your Mission

Transform the validated IR dict into an executable pocketflow.Flow object by:
1. Instantiating nodes from their classes
2. Setting parameters (including template variables)
3. Wiring nodes together using PocketFlow operators
4. Creating the final Flow object

## Critical PocketFlow Knowledge

### Node Instantiation
```python
# From my research, nodes are instantiated simply:
node_instance = NodeClass()  # No parameters to constructor

# Parameters are set separately:
if params:
    node_instance.set_params(params)  # Pass dict directly
```

### Wiring Operators
```python
# Default connections use >>
node_a >> node_b  # Creates default path

# Action-based routing uses -
node_a - "error" >> error_handler
node_a - "success" >> next_node

# Both can be chained
start >> process >> end
process - "retry" >> process  # Self-loop
```

### Flow Creation
```python
from pocketflow import Flow

# Flow takes the start node
flow = Flow(start_node)
```

## Key Implementation Insights

### 1. Node Storage Pattern
Store nodes in a dict keyed by node_id for easy lookup during edge processing:
```python
nodes = {}
for node_data in ir_dict["nodes"]:
    node_id = node_data["id"]
    node_type = node_data["type"]

    # Use the function from 4.2
    node_class = import_node_class(node_type, registry)
    node_instance = node_class()

    if "params" in node_data:
        node_instance.set_params(node_data["params"])

    nodes[node_id] = node_instance
```

### 2. Template Variables Must Pass Through
**Critical**: Template variables like `$issue_number` must be passed unchanged. They're resolved at runtime, not compilation:
```python
# If params contain {"issue": "$issue_number"}
# Pass it exactly as-is to set_params()
node.set_params({"issue": "$issue_number"})  # Don't try to resolve!
```

### 3. Edge Processing Pattern
Process edges after all nodes exist:
```python
for edge in ir_dict["edges"]:
    source = nodes[edge["source"]]  # Will KeyError if bad ID
    target = nodes[edge["target"]]
    action = edge.get("action", "default")

    if action == "default":
        source >> target
    else:
        source - action >> target
```

### 4. Start Node Detection
The IR might not specify which node is the start. Use first node as fallback:
```python
# Explicit start node (future feature, not in MVP)
start_id = ir_dict.get("start_node")

# Fallback: first node in array
if not start_id and ir_dict["nodes"]:
    start_id = ir_dict["nodes"][0]["id"]
```

## Error Handling Patterns

### Missing Node References
When an edge references a non-existent node:
```python
try:
    source = nodes[edge["source"]]
except KeyError:
    raise CompilationError(
        f"Edge references non-existent source node '{edge['source']}'",
        phase="flow_wiring",
        node_id=edge["source"],
        details={"edge": edge, "available_nodes": list(nodes.keys())},
        suggestion=f"Available nodes: {', '.join(sorted(nodes.keys()))}"
    )
```

### Import Failures
The `import_node_class()` function already throws CompilationError, but you might want to add context:
```python
try:
    node_class = import_node_class(node_type, registry)
except CompilationError as e:
    # Re-raise with node_id context
    e.node_id = node_data["id"]
    raise
```

## Logging Strategy

Continue the structured logging pattern:
```python
logger.debug("Creating node instance", extra={
    "phase": "node_instantiation",
    "node_id": node_id,
    "node_type": node_type
})

logger.debug("Wiring nodes", extra={
    "phase": "flow_wiring",
    "source": edge["source"],
    "target": edge["target"],
    "action": action
})
```

**Warning**: Don't use these reserved field names in extra dict:
- module, filename, funcName, levelname, pathname, process, thread

## Testing Strategy

### Use Mocks Extensively
Create mock nodes that track method calls:
```python
class MockNode:
    def __init__(self):
        self.params = None
        self.connections = []

    def set_params(self, params):
        self.params = params

    def __rshift__(self, other):  # >> operator
        self.connections.append(("default", other))
        return other

    def __sub__(self, action):  # - operator
        return MockActionNode(self, action)
```

### Test the Happy Path First
1. Simple linear flow: A >> B >> C
2. Verify all nodes instantiated
3. Verify parameters set correctly
4. Verify connections made

### Test Error Cases
1. Edge with non-existent source/target
2. Empty nodes array
3. Malformed edge data

### Test Real Integration
Use the TestNode from `src/pflow/nodes/test_node.py` if it exists in registry.

## Common Pitfalls to Avoid

1. **Don't instantiate nodes in import_node_class** - It returns the class, not instance
2. **Don't resolve template variables** - Pass them through unchanged
3. **Don't assume node order** - Nodes can be defined in any order, edges connect them
4. **Don't forget error context** - Always include phase, node_id when available

## Code Organization

Add your implementation to `compiler.py` after `import_node_class()`:
1. Helper function for node instantiation
2. Helper function for edge wiring
3. Update `compile_ir_to_flow()` to orchestrate

## Final Integration

Your code will be called like this:
```python
# From compile_ir_to_flow (already exists)
ir_dict = _parse_ir_input(ir_json)
_validate_ir_structure(ir_dict)

# Your code starts here
nodes = _instantiate_nodes(ir_dict, registry)  # Helper 1
_wire_nodes(nodes, ir_dict["edges"])          # Helper 2
start_node = _get_start_node(nodes, ir_dict)  # Helper 3

# Create and return flow
return Flow(start_node)
```

## Quick Command Reference

```bash
# Run tests
make test

# Run specific test file
python -m pytest tests/test_flow_construction.py -v

# Check code quality
make check

# Update task status when done
task-master set-status --id=4.3 --status=done
```

## Success Checklist

- [ ] All nodes from IR are instantiated
- [ ] Parameters (including templates) are set via set_params()
- [ ] Edges create proper connections (>> for default, - for actions)
- [ ] Start node is identified and Flow created
- [ ] CompilationError used for all failures with rich context
- [ ] Structured logging at each phase
- [ ] Tests cover happy path and error cases
- [ ] No template variable resolution (pass through)
- [ ] Code passes `make check`

Remember: You're building one focused piece - transforming validated IR into an executable Flow. Keep it simple, test thoroughly, and make errors helpful for debugging.
