# Universal MCP Node: Implementation Analysis

## Executive Summary

MCP (Model Context Protocol) enables AI systems to interact with tools via JSON-RPC 2.0. pflow will implement a universal MCP node that automatically works with any MCP server without custom code for each one.

**Implementation Decision**: Use direct registry manipulation + compiler metadata injection (3 lines of code change)

## Verified Protocol Details

### Communication Flow (Confirmed)
```
pflow MCPNode <--stdio--> MCP Server <--API--> External Service
               JSON-RPC 2.0 (newline-delimited)
```

### Required Protocol Sequence
```json
// 1. Initialize (mandatory handshake)
{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05"},"id":1}

// 2. List tools
{"jsonrpc":"2.0","method":"tools/list","id":2}

// 3. Call tool
{"jsonrpc":"2.0","method":"tools/call","params":{"name":"read_file","arguments":{"path":"/file.txt"}},"id":3}
```

### Transport Support (MVP: stdio only)
- **stdio**: Subprocess with JSON over stdin/stdout (MVP focus)
- **HTTP/SSE**: Future enhancement
- **Streamable HTTP**: New standard, future consideration

## The Chosen Implementation

After analyzing 8 options, we selected **Direct Registry Manipulation + Compiler Metadata Injection**:

### 1. Registry Side: Virtual Node Entries
```python
# Each MCP tool becomes a registry entry
{
    "mcp-github-create-issue": {
        "class_name": "MCPNode",
        "module": "pflow.nodes.mcp.node",
        "file_path": "virtual://mcp",  # Virtual path - works fine
        "interface": {
            "description": "Create a GitHub issue",
            "params": [...],  # From tool schema
            "outputs": [...],
            "actions": ["default", "error"]
        }
    }
}
```

**Key Discovery**: The registry already supports this - multiple entries CAN point to the same class.

### 2. Compiler Side: Metadata Injection
```python
# Add to compiler.py (~line 290), following existing pattern
if node_type.startswith("mcp-"):
    params["__mcp_server__"] = node_type.split("-")[1]
    params["__mcp_tool__"] = "-".join(node_type.split("-")[2:])
```

This follows the established `__registry__` pattern (line 284 in compiler.py).

### 3. MCPNode Implementation
```python
class MCPNode(Node):
    """Universal MCP node - handles all MCP tool executions."""

    def prep(self, shared: dict) -> dict:
        # Get server/tool from compiler-injected params
        server = self.params.get("__mcp_server__")
        tool = self.params.get("__mcp_tool__")

        # Load server config
        config = self._load_server_config(server)

        # Prepare for execution
        return {
            "server": server,
            "tool": tool,
            "config": config,
            "arguments": self.params  # User-provided tool args
        }

    def exec(self, prep_res: dict) -> dict:
        # Start MCP server subprocess
        proc = subprocess.Popen(
            [prep_res["config"]["command"]] + prep_res["config"]["args"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            env={**os.environ, **self._expand_env(prep_res["config"]["env"])}
        )

        # Execute JSON-RPC sequence
        # 1. Initialize
        # 2. Call tool
        # 3. Get result

        # Terminate subprocess
        proc.terminate()

        return result
```

## Configuration Management

### Server Configuration (`~/.pflow/mcp-servers.json`)
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
    }
  }
}
```

Environment variables use `${VAR}` syntax to match pflow's existing template system.

## Technical Challenges (Resolved)

### ✅ Registry Flexibility
**Resolved**: Registry supports multiple entries pointing to same class.

### ✅ Node Identity
**Resolved**: Compiler injects metadata via special params.

### ✅ Async SDK vs Sync Nodes
**Solution**: Use `asyncio.run()` wrapper or implement minimal sync client.

### ⏳ Server Discovery
**MVP**: Manual configuration via CLI
**Future**: Auto-discovery from npm/pip packages

### ⏳ Subprocess Lifecycle
**MVP**: New subprocess per execution (simple but slower)
**Future**: Connection pooling

## Implementation Timeline

### Phase 1: Core Implementation (Day 1)
- [ ] MCPNode class with stdio support
- [ ] Compiler modification (3 lines)
- [ ] Basic subprocess management

### Phase 2: CLI Integration (Day 2)
- [ ] `pflow mcp add` command
- [ ] `pflow mcp sync` command
- [ ] Configuration storage

### Phase 3: Testing (Day 3)
- [ ] Test with filesystem MCP server
- [ ] Test with GitHub MCP server
- [ ] Error handling validation

## Key Insights

1. **The registry is more flexible than documented** - Virtual entries work fine
2. **Compiler already has metadata injection pattern** - Just follow it
3. **stdio-only MVP is sufficient** - HTTP/SSE can come later
4. **Manual configuration is acceptable** - Auto-discovery is nice-to-have

## Success Metrics

- Successfully sync tools from an MCP server
- Execute a tool via natural language workflow
- Handle errors gracefully
- Complete implementation in 2-3 days

## Conclusion

The universal MCP node is straightforward to implement using pflow's existing patterns. The key innovation is using virtual registry entries that all point to one MCPNode class, with the compiler injecting metadata to identify which tool to execute.

This approach requires minimal changes (3 lines in compiler, 1 new node class) while providing maximum flexibility for users to integrate any MCP server.