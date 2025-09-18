# Task 47 Review: Integrate MCP Solution with Composio via Streamable HTTP Transport

## Metadata
- **Implementation Date**: 2025-01-16
- **Session ID**: e8f90307-86e9-4da9-9992-675b31b8c1c4
- **Branch**: feat/integrate-mcp-composio

## Executive Summary
Implemented Streamable HTTP transport support for MCP servers, enabling pflow to connect to remote MCP services including Composio. The implementation leverages the MCP SDK's `streamablehttp_client` and maintains the universal node pattern. Successfully validated with local test servers. A critical post-implementation discovery: this also enables MCP gateway support (Docker MCP Gateway, IBM Context Forge) without additional changes, solving OAuth complexity through gateway-managed authentication.

## Implementation Overview

### What Was Built
Full Streamable HTTP transport layer for MCP with:
- Transport routing in MCPNode (stdio vs HTTP)
- Authentication system (Bearer, API key, Basic auth)
- Recursive environment variable expansion for nested configs
- HTTP-specific error handling with user-friendly messages
- CLI support for adding/managing HTTP servers
- Tool discovery over HTTP
- Comprehensive documentation and testing infrastructure
- (Discovered post-implementation: Full gateway compatibility)

### Implementation Approach
Leveraged existing MCP SDK's `streamablehttp_client` instead of implementing protocol from scratch. Maintained universal node pattern where MCPNode remains server-agnostic. Transport differences isolated to configuration and initial connection setup.

## Files Modified/Created

### Core Changes
- `src/pflow/nodes/mcp/node.py` - Added transport routing, HTTP execution, auth headers, nested env var expansion
- `src/pflow/mcp/manager.py` - Extended validation for HTTP configs, updated add_server signature
- `src/pflow/mcp/discovery.py` - Added HTTP discovery path, fixed nested env var expansion
- `src/pflow/cli/mcp.py` - Added HTTP transport options (--url, --auth-type, etc.)

### Test Files
- `tests/test_mcp/test_http_transport.py` - Created comprehensive HTTP transport tests
- `test-mcp-http-server.py` - Local MCP HTTP server for testing
- `test-http-transport.sh` - Automated test script for HTTP transport
- **19 test files updated** - Fixed add_server() signature changes throughout test suite

### Documentation
- `docs/mcp-http-transport.md` - User-facing documentation for HTTP transport
- `.taskmaster/tasks/task_47/streamable-http-transport-spec.md` - Implementation spec

Critical tests:
- `test_http_config_validation_*` - Validates all HTTP config edge cases
- `test_expand_env_vars_nested` - Ensures nested auth configs work
- Manual testing with `test-mcp-http-server.py` - Validated full protocol flow

## Integration Points & Dependencies

### Incoming Dependencies
- Planner -> MCPNode (generates workflows using HTTP-based MCP tools)
- Compiler -> MCPNode (injects __mcp_server__ and __mcp_tool__ metadata)
- Registry -> Virtual MCP entries (mcp-composio-slack-list_channels etc.)

### Outgoing Dependencies
- MCPNode -> streamablehttp_client (MCP SDK for HTTP transport)
- MCPNode -> MCPServerManager (loads server configs)
- MCPDiscovery -> streamablehttp_client (discovers tools over HTTP)

### Shared Store Keys
No new shared store keys - HTTP transport maintains same interface as stdio.

## Architectural Decisions & Tradeoffs

### Key Decisions
1. **No session caching** -> Keep MVP simple -> Considered class-level cache but adds complexity
2. **Universal node pattern** -> MCPNode stays server-agnostic -> Alternative: separate HTTPMCPNode class
3. **Recursive env var expansion** -> Handle nested auth configs -> Fixed critical bug in original implementation
4. **Transport routing in _exec_async** -> Clean separation -> Alternative: inheritance hierarchy

### Technical Debt Incurred
- No connection pooling (new connection per execution) - acceptable for MVP
- No OAuth support - deferred to gateways/partners
- No automatic token refresh - users must update manually
- Session IDs discarded after each execution - could cache for performance

## Testing Implementation

### Test Strategy Applied
Mock boundaries only - mock `streamablehttp_client` not internal logic. Test through real code paths using compiler and flow execution.

### Critical Test Cases
- `test_expand_env_vars_nested` - Caught the nested dict bug that would have broken all auth
- `test_http_config_validation_auth_types` - Validates each auth type configuration
- `test_exec_async_http_routing` - Ensures transport selection works correctly

