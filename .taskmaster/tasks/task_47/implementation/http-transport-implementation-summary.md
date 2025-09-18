# Task 47: Streamable HTTP Transport Implementation Summary

## Executive Overview

Successfully implemented Streamable HTTP transport support for MCP (Model Context Protocol) servers in pflow, enabling communication with remote MCP servers over HTTP/HTTPS. This implementation follows the MCP 2025-03-26 specification for Streamable HTTP (not the deprecated HTTP+SSE), allowing pflow to connect to cloud-hosted services like Composio, API gateways, and remote MCP servers.

## What Was Implemented

### 1. Core Transport Layer

**File**: `src/pflow/nodes/mcp/node.py`

#### Transport Routing (lines 184-201)
- Added `_exec_async()` method that routes between transports based on config
- Renamed original `_exec_async` to `_exec_async_stdio`
- Added new `_exec_async_http` method for HTTP transport
- Maintains backward compatibility - stdio is still the default

#### HTTP Execution (lines 264-326)
```python
async def _exec_async_http(self, prep_res: dict) -> dict:
    """HTTP transport using mcp.client.streamable_http.streamablehttp_client"""
    # Key points:
    # - Uses SDK's streamablehttp_client (not custom implementation)
    # - Returns (read, write, get_session_id) tuple
    # - Session ID logged but not cached (MVP limitation)
    # - Same timeout pattern as stdio (Python 3.10/3.11 compatible)
```

#### Authentication System (lines 328-384)
- `_build_auth_headers()` supports three auth types:
  - Bearer tokens: `Authorization: Bearer <token>`
  - API keys: Custom header name (default: X-API-Key)
  - Basic auth: Base64 encoded username:password
- All auth credentials support `${ENV_VAR}` expansion

#### Critical Fix: Nested Environment Variable Expansion (lines 421-466)
- **Problem**: Original `_expand_env_vars()` only handled flat dictionaries
- **Solution**: Added `_expand_env_vars_nested()` that recursively processes nested structures
- **Why Critical**: Auth config is nested: `{"auth": {"token": "${TOKEN}"}}`
- This fix is used by both MCPNode and MCPDiscovery

#### Enhanced Error Handling (lines 482-514)
- Added HTTP-specific error detection before generic handling
- Maps httpx exceptions to user-friendly messages:
  - ConnectError → "Could not connect to MCP server"
  - HTTPStatusError → Status-specific messages (401, 403, 404, 429, 500+)
  - TimeoutException → "Request timed out"

### 2. Configuration Management

**File**: `src/pflow/mcp/manager.py`

#### Validation System (lines 267-388)
- Split validation into transport-specific methods:
  - `_validate_stdio_config()`: Validates command, args
  - `_validate_http_config()`: Validates URL, auth, headers, timeouts
  - `_validate_auth_config()`: Validates auth structure
- URL validation requires http:// or https:// prefix
- Warns about HTTP (non-HTTPS) for non-localhost URLs
- Timeout validation: positive numbers, max 600 seconds

#### Extended add_server Method (lines 135-228)
- Signature updated to support both transports
- HTTP-specific parameters: url, auth, headers, timeout, sse_timeout
- Maintains backward compatibility for stdio servers
- Atomic file operations preserved (security feature)

### 3. Tool Discovery

**File**: `src/pflow/mcp/discovery.py`

#### Transport Routing (lines 57-74)
- `_discover_async()` routes to transport-specific methods
- Original code moved to `_discover_async_stdio()`
- New `_discover_async_http()` method added

#### HTTP Discovery Implementation (lines 140-216)
- Uses same streamablehttp_client as execution
- Builds auth headers using shared method
- Returns identical tool structure as stdio discovery
- Tools are registered the same way regardless of transport

#### Shared Authentication Logic (lines 218-262)
- `_build_auth_headers()` duplicated from MCPNode
- Handles same three auth types
- Uses fixed nested env var expansion

### 4. CLI Interface

**File**: `src/pflow/cli/mcp.py`

#### Enhanced add Command (lines 28-160)
- Made `command` argument optional (required only for stdio)
- Added transport selection: `--transport stdio|http`
- HTTP-specific options:
  - `--url`: Server URL
  - `--auth-type`: bearer|api_key|basic
  - `--auth-token`: Token/key value
  - `--auth-header`: Header name for API key
  - `--username/--password`: Basic auth
  - `--header`: Custom headers (multiple allowed)
  - `--timeout/--sse-timeout`: Timeout configuration

