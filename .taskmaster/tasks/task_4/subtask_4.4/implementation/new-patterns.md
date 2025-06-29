# Patterns Discovered

## Pattern: Edge Field Format Compatibility
**Context**: When you need to support multiple field name formats in data structures
**Solution**: Use Python's or operator to check multiple field names
**Why it works**: Short-circuit evaluation means first non-None value is returned
**When to use**: API evolution, backwards compatibility, multiple input formats
**Example**:
```python
# Support both edge field formats
source_id = edge.get("source") or edge.get("from")
target_id = edge.get("target") or edge.get("to")

# Then validate we have valid values
if not source_id or not target_id:
    raise CompilationError("Edge missing required fields")
```

## Pattern: Simple Test Nodes for Flow Verification
**Context**: When testing flow orchestration without complex node logic
**Solution**: Create minimal nodes that just mark execution in shared storage
**Why it works**: Focuses on verifying flow mechanics, not business logic
**When to use**: Integration tests, flow compilation verification
**Example**:
```python
class TestNode(Node):
    def prep(self, shared_storage):
        # Just mark that we executed
        shared_storage["test_node_executed"] = True
    # post implicitly returns None for default transition
```

## Pattern: Accessing Flow Start Node
**Context**: PocketFlow's Flow class has both start() method and start_node attribute
**Solution**: Always use flow.start_node to access the actual node instance
**Why it works**: Avoids confusion between method and attribute
**When to use**: Anytime you need to inspect or verify the start node
**Example**:
```python
flow = compile_ir_to_flow(ir, registry)
# WRONG: flow.start is the method
# RIGHT: flow.start_node is the node instance
assert flow.start_node.params["key"] == "value"
```
