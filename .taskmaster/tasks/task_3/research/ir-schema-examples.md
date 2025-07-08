# IR Schema Examples for Task 3

## Overview
Task 3 requires creating a sample 'hello_workflow.json' file that conforms to the IR schema. These examples from the current context show the proper format.

## Minimal IR Structure (from examples/core/minimal.json)
```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "hello",
      "type": "echo",
      "params": {
        "message": "Hello, pflow!"
      }
    }
  ]
}
```

## Simple Pipeline Structure (Referenced in schemas.md)
For a read-file => write-file workflow:
```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "read",
      "type": "read-file",
      "params": {
        "file_path": "input.txt"
      }
    },
    {
      "id": "write",
      "type": "write-file",
      "params": {
        "file_path": "output.txt"
      }
    }
  ],
  "edges": [
    {"from": "read", "to": "write"}
  ]
}
```

## Key Requirements (from schemas.md)
- `ir_version` is required (use "0.1.0")
- `nodes` array is required with at least one node
- Each node needs: `id` (unique), `type` (registry name)
- `edges` array defines connections with `from` and `to`
- `params` are optional node-specific configuration

## Node Naming Convention
From Task 11 details: "Each node should have explicit name attribute (e.g., class ReadFileNode(BaseNode): name = 'read-file')"
- Use kebab-case for node types in IR: "read-file", "write-file"
