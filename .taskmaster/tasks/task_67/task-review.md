# Task 67 Review: Fix MCP Standard Format Compatibility

## Metadata
<!-- Implementation Date: 2025-01-19 -->
<!-- Session ID: e54ce0cf-d005-458d-97e3-a29fdf2e5623 -->
<!-- GitHub Issue: https://github.com/spinje/pflow/issues/29 -->

## Executive Summary
Fixed critical runtime failures where MCP nodes couldn't find configured servers due to format mismatches between refactored components. Migrated completely to standard MCP format (`mcpServers` key) and fixed auto-discovery, eliminating ~500 lines of conversion code.

## Implementation Overview

### What Was Built
Completed migration to standard MCP configuration format, fixing runtime breakage that prevented all MCP workflows from executing. The original refactor (Task 47) had migrated most components but missed critical runtime paths in MCPNode and auto-discovery.

### Implementation Approach
Direct fixes to broken components rather than rollback - located each failure point through debugging user workflows and fixed in place. No backwards compatibility layer needed (zero users).

## Files Modified/Created

### Core Changes
- `src/pflow/nodes/mcp/node.py` - Changed config key from `"servers"` to `"mcpServers"` in _load_server_config()
- `src/pflow/mcp/registrar.py` - Added missing register_tools() method for auto-discovery
- `src/pflow/mcp/discovery.py` - Added stderr suppression for non-verbose mode
- `src/pflow/cli/main.py` - Already had auto-discovery, just needed other fixes to work

### Test Files
- `tests/test_cli/test_mcp_auto_discovery.py` - Fixed all 7 failing tests by correcting import paths

## Integration Points & Dependencies

### Incoming Dependencies
- Planner -> MCPNode (generates workflows using MCP tools)
- WorkflowExecutor -> MCPNode (executes MCP tool calls)
- CLI mcp commands -> MCPServerManager (manages configs)

### Outgoing Dependencies
- MCPNode -> MCPServerManager (reads config file directly)
- Auto-discovery -> MCPDiscovery -> MCPRegistrar -> Registry
- MCPRegistrar -> SettingsManager (for node filtering)

### Shared Store Keys
None created - MCP nodes use dynamic keys based on tool parameters

## Architectural Decisions & Tradeoffs

### Key Decisions
1. **No Migration Code** -> Direct standard format only -> Simpler, zero users means no compatibility needed
2. **MCPNode reads config directly** -> Instead of using manager -> Avoided circular dependency during refactor
3. **Explicit /dev/null for stderr** -> Instead of None -> MCP SDK wasn't fully suppressing with None

### Technical Debt Incurred
- MCPNode duplicates config loading logic from MCPServerManager (should be consolidated)
- Test mocking is fragile with specific import paths

## Testing Implementation

### Test Strategy Applied
Debugged with real user workflows first to find actual failure points, then fixed tests to match new reality. Used real MCP servers (Composio) for validation.

### Critical Test Cases
- `test_mcp_auto_discovery.py` - Validates entire discovery pipeline
- Real workflow execution with `slack-composio` server
- Manual `pflow mcp sync --all` for all configured servers

## Unexpected Discoveries

### Gotchas Encountered
1. **MCPNode bypasses MCPServerManager** - It reads ~/.pflow/mcp-servers.json directly, so format changes broke it
2. **register_tools() didn't exist** - Auto-discovery was calling a method that was never implemented
3. **Test import paths matter** - `pflow.mcp.MCPServerManager` vs `pflow.mcp.manager.MCPServerManager`

### Edge Cases Found
- Empty `mcpServers` object is valid (not null/missing)
- Server stderr appears even with errlog=None in stdio_client

## Patterns Established

### Reusable Patterns
```python
# Explicit stderr suppression for MCP servers
import os
if verbose:
    errlog = sys.stderr
else:
    errlog = open(os.devnull, 'w')
# Use in finally block to close
```

### Anti-Patterns to Avoid
- Don't use `errlog=None` for stdio_client - doesn't fully suppress
- Don't patch module paths in tests - patch package imports

## Breaking Changes

### API/Interface Changes
- Config format completely changed from internal to standard
- `transport` field renamed to `type`
- `command` now split into `command` and `args` array

### Behavioral Changes
- Auto-discovery now shows progress only in verbose mode
- MCP tools require manual sync or config change to appear

## Future Considerations

### Extension Points
- MCPServerManager.parse_standard_mcp_config() for reading external configs
- Auto-discovery caching prevents re-discovery on every run

### Scalability Concerns
- Each MCP tool discovery starts a server process (temporary but could be slow with many servers)

## AI Agent Guidance

### Quick Start for Related Tasks
1. **Read first**: `src/pflow/mcp/manager.py` for config format
2. **Test with**: Real config files from Claude Code docs
3. **Debug with**: `uv run pflow mcp sync --all` to validate changes

### Common Pitfalls
1. **MCPNode reads config directly** - Changes to manager don't affect it
2. **Auto-discovery needs register_tools()** - Not sync_server()
3. **Test imports must match** - Use package imports not module paths
4. **Server lifecycle is temporary** - Servers start for discovery then stop

### Test-First Recommendations
Run these first when modifying MCP:
```bash
# Quick validation
uv run pytest tests/test_cli/test_mcp_auto_discovery.py -xvs

# Full MCP suite
uv run pytest tests/test_mcp/ -xvs

# Manual validation
uv run pflow mcp sync --all
```

---

*Generated from implementation context of Task 67*