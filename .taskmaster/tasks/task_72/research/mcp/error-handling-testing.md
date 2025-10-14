# FastMCP Error Handling and Testing

## Error Handling

### Error Handling in Tools

FastMCP provides built-in error handling through middleware and context-based logging. When errors occur in tools:

1. **Raise exceptions normally** - FastMCP middleware catches and converts them to MCP error responses
2. **Log errors using context** - Use `ctx.error()` to send error messages to clients
3. **Middleware handles formatting** - `ErrorHandlingMiddleware` ensures consistent error response formats

```python
@mcp.tool
async def analyze_data(data: list[float], ctx: Context) -> dict:
    await ctx.debug("Starting analysis")
    await ctx.info(f"Analyzing {len(data)} data points")

    try:
        if not data:
            await ctx.error("Empty data provided")
            raise ValueError("Cannot analyze empty data")

        result = sum(data) / len(data)
        await ctx.info(f"Analysis complete, average: {result}")
        return {"average": result}
    except Exception as e:
        await ctx.error(f"Analysis failed: {str(e)}")
        raise
```

### Error Handling Middleware

FastMCP provides two key middleware classes:

**ErrorHandlingMiddleware**:
- Catches exceptions and converts them to MCP error responses
- Tracks error patterns for monitoring
- Key methods:
  - `on_message()`: Handles errors for all messages
  - `get_error_stats()`: Retrieves error statistics

**RetryMiddleware**:
- Implements automatic retry logic for failed requests
- Uses exponential backoff to prevent overwhelming servers
- Handles transient errors automatically

```python
# Error handling middleware usage
middleware = ErrorHandlingMiddleware()
error_stats = middleware.get_error_stats()
```

### Error Response Format

While specific error response formats aren't detailed in the documentation, FastMCP follows these principles:

- **Centralized error management** - All errors go through middleware
- **Consistent error response formatting** - Standardized across all tools
- **Error tracking and monitoring** - Built-in error pattern monitoring
- **Automatic retry mechanisms** - For resilient communication

## Logging and Debugging

### MCP Context for Logging

All logging in FastMCP tools is done through the `Context` object, which provides async logging methods that send messages directly to MCP clients.

**Available Log Levels**:
1. **Debug**: `await ctx.debug()` - Detailed diagnostic information
2. **Info**: `await ctx.info()` - Normal execution progress
3. **Warning**: `await ctx.warning()` - Potential issues that don't stop execution
4. **Error**: `await ctx.error()` - Problematic events

**Basic Logging**:
```python
@mcp.tool
async def process_file(file_uri: str, ctx: Context) -> str:
    await ctx.debug("Starting file processing")
    await ctx.info(f"Processing file: {file_uri}")
    await ctx.warning("File is larger than recommended")
    await ctx.error("Failed to read file")
    return "Processed"
```

**Structured Logging with Extra Metadata**:
```python
await ctx.info(
    "Processing transaction",
    extra={
        "transaction_id": transaction_id,
        "amount": amount,
        "currency": "USD"
    }
)
```

### Accessing Context

Two methods to access context in tools:

**1. Dependency Injection (Recommended)**:
```python
@mcp.tool
async def process_file(file_uri: str, ctx: Context) -> str:
    await ctx.info(f"Processing file: {file_uri}")
    return "Processed file"
```

**2. Runtime Dependency**:
```python
from fastmcp import get_context

async def process_data(data: list[float]) -> dict:
    ctx = get_context()
    await ctx.info(f"Processing {len(data)} data points")
    return {"count": len(data)}
```

### Context Capabilities Beyond Logging

The MCP Context provides additional capabilities:

**Progress Reporting**:
```python
await ctx.report_progress(progress=50, total=100)
```

**Resource Access**:
```python
content = await ctx.read_resource(uri)
```

**State Management**:
```python
await ctx.set_state(key, value)
value = await ctx.get_state(key)
```

**Client Interactions**:
```python
input_data = await ctx.elicit()  # Request structured input
text = await ctx.sample()  # Request LLM generation
```

**Context Properties**:
- `ctx.request_id` - Unique request identifier
- `ctx.client_id` - Client making the request
- `ctx.fastmcp` - Access to underlying FastMCP server instance