## Unexpected Discoveries

### Gotchas Encountered
1. **Nested env vars were broken** - Current `_expand_env_vars()` only worked on flat dicts
2. **Composio uses URL-embedded auth** - UUID in URL path, not traditional API keys (simpler than expected)
3. **Union types in JSON schemas** - Some servers return `["string", "null"]` for nullable params
4. **Saved workflows interfere** - Planner prioritizes saved workflows over registry entries
5. **MCPRegistrar initialization bug** - CLI passed manager as positional instead of keyword arg
6. **Gateway compatibility discovered** - Post-implementation finding: HTTP transport works with MCP gateways without changes

### Edge Cases Found
- Server names with hyphens work fine (`test-http`)
- Empty env vars cause silent failures (now logged)
- HTTP 404 can mean session expired OR endpoint missing
- Some MCP servers don't populate outputSchema

## Patterns Established

### Reusable Patterns

**Transport routing pattern**:
```python
async def _exec_async(self, prep_res: dict) -> dict:
    transport = config.get("transport", "stdio")
    if transport == "http":
        return await self._exec_async_http(prep_res)
    elif transport == "stdio":
        return await self._exec_async_stdio(prep_res)
```

**Recursive env var expansion**:
```python
def _expand_env_vars_nested(self, data: Any) -> Any:
    if isinstance(data, dict):
        return {k: self._expand_env_vars_nested(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [self._expand_env_vars_nested(item) for item in data]
    elif isinstance(data, str):
        # Pattern substitution...
```

### Anti-Patterns to Avoid
- Don't try to cache sessions with `asyncio.run()` pattern - event loops are destroyed
- Don't add server-specific logic to MCPNode - breaks universal node principle
- Don't use positional arguments for manager methods - causes widespread test breakage

## Breaking Changes

### API/Interface Changes
- `MCPServerManager.add_server()` signature changed - transport now before command
- All test calls updated to use keyword arguments

### Behavioral Changes
- MCP tools can now come from remote servers
- Discovery can happen over network (timeout considerations)

## Future Considerations

### Extension Points
- Add new auth types in `_build_auth_headers()`
- Add new transports in `_exec_async()` router
- Session caching could go in class-level dict
- Gateway-aware features (Task 65) - show backend service metadata

### Gateway Integration (Task 65)
- HTTP transport already supports MCP gateways
- Enables OAuth services without implementation
- Docker MCP Gateway and IBM Context Forge compatible
- Documentation and testing needed to expose this capability

### Scalability Concerns
- No connection pooling means overhead for MCP-heavy workflows
- Session creation per execution (~420ms overhead per Task 43 findings)
- Consider AsyncNode when available for proper pooling
- Gateways can provide connection pooling to backend services

## AI Agent Guidance

### Quick Start for Related Tasks

**For adding new auth types**:
1. Read `_build_auth_headers()` in `src/pflow/nodes/mcp/node.py`
2. Add validation in `_validate_auth_config()` in `src/pflow/mcp/manager.py`
3. Update CLI options in `src/pflow/cli/mcp.py`

**For debugging MCP tool issues**:
1. Check for saved workflows first: `ls ~/.pflow/workflows/`
2. Verify tool names with: `pflow registry list | grep mcp`
3. Test discovery: `pflow mcp sync <server-name>`
4. Enable verbose mode to see MCP protocol messages

**Key files to read first**:
- `src/pflow/nodes/mcp/node.py` - lines 184-326 for transport implementation
- `tests/test_mcp/test_http_transport.py` - for test patterns

### Common Pitfalls
1. **Forgetting nested env var expansion** - Auth configs are nested, must use recursive version
2. **Union types in schemas** - Real servers return `["string", "null"]`, handle lists
3. **Saved workflow interference** - Delete conflicting workflows when tool names change
4. **Position vs keyword args** - Always use keyword args for manager methods
5. **Async test patterns** - Project doesn't use pytest-asyncio, use `asyncio.run()`

### Test-First Recommendations
When modifying HTTP transport:
1. Run `pytest tests/test_mcp/test_http_transport.py` first
2. Check `test_expand_env_vars_nested` - critical for auth
3. Verify `test_http_config_validation_*` - catches config errors
4. Run integration test with local HTTP server (see `test-mcp-http-server.py`)

---

*Generated from implementation context of Task 47*