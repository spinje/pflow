# PocketFlow Patterns for Task 9: Shared Store Collision Detection and Proxy Mapping

## Overview

This task implements the NodeAwareSharedStore proxy that enables transparent key mapping for node compatibility while maintaining zero overhead for simple flows. It's a core architectural pattern that allows natural node interfaces.

## Relevant Cookbook Examples

- `cookbook/pocketflow-communication`: Shared store usage patterns
- `cookbook/pocketflow-proxy`: While no specific proxy example exists, the pattern emerges from flow composition needs

## Patterns to Adopt

### Pattern: Transparent Proxy Layer
**Source**: Architectural design from shared-store.md
**Compatibility**: ✅ Direct
**Description**: Dict-like proxy that transparently maps keys without nodes knowing

**Implementation for pflow**:
```python
class NodeAwareSharedStore:
    """Transparent proxy for shared store with optional key mapping."""

    def __init__(self, shared, input_mappings=None, output_mappings=None):
        self.shared = shared
        self.input_mappings = input_mappings or {}
        self.output_mappings = output_mappings or {}
        self._reserved_keys = {"stdin", "_flow_metadata", "_execution_id"}

    def get(self, key, default=None):
        """Get with transparent input mapping."""
        actual_key = self.input_mappings.get(key, key)
        return self.shared.get(actual_key, default)

    def __getitem__(self, key):
        """Dict-like access with mapping."""
        actual_key = self.input_mappings.get(key, key)
        if actual_key not in self.shared:
            raise KeyError(key)
        return self.shared[actual_key]

    def __setitem__(self, key, value):
        """Set with output mapping and reserved key protection."""
        if key in self._reserved_keys:
            raise ValueError(f"Cannot overwrite reserved key: {key}")

        actual_key = self.output_mappings.get(key, key)
        self.shared[actual_key] = value

    def __contains__(self, key):
        """Check existence with mapping."""
        actual_key = self.input_mappings.get(key, key)
        return actual_key in self.shared

    # Additional dict methods for compatibility
    def keys(self):
        return self.shared.keys()

    def items(self):
        return self.shared.items()

    def update(self, other):
        for k, v in other.items():
            self[k] = v  # Goes through mapping
```

**Key Features**:
- Transparent to nodes - they use natural keys
- Zero overhead when no mapping exists
- Protects reserved keys
- Full dict-like interface

### Pattern: Collision Detection
**Source**: Best practices for flow validation
**Compatibility**: ✅ Direct
**Description**: Detect key conflicts before execution

**Implementation**:
```python
def detect_collisions(node_interfaces):
    """Detect shared store key collisions between nodes."""
    output_keys = {}  # key -> node_id that outputs it
    collisions = []

    for node_id, interface in node_interfaces.items():
        # Check outputs for collisions
        for output_key in interface.get("outputs", []):
            if output_key in output_keys:
                collisions.append({
                    "key": output_key,
                    "nodes": [output_keys[output_key], node_id],
                    "type": "output_collision"
                })
            else:
                output_keys[output_key] = node_id

    return collisions

def get_reserved_keys():
    """Return list of reserved shared store keys."""
    return [
        "stdin",           # Shell pipe input
        "_flow_metadata",  # Flow execution metadata
        "_execution_id",   # Unique execution identifier
        "_trace",         # Execution trace data
    ]

def validate_shared_store_usage(node_interfaces):
    """Comprehensive validation of shared store usage."""
    errors = []
    reserved = set(get_reserved_keys())

    # Check for reserved key usage
    for node_id, interface in node_interfaces.items():
        for output_key in interface.get("outputs", []):
            if output_key in reserved:
                errors.append(f"Node '{node_id}' attempts to write reserved key '{output_key}'")

    # Check for collisions
    collisions = detect_collisions(node_interfaces)
    for collision in collisions:
        errors.append(
            f"Key '{collision['key']}' written by multiple nodes: {collision['nodes']}"
        )

    return errors
```

### Pattern: Key Existence Validation
**Source**: Fail-fast principle from architecture
**Compatibility**: ✅ Direct
**Description**: Validate required inputs exist before node execution

