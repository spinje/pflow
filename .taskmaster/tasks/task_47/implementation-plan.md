# Streamable HTTP Transport Implementation Plan

## Overview

This document provides a step-by-step implementation plan for adding Streamable HTTP transport support to pflow's MCP integration. The implementation leverages the existing `streamablehttp_client` in the MCP SDK and extends the current MCPNode architecture.

## Implementation Phases

### Phase 1: Core HTTP Transport (Day 1-2)

#### Step 1.1: Update MCPNode for Transport Selection

**File**: `src/pflow/nodes/mcp/node.py`

**Changes**:
1. Rename current `_exec_async` to `_exec_async_stdio`
2. Create new `_exec_async_http` method
3. Add transport routing in `_exec_async`

```python
async def _exec_async(self, prep_res: dict) -> dict:
    """Route to appropriate transport implementation."""
    config = prep_res["config"]
    transport = config.get("transport", "stdio")

    if transport == "http":
        return await self._exec_async_http(prep_res)
    else:
        return await self._exec_async_stdio(prep_res)

async def _exec_async_stdio(self, prep_res: dict) -> dict:
    """Current stdio implementation (renamed)."""
    # ... existing code ...

async def _exec_async_http(self, prep_res: dict) -> dict:
    """New HTTP transport implementation."""
    from mcp.client.streamable_http import streamablehttp_client

    config = prep_res["config"]
    url = config["url"]
    headers = self._build_auth_headers(config)
    timeout = config.get("timeout", 30)
    sse_timeout = config.get("sse_timeout", 300)

    async with streamablehttp_client(
        url=url,
        headers=headers,
        timeout=timeout,
        sse_read_timeout=sse_timeout
    ) as (read, write, get_session_id):
        async with ClientSession(read, write) as session:
            # Initialize handshake (same as stdio)
            await session.initialize()

            # Log session ID if available
            session_id = get_session_id()
            if session_id:
                logger.debug(f"HTTP session established: {session_id}")

            # Call tool (same as stdio)
            result = await session.call_tool(
                prep_res["tool"],
                prep_res["arguments"]
            )

            # Extract and return result (same as stdio)
            extracted_result = self._extract_result(result)
            return {"result": extracted_result}
```

#### Step 1.2: Implement Authentication Header Building

**File**: `src/pflow/nodes/mcp/node.py`

**New Method**:
```python
def _build_auth_headers(self, config: dict) -> dict:
    """Build authentication headers from config."""
    headers = {}

    # Add custom headers if provided
    if "headers" in config:
        expanded = self._expand_env_vars(config["headers"])
        headers.update(expanded)

    # Add authentication headers
    auth = config.get("auth", {})
    if not auth:
        return headers

    auth_type = auth.get("type")

    if auth_type == "bearer":
        token = auth.get("token", "")
        if token:
            # Expand environment variables in token
            expanded = self._expand_env_vars({"token": token})
            headers["Authorization"] = f"Bearer {expanded['token']}"

    elif auth_type == "api_key":
        key = auth.get("key", "")
        header_name = auth.get("header", "X-API-Key")
        if key:
            expanded = self._expand_env_vars({"key": key})
            headers[header_name] = expanded["key"]

    elif auth_type == "basic":
        username = auth.get("username", "")
        password = auth.get("password", "")
        if username and password:
            import base64
            expanded_user = self._expand_env_vars({"u": username})["u"]
            expanded_pass = self._expand_env_vars({"p": password})["p"]
            credentials = base64.b64encode(
                f"{expanded_user}:{expanded_pass}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {credentials}"

    return headers
```

#### Step 1.3: Update Error Handling

**File**: `src/pflow/nodes/mcp/node.py`

**Update `exec_fallback`**:
```python
def exec_fallback(self, prep_res: dict, exc: Exception) -> dict:
    """Enhanced error handling for HTTP errors."""
    actual_error = str(exc)
    exc_str = str(exc)

    # Handle HTTP-specific errors
    if "httpx" in str(type(exc).__module__):
        import httpx
        if isinstance(exc, httpx.ConnectError):
            actual_error = f"Could not connect to MCP server at {prep_res['config'].get('url', 'unknown')}. Check if the server is running and accessible."
        elif isinstance(exc, httpx.TimeoutException):
            actual_error = f"HTTP request timed out after {self._timeout} seconds"
        elif isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status == 401:
                actual_error = "Authentication failed. Check your API credentials."
            elif status == 403:
                actual_error = "Access forbidden. Check your permissions."
            elif status == 404:
                actual_error = "Session expired or endpoint not found."
            elif status == 429:
                actual_error = "Rate limited. Too many requests."
            else:
                actual_error = f"HTTP error {status}: {exc.response.text[:200]}"

    # ... existing error handling ...

    return {"error": actual_error, "exception_type": type(exc).__name__}
```

