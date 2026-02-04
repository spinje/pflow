# Working with JSON Workflows

> **⚠️ Historical Document**: JSON workflows were replaced by the markdown format (`.pflow.md`) in Task 107. This guide is preserved for historical reference only. For the current workflow format, see the [format specification](../../.taskmaster/tasks/task_107/starting-context/format-specification.md) and the agent instructions (`pflow instructions usage`).

While pflow excels at natural language workflow creation, you can also define workflows directly in JSON format for precise control and version management.

## Quick Start

### Minimal Valid Workflow

The simplest valid workflow JSON requires only two fields:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "hello",
      "type": "shell",
      "params": {
        "command": "echo 'Hello, World!'"
      }
    }
  ]
}
```

Save this as `hello.json` and run:
```bash
pflow hello.json
```

## Important Requirements

### Required Fields

1. **`ir_version`** (REQUIRED) - Must be `"0.1.0"`
   - Without this field, pflow won't recognize your JSON as a workflow
   - The error message will mention falling back to the planner

2. **`nodes`** (REQUIRED) - Array of node definitions
   - Each node needs: `id`, `type`, and optionally `params`

### Optional Fields

- **`edges`** - Array of connections between nodes (defaults to `[]` for single-node workflows)
- **`metadata`** - Workflow metadata (name, description, author, etc.)
- **`inputs`** - Define workflow parameters with types and defaults
- **`outputs`** - Map internal values to workflow outputs
- **`trigger_node`** - Specify which node starts the workflow

### Common Mistakes

**DON'T add these fields at the root level:**
- `name` - Use metadata.name instead
- `description` - Use metadata.description instead
- `output_key` - Use outputs array instead
- `input_params` - Use inputs with proper schema

**Wrong:**
```json
{
  "name": "my-workflow",  // Not allowed at root
  "description": "...",    // Not allowed at root
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
    "name": "my-workflow",      // Inside metadata
    "description": "..."         // Inside metadata
  },
  "nodes": [...],
  "edges": []
}
```

## Available Node Types

pflow provides these core node types:

| Type | Description |
|------|-------------|
| `shell` | Execute shell commands |
| `http` | Make HTTP requests |
| `llm` | Call LLM models (via llm library) |
| `read-file` | Read file contents |
| `write-file` | Write content to file |
| `copy-file` | Copy files |
| `move-file` | Move files |
| `delete-file` | Delete files |
| `mcp-*` | MCP tool bridge nodes |

## Accessing Output

Node outputs are namespaced under the node ID. To access the output:

```bash
# If your node has id "read-file"
pflow workflow.json --output-key read-file

# The node stores data at:
# - {node-id}.result (standard output)
# - {node-id}.{specific-keys} (node-specific outputs)
```

## Template Variables

Use template variables to pass data between nodes. Outputs are namespaced by node ID:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "fetch",
      "type": "http",
      "params": {
        "url": "https://api.example.com/data"
      }
    },
    {
      "id": "process",
      "type": "llm",
      "params": {
        "prompt": "Summarize this data: ${fetch.response}"
      }
    }
  ],
  "edges": [
    {"from": "fetch", "to": "process"}
  ]
}
```

**Template syntax**: `${node-id.output-key}` or `${node-id.output-key.nested.path}`

For complete template syntax and type preservation rules, see the [Template Variables Reference](../reference/template-variables.md).

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
  ]
}
```

First, register the MCP server:
```bash
# Add filesystem MCP server
pflow mcp add filesystem npx -- -y @modelcontextprotocol/server-filesystem /tmp

# Sync to discover tools
pflow mcp sync filesystem

# Now run your workflow
pflow mcp-workflow.json --output-key read-file
```

## Multi-Node Workflows

Connect nodes using edges:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "fetch",
      "type": "http",
      "params": {
        "url": "https://api.example.com/data"
      }
    },
    {
      "id": "process",
      "type": "llm",
      "params": {
        "prompt": "Summarize this data: ${fetch.response}"
      }
    }
  ],
  "edges": [
    {"from": "fetch", "to": "process"}
  ]
}
```

## Batch Processing

Nodes can process arrays of items using the `batch` configuration:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "list-files",
      "type": "shell",
      "params": {
        "command": "find . -name '*.txt' -type f"
      }
    },
    {
      "id": "summarize",
      "type": "llm",
      "params": {
        "prompt": "Summarize: ${file.content}"
      },
      "batch": {
        "items": "${list-files.files}",
        "as": "file",
        "parallel": true,
        "max_concurrent": 5
      }
    }
  ],
  "edges": [
    {"from": "list-files", "to": "summarize"}
  ]
}
```

For batch configuration options, see the [IR Schema Reference](../reference/ir-schema.md#batch-processing-configuration).

## Full Schema Reference

For complete documentation of all available fields, see [IR Schema Documentation](../reference/ir-schema.md).

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

4. **Template not resolving?**
   - Use the `${node-id.output-key}` format
   - Check that the source node runs before the consuming node
   - Use `pflow validate workflow.json` to check templates

## Examples

See the `examples/` directory for more workflow JSON examples:

### Core Examples (`examples/core/`)
- [`examples/core/minimal.json`](../../examples/core/minimal.json) - Simplest valid workflow
- [`examples/core/simple-pipeline.json`](../../examples/core/simple-pipeline.json) - Multi-node pipeline with edges
- [`examples/core/template-variables.json`](../../examples/core/template-variables.json) - Template variable usage

### MCP Examples
- [`examples/mcp-filesystem.json`](../../examples/mcp-filesystem.json) - MCP filesystem operations

### Advanced Examples (`examples/advanced/`)
- [`examples/advanced/content-pipeline.json`](../../examples/advanced/content-pipeline.json) - Multi-stage content generation
- [`examples/advanced/github-workflow.json`](../../examples/advanced/github-workflow.json) - GitHub API automation
