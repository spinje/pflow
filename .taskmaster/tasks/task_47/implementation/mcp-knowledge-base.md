# MCP (Model Context Protocol) Comprehensive Knowledge Base

## Table of Contents
1. [MCP Protocol Evolution](#mcp-protocol-evolution)
2. [Transport Mechanisms](#transport-mechanisms)
3. [Protocol Specification Details](#protocol-specification-details)
4. [Authentication Patterns](#authentication-patterns)
5. [Server Implementation Guide](#server-implementation-guide)
6. [Client Implementation Patterns](#client-implementation-patterns)
7. [Session Management](#session-management)
8. [Discovery Mechanism](#discovery-mechanism)
9. [Testing Strategies](#testing-strategies)
10. [Real-World Servers](#real-world-servers)
11. [Architecture Insights](#architecture-insights)
12. [Performance Characteristics](#performance-characteristics)
13. [Security Considerations](#security-considerations)
14. [Integration Strategies](#integration-strategies)
15. [Common Pitfalls and Solutions](#common-pitfalls-and-solutions)

---

## 1. MCP Protocol Evolution

### Historical Context
- **Original**: HTTP+SSE transport (now deprecated)
- **Current**: Streamable HTTP (since 2024-11-05 spec)
- **Future**: WebSocket transport under discussion

### Key Insight: Transport Evolution
The protocol moved from HTTP+SSE to Streamable HTTP to simplify implementation:
- **Old**: Separate endpoints for different operations
- **New**: Single `/mcp` endpoint handling POST, GET, DELETE
- **Benefit**: Simpler routing, better session management

### Protocol Versions
- **Current**: 2025-03-26 (though servers may report different versions)
- **Backwards Compatibility**: Clients should handle version negotiation
- **Version Exchange**: Happens during initialization handshake

## 2. Transport Mechanisms

### Stdio Transport
**Purpose**: Local process communication
**How it works**:
- Parent process spawns child with command
- Communication via stdin/stdout
- stderr for logging (can be suppressed)
- Process lifecycle = session lifecycle

**Key Learning**: Each execution spawns a new process, causing ~420ms overhead

### Streamable HTTP Transport
**Purpose**: Remote server communication
**Architecture**:
```
Client                          Server
  |                               |
  |--POST /mcp (initialize)------>|
  |<-----200 + Session ID---------|
  |                               |
  |--POST /mcp (tool/call)------->|
  |<-----200 + Result-------------|
  |                               |
  |--GET /mcp (SSE stream)-------->|
  |<-----Server-sent events--------|
  |                               |
  |--DELETE /mcp (terminate)------>|
  |<-----200--------------------- |
```

**Critical Discovery**: The `streamablehttp_client` in MCP SDK returns a tuple:
```python
(read_stream, write_stream, get_session_id_callback)
```
The third element is a callback function, not available in stdio.

### Transport Selection Pattern
```python
# Universal pattern discovered through research
if config.get("transport") == "http":
    return await self._exec_async_http(prep_res)
elif config.get("transport") == "stdio":
    return await self._exec_async_stdio(prep_res)
else:
    raise ValueError(f"Unsupported transport: {transport}")
```

## 3. Protocol Specification Details

### Required Headers (Streamable HTTP)

**Request Headers**:
- `Content-Type: application/json` (for POST)
- `Accept: application/json, text/event-stream`
- `Mcp-Session-Id: <session-id>` (after initialization)
- `Last-Event-ID: <event-id>` (for SSE resumption)

**Response Headers**:
- `Mcp-Session-Id: <session-id>` (server assigns)
- `Content-Type: application/json` or `text/event-stream`

### JSON-RPC Message Structure
```json
{
  "jsonrpc": "2.0",
  "id": 1,  // Request ID for correlation
  "method": "tools/call",
  "params": {
    "name": "tool_name",
    "arguments": {}
  }
}
```

### Method Types
- **initialize**: Protocol handshake
- **notifications/initialized**: Client confirms ready
- **tools/list**: Discover available tools
- **tools/call**: Execute a tool
- **resources/list**: List available resources (optional)
- **prompts/list**: List available prompts (optional)

### Error Response Format
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32601,  // JSON-RPC error code
    "message": "Method not found",
    "data": {}  // Optional additional data
  }
}
```

## 4. Authentication Patterns

### Bearer Token
**Most Common**: Modern APIs, OAuth 2.0
```http
Authorization: Bearer <token>
```

### API Key
**Simple**: Service-specific keys
```http
X-API-Key: <key>
# or custom header
X-Custom-Auth: <key>
```

### Basic Authentication
**Legacy**: Username/password
```http
Authorization: Basic <base64(username:password)>
```

### Environment Variable Pattern
**Critical Learning**: Always use `${VAR}` syntax in configs
```json
{
  "auth": {
    "type": "bearer",
    "token": "${API_TOKEN}"  // Expanded at runtime
  }
}
```

### Nested Environment Variable Expansion
**Problem Discovered**: Original code only handled flat dicts
**Solution**: Recursive expansion function
```python
def _expand_env_vars_nested(data):
    if isinstance(data, dict):
        return {k: _expand_env_vars_nested(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_expand_env_vars_nested(item) for item in data]
    elif isinstance(data, str):
        # Apply ${VAR} substitution
        return pattern.sub(replacer, data)
    return data
```

## 5. Server Implementation Guide

### Minimal MCP HTTP Server Structure
```python
class MCPServer:
    async def handle_mcp_post(self, request):
        data = await request.json()
        method = data.get('method')

        if method == 'initialize':
            session_id = str(uuid.uuid4())
            return {
                'jsonrpc': '2.0',
                'id': data['id'],
                'result': {
                    'protocolVersion': '2025-03-26',
                    'capabilities': {},
                    'serverInfo': {
                        'name': 'my-server',
                        'version': '1.0.0'
                    }
                }
            }, {'Mcp-Session-Id': session_id}

        elif method == 'tools/list':
            return {
                'jsonrpc': '2.0',
                'id': data['id'],
                'result': {
                    'tools': [
                        {
                            'name': 'tool_name',
                            'description': 'Tool description',
                            'inputSchema': {
                                'type': 'object',
                                'properties': {},
                                'required': []
                            }
                        }
                    ]
                }
            }
```

### Tool Response Formats

**Text Response**:
```json
{
  "content": [
    {
      "type": "text",
      "text": "Response text"
    }
  ]
}
```

**Error Response**:
```json
{
  "isError": true,
  "content": [
    {
      "type": "text",
      "text": "Error message"
    }
  ]
}
```

**Structured Response** (with outputSchema):
```json
{
  "structuredContent": {
    "field1": "value1",
    "field2": 123
  }
}
```

### Session Management
- Sessions identified by UUID
- Server assigns during initialization
- Client includes in all subsequent requests
- Server can terminate at any time (404 response)

## 6. Client Implementation Patterns

### SDK Usage Pattern (Python)
```python
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

async with streamablehttp_client(url, headers=headers) as (read, write, get_session_id):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("tool_name", args)
```

### Async-to-Sync Bridge Pattern
**Problem**: MCP SDK is async-only, but pflow nodes are synchronous
**Solution**: Use `asyncio.run()` for each execution
```python
def exec(self, prep_res):
    return asyncio.run(self._exec_async(prep_res))
```

**Important Limitation**: Each `asyncio.run()` creates new event loop, preventing connection reuse.

### Timeout Handling (Python 3.10/3.11 Compatible)
```python
timeout_context = getattr(asyncio, "timeout", None)
if timeout_context is not None:
    # Python 3.11+
    async with timeout_context(timeout_seconds):
        return await operation()
else:
    # Python 3.10
    return await asyncio.wait_for(operation(), timeout=timeout_seconds)
```

## 7. Session Management

### Session Lifecycle
1. **Creation**: Server assigns ID during initialization
2. **Usage**: Client includes ID in all requests
3. **Termination**: DELETE request or timeout
4. **No Caching (MVP)**: New session per workflow execution

### Session ID Characteristics
- Must contain only visible ASCII (0x21 to 0x7E)
- Should be cryptographically secure
- Examples: UUID, JWT, hash

### Why No Session Caching in MVP
**Architectural Constraint**: `asyncio.run()` creates new event loop
**Result**: Can't reuse async resources between executions
**Future**: Need AsyncNode support for proper pooling

## 8. Discovery Mechanism

### Tool Discovery Flow
1. Connect to server (stdio or HTTP)
2. Initialize session
3. Call `tools/list` method
4. Parse tool definitions
5. Register in pflow registry

### Tool Definition Structure
```json
{
  "name": "tool_name",
  "description": "What this tool does",
  "inputSchema": {
    "type": "object",
    "properties": {
      "param1": {
        "type": "string",
        "description": "Parameter description"
      }
    },
    "required": ["param1"]
  },
  "outputSchema": {  // Optional
    "type": "object",
    "properties": {}
  }
}
```

### Registry Pattern
Tools registered as `mcp-servername-toolname`:
- `mcp-github-create_issue`
- `mcp-composio-send_slack_message`
- `mcp-filesystem-read_file`

## 9. Testing Strategies

### Local Test Server Benefits
- No authentication complexity
- Full control over responses
- Easy to debug
- Can simulate errors

### Test Server Implementation Pattern
```python
# Key: Implement only what you need
async def handle_mcp_post(request):
    # 1. Parse JSON-RPC
    # 2. Route by method
    # 3. Return appropriate response
    # 4. Don't forget session ID header
```

### Testing Checklist
- [ ] Server appears in `pflow mcp list`
- [ ] Transport type shows correctly
- [ ] `pflow mcp sync` discovers tools
- [ ] Tools appear in registry
- [ ] Workflow execution succeeds
- [ ] Environment variables not in plaintext
- [ ] Error messages are clear

## 10. Real-World Servers

### Atlassian MCP Server
- **URL**: `https://mcp.atlassian.com/v1/sse`
- **Auth**: OAuth 2.1 with PKCE
- **Services**: Jira, Confluence, Compass
- **Status**: Production ready

### Kite Public Servers
- **URL**: `https://kite-mcp-inspector.fly.dev/mcp`
- **Auth**: None (public test servers)
- **Purpose**: Testing MCP clients
- **Tools**: Various test tools

### Community Servers
- **GitHub**: Various implementations
- **Slack**: korotovsky/slack-mcp-server
- **Custom**: Many domain-specific servers

### Composio (Managed Service)
- **URL**: Would be `https://backend.composio.dev/api/v2/mcp`
- **Auth**: Bearer token (API key)
- **Services**: 100+ integrated tools
- **Model**: Managed authentication

## 11. Architecture Insights

### Universal Node Pattern
**Principle**: Nodes should be server-agnostic
**Implementation**: No server-specific logic in MCPNode
**Benefit**: New servers work without code changes

### Virtual Registry Pattern
**Discovery**: Multiple registry entries can point to same class
**Implementation**: All MCP tools use `MCPNode` class
**Benefit**: No code generation needed

### Compiler Metadata Injection
**Pattern**: Compiler injects special parameters
```python
if node_type.startswith("mcp-"):
    params["__mcp_server__"] = server_name
    params["__mcp_tool__"] = tool_name
```

### Performance Measurements (Task 43)
- **Startup + Handshake**: ~420ms
- **Tool execution**: ~2.4ms
- **Shutdown**: ~6ms
- **Total overhead**: 99.4% is startup!

**Implication**: Connection pooling would provide 5-10x speedup

## 12. Performance Characteristics

### Stdio Transport
- New process per execution
- ~420ms startup overhead
- No connection reuse possible
- Memory: Process overhead

### HTTP Transport
- New connection per execution (MVP)
- Network latency added
- Could cache sessions (not implemented)
- Memory: Minimal

### Optimization Opportunities
1. **Connection Pooling**: Reuse HTTP connections
2. **Session Caching**: Reuse session IDs
3. **Batch Operations**: Multiple tools in one request
4. **AsyncNode**: Proper async support

## 13. Security Considerations

### Credential Management
- **Never hardcode**: Always use env vars
- **Runtime expansion**: Store `${VAR}`, expand when needed
- **No logging**: Mask credentials in logs
- **Secure storage**: Config files should have restricted permissions

### URL Validation
- **Require scheme**: Must start with http:// or https://
- **HTTPS enforcement**: Warn for non-localhost HTTP
- **No path traversal**: Validate server names
- **Origin validation**: Prevent DNS rebinding

### Authentication Security
- **Token rotation**: Support easy credential updates
- **Minimal scope**: Request only needed permissions
- **Timeout tokens**: Handle expiration gracefully

## 14. Integration Strategies

### Composio Integration Path
**Original Vision**: OAuth complexity handled by Composio
**Reality**: Can use API keys for MVP
**Future**: Full OAuth through Composio SDK

### Gateway Pattern (Alternative)
**Examples**: docker/mcp-gateway, IBM/mcp-context-forge
**Benefit**: Gateway handles auth complexity
**Tradeoff**: User runs local gateway

### Direct Integration
**Current**: What we implemented
**Benefit**: No external dependencies
**Limitation**: No OAuth support

## 15. Common Pitfalls and Solutions

### Pitfall 1: Flat Environment Variable Expansion
**Problem**: `{"auth": {"token": "${TOKEN}"}}` not expanded
**Solution**: Recursive expansion for nested structures

### Pitfall 2: Session Creation Overhead
**Problem**: New session per execution is slow
**Solution**: Accept for MVP, optimize later with AsyncNode

### Pitfall 3: Server-Specific Logic
**Problem**: Adding filesystem path resolution in node
**Solution**: Keep nodes universal, let servers handle

### Pitfall 4: Mixing Transports in Discovery
**Problem**: Trying to use stdio discovery for HTTP
**Solution**: Route discovery by transport type

### Pitfall 5: Not Handling ExceptionGroup
**Problem**: MCP SDK wraps errors in ExceptionGroup
**Solution**: Extract actual error with regex patterns

### Pitfall 6: Forgetting Session ID
**Problem**: Server rejects requests without session ID
**Solution**: Always include after initialization

### Pitfall 7: Wrong Header Names
**Problem**: Using wrong authentication header
**Solution**: Check server documentation

### Pitfall 8: Config Storage Security
**Problem**: Tokens in plaintext in config
**Solution**: Store as `${VAR}`, expand at runtime

## Key Insights That Shaped Implementation

### Insight 1: SDK Already Has HTTP Support
**Discovery**: `mcp.client.streamable_http` exists
**Impact**: No need to implement protocol from scratch
**Learning**: Always check SDK capabilities first

### Insight 2: Transport Agnostic Design Works
**Discovery**: Same `ClientSession` interface for all transports
**Impact**: Minimal code changes needed
**Learning**: Good abstractions enable easy extension

### Insight 3: Virtual Registry Pattern is Powerful
**Discovery**: Registry accepts arbitrary structures
**Impact**: No code generation for MCP tools
**Learning**: Flexible registries enable dynamic tools

### Insight 4: Nested Data Structures are Common
**Discovery**: Auth configs are nested
**Impact**: Need recursive env var expansion
**Learning**: Always handle nested structures

### Insight 5: Session Management Can Be Simple
**Discovery**: No caching still works fine
**Impact**: MVP doesn't need optimization
**Learning**: Start simple, optimize later

### Insight 6: Error Messages Matter
**Discovery**: Users see raw MCP errors
**Impact**: Need user-friendly translation
**Learning**: Always wrap technical errors

### Insight 7: Testing Locally First
**Discovery**: Real servers have auth complexity
**Impact**: Created local test server
**Learning**: Control your test environment

## Protocol Documentation References

### Official Resources
- **Specification**: https://modelcontextprotocol.io/docs/concepts/transports
- **GitHub**: https://github.com/modelcontextprotocol/modelcontextprotocol
- **Community**: https://github.com/topics/mcp-server

### Implementation Examples
- **Python SDK**: https://github.com/modelcontextprotocol/python-sdk
- **TypeScript SDK**: https://github.com/modelcontextprotocol/typescript-sdk
- **Server Examples**: Various community implementations

## Conclusion

The MCP protocol is well-designed for extensibility. The move from HTTP+SSE to Streamable HTTP simplified implementation while maintaining flexibility. The key to successful implementation is:

1. **Understand the protocol**: Single endpoint, session management
2. **Leverage the SDK**: Don't reinvent the wheel
3. **Keep it simple**: MVP doesn't need all optimizations
4. **Test locally first**: Control your environment
5. **Handle errors gracefully**: Users need clear messages
6. **Security first**: Never store credentials in plaintext

The architecture patterns discovered (universal nodes, virtual registry, metadata injection) are powerful and should be preserved in future development. The main opportunity for improvement is connection pooling, which requires architectural changes beyond the MVP scope.