### Phase 2: Configuration Management (Day 2)

#### Step 2.1: Update MCPServerManager Validation

**File**: `src/pflow/mcp/manager.py`

**Changes**:
1. Remove hardcoded stdio-only restriction
2. Add HTTP-specific validation
3. Update `add_server` method signature

```python
def validate_server_config(self, config: dict[str, Any]) -> None:
    """Validate server configuration for both stdio and HTTP."""
    if "transport" not in config:
        raise ValueError("Missing required field: transport")

    transport = config["transport"]

    if transport == "stdio":
        self._validate_stdio_config(config)
    elif transport == "http":
        self._validate_http_config(config)
    else:
        raise ValueError(
            f"Unsupported transport: {transport}. "
            f"Supported: 'stdio', 'http'"
        )

def _validate_stdio_config(self, config: dict[str, Any]) -> None:
    """Validate stdio transport configuration."""
    if "command" not in config:
        raise ValueError("stdio transport requires 'command' field")
    if not config["command"]:
        raise ValueError("Command cannot be empty")
    # ... existing validation ...

def _validate_http_config(self, config: dict[str, Any]) -> None:
    """Validate HTTP transport configuration."""
    if "url" not in config:
        raise ValueError("HTTP transport requires 'url' field")

    url = config["url"]
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")

    # Validate URL format
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("URL must start with http:// or https://")

    # Validate optional auth
    if "auth" in config:
        self._validate_auth_config(config["auth"])

    # Validate optional headers
    if "headers" in config and not isinstance(config["headers"], dict):
        raise ValueError("Headers must be a dictionary")

def _validate_auth_config(self, auth: dict[str, Any]) -> None:
    """Validate authentication configuration."""
    if not isinstance(auth, dict):
        raise ValueError("Auth config must be a dictionary")

    if "type" not in auth:
        raise ValueError("Auth config must specify 'type'")

    auth_type = auth["type"]

    if auth_type == "bearer":
        if "token" not in auth:
            raise ValueError("Bearer auth requires 'token' field")
    elif auth_type == "api_key":
        if "key" not in auth:
            raise ValueError("API key auth requires 'key' field")
    elif auth_type == "basic":
        if "username" not in auth or "password" not in auth:
            raise ValueError("Basic auth requires 'username' and 'password'")
    else:
        raise ValueError(
            f"Unsupported auth type: {auth_type}. "
            f"Supported: 'bearer', 'api_key', 'basic'"
        )
```

#### Step 2.2: Update add_server Method

**File**: `src/pflow/mcp/manager.py`

```python
def add_server(
    self,
    name: str,
    transport: str = "stdio",
    command: Optional[str] = None,
    args: Optional[list[str]] = None,
    env: Optional[dict[str, str]] = None,
    url: Optional[str] = None,
    auth: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    timeout: Optional[int] = None,
) -> None:
    """Add or update an MCP server configuration."""
    # Validate server name
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"Invalid server name: {name}")

    config = self.load()
    now = datetime.now(timezone.utc).isoformat()
    is_update = name in config["servers"]

    # Build configuration based on transport
    if transport == "stdio":
        if not command:
            raise ValueError("Command is required for stdio transport")

        server_config = {
            "transport": transport,
            "command": command,
            "args": args or [],
            "env": env or {},
            "updated_at": now,
        }

    elif transport == "http":
        if not url:
            raise ValueError("URL is required for HTTP transport")

        server_config = {
            "transport": transport,
            "url": url,
            "updated_at": now,
        }

        # Add optional fields if provided
        if auth:
            server_config["auth"] = auth
        if headers:
            server_config["headers"] = headers
        if timeout:
            server_config["timeout"] = timeout
        if env:
            server_config["env"] = env  # Some HTTP servers may need env vars

    else:
        raise ValueError(f"Unsupported transport: {transport}")

    # Preserve created_at for updates
    if not is_update:
        server_config["created_at"] = now
    elif "created_at" in config["servers"][name]:
        server_config["created_at"] = config["servers"][name]["created_at"]
    else:
        server_config["created_at"] = now

    # Validate the complete configuration
    self.validate_server_config(server_config)

    config["servers"][name] = server_config
    self.save(config)

    action = "Updated" if is_update else "Added"
    logger.info(f"{action} MCP server '{name}' with {transport} transport")
```

