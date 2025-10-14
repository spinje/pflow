# MCP Server Implementation Templates

**Purpose**: Ready-to-use code templates for implementing the pflow MCP server
**Usage**: Copy these templates and fill in the implementation details

---

## File 1: server.py

```python
"""
pflow MCP Server Instance

This module defines the central FastMCP server instance that all tools register with.
This is the single source of truth for the MCP server configuration.

The server is exported and imported by tool modules to register their tools.
"""

from fastmcp import FastMCP

# Central MCP server instance
# All tools import this instance and register via @mcp.tool() decorator
mcp = FastMCP(
    name="pflow",
    version="0.1.0",  # Match pflow version
    instructions=(
        "Exposes pflow workflow building and execution capabilities. "
        "Provides tools for workflow discovery, execution, validation, "
        "saving, and registry operations. Use these tools to build and "
        "run workflows programmatically without CLI overhead."
    )
)
```

---

## File 2: main.py

```python
"""
pflow MCP Server Entry Point

Run with:
    python -m pflow.mcp_server.main

Or via CLI:
    pflow serve mcp
"""

from .server import mcp

# Import tools package to trigger decorator registration
# This imports all tool modules via tools/__init__.py
from . import tools

# Note: Tools are registered at import time via @mcp.tool() decorators
# No manual registration needed here

if __name__ == "__main__":
    # Run with stdio transport (default)
    # This makes the server compatible with Claude Desktop and similar MCP clients
    mcp.run()
```

---

## File 3: tools/__init__.py

```python
"""
pflow MCP Server Tools Package

This package contains all MCP tool implementations organized by functional domain:
- workflow_tools: Workflow lifecycle (execute, validate, save, list, discover)
- registry_tools: Node operations (discover, search, describe, list, run)
- settings_tools: Configuration management (get, set)
- trace_tools: Debugging and tracing (read)

Import this package to register all tools with the MCP server.
"""

# Import all tool modules to trigger @mcp.tool() decorator registration
# These imports happen at package import time
from . import workflow_tools
from . import registry_tools
from . import settings_tools
from . import trace_tools

__all__ = [
    'workflow_tools',
    'registry_tools',
    'settings_tools',
    'trace_tools',
]
```

---

## File 4: tools/workflow_tools.py

