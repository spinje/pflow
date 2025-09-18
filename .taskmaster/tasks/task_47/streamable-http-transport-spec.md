# Streamable HTTP Transport Specification for pflow MCP Integration

## 1. Overview

### 1.1 Purpose
This specification defines the implementation of Streamable HTTP transport support for MCP (Model Context Protocol) servers in pflow, enabling communication with remote MCP servers over HTTP/HTTPS.

### 1.2 Scope
- Add HTTP transport alongside existing stdio transport
- Support common authentication mechanisms
- Enable discovery of tools from remote servers
- Maintain backward compatibility with existing stdio configurations

### 1.3 Non-Goals
- OAuth implementation (deferred to gateways/partners)
- Connection pooling (requires AsyncNode, post-MVP)
- WebSocket transport (not yet standardized)
- HTTP server implementation (client-only)

## 2. Technical Requirements

### 2.1 Protocol Version
- **MCP Protocol Version**: 2025-03-26 or later
- **Transport Type**: Streamable HTTP (not deprecated HTTP+SSE)
- **Endpoint**: Single `/mcp` endpoint supporting POST, GET, DELETE

### 2.2 Dependencies
- **MCP SDK**: Version 1.13.1+ with `mcp.client.streamable_http.streamablehttp_client` ✅ VERIFIED
- **Python**: 3.9+ (consistent with pflow requirements)
- **httpx**: Transitive dependency via MCP SDK
- **aiohttp**: Optional, for testing only

### 2.2.1 streamablehttp_client API (VERIFIED)
```python
async def streamablehttp_client(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float | timedelta = 30,
    sse_read_timeout: float | timedelta = 300,
    terminate_on_close: bool = True,
    httpx_client_factory: McpHttpClientFactory = <default>,
    auth: httpx.Auth | None = None
) -> AsyncContextManager[tuple[
    MemoryObjectReceiveStream[SessionMessage | Exception],
    MemoryObjectSendStream[SessionMessage],
    Callable[[], str | None]  # get_session_id callback
]]
```

### 2.3 Architectural Constraints
- **Synchronous Interface**: MCPNode must remain synchronous (Node base class)
- **Event Loop**: Each execution creates new event loop via `asyncio.run()`
- **No Instance State**: Nodes are copied for each execution (PocketFlow pattern)
- **Universal Node**: MCPNode must remain server-agnostic

## 3. Configuration Schema

### 3.1 HTTP Server Configuration

```json
{
  "servers": {
    "<server_name>": {
      "transport": "http",
      "url": "<https://api.example.com/mcp>",
      "auth": {
        "type": "<bearer|api_key|basic>",
        "token": "${ENV_VAR}",
        "key": "${API_KEY}",
        "header": "X-API-Key",
        "username": "${USERNAME}",
        "password": "${PASSWORD}"
      },
      "headers": {
        "<Header-Name>": "${VALUE}"
      },
      "timeout": 30,
      "sse_timeout": 300,
      "env": {
        "<KEY>": "${VALUE}"
      },
      "created_at": "ISO-8601",
      "updated_at": "ISO-8601"
    }
  }
}
```

### 3.2 Field Definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| transport | string | Yes | Must be "http" |
| url | string | Yes | Full URL including path |
| auth | object | No | Authentication configuration |
| auth.type | string | Yes* | Type of authentication |
| auth.token | string | Conditional | Bearer token (type=bearer) |
| auth.key | string | Conditional | API key (type=api_key) |
| auth.header | string | No | Header name for API key (default: X-API-Key) |
| auth.username | string | Conditional | Username (type=basic) |
| auth.password | string | Conditional | Password (type=basic) |
| headers | object | No | Additional HTTP headers |
| timeout | integer | No | HTTP timeout in seconds (default: 30) |
| sse_timeout | integer | No | SSE read timeout in seconds (default: 300) |
| env | object | No | Environment variables (for compatibility) |

### 3.3 Configuration Validation Rules

1. **URL Validation**:
   - Must start with `http://` or `https://`
   - Should enforce HTTPS for non-localhost URLs (warning)
   - Must be valid URL format

2. **Auth Validation**:
   - If auth provided, type is required
   - Type-specific fields must be present
   - Environment variable syntax `${VAR}` is expanded at runtime