### Phase 3: Discovery Support (Day 3)

#### Step 3.1: Update MCPDiscovery for HTTP

**File**: `src/pflow/mcp/discovery.py`

```python
async def _discover_async(self, server_name: str, server_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Enhanced discovery supporting both transports."""
    transport = server_config.get("transport", "stdio")

    if transport == "http":
        return await self._discover_async_http(server_name, server_config)
    else:
        return await self._discover_async_stdio(server_name, server_config)

async def _discover_async_stdio(self, server_name: str, server_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Current stdio discovery (renamed)."""
    # ... existing code ...

async def _discover_async_http(self, server_name: str, server_config: dict[str, Any]) -> list[dict[str, Any]]:
    """HTTP transport discovery."""
    from mcp.client.streamable_http import streamablehttp_client

    url = server_config["url"]

    # Build auth headers (reuse logic from MCPNode)
    headers = self._build_auth_headers(server_config)

    logger.info(f"Connecting to HTTP MCP server '{server_name}' at {url}...")

    tools_list = []

    try:
        async with streamablehttp_client(url, headers=headers) as (read, write, get_session_id):
            async with ClientSession(read, write) as session:
                # Initialize handshake
                await session.initialize()

                session_id = get_session_id()
                logger.debug(f"HTTP session for discovery: {session_id}")

                # List available tools (same as stdio)
                tools_response = await session.list_tools()

                # Process tools (same as stdio)
                for tool in tools_response.tools:
                    # ... same tool processing logic ...
                    tools_list.append(tool_def)

                logger.info(f"Discovered {len(tools_list)} tools from {server_name}")

    except Exception:
        logger.exception(f"Error during HTTP discovery for {server_name}")
        raise

    return tools_list
```

### Phase 4: CLI Updates (Day 3)

#### Step 4.1: Update MCP CLI Commands

**File**: `src/pflow/cli/mcp.py`

**Update `add` command**:
```python
@click.command()
@click.argument("name")
@click.argument("command", required=False)
@click.option("--transport", default="stdio", type=click.Choice(["stdio", "http"]))
@click.option("--url", help="Server URL for HTTP transport")
@click.option("--auth-type", type=click.Choice(["bearer", "api_key", "basic"]))
@click.option("--auth-token", help="Authentication token/key")
@click.option("--auth-header", default="X-API-Key", help="Header name for API key")
@click.option("--username", help="Username for basic auth")
@click.option("--password", help="Password for basic auth")
@click.option("--env", multiple=True, help="Environment variables as KEY=VALUE")
@click.option("--header", multiple=True, help="HTTP headers as KEY=VALUE")
def add(name, command, transport, url, auth_type, auth_token, auth_header,
        username, password, env, header):
    """Add or update an MCP server configuration."""

    manager = MCPServerManager()

    # Parse environment variables
    env_dict = {}
    for env_var in env:
        if "=" in env_var:
            key, value = env_var.split("=", 1)
            env_dict[key] = value

    # Parse headers
    header_dict = {}
    for h in header:
        if "=" in h:
            key, value = h.split("=", 1)
            header_dict[key] = value

    # Build auth config
    auth_config = None
    if auth_type:
        if auth_type == "bearer":
            auth_config = {"type": "bearer", "token": auth_token}
        elif auth_type == "api_key":
            auth_config = {
                "type": "api_key",
                "key": auth_token,
                "header": auth_header
            }
        elif auth_type == "basic":
            auth_config = {
                "type": "basic",
                "username": username,
                "password": password
            }

    # Add server based on transport
    if transport == "http":
        if not url:
            click.echo("Error: --url is required for HTTP transport", err=True)
            sys.exit(1)

        manager.add_server(
            name=name,
            transport="http",
            url=url,
            auth=auth_config,
            headers=header_dict if header_dict else None,
            env=env_dict if env_dict else None,
        )

        click.echo(f"Added HTTP MCP server '{name}' at {url}")

    else:  # stdio
        if not command:
            click.echo("Error: COMMAND is required for stdio transport", err=True)
            sys.exit(1)

        # Parse command string for stdio
        cmd, args = manager.parse_command_string(command)

        manager.add_server(
            name=name,
            transport="stdio",
            command=cmd,
            args=args,
            env=env_dict if env_dict else None,
        )

        click.echo(f"Added stdio MCP server '{name}' with command: {command}")
```

