# MCP Implementation Strategy for pflow

## Vision

Users configure MCP servers once, then all tools from those servers become available as workflow nodes - each appearing as a distinct node in the registry but all executing through a single MCPNode implementation.

```
Configure server → Discover tools → Create virtual registry entries → Execute via MCPNode
```

## Verified Technical Foundation

Based on official documentation and testing:
- **Protocol**: JSON-RPC 2.0 over newline-delimited messages (stdio)
- **SDK**: Async-only Python implementation (`mcp` package)
- **Handshake**: Required `initialize` method before any operations
- **Tool Discovery**: Via `tools/list` method returning JSON schemas
- **Testing**: MCP Inspector available via `npx @modelcontextprotocol/inspector`

## Implementation Architecture

### 1. Configuration System

Location: `~/.pflow/mcp-servers.json` (following pflow's existing pattern)

```json
{
  "servers": {
    "github": {
      "transport": "stdio",
      "command": "npx",
      "args": ["@modelcontextprotocol/github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      }
    },
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["@modelcontextprotocol/server-filesystem", "/path"],
      "env": {}
    }
  }
}
```

**MVP Scope**: stdio transport only (HTTP/SSE in future phases)

### 2. Registry Integration with Compiler Enhancement

The solution combines registry manipulation with minimal compiler changes:

**Registry Update** (`src/pflow/mcp/registrar.py`):
```python
class MCPRegistrar:
    """Updates registry with virtual MCP nodes."""

    def sync_server(self, server_name: str):
        # Load existing registry
        registry = Registry()
        nodes = registry.load()

        # Discover tools via MCP protocol
        tools = self._discover_tools(server_name)

        # Add virtual entries
        for tool in tools:
            node_name = f"mcp-{server_name}-{tool.name}"
            nodes[node_name] = {
                "class_name": "MCPNode",
                "module": "pflow.nodes.mcp.node",
                "file_path": "virtual://mcp",  # Non-existent but valid
                "interface": {
                    "description": tool.description,
                    "params": self._convert_schema(tool.inputSchema),
                    "outputs": self._convert_schema(tool.outputSchema),
                    "actions": ["default", "error"]
                }
            }

        registry.save(nodes)
```

**Compiler Enhancement** (`src/pflow/runtime/compiler.py`, line ~291):
```python
# Existing code for special parameters
if node_type == "nested-workflow":
    params["__registry__"] = registry

# NEW: Add MCP metadata injection (3 lines)
if node_type.startswith("mcp-"):
    params["__mcp_server__"] = node_type.split("-")[1]
    params["__mcp_tool__"] = "-".join(node_type.split("-")[2:])
```

### 3. The MCPNode Implementation

Single node class handling all MCP tools with async-to-sync wrapper:

```python
# src/pflow/nodes/mcp/node.py
import asyncio
from typing import Any, Dict
from pocketflow import Node

class MCPNode(Node):
    """Universal MCP node executing any MCP tool."""

    def __init__(self):
        super().__init__(max_retries=3, wait=1.0)
        # No connection pooling in MVP

    def prep(self, shared: dict) -> dict:
        # Get server/tool from compiler-injected params
        server = self.params.get("__mcp_server__")
        tool = self.params.get("__mcp_tool__")

        # Load server configuration
        config = self._load_server_config(server)

        # Prepare tool arguments from user params
        tool_args = {k: v for k, v in self.params.items()
                    if not k.startswith("__")}

        return {
            "server": server,
            "tool": tool,
            "config": config,
            "arguments": tool_args
        }

    def exec(self, prep_res: dict) -> dict:
        """Execute MCP tool using async-to-sync wrapper."""
        # Run async code in sync context
        return asyncio.run(self._exec_async(prep_res))

    async def _exec_async(self, prep_res: dict) -> dict:
        """Async implementation using MCP protocol."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        # Start server subprocess
        params = StdioServerParameters(
            command=prep_res["config"]["command"],
            args=prep_res["config"]["args"],
            env=prep_res["config"].get("env", {})
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize handshake
                await session.initialize()

                # Call tool
                result = await session.call_tool(
                    prep_res["tool"],
                    prep_res["arguments"]
                )

                # Extract text content (MVP: text only)
                for content in result.content or []:
                    if hasattr(content, 'text'):
                        return {"result": content.text}

                return {"result": str(result)}

    def post(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        """Store results in shared store."""
        if "error" in exec_res:
            shared["error"] = exec_res["error"]
            return "error"

        shared["result"] = exec_res.get("result")
        return "default"
```

### 4. CLI Commands

```bash
# Configure server
$ pflow mcp add github -- npx @modelcontextprotocol/github

# List servers
$ pflow mcp list

# Discover and register tools
$ pflow mcp sync github

# Remove server
$ pflow mcp remove github
```

### 5. Discovery Implementation

```python
# src/pflow/mcp/discovery.py
import asyncio
from typing import List, Dict

class MCPDiscovery:
    """Discovers tools from MCP servers."""

    def discover_tools(self, server_name: str) -> List[Dict]:
        """Synchronous wrapper for tool discovery."""
        return asyncio.run(self._discover_async(server_name))

    async def _discover_async(self, server_name: str) -> List[Dict]:
        """Async tool discovery using MCP protocol."""
        config = self._load_config(server_name)

        # Import MCP SDK
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=config["command"],
            args=config["args"],
            env=config.get("env", {})
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_response = await session.list_tools()

                return [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.inputSchema.model_dump()
                            if hasattr(tool.inputSchema, 'model_dump') else {},
                        "outputSchema": tool.outputSchema.model_dump()
                            if hasattr(tool, 'outputSchema') and tool.outputSchema else None
                    }
                    for tool in tools_response.tools
                ]
```

## Implementation Phases

### Phase 1: MVP (2-3 days)
✅ Test with official SDK to understand protocol
✅ Minimal MCPNode with async wrapper
✅ Registry direct manipulation
✅ Compiler enhancement (3 lines)
✅ Basic CLI commands
✅ stdio transport only
❌ No connection pooling
❌ No OAuth/auth support

### Phase 2: Enhancement (1 week)
- Connection pooling for performance
- Error handling improvements
- HTTP/SSE transport support
- Authentication mechanisms

### Phase 3: Future (as needed)
- Auto-discovery of servers
- Project/local scopes
- Third-party server marketplace

## Simplified MVP Approach

**What we're building**:
1. One MCPNode class that reads metadata from params
2. Three-line compiler change to inject metadata
3. CLI commands to configure and sync servers
4. Direct registry updates (no scanner changes)

**What we're NOT building (yet)**:
- Connection pooling
- HTTP/SSE transports
- OAuth authentication
- Auto-discovery
- Complex error recovery

## Testing Strategy

### Before Implementation
1. Use MCP Inspector to understand servers
2. Build test client with official SDK
3. Capture protocol messages
4. Test async-to-sync wrapper

### During Implementation
1. Test with filesystem server (safe, local)
2. Test with mock server
3. Verify registry updates
4. Test natural language planning

## Key Design Decisions

### Virtual Registry Entries
- **Why**: Better discoverability for planner and users
- **How**: Direct registry manipulation, no Python files needed
- **Trade-off**: Registry size grows with number of tools

### Single MCPNode Class
- **Why**: Simplicity and maintainability
- **How**: Metadata injection via compiler
- **Trade-off**: Less type safety but much simpler

### Async-to-Sync Wrapper
- **Why**: pflow nodes are synchronous, MCP SDK is async
- **How**: asyncio.run() for each execution
- **Trade-off**: Some overhead but keeps pflow architecture intact

## Success Criteria

**MVP Must Have**:
- [ ] Connect to filesystem MCP server
- [ ] List and execute tools
- [ ] Tools appear in registry
- [ ] Natural language finds MCP tools
- [ ] Error messages are clear

**Nice to Have**:
- [ ] Multiple server support
- [ ] Performance optimization
- [ ] Comprehensive error handling

## Next Steps

1. **Day 1**: Build and run test client
2. **Day 2**: Implement MCPNode and compiler change
3. **Day 3**: Add CLI commands and registry updates
4. **Day 4**: Test with real servers
5. **Day 5**: Documentation and release

## Conclusion

This strategy leverages pflow's existing flexibility:
- Registry supports multiple entries → same class
- Compiler already injects special params
- Natural language planner sees specific tools

The MVP focuses on stdio transport with a simple async wrapper, postponing optimization for later phases. This approach ships in days, not weeks.