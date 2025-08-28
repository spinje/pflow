#!/usr/bin/env python
"""
MCP Protocol Reference Implementation

This file demonstrates how MCP servers SHOULD implement structured outputs
according to the Model Context Protocol specification. It shows the proper
way to provide typed, validated data using output schemas.

IMPORTANT: This is a reference implementation showing the protocol structure.
The FastMCP API may have changed since this was written. Use this as a guide
for understanding how structured outputs should work in MCP.

Key Concepts Demonstrated:
1. Using Pydantic models for type-safe output schemas
2. Returning structuredContent for typed data
3. Mixing structured and unstructured tools in one server
4. Proper error handling with isError flag

Protocol Version: 2025-06-18 (supports structuredContent)
"""

import asyncio
import sys
from typing import Optional

from pydantic import BaseModel, Field

# Note: This uses the FastMCP pattern which auto-generates output schemas
# from Pydantic return type annotations. Other MCP server implementations
# can manually provide outputSchema in tool definitions.

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.stdio import stdio_server
except ImportError:
    print("Note: MCP SDK required. Install with: pip install 'mcp[cli]'", file=sys.stderr)
    sys.exit(1)

# Create FastMCP app
mcp = FastMCP("Structured Output Reference Server")


# ==============================================================================
# STRUCTURED OUTPUT MODELS
# These Pydantic models define the structure of tool outputs.
# The MCP protocol will include these as outputSchema in tool definitions.
# ==============================================================================


class WeatherData(BaseModel):
    """
    Structured weather information with typed, validated fields.

    When a tool returns this model, the MCP protocol sends:
    - structuredContent: The actual WeatherData as JSON
    - outputSchema: JSON Schema derived from this model
    - content[0].text: JSON string for backward compatibility
    """

    temperature: float = Field(description="Temperature in Celsius")
    humidity: float = Field(ge=0, le=100, description="Humidity percentage (0-100)")
    conditions: str = Field(description="Weather conditions (e.g., 'Sunny', 'Cloudy')")
    wind_speed: Optional[float] = Field(default=None, description="Wind speed in km/h")
    uv_index: Optional[int] = Field(default=None, ge=0, le=11, description="UV index (0-11)")


class CalculationResult(BaseModel):
    """
    Structured result from mathematical calculations.

    Shows how to return complex nested data with full type information.
    """

    result: float = Field(description="The calculation result")
    operation: str = Field(description="Operation performed (add, subtract, multiply, divide)")
    inputs: list[float] = Field(description="Input values used in calculation")
    formula: str = Field(description="Human-readable formula")
    is_exact: bool = Field(default=True, description="Whether result is exact or approximate")


class FileInfo(BaseModel):
    """
    Structured file metadata.

    Demonstrates optional fields and nested structures.
    """

    path: str = Field(description="Full file path")
    size_bytes: int = Field(ge=0, description="File size in bytes")
    is_directory: bool = Field(description="Whether this is a directory")
    permissions: Optional[str] = Field(default=None, description="File permissions string")
    created_at: Optional[str] = Field(default=None, description="ISO 8601 creation timestamp")
    modified_at: Optional[str] = Field(default=None, description="ISO 8601 modification timestamp")


class ErrorResult(BaseModel):
    """
    Structured error information.

    When returned, the server should also set isError=True in the response.
    """

    error_type: str = Field(description="Type of error (e.g., 'FileNotFound', 'PermissionDenied')")
    message: str = Field(description="Human-readable error message")
    details: Optional[dict] = Field(default=None, description="Additional error context")


# ==============================================================================
# TOOL IMPLEMENTATIONS
# These demonstrate different output patterns in MCP.
# ==============================================================================


@mcp.tool()
def get_weather(city: str) -> WeatherData:
    """
    Get current weather for a city (returns structured data).

    This tool demonstrates:
    - Returning a Pydantic model for structured output
    - Type validation and constraints (humidity 0-100)
    - Optional fields (wind_speed, uv_index)

    The MCP protocol will:
    1. Include outputSchema in the tool definition
    2. Return structuredContent with the WeatherData
    3. Validate the response against the schema
    """
    # Simulate weather API call
    weather_database = {
        "San Francisco": WeatherData(temperature=18.5, humidity=72.0, conditions="Foggy", wind_speed=15.0, uv_index=3),
        "New York": WeatherData(temperature=5.0, humidity=45.0, conditions="Clear", wind_speed=20.0, uv_index=2),
        "London": WeatherData(
            temperature=12.0,
            humidity=80.0,
            conditions="Rainy",
            wind_speed=25.0,
            # Note: uv_index is optional and not provided here
        ),
    }

    # Return structured data or default
    return weather_database.get(
        city,
        WeatherData(
            temperature=20.0, humidity=50.0, conditions="Unknown location - using default weather", wind_speed=10.0
        ),
    )


@mcp.tool()
def calculate(operation: str, a: float, b: float) -> CalculationResult:
    """
    Perform a calculation and return structured result.

    Demonstrates:
    - Multiple typed parameters
    - Complex return structure with nested data
    - Computed fields (formula)
    """
    operations = {
        "add": (a + b, f"{a} + {b}"),
        "subtract": (a - b, f"{a} - {b}"),
        "multiply": (a * b, f"{a} x {b}"),
        "divide": (a / b if b != 0 else float("nan"), f"{a} ÷ {b}"),
    }

    if operation not in operations:
        # This would ideally return an ErrorResult with isError=True
        result_value = 0
        formula = f"Unknown operation: {operation}"
    else:
        result_value, formula = operations[operation]

    return CalculationResult(
        result=result_value,
        operation=operation,
        inputs=[a, b],
        formula=formula,
        is_exact=operation != "divide" or (b != 0 and a % b == 0),
    )


