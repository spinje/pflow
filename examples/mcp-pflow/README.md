# pflow MCP Server Setup

This directory contains configuration examples for running pflow as an MCP (Model Context Protocol) server with Claude Desktop.

## Overview

The pflow MCP server exposes pflow's workflow capabilities to AI agents like Claude Desktop, enabling them to:
- Discover and execute existing workflows
- Build new workflows using natural language
- Run individual nodes to explore outputs
- Validate and save workflows

## Installation Methods

### Development Installation (Current - Local Repository)

When developing pflow or using it from a local clone, you need to use the `--directory` flag to point `uv` to your local project.

**Configuration:**
```json
{
  "mcpServers": {
    "pflow": {
      "command": "/opt/homebrew/bin/uv",
      "args": [
        "run",
        "--directory",
        "/Users/YOUR_USERNAME/projects/pflow",
        "pflow",
        "mcp",
        "serve"
      ]
    }
  }
}
```

**Why the quirks?**
1. **Absolute path for `uv`**: Claude Desktop may not have your shell's PATH environment, so we specify the full path to the `uv` binary
2. **`--directory` flag**: Tells `uv run` which project to use since pflow isn't installed globally
3. **No `cwd` field**: The `--directory` flag is more explicit and reliable than `cwd`

**Finding your `uv` path:**
```bash
which uv
# Common locations:
# - /opt/homebrew/bin/uv (macOS Homebrew on Apple Silicon)
# - /usr/local/bin/uv (macOS Homebrew on Intel)
# - ~/.cargo/bin/uv (Rust/Cargo installation)
```

### Production Installation (Future - PyPI)

Once pflow is published to PyPI, installation will be much simpler:

**Step 1: Install pflow globally**
```bash
# Using uv (recommended)
uv tool install pflow

# Or using pipx
pipx install pflow

# Or using pip
pip install --user pflow
```

**Step 2: Simple Claude Desktop configuration**
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

**Why it's simpler:**
- `pflow` command is in your PATH (no absolute paths needed)
- No `--directory` flag needed (installed as a package)
- No `cwd` field needed
- Works the same across all machines

## Setup Instructions

### 1. Locate Claude Desktop Config

The configuration file is at:
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

On macOS, you can edit it with:
```bash
open -a "TextEdit" ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

### 2. Choose Your Configuration

**For Development (Local Clone):**

Use `example-claude-desktop-config.json` as a template and update the path:

```bash
# 1. Copy the example
cp examples/mcp-pflow/example-claude-desktop-config.json \
   ~/Library/Application\ Support/Claude/claude_desktop_config.json

# 2. Edit and replace /path/to/pflow with YOUR project path
# Find your project path:
pwd  # Run this in the pflow directory
```

**For Production (PyPI - Future):**

Use the simpler configuration shown above.

### 3. Restart Claude Desktop

Completely quit and reopen Claude Desktop for the configuration to take effect.

## Verification

### Test the Command Manually

Before configuring Claude Desktop, verify the command works:

```bash
# Development installation
/opt/homebrew/bin/uv run --directory /path/to/pflow pflow --version

# Test MCP server starts
echo '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}},"id":1}' | \
  /opt/homebrew/bin/uv run --directory /path/to/pflow pflow mcp serve
```

You should see:
- Server initialization logs
- A JSON-RPC response with server capabilities
- No error messages

### Check Claude Desktop Logs

If the server fails to start, check the logs:

**macOS:**
```bash
# View logs
tail -f ~/Library/Logs/Claude/mcp*.log

# Or in Claude Desktop: Settings → Developer → View Logs
```

**Common errors:**
- `Failed to spawn: pflow` → Wrong path or `--directory` not set correctly
- `No such file or directory` → `uv` path is wrong or pflow directory doesn't exist
- `Server transport closed` → Check that the command works when run manually

## Available Tools

Once configured, Claude Desktop can use these pflow tools:

**Discovery Tools:**
- `workflow_discover` - Find existing workflows using natural language
- `registry_discover` - Find nodes/components for building workflows

**Execution Tools:**
- `workflow_execute` - Run a workflow (from library, file, or dict)
- `workflow_validate` - Validate workflow structure and references
- `workflow_save` - Save a workflow to the library
- `registry_run` - Execute a single node to explore its output

**Supporting Tools:**
- `registry_list` - List all available nodes (with optional filter)
- `registry_describe` - Get detailed node specifications
- `workflow_list` - List saved workflows (with optional filter)
- `workflow_describe` - Get workflow interface details (inputs/outputs)

## Troubleshooting

### Issue: "Failed to spawn: pflow"

**Cause:** The `pflow` command isn't found in the specified directory.

**Solution:**
1. Verify the path in `--directory` points to your pflow project root
2. Test the command manually (see Verification section)
3. Make sure you've installed dependencies: `cd /path/to/pflow && uv sync`

### Issue: "Server transport closed unexpectedly"

**Cause:** The server started but crashed during initialization.

**Solution:**
1. Run the test command manually to see full error output
2. Check that all dependencies are installed
3. Verify Python version (requires 3.10+)

### Issue: Changes not taking effect

**Cause:** Claude Desktop hasn't reloaded the configuration.

**Solution:**
1. Completely quit Claude Desktop (Cmd+Q)
2. Wait a few seconds
3. Reopen Claude Desktop
4. The MCP server should reinitialize

## Migration Path to PyPI

When pflow is published to PyPI, you can migrate in two steps:

**Step 1: Install globally**
```bash
uv tool install pflow
# or
pipx install pflow
```

**Step 2: Simplify config**
Replace your Claude Desktop config with the simpler version (see "Production Installation" above).

**Benefits:**
- ✅ No absolute paths to maintain
- ✅ Works the same on all machines
- ✅ Automatic updates with `uv tool upgrade pflow`
- ✅ Cleaner, more portable configuration

## Additional Resources

- **pflow documentation**: See `../../docs/mcp-server.md`
- **MCP debugging guide**: https://modelcontextprotocol.io/docs/tools/debugging
- **Task 72 implementation log**: See `.taskmaster/tasks/task_72/implementation/progress-log.md` for development history

## Questions?

If you encounter issues not covered here:
1. Check the Claude Desktop logs (see "Check Claude Desktop Logs" above)
2. Verify the command works manually
3. Review the progress log for known issues and fixes


