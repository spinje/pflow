# Proxy Mappings Example

## Purpose
This example demonstrates the NodeAwareSharedStore proxy pattern for handling incompatible node interfaces. It shows:
- How to map between different key names nodes expect
- Input and output transformations
- Enabling node reuse without modification

## Use Case
Proxy mappings are crucial when:
- Integrating nodes with different naming conventions
- Reusing nodes designed for different contexts
- Building adapters between incompatible components
- Creating clean interfaces between workflow stages
- Connecting file operations with test nodes

## Visual Flow
```
[read-file] → [test_processor] → [write-file]
     ↓              ↓                 ↓
content ──┐    test_input      processed_content
          └─►  test_output ──┐       content
                            └─►
```

## Node Interfaces
1. **read-file** outputs:
   - `content`: The file content
   - `error`: Error message if read failed

2. **test_processor** expects:
   - Input: `test_input` (but reader provides `content`)
   - Output: `test_output` (but writer needs `processed_content`)

3. **write-file** expects:
   - `content`: The content to write
   - `file_path`: Destination path

## Mapping Configuration
```json
"mappings": {
  "test_processor": {
    "input_mappings": {
      "test_input": "content"  // test_processor.test_input = shared["content"]
    },
    "output_mappings": {
      "test_output": "processed_content"  // shared["processed_content"] = test_processor.test_output
    }
  },
  "writer": {
    "input_mappings": {
      "content": "processed_content"  // writer.content = shared["processed_content"]
    }
  }
}
```

## How Proxy Mappings Work
1. **Before node execution**: Input mappings transform shared store keys
2. **After node execution**: Output mappings transform node outputs
3. **Transparent to nodes**: Nodes don't know about the mappings

## How to Validate
```python
from pflow.core import validate_ir
import json

with open('proxy-mappings.json') as f:
    ir = json.load(f)
    validate_ir(ir)  # Should pass without errors
```

## Common Variations
1. **Multiple input sources**: Map multiple shared keys to one node input
2. **Output fanout**: Map one output to multiple shared keys
3. **Nested mappings**: Handle complex object transformations
4. **Conditional mappings**: Different mappings based on node state

## When to Use Proxy Mappings
- **DO**: When integrating existing nodes with different interfaces
- **DO**: To create cleaner workflow interfaces
- **DON'T**: For simple workflows where nodes naturally connect
- **DON'T**: When it adds unnecessary complexity

## Notes
- Mappings are optional - only use when needed
- Each node can have both input and output mappings
- Mappings reference shared store keys, not node IDs
- The proxy pattern enables maximum node reusability
