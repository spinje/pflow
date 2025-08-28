# MCP HTTP Transport Implementation Guide

## Executive Summary

This document provides comprehensive guidance for implementing HTTP transport support in pflow's MCP integration. The current implementation only supports stdio transport, creating a new subprocess for each execution. HTTP transport (specifically "Streamable HTTP") would enable persistent connections, better performance, and remote server support.

## Current State Analysis

### What We Have (stdio)

```python
# Current implementation in MCPNode._exec_async()
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(
    command=config["command"],
    args=config.get("args", []),
    env=env if env else None
)

async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool(prep_res["tool"], prep_res["arguments"])
```

### Critical Limitations

1. **New Process Per Execution**: Each `MCPNode.exec()` calls `asyncio.run()` which creates a new event loop and subprocess
2. **No Connection Pooling**: Every tool call spawns a fresh MCP server process
3. **max_retries=1 Workaround**: Set to prevent multiple server processes (see line 69 TODO in MCPNode)
4. **Resource Inefficiency**: Process startup/teardown overhead for each operation

## MCP Transport Evolution

### Timeline
- **2024-11-05**: Original HTTP+SSE transport (now deprecated)
- **2025-03-26**: Streamable HTTP transport (current standard)
- **Future**: WebSocket transport (SEP-1287, not yet standard)

### Why Streamable HTTP Replaced HTTP+SSE

1. **Single Endpoint**: All interactions through one `/mcp` endpoint instead of separate SSE and POST endpoints
2. **Serverless Compatible**: Can scale to zero (unlike persistent SSE connections)
3. **Bidirectional**: Server can send notifications back on same connection
4. **Simpler Implementation**: Reduced complexity for both client and server

## Streamable HTTP Transport Specification

### Core Architecture

```
Client                          Server
  |                               |
  |--POST /mcp (Initialize)------>|
  |<--200 OK (with session ID)----|
  |                               |
  |--POST /mcp (Tool Call)-------->|
  |  Headers:                      |
  |  - Mcp-Session-Id: xxx        |
  |  - Accept: application/json,   |
  |            text/event-stream   |
  |                               |
  |<--200 OK (SSE stream)---------|
  |  - JSON-RPC response          |
  |  - Additional notifications    |
  |  - Stream closes               |
```

### Required Headers

```python
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "Mcp-Protocol-Version": "2025-03-26",
    "Mcp-Session-Id": session_id,  # After initialization
}
```

### Session Management

```python
# Server returns session ID during initialization
response_headers = {
    "Mcp-Session-Id": "550e8400-e29b-41d4-a716-446655440000"
}

# Client must include in all subsequent requests
request_headers = {
    "Mcp-Session-Id": "550e8400-e29b-41d4-a716-446655440000"
}
```

## Implementation Strategy for pflow

### Phase 1: Synchronous HTTP Client (MVP Compatible)

Since pflow MVP is synchronous-only, we need to maintain the sync interface:

```python
class MCPNode(Node):
    def __init__(self):
        super().__init__(max_retries=1, wait=0)
        self._http_sessions = {}  # Server -> session cache

    def exec(self, prep_res: dict) -> dict:
        """Execute MCP tool with transport selection."""
        config = prep_res["config"]
        transport = config.get("transport", "stdio")

        if transport == "stdio":
            # Current implementation
            return asyncio.run(self._exec_async_stdio(prep_res))
        elif transport == "http":
            # New HTTP implementation
            return asyncio.run(self._exec_async_http(prep_res))
        else:
            raise ValueError(f"Unsupported transport: {transport}")

    async def _exec_async_http(self, prep_res: dict) -> dict:
        """Execute via Streamable HTTP transport."""
        config = prep_res["config"]
        server_url = config["url"]

        # Get or create session
        session = await self._get_or_create_http_session(server_url, config)

        # Call tool
        result = await session.call_tool(
            prep_res["tool"],
            prep_res["arguments"]
        )

        # Keep session alive for reuse
        return {"result": self._extract_result(result)}
```

### Phase 2: AsyncNode Implementation (Post-MVP)

When pflow enables async support, migrate to AsyncNode:

```python
class MCPAsyncNode(AsyncNode):
    """Future async version with proper connection pooling."""
    _connection_pool = {}

    async def exec_async(self, shared, **params):
        config = self._load_server_config(params["__mcp_server__"])

        # Reuse existing connection
        conn = await self._get_or_create_connection(config)

        # Connection stays alive across executions
        result = await conn.call_tool(
            params["__mcp_tool__"],
            {k: v for k, v in params.items() if not k.startswith("__")}
        )

        return {"result": result}
```

## Configuration Changes

### Current stdio Configuration

```json
{
  "servers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
      "transport": "stdio"
    }
  }
}
```

### Future HTTP Configuration

```json
{
  "servers": {
    "github-remote": {
      "url": "https://mcp.github.com",
      "transport": "http",
      "auth": {
        "type": "bearer",
        "token": "${GITHUB_TOKEN}"
      },
      "session": {
        "timeout": 3600,
        "keepalive": true
      }
    }
  }
}
```

## Critical Implementation Details

### 1. Session Caching Strategy

```python
class SessionManager:
    """Manage HTTP sessions across executions."""

    def __init__(self):
        self._sessions = {}  # server_url -> (session, created_at)
        self._lock = asyncio.Lock()

    async def get_session(self, server_url: str, config: dict):
        async with self._lock:
            if server_url in self._sessions:
                session, created_at = self._sessions[server_url]
                # Check if session is still valid
                if time.time() - created_at < 3600:  # 1 hour timeout
                    return session

            # Create new session
            session = await self._create_session(server_url, config)
            self._sessions[server_url] = (session, time.time())
            return session
```

