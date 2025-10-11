# Final MCP Server Implementation Specification

## Design Philosophy
- **Clean Interface**: No unnecessary parameters, sensible defaults
- **Agent-Optimized**: Always return JSON, never auto-repair, include debugging info
- **Direct Service Integration**: Use pflow services directly, not CLI wrapping

## Core Tool Set (13 Tools Total)

### Priority 1: Core Workflow Loop (6 Tools)

#### 1. `workflow_discover`
```python
{
  "name": "workflow_discover",
  "description": "Find existing workflows matching a request. Always run first.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "Task description"}
    },
    "required": ["query"]
  }
}

# Returns: Matches with confidence scores, inputs/outputs, reasoning
# Note: Uses LLM for intelligent matching
```

#### 2. `registry_discover`
```python
{
  "name": "registry_discover",
  "description": "Find nodes for building workflows using intelligent selection.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "task": {"type": "string", "description": "What needs to be built"}
    },
    "required": ["task"]
  }
}

# Returns: Complete node specifications with interfaces
# Note: Uses LLM for selection
```

#### 3. `registry_run`
```python
{
  "name": "registry_run",
  "description": "Test a node to reveal actual output structure.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "node_type": {"type": "string"},
      "parameters": {"type": "object", "default": {}}
    },
    "required": ["node_type"]
  }
}

# Always returns complete structure (no show_structure flag needed)
# Critical for MCP nodes where docs show "Any" but output is nested
```

#### 4. `workflow_execute`
```python
{
  "name": "workflow_execute",
  "description": "Execute a workflow with structured output.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "workflow": {"type": ["string", "object"], "description": "Name, path, or IR"},
      "parameters": {"type": "object", "default": {}}
    },
    "required": ["workflow"]
  }
}

# Built-in behaviors (no flags needed):
# - JSON output format
# - No auto-repair (explicit errors)
# - Trace saved to ~/.pflow/debug/
# Returns: Structured result with outputs, errors, trace path
```

#### 5. `workflow_validate`
```python
{
  "name": "workflow_validate",
  "description": "Validate workflow structure without execution.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "workflow": {"type": ["string", "object"]}
    },
    "required": ["workflow"]
  }
}

# Returns: Valid flag and detailed errors with suggestions
```

#### 6. `workflow_save`
```python
{
  "name": "workflow_save",
  "description": "Save workflow to global library.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "workflow_file": {"type": "string"},
      "name": {"type": "string", "description": "lowercase-with-hyphens"},
      "description": {"type": "string"}
    },
    "required": ["workflow_file", "name", "description"]
  }
}

# Simplified: No generate_metadata or delete_draft flags
# Can add metadata generation by default if valuable
```

### Priority 2: Supporting Tools (5 Tools)

#### 7. `registry_describe`
```python
{
  "name": "registry_describe",
  "description": "Get detailed specifications for specific nodes.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "nodes": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["nodes"]
  }
}
```

#### 8. `registry_search`
```python
{
  "name": "registry_search",
  "description": "Search for nodes by pattern.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "pattern": {"type": "string"}
    },
    "required": ["pattern"]
  }
}
```

#### 9. `workflow_list`
```python
{
  "name": "workflow_list",
  "description": "List saved workflows.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "filter": {"type": "string", "description": "Optional filter"}
    }
  }
}
```

#### 10. `settings_set`
```python
{
  "name": "settings_set",
  "description": "Set API keys and credentials.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "key": {"type": "string"},
      "value": {"type": "string"}
    },
    "required": ["key", "value"]
  }
}
```

#### 11. `settings_get`
```python
{
  "name": "settings_get",
  "description": "Get setting value.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "key": {"type": "string"}
    },
    "required": ["key"]
  }
}
```

### Priority 3: Advanced Tools (2 Tools)

#### 12. `registry_list`
```python
{
  "name": "registry_list",
  "description": "List all nodes (warning: returns hundreds).",
  "inputSchema": {
    "type": "object",
    "properties": {}
  }
}
```

#### 13. `trace_read`
```python
{
  "name": "trace_read",
  "description": "Read execution trace for debugging.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "trace_file": {"type": "string", "description": "Path or 'latest'"}
    }
  }
}

# Parses trace JSON and returns structured data
```

## Implementation Details

### Built-in Behaviors (No Parameters Needed)

