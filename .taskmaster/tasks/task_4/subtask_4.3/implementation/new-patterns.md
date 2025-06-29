# Patterns Discovered

## Pattern: Connection Tracking in Mock Nodes
**Context**: When you need to test PocketFlow node wiring without executing real nodes
**Solution**: Override >> and - operators in mock nodes to track connections
**Why it works**: Captures the wiring calls without side effects
**When to use**: Testing flow construction, compiler output, or any node connection logic
**Example**:
```python
class MockNode(BaseNode):
    def __init__(self):
        super().__init__()
        self.connections = []  # Track connections

    def __rshift__(self, other):
        """Override >> to track default connections."""
        self.connections.append(("default", other))
        return super().__rshift__(other)

    def __sub__(self, action):
        """Override - to track action-based connections."""
        class MockTransition:
            def __init__(self, source, action):
                self.source = source
                self.action = action

            def __rshift__(self, target):
                self.source.connections.append((self.action, target))
                return self.source.next(target, self.action)

        return MockTransition(self, action)

# Usage in tests:
node_a >> node_b
assert ("default", node_b) in node_a.connections

node_a - "error" >> node_c
assert ("error", node_c) in node_a.connections
```

## Pattern: Phase-Based Compilation Error Handling
**Context**: When implementing multi-phase compilers or processors
**Solution**: Use distinct phase names in errors and structure try-except blocks by phase
**Why it works**: Makes debugging easier by immediately identifying which phase failed
**When to use**: Any multi-step transformation or compilation process
**Example**:
```python
# In main orchestrator:
try:
    nodes = _instantiate_nodes(ir_dict, registry)
except CompilationError:
    logger.exception("Node instantiation failed", extra={"phase": "node_instantiation"})
    raise

try:
    _wire_nodes(nodes, ir_dict.get("edges", []))
except CompilationError:
    logger.exception("Node wiring failed", extra={"phase": "flow_wiring"})
    raise

# In helper functions:
raise CompilationError(
    f"Edge references non-existent node '{node_id}'",
    phase="flow_wiring",  # Clear phase identification
    node_id=node_id,
    details={"edge": edge, "available_nodes": list(nodes.keys())},
    suggestion=f"Available nodes: {', '.join(sorted(nodes.keys()))}"
)
```

## Pattern: PocketFlow Operator Understanding
**Context**: When working with PocketFlow's >> and - operators
**Solution**: Understand the two-step pattern: - returns transition, >> completes connection
**Why it works**: Enables the clean `node - "action" >> target` syntax
**When to use**: Implementing custom nodes or understanding flow construction
**Example**:
```python
# How it works internally:
# node_a >> node_b
# Calls: node_a.__rshift__(node_b)
# Which calls: node_a.next(node_b, "default")

# node_a - "error" >> node_b
# Step 1: node_a.__sub__("error") returns _ConditionalTransition
# Step 2: transition.__rshift__(node_b) calls node_a.next(node_b, "error")

# This is why you can't do:
# wrong = node_a - "error"  # Just returns transition object
# You must complete with >>:
# right = node_a - "error" >> error_handler
```
