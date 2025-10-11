# FastMCP Tool Implementation

Reference documentation for implementing MCP tools in the pflow server.

## Tool Definition Basics

Tools in FastMCP are defined using the `@mcp.tool` decorator on functions or by calling `mcp.tool()` programmatically.

### Simple Tool

```python
@mcp.tool
def add(a: int, b: int) -> int:
    """Adds two integer numbers together."""
    return a + b
```

### Decorator Arguments

The `@mcp.tool()` decorator accepts several optional arguments:

- `name`: Custom tool name (defaults to function name)
- `description`: Tool description (defaults to docstring)
- `tags`: List of categorization tags
- `enabled`: Boolean to control tool availability
- `exclude_args`: List of argument names to hide from the schema
- `annotations`: Metadata dictionary about tool behavior

Example with options:

```python
@mcp.tool(
    name="custom_name",
    description="Custom description",
    tags=["workflow", "execution"],
    enabled=True,
    exclude_args=["internal_param"],
    annotations={"category": "core"}
)
def my_tool(data: str, internal_param: bool = False) -> str:
    return f"Processed: {data}"
```

## Parameter Schemas

FastMCP automatically generates JSON schemas from Python type annotations.

### Supported Types

**Basic types:**
- `str`, `int`, `float`, `bool`

**Collection types:**
- `list[T]`
- `dict[K, V]`
- `set[T]`

**Date/time types:**
- `datetime`
- `date`
- `timedelta`

**Union types:**
- `str | int`
- `Optional[str]`

**Constrained types:**
- `Literal["option1", "option2"]`
- `Enum` subclasses

**Complex types:**
- Pydantic models

### Advanced Parameter Validation

Use `typing.Annotated` with Pydantic `Field` for detailed validation:

```python
from typing import Annotated
from pydantic import Field

@mcp.tool
def process_data(
    count: Annotated[int, Field(ge=0, le=100, description="Number of items to process")],
    user_id: Annotated[str, Field(pattern=r"^[A-Z]{2}\d{4}$", description="User ID format: XX9999")],
    tags: Annotated[list[str], Field(min_length=1, max_length=10)] = []
) -> str:
    """Process data with validated parameters."""
    return f"Processing {count} items for user {user_id}"
```

Common Pydantic field constraints:
- `ge`, `gt`, `le`, `lt`: Numeric comparisons
- `min_length`, `max_length`: String/list length
- `pattern`: Regex pattern matching
- `description`: Parameter documentation

### Optional Parameters

```python
@mcp.tool
def fetch_data(
    url: str,
    timeout: int = 30,
    headers: dict[str, str] | None = None
) -> dict:
    """Fetch data from URL with optional timeout and headers."""
    pass
```

## Return Types

### Simple Returns

Tools can return any serializable Python type:

```python
@mcp.tool
def get_user(user_id: str) -> dict:
    """Returns user data as dictionary."""
    return {"id": user_id, "name": "John Doe"}

@mcp.tool
def count_items(items: list[str]) -> int:
    """Returns count of items."""
    return len(items)
```

### Automatic Content Block Conversion

FastMCP automatically converts return values to MCP content blocks:
- Simple types → text content
- Structured data → JSON content
- Multiple values → multiple content blocks

### ToolResult for Full Control

For advanced control over the response:

```python
from fastmcp import ToolResult

@mcp.tool
def advanced_tool(query: str) -> ToolResult:
    """Tool with custom result formatting."""
    return ToolResult(
        content=[
            {"type": "text", "text": f"Query: {query}"},
            {"type": "text", "text": "Result: Success"}
        ],
        is_error=False
    )
```

## Async Patterns

FastMCP supports both synchronous and asynchronous tools.

### Async Tools

```python
@mcp.tool
async def fetch_remote_data(url: str) -> dict:
    """Async tool for I/O operations."""
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()
```

### Sync Tools

```python
@mcp.tool
def process_local_data(data: str) -> str:
    """Synchronous tool for CPU-bound operations."""
    return data.upper()
```

### When to Use Async

- **Use async** for I/O-bound operations:
  - Network requests
  - File I/O
  - Database queries
  - External API calls

- **Use sync** for CPU-bound operations:
  - Data processing
  - Computations
  - Quick lookups

## Error Handling

### Standard Exceptions

```python
@mcp.tool
def divide(a: int, b: int) -> float:
    """Divide two numbers."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
```

### ToolError for Controlled Errors

```python
from fastmcp import ToolError

@mcp.tool
def validate_input(data: str) -> str:
    """Validate and process input."""
    if not data.strip():
        raise ToolError("Input cannot be empty")
    return f"Valid: {data}"
```

### Context Access

