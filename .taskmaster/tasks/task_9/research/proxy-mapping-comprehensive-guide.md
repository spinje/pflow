# Comprehensive Guide: Shared Store Collision Detection and Proxy Mapping

## Executive Summary

Task 9 implements the critical infrastructure that enables data flow between nodes in pflow workflows. This document explains the proxy mapping system, collision detection, and the architectural decisions that make workflows possible.

## The Fundamental Problem

### Nodes Have Fixed Interfaces

Every node in pflow has a predefined interface:
```python
class YouTubeTranscriptNode(Node):
    """
    Interface:
    - Reads: shared["url"]
    - Writes: shared["transcript"]
    """

class LLMNode(Node):
    """
    Interface:
    - Reads: shared["prompt"]
    - Writes: shared["response"]
    """
```

### The Connection Problem

How do we connect these nodes when their interfaces don't match?
```
YouTubeTranscript writes "transcript" → ??? → LLM needs "prompt"
```

## The Solution: Proxy Mapping

The `NodeAwareSharedStore` acts as a transparent translation layer between nodes and the shared store.

### Basic Concept

```python
# Without proxy: Direct access (when interfaces match)
shared = {"url": "https://youtube.com/..."}
node.run(shared)  # Node reads shared["url"] directly

# With proxy: Transparent mapping
shared = {"transcript": "Video content..."}
proxy = NodeAwareSharedStore(
    shared,
    input_mappings={"prompt": "transcript"}
)
node.run(proxy)  # Node reads "prompt", proxy returns value from "transcript"
```

### How It Works

1. **Node reads `shared["prompt"]`**
2. **Proxy intercepts the read**
3. **Proxy checks input_mappings**
4. **Proxy returns `shared["transcript"]` instead**
5. **Node never knows the difference**

## Types of Mappings

### 1. Simple Key-to-Key Mapping
```json
{
  "input_mappings": {
    "prompt": "transcript"  // When node reads "prompt", give it "transcript"
  }
}
```

### 2. Path-Based Extraction (Advanced)
```json
{
  "input_mappings": {
    "prompt": "api_response.data.content",  // Extract nested value
    "user_id": "api_response.user.id",      // Deep path
    "labels": "issue.labels[*].name"        // Array extraction
  }
}
```

### 3. Output Mappings (Collision Avoidance)
```json
{
  "output_mappings": {
    "response": "analysis_result"  // When node writes "response", store as "analysis_result"
  }
}
```

## Collision Detection

### What Are Collisions?

Collisions occur when:
1. **Multiple nodes write to the same key**
   ```
   Node A writes shared["response"]
   Node B writes shared["response"]  // COLLISION!
   ```

2. **Nodes write to reserved keys**
   ```
   Node writes shared["stdin"]  // COLLISION with reserved key!
   ```

### Detection Algorithm

```python
def detect_collisions(node_interfaces):
    """
    node_interfaces = [
        {"id": "node1", "outputs": ["response", "status"]},
        {"id": "node2", "outputs": ["response", "data"]},  # "response" collision!
    ]
    """
    written_keys = {}
    collisions = []

    for node in node_interfaces:
        for output_key in node["outputs"]:
            if output_key in written_keys:
                collisions.append({
                    "key": output_key,
                    "nodes": [written_keys[output_key], node["id"]]
                })
            written_keys[output_key] = node["id"]

    return collisions
```

### Reserved Keys

These keys are protected and cannot be written by nodes:
- `stdin` - Reserved for piped input from shell
- Future: `stdout`, `stderr`, etc.

## Implementation Requirements

### 1. NodeAwareSharedStore Class

```python
class NodeAwareSharedStore:
    def __init__(self, shared_store, input_mappings=None, output_mappings=None):
        self.shared = shared_store
        self.input_mappings = input_mappings or {}
        self.output_mappings = output_mappings or {}

    def __getitem__(self, key):
        # Check if this key should be mapped
        if key in self.input_mappings:
            mapped_key = self.input_mappings[key]
            # Handle path-based extraction
            if "." in mapped_key or "[" in mapped_key:
                return self._extract_path(self.shared, mapped_key)
            return self.shared[mapped_key]
        # Direct access (zero overhead when no mapping)
        return self.shared[key]

    def __setitem__(self, key, value):
        # Check output mappings
        if key in self.output_mappings:
            mapped_key = self.output_mappings[key]
            self.shared[mapped_key] = value
        else:
            # Check for reserved keys
            if key in get_reserved_keys():
                raise ValueError(f"Cannot write to reserved key: {key}")
            self.shared[key] = value
```

### 2. Path Extraction

Support for nested JSON access:
```python
def _extract_path(self, data, path):
    """
    Extract value from nested structure using path notation.

    Examples:
    - "user.name" → data["user"]["name"]
    - "items[0].id" → data["items"][0]["id"]
    - "labels[*].name" → [label["name"] for label in data["labels"]]
    """
```

### 3. Validation Functions

