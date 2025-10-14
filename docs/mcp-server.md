# pflow MCP Server

Expose pflow's workflow tools to AI assistants like Claude Code, Gemini Cli, Codex Cli, Cursor Cli and even desktop apps like Claude Desktop via the Model Context Protocol.

## Prerequisites

- Python 3.9 or higher
- [uv](https://docs.astral.sh/uv/) package manager

## Installation

Install pflow as an isolated command-line tool:

```bash
uv tool install pflow-cli
```

## Configuration

### Claude Desktop

Add pflow to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pflow": {
      "command": "pflow",
      "args": ["mcp", "serve"]
    }
  }
}
```

Restart Claude Desktop and verify the connection works (see [Verification](#verification) below).

> **Note**: If you get "command not found" errors, see [Troubleshooting](#command-not-found-errors) for the explicit path approach.

### Other MCP Clients

pflow implements the standard MCP stdio protocol. Consult your client's documentation for configuration details.

## Verification

1. Restart Claude Desktop
2. Look for a pflow connection indicator in the interface
3. Try: "List available pflow tools"

If successful, Claude will show 11 workflow building tools.

## Available Tools

pflow provides these MCP tools:

- **workflow_discover** - Find existing workflows by description
- **workflow_execute** - Run workflows with parameters
- **workflow_validate** - Check workflow syntax before running
- **workflow_save** - Save workflows to library
- **workflow_list** - List all saved workflows
- **workflow_describe** - Show workflow inputs and outputs
- **registry_discover** - Find nodes for building workflows (AI-powered)
- **registry_run** - Test a node to see its output structure
- **registry_describe** - Get detailed node specifications
- **registry_search** - Search for nodes by keyword
- **registry_list** - List all available nodes

## Troubleshooting

### "Command not found" errors

If Claude Desktop can't find pflow, use the explicit path instead.

**Find your pflow path:**
```bash
which pflow
# Output: /Users/username/.local/bin/pflow
```

**Update your config with the full path:**
```json
{
  "mcpServers": {
    "pflow": {
      "command": "/Users/username/.local/bin/pflow",
      "args": ["mcp", "serve"]
    }
  }
}
```

Then restart Claude Desktop.

> **Why does this happen?** Some GUI applications don't inherit your shell's PATH environment variable. The explicit path works regardless of PATH configuration.

### Development installations

If you're developing pflow in a git worktree, use the virtualenv path directly:

```json
{
  "mcpServers": {
    "pflow": {
      "command": "/path/to/pflow/.venv/bin/pflow",
      "args": ["mcp", "serve"]
    }
  }
}
```

### Server logs

Check logs if the server fails to start:

```bash
# macOS
tail -f ~/Library/Logs/Claude/mcp-server-pflow.log

# Linux
tail -f ~/.config/Claude/logs/mcp-server-pflow.log
```

## Next Steps

- [Learn about workflow building](getting-started.md)
- [Browse node types](nodes.md)
- [See examples](examples.md)
- [Connect to remote MCP servers](mcp-http-transport.md)
