# Proxy Pattern for Natural Node Interfaces

## The Problem

Different nodes naturally use different key names for similar concepts:
- A generic `read-file` node uses `shared["content"]`
- A specialized `read-csv` node might use `shared["csv_data"]`
- An `analyze-data` node expects `shared["data"]`

Without the proxy pattern, nodes become tightly coupled and hard to compose.

## The Solution: NodeAwareSharedStore

The proxy pattern allows transparent key mapping, enabling nodes to use their natural interfaces while still working together.

```python
# Without proxy: Nodes must agree on keys
read-csv writes to shared["csv_data"]
analyze-data reads from shared["data"]  # Incompatible!

# With proxy: Transparent mapping
read-csv writes to shared["csv_data"]
    ↓ (proxy maps "csv_data" → "data")
analyze-data reads from shared["data"]  # Works!
```

## Implementation

### Basic Proxy
```python
class NodeAwareSharedStore:
    """Proxy that provides transparent key mapping for nodes."""

    def __init__(self, base_store, input_mappings=None, output_mappings=None):
        self._base = base_store
        self._input_mappings = input_mappings or {}
        self._output_mappings = output_mappings or {}

    def __getitem__(self, key):
        """Read with input mapping."""
        mapped_key = self._input_mappings.get(key, key)
        return self._base[mapped_key]

    def __setitem__(self, key, value):
        """Write with output mapping."""
        mapped_key = self._output_mappings.get(key, key)
        self._base[mapped_key] = value
```

### Usage Example
```python
# Base shared store
shared = {"csv_data": "1,2,3\n4,5,6"}

# Proxy for analyze-data node
proxy = NodeAwareSharedStore(
    shared,
    input_mappings={"data": "csv_data"}  # data → csv_data
)

# Node reads "data" but gets "csv_data"
value = proxy["data"]  # Returns "1,2,3\n4,5,6"
```

## Mapping Patterns

### 1. Simple Renaming
```json
{
  "mappings": {
    "input_mappings": {
      "data": "csv_data"
    }
  }
}
```

### 2. Bidirectional Mapping
```json
{
  "mappings": {
    "input_mappings": {
      "content": "file_content"
    },
    "output_mappings": {
      "result": "analysis_result"
    }
  }
}
```

### 3. Multiple Sources
```json
{
  "mappings": {
    "input_mappings": {
      "text": "content",      // Try content first
      "text": "stdin",        // Fallback to stdin
      "text": "user_input"    // Last resort
    }
  }
}
```

## Advanced Proxy Features

### 1. Existence Checking
```python
def __contains__(self, key):
    """Check if key exists (considering mappings)."""
    mapped_key = self._input_mappings.get(key, key)
    return mapped_key in self._base
```

### 2. Key Listing
```python
def keys(self):
    """List available keys (including mapped ones)."""
    base_keys = set(self._base.keys())
    mapped_keys = set(self._input_mappings.keys())
    return base_keys | mapped_keys
```

### 3. Fallback Values
```python
def get(self, key, default=None):
    """Get with fallback support."""
    try:
        return self[key]
    except KeyError:
        return default
```

### 4. Multiple Mapping Resolution
```python
def __getitem__(self, key):
    """Try multiple mappings until one works."""
    # Direct key
    if key in self._base:
        return self._base[key]

    # Try mappings
    if key in self._input_mappings:
        mapped = self._input_mappings[key]
        if isinstance(mapped, list):
            # Multiple possible sources
            for source in mapped:
                if source in self._base:
                    return self._base[source]
        else:
            # Single mapping
            if mapped in self._base:
                return self._base[mapped]

    raise KeyError(f"No mapping found for '{key}'")
```

## Zero-Overhead Principle

When no mappings exist, the proxy should have minimal overhead:

```python
class NodeAwareSharedStore:
    def __getitem__(self, key):
        # Fast path - no mappings
        if not self._input_mappings:
            return self._base[key]

        # Mapping path
        mapped_key = self._input_mappings.get(key, key)
        return self._base[mapped_key]
```

## Integration with Workflow IR

### IR with Mappings
```json
{
  "nodes": [
    {
      "id": "reader",
      "type": "read-csv"
    },
    {
      "id": "analyzer",
      "type": "analyze-data",
      "mappings": {
        "input_mappings": {
          "data": "csv_data"
        }
      }
    }
  ]
}
```

### Compiler Integration
```python
def create_node_proxy(shared_store, node_config):
    """Create proxy for node if mappings exist."""
    mappings = node_config.get("mappings", {})

    if not mappings:
        # No proxy needed
        return shared_store

    return NodeAwareSharedStore(
        shared_store,
        input_mappings=mappings.get("input_mappings", {}),
        output_mappings=mappings.get("output_mappings", {})
    )
```

## Common Use Cases

### 1. Generic to Specific
```python
# Generic node writes to "content"
# Specific node needs "markdown_content"
mappings = {"markdown_content": "content"}
```

### 2. Version Migration
```python
# Old nodes use "data", new ones use "dataset"
mappings = {"data": "dataset"}
```

### 3. Multi-Source Aggregation
```python
# Node can work with various inputs
mappings = {
    "input": ["stdin", "file_content", "api_response"]
}
```

### 4. Reserved Key Avoidance
```python
# If "stdin" is reserved, map to safe key
mappings = {"user_input": "stdin_backup"}
```

## Testing the Proxy

### Unit Tests
```python
def test_simple_mapping():
    base = {"source": "value"}
    proxy = NodeAwareSharedStore(base, {"target": "source"})

    assert proxy["target"] == "value"
    assert "target" in proxy

def test_write_mapping():
    base = {}
    proxy = NodeAwareSharedStore(base, output_mappings={"out": "stored"})

    proxy["out"] = "value"
    assert base["stored"] == "value"

def test_no_mapping_overhead():
    base = {"key": "value"}
    proxy = NodeAwareSharedStore(base)  # No mappings

    # Should be as fast as direct access
    assert proxy["key"] == "value"
```

### Integration Tests
```python
def test_node_compatibility():
    """Test incompatible nodes work together via proxy."""
    # Setup
    shared = {}

    # CSV reader writes to "csv_data"
    csv_reader = ReadCSVNode()
    csv_reader.run(shared)
    assert "csv_data" in shared

    # Analyzer needs "data"
    analyzer = AnalyzeDataNode()
    # Would fail: analyzer.run(shared)

    # With proxy
    proxy = NodeAwareSharedStore(shared, {"data": "csv_data"})
    analyzer.run(proxy)  # Works!
```

## Best Practices

1. **Keep Mappings Simple** - Avoid complex transformation logic
2. **Document Mappings** - Clear comments on why mappings exist
3. **Validate Early** - Check mapping conflicts during compilation
4. **Prefer Convention** - Use common keys when possible
5. **Test Compatibility** - Ensure mapped nodes work together

## Performance Considerations

```python
# Optimize for common case (no mappings)
if not self._has_mappings:
    return self._base[key]  # Direct access

# Cache mapping lookups
@lru_cache(maxsize=128)
def _resolve_mapping(self, key):
    return self._input_mappings.get(key, key)
```

## Future Enhancements

1. **Deep Path Mapping**: `"user.name": "data.user_name"`
2. **Transform Functions**: `"uppercase_text": lambda x: x.upper()`
3. **Type Coercion**: `"count": int(shared["count_string"])`
4. **Conditional Mapping**: Map based on node state

## Remember

The proxy pattern enables pflow's promise of composable nodes. It's the glue that lets nodes maintain natural interfaces while working together seamlessly. Keep it simple, fast, and transparent.