### Logging Use Cases

- **Debugging**: Track execution flow and variable values
- **Progress tracking**: Keep users informed of long-running operations
- **Error reporting**: Communicate failures and issues
- **Audit trails**: Create records of operations

**Note**: For standard server-side logging (not sent to clients), use `fastmcp.utilities.logging.get_logger()` or Python's built-in `logging` module.

## Testing MCP Servers

### Core Testing Principles

1. **Tests should verify a single behavior**
2. **Each test must be self-contained**
3. **Tests should be runnable in any order or in parallel**
4. **Provide clear intent through test names and assertions**

### Test Organization

- **Mirror the `src/` directory structure**
- Place tests in corresponding `tests/` directories
- Example: `src/fastmcp/server/auth.py` → `tests/server/test_auth.py`

### In-Memory Testing Approach

FastMCP supports in-memory testing - the most efficient way to test:

- Use direct server instance for testing
- No network deployment required
- Deterministic and fast test execution
- Pass server directly to client for testing

**Basic Test Pattern**:
```python
async def test_tool_functionality():
    # Create isolated server instance
    mcp = FastMCP("test-server")

    # Define tool within test
    @mcp.tool
    def example_tool(param: str) -> str:
        return param.upper()

    # Use in-memory client
    async with Client(mcp) as client:
        result = await client.call_tool("example_tool", {"param": "test"})
        assert result.data == "TEST"
```

### Test Setup Best Practices

**Isolated Server Instances**:
```python
import pytest
from fastmcp import FastMCP
from fastmcp.testing import Client

@pytest.mark.asyncio
async def test_greeting_tool():
    # Create fresh server for this test
    mcp = FastMCP("test-server")

    @mcp.tool
    async def greet(name: str, ctx: Context) -> str:
        await ctx.info(f"Greeting {name}")
        return f"Hello, {name}!"

    async with Client(mcp) as client:
        result = await client.call_tool("greet", {"name": "World"})
        assert result.data == "Hello, World!"
```

### Mocking External Dependencies

Use `AsyncMock` for simulating database or external service interactions:

```python
from unittest.mock import AsyncMock
import pytest

@pytest.mark.asyncio
async def test_with_mock_database():
    mcp = FastMCP("test-server")

    # Mock database
    mock_db = AsyncMock()
    mock_db.fetch_user.return_value = {"id": 1, "name": "Alice"}

    @mcp.tool
    async def get_user(user_id: int, ctx: Context) -> dict:
        await ctx.info(f"Fetching user {user_id}")
        user = await mock_db.fetch_user(user_id)
        return user

    async with Client(mcp) as client:
        result = await client.call_tool("get_user", {"user_id": 1})
        assert result.data["name"] == "Alice"

        # Verify mock was called
        mock_db.fetch_user.assert_called_once_with(1)
```

### Assertion Strategies

- **Be specific in assertions**
- **Provide context on failure**
- **Use meaningful error messages**
- **Avoid multiple assertions testing different behaviors in one test**

```python
async def test_with_clear_assertions():
    mcp = FastMCP("test-server")

    @mcp.tool
    def calculate_total(items: list[float]) -> dict:
        return {
            "total": sum(items),
            "count": len(items),
            "average": sum(items) / len(items) if items else 0
        }

    async with Client(mcp) as client:
        result = await client.call_tool("calculate_total", {"items": [10, 20, 30]})

        # Specific assertions with clear intent
        assert result.data["total"] == 60, "Total should be sum of all items"
        assert result.data["count"] == 3, "Count should match number of items"
        assert result.data["average"] == 20, "Average should be total/count"
```

## Mock Client Testing

### Testing Without Real Transport

The recommended approach is to use FastMCP's in-memory client:

```python
from fastmcp.testing import Client

@pytest.mark.asyncio
async def test_tool_without_transport():
    mcp = FastMCP("test-server")

    @mcp.tool
    def uppercase(text: str) -> str:
        return text.upper()

    # No network transport - direct server access
    async with Client(mcp) as client:
        result = await client.call_tool("uppercase", {"text": "hello"})
        assert result.data == "HELLO"
```

