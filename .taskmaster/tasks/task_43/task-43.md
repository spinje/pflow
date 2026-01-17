# Task 43: MCP Server Support

## Description
Enable pflow to connect to MCP (Model Context Protocol) servers and expose their tools as workflow nodes. Users configure MCP servers once, then all tools from those servers become available as individual nodes in pflow's registry, allowing natural language workflows to leverage any MCP-compatible service without custom integration code.

## Status
done

## Completed
2025-09-02

## Dependencies
- Task 40: Improve Workflow Validation and Consolidate into Unified System - MCP tools have JSON schemas that must integrate with pflow's validation system
- Task 5: Node Discovery and Registry - Registry system must be functional for storing virtual node entries

## Priority
high

## Details
MCP (Model Context Protocol) is Anthropic's open standard for AI systems to interact with external tools and services via JSON-RPC 2.0. This task implements a universal MCP integration that allows pflow to work with any protocol-compliant MCP server without writing custom code for each one.

### Architecture Overview
MCP tools become pflow nodes through "virtual registry entries" - multiple registry entries pointing to a single MCPNode implementation:

1. **Configuration**: Users add MCP servers via CLI (`pflow mcp add`)
2. **Discovery**: pflow queries servers for available tools via JSON-RPC
3. **Registration**: Each tool becomes a registry entry (e.g., `mcp-github-create-issue`)
4. **Execution**: All MCP registry entries use the same `MCPNode` class
5. **Identity**: Compiler injects metadata so nodes know which server/tool they represent

### Key Components

**1. MCP Configuration Management**
- Store server configs in `~/.pflow/mcp-servers.json`
- CLI commands: `pflow mcp add/list/remove/sync`
- Environment variable expansion (`${VAR}` syntax)

**2. Tool Discovery & Registration**
- Connect to MCP servers via JSON-RPC 2.0
- Query available tools and their schemas
- Create virtual registry entries for each tool
- Use namespaced naming: `mcp-{server}-{tool}`

**3. Universal MCPNode**
- Single node class handles all MCP tools
- Receives server/tool identity via compiler metadata injection
- Manages subprocess lifecycle for stdio transport
- Async-to-sync wrapper for MCP protocol operations

**4. Compiler Enhancement**
- Inject `__mcp_server__` and `__mcp_tool__` parameters for MCP nodes
- Follow existing `__registry__` pattern for special parameters

### MVP Scope

**Includes:**
- stdio transport only (simplest to implement)
- Manual tool discovery via `pflow mcp sync`
- Text content handling
- Basic error handling and timeouts

**Excludes:**
- HTTP/SSE transports
- Connection pooling
- OAuth authentication
- Binary content types
- Auto-discovery on startup

### Example Configuration

`~/.pflow/mcp-servers.json`:
```json
{
  "servers": {
    "github": {
      "transport": "stdio",
      "command": "npx",
      "args": ["@modelcontextprotocol/github"],
      "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
    }
  }
}
```

### User Experience
```bash
# Configure server
$ pflow mcp add github -- npx @modelcontextprotocol/github

# Discover tools
$ pflow mcp sync github

# Use in workflow
$ pflow "create github issue about the bug"
# Planner sees mcp-github-create-issue node
```

## Test Strategy

**Protocol Testing:**
- Use official MCP SDK to validate protocol understanding
- Test against real MCP servers (`@modelcontextprotocol/server-filesystem`)
- Verify JSON-RPC message format and handshake sequence

**Integration Testing:**
- Registry correctly stores virtual node entries
- Compiler properly injects metadata for MCP nodes
- MCPNode successfully executes tools via subprocess
- Environment variable expansion works correctly

**Error Handling:**
- Subprocess timeouts and cleanup
- Invalid server configurations
- Protocol errors and malformed responses
- Missing or unavailable tools

## Future Enhancements (Excluded from MVP, DONT build this now)

### Remote MCP Server Support

After the MVP, pflow should support remote MCP servers to enable:
- **Cloud-hosted tools**: Connect to MCP servers running on Cloudflare, AWS, Azure
- **SaaS integrations**: Direct connections to services like Notion, Linear, Sentry
- **Team collaboration**: Shared MCP servers accessible by multiple users
- **Scalability**: No local resource constraints from subprocess management

**Streamable HTTP Transport** (Priority)
- New standard replacing SSE, designed for cloud deployments
- Single endpoint for all interactions (`/mcp`)
- Supports serverless architectures (scale to zero)
- Session management via `Mcp-Session-Id` headers
- Bidirectional communication on same connection

**SSE Transport** (Legacy compatibility)
- Server-Sent Events for real-time streaming
- Required by some existing cloud MCP servers
- Two endpoints: GET for SSE, POST for requests
- Being phased out in favor of Streamable HTTP

### Additional Improvements

**Performance Optimizations:**
- Connection pooling for frequently used servers
- Caching of tool schemas between sessions
- Parallel tool discovery for multiple servers

**Enhanced Features:**
- Binary content support (images, audio, files)
- OAuth/token authentication for secure servers
- Auto-discovery of configured servers on startup
- Project and workspace-scoped configurations
- MCP server health monitoring and auto-reconnect

**Developer Experience:**
- MCP server marketplace/registry
- Workflow templates using popular MCP tools
- Visual tool browser in pflow CLI
- Debugging mode with message inspection