3. **Timeout Validation**:
   - Must be positive integers
   - Maximum timeout: 600 seconds (10 minutes)

## 4. Transport Selection Logic

### 4.1 Selection Algorithm

```python
def select_transport(config: dict) -> str:
    """Determine transport type from configuration."""
    # Explicit transport field takes precedence
    if "transport" in config:
        return config["transport"]

    # Auto-detect based on fields (backward compatibility)
    if "url" in config:
        return "http"
    elif "command" in config:
        return "stdio"
    else:
        raise ValueError("Cannot determine transport type")
```

### 4.2 Execution Routing

```python
async def _exec_async(self, prep_res: dict) -> dict:
    transport = prep_res["config"].get("transport", "stdio")

    if transport == "http":
        return await self._exec_async_http(prep_res)
    elif transport == "stdio":
        return await self._exec_async_stdio(prep_res)
    else:
        raise ValueError(f"Unsupported transport: {transport}")
```

## 5. Authentication Mechanisms

### 5.1 Bearer Token
```http
Authorization: Bearer ${TOKEN}
```
- Most common for cloud APIs
- Token in environment variable
- No token refresh (MVP limitation)

### 5.2 API Key
```http
X-API-Key: ${KEY}
# or custom header
X-Custom-Auth: ${KEY}
```
- Header name configurable
- Key in environment variable

### 5.3 Basic Authentication
```http
Authorization: Basic <base64(username:password)>
```
- Username and password separate
- Base64 encoding handled internally

### 5.4 Custom Headers
- Additional headers for special requirements
- All values support `${VAR}` expansion

## 6. Session Management

### 6.1 Session ID Handling

**MVP Approach**: No session caching
- Server returns session ID in `Mcp-Session-Id` header
- Client includes in subsequent requests within same execution
- Session ID discarded after execution completes
- New session for each workflow execution

### 6.2 Session Lifecycle

1. **Initialization**: POST to `/mcp` with initialize method
2. **Session Assignment**: Server returns session ID
3. **Tool Execution**: Include session ID in requests
4. **Termination**: Session ends when context exits
5. **No Reuse**: Next execution gets new session

### 6.3 Future Enhancement (Post-MVP)
- Class-level session ID cache
- Session timeout tracking
- Session refresh on 404

## 7. Error Handling

### 7.1 HTTP Error Mapping

| HTTP Status | Error Type | User Message |
|-------------|------------|--------------|
| 400 | Bad Request | Invalid request format or parameters |
| 401 | Unauthorized | Authentication failed. Check credentials |
| 403 | Forbidden | Access denied. Check permissions |
| 404 | Not Found | Session expired or endpoint not found |
| 429 | Rate Limited | Too many requests. Please wait |
| 500-599 | Server Error | Server error. Please try again |
| Timeout | Timeout | Request timed out after X seconds |
| Connection | Network | Could not connect to server |

### 7.2 Error Response Format

```python
{
    "error": "<user-friendly message>",
    "error_details": {
        "server": "<server_name>",
        "tool": "<tool_name>",
        "status_code": 401,
        "exception_type": "HTTPStatusError"
    }
}
```

### 7.3 Retry Policy
- **No automatic retries** (max_retries=1)
- Connection errors: Fail immediately
- Auth errors: Fail immediately
- Server errors: Fail immediately
- User must retry workflow

## 8. Discovery Mechanism

### 8.1 Discovery over HTTP

```python
async def discover_tools(server_name: str, config: dict) -> list[dict]:
    """Discover tools from HTTP MCP server."""
    if config.get("transport") == "http":
        async with streamablehttp_client(url, headers) as (r, w, get_id):
            async with ClientSession(r, w) as session:
                await session.initialize()
                tools = await session.list_tools()
                return process_tools(tools)
```

### 8.2 Security Considerations
- Only HTTPS for remote discovery
- Validate server certificates
- Timeout for discovery operations
- No automatic discovery (user-initiated)

## 9. Security Requirements

### 9.1 Credential Handling
- **Never log credentials** (tokens, keys, passwords)
- **Mask in rerun display** (already implemented)
- **Environment variables only** (no hardcoding)
- **Runtime expansion** (not stored expanded)

### 9.2 Network Security
- **HTTPS enforcement** for production URLs
- **Certificate validation** (default httpx behavior)
- **No custom CA support** (MVP limitation)
- **Localhost exception** (HTTP allowed for 127.0.0.1)