#### Updated list Command (lines 179-204)
- Shows transport type for each server
- Displays transport-specific information:
  - HTTP: URL, auth type, headers, timeout
  - stdio: command and arguments

### 5. Testing

**File**: `tests/test_mcp/test_http_transport.py`

Comprehensive test coverage including:
- Configuration validation for all scenarios
- Auth header building for all auth types
- Transport routing verification
- Nested env var expansion
- HTTP error handling
- Discovery routing

**Test Utilities Created**:
- `test-mcp-http-server.py`: Minimal MCP HTTP server for testing
- `test-http-transport.sh`: Automated test script

## Architecture Decisions & Rationale

### 1. Universal Node Pattern Maintained
**Decision**: Keep MCPNode server-agnostic, no server-specific logic
**Rationale**: Ensures any future MCP server works without code changes
**Example**: We don't modify paths for filesystem vs GitHub - pass through unchanged

### 2. No Session Caching (MVP)
**Decision**: Create new session for each execution
**Rationale**:
- Matches stdio pattern (new subprocess each time)
- Avoids cache invalidation complexity
- asyncio.run() creates new event loop anyway
- Can optimize later without breaking changes

### 3. Transport as Configuration
**Decision**: Transport type stored in server config, not node type
**Rationale**: Same tools work over different transports
**Example**: `mcp-github-create_issue` works whether GitHub server is stdio or HTTP

### 4. Environment Variable Security
**Decision**: Store `${VAR}` patterns, expand at runtime
**Rationale**: Never store credentials in plain text
**Implementation**: Recursive expansion handles nested auth configs

### 5. Synchronous Node Interface
**Decision**: Keep using asyncio.run() bridge pattern
**Rationale**:
- PocketFlow nodes are synchronous
- Avoids massive refactoring
- AsyncNode support not ready in pflow

## Critical Code Patterns

### Pattern 1: Transport Routing
```python
if transport == "http":
    return await self._exec_async_http(prep_res)
elif transport == "stdio":
    return await self._exec_async_stdio(prep_res)
else:
    raise ValueError(f"Unsupported transport: {transport}")
```
This pattern is used in both MCPNode and MCPDiscovery.

### Pattern 2: Timeout Handling (Python 3.10/3.11 Compatible)
```python
timeout_context = getattr(asyncio, "timeout", None)
if timeout_context is not None:
    # Python 3.11+
    async with timeout_context(self._timeout):
        return await _run_session()
else:
    # Python 3.10 fallback
    return await asyncio.wait_for(_run_session(), timeout=self._timeout)
```

### Pattern 3: Auth Header Building
```python
# Expand env vars first (handles nested dicts)
auth = self._expand_env_vars(config.get("auth", {}))
# Then build headers based on auth type
if auth_type == "bearer":
    headers["Authorization"] = f"Bearer {auth.get('token')}"
```

## Integration Points

### 1. MCP SDK Integration
- Uses `mcp.client.streamable_http.streamablehttp_client`
- Same `ClientSession` interface as stdio
- No custom protocol implementation needed

### 2. Registry Integration
- Tools registered with `mcp-servername-toolname` pattern
- Same registry structure for HTTP and stdio tools
- Planner sees no difference between transports

### 3. Error Handling Integration
- Follows PocketFlow retry pattern (max_retries=1)
- Returns "default" action even on error (planner limitation)
- Stores errors in shared["error"] for downstream handling

## Current Limitations (MVP)

1. **No OAuth Support**: Only bearer tokens, API keys, basic auth
2. **No Connection Pooling**: New connection per execution
3. **No Session Caching**: Session IDs not reused
4. **No Token Refresh**: No automatic token renewal
5. **No Proxy Support**: Direct connections only
6. **No Client Certificates**: Only standard HTTPS
7. **SSE Not Fully Implemented**: POST-only communication works fine

## Testing & Verification

### Automated Testing
Run `./test-http-transport.sh` which:
1. Starts local MCP HTTP server
2. Configures HTTP transport
3. Discovers tools successfully
4. Executes test workflow
5. Verifies env var security
6. Tests error scenarios

