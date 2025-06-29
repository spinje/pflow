# Wrong Types Example

## What's Wrong
Multiple type errors:
1. `ir_version` is a number instead of string
2. `nodes` is an object instead of array
3. `edges` is a string instead of array
4. `params` is a string instead of object

## Expected Error
The first error encountered:
```
ValidationError: Validation error at ir_version: '1.0' does not match '^\\d+\\.\\d+\\.\\d+$'
Use semantic versioning format, e.g., '0.1.0'
```

## How to Fix
Correct all type issues:
```json
{
  "ir_version": "1.0.0",    // String with semver format
  "nodes": [                 // Array, not object
    {
      "id": "n1",           // Add required id field
      "type": "test",
      "params": {}          // Object, not string
    }
  ],
  "edges": []               // Array, not string
}
```

## Why This Matters
Correct types ensure:
- Consistent parsing across tools
- Predictable data structures
- Clear error messages
- Proper validation