### Phase 5: Testing (Day 4)

#### Step 5.1: Unit Tests

**File**: `tests/test_mcp/test_http_transport.py`

```python
import pytest
from unittest.mock import patch, AsyncMock
from pflow.nodes.mcp.node import MCPNode
from pflow.mcp.manager import MCPServerManager

def test_http_config_validation():
    """Test HTTP transport configuration validation."""
    manager = MCPServerManager()

    # Valid HTTP config
    config = {
        "transport": "http",
        "url": "https://api.example.com/mcp",
        "auth": {"type": "bearer", "token": "${API_TOKEN}"}
    }
    manager.validate_server_config(config)  # Should not raise

    # Missing URL
    with pytest.raises(ValueError, match="requires 'url'"):
        manager.validate_server_config({"transport": "http"})

    # Invalid URL
    with pytest.raises(ValueError, match="must start with http"):
        manager.validate_server_config({
            "transport": "http",
            "url": "ftp://example.com"
        })

@pytest.mark.asyncio
async def test_http_transport_execution():
    """Test MCPNode execution with HTTP transport."""
    node = MCPNode()

    # Mock streamablehttp_client
    mock_client = AsyncMock()
    mock_session = AsyncMock()

    with patch("pflow.nodes.mcp.node.streamablehttp_client", mock_client):
        # ... test implementation ...
```

#### Step 5.2: Integration Tests

**File**: `tests/test_mcp/test_http_integration.py`

```python
import pytest
from aiohttp import web
import asyncio

@pytest.fixture
async def mock_mcp_server():
    """Create a mock MCP HTTP server for testing."""

    async def handle_mcp(request):
        """Handle MCP requests."""
        data = await request.json()

        if data.get("method") == "initialize":
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": data["id"],
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "serverInfo": {"name": "test-server"}
                    }
                },
                headers={"Mcp-Session-Id": "test-session-123"}
            )

        # ... handle other methods ...

    app = web.Application()
    app.router.add_post("/mcp", handle_mcp)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", 0)
    await site.start()

    port = site._server.sockets[0].getsockname()[1]
    yield f"http://localhost:{port}/mcp"

    await runner.cleanup()

def test_full_http_flow(mock_mcp_server):
    """Test complete HTTP MCP flow."""
    # ... test with real HTTP server ...
```

### Phase 6: Documentation (Day 4)

#### Step 6.1: User Documentation

**File**: `docs/mcp-http-transport.md`

- Configuration examples
- Authentication patterns
- Troubleshooting guide
- Migration from stdio

#### Step 6.2: Examples

**File**: `examples/mcp-http/`

- Basic HTTP connection
- Authentication examples
- Error handling patterns

## Testing Plan

### Local Testing
1. Unit tests with mocked HTTP client
2. Integration tests with mock HTTP server
3. Test all authentication types
4. Error scenario testing

### Real Server Testing
1. Test against Kite public servers (no auth)
2. Test against Atlassian server (OAuth)
3. Test against community servers (API keys)
4. Performance comparison with stdio

## Rollout Strategy

### MVP Release (Week 1)
- Core HTTP transport
- Basic authentication (Bearer, API key)
- Essential error handling
- Minimal documentation

### Enhancement Release (Week 2)
- Session caching (if needed)
- Additional auth methods
- Performance optimizations
- Comprehensive documentation

## Success Metrics

1. **Functional**: HTTP servers work identically to stdio
2. **Performance**: < 500ms overhead for remote servers
3. **Security**: No credential leaks in logs
4. **Compatibility**: Works with 3+ real MCP servers
5. **Test Coverage**: > 80% code coverage

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Session management complexity | High | Start without caching |
| Authentication variety | Medium | Support common patterns first |
| Network reliability | Medium | Robust timeout handling |
| Security vulnerabilities | High | HTTPS enforcement, credential masking |

This implementation plan provides a clear, step-by-step approach to adding Streamable HTTP transport support to pflow's MCP integration, with realistic timelines and comprehensive testing.