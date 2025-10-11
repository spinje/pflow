# FastMCP Server Basics

This document contains the core patterns and implementation details for building a FastMCP server, extracted from the official FastMCP documentation.

## Server Initialization

### Basic Import and Setup

```python
from fastmcp import FastMCP

# Simple initialization
mcp = FastMCP("My MCP Server")

# With additional configuration
mcp = FastMCP(
    name="MyAssistantServer",
    instructions="Provides data analysis tools",
    include_tags={"public"}
)
```

### Initialization Parameters

The `FastMCP` class accepts the following key parameters:

1. **`name`**: Human-readable server name (default: "FastMCP")
2. **`instructions`**: Optional description of server functionality
3. **`auth`**: Authentication provider
4. **`tools`**: List of tools/functions to add to server
5. **`include_tags`/`exclude_tags`**: Component filtering mechanism
6. **`on_duplicate_*`**: Handling strategy for duplicate components

### Component Types

FastMCP servers can expose three types of components:

- **Tools**: Callable functions for performing actions
- **Resources**: Data sources clients can read
- **Resource Templates**: Parameterized resources
- **Prompts**: Reusable message templates for language models

## Basic Server Structure

### Tool Registration Pattern

```python
from fastmcp import FastMCP

mcp = FastMCP("My MCP Server")

@mcp.tool
def greet(name: str) -> str:
    """Greet a user by name."""
    return f"Hello, {name}!"

@mcp.tool
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b
```

### Complete Server Example

```python
from fastmcp import FastMCP

mcp = FastMCP(
    name="MyAssistantServer",
    instructions="Provides data analysis tools",
    include_tags={"public"}
)

@mcp.tool
def hello(name: str) -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"

if __name__ == "__main__":
    mcp.run()
```

## Running with stdio

### Method 1: Direct Run (Recommended for Scripts)

```python
from fastmcp import FastMCP

mcp = FastMCP(name="MyServer")

@mcp.tool
def hello(name: str) -> str:
    return f"Hello, {name}!"

if __name__ == "__main__":
    mcp.run()  # Default STDIO transport
```

### Method 2: CLI Execution

```bash
# Basic run with stdio (default)
fastmcp run server.py

# Advanced options
fastmcp run server.py --python 3.11 \
    --with pandas \
    --transport stdio
```

### Async Context

```python
async def main():
    await mcp.run_async()  # Uses stdio by default

# In async context
import asyncio
asyncio.run(main())
```

## Transport Options

### STDIO (Default)

Best for:
- Local development
- Command-line tools
- Desktop applications
- Integration with Claude Desktop/other MCP clients

```python
mcp.run()  # Default is stdio
# OR explicitly
mcp.run(transport="stdio")
```

### HTTP Transport

Best for:
- Network-accessible services
- Multiple client support
- Production deployments

```python
# HTTP with custom host/port
mcp.run(transport="http", host="127.0.0.1", port=8000)

# Async version
async def main():
    await mcp.run_async(transport="http", port=8000)
```

### SSE Transport

**Not recommended for new projects** (legacy transport)

## Key Patterns

### 1. Standalone Script Pattern

```python
from fastmcp import FastMCP

mcp = FastMCP("MyServer")

@mcp.tool
def my_tool(arg: str) -> str:
    return f"Processed: {arg}"

if __name__ == "__main__":
    mcp.run()  # stdio transport
```

**Usage**: Run directly with `python server.py` or `fastmcp run server.py`

### 2. CLI-Driven Pattern

```python
from fastmcp import FastMCP

mcp = FastMCP("MyServer")

@mcp.tool
def my_tool(arg: str) -> str:
    return f"Processed: {arg}"

# No __main__ block needed
```

**Usage**: Must use `fastmcp run server.py`

### 3. Type Hints Are Important

FastMCP uses type hints to:
- Generate proper tool schemas
- Validate arguments
- Provide IDE support

```python
@mcp.tool
def calculate(x: int, y: int, operation: str = "add") -> int:
    """Calculate using two numbers."""
    if operation == "add":
        return x + y
    elif operation == "multiply":
        return x * y
    return 0
```

### 4. Tag-Based Filtering

```python
mcp = FastMCP(
    name="FilteredServer",
    include_tags={"public"},  # Only include public tools
    exclude_tags={"internal"}  # Exclude internal tools
)

@mcp.tool(tags={"public"})
def public_tool():
    pass

@mcp.tool(tags={"internal"})
def internal_tool():
    pass
```

### 5. Configuration Options

Server-level configuration:
```python
mcp = FastMCP(
    name="ConfiguredServer",
    instructions="Detailed server description",
    tools=[existing_function1, existing_function2],  # Pre-register tools
)
```

Environment variables for global settings are also supported.

## Client Connection (for Testing)

```python
import asyncio
from fastmcp import Client

client = Client("http://localhost:8000/mcp")

async def call_tool(name: str):
    async with client:
        result = await client.call_tool("greet", {"name": name})
        print(result)

asyncio.run(call_tool("Ford"))
```

## Deployment Patterns

### 1. Local/Desktop (stdio)
- Use `mcp.run()` with default transport
- Integrates with Claude Desktop and similar MCP clients
- Best for development and local tools

### 2. Network Services (HTTP)
- Use `mcp.run(transport="http")`
- Accessible over network
- Supports multiple concurrent clients
- Can be deployed to cloud platforms

### 3. Production ASGI
- FastMCP can be used as ASGI application
- Deploy with uvicorn, gunicorn, or similar
- Full production-grade deployment

## Important Implementation Notes

1. **Use `run()` in synchronous contexts**: When your code is not async
2. **Use `run_async()` in async environments**: When working within async code
3. **Choose transport based on deployment needs**:
   - stdio for local/desktop
   - HTTP for network services
4. **Type hints are required**: FastMCP relies on them for schema generation
5. **Docstrings become tool descriptions**: Write clear docstrings for better tool documentation

## Minimal Working Example

```python
from fastmcp import FastMCP

mcp = FastMCP("Minimal Server")

@mcp.tool
def echo(message: str) -> str:
    """Echo back the message."""
    return message

if __name__ == "__main__":
    mcp.run()
```

Save as `server.py` and run with:
```bash
python server.py
# OR
fastmcp run server.py
```

## Next Steps for pflow MCP Server

Based on these patterns, our pflow MCP server should:

1. Use the standalone script pattern with `if __name__ == "__main__"`
2. Default to stdio transport for Claude Desktop integration
3. Register pflow CLI commands as tools using `@mcp.tool` decorator
4. Use clear type hints and docstrings for all tools
5. Structure tools to mirror pflow CLI commands (run, registry, workflow, etc.)
6. Consider tag-based filtering if we want to expose different tool sets
7. Use FastMCP's simple initialization without complex configuration initially
