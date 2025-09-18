# Task 47: Streamable HTTP Transport Implementation Research Findings

## Executive Summary

After extensive research into the pflow codebase and MCP protocol specifications, implementing Streamable HTTP transport for MCP is not only feasible but architecturally straightforward. The MCP Python SDK already includes `streamablehttp_client` support, and the current MCPNode architecture is well-designed for extension with minimal changes required.

## Key Discoveries

### 1. MCP SDK Already Has Full HTTP Support

**Finding**: The MCP Python SDK includes `mcp.client.streamable_http.streamablehttp_client`
- Provides the same `ClientSession` interface as stdio transport
- Returns `(read, write, get_session_id)` tuple (extra session ID callback)
- Handles all protocol details including SSE streaming
- Supports authentication via headers and httpx.Auth

**Impact**: We don't need to implement HTTP protocol handling from scratch - just integrate the existing client.

### 2. MCPNode Architecture is Perfect for Extension

**Finding**: The current `MCPNode` class uses clean separation between transport setup and protocol logic:
```python
def exec(self, prep_res: dict) -> dict:
    return asyncio.run(self._exec_async(prep_res))

async def _exec_async(self, prep_res: dict) -> dict:
    # Transport setup (differs)
    async with transport_client(...) as (...):
        async with ClientSession(...) as session:
            # Protocol logic (identical for both transports)
            await session.initialize()
            result = await session.call_tool(...)
```

**Impact**: 80% of the code can be reused - only transport setup differs.

### 3. Configuration Structure Needs Minor Extension

**Current stdio config**:
```json
{
  "command": "npx",
  "args": ["@modelcontextprotocol/server-github"],
  "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
  "transport": "stdio"
}
```

**Required HTTP config**:
```json
{
  "url": "https://api.example.com/mcp",
  "transport": "http",
  "auth": {
    "type": "bearer",
    "token": "${API_TOKEN}"
  },
  "headers": {},
  "session": {
    "timeout": 3600
  }
}
```

**Impact**: MCPServerManager needs validation logic for HTTP-specific fields.

### 4. Session Caching is Limited but Possible

**Finding**: Due to `asyncio.run()` creating new event loops each execution:
- True connection pooling is impossible in current architecture
- Session ID caching (as strings) is feasible
- Full connection pooling requires AsyncNode (post-MVP)

**Recommendation**: Implement without session caching for MVP simplicity.

### 5. Discovery Works Over HTTP

**Finding**: Tool discovery can work over HTTP with minimal changes:
- Same `ClientSession.list_tools()` interface
- Just swap `stdio_client` for `streamablehttp_client`
- Security considerations for remote discovery are manageable

**Impact**: Both local and remote servers can populate the same registry.

## Implementation Requirements

### Core Changes Needed

#### 1. MCPNode Transport Selection
```python
async def _exec_async(self, prep_res: dict) -> dict:
    config = prep_res["config"]
    transport = config.get("transport", "stdio")

    if transport == "http":
        return await self._exec_async_http(prep_res)
    else:
        return await self._exec_async_stdio(prep_res)  # Current implementation
```

#### 2. HTTP Transport Implementation
```python
async def _exec_async_http(self, prep_res: dict) -> dict:
    from mcp.client.streamable_http import streamablehttp_client

    url = config["url"]
    headers = self._build_auth_headers(config)

    async with streamablehttp_client(url, headers=headers) as (read, write, get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(prep_res["tool"], prep_res["arguments"])
            return {"result": self._extract_result(result)}
```

#### 3. Configuration Validation
- Remove hardcoded "stdio-only" restriction
- Add transport-specific validation methods
- Support URL, auth, headers fields for HTTP

#### 4. Authentication Support
```python
def _build_auth_headers(self, config: dict) -> dict:
    headers = config.get("headers", {}).copy()
    auth = config.get("auth", {})

    if auth.get("type") == "bearer":
        token = self._expand_env_vars({"token": auth["token"]})["token"]
        headers["Authorization"] = f"Bearer {token}"
    elif auth.get("type") == "api_key":
        key = self._expand_env_vars({"key": auth["key"]})["key"]
        headers[auth.get("header", "X-API-Key")] = key

    return headers
```

