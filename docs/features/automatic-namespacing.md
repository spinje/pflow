# Automatic Namespacing

## Overview

Automatic namespacing is a feature that prevents output collisions between nodes by isolating each node's outputs in its own namespace within the shared store. This enables workflows to use multiple instances of the same node type without data being overwritten.

## The Problem

Without namespacing, when multiple nodes of the same type write to the same shared store key, data gets overwritten:

```json
{
  "nodes": [
    {"id": "fetch1", "type": "github-get-issue", "params": {"issue": "123"}},
    {"id": "fetch2", "type": "github-get-issue", "params": {"issue": "456"}}
  ]
}
```

Both nodes write to `shared["issue_data"]`, so `fetch2` overwrites `fetch1`'s data.

## The Solution

With automatic namespacing enabled, each node's outputs are isolated:
- `fetch1` writes to `shared["fetch1"]["issue_data"]`
- `fetch2` writes to `shared["fetch2"]["issue_data"]`

No collisions occur, and all data is preserved.

## Enabling Namespacing

Add `"enable_namespacing": true` to your workflow IR:

```json
{
  "ir_version": "0.1.0",
  "enable_namespacing": true,
  "nodes": [
    {"id": "fetch1", "type": "github-get-issue", "params": {"issue": "123"}},
    {"id": "fetch2", "type": "github-get-issue", "params": {"issue": "456"}},
    {"id": "compare", "type": "llm", "params": {
      "prompt": "Compare:\n1: $fetch1.issue_data.title\n2: $fetch2.issue_data.title"
    }}
  ],
  "edges": [
    {"from": "fetch1", "to": "fetch2"},
    {"from": "fetch2", "to": "compare"}
  ]
}
```

## Template Variable Syntax

With namespacing, reference node outputs using the pattern `$node_id.output_key`:
- `$fetch1.issue_data` - Access fetch1's issue_data
- `$fetch1.issue_data.title` - Access nested fields
- `$fetch2.issue_data.user.login` - Deep path access

## How It Works

1. **Node Execution**: When a node runs, it gets a namespaced view of the shared store
2. **Writes**: All writes go to `shared[node_id][key]`
3. **Reads**: Nodes check their namespace first, then fall back to root level
4. **Template Resolution**: Template variables can access any namespace using dot notation

## Backward Compatibility

- **Default**: Namespacing is disabled by default (`enable_namespacing: false`)
- **CLI Inputs**: Data from CLI remains at root level and is accessible to all nodes
- **Legacy Workflows**: Existing workflows continue to work without changes
- **Gradual Migration**: Enable namespacing per workflow as needed

## Benefits

1. **No Collisions**: Multiple instances of the same node type work perfectly
2. **Clear Data Lineage**: Easy to trace which node produced which data
3. **Powerful Workflows**: No artificial limitations on node usage
4. **Debugging**: Clear visualization of data flow in shared store

## Example: Multiple API Calls

```json
{
  "ir_version": "0.1.0",
  "enable_namespacing": true,
  "nodes": [
    {"id": "github", "type": "api-call", "params": {"url": "https://api.github.com/..."}},
    {"id": "gitlab", "type": "api-call", "params": {"url": "https://gitlab.com/api/..."}},
    {"id": "analyze", "type": "llm", "params": {
      "prompt": "Compare GitHub ($github.response) vs GitLab ($gitlab.response)"
    }}
  ]
}
```

Each API call's response is preserved in its own namespace, allowing the LLM to access both.

## Shared Store Structure

Without namespacing:
```python
shared = {
  "response": "...",      # Last API call overwrites previous
  "issue_data": {...},    # Last issue fetch overwrites previous
}
```

With namespacing:
```python
shared = {
  "github": {
    "response": "..."     # GitHub API response
  },
  "gitlab": {
    "response": "..."     # GitLab API response
  },
  "stdin": "..."          # CLI input remains at root
}
```

## Migration Guide

To migrate existing workflows to use namespacing:

1. Add `"enable_namespacing": true` to the workflow IR
2. Update template variables to use node ID prefixes:
   - Change: `$issue_data`
   - To: `$node_id.issue_data`
3. Test the workflow to ensure correct data flow

## Technical Implementation

The feature is implemented through:
- `NamespacedSharedStore`: A proxy that redirects writes to namespaced locations
- `NamespacedNodeWrapper`: Wraps nodes to provide namespaced store access
- Compiler integration: Automatically applies wrapping when enabled
- Template resolver: Already supports path-based access (`$node.key`)

## When to Use Namespacing

Enable namespacing when:
- Using multiple instances of the same node type
- Building complex workflows with many nodes
- Need clear data lineage and debugging
- Want to avoid collision workarounds

Keep namespacing disabled when:
- Simple linear workflows with unique node types
- Maximum backward compatibility needed
- Minimal workflow complexity

## Future Enhancements

- Automatic collision detection and warning
- Migration tooling for existing workflows
- Namespace visualization in debugging output
- Performance optimizations for large namespaces