```python
"""
Workflow Tools for pflow MCP Server

This module provides tools for workflow lifecycle management including
execution, validation, saving, listing, and discovery.

Tools:
1. workflow_execute - Execute workflows with JSON output and traces
2. workflow_validate - Validate workflow structure without execution
3. workflow_save - Save workflow to global library
4. workflow_list - List all saved workflows
5. workflow_discover - Find workflows using LLM matching

All tools use agent-optimized defaults:
- JSON output (always)
- Traces enabled (always)
- No auto-repair (explicit errors)
- Fresh service instances (stateless)
"""

from typing import Annotated, Any
from pydantic import Field
from fastmcp import Context

# Import central server instance
from ..server import mcp

# Import service layer (stateless wrappers)
from ..services.workflow_service import (
    execute_workflow,
    validate_workflow,
    save_workflow,
    list_workflows,
    discover_workflows
)

# Import utilities
from ..utils.errors import format_error_for_llm
from ..utils.validation import validate_workflow_name


@mcp.tool()
async def workflow_execute(
    workflow: Annotated[
        str | dict,
        Field(description="Workflow JSON string, dict, or saved workflow name")
    ],
    parameters: Annotated[
        dict[str, Any] | None,
        Field(description="Input parameters for workflow execution")
    ] = None,
    ctx: Context | None = None
) -> dict:
    """
    Execute a pflow workflow with agent-optimized defaults.

    This tool executes workflows with settings optimized for AI agents:
    - Always returns JSON output
    - Always saves execution trace
    - Never auto-repairs (returns explicit errors)
    - Creates fresh service instances (stateless)

    Args:
        workflow: Workflow JSON string, dict, or name of saved workflow
        parameters: Input parameters dict (optional)
        ctx: MCP context for logging and progress (optional)

    Returns:
        dict: {
            "success": bool,
            "outputs": dict,          # Workflow outputs
            "trace_path": str         # Path to execution trace file
        }

    Errors:
        Returns {"success": false, "error": {...}} on failure
    """
    try:
        if ctx:
            await ctx.info(f"Starting workflow execution: {workflow}")
            await ctx.report_progress(10, 100)

        # Call service layer (creates fresh instances, stateless)
        result = await execute_workflow(workflow, parameters)

        if ctx:
            await ctx.report_progress(100, 100)
            await ctx.info("Workflow execution complete")

        return {
            "success": True,
            "outputs": result["output_data"],
            "trace_path": result["trace_path"]
        }

    except Exception as e:
        error = format_error_for_llm(e)
        if ctx:
            await ctx.error(f"Execution failed: {error}")
        return {
            "success": False,
            "error": error
        }


@mcp.tool()
async def workflow_validate(
    workflow: Annotated[
        str | dict,
        Field(description="Workflow JSON string or dict to validate")
    ]
) -> dict:
    """
    Validate workflow structure without execution.

    Checks workflow for:
    - Valid JSON structure
    - Required fields (ir_version, nodes)
    - Node structure compliance
    - Edge validity
    - Template variable consistency

    Args:
        workflow: Workflow JSON string or dict

    Returns:
        dict: {
            "valid": bool,
            "errors": list[str]      # Validation errors if any
        }
    """
    try:
        errors = await validate_workflow(workflow)

        return {
            "valid": len(errors) == 0,
            "errors": errors
        }

    except Exception as e:
        return {
            "valid": False,
            "errors": [format_error_for_llm(e)]
        }


@mcp.tool()
async def workflow_save(
    name: Annotated[
        str,
        Field(
            pattern=r"^[\w\-]+$",
            min_length=1,
            max_length=100,
            description="Workflow name (alphanumeric, dash, underscore only)"
        )
    ],
    workflow: Annotated[
        dict,
        Field(description="Workflow JSON object to save")
    ]
) -> dict:
    """
    Save workflow to global library (~/.pflow/workflows/).

    Saves workflow with the given name to the global workflow library.
    The workflow is stored as a JSON file in ~/.pflow/workflows/.

    Security:
    - Name is validated to prevent path traversal
    - Only alphanumeric, dash, and underscore allowed
    - No directory separators or special characters

    Args:
        name: Workflow name (validated for security)
        workflow: Workflow JSON object to save

    Returns:
        dict: {
            "success": bool,
            "path": str,             # Full path to saved workflow
            "name": str              # Workflow name
        }

    Errors:
        Returns {"success": false, "error": {...}} on failure
    """
    try:
        # Additional security validation (belt and suspenders)
        validate_workflow_name(name)

        # Save via service layer
        path = await save_workflow(name, workflow)

        return {
            "success": True,
            "path": str(path),
            "name": name
        }

    except Exception as e:
        return {
            "success": False,
            "error": format_error_for_llm(e)
        }


@mcp.tool()
async def workflow_list() -> dict:
    """
    List all saved workflows in the global library.

    Returns list of workflows from ~/.pflow/workflows/ with metadata.

    Returns:
        dict: {
            "success": bool,
            "workflows": list[dict]  # List of workflow metadata
        }

    Each workflow dict contains:
        {
            "name": str,              # Workflow name
            "path": str,              # Full path to file
            "size": int,              # File size in bytes
            "modified": str           # Last modified timestamp
        }
    """
    try:
        workflows = await list_workflows()

        return {
            "success": True,
            "workflows": workflows
        }

    except Exception as e:
        return {
            "success": False,
            "error": format_error_for_llm(e)
        }


@mcp.tool()
async def workflow_discover(
    query: Annotated[
        str,
        Field(description="Natural language description of desired workflow")
    ],
    ctx: Context | None = None
) -> dict:
    """
    Find workflows using LLM-based semantic matching.

    Uses pflow's WorkflowDiscoveryNode to find workflows that match
    the natural language query. This is more powerful than keyword search.

    Args:
        query: Natural language description of what you want to do
        ctx: MCP context for logging (optional)

    Returns:
        dict: {
            "success": bool,
            "matches": list[dict]    # Matching workflows with scores
        }

    Each match contains:
        {
            "name": str,              # Workflow name
            "score": float,           # Relevance score (0-1)
            "description": str,       # Workflow description
            "path": str               # Path to workflow file
        }
    """
    try:
        if ctx:
            await ctx.info(f"Discovering workflows: {query}")

        matches = await discover_workflows(query)

        if ctx:
            await ctx.info(f"Found {len(matches)} matching workflows")

        return {
            "success": True,
            "matches": matches
        }

    except Exception as e:
        error = format_error_for_llm(e)
        if ctx:
            await ctx.error(f"Discovery failed: {error}")
        return {
            "success": False,
            "error": error
        }
```

---

## File 5: tools/registry_tools.py

