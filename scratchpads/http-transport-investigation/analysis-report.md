# HTTP Transport Analysis for MCP Discovery

## Executive Summary

✅ **HTTP transport for MCP tool discovery is fully feasible** with minimal changes to the existing codebase. The MCP library has built-in support for HTTP via Server-Sent Events (SSE), and our current discovery architecture can be extended to support HTTP URLs with minor modifications.

## Key Findings

### 1. Current Discovery Architecture

The existing `MCPDiscovery` implementation in `/src/pflow/mcp/discovery.py` is well-structured and uses the following flow:

```
MCPServerManager.get_server(name)
  → StdioServerParameters
  → stdio_client()
  → ClientSession
  → session.list_tools()
```

### 2. HTTP Transport Support in MCP Library

The MCP library already includes HTTP support via SSE:
- `mcp.client.sse.sse_client()` function for HTTP connections
- Same `ClientSession` interface as stdio client
- Built-in URL scheme detection (`http`/`https` vs commands)

**Evidence from MCP library source:**
```python
# From mcp/client/__main__.py
if urlparse(command_or_url).scheme in ("http", "https"):
    async with sse_client(command_or_url) as streams:
        await run_session(*streams)
else:
    # Use stdio client for commands
    server_parameters = StdioServerParameters(...)
    async with stdio_client(server_parameters) as streams:
        await run_session(*streams)
```

### 3. Required Changes (Minimal)

The changes needed are straightforward and isolated:

**A. Server Configuration Enhancement**
- Extend `MCPServerManager.add_server()` to accept `transport="http"`
- Update configuration schema to store HTTP URLs vs command/args
- Modify validation to allow HTTP URLs

**B. Discovery Transport Selection**
- Modify `MCPDiscovery._discover_async()` to detect transport type
- Use `sse_client()` for HTTP URLs vs `stdio_client()` for commands
- Both return the same interface, so rest of discovery code unchanged

**C. CLI Command Updates**
- Extend `pflow mcp add` to support URL arguments
- Update help text and examples

### 4. Implementation Approach

```python
# In MCPDiscovery._discover_async()
async def _discover_async(self, server_name: str, server_config: dict[str, Any]):
    transport = server_config.get("transport", "stdio")

    if transport == "http":
        # HTTP/SSE transport
        url = server_config["url"]  # New field
        headers = server_config.get("headers", {})

        async with sse_client(url, headers=headers) as (read, write), \
                   ClientSession(read, write) as session:
            await session.initialize()
            tools_response = await session.list_tools()
            # ... rest of discovery logic unchanged

    else:
        # Existing stdio transport logic
        params = StdioServerParameters(...)
        async with stdio_client(params) as (read, write), \
                   ClientSession(read, write) as session:
            # ... existing logic
```

### 5. Security Implications

**Low Risk for Discovery:**
- Tool discovery is read-only operation (listing available tools)
- No sensitive data transmitted during discovery
- Server URLs can be validated and allowlisted
- HTTPS enforcement for production use

**Authentication Considerations:**
- HTTP MCP servers may require API tokens/headers
- Headers can be stored in server configuration (encrypted)
- OAuth flows would be handled by the MCP server itself

**Recommended Security Measures:**
- Validate URLs (HTTPS only for remote servers)
- Timeout configurations (already supported by sse_client)
- Header sanitization for logging
- Optional URL allowlist in settings

### 6. Configuration Examples

**Current (stdio only):**
```bash
pflow mcp add github npx -y @modelcontextprotocol/server-github
```

**Proposed (with HTTP support):**
```bash
# HTTP MCP server
pflow mcp add composio https://api.composio.dev/mcp --header "Authorization=Bearer ${COMPOSIO_TOKEN}"

# Local stdio (unchanged)
pflow mcp add github npx -y @modelcontextprotocol/server-github
```

**Configuration JSON:**
```json
{
  "servers": {
    "composio": {
      "transport": "http",
      "url": "https://api.composio.dev/mcp",
      "headers": {
        "Authorization": "Bearer ${COMPOSIO_TOKEN}"
      },
      "created_at": "2024-01-01T00:00:00Z"
    },
    "github": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      },
      "created_at": "2024-01-01T00:00:00Z"
    }
  }
}
```

## Integration with Task 47: Composio Integration

This HTTP transport capability directly enables the Composio integration strategy outlined in Task 47:

1. **CLI (Local)**: Continue using stdio MCP servers
2. **Cloud (Remote)**: Use HTTP transport to connect to Composio's MCP endpoints
3. **Unified Discovery**: Both transports populate the same pflow registry

## Conclusion

**Recommendation: Proceed with HTTP transport implementation**

- Implementation risk: **Low** (well-supported by MCP library)
- Code changes: **Minimal** (isolated to transport layer)
- Testing effort: **Medium** (need HTTP test server setup)
- Strategic value: **High** (enables Composio and other remote MCP servers)

The changes required are primarily configuration and transport selection logic. The discovery, registry population, and tool execution flows remain unchanged.