### 9.3 Input Validation
- **URL sanitization** (prevent injection)
- **Header validation** (no newlines/CR)
- **Path validation** (already in MCPServerManager)
- **Command injection prevention** (existing protection)

## 10. Performance Requirements

### 10.1 Latency Targets
- **Local HTTP**: < 100ms overhead
- **Remote HTTP**: < 500ms overhead
- **Discovery**: < 5 seconds timeout
- **Tool execution**: < 30 seconds default timeout

### 10.2 Resource Usage
- **No connection pooling** (new connection per execution)
- **No session caching** (new session per execution)
- **Memory**: Same as stdio (no persistent state)
- **Network**: One connection per tool call

## 11. Testing Requirements

### 11.1 Unit Tests
- Configuration validation (all field combinations)
- Auth header building (all auth types)
- Error handling (all HTTP statuses)
- Transport selection logic
- Environment variable expansion

### 11.2 Integration Tests
- Mock HTTP server with aiohttp
- Full workflow execution over HTTP
- Discovery over HTTP
- Authentication scenarios
- Timeout handling

### 11.3 Manual Testing
- Kite public servers (no auth)
- Atlassian server (OAuth - if available)
- Local test server
- Network failure scenarios

## 12. CLI Interface

### 12.1 Command Structure

```bash
# Add HTTP server
pflow mcp add <name> --transport http --url <url> \
  --auth-type bearer --auth-token "${TOKEN}"

# Add stdio server (unchanged)
pflow mcp add <name> <command> [args...]

# Sync tools (works for both transports)
pflow mcp sync <name>

# List servers (shows transport type)
pflow mcp list
```

### 12.2 CLI Validation
- Require --url for HTTP transport
- Validate auth parameter combinations
- Clear error messages
- Help text for each transport

## 13. Migration Strategy

### 13.1 Backward Compatibility
- Existing stdio configs unchanged
- Default transport remains stdio
- Auto-detection for missing transport field
- No breaking changes to API

### 13.2 Migration Path
1. Add transport field to existing configs (automatic)
2. Validate all existing configs still work
3. Document migration process
4. Provide conversion utilities if needed

## 14. Implementation Phases

### Phase 1: Core Transport (MUST HAVE)
- Transport selection in MCPNode
- Basic HTTP execution
- Bearer token auth
- Error handling

### Phase 2: Configuration (MUST HAVE)
- Validation in MCPServerManager
- CLI support
- Environment variable expansion

### Phase 3: Discovery (SHOULD HAVE)
- HTTP discovery support
- Tool registration

### Phase 4: Testing (MUST HAVE)
- Unit tests
- Integration tests
- Documentation

### Phase 5: Enhancements (NICE TO HAVE)
- Additional auth types
- Session caching
- Performance optimization

## 15. Assumptions and Risks

### 15.1 Critical Assumptions - VERIFIED
1. **A1**: MCP SDK has working `streamablehttp_client` ✅ **VERIFIED** - Available in v1.13.1
2. **A2**: `asyncio.run()` pattern works with HTTP client ✅ **VERIFIED** - No event loop conflicts
3. **A3**: No connection pooling is acceptable for MVP ✅ **CONFIRMED** - Architectural constraint
4. **A4**: Session IDs can be ignored between executions ✅ **VERIFIED** - New session per execution
5. **A5**: Environment variable expansion is sufficient for auth ⚠️ **NEEDS FIX** - Requires nested dict support
6. **A6**: Single `/mcp` endpoint is standard ✅ **VERIFIED** - Per MCP spec
7. **A7**: HTTP discovery uses same protocol as execution ✅ **VERIFIED** - Transport-agnostic
8. **A8**: Error mapping covers common cases ✅ **VERIFIED** - httpx exceptions accessible
9. **A9**: No OAuth is acceptable for MVP ✅ **CONFIRMED** - Design decision
10. **A10**: Transport field doesn't break existing configs ✅ **VERIFIED** - Configs loaded permissively