Access logging and progress reporting:

```python
from fastmcp import Context

@mcp.tool
async def long_running_task(ctx: Context, items: list[str]) -> str:
    """Task with progress reporting."""
    ctx.info("Starting processing")

    for i, item in enumerate(items):
        ctx.info(f"Processing item {i+1}/{len(items)}")
        # Process item...

    ctx.info("Completed")
    return f"Processed {len(items)} items"
```

## Registering Methods as Tools

FastMCP has specific patterns for registering class methods.

### Instance Methods (Recommended Pattern)

**DO NOT** decorate instance methods directly:

```python
# ❌ WRONG - Do not do this
class MyClass:
    @mcp.tool  # This breaks method binding
    def instance_method(self, x: int) -> int:
        return x * 2
```

**DO** register after creating the instance:

```python
# ✅ CORRECT
class MyClass:
    def instance_method(self, x: int) -> int:
        """Multiply by 2."""
        return x * 2

# Create instance first, then register bound method
obj = MyClass()
mcp.tool(obj.instance_method)
```

### Initialization Registration Pattern

Encapsulate registration in `__init__`:

```python
class WorkflowProvider:
    def __init__(self, mcp_instance):
        self.mcp = mcp_instance
        # Register all methods during initialization
        self.mcp.tool(self.run_workflow)
        self.mcp.tool(self.list_workflows)
        self.mcp.tool(self.validate_workflow)

    def run_workflow(self, workflow_json: str) -> dict:
        """Execute a workflow from JSON."""
        # Implementation here
        return {"status": "success"}

    def list_workflows(self) -> list[str]:
        """List available workflows."""
        return ["workflow1", "workflow2"]

    def validate_workflow(self, workflow_json: str) -> dict:
        """Validate workflow JSON."""
        return {"valid": True}

# Usage
provider = WorkflowProvider(mcp)
```

### Class Methods

```python
class MyClass:
    @classmethod
    def from_string(cls, s: str) -> 'MyClass':
        """Create instance from string."""
        return cls(s)

# Register after class definition
mcp.tool(MyClass.from_string)
```

### Static Methods

```python
class Utils:
    @staticmethod
    def utility(x: int, y: int) -> int:
        """Utility function."""
        return x + y

# Register like a regular function
mcp.tool(Utils.utility)
```

## Common Patterns

### Pattern 1: Input Validation with Custom Types

```python
from pydantic import BaseModel, Field

class WorkflowInput(BaseModel):
    name: str = Field(..., min_length=1, description="Workflow name")
    nodes: list[dict] = Field(..., min_length=1, description="List of nodes")
    version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")

@mcp.tool
def create_workflow(workflow: WorkflowInput) -> dict:
    """Create a new workflow with validated input."""
    return {
        "status": "created",
        "name": workflow.name,
        "node_count": len(workflow.nodes)
    }
```

### Pattern 2: File Operations

```python
from pathlib import Path

@mcp.tool
def read_workflow(path: str) -> str:
    """Read workflow from file."""
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise ToolError(f"File not found: {path}")
    return file_path.read_text()

@mcp.tool
def save_workflow(path: str, content: str) -> dict:
    """Save workflow to file."""
    file_path = Path(path).expanduser()
    file_path.write_text(content)
    return {"path": str(file_path), "size": len(content)}
```

### Pattern 3: List/Get Operations

```python
@mcp.tool
def list_items(
    category: str | None = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 20
) -> list[dict]:
    """List items with optional filtering."""
    # Implementation
    return [
        {"id": "1", "name": "Item 1"},
        {"id": "2", "name": "Item 2"}
    ]

@mcp.tool
def get_item(item_id: str) -> dict:
    """Get single item by ID."""
    # Implementation
    return {"id": item_id, "name": "Item"}
```

### Pattern 4: Command Execution

```python
import subprocess

@mcp.tool
async def execute_command(
    command: str,
    cwd: str | None = None,
    timeout: int = 30
) -> dict:
    """Execute shell command with timeout."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        raise ToolError(f"Command timed out after {timeout}s")
    except subprocess.CalledProcessError as e:
        raise ToolError(f"Command failed: {e.stderr}")
```

### Pattern 5: JSON Schema Operations

```python
import json
from typing import Any

@mcp.tool
def validate_json(content: str, schema: dict[str, Any] | None = None) -> dict:
    """Validate JSON string and optionally check against schema."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ToolError(f"Invalid JSON: {e}")

    if schema:
        # Add schema validation logic here
        pass

    return {"valid": True, "data": data}
```

## Complete Tool Examples

### Example 1: Workflow Execution Tool