### Manual Verification Points
- ✅ HTTP server appears in `pflow mcp list` with correct transport
- ✅ `pflow mcp sync` discovers tools from HTTP server
- ✅ Tools appear in registry as `mcp-servername-toolname`
- ✅ Workflows execute successfully with HTTP tools
- ✅ Environment variables not stored in plain text
- ✅ Authentication headers sent correctly

### Test Servers Used
- Local test server (created for testing)
- Kite public MCP servers (no auth)
- Composio (bearer token auth) - ready but needs API key

## Future Enhancement Opportunities

### Priority 1: Connection Pooling
```python
# Could add class-level connection cache
class MCPNode:
    _connections = {}  # server_url -> connection

    async def get_connection(self, url):
        if url not in self._connections:
            self._connections[url] = await create_connection(url)
        return self._connections[url]
```

### Priority 2: Session ID Caching
```python
# Could cache session IDs between executions
class MCPNode:
    _session_cache = {}  # server_url -> session_id

    def get_cached_session(self, url):
        return self._session_cache.get(url)
```

### Priority 3: OAuth Support
- Could integrate with OAuth libraries
- Or use gateway approach (mcp-gateway, context-forge)
- Or integrate Composio SDK for managed auth

### Priority 4: WebSocket Transport
- MCP considering WebSocket as future transport
- Would require new `_exec_async_websocket()` method
- Better for bidirectional streaming

## Common Pitfalls to Avoid

### Pitfall 1: Forgetting Nested Env Vars
**Wrong**:
```python
env_dict["auth"]["token"]  # Still has ${TOKEN}
```
**Right**:
```python
expanded = self._expand_env_vars_nested(env_dict)
expanded["auth"]["token"]  # Now has actual value
```

### Pitfall 2: Server-Specific Logic in Node
**Wrong**:
```python
if server == "filesystem":
    params["path"] = os.path.abspath(params["path"])
```
**Right**: Pass parameters unchanged, let server handle

### Pitfall 3: Trying to Cache with asyncio.run()
**Won't Work**: Each asyncio.run() creates new event loop
**Solution**: Need AsyncNode support or class-level caching

### Pitfall 4: Not Validating URL Format
**Wrong**: Accept any string as URL
**Right**: Require http:// or https:// prefix

## File Structure Summary

```
Modified Files:
├── src/pflow/nodes/mcp/node.py          # Core transport implementation
├── src/pflow/mcp/manager.py             # Config validation & management
├── src/pflow/mcp/discovery.py           # Tool discovery over HTTP
├── src/pflow/cli/mcp.py                 # CLI interface updates

New Files:
├── tests/test_mcp/test_http_transport.py    # Unit tests
├── docs/mcp-http-transport.md               # User documentation
├── test-mcp-http-server.py                  # Test server
└── test-http-transport.sh                   # Test script
```

## How to Continue Development

### To Add a New Auth Type:
1. Update `_validate_auth_config()` in manager.py
2. Add case in `_build_auth_headers()` in node.py
3. Add CLI options in mcp.py
4. Add tests in test_http_transport.py

### To Add Connection Pooling:
1. Create connection manager class
2. Store at class level (not instance)
3. Handle connection lifecycle
4. Consider timeout and cleanup

### To Add OAuth:
1. Option A: Integrate OAuth library
2. Option B: Use gateway pattern
3. Option C: Integrate Composio SDK
4. Update auth validation and CLI

### To Debug Issues:
1. Check `~/.pflow/mcp-servers.json` for config
2. Run with `--trace` flag for detailed logs
3. Check test server logs for requests
4. Verify environment variables are set
5. Test with curl to isolate issues

## Success Metrics

The implementation successfully:
- ✅ Enables HTTP transport alongside stdio
- ✅ Supports common authentication methods
- ✅ Maintains backward compatibility
- ✅ Provides clear error messages
- ✅ Secures credentials with env vars
- ✅ Works with real MCP servers
- ✅ Integrates cleanly with existing architecture

## Conclusion

The Streamable HTTP transport implementation is complete, tested, and production-ready for the MVP. It provides a solid foundation for connecting to remote MCP servers while maintaining the simplicity and security of the existing system. The architecture allows for future enhancements without breaking changes, and the implementation follows all established patterns in the pflow codebase.

The key achievement is that HTTP-based MCP tools work identically to stdio tools from the user's perspective - the transport complexity is completely hidden. This enables the Composio integration strategy while keeping the door open for other remote MCP services.