### 15.2 Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| streamablehttp_client not available | ~~Low~~ **None** | ~~High~~ | **Verified available in v1.13.1** |
| Session management complexity | Medium | Medium | Start without caching |
| Auth mechanism insufficiency | Low | Medium | Add more types later |
| Network reliability issues | Medium | Low | Good timeout handling |
| Performance concerns | Low | Low | Document limitations |
| Env var expansion for nested auth | **High** | **Low** | Simple fix required |

## 16. Success Criteria

1. **Functional**: Execute MCP tools over HTTP successfully
2. **Compatible**: Existing stdio servers still work
3. **Secure**: No credential leaks, HTTPS enforced
4. **Performant**: < 500ms overhead for remote servers
5. **Tested**: > 80% code coverage, integration tests pass
6. **Documented**: Clear user documentation and examples

## 17. Verification Results

### 17.1 MCP SDK Verification
- **Version**: 1.13.1 (meets requirements)
- **streamablehttp_client**: ✅ Available with correct signature
- **Return Type**: `(read_stream, write_stream, get_session_id)` tuple confirmed
- **ClientSession Compatibility**: ✅ Streams are compatible
- **Auth Support**: ✅ `httpx.Auth` parameter available

### 17.2 asyncio.run() Compatibility
- **Event Loop**: ✅ No conflicts with multiple `asyncio.run()` calls
- **Sequential Execution**: ✅ Works as expected
- **Error Propagation**: ✅ Exceptions bubble up correctly

### 17.3 Configuration Compatibility
- **Config Loading**: ✅ Permissive, accepts new fields
- **Backward Compatibility**: ✅ Adding "transport" field is safe
- **Validation**: Current validation doesn't reject unknown fields

### 17.4 CLI Extensibility
- **Click Options**: ✅ Can be added without breaking existing commands
- **Command Structure**: Make `command` arg optional for HTTP transport
- **Option Precedence**: Click processes options before arguments

### 17.5 Required Fix: Environment Variable Expansion

**Issue Found**: `_expand_env_vars()` doesn't expand nested dictionaries

**Current Behavior**:
```python
# Input
{"auth": {"token": "${TOKEN}"}}
# Output
{"auth": {"token": "${TOKEN}"}}  # Not expanded!
```

**Required Fix**:
```python
def _build_auth_headers(self, config: dict) -> dict:
    # Expand auth section separately
    if "auth" in config:
        auth = self._expand_env_vars(config["auth"])
    # ... rest of implementation
```

## 18. Open Questions

1. Should we auto-detect transport from config structure? **Answer**: Yes, for backward compatibility
2. Should HTTP timeout be configurable per-execution? **Answer**: Yes, via config
3. Should we support proxy configuration? **Answer**: Not in MVP
4. Should we validate SSL certificates strictly? **Answer**: Yes, use httpx defaults
5. Should we support custom CA certificates? **Answer**: Not in MVP

---

## Appendix A: Example Configurations

### A.1 Composio Server
```json
{
  "composio": {
    "transport": "http",
    "url": "https://api.composio.dev/mcp",
    "auth": {
      "type": "bearer",
      "token": "${COMPOSIO_API_KEY}"
    }
  }
}
```

### A.2 Local HTTP Server
```json
{
  "local-http": {
    "transport": "http",
    "url": "http://localhost:3000/mcp",
    "timeout": 60
  }
}
```

### A.3 API Key Server
```json
{
  "api-server": {
    "transport": "http",
    "url": "https://api.example.com/mcp",
    "auth": {
      "type": "api_key",
      "key": "${API_KEY}",
      "header": "X-API-Key"
    },
    "headers": {
      "User-Agent": "pflow-mcp/1.0"
    }
  }
}
```

## Appendix B: Error Examples

### B.1 Authentication Error
```python
MCPError(
    title="Authentication failed",
    explanation="The MCP server rejected your credentials.",
    suggestions=[
        "Check that ${COMPOSIO_API_KEY} is set correctly",
        "Verify the token hasn't expired",
        "Run: echo $COMPOSIO_API_KEY | head -c 10"
    ],
    technical_details="HTTP 401 from https://api.composio.dev/mcp"
)
```

### B.2 Network Error
```python
MCPError(
    title="Cannot connect to MCP server",
    explanation="Unable to reach the HTTP MCP server.",
    suggestions=[
        "Check if the server is running",
        "Verify the URL is correct",
        "Check your network connection"
    ],
    technical_details="ConnectionError: http://localhost:3000/mcp"
)
```