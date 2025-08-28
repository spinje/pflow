# MCP Integration Examples

This directory contains examples and reference implementations for Model Context Protocol (MCP) integration with pflow.

## What is MCP?

MCP (Model Context Protocol) is an open protocol that enables AI assistants and applications to connect with external data sources and tools through a standardized interface. With pflow's MCP support, you can:

- Connect to any MCP-compatible server (filesystem, databases, APIs, etc.)
- Use MCP tools as workflow nodes without writing custom code
- Leverage typed, structured data when servers provide output schemas
- Combine MCP tools with native pflow nodes seamlessly

## Files in this Directory

### mcp-protocol-reference.py

A comprehensive reference implementation demonstrating how MCP **servers** should implement structured outputs according to the protocol specification. This file shows:

- **Structured Output Models**: Using Pydantic models to define typed, validated outputs
- **Output Schemas**: How servers can provide JSON Schema for their outputs
- **structuredContent**: The protocol field for returning typed data
- **Mixed Output Types**: Combining structured and unstructured tools
- **Wire Format Examples**: Actual JSON-RPC messages exchanged between client and server

**Important Notes:**
- This is a reference implementation showing ideal protocol usage
- Most current MCP servers (filesystem, Slack, etc.) don't yet provide output schemas
- When servers do provide schemas, pflow automatically leverages them
- The FastMCP pattern shown here auto-generates schemas from type annotations

### mcp-client-example.py

A comprehensive **client** reference showing how to connect to and interact with MCP servers. This file demonstrates:

- **Minimal Viable Client**: The simplest possible MCP client implementation
- **Production Patterns**: Error handling, retries, and multiple server connections
- **Async-to-Sync Bridge**: The critical pattern that enables pflow's synchronous nodes to use the async MCP SDK
- **How pflow Implements MCP**: Simplified version of pflow's MCPNode showing virtual nodes and metadata injection

This is the client counterpart to `mcp-protocol-reference.py`, showing how to consume MCP services rather than provide them.

### mcp-debugging.py

Practical debugging utilities for troubleshooting MCP connections and protocol issues:

- **Quick Diagnostics**: Test server connectivity and basic functionality
- **Protocol Inspector**: Examine raw JSON-RPC messages and responses
- **Issue Debugger**: Diagnose common problems like path permissions and type mismatches
- **Interactive REPL**: Send custom commands to MCP servers for exploration

Usage:
```bash
python examples/mcp-integration/mcp-debugging.py test filesystem
python examples/mcp-integration/mcp-debugging.py diagnose --all
```

### structured-content-implementation.py

A proposed implementation for enhancing pflow's MCPNode to handle structured content from future MCP servers:

- **Priority-based extraction**: Handles `structuredContent`, `isError`, and content blocks in order
- **Field extraction**: Shows how to extract individual fields from structured data to the shared store
- **Future-proof**: Ready for when MCP servers start providing output schemas
- **Backward compatible**: Falls back to text content for current servers

This file shows the actual code that would be added to `MCPNode._extract_result()` to support typed, validated outputs when servers upgrade to provide them.

## How pflow Handles MCP

### 1. Virtual Nodes
MCP tools become "virtual nodes" in pflow - they don't exist as Python files but are registered dynamically:

```python
# Registry entry for an MCP tool
{
    "mcp-github-create-issue": {
        "class_name": "MCPNode",  # All MCP tools use the same class
        "module": "pflow.nodes.mcp.node",
        "file_path": "virtual://mcp",
        "interface": {
            "description": "Create a GitHub issue",
            "inputs": [],  # MCP tools don't read from shared store
            "params": [...],  # Tool parameters
            "outputs": [...]  # Tool outputs (usually generic for now)
        }
    }
}
```

### 2. Metadata Injection
The compiler identifies MCP nodes by their name pattern (`mcp-{server}-{tool}`) and injects metadata:

```python
# Compiler adds special parameters
params["__mcp_server__"] = "github"
params["__mcp_tool__"] = "create-issue"
```

### 3. Universal MCPNode
A single `MCPNode` class handles all MCP tools, using the injected metadata to determine which server and tool to execute. This keeps the implementation server-agnostic.

