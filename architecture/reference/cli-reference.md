# CLI Reference

> **Note**: The CLI is extensively documented in multiple locations. This file serves as a navigation guide.

## Authoritative Sources

### For Understanding CLI Structure
See **[architecture.md](../architecture.md#cli-interface)** - Covers:
- Running workflows (file and saved)
- Workflow management commands
- Settings management

### For AI Agents Building Workflows
Run `pflow instructions usage` - The comprehensive agent guide covering:
- Discovery commands (`workflow discover`, `registry discover`)
- Execution commands (`registry run`, workflow execution)
- Building and saving workflows

### For Implementation Details
See **`src/pflow/cli/CLAUDE.md`** - Internal CLI implementation guide

## Quick Command Reference

```bash
# Execute workflows
pflow workflow.json [params]           # Run from file
pflow saved-name [params]              # Run saved workflow

# Workflow management
pflow workflow list [filter]           # List saved workflows
pflow workflow describe <name>         # Show workflow details
pflow workflow save <file> --name <n>  # Save workflow
pflow workflow discover "description"  # Find workflows (LLM-powered)

# Node registry
pflow registry list [filter]           # List available nodes
pflow registry describe <node>         # Show node interface
pflow registry run <node> [params]     # Execute single node
pflow registry discover "capability"   # Find nodes (LLM-powered)

# Settings
pflow settings show                    # Show current settings
pflow settings allow <node>            # Allow node type
pflow settings deny <node>             # Deny node type

# MCP
pflow mcp list                         # List MCP servers
pflow mcp serve                        # Start MCP server
```

## Historical Note

The original cli-reference.md described a `=>` CLI composition syntax that was never implemented. pflow uses JSON workflow files for composition, not CLI operators. See `historical/cli-reference-original.md` for the original design document.