### Testing with Context

```python
@pytest.mark.asyncio
async def test_context_logging():
    mcp = FastMCP("test-server")

    @mcp.tool
    async def process(data: str, ctx: Context) -> str:
        await ctx.debug("Starting processing")
        await ctx.info(f"Processing data: {data}")
        result = data.upper()
        await ctx.info(f"Processing complete: {result}")
        return result

    async with Client(mcp) as client:
        result = await client.call_tool("process", {"data": "test"})
        assert result.data == "TEST"
```

### Testing Error Handling

```python
@pytest.mark.asyncio
async def test_error_handling():
    mcp = FastMCP("test-server")

    @mcp.tool
    async def divide(a: float, b: float, ctx: Context) -> float:
        if b == 0:
            await ctx.error("Division by zero attempted")
            raise ValueError("Cannot divide by zero")
        return a / b

    async with Client(mcp) as client:
        # Test successful case
        result = await client.call_tool("divide", {"a": 10, "b": 2})
        assert result.data == 5.0

        # Test error case
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            await client.call_tool("divide", {"a": 10, "b": 0})
```

### Fixture Usage

Create reusable test configurations:

```python
import pytest
from fastmcp import FastMCP

@pytest.fixture
def test_server():
    """Provide a fresh server instance for each test."""
    return FastMCP("test-server")

@pytest.fixture
def mock_database():
    """Provide a mocked database for testing."""
    db = AsyncMock()
    db.fetch_user.return_value = {"id": 1, "name": "Test User"}
    return db

@pytest.mark.asyncio
async def test_with_fixtures(test_server, mock_database):
    @test_server.tool
    async def get_user(user_id: int, ctx: Context) -> dict:
        user = await mock_database.fetch_user(user_id)
        await ctx.info(f"Retrieved user: {user['name']}")
        return user

    async with Client(test_server) as client:
        result = await client.call_tool("get_user", {"user_id": 1})
        assert result.data["name"] == "Test User"
```

**Important**: Avoid opening clients in fixtures. Create server fixtures but open clients in tests.

### Special Test Markers

- `@pytest.mark.integration`: For tests requiring external resources
- `@pytest.mark.client_process`: For tests spawning separate processes

### Network Transport Testing

For actual network transport tests, use `run_server_in_process`:

```python
@pytest.mark.client_process
async def test_with_network_transport():
    mcp = FastMCP("test-server")

    @mcp.tool
    def echo(message: str) -> str:
        return message

    # Test with actual network transport
    from fastmcp.testing import run_server_in_process
    async with run_server_in_process(mcp) as client:
        result = await client.call_tool("echo", {"message": "hello"})
        assert result.data == "hello"
```

This approach tests:
- HTTP, WebSocket, and other transport-specific behaviors
- Authentication mechanisms
- Timeouts and headers
- Real network conditions

## Code Examples

### Complete Tool with Error Handling and Logging

```python
from fastmcp import FastMCP, Context

mcp = FastMCP("data-processor")

@mcp.tool
async def process_dataset(
    file_path: str,
    operation: str,
    ctx: Context
) -> dict:
    """
    Process a dataset with comprehensive error handling and logging.

    Args:
        file_path: Path to the data file
        operation: Operation to perform (sum, average, count)
        ctx: MCP context for logging

    Returns:
        dict with operation results
    """
    await ctx.info(f"Starting dataset processing: {operation}")
    await ctx.debug(f"File path: {file_path}")

    try:
        # Validate input
        if operation not in ["sum", "average", "count"]:
            await ctx.error(f"Invalid operation: {operation}")
            raise ValueError(f"Operation must be sum, average, or count. Got: {operation}")

        await ctx.debug("Reading data file")
        # Simulated file reading
        data = [1, 2, 3, 4, 5]

        await ctx.info(f"Processing {len(data)} data points")
        await ctx.report_progress(50, 100)

        # Perform operation
        if operation == "sum":
            result = sum(data)
        elif operation == "average":
            result = sum(data) / len(data)
        else:  # count
            result = len(data)

        await ctx.report_progress(100, 100)
        await ctx.info(
            f"Processing complete: {operation} = {result}",
            extra={
                "operation": operation,
                "result": result,
                "data_points": len(data)
            }
        )

        return {
            "operation": operation,
            "result": result,
            "data_points": len(data)
        }

    except FileNotFoundError as e:
        await ctx.error(f"File not found: {file_path}")
        raise
    except Exception as e:
        await ctx.error(f"Processing failed: {str(e)}")
        raise
```