### 4. Structured Content Support
pflow is ready for next-generation MCP servers that provide output schemas:

- **Priority 1**: Check for `structuredContent` (typed, validated data)
- **Priority 2**: Check for `isError` flag (tool-level errors)
- **Priority 3**: Fall back to content blocks (text, images, resources)

When servers return structured data, pflow automatically:
- Extracts individual fields to the shared store
- Makes them directly accessible to downstream nodes
- Preserves type information for better workflow composition

## MCP Client Implementation

While `mcp-protocol-reference.py` shows how servers should behave, `mcp-client-example.py` demonstrates how clients connect to and interact with MCP servers.

### Key Client Patterns

1. **Initialize First**: Every MCP client must call `initialize()` before any other operations
2. **Async SDK**: The MCP SDK is async-only, requiring `asyncio.run()` for sync contexts
3. **Error Handling**: Production clients need retry logic and proper error extraction
4. **Connection Lifecycle**: Each tool call creates a new subprocess (no connection pooling yet)

### The Async-to-Sync Bridge

This is the critical pattern that enables pflow's synchronous PocketFlow nodes to use the async MCP SDK:

```python
def exec(self, prep_res: dict) -> dict:
    """Synchronous method required by PocketFlow."""
    return asyncio.run(self._exec_async(prep_res))

async def _exec_async(self, prep_res: dict) -> dict:
    """Async implementation using MCP SDK."""
    # ... MCP SDK calls here ...
```

Each `asyncio.run()` creates a new event loop, providing isolation and avoiding conflicts.

### How pflow's MCPNode Works

1. **Virtual Nodes**: Registry entries like `mcp-github-create_issue` all point to the same `MCPNode` class
2. **Metadata Injection**: Compiler adds `__mcp_server__` and `__mcp_tool__` parameters
3. **Universal Client**: MCPNode never contains server-specific logic, ensuring compatibility with future servers
4. **Type Preservation**: Template resolver preserves number/boolean types (critical for MCP tools)

See the full client example: [mcp-client-example.py](./mcp-client-example.py)

## Setting Up MCP Servers

### 1. Add a Server
```bash
# Filesystem server
pflow mcp add filesystem npx -- -y @modelcontextprotocol/server-filesystem /tmp

# GitHub server (requires token)
pflow mcp add github npx -- -y @modelcontextprotocol/server-github \
    -e GITHUB_TOKEN=${GITHUB_TOKEN}

# Slack server
pflow mcp add slack npx -- -y @zencoderai/slack-mcp-server \
    -e SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN} \
    -e SLACK_TEAM_ID=${SLACK_TEAM_ID}
```

### 2. Discover Tools
```bash
# Sync tools from a specific server
pflow mcp sync github

# Sync all configured servers
pflow mcp sync --all
```

### 3. List Available Tools
```bash
# List all MCP tools
pflow mcp tools

# List tools from specific server
pflow mcp tools github

# Get detailed info about a tool
pflow mcp info mcp-github-create-issue
```

### 4. Use in Workflows
```json
{
  "name": "create-github-issue",
  "nodes": [
    {
      "id": "create-issue",
      "type": "mcp-github-create-issue",
      "params": {
        "repository": "user/repo",
        "title": "Bug Report",
        "body": "Description of the issue"
      }
    }
  ],
  "edges": []
}
```

Or through natural language:
```bash
pflow "create a GitHub issue in user/repo with title 'Bug Report'"
```

## Current State of MCP Servers

### What Works Today
- **Input schemas**: All servers provide JSON Schema for their inputs
- **Basic outputs**: Tools return results as text in content blocks
- **Tool discovery**: Automatic registration of all server tools
- **Environment variables**: `${VAR}` syntax for configuration

### What's Coming
- **Output schemas**: Servers will provide structured output definitions
- **structuredContent**: Typed, validated return values
- **Better error handling**: `isError` flag for tool-level failures
- **Resource types**: Links and embedded resources

## Protocol Details

The MCP protocol uses JSON-RPC 2.0 over stdio (most common) or HTTP transports. Key methods:

- `initialize`: Handshake and capability negotiation
- `tools/list`: Discover available tools with schemas
- `tools/call`: Execute a tool with arguments
- `resources/list`: Discover available resources (optional)
- `prompts/list`: Discover available prompts (optional)

See `mcp-protocol-reference.py` for detailed wire format examples.

## Testing MCP Integration

### Basic Test
```python
from pflow.nodes.mcp.node import MCPNode

# Test filesystem tool
node = MCPNode()
node.set_params({
    "__mcp_server__": "filesystem",
    "__mcp_tool__": "list_allowed_directories"
})

shared = {}
prep_res = node.prep(shared)
exec_res = node.exec(prep_res)
action = node.post(shared, prep_res, exec_res)

print(f"Result: {shared.get('result')}")
```

### Structured Output (Future)
When servers provide output schemas, the result will be typed:

```python
# If get_weather returns WeatherData
shared["result"] = {
    "temperature": 22.5,
    "humidity": 65,
    "conditions": "Partly cloudy"
}
# Individual fields also extracted
shared["temperature"] = 22.5
shared["humidity"] = 65
shared["conditions"] = "Partly cloudy"
```

## Debugging MCP Connections

When things go wrong with MCP integration, use our debugging utilities to diagnose and fix issues quickly.

### Quick Diagnostics

Test if a server can start and connect:
```bash
python examples/mcp-integration/mcp-debugging.py test filesystem
python examples/mcp-integration/mcp-debugging.py test --all
```

### Protocol Inspection

Examine the raw JSON-RPC messages:
```bash
# Inspect protocol messages
python examples/mcp-integration/mcp-debugging.py inspect filesystem

# Inspect specific tool call
python examples/mcp-integration/mcp-debugging.py inspect filesystem read_file '{"path": "/tmp/test.txt"}'
```

### Comprehensive Diagnostics

Run all diagnostic checks:
```bash
python examples/mcp-integration/mcp-debugging.py diagnose --all
```

This checks:
- Environment variables (tokens, credentials)
- Path permissions and symlink resolution
- Type conversion and preservation
- Common error patterns

### Interactive Debugging

Use the REPL for interactive exploration:
```bash
python examples/mcp-integration/mcp-debugging.py repl
mcp(disconnected)> connect filesystem
mcp(filesystem)> list
mcp(filesystem)> call read_file {"path": "/tmp/test.txt"}
```

See full debugging utilities: [mcp-debugging.py](./mcp-debugging.py)

## Troubleshooting

### Common Issues

1. **"Access denied" errors**: Check server's allowed directories
   ```bash
   # macOS: Use /private/tmp instead of /tmp
   pflow mcp add filesystem npx -- -y @modelcontextprotocol/server-filesystem /private/tmp
   ```

2. **Missing environment variables**: Set before running pflow
   ```bash
   export GITHUB_TOKEN=your_token_here
   ```

3. **Tools not found**: Re-sync after adding servers
   ```bash
   pflow mcp sync --all
   ```

4. **Type errors**: Check parameter types match tool expectations
   ```bash
   # Diagnose type conversion issues
   python examples/mcp-integration/mcp-debugging.py diagnose types
   ```

5. **"Unhandled errors in a TaskGroup"**: Usually means retry or type issues
   ```bash
   # Get specific diagnostics
   python examples/mcp-integration/mcp-debugging.py diagnose taskgroup
   ```

For any issues, start with comprehensive diagnostics:
```bash
python examples/mcp-integration/mcp-debugging.py diagnose --all
```

## Resources

- [MCP Specification](https://modelcontextprotocol.io)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Available MCP Servers](https://github.com/modelcontextprotocol/servers)

## Future Enhancements

As the MCP ecosystem evolves, pflow is ready to leverage:

1. **Connection pooling**: Reuse server connections instead of starting new subprocesses
2. **HTTP/SSE transports**: Remote server connections beyond stdio
3. **Advanced schemas**: Complex nested structures with full validation
4. **Streaming responses**: Real-time data from long-running operations
5. **Resource management**: Direct access to server-managed resources

The infrastructure is in place - we're just waiting for servers to catch up with the protocol's full capabilities!