```python
"""
Registry Tools for pflow MCP Server

This module provides tools for node discovery and execution including
component browsing, searching, describing, listing, and testing nodes.

Tools:
1. registry_discover - Find nodes using LLM-based selection
2. registry_search - Search nodes by pattern
3. registry_describe - Get detailed node specifications
4. registry_list - Browse all available nodes (verbose)
5. registry_run - Execute node independently to test

All tools use fresh Registry instances (stateless).
"""

from typing import Annotated, Any
from pydantic import Field
from fastmcp import Context

from ..server import mcp
from ..services.registry_service import (
    discover_nodes,
    search_nodes,
    describe_node,
    list_nodes,
    execute_node
)
from ..utils.errors import format_error_for_llm


@mcp.tool()
async def registry_discover(
    query: Annotated[
        str,
        Field(description="Natural language description of desired functionality")
    ],
    ctx: Context | None = None
) -> dict:
    """
    Find nodes using LLM-based intelligent selection.

    Uses pflow's ComponentBrowsingNode to find nodes that match the
    natural language query. More powerful than keyword search.

    Args:
        query: Description of what you want to do
        ctx: MCP context for logging (optional)

    Returns:
        dict: {
            "success": bool,
            "nodes": list[dict]       # Matching nodes with metadata
        }
    """
    try:
        if ctx:
            await ctx.info(f"Discovering nodes: {query}")

        nodes = await discover_nodes(query)

        if ctx:
            await ctx.info(f"Found {len(nodes)} matching nodes")

        return {
            "success": True,
            "nodes": nodes
        }

    except Exception as e:
        error = format_error_for_llm(e)
        if ctx:
            await ctx.error(f"Discovery failed: {error}")
        return {
            "success": False,
            "error": error
        }


@mcp.tool()
async def registry_search(
    pattern: Annotated[
        str,
        Field(description="Search pattern for node names/descriptions")
    ]
) -> dict:
    """
    Search nodes by keyword pattern.

    Simple keyword-based search across node names and descriptions.
    Use registry_discover for more intelligent LLM-based matching.

    Args:
        pattern: Search pattern (case-insensitive)

    Returns:
        dict: {
            "success": bool,
            "nodes": list[dict]       # Matching nodes
        }
    """
    try:
        nodes = await search_nodes(pattern)

        return {
            "success": True,
            "nodes": nodes
        }

    except Exception as e:
        return {
            "success": False,
            "error": format_error_for_llm(e)
        }


@mcp.tool()
async def registry_describe(
    node_name: Annotated[
        str,
        Field(description="Name of node to describe")
    ]
) -> dict:
    """
    Get detailed specifications for a specific node.

    Returns complete node metadata including:
    - Description and documentation
    - Input/output keys
    - Parameters and types
    - Example usage

    Args:
        node_name: Name of the node (e.g., "llm", "read-file")

    Returns:
        dict: {
            "success": bool,
            "metadata": dict         # Complete node metadata
        }
    """
    try:
        metadata = await describe_node(node_name)

        return {
            "success": True,
            "metadata": metadata
        }

    except Exception as e:
        return {
            "success": False,
            "error": format_error_for_llm(e)
        }


@mcp.tool()
async def registry_list(
    category: Annotated[
        str | None,
        Field(description="Filter by category (optional)")
    ] = None
) -> dict:
    """
    Browse all available nodes (verbose).

    Lists all nodes in the registry with full metadata.
    Warning: Can be large (~100+ nodes). Use registry_search or
    registry_discover for targeted node finding.

    Args:
        category: Optional category filter (e.g., "file", "llm", "git")

    Returns:
        dict: {
            "success": bool,
            "nodes": list[dict],     # All nodes with metadata
            "total": int             # Total node count
        }
    """
    try:
        nodes = await list_nodes(category)

        return {
            "success": True,
            "nodes": nodes,
            "total": len(nodes)
        }

    except Exception as e:
        return {
            "success": False,
            "error": format_error_for_llm(e)
        }


@mcp.tool()
async def registry_run(
    node_name: Annotated[
        str,
        Field(description="Name of node to execute")
    ],
    parameters: Annotated[
        dict[str, Any],
        Field(description="Node parameters")
    ],
    ctx: Context | None = None
) -> dict:
    """
    Execute a node independently for testing.

    Runs a single node with given parameters to:
    - Test node functionality
    - Discover actual output structure
    - Verify parameters
    - Debug node behavior

    Args:
        node_name: Name of node (e.g., "llm", "read-file")
        parameters: Parameters dict for the node
        ctx: MCP context for logging (optional)

    Returns:
        dict: {
            "success": bool,
            "outputs": dict,         # Node outputs
            "shared_store": dict     # Full shared store after execution
        }
    """
    try:
        if ctx:
            await ctx.info(f"Executing node: {node_name}")

        result = await execute_node(node_name, parameters)

        if ctx:
            await ctx.info("Node execution complete")

        return {
            "success": True,
            "outputs": result["outputs"],
            "shared_store": result["shared_store"]
        }

    except Exception as e:
        error = format_error_for_llm(e)
        if ctx:
            await ctx.error(f"Execution failed: {error}")
        return {
            "success": False,
            "error": error
        }
```

