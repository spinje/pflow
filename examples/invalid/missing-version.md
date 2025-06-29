# Missing Version Example

## What's Wrong
This IR is missing the required `ir_version` field at the root level.

## Expected Error
```
ValidationError: Validation error at root: 'ir_version' is a required property
Add the required field 'ir_version'
```

## How to Fix
Add the version field:
```json
{
  "ir_version": "0.1.0",  // Add this line
  "nodes": [...]
}
```

## Why This Matters
The version field enables:
- Schema evolution over time
- Backward compatibility checking
- Clear version requirements for tools
