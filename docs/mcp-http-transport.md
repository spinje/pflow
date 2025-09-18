# MCP HTTP Transport Documentation

## Overview

pflow now supports Streamable HTTP transport for MCP (Model Context Protocol) servers, enabling communication with remote MCP servers over HTTP/HTTPS. This allows you to connect to cloud-hosted MCP services, API gateways, and remote servers without running local processes.

## Features

- **Streamable HTTP Protocol**: Full support for the MCP 2025-03-26 specification
- **Multiple Authentication Methods**: Bearer tokens, API keys, and basic authentication
- **Environment Variable Expansion**: Secure credential management with `${VAR}` syntax
- **Custom Headers**: Add any HTTP headers required by your server
- **Configurable Timeouts**: Control HTTP and SSE read timeouts
- **Mixed Transport Support**: Use both stdio and HTTP servers in the same project

## Configuration

### Adding an HTTP Server

Use the `pflow mcp add` command with the `--transport http` option:

```bash
# Basic HTTP server (no authentication)
pflow mcp add myserver --transport http --url http://localhost:3000/mcp

# With bearer token authentication
pflow mcp add composio --transport http \
  --url https://api.composio.dev/mcp \
  --auth-type bearer \
  --auth-token '${COMPOSIO_API_KEY}'

# With API key authentication
pflow mcp add myapi --transport http \
  --url https://api.example.com/mcp \
  --auth-type api_key \
  --auth-token '${API_KEY}' \
  --auth-header X-Custom-Key

# With basic authentication
pflow mcp add secure --transport http \
  --url https://secure.example.com/mcp \
  --auth-type basic \
  --username myuser \
  --password '${SECRET_PASSWORD}'

# With custom headers and timeout
pflow mcp add custom --transport http \
  --url https://api.example.com/mcp \
  --header "User-Agent=pflow/1.0" \
  --header "Accept=application/json" \
  --timeout 60 \
  --sse-timeout 300
```

### Configuration File Structure

HTTP servers are stored in `~/.pflow/mcp-servers.json`:

```json
{
  "servers": {
    "composio": {
      "transport": "http",
      "url": "https://api.composio.dev/mcp",
      "auth": {
        "type": "bearer",
        "token": "${COMPOSIO_API_KEY}"
      },
      "headers": {
        "User-Agent": "pflow/1.0"
      },
      "timeout": 30,
      "sse_timeout": 300,
      "created_at": "2025-01-01T00:00:00Z",
      "updated_at": "2025-01-01T00:00:00Z"
    }
  }
}
```

## Authentication

### Bearer Token

Most common for modern APIs. The token is sent in the `Authorization: Bearer <token>` header.

```bash
pflow mcp add github-cloud --transport http \
  --url https://mcp.github.com/v1 \
  --auth-type bearer \
  --auth-token '${GITHUB_TOKEN}'
```

### API Key

For services that use custom header names for API keys.

```bash
pflow mcp add service --transport http \
  --url https://api.service.com/mcp \
  --auth-type api_key \
  --auth-token '${SERVICE_API_KEY}' \
  --auth-header X-API-Key
```

### Basic Authentication

For services requiring username and password.

```bash
pflow mcp add internal --transport http \
  --url https://internal.company.com/mcp \
  --auth-type basic \
  --username admin \
  --password '${ADMIN_PASSWORD}'
```

### Environment Variables

Always use environment variables for sensitive credentials:

1. Set the environment variable:
   ```bash
   export COMPOSIO_API_KEY="your-actual-key-here"
   ```

2. Reference it in the configuration using `${VAR}` syntax:
   ```bash
   pflow mcp add composio --transport http \
     --url https://api.composio.dev/mcp \
     --auth-type bearer \
     --auth-token '${COMPOSIO_API_KEY}'
   ```

The `${COMPOSIO_API_KEY}` will be expanded at runtime, keeping your credentials secure.

## Tool Discovery

Discover available tools from an HTTP server:

```bash
# Sync tools from a specific HTTP server
pflow mcp sync composio

# Sync all servers (both stdio and HTTP)
pflow mcp sync --all
```

## Usage in Workflows

Once configured and synced, HTTP-based MCP tools work identically to stdio tools:

```bash
# Use natural language to create workflows
pflow "create a github issue about the http transport feature"

# The planner will automatically use available HTTP-based tools
```

## Listing Servers

View all configured servers with their transport types:

```bash
pflow mcp list
```