---

## File 6: services/workflow_service.py

```python
"""
Stateless Workflow Service Functions

This module provides async wrappers around pflow's synchronous workflow
operations. All functions create fresh instances of services (stateless).

Agent-optimized defaults:
- Always return JSON
- Always save traces
- Never auto-repair (explicit errors)
- Always normalize workflows (add ir_version, edges)
"""

import asyncio
from pathlib import Path
from typing import Any

# Import pflow core services
from pflow.core.workflow_manager import WorkflowManager
from pflow.runtime.workflow_executor import execute_workflow as core_execute
from pflow.runtime.workflow_validator import validate_workflow_structure
from pflow.planning.nodes import WorkflowDiscoveryNode


async def execute_workflow(
    workflow: str | dict,
    parameters: dict[str, Any] | None = None
) -> dict:
    """
    Execute workflow with agent-optimized defaults.

    Creates fresh WorkflowManager instance - stateless operation.

    Args:
        workflow: Workflow JSON, dict, or name
        parameters: Input parameters

    Returns:
        dict: {
            "output_data": dict,
            "trace_path": str
        }
    """
    # Fresh instances (stateless)
    manager = WorkflowManager()

    # Normalize parameters
    params = parameters or {}

    # Execute in thread pool (pflow's execute is sync)
    result = await asyncio.to_thread(
        core_execute,
        workflow=workflow,
        parameters=params,
        trace=True,              # Always trace for agents
        json_output=True,        # Always JSON for agents
        auto_repair=False,       # No auto-repair for agents
        normalize=True           # Add ir_version, edges
    )

    return result


async def validate_workflow(workflow: str | dict) -> list[str]:
    """
    Validate workflow structure.

    Returns list of validation errors (empty if valid).
    """
    # Execute validation in thread pool
    errors = await asyncio.to_thread(
        validate_workflow_structure,
        workflow
    )

    return errors


async def save_workflow(name: str, workflow: dict) -> Path:
    """
    Save workflow to library.

    Creates fresh WorkflowManager - stateless.
    """
    manager = WorkflowManager()

    # Save in thread pool
    path = await asyncio.to_thread(
        manager.save,
        name,
        workflow
    )

    return path


async def list_workflows() -> list[dict]:
    """
    List all saved workflows.

    Returns list of workflow metadata dicts.
    """
    manager = WorkflowManager()

    # List in thread pool
    workflows = await asyncio.to_thread(
        manager.list_all
    )

    return workflows


async def discover_workflows(query: str) -> list[dict]:
    """
    Discover workflows using LLM matching.

    Uses WorkflowDiscoveryNode for intelligent matching.
    """
    # Fresh instances
    node = WorkflowDiscoveryNode()
    manager = WorkflowManager()

    # Prepare shared store
    shared = {
        "user_input": query,
        "workflow_manager": manager  # REQUIRED!
    }

    # Run in thread pool (node.run is sync)
    await asyncio.to_thread(
        node.run,
        shared
    )

    # Extract result
    matches = shared.get("discovery_result", [])

    return matches
```

---

## File 7: utils/errors.py

```python
"""
Error Formatting Utilities

Formats exceptions for LLM visibility with user-friendly messages.
"""


def format_error_for_llm(error: Exception) -> dict:
    """
    Format exception for LLM consumption.

    Converts Python exceptions to structured dicts that LLMs can
    understand and reason about.

    Args:
        error: Python exception

    Returns:
        dict: {
            "type": str,         # Error type
            "message": str,      # User-friendly message
            "details": str       # Additional context
        }
    """
    error_type = type(error).__name__

    # Determine error category
    if error_type in ["ValidationError", "ValueError"]:
        category = "validation"
    elif error_type in ["FileNotFoundError", "IOError"]:
        category = "file"
    elif error_type in ["KeyError", "AttributeError"]:
        category = "data"
    elif error_type in ["TimeoutError", "ConnectionError"]:
        category = "network"
    else:
        category = "general"

    # Extract message (first line only, no stack trace)
    message = str(error).split('\n')[0]

    return {
        "type": error_type,
        "category": category,
        "message": message,
        "details": str(error)[:500]  # Limit details
    }


class SecurityError(Exception):
    """Raised for security violations (path traversal, etc.)."""
    pass
```

---

## File 8: utils/validation.py

