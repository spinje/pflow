# Task 67: Fix MCP Standard Format Compatibility

## Description
Ensure pflow uses the standard MCP configuration format (`mcpServers` key) for full compatibility with Claude Code, Claude Desktop, and other MCP clients. This eliminates format conversion bugs and allows users to share configuration files across different MCP-compatible tools.

## Status
done

## Completed
2025-09-19

## Dependencies
- Task 43: MCP Server support - Provides the base MCP functionality that needs format standardization
- Task 47: Implement MCP HTTP transport - Extended MCP support that also needed to use the standard format

## Priority
high

## Details
This task addressed critical runtime failures where MCP nodes couldn't find configured servers due to format mismatches between the refactored code and runtime components. The root issue was that pflow was using a non-standard internal format that was incompatible with the MCP ecosystem.

### Key Problems Fixed
1. **Wrong Config Key in MCPNode**: The node was looking for servers under `"servers"` instead of `"mcpServers"`
2. **Missing register_tools() Method**: Auto-discovery was calling a non-existent method, causing silent registration failures
3. **Test Import Paths**: Tests were using wrong module paths after the refactor
4. **Noisy Server Output**: MCP server stderr was always shown during discovery

### Implementation Approach (MVP)
- Complete removal of internal format and migration code (no backwards compatibility needed - zero users)
- Direct adoption of standard MCP format as the only supported format
- Updated `pflow mcp add` to accept standard JSON config files
- Added `${VAR:-default}` environment variable syntax support
- Fixed auto-discovery to properly register tools with the standard format

### Technical Changes
- `MCPServerManager`: Removed all format conversion methods, works directly with standard format
- `MCPNode._load_server_config()`: Updated to read from `mcpServers` key
- `MCPRegistrar`: Added missing `register_tools()` method for auto-discovery
- `MCPDiscovery`: Suppress server stderr to `/dev/null` when not in verbose mode
- All tests: Updated to use standard format and correct import paths

### Standard Format Structure
```json
{
  "mcpServers": {
    "server-name": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-name"],
      "env": {"API_KEY": "${API_KEY:-default}"}
    }
  }
}
```

## Test Strategy
Testing focused on ensuring the standard format works end-to-end:

- **Unit Tests**: Updated 145+ MCP tests to use standard format
- **Integration Tests**: Validated with real MCP servers (filesystem, Slack via Composio, Google Sheets)
- **Manual Testing**: Confirmed config files from Claude Code documentation work directly
- **Auto-discovery Tests**: Verified tools are properly registered and persisted in the registry
- **Output Control Tests**: Ensured server stderr is suppressed unless verbose mode is active

Key test scenarios:
- Config file loading and parsing with standard format
- Tool discovery and registration in the registry
- Runtime execution finding servers correctly
- Environment variable expansion including default values
- Cross-client config file compatibility