### 2. SSE Response Handling

```python
async def handle_sse_response(response):
    """Process Server-Sent Events stream."""
    results = []

    async for line in response.aiter_lines():
        if line.startswith("data: "):
            data = json.loads(line[6:])
            if data.get("jsonrpc") == "2.0":
                results.append(data)
        elif line == "":
            # End of event
            pass

    return results
```

### 3. Backwards Compatibility Detection

```python
async def detect_transport(server_url: str) -> str:
    """Auto-detect server transport type."""
    try:
        # Try Streamable HTTP first
        response = await http_client.post(
            f"{server_url}/mcp",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
            headers={"Accept": "application/json, text/event-stream"}
        )
        if response.status == 200:
            return "streamable_http"
    except:
        pass

    try:
        # Try legacy SSE
        response = await http_client.get(
            server_url,
            headers={"Accept": "text/event-stream"}
        )
        if response.status == 200:
            return "legacy_sse"
    except:
        pass

    raise ValueError(f"Cannot detect transport for {server_url}")
```

## Security Considerations

### 1. Origin Validation
```python
def validate_origin(request_headers):
    origin = request_headers.get("Origin")
    allowed_origins = config.get("allowed_origins", ["http://localhost"])
    if origin not in allowed_origins:
        raise SecurityError(f"Origin {origin} not allowed")
```

### 2. Local Binding
```python
# For local servers, bind to localhost only
server_config = {
    "host": "127.0.0.1",  # Not 0.0.0.0
    "port": 8080
}
```

### 3. Authentication
```python
def add_auth_headers(headers, auth_config):
    auth_type = auth_config.get("type")
    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {auth_config['token']}"
    elif auth_type == "api_key":
        headers[auth_config["header"]] = auth_config["key"]
    return headers
```

## Testing Strategy

### 1. Mock HTTP Server for Tests
```python
class MockMCPHTTPServer:
    """Mock server for testing HTTP transport."""

    async def handle_request(self, request):
        if request.path == "/mcp":
            body = await request.json()

            if body["method"] == "initialize":
                return web.Response(
                    json={"result": {"protocolVersion": "2025-03-26"}},
                    headers={"Mcp-Session-Id": "test-session"}
                )
            elif body["method"] == "tools/call":
                # Return SSE stream
                return web.StreamResponse(
                    headers={"Content-Type": "text/event-stream"}
                )
```

### 2. Integration Tests
```python
def test_http_transport_session_reuse():
    """Test that HTTP sessions are reused across executions."""
    # First execution creates session
    node1 = MCPNode()
    result1 = node1.exec({"config": {"url": "http://localhost:8080", "transport": "http"}})

    # Second execution reuses session
    node2 = MCPNode()
    result2 = node2.exec({"config": {"url": "http://localhost:8080", "transport": "http"}})

    # Verify same session ID used
    assert mock_server.request_count == 1  # Only one initialization
```

## Migration Path

### Step 1: Add HTTP Client Support (Keep stdio)
- Implement basic HTTP client in MCPNode
- Add transport detection logic
- Update config schema validation

### Step 2: Add Session Management
- Implement session caching
- Add session timeout handling
- Handle session termination gracefully

### Step 3: Optimize for Performance
- Connection pooling with aiohttp
- Request batching support
- Implement retry logic with exponential backoff

### Step 4: Migrate to AsyncNode (Post-MVP)
- Convert MCPNode to MCPAsyncNode
- Implement proper connection pooling
- Remove asyncio.run() wrapper

## Open Questions and Decisions

### 1. Session Lifetime Management
- **Option A**: Create new session per workflow execution
- **Option B**: Maintain sessions across workflow executions
- **Recommendation**: Option B with configurable timeout

### 2. Error Handling
- How to handle session expiration mid-workflow?
- Should we auto-retry with new session?
- **Recommendation**: Auto-retry once with new session

### 3. Configuration Migration
- How to handle existing stdio configs?
- Auto-detect transport from config structure?
- **Recommendation**: Explicit transport field required

## Appendix: MCP SDK HTTP Client Example

```python
# Expected MCP SDK interface (hypothetical)
from mcp.client.http import http_client

async with http_client(
    url="https://mcp.example.com",
    headers={"Authorization": "Bearer token"}
) as client:
    async with ClientSession(client) as session:
        await session.initialize()
        result = await session.call_tool("create-issue", {
            "title": "Test Issue",
            "body": "Issue body"
        })
```

## References

1. [MCP Specification - Transports](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)
2. [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
3. [SEP-1287: WebSocket Transport Proposal](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1288)
4. [Cloudflare Blog: Streamable HTTP Transport](https://blog.cloudflare.com/streamable-http-mcp-servers-python/)
5. [Why MCP Deprecated SSE](https://blog.fka.dev/blog/2025-06-06-why-mcp-deprecated-sse-and-go-with-streamable-http/)

## Implementation Checklist

- [ ] Update MCPServerManager to support URL-based configs
- [ ] Add transport field validation
- [ ] Implement HTTP client in MCPNode
- [ ] Add session management
- [ ] Update config schema
- [ ] Write tests for HTTP transport
- [ ] Add backwards compatibility detection
- [ ] Update documentation
- [ ] Migration guide for users