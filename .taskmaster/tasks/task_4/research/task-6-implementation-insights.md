# Task 6 Implementation Insights for Task 4

This document captures critical implementation details from Task 6 (JSON IR schema) that directly impact Task 4 (IR-to-PocketFlow compiler).

## Critical Implementation Insights for Task 4 (Based on Task 6 Implementation)

### 1. **IR Structure You'll Be Working With**
I just implemented the IR schema validation in `src/pflow/core/ir_schema.py`. The actual structure you'll receive is:
```python
{
    "ir_version": "1.0.0",  # Required, semver format
    "nodes": [              # Required array, not a dict
        {
            "id": "n1",     # Required string
            "type": "read-file",  # Required, NOT "registry_id"
            "params": {}    # Optional dict
        }
    ],
    "edges": [              # Optional, defaults to []
        {
            "from": "n1",   # Required if edges exist
            "to": "n2",     # Required if edges exist
            "action": "default"  # Optional, defaults to "default"
        }
    ],
    "start_node": "n1",     # Optional, defaults to nodes[0].id
    "mappings": {}          # Optional, for NodeAwareSharedStore proxy
}
```

### 2. **Validation Is Already Done**
The IR you receive has already been validated by my `validate_ir()` function. However, you still need to handle:
- Node types not found in registry
- Import failures for node modules
- Node reference validation is done (edges reference existing nodes)

### 3. **Template Variables Are Part of Params**
In the examples I created (`examples/core/template-variables.json`), template variables look like:
```json
"params": {
    "endpoint": "$api_endpoint",
    "prompt": "Process this data: $content"
}
```
You MUST pass these through unchanged to `node.set_params()`. Don't try to resolve them.

### 4. **Custom Error Pattern I Established**
I created a `ValidationError` class with `path` and `suggestion` attributes. While you'll create your own `CompilationError`, follow a similar pattern:
```python
class CompilationError(Exception):
    def __init__(self, message, node_id=None, node_type=None):
        self.node_id = node_id
        self.node_type = node_type
        super().__init__(message)
```

### 5. **Real Examples to Test With**
I created 7 valid examples in `examples/` that your compiler should handle:
- `minimal.json` - Single node, no edges
- `simple-pipeline.json` - Basic node chain
- `template-variables.json` - Has `$variable` params
- `error-handling.json` - Uses action-based routing
- `proxy-mappings.json` - Has mappings field

Use these for testing your implementation.

### 6. **Start Node Behavior I Defined**
In the schema, `start_node` is optional. If not provided, I documented that it should use the first node. So:
```python
start_node_id = ir_data.get("start_node", ir_data["nodes"][0]["id"])
```

### 7. **Node Type Field Name**
I made the decision to use `"type"` not `"registry_id"` for the node type field. This affects your registry lookups:
```python
node_type = node_data["type"]  # Will be "read-file", "llm", etc.
metadata = registry.get_node(node_type)
```

### 8. **Edges Default to Empty Array**
In my schema implementation, edges default to `[]` if not provided, so you can safely do:
```python
for edge in ir_data.get("edges", []):
    # Process edges
```

## Additional Context from Task 6 Implementation

### Validation Error Messages
The validation function provides detailed error messages with paths like `nodes[0].type` and suggestions. Your CompilationError should maintain this level of detail for consistency.

### Example IR Files
All example files in `examples/` have been validated and tested. They demonstrate:
- Minimal workflows (single node)
- Pipeline patterns (multiple nodes with edges)
- Template variable usage ($variable syntax)
- Action-based routing (error/retry actions)
- Proxy mappings for shared store

### Import Path for Validation
When you need to validate IR before compilation:
```python
from pflow.core import validate_ir, ValidationError
```

These are concrete details from the Task 6 implementation that directly impact how you'll build the compiler.
