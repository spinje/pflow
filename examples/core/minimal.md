# Minimal IR Example

## Purpose
This example demonstrates the absolute minimum valid IR structure. It shows:
- Required fields (`ir_version` and `nodes`)
- Basic node structure with `id`, `type`, and `params`
- No edges or flow control needed for single-node workflows

## Use Case
Perfect for simple one-step operations like:
- Writing content to a file
- Creating configuration files
- Testing file node implementations

## Visual Flow
```
[hello: write-file]
```

## Node Explanation
- **hello**: A write-file node that creates a text file
  - `type`: "write-file" - References the write-file node type in the registry
  - `params`: Contains the content to write and the file path

## How to Validate
```python
from pflow.core import validate_ir
import json

with open('minimal.json') as f:
    ir = json.load(f)
    validate_ir(ir)  # Should pass without errors
```

## Common Variations
1. **Different node type**: Change "write-file" to other MVP nodes like "read-file" or "copy-file"
2. **Additional parameters**: Add more fields to `params` as needed
3. **Multiple nodes**: Add more nodes to the array (but then you'd want edges)

## Notes
- No `edges` field needed for single-node workflows
- No `start_node` needed - execution begins with the first (only) node
- Template variables can be used in params: `"message": "$greeting"`
