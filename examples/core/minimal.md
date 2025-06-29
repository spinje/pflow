# Minimal IR Example

## Purpose
This example demonstrates the absolute minimum valid IR structure. It shows:
- Required fields (`ir_version` and `nodes`)
- Basic node structure with `id`, `type`, and `params`
- No edges or flow control needed for single-node workflows

## Use Case
Perfect for simple one-step operations like:
- Running a single command
- Performing a basic transformation
- Testing node implementations

## Visual Flow
```
[hello: echo]
```

## Node Explanation
- **hello**: A simple echo node that outputs a message
  - `type`: "echo" - References the echo node type in the registry
  - `params`: Contains the message to output

## How to Validate
```python
from pflow.core import validate_ir
import json

with open('minimal.json') as f:
    ir = json.load(f)
    validate_ir(ir)  # Should pass without errors
```

## Common Variations
1. **Different node type**: Change "echo" to any registered node type
2. **Additional parameters**: Add more fields to `params` as needed
3. **Multiple nodes**: Add more nodes to the array (but then you'd want edges)

## Notes
- No `edges` field needed for single-node workflows
- No `start_node` needed - execution begins with the first (only) node
- Template variables can be used in params: `"message": "$greeting"`
