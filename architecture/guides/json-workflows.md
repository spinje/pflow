# Working with JSON Workflows

While pflow excels at natural language workflow creation, you can also define workflows directly in JSON format for precise control and version management.

## Quick Start

### Minimal Valid Workflow

The simplest valid workflow JSON requires only three fields:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "my-node",
      "type": "echo",
      "params": {
        "message": "Hello, World!"
      }
    }
  ],
  "edges": []
}
```

Save this as `hello.json` and run:
```bash
pflow --file hello.json
```

## Important Requirements

### ⚠️ Required Fields

1. **`ir_version`** (REQUIRED) - Must be `"0.1.0"`
   - Without this field, pflow won't recognize your JSON as a workflow
   - The error message will mention falling back to the planner

2. **`nodes`** (REQUIRED) - Array of node definitions
   - Each node needs: `id`, `type`, and optionally `params`

3. **`edges`** (REQUIRED) - Array of connections between nodes
   - Can be empty `[]` for single-node workflows

### ❌ Common Mistakes

**DON'T add these fields at the root level:**
- `name` - Use metadata.name instead
- `description` - Use metadata.description instead
- `output_key` - Use outputs array instead
- `input_params` - Use input_params with proper schema

**Wrong:**
```json
{
  "name": "my-workflow",  // ❌ Not allowed at root
  "description": "...",    // ❌ Not allowed at root
  "ir_version": "0.1.0",
  "nodes": [...],
  "edges": []
}
```

**Correct:**
```json
{
  "ir_version": "0.1.0",
  "metadata": {
    "name": "my-workflow",      // ✅ Inside metadata
    "description": "..."         // ✅ Inside metadata
  },
  "nodes": [...],
  "edges": []
}
```

## Accessing Output

Node outputs are namespaced under the node ID. To access the output:

```bash
# If your node has id "read-file"
pflow --file workflow.json --output-key read-file

# The node stores data at:
# - {node-id}.result (standard output)
# - {node-id}.{specific-keys} (node-specific outputs)
```

## MCP Workflows

With MCP (Model Context Protocol) support, you can use any registered MCP tool:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "read-file",
      "type": "mcp-filesystem-read_text_file",
      "params": {
        "path": "/path/to/file.txt"
      }
    }
  ],
  "edges": []
}
```

First, register the MCP server:
```bash
# Add filesystem MCP server
pflow mcp add filesystem npx -- -y @modelcontextprotocol/server-filesystem /tmp

# Sync to discover tools
pflow mcp sync filesystem

# Now run your workflow
pflow --file mcp-workflow.json --output-key read-file
```

## Multi-Node Workflows

Connect nodes using edges:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "fetch",
      "type": "fetch-url",
      "params": {
        "url": "https://api.example.com/data"
      }
    },
    {
      "id": "process",
      "type": "llm",
      "params": {
        "prompt": "Summarize this data: ${content}"
      }
    }
  ],
  "edges": [
    {
      "source": "fetch",
      "target": "process",
      "action": "default"
    }
  ]
}
```

## Full Schema Reference

For complete documentation of all available fields, see [IR Schema Documentation](../reference/ir-schema.md).

### Optional Fields

- `metadata` - Workflow metadata (name, description, author, etc.)
- `input_params` - Define workflow parameters with types and defaults
- `outputs` - Map internal values to workflow outputs
- `trigger_node` - Specify which node starts the workflow

## Debugging Tips

1. **Workflow not recognized?**
   - Check for `"ir_version": "0.1.0"`
   - Remove any extra fields not in the schema
   - Use `--verbose` flag for detailed errors

2. **Output not found?**
   - Remember outputs are namespaced under node IDs
   - Use `--output-key {node-id}` to see all node outputs
   - Check the shared store structure with verbose mode

3. **Validation errors?**
   - The IR schema is strict about allowed fields
   - Move descriptive fields into `metadata` object
   - Ensure all node types are registered in the registry

## Examples

See the `examples/` directory for more workflow JSON examples:
- `examples/simple-llm.json` - Basic LLM workflow
- `examples/multi-step.json` - Multi-node workflow with edges
- `examples/mcp-filesystem.json` - MCP filesystem operations
- `examples/github-automation.json` - GitHub API automation