**Implementation**:
```python
def validate_node_inputs(node, shared_or_proxy):
    """Ensure required inputs exist before execution."""
    # Get node metadata (from Task 7)
    metadata = get_node_metadata(node.__class__)

    missing = []
    for required_input in metadata.get("required_inputs", []):
        if required_input not in shared_or_proxy:
            missing.append(required_input)

    if missing:
        raise ValueError(
            f"Node '{node.__class__.__name__}' missing required inputs: {missing}"
        )

# Integration with node execution
def execute_node_with_validation(node, shared, mappings=None):
    """Execute node with proxy and validation."""
    # Create proxy if mappings exist
    if mappings:
        proxy = NodeAwareSharedStore(
            shared,
            input_mappings=mappings.get("input_mappings"),
            output_mappings=mappings.get("output_mappings")
        )
        store = proxy
    else:
        store = shared

    # Validate inputs exist
    validate_node_inputs(node, store)

    # Execute node
    return node._run(store)
```

### Pattern: Zero-Overhead Direct Access
**Source**: Performance requirement from MVP scope
**Compatibility**: ✅ Direct
**Description**: No proxy when not needed

**Implementation in flow execution**:
```python
def execute_flow_with_proxy_support(flow, shared, ir_mappings=None):
    """Execute flow with optional proxy mapping."""

    # If no mappings defined, use direct access (zero overhead)
    if not ir_mappings:
        return flow.run(shared)

    # Otherwise, wrap node execution with proxies
    # This would be integrated into the IR compiler
    for node_id, mappings in ir_mappings.items():
        # Attach mappings to nodes for runtime use
        # Actual implementation depends on Task 4 design
        pass

    return flow.run(shared)
```

## Patterns to Avoid

### Pattern: Complex Nested Mappings
**Source**: Advanced proxy examples
**Issue**: MVP uses flat key structure
**Alternative**: Simple key-to-key mapping only

### Pattern: Dynamic Mapping Changes
**Issue**: Mappings should be static from IR
**Alternative**: Fixed mappings defined at flow creation

### Pattern: Shared Store Class Wrapper
**Issue**: Over-engineering, dict works fine
**Alternative**: Validation functions + proxy pattern

## Implementation Guidelines

1. **Keep proxy transparent**: Nodes shouldn't know they're using a proxy
2. **Fail fast**: Validate early and with clear messages
3. **Zero overhead**: Direct dict access when no mapping needed
4. **Simple mappings**: Flat key-to-key only for MVP
5. **Clear errors**: Help users understand collision issues

## Usage Examples

### Example 1: Compatible Nodes (No Proxy)
```python
# Both nodes use "content" naturally
shared = {}
read_node._run(shared)  # Writes to shared["content"]
write_node._run(shared)  # Reads from shared["content"]
```

### Example 2: Incompatible Nodes (Proxy Required)
```python
# github_node outputs "issue_text"
# llm_node expects "prompt"

mappings = {
    "llm_node": {
        "input_mappings": {"prompt": "issue_text"}
    }
}

# During execution
shared = {}
github_node._run(shared)  # Writes shared["issue_text"]

# Create proxy for llm_node
proxy = NodeAwareSharedStore(
    shared,
    input_mappings={"prompt": "issue_text"}
)
llm_node._run(proxy)  # Reads proxy["prompt"] → shared["issue_text"]
```

## Testing Approach

```python
def test_proxy_mapping():
    # Test transparent mapping
    shared = {"raw_data": "test content"}
    proxy = NodeAwareSharedStore(
        shared,
        input_mappings={"content": "raw_data"},
        output_mappings={"result": "processed_data"}
    )

    # Input mapping
    assert proxy["content"] == "test content"
    assert proxy.get("content") == "test content"
    assert "content" in proxy

    # Output mapping
    proxy["result"] = "processed"
    assert shared["processed_data"] == "processed"
    assert "result" not in shared

    # Direct access (no mapping)
    proxy["other"] = "value"
    assert shared["other"] == "value"

def test_collision_detection():
    interfaces = {
        "node1": {"outputs": ["content", "status"]},
        "node2": {"outputs": ["content", "result"]},  # Collision!
    }

    collisions = detect_collisions(interfaces)
    assert len(collisions) == 1
    assert collisions[0]["key"] == "content"

def test_reserved_keys():
    shared = {}
    proxy = NodeAwareSharedStore(shared)

    with pytest.raises(ValueError, match="reserved key"):
        proxy["stdin"] = "value"
```

This proxy pattern is foundational to pflow's philosophy of simple, natural node interfaces while supporting complex flow orchestration.
