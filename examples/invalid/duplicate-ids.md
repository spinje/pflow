# Duplicate IDs Example

## What's Wrong
Two nodes have the same ID ("processor"), which violates the uniqueness requirement.

## Expected Error
```
ValidationError: Validation error at nodes[1].id: Duplicate node ID 'processor'
Use unique IDs for each node
```

## How to Fix
Give each node a unique identifier:
```json
{
  "id": "processor",      // Keep this
  "type": "transform",
  ...
},
{
  "id": "validator",      // Change to unique ID
  "type": "validate",
  ...
}
```

## Why This Matters
Unique IDs are essential for:
- Edge references to work correctly
- Debugging and error messages
- Node state tracking during execution
