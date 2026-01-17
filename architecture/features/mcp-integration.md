# MCP Integration

> **Status**: ✅ Implemented

MCP (Model Context Protocol) is fully integrated into pflow.

## Current Capabilities

- **MCP Client**: Connect to external MCP servers (stdio + HTTP transports)
- **MCP Server**: Expose pflow as MCP server (11 tools for AI agents)
- **CLI**: `pflow mcp add|list|sync|serve|tools|info`

## Documentation

- **Client implementation**: `src/pflow/mcp/CLAUDE.md`
- **Server implementation**: `src/pflow/mcp_server/CLAUDE.md`
- **CLI commands**: Run `pflow mcp --help`

## Historical

For the original v2.0 design document, see `historical/mcp-integration-original.md`
