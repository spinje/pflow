# Simple Pipeline Example

## Purpose
This example demonstrates a basic 3-node sequential pipeline. It shows:
- Multiple nodes working together
- Edge connections defining flow order
- A complete read → copy → write pattern using MVP file operations

## Use Case
This pattern is fundamental for:
- File processing workflows
- Backup operations
- File management pipelines

## Visual Flow
```
[reader: read-file] → [copier: copy-file] → [writer: write-file]
```

## Node Explanation
1. **reader**: Reads content from a file
   - `type`: "read-file" - Reads file content into shared store
   - `params.file_path`: Source file location

2. **copier**: Creates a backup copy
   - `type`: "copy-file" - Copies the file content
   - `params.destination`: Backup file location

3. **writer**: Writes content to final destination
   - `type`: "write-file" - Writes content to file
   - `params.file_path`: Destination file location

## Edge Flow
- `reader → copier`: Passes file content
- `copier → writer`: Passes content for final write

## How to Validate
```python
from pflow.core import validate_ir
import json

with open('simple-pipeline.json') as f:
    ir = json.load(f)
    validate_ir(ir)  # Should pass without errors
```

## Common Variations
1. **Different file operations**: Use "move-file" or "delete-file" nodes
2. **Multiple operations**: Chain several file operations together
3. **Conditional paths**: Add error handling edges with actions
4. **Direct copy**: Skip the writer and just use reader → copier

## Notes
- Edges define execution order
- Data flows through the shared store between nodes
- No explicit start_node - begins with "reader" (first in array)