Output:
```
Configured MCP servers:

  github:
    Transport: stdio
    Command: npx -y @modelcontextprotocol/server-github
    Environment: GITHUB_TOKEN=${GITHUB_TOKEN}
    Created: 2025-01-01T00:00:00Z

  composio:
    Transport: http
    URL: https://api.composio.dev/mcp
    Auth Type: bearer
    Headers: User-Agent=pflow/1.0
    Timeout: 30s
    Created: 2025-01-01T00:00:00Z
```

## Timeouts

Configure timeouts for HTTP operations:

- **`--timeout`**: General HTTP request timeout (default: 30 seconds)
- **`--sse-timeout`**: Server-Sent Events read timeout (default: 300 seconds)

```bash
pflow mcp add slow-server --transport http \
  --url https://slow.example.com/mcp \
  --timeout 60 \
  --sse-timeout 600
```

## Security Best Practices

1. **Always use HTTPS** for production servers
2. **Use environment variables** for all credentials
3. **Never commit credentials** to version control
4. **Rotate tokens regularly**
5. **Use minimal required permissions** for API tokens

## Error Handling

The HTTP transport provides clear error messages for common issues:

- **Connection errors**: "Could not connect to MCP server at <url>"
- **Authentication failures**: "Authentication failed. Check your API credentials."
- **Rate limiting**: "Rate limited. Too many requests. Please wait and try again."
- **Timeouts**: "HTTP request timed out after X seconds"

## Troubleshooting

### Connection Issues

If you can't connect to an HTTP server:

1. Verify the URL is correct and accessible
2. Check if the server requires authentication
3. Ensure environment variables are set correctly
4. Try increasing the timeout values

### Authentication Errors

If authentication fails:

1. Verify your credentials are correct
2. Check that environment variables are exported
3. Ensure the auth type matches what the server expects
4. Verify token hasn't expired

### Discovery Issues

If tool discovery fails:

1. Ensure the server supports the MCP protocol
2. Check if the server is running and accessible
3. Verify authentication is configured correctly
4. Check server logs for more details

## Examples

### Example 1: Composio Integration

```bash
# Set up Composio API key
export COMPOSIO_API_KEY="your-composio-api-key"

# Add Composio server
pflow mcp add composio --transport http \
  --url https://api.composio.dev/mcp \
  --auth-type bearer \
  --auth-token '${COMPOSIO_API_KEY}'

# Discover available tools
pflow mcp sync composio

# Use Composio tools in workflows
pflow "send a slack message saying hello"
```

### Example 2: Local Development Server

```bash
# Add local HTTP server (no auth)
pflow mcp add dev --transport http \
  --url http://localhost:8080/mcp

# Sync tools
pflow mcp sync dev

# Use in workflows
pflow "use the dev server to process some data"
```

### Example 3: Corporate API Gateway

```bash
# Set up credentials
export CORP_API_KEY="internal-api-key"

# Add corporate gateway with custom headers
pflow mcp add corp --transport http \
  --url https://gateway.company.com/mcp \
  --auth-type api_key \
  --auth-token '${CORP_API_KEY}' \
  --auth-header X-Corp-Auth \
  --header "X-Department=Engineering" \
  --header "X-Project=pflow"

# Discover and use tools
pflow mcp sync corp
```

## Migration from stdio

If you're migrating from stdio to HTTP transport:

1. The tool names remain the same after syncing
2. Existing workflows continue to work
3. The planner automatically uses the available transport
4. No changes needed to workflow files

## Limitations

Current limitations (MVP):

- No OAuth support (use API keys or bearer tokens)
- No connection pooling (new connection per execution)
- No automatic token refresh
- No client certificate authentication
- No proxy support

These limitations may be addressed in future versions.

## Technical Details

### Protocol Version

pflow implements the Streamable HTTP transport as defined in MCP protocol version 2025-03-26, which replaced the deprecated HTTP+SSE transport.

### Session Management

Each workflow execution creates a new HTTP session. Session IDs are managed automatically by the protocol but are not cached between executions.

### Error Recovery

HTTP transport includes automatic error detection and user-friendly error messages. Failed requests are not automatically retried in the current version.

## Next Steps

- [Learn about MCP](https://modelcontextprotocol.io/)
- [Browse available MCP servers](https://github.com/topics/mcp-server)
- [Create custom MCP servers](https://modelcontextprotocol.io/docs/guides/building-servers)