```python
"""
Input Validation Utilities

Security-focused validation for user inputs.
"""

from .errors import SecurityError


def validate_workflow_name(name: str) -> None:
    """
    Validate workflow name for security.

    Prevents path traversal attacks and ensures safe file names.

    Args:
        name: Workflow name to validate

    Raises:
        SecurityError: If name contains dangerous characters
        ValueError: If name is invalid format
    """
    # Already validated by Pydantic pattern, but double-check
    if not name:
        raise ValueError("Workflow name cannot be empty")

    # Check for path traversal attempts
    dangerous_chars = ['/', '\\', '..', '~', '*', '?', '<', '>', '|']
    for char in dangerous_chars:
        if char in name:
            raise SecurityError(
                f"Invalid character '{char}' in workflow name. "
                f"Only alphanumeric, dash, and underscore allowed."
            )

    # Additional check for hidden files
    if name.startswith('.'):
        raise SecurityError("Workflow name cannot start with '.'")


def validate_workflow_json(workflow: dict) -> list[str]:
    """
    Validate workflow JSON structure.

    Args:
        workflow: Workflow dict to validate

    Returns:
        list[str]: Validation errors (empty if valid)
    """
    errors = []

    # Check required fields
    if "nodes" not in workflow:
        errors.append("Missing required field: 'nodes'")

    if "ir_version" not in workflow:
        # This is OK - we can add it
        pass

    # Validate nodes structure
    if "nodes" in workflow:
        if not isinstance(workflow["nodes"], list):
            errors.append("'nodes' must be a list")
        elif len(workflow["nodes"]) == 0:
            errors.append("'nodes' cannot be empty")

    return errors
```

---

## Usage Examples

### Starting the Server

```bash
# Run directly
python -m pflow.mcp_server.main

# Or via CLI (once integrated)
pflow serve mcp
```

### Testing with FastMCP Client

```python
import asyncio
from fastmcp.testing import Client
from pflow.mcp_server import mcp

async def test_tools():
    async with Client(mcp) as client:
        # List all tools
        tools = await client.list_tools()
        print(f"Registered {len(tools)} tools:")
        for tool in tools:
            print(f"  - {tool.name}")

        # Test workflow_execute
        result = await client.call_tool(
            "workflow_execute",
            {
                "workflow": {"nodes": [...], "edges": [...]},
                "parameters": {"input": "test"}
            }
        )
        print(f"Result: {result.data}")

asyncio.run(test_tools())
```

### Integration with CLI

```python
# In src/pflow/cli/main.py

@cli.group()
def serve():
    """Start pflow servers."""
    pass

@serve.command()
def mcp():
    """Start MCP server with stdio transport."""
    from pflow.mcp_server import mcp
    mcp.run()
```

---

## Testing Template

```python
"""
Test Workflow Tools

Tests for all workflow lifecycle tools.
"""

import pytest
from fastmcp import FastMCP
from fastmcp.testing import Client


@pytest.fixture
def test_server():
    """Provide fresh server instance."""
    return FastMCP("test-server")


@pytest.mark.asyncio
async def test_workflow_execute(test_server):
    """Test workflow execution tool."""
    # Import tool module to register tools
    from pflow.mcp_server.tools import workflow_tools

    async with Client(test_server) as client:
        result = await client.call_tool(
            "workflow_execute",
            {
                "workflow": {
                    "ir_version": "1.0",
                    "nodes": [...],
                    "edges": [...]
                },
                "parameters": {}
            }
        )

        assert result.data["success"] is True
        assert "outputs" in result.data
        assert "trace_path" in result.data


@pytest.mark.asyncio
async def test_workflow_validate(test_server):
    """Test workflow validation tool."""
    from pflow.mcp_server.tools import workflow_tools

    async with Client(test_server) as client:
        # Test valid workflow
        result = await client.call_tool(
            "workflow_validate",
            {
                "workflow": {
                    "ir_version": "1.0",
                    "nodes": [...],
                    "edges": [...]
                }
            }
        )

        assert result.data["valid"] is True
        assert len(result.data["errors"]) == 0


# ... more tests
```

---

## Notes

1. **All templates are production-ready** - Just fill in the actual pflow integration calls
2. **Service layer is key** - Enforces stateless operation
3. **Error handling is consistent** - All tools return `{"success": bool, ...}`
4. **Type hints are complete** - FastMCP uses these for schemas
5. **Docstrings are detailed** - These become tool descriptions for AI
6. **Security is built-in** - Validation and error formatting included
7. **Testing is straightforward** - Use FastMCP's in-memory client

**Next Step**: Copy these templates to `src/pflow/mcp_server/` and fill in the actual implementation details by integrating with pflow's existing services.