```python
from typing import Annotated
from pydantic import Field
import json

@mcp.tool
async def run_workflow(
    workflow_json: Annotated[str, Field(description="Workflow definition as JSON string")],
    inputs: Annotated[dict[str, Any], Field(default_factory=dict, description="Input parameters")] = {},
    trace: Annotated[bool, Field(description="Enable execution tracing")] = False
) -> dict:
    """
    Execute a pflow workflow from JSON definition.

    Returns execution result with status, outputs, and optional trace.
    """
    try:
        # Parse workflow
        workflow_data = json.loads(workflow_json)

        # Execute (pseudo-code)
        result = await execute_workflow_internal(workflow_data, inputs, trace)

        return {
            "status": "success",
            "outputs": result.outputs,
            "trace": result.trace if trace else None
        }
    except json.JSONDecodeError as e:
        raise ToolError(f"Invalid workflow JSON: {e}")
    except Exception as e:
        raise ToolError(f"Workflow execution failed: {e}")
```

### Example 2: Registry Query Tool

```python
@mcp.tool
def list_nodes(
    category: Annotated[str | None, Field(description="Filter by category")] = None,
    search: Annotated[str | None, Field(description="Search in node names/descriptions")] = None
) -> list[dict]:
    """
    List available pflow nodes with optional filtering.

    Returns list of nodes with metadata (name, description, inputs, outputs).
    """
    # Pseudo-code
    nodes = get_all_nodes()

    if category:
        nodes = [n for n in nodes if n.category == category]

    if search:
        nodes = [n for n in nodes if search.lower() in n.name.lower()
                 or search.lower() in n.description.lower()]

    return [
        {
            "name": node.name,
            "description": node.description,
            "category": node.category,
            "inputs": node.inputs,
            "outputs": node.outputs
        }
        for node in nodes
    ]
```

### Example 3: File Management Tool

```python
from pathlib import Path

@mcp.tool
def save_workflow_file(
    name: Annotated[str, Field(min_length=1, pattern=r"^[\w\-]+$", description="Workflow name (alphanumeric)")],
    workflow_json: Annotated[str, Field(description="Workflow JSON content")],
    overwrite: Annotated[bool, Field(description="Overwrite if exists")] = False
) -> dict:
    """
    Save workflow to ~/.pflow/workflows directory.

    Returns saved file path and metadata.
    """
    workflows_dir = Path.home() / ".pflow" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    file_path = workflows_dir / f"{name}.json"

    if file_path.exists() and not overwrite:
        raise ToolError(f"Workflow '{name}' already exists. Use overwrite=true to replace.")

    # Validate JSON first
    try:
        json.loads(workflow_json)
    except json.JSONDecodeError as e:
        raise ToolError(f"Invalid JSON: {e}")

    file_path.write_text(workflow_json)

    return {
        "path": str(file_path),
        "name": name,
        "size": len(workflow_json),
        "created": not file_path.exists()
    }
```

## Client-Side Tool Operations

### How Tools Are Called

From the client perspective:

1. **Discovery**: `list_tools()` returns available tools with schemas
2. **Filtering**: Tools can be filtered by metadata tags
3. **Execution**: `call_tool(name, arguments)` executes the tool

### Result Access Methods

When a tool is called, the result provides multiple access methods:

```python
result = await client.call_tool("my_tool", {"param": "value"})

# Method 1: Hydrated Python objects (FastMCP's key feature)
data = result.data  # Complete Python objects with types reconstructed

# Method 2: Standard content blocks
content = result.content  # MCP content blocks

# Method 3: Raw JSON
raw = result.structured_content  # Raw JSON data

# Method 4: Error checking
if result.is_error:
    print("Tool failed")
```

### Error Handling from Client

```python
# Default: raises ToolError on failure
try:
    result = await client.call_tool("my_tool", {"param": "value"})
except ToolError as e:
    print(f"Tool failed: {e}")

# Manual error checking
result = await client.call_tool("my_tool", {"param": "value"}, raise_on_error=False)
if result.is_error:
    print("Handle error manually")
```

## Key Takeaways for pflow MCP Server

1. **Use instance method registration pattern** for organizing related tools in classes
2. **Leverage Pydantic Field** for comprehensive input validation
3. **Use async for I/O operations** (file access, subprocess calls)
4. **Provide clear descriptions** in docstrings - they become tool documentation
5. **Return structured data** (dicts, lists) rather than plain strings when possible
6. **Use ToolError** for user-facing error messages
7. **Type everything** - types become the schema that AI agents see
8. **Keep tools focused** - one clear responsibility per tool
9. **Add helpful parameter descriptions** using Field() annotations
10. **Consider the AI agent perspective** - tools are the API they interact with