@mcp.tool()
def get_file_info(path: str) -> FileInfo:
    """
    Get metadata about a file or directory (returns structured data).

    Demonstrates:
    - File system information as structured data
    - Optional fields (permissions, timestamps)
    - Error cases that could use ErrorResult
    """
    from datetime import datetime

    # This is a mock implementation
    # Real implementation would check actual filesystem

    if not path.startswith("/"):
        # In a real server, this might return ErrorResult with isError=True
        return FileInfo(
            path=path, size_bytes=0, is_directory=False, permissions=None, created_at=None, modified_at=None
        )

    # Mock file info
    return FileInfo(
        path=path,
        size_bytes=1024 * 10,  # 10 KB
        is_directory=path.endswith("/"),
        permissions="rwxr-xr-x" if path.endswith("/") else "rw-r--r--",
        created_at=datetime.now().isoformat(),
        modified_at=datetime.now().isoformat(),
    )


@mcp.tool()
def echo_text(message: str) -> str:
    """
    Simple tool that returns plain text (unstructured output).

    Demonstrates:
    - Not all tools need structured output
    - Simple string return is still valid
    - MCP will use content blocks, not structuredContent

    This tool will NOT have an outputSchema, and the result
    will be returned in content[0].text rather than structuredContent.
    """
    return f"Echo: {message}"


@mcp.tool()
def list_items(category: str) -> list[str]:
    """
    Return a list of items (semi-structured output).

    Demonstrates:
    - Lists are valid return types
    - Will be included in structuredContent as JSON array
    - outputSchema will show array type
    """
    items = {
        "fruits": ["apple", "banana", "orange", "mango"],
        "colors": ["red", "green", "blue", "yellow"],
        "numbers": ["one", "two", "three", "four"],
    }

    return items.get(category, [f"Unknown category: {category}"])


# ==============================================================================
# SERVER RUNTIME
# This shows how to run an MCP server with stdio transport.
# ==============================================================================


async def run_server():
    """
    Run the MCP server using stdio transport.

    The stdio transport is most common for MCP servers as it allows
    them to be launched as subprocesses by clients.
    """
    async with stdio_server() as streams:
        # Note: The initialization options setup may vary by MCP SDK version
        # This is a reference pattern - check current SDK documentation
        await mcp.run(
            streams[0],
            streams[1],
            # initialization_options would include server capabilities
            # FastMCP typically handles this automatically
        )


def main():
    """
    Entry point for the MCP server.

    When run, this server will:
    1. Listen on stdio for MCP protocol messages
    2. Respond to initialize requests with server info
    3. List available tools with their input/output schemas
    4. Execute tools and return structured or unstructured data
    """
    print("MCP Protocol Reference Server", file=sys.stderr)
    print("==============================", file=sys.stderr)
    print("This server demonstrates structured output patterns.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Available tools:", file=sys.stderr)
    print("  - get_weather(city) -> WeatherData", file=sys.stderr)
    print("  - calculate(operation, a, b) -> CalculationResult", file=sys.stderr)
    print("  - get_file_info(path) -> FileInfo", file=sys.stderr)
    print("  - echo_text(message) -> str", file=sys.stderr)
    print("  - list_items(category) -> list[str]", file=sys.stderr)
    print("", file=sys.stderr)
    print("Protocol features demonstrated:", file=sys.stderr)
    print("  ✓ structuredContent for typed data", file=sys.stderr)
    print("  ✓ outputSchema from Pydantic models", file=sys.stderr)
    print("  ✓ Mixed structured/unstructured tools", file=sys.stderr)
    print("  ✓ Optional fields and validation", file=sys.stderr)
    print("", file=sys.stderr)

    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        print("\nServer stopped.", file=sys.stderr)
    except Exception as e:
        print(f"\nServer error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()


# ==============================================================================
# PROTOCOL WIRE FORMAT EXAMPLES
# These comments show what the actual JSON-RPC messages look like.
# ==============================================================================

"""
Example 1: Tool with structured output (get_weather)

Client Request:
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "get_weather",
    "arguments": {"city": "San Francisco"}
  },
  "id": 1
}

Server Response:
{
  "jsonrpc": "2.0",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"temperature\":18.5,\"humidity\":72.0,\"conditions\":\"Foggy\",\"wind_speed\":15.0,\"uv_index\":3}"
      }
    ],
    "structuredContent": {
      "temperature": 18.5,
      "humidity": 72.0,
      "conditions": "Foggy",
      "wind_speed": 15.0,
      "uv_index": 3
    },
    "isError": false
  },
  "id": 1
}

Example 2: Tool listing with output schemas

Client Request:
{
  "jsonrpc": "2.0",
  "method": "tools/list",
  "params": {},
  "id": 2
}

Server Response (partial):
{
  "jsonrpc": "2.0",
  "result": {
    "tools": [
      {
        "name": "get_weather",
        "description": "Get current weather for a city",
        "inputSchema": {
          "type": "object",
          "properties": {
            "city": {"type": "string"}
          },
          "required": ["city"]
        },
        "outputSchema": {
          "type": "object",
          "properties": {
            "temperature": {"type": "number"},
            "humidity": {"type": "number", "minimum": 0, "maximum": 100},
            "conditions": {"type": "string"},
            "wind_speed": {"type": "number"},
            "uv_index": {"type": "integer", "minimum": 0, "maximum": 11}
          },
          "required": ["temperature", "humidity", "conditions"]
        }
      }
    ]
  },
  "id": 2
}
"""