```python
def validate_key_existence(shared_store, required_keys):
    """Ensure required keys exist before node execution."""
    missing = [key for key in required_keys if key not in shared_store]
    if missing:
        raise KeyError(f"Missing required keys: {missing}")
```

## Integration with the Planner (Task 17)

The planner will use these capabilities to:

### 1. Detect and Resolve Collisions
```python
# Planner detects collision
collisions = detect_collisions(workflow_nodes)
if collisions:
    # Generate output mappings to resolve
    for collision in collisions:
        for node_id in collision["nodes"]:
            mappings[node_id] = {
                "output_mappings": {
                    collision["key"]: f"{node_id}_{collision['key']}"
                }
            }
```

### 2. Connect Incompatible Interfaces
```python
# Planner knows:
# - youtube-transcript writes "transcript"
# - llm reads "prompt"
# Generate mapping:
mappings["llm"] = {
    "input_mappings": {"prompt": "transcript"}
}
```

### 3. Handle Complex Data Flows
```python
# API returns nested JSON
# LLM needs specific field
mappings["analyzer"] = {
    "input_mappings": {
        "prompt": "github_response.issue.body",
        "issue_id": "github_response.issue.id"
    }
}
```

## Example Workflows

### Simple Linear Flow
```
read-file → llm → write-file
```
No mappings needed if interfaces match.

### Complex Flow with Collisions
```
github-api → analyzer-llm → fixer-llm → reviewer-llm
```

All LLMs write to "response" - collision!

Solution:
```json
{
  "mappings": {
    "analyzer-llm": {
      "output_mappings": {"response": "analysis"}
    },
    "fixer-llm": {
      "input_mappings": {"prompt": "analysis"},
      "output_mappings": {"response": "fix"}
    },
    "reviewer-llm": {
      "input_mappings": {"prompt": "fix"},
      "output_mappings": {"response": "review"}
    }
  }
}
```

### API Data Extraction
```
github-api → notifier
```

Where github-api returns:
```json
{
  "issue": {
    "id": 123,
    "title": "Bug report",
    "user": {
      "login": "johndoe",
      "email": "john@example.com"
    }
  }
}
```

Mapping:
```json
{
  "notifier": {
    "input_mappings": {
      "recipient": "api_response.issue.user.email",
      "subject": "api_response.issue.title"
    }
  }
}
```

## Edge Cases and Considerations

### 1. Missing Keys
```python
# Node expects shared["prompt"]
# Proxy maps to shared["transcript"]
# But "transcript" doesn't exist!
# Must fail with clear error: "Missing required key: transcript (mapped from prompt)"
```

### 2. Type Mismatches
```python
# Path extraction might return unexpected types
# "items[*].name" could return:
# - Array of strings
# - Single string (if only one item)
# - None/null (if no items)
```

### 3. Performance
- Direct access (no mapping) must have zero overhead
- Path extraction is more expensive - cache if possible
- Collision detection runs once during planning, not runtime

### 4. Circular Mappings
```json
{
  "input_mappings": {
    "a": "b",
    "b": "a"  // Circular!
  }
}
```

## Testing Strategy

### 1. Basic Proxy Functionality
- Simple key mapping
- Missing key handling
- Reserved key protection

### 2. Path Extraction
- Nested object access
- Array indexing
- Array filtering/mapping
- Edge cases (null, missing paths)

### 3. Collision Detection
- Multiple writers
- Reserved keys
- Complex workflows

### 4. Performance
- Benchmark direct vs mapped access
- Measure overhead
- Test with large shared stores

## Implementation Checklist

1. [ ] Create `src/pflow/core/proxy.py`
2. [ ] Implement `get_reserved_keys()`
3. [ ] Implement `detect_collisions()`
4. [ ] Implement `NodeAwareSharedStore` class
   - [ ] Basic key mapping
   - [ ] Path extraction
   - [ ] Output mapping
   - [ ] Reserved key protection
5. [ ] Add validation utilities
   - [ ] Key existence checking
   - [ ] Type validation (optional)
6. [ ] Comprehensive test suite
7. [ ] Performance benchmarks
8. [ ] Documentation

## Success Criteria

The implementation is successful when:
1. Nodes can communicate despite interface mismatches
2. Collisions are detected and resolved automatically
3. Complex JSON structures can be accessed via paths
4. Zero overhead for direct access (no mappings)
5. Clear error messages for missing keys
6. Reserved keys are protected

## Future Enhancements (Post-MVP)

1. **JSONPath/JMESPath support** for advanced queries
2. **Transform functions** in mappings (uppercase, parsing, etc.)
3. **Type coercion** (string to int, etc.)
4. **Default values** for missing keys
5. **Mapping composition** (chain multiple mappings)

## Conclusion

The proxy mapping system is the critical infrastructure that makes pflow workflows possible. It solves the fundamental problem of connecting nodes with incompatible interfaces while maintaining the simplicity of the shared store pattern. By supporting both simple key mapping and advanced path extraction, it enables powerful workflows without requiring intermediate transformation nodes.

Remember: The goal is to make simple things simple (direct access with zero overhead) and complex things possible (advanced mappings and collision resolution).