All tools automatically:
- Return JSON structures (no format parameter)
- Include error details (no verbose flag)
- Disable auto-repair (no repair flag)
- Save traces where applicable (no trace flag)
- Auto-normalize workflows (add ir_version, edges)

### Tool Response Patterns

**Success Response**:
```json
{
  "success": true,
  "data": {...},
  "trace_path": "/path/to/trace" // if applicable
}
```

**Error Response**:
```json
{
  "success": false,
  "error": {
    "type": "validation|execution|not_found",
    "message": "Human readable message",
    "details": {...},
    "suggestions": ["Try this", "Or this"]
  }
}
```

### Implementation Using FastMCP

```python
from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server
import asyncio

mcp = FastMCP("pflow", version="0.1.0")

@mcp.tool()
async def workflow_discover(query: str) -> dict:
    """Find existing workflows matching a request."""
    from pflow.planning.nodes import WorkflowDiscoveryNode
    from pflow.core.workflow_manager import WorkflowManager

    # Direct node reuse pattern
    node = WorkflowDiscoveryNode()
    shared = {
        "user_input": query,
        "workflow_manager": WorkflowManager()
    }

    # Run in thread pool (sync code)
    result = await asyncio.to_thread(node.run, shared)

    # Format response
    return {
        "success": True,
        "matches": shared.get("discovery_result", [])
    }

@mcp.tool()
async def workflow_execute(workflow: str | dict, parameters: dict = None) -> dict:
    """Execute workflow with agent-optimized defaults."""
    from pflow.execution.workflow_execution import execute_workflow
    from pflow.execution.null_output import NullOutput

    # Resolve workflow
    workflow_ir = resolve_workflow(workflow)  # helper function

    # Execute with built-in agent defaults
    result = await asyncio.to_thread(
        execute_workflow,
        workflow_ir=workflow_ir,
        execution_params=parameters or {},
        output=NullOutput(),      # No CLI output
        enable_repair=False,       # No auto-repair
        # trace automatically saved
    )

    if result.success:
        return {
            "success": True,
            "outputs": result.output_data,
            "trace_path": f"~/.pflow/debug/workflow-trace-{timestamp}.json"
        }
    else:
        return {
            "success": False,
            "error": format_error(result),  # Include details, suggestions
            "checkpoint": result.shared_after.get("__execution__"),
            "trace_path": f"~/.pflow/debug/workflow-trace-{timestamp}.json"
        }

# Server startup
async def run_server():
    async with stdio_server() as streams:
        await mcp.run(streams[0], streams[1])

if __name__ == "__main__":
    asyncio.run(run_server())
```

### CLI Integration

```python
# src/pflow/cli/commands/serve.py
@click.group()
def serve():
    """Run pflow as a server."""
    pass

@serve.command()
def mcp():
    """Run as MCP server (stdio transport)."""
    from pflow.mcp_server import run_server
    asyncio.run(run_server())
```

## File Structure

```
src/pflow/mcp_server/
├── __init__.py
├── server.py          # FastMCP server with all tool registrations
├── tools/
│   ├── discovery.py   # workflow_discover, registry_discover
│   ├── execution.py   # workflow_execute, workflow_validate
│   ├── registry.py    # registry_run, describe, search, list
│   ├── workflow.py    # workflow_save, workflow_list
│   ├── settings.py    # settings_set, settings_get
│   └── trace.py      # trace_read
└── utils/
    ├── resolver.py    # Workflow resolution logic
    └── security.py    # Path validation
```

## Key Simplifications from Previous Spec

1. **No natural language execution tool** - Agents use individual steps
2. **No agent mode parameters** - Built-in defaults for all tools
3. **No optional flags** - Clean interface, sensible defaults
4. **13 tools instead of 14** - Removed complex natural language tool
5. **Simplified workflow_save** - No metadata/delete flags

## Implementation Timeline

- **Phase 1** (2 days): Priority 1 tools (core loop)
- **Phase 2** (1 day): Priority 2 tools (supporting)
- **Phase 3** (1 day): Testing and validation
- **Phase 4** (0.5 day): Priority 3 tools if time permits

**Total: 4.5 days**

## Success Metrics

MCP server is successful when agents can:
1. Discover workflows without rebuilding (≥95% confidence = use existing)
2. Build new workflows with discovered nodes
3. Test MCP nodes to reveal nested structures
4. Validate before execution
5. Execute with full error details
6. Save for reuse

The interface is clean, defaults are sensible, and agents don't need to manage flags.