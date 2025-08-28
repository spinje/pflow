# MCP (Model Context Protocol) Integration Guide

## Overview

MCP (Model Context Protocol) is an open standard that enables AI systems to interact with external tools and services. With pflow's MCP integration, you can connect to any MCP-compliant server and automatically use all its tools as workflow nodes—no custom integration code required.

## Quick Start

### 1. Add an MCP Server

```bash
# Add the official filesystem server
pflow mcp add filesystem npx -- -y @modelcontextprotocol/server-filesystem /tmp

# Add GitHub server (requires GITHUB_TOKEN environment variable)
pflow mcp add github npx -- -y @modelcontextprotocol/server-github -e GITHUB_TOKEN=${GITHUB_TOKEN}
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

# In a JSON workflow
{
  "ir_version": "0.1.0",
  "nodes": [{
    "id": "read",
    "type": "mcp-filesystem-read_text_file",
    "params": {"path": "/tmp/config.json"}
  }],
  "edges": []
}
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

### Environment Variables

Use `${VAR}` syntax for environment variable expansion:

```bash
# The ${GITHUB_TOKEN} will be replaced with actual env var value
pflow mcp add github npx -- -y @modelcontextprotocol/server-github -e GITHUB_TOKEN=${GITHUB_TOKEN}
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

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "list-issues",
      "type": "mcp-github-list_issues",
      "params": {
        "repo": "myorg/myrepo",
        "state": "open"
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "params": {
        "prompt": "Categorize these issues: ${list-issues.result}"
      }
    },
    {
      "id": "save-report",
      "type": "mcp-filesystem-write_file",
      "params": {
        "path": "/tmp/issue-report.md",
        "content": "${analyze.result}"
      }
    }
  ],
  "edges": [
    {"source": "list-issues", "target": "analyze", "action": "default"},
    {"source": "analyze", "target": "save-report", "action": "default"}
  ]
}
```

### Forcing Tool Re-discovery

If an MCP server updates its tools:

```bash
# Force re-sync to update tool list
pflow mcp sync filesystem --force
```

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

## Limitations (MVP)

Current implementation supports:
- ✅ stdio transport only
- ✅ Text content handling
- ✅ Manual tool discovery via sync
- ✅ Basic error handling

Future enhancements will add:
- HTTP/SSE transports
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