# MCP HTTP Transport Examples

This directory contains examples demonstrating how to use pflow's Streamable HTTP transport for MCP (Model Context Protocol) servers.

## Files

### example-http-server.py
A complete, working example of an MCP server implementation with Streamable HTTP transport. This demonstrates:
- Full protocol implementation (initialize, list_tools, call_tool, session termination)
- Proper session management with session IDs
- Request/response handling following MCP 2025-03-26 specification
- Simple tools (echo and add_numbers) for testing

**Usage:**
```bash
# Start the server
python example-http-server.py

# In another terminal, configure pflow
pflow mcp add test-http --transport http --url http://localhost:8080/mcp

# Sync tools
pflow mcp sync test-http

# Use in workflows
pflow "echo hello world using the test-http server"
```

### test-http-setup.sh
A comprehensive test script that demonstrates:
- Starting an HTTP MCP server
- Configuring pflow with HTTP transport
- Running discovery and sync
- Executing workflows with HTTP-based tools
- Cleanup procedures

**Usage:**
```bash
chmod +x test-http-setup.sh
./test-http-setup.sh
```

### example-workflow.json
An example workflow that uses HTTP-based MCP tools. Shows the workflow IR structure for calling HTTP MCP services.

**Usage:**
```bash
# After setting up the HTTP server and syncing tools
pflow run example-workflow.json
```

## Quick Start

1. **Start the example server:**
   ```bash
   python example-http-server.py
   ```

2. **Configure pflow (in another terminal):**
   ```bash
   pflow mcp add example --transport http --url http://localhost:8080/mcp
   ```

3. **Discover and sync tools:**
   ```bash
   pflow mcp sync example
   ```

4. **List available tools:**
   ```bash
   pflow mcp tools example
   ```

5. **Use in natural language:**
   ```bash
   pflow "use the example server to add 10 and 32"
   ```

## Authentication Examples

### Bearer Token
```bash
pflow mcp add secure-api --transport http \
  --url https://api.example.com/mcp \
  --auth-type bearer \
  --auth-token '${API_TOKEN}'
```

### API Key
```bash
pflow mcp add api-service --transport http \
  --url https://api.service.com/mcp \
  --auth-type api_key \
  --auth-token '${SERVICE_KEY}' \
  --auth-header X-Service-Key
```

### Basic Auth
```bash
pflow mcp add internal --transport http \
  --url https://internal.company.com/mcp \
  --auth-type basic \
  --username admin \
  --password '${ADMIN_PASSWORD}'
```

## Protocol Details

The example server implements the Streamable HTTP transport protocol:
- **Single endpoint**: `/mcp` handling POST, GET, and DELETE
- **Session management**: Session IDs in headers
- **JSON-RPC**: Standard MCP message format
- **Server-Sent Events**: Optional streaming support (GET)

## Creating Your Own HTTP MCP Server

Use `example-http-server.py` as a template. Key components:

1. **Routes**: Handle `/mcp` with POST, GET, DELETE methods
2. **Session Management**: Generate and track session IDs
3. **Tool Implementation**: Define your tools and their schemas
4. **Response Format**: Follow MCP protocol for responses

## Troubleshooting

1. **Connection errors**: Ensure server is running on the correct port
2. **Tool not found**: Run `pflow mcp sync` after adding/updating servers
3. **Authentication failures**: Check environment variables are set
4. **Session errors**: Server may have restarted; sync tools again

## Further Reading

- [MCP Documentation](https://modelcontextprotocol.io/)
- [pflow MCP HTTP Transport Docs](../../docs/mcp-http-transport.md)
- [Streamable HTTP Specification](https://modelcontextprotocol.io/docs/concepts/transports)