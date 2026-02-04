# MCP (Model Context Protocol) Integration Guide

## Overview

MCP (Model Context Protocol) is an open standard that enables AI systems to interact with external tools and services. With pflow's MCP integration, you can connect to any MCP-compliant server and automatically use all its tools as workflow nodes—no custom integration code required.

## Quick Start

### 1. Add an MCP Server

```bash
# Add from inline JSON (simple format - recommended for CLI)
pflow mcp add '{"filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}}'

# Add GitHub server with environment variable
pflow mcp add '{"github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"], "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}}}'

# Add from a config file
pflow mcp add ./github.mcp.json
```

### 2. Discover Available Tools

```bash
# Sync tools from a specific server
pflow mcp sync filesystem

# Sync all configured servers
pflow mcp sync --all
```

### 3. Use MCP Tools in Workflows

Once synced, MCP tools appear as nodes with the pattern `mcp-{server}-{tool}`:

```bash
# Natural language - pflow finds the MCP tool
pflow "read the config.json file from /tmp"

# Direct node execution
pflow mcp-filesystem-read_text_file path=/tmp/config.json

# In a .pflow.md workflow
## Steps

### read

Read a file from the filesystem MCP server.

- type: mcp-filesystem-read_text_file
- path: /tmp/config.json
```

## MCP Server Management

### List Configured Servers

```bash
# Show all configured MCP servers
pflow mcp list

# Output as JSON
pflow mcp list --json
```

### View Available Tools

```bash
# List all registered MCP tools
pflow mcp tools

# List tools from specific server
pflow mcp tools filesystem

# Get detailed info about a tool
pflow mcp info mcp-filesystem-read_text_file
```

### Remove a Server

```bash
# Remove server and its tools
pflow mcp remove filesystem

# Force removal without confirmation
pflow mcp remove filesystem --force
```

## Configuration

MCP server configurations are stored in `~/.pflow/mcp-servers.json`:

```json
{
  "servers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      },
      "transport": "stdio"
    }
  }
}
```

### Config File Format

MCP server configurations can be stored in `.mcp.json` files. The format is compatible with Claude Desktop and other MCP tools:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      }
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    }
  }
}
```

pflow also accepts a simpler direct format (without the `mcpServers` wrapper):

```json
{
  "github": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "env": {
      "GITHUB_TOKEN": "${GITHUB_TOKEN}"
    }
  }
}
```

### Environment Variables

Use `${VAR}` syntax for environment variable expansion:

```bash
# Environment variables in JSON configs are expanded at runtime
pflow mcp add '{"github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"], "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}}}'
```

## Available MCP Servers

### Official Servers

1. **Filesystem** - File operations
   ```bash
   npx -y @modelcontextprotocol/server-filesystem /path/to/dir
   ```

2. **GitHub** - GitHub API operations
   ```bash
   npx -y @modelcontextprotocol/server-github
   # Requires: GITHUB_TOKEN
   ```

3. **GitLab** - GitLab API operations
   ```bash
   npx -y @modelcontextprotocol/server-gitlab
   # Requires: GITLAB_API_TOKEN
   ```

4. **Slack** - Slack operations
   ```bash
   npx -y @modelcontextprotocol/server-slack
   # Requires: SLACK_TOKEN
   ```

5. **Google Drive** - Google Drive operations
   ```bash
   npx -y @modelcontextprotocol/server-google-drive
   # Requires OAuth setup
   ```

### Community Servers

See the [MCP Servers List](https://github.com/modelcontextprotocol/servers) for more servers.

## How It Works

### Virtual Node Registration

When you sync an MCP server, pflow:
1. Connects to the server and discovers available tools
2. Creates a "virtual" registry entry for each tool
3. All entries point to the same `MCPNode` class
4. The compiler injects metadata to identify which tool to execute

### Execution Flow

```
User Request → pflow finds mcp-github-create-issue →
Compiler injects server="github", tool="create-issue" →
MCPNode starts GitHub server subprocess →
Executes tool via JSON-RPC protocol →
Returns result to workflow
```

### Architecture Benefits

- **No code generation** - One MCPNode class handles all tools
- **Dynamic discovery** - Tools update when servers update
- **Clean namespacing** - No conflicts between servers
- **Zero custom code** - Any MCP server works automatically

## Advanced Usage

### Using MCP Tools in Complex Workflows

````markdown
# Issue Analysis

Fetch open issues from GitHub, categorize them with an LLM, and save a report.

## Steps

### list-issues

Fetch all open issues from the GitHub repository.

- type: mcp-github-list_issues
- repo: myorg/myrepo
- state: open

### analyze

Categorize the issues by type and priority.

- type: llm

```prompt
Categorize these issues: ${list-issues.result}
```

### save-report

Save the categorized report to a file.

- type: mcp-filesystem-write_file
- path: /tmp/issue-report.md
- content: ${analyze.result}
````
```

### Forcing Tool Re-discovery

If an MCP server updates its tools:

```bash
# Force re-sync to update tool list
pflow mcp sync filesystem --force
```

## Running pflow as an MCP Server

pflow can also run as an MCP server itself, exposing its workflow capabilities as tools for AI agents.

```bash
# Start pflow as an MCP server (stdio transport)
pflow mcp serve

# With debug logging
pflow mcp serve --debug
```

This exposes pflow's workflow building and execution capabilities as programmatic tools for AI agents:
- Discover existing workflows and nodes
- Execute workflows with structured output
- Validate workflows before execution
- Save workflows to the global library
- Configure settings and API keys

**Note**: This command is typically invoked by AI agents/clients, not directly by users. The server uses stdio transport where stdin receives JSON-RPC requests and stdout sends responses.

## Troubleshooting

### Server Not Starting

```bash
# Check if command exists
which npx

# Test server manually
npx -y @modelcontextprotocol/server-filesystem /tmp
```

### Tools Not Found

```bash
# Verify server is configured
pflow mcp list

# Re-sync tools
pflow mcp sync <server-name>

# Check registered tools
pflow mcp tools <server-name>
```

### Environment Variables Not Working

- Ensure variables are exported: `export GITHUB_TOKEN=...`
- Check configuration: `cat ~/.pflow/mcp-servers.json`
- Verify expansion: Variables use `${VAR}` syntax

### Permission Errors

- Filesystem server only accesses allowed directories
- Check server documentation for access requirements
- Some servers require authentication tokens

## Transport Support

### stdio (Production-Ready)

The stdio transport is fully supported and recommended for most use cases:
- Reliable subprocess communication
- Works with all standard MCP servers
- Automatic process management

### HTTP (Experimental)

HTTP transport code exists but is not fully functional:
- Connection and handshake issues remain
- Not recommended for production use
- May be improved in future releases

## Limitations (MVP)

Current implementation supports:
- ✅ stdio transport (production-ready)
- ✅ Text content handling
- ✅ Manual tool discovery via sync
- ✅ Basic error handling
- ✅ pflow as MCP server (`pflow mcp serve`)

Future enhancements will add:
- HTTP/SSE transports (stable)
- Binary content (images, files)
- Connection pooling
- OAuth authentication
- Auto-discovery on startup

## Security Considerations

- MCP servers run as subprocesses with your user permissions
- Only install servers from trusted sources
- Review tool permissions before syncing
- Store tokens securely (use environment variables)
- Be cautious with filesystem access paths

## Contributing

To add support for new MCP servers:
1. Test the server works with stdio transport
2. Document required environment variables
3. Submit examples to the pflow repository

For MCP protocol questions, see [modelcontextprotocol.io](https://modelcontextprotocol.io).