### Complete Test Suite Example

```python
import pytest
from unittest.mock import AsyncMock
from fastmcp import FastMCP, Context
from fastmcp.testing import Client

@pytest.fixture
def server():
    """Provide fresh server instance for each test."""
    return FastMCP("test-server")

@pytest.mark.asyncio
async def test_successful_processing(server):
    """Test successful dataset processing."""

    @server.tool
    async def process_dataset(file_path: str, operation: str, ctx: Context) -> dict:
        await ctx.info(f"Processing {operation}")
        data = [1, 2, 3, 4, 5]

        if operation == "sum":
            result = sum(data)
        elif operation == "average":
            result = sum(data) / len(data)
        else:
            result = len(data)

        return {"operation": operation, "result": result}

    async with Client(server) as client:
        result = await client.call_tool(
            "process_dataset",
            {"file_path": "test.csv", "operation": "sum"}
        )

        assert result.data["operation"] == "sum"
        assert result.data["result"] == 15

@pytest.mark.asyncio
async def test_invalid_operation_error(server):
    """Test error handling for invalid operations."""

    @server.tool
    async def process_dataset(file_path: str, operation: str, ctx: Context) -> dict:
        if operation not in ["sum", "average", "count"]:
            await ctx.error(f"Invalid operation: {operation}")
            raise ValueError(f"Invalid operation: {operation}")

        return {"operation": operation, "result": 0}

    async with Client(server) as client:
        with pytest.raises(ValueError, match="Invalid operation"):
            await client.call_tool(
                "process_dataset",
                {"file_path": "test.csv", "operation": "invalid"}
            )

@pytest.mark.asyncio
async def test_with_mocked_file_system(server):
    """Test with mocked external dependencies."""

    mock_fs = AsyncMock()
    mock_fs.read_file.return_value = [10, 20, 30]

    @server.tool
    async def process_dataset(file_path: str, operation: str, ctx: Context) -> dict:
        await ctx.debug(f"Reading file: {file_path}")
        data = await mock_fs.read_file(file_path)

        await ctx.info(f"Processing {len(data)} items")
        result = sum(data) if operation == "sum" else len(data)

        return {"result": result}

    async with Client(server) as client:
        result = await client.call_tool(
            "process_dataset",
            {"file_path": "test.csv", "operation": "sum"}
        )

        assert result.data["result"] == 60
        mock_fs.read_file.assert_called_once_with("test.csv")

@pytest.mark.asyncio
async def test_context_logging_and_progress(server):
    """Test context logging and progress reporting."""

    @server.tool
    async def long_operation(steps: int, ctx: Context) -> dict:
        await ctx.info("Starting long operation")

        for i in range(steps):
            await ctx.debug(f"Step {i+1}/{steps}")
            await ctx.report_progress(i+1, steps)

        await ctx.info("Operation complete")
        return {"steps_completed": steps}

    async with Client(server) as client:
        result = await client.call_tool(
            "long_operation",
            {"steps": 5}
        )

        assert result.data["steps_completed"] == 5
```

## Key Takeaways for Implementation

1. **Always use Context for logging** - Don't use print() or standard logging in tools
2. **Let middleware handle errors** - Just raise exceptions normally, middleware converts them
3. **Test in-memory first** - Fastest and most reliable testing approach
4. **Mock external dependencies** - Use AsyncMock for databases, APIs, file systems
5. **Be specific with assertions** - Clear error messages help debugging
6. **Use fixtures for reusable setup** - But don't open clients in fixtures
7. **Structure logging appropriately** - Use debug/info/warning/error levels correctly
8. **Test error cases explicitly** - Don't just test happy paths
9. **Keep tests isolated** - Each test should be self-contained and runnable independently
10. **Use structured logging** - Add extra metadata for better observability