### Protocol Requirements (Streamable HTTP)

#### Required Headers
- `Content-Type: application/json` (POST)
- `Accept: application/json, text/event-stream`
- `Mcp-Session-Id: <session-id>` (after initialization)

#### Session Management
- Server returns session ID in `Mcp-Session-Id` header
- Client must include in all subsequent requests
- Sessions can expire - handle 404 responses

#### Error Handling
- 401/403: Authentication failures
- 404: Session expired
- 429: Rate limiting
- Standard HTTP timeout handling

### Security Considerations

1. **URL Validation**: Enforce HTTPS for remote servers
2. **Environment Variables**: Use `${VAR}` pattern for secrets
3. **Origin Validation**: Prevent DNS rebinding attacks
4. **No Credential Logging**: Mask auth data in logs
5. **Timeout Controls**: Configurable per-server timeouts

## Testing Strategy

### Unit Tests
- Mock `streamablehttp_client` at boundary
- Test auth header construction
- Validate config parsing
- Error response handling

### Integration Tests
- Use mock HTTP server (aiohttp test utilities)
- Test full flow through compiler
- Session ID management
- Authentication scenarios

### Available Test Servers
1. **Atlassian MCP**: Production-ready OAuth server
2. **Kite Public Servers**: Zero-auth testing
3. **MCP Inspector**: Local debugging tool
4. **Community Servers**: GitHub, Slack implementations

## Architecture Decisions

### 1. No Session Caching for MVP
**Rationale**: Simplicity over optimization
- Matches stdio pattern (new process per execution)
- Avoids cache invalidation complexity
- Can be added later without breaking changes

### 2. Universal Node Pattern Maintained
**Rationale**: Server-agnostic design
- MCPNode remains universal for all MCP servers
- No server-specific logic in node
- Transport differences isolated to config/setup

### 3. Reuse Existing Patterns
**Rationale**: Consistency and reliability
- Environment variable expansion (`_expand_env_vars`)
- Error handling (`exec_fallback`)
- Config management (atomic writes)

## Implementation Timeline

### Phase 1: Core HTTP Transport (2-3 days)
1. Add `_exec_async_http()` method to MCPNode
2. Implement auth header building
3. Basic error handling for HTTP errors
4. Update config validation in MCPServerManager

### Phase 2: Discovery Support (1 day)
1. Add HTTP transport to MCPDiscovery
2. Update CLI for HTTP server addition
3. Test with real HTTP servers

### Phase 3: Testing & Hardening (1-2 days)
1. Unit tests for HTTP transport
2. Integration tests with mock servers
3. Test against real servers (Atlassian, Kite)
4. Security validation

### Phase 4: Documentation (0.5 days)
1. Update user documentation
2. Add HTTP server examples
3. Migration guide from stdio

## Risks and Mitigations

### Risk 1: Session Management Complexity
- **Mitigation**: Start without caching, add if needed

### Risk 2: Authentication Variety
- **Mitigation**: Support common patterns first (Bearer, API key)

### Risk 3: Network Reliability
- **Mitigation**: Robust timeout and retry handling

### Risk 4: Security Vulnerabilities
- **Mitigation**: HTTPS enforcement, proper credential handling

## Success Criteria

1. **Functional**: HTTP MCP servers work identically to stdio servers
2. **Secure**: No credential leaks, HTTPS enforced
3. **Performant**: Acceptable latency for remote servers
4. **Compatible**: Works with existing MCP server implementations
5. **Maintainable**: Clean separation of transport logic

## Conclusion

Implementing Streamable HTTP transport is a natural and straightforward extension of the current MCP architecture. The MCP SDK provides the necessary primitives, the MCPNode is well-designed for extension, and the changes required are isolated and minimal. This implementation directly enables the Composio integration strategy while maintaining backward compatibility with stdio transport.

The key insight is that we're not building HTTP support from scratch - we're integrating an existing, well-tested SDK feature into our already robust MCP node architecture. By following the patterns already established in the codebase and keeping the implementation simple for MVP, we can deliver this feature quickly and reliably.