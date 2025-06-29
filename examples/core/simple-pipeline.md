# Simple Pipeline Example

## Purpose
This example demonstrates a basic 3-node sequential pipeline. It shows:
- Multiple nodes working together
- Edge connections defining flow order
- A complete read → transform → write pattern

## Use Case
This pattern is fundamental for:
- File processing workflows
- Data transformation pipelines
- ETL (Extract, Transform, Load) operations

## Visual Flow
```
[reader: read-file] → [transformer: uppercase] → [writer: write-file]
```

## Node Explanation
1. **reader**: Reads content from a file
   - `type`: "read-file" - Reads file content into shared store
   - `params.path`: Source file location

2. **transformer**: Transforms the content
   - `type`: "uppercase" - Converts text to uppercase
   - `params`: Empty - uses default behavior

3. **writer**: Writes transformed content
   - `type`: "write-file" - Writes content to file
   - `params.path`: Destination file location

## Edge Flow
- `reader → transformer`: Passes file content
- `transformer → writer`: Passes transformed content

## How to Validate
```python
from pflow.core import validate_ir
import json

with open('simple-pipeline.json') as f:
    ir = json.load(f)
    validate_ir(ir)  # Should pass without errors
```

## Common Variations
1. **Different transformations**: Replace "uppercase" with other processors
2. **Multiple transformers**: Chain several transformations together
3. **Conditional paths**: Add error handling edges with actions
4. **Parallel processing**: Multiple edges from one node

## Notes
- Edges define execution order
- Data flows through the shared store between nodes
- No explicit start_node - begins with "reader" (first in array)
