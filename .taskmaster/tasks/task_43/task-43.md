# Task 43: MCP Server Support

## ID
43

## Title
MCP Server Support (Install MCPs and Use as Dynamic Nodes)

## Description
Enable pflow to connect to MCP (Model Context Protocol) servers and expose their tools as workflow nodes. Users configure MCP servers once, then all tools from those servers become available as individual nodes in pflow's registry, allowing natural language workflows to leverage any MCP-compatible service without custom integration code.

## Status
not started

## Dependencies
- Task 40: Improve Workflow Validation and Consolidate into Unified System - MCP nodes have dynamically discovered parameters with JSON schemas that must integrate with pflow's validation system
- Task 5: Node Discovery and Registry - The registry must be enhanced to support virtual node entries where multiple registry entries point to the same implementation class with different metadata

## Priority
high

## Details
MCP (Model Context Protocol) is Anthropic's open standard for AI systems to interact with external tools and services via JSON-RPC 2.0. This task implements a universal MCP integration that allows pflow to work with any protocol-compliant MCP server without writing custom code for each one.

### Architecture Overview
The implementation creates "virtual nodes" - registry entries that represent specific MCP tools but all execute through one shared implementation:
1. Users configure MCP servers via CLI commands
2. pflow connects to servers and discovers their available tools
3. Each discovered tool gets a registry entry with a namespaced name (e.g., `mcp-github-create-issue`)
4. All these registry entries point to the same `MCPNode` class but with different metadata
5. The planner sees specific tools, users see specific nodes, but only one class needs maintenance

### Key Components to Build

**MCP Configuration System**:
- Storage location: `~/.pflow/mcp-servers.json` (following pflow's existing `~/.pflow/registry.json` pattern)
- CLI commands: `pflow mcp add/list/remove/sync`
- MVP: stdio transport only
- Future: HTTP and SSE transports
- Environment variable expansion using `${VAR}` syntax (matching pflow's template syntax)
- MVP: User scope only (global configuration)
- Future: Project and local scopes

**Discovery Mechanism**:
- Connect to MCP servers using JSON-RPC 2.0 protocol
- Send `initialize` handshake, then `tools/list` to enumerate available tools
- Extract tool metadata: name, description, inputSchema (required), outputSchema (optional)
- Store discovered tools in registry (persist between runs)
- MVP: Manual sync via `pflow mcp sync` command
- Future: Auto-discovery on startup

**Registry Integration**:
- "Virtual nodes": Registry entries created dynamically from discovered MCP tools
- Key difference from regular nodes: Not scanned from Python files but generated at sync time
- All virtual entries share: `module: "pflow.nodes.mcp.node"`, `class_name: "MCPNode"`
- Each entry has unique metadata: `mcp_config: {server: "github", tool: "create-issue"}`
- Tools use namespaced names to avoid conflicts: `mcp-{server}-{tool}`
- Planner and users see specific tools (better discoverability than generic "mcp-node")

**Universal MCPNode Implementation**:
- Single `MCPNode` class in `src/pflow/nodes/mcp/node.py`
- Reads server name and tool name from registry metadata (not from params)
- MVP: Create new subprocess for each execution (simple but slower)
- Future: Connection pooling for performance
- MVP: stdio transport only via subprocess.Popen
- MVP: Handle text content type only
- Future: Handle image, audio, resource content types

### Implementation Approach (MVP)
Focus on minimal working implementation:
- stdio transport only (subprocess with stdin/stdout communication)
- JSON-RPC 2.0 messages as newline-delimited JSON
- Manual server configuration via CLI commands
- Test with official Anthropic MCP servers from `@modelcontextprotocol/*` npm packages
- No connection pooling (new subprocess per execution)
- No OAuth/authentication support
- Text content only (no binary data)

### Configuration Example
Structure of `~/.pflow/mcp-servers.json`:
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
Note: Environment variables use `${VAR}` syntax for consistency with pflow's template system

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
Testing focuses on protocol compliance and registry integration:

**Unit Tests**:
- Registry metadata extraction: Verify MCPNode reads server/tool from metadata correctly
- JSON-RPC formatting: Test message structure matches MCP specification
- Error handling: Map JSON-RPC error codes (-32601, -32602, etc.) to user messages
- Configuration parsing: Test environment variable expansion with `${VAR}` syntax

**Integration Tests**:
- Mock MCP server: Create a simple Python MCP server that exposes test tools
- Discovery flow: Verify `pflow mcp sync` creates correct registry entries
- Subprocess management: Test stdio communication with newline-delimited JSON
- Registry virtual nodes: Confirm multiple tools from same server use same MCPNode class

**End-to-End Tests**:
- If available, test with real `@modelcontextprotocol/*` npm packages
- Natural language: "create github issue" should select `mcp-github-create-issue` node
- Mixed workflows: Combine ShellNode, LLMNode, and MCPNode in single workflow

**Error Scenarios**:
- Server not found: Clear error when configured server command doesn't exist
- Protocol errors: Handle malformed JSON-RPC responses gracefully
- Timeout: Kill subprocess if tool execution exceeds timeout
- Missing tools: Handle case where `tools/list` returns empty or tool no longer exists
