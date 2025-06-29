# Bad Edge Reference Example

## What's Wrong
The edges reference a node "middle" that doesn't exist in the nodes array.

## Expected Error
```
ValidationError: Validation error at edges[0].to: Edge references non-existent node 'middle'
Change to one of: ['end', 'start']
```

## How to Fix
Either:
1. Add the missing node:
```json
"nodes": [
  {"id": "start", ...},
  {"id": "middle", ...},  // Add this
  {"id": "end", ...}
]
```

2. Or fix the edge reference:
```json
"edges": [
  {
    "from": "start",
    "to": "end"  // Direct connection
  }
]
```

## Why This Matters
Valid node references ensure:
- Workflow can be executed
- No runtime failures from missing nodes
- Clear flow visualization
