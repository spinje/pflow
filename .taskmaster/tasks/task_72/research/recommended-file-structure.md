# Recommended File Structure for pflow MCP Server

## Visual Structure

```
src/pflow/mcp_server/
│
├── __init__.py                          # Package exports
│   └── Exports: mcp, main entry point
│
├── server.py                            # 🎯 CENTRAL SERVER INSTANCE
│   └── FastMCP("pflow", version="0.1.0")
│
├── main.py                              # 🚀 ENTRY POINT
│   ├── Imports: mcp from server.py
│   ├── Imports: tools package (triggers registration)
│   └── Runs: mcp.run() for stdio transport
│
├── tools/                               # 📦 TOOL DEFINITIONS (4 files)
│   ├── __init__.py
│   │   └── Auto-imports all tool modules
│   │
│   ├── workflow_tools.py                # 6 workflow tools
│   │   ├── @mcp.tool workflow_execute
│   │   ├── @mcp.tool workflow_validate
│   │   ├── @mcp.tool workflow_save
│   │   ├── @mcp.tool workflow_list
│   │   └── @mcp.tool workflow_discover
│   │
│   ├── registry_tools.py                # 5 registry tools
│   │   ├── @mcp.tool registry_discover
│   │   ├── @mcp.tool registry_search
│   │   ├── @mcp.tool registry_describe
│   │   ├── @mcp.tool registry_list
│   │   └── @mcp.tool registry_run
│   │
│   ├── settings_tools.py                # 2 settings tools
│   │   ├── @mcp.tool settings_get
│   │   └── @mcp.tool settings_set
│   │
│   └── trace_tools.py                   # 1 trace tool
│       └── @mcp.tool trace_read
│
├── services/                            # 🔧 SERVICE LAYER (Stateless wrappers)
│   ├── __init__.py
│   │
│   ├── workflow_service.py              # WorkflowManager integration
│   │   ├── async execute_workflow()    # Wraps core execute
│   │   ├── async validate_workflow()   # Wraps validator
│   │   ├── async save_workflow()       # Wraps manager.save
│   │   ├── async list_workflows()      # Wraps manager.list
│   │   └── async discover_workflows()  # Wraps planning node
│   │
│   ├── registry_service.py              # Registry integration
│   │   ├── async discover_nodes()      # Uses ComponentBrowsingNode
│   │   ├── async search_nodes()        # Wraps registry.search
│   │   ├── async describe_node()       # Wraps registry.get_metadata
│   │   ├── async list_nodes()          # Wraps registry.list_all
│   │   └── async execute_node()        # Wraps registry.execute
│   │
│   └── settings_service.py              # Settings file access
│       ├── async get_setting()         # Read from settings.json
│       └── async set_setting()         # Write to settings.json
│
└── utils/                               # 🛠️ SHARED UTILITIES
    ├── __init__.py
    │
    ├── errors.py                        # Error formatting
    │   ├── format_error_for_llm()      # Makes errors LLM-visible
    │   └── class SecurityError(Exception)
    │
    └── validation.py                    # Input validation
        ├── validate_workflow_name()    # Path traversal prevention
        └── validate_workflow_json()    # JSON schema validation
```

## Data Flow

```
┌─────────────────┐
│   MCP Client    │  (Claude Code, Cursor, etc.)
│   (AI Agent)    │
└────────┬────────┘
         │
         │ 1. call_tool("workflow_execute", {...})
         │
         ▼
┌─────────────────────────────────────────────┐
│         FastMCP Server (stdio)               │
│                                              │
│  ┌──────────────────────────────────────┐  │
│  │  server.py (mcp instance)            │  │
│  │  Routes request to registered tool   │  │
│  └──────────────┬───────────────────────┘  │
│                 │                            │
│                 │ 2. Calls decorated function│
│                 ▼                            │
│  ┌──────────────────────────────────────┐  │
│  │  tools/workflow_tools.py             │  │
│  │  @mcp.tool workflow_execute()        │  │
│  │                                       │  │
│  │  ┌────────────────────────────────┐  │  │
│  │  │ 3. Fresh instances (stateless) │  │  │
│  │  │    manager = WorkflowManager() │  │  │
│  │  │    registry = Registry()       │  │  │
│  │  └────────────────────────────────┘  │  │
│  │                                       │  │
│  │  ┌────────────────────────────────┐  │  │
│  │  │ 4. Call service layer          │  │  │
│  │  │    await execute_workflow()    │  │  │
│  │  └────────────┬───────────────────┘  │  │
│  └───────────────┼───────────────────────┘  │
│                  │                           │
│                  │ 5. Service wraps sync code│
│                  ▼                           │
│  ┌──────────────────────────────────────┐  │
│  │  services/workflow_service.py        │  │
│  │  async execute_workflow()            │  │
│  │                                       │  │
│  │  ┌────────────────────────────────┐  │  │
│  │  │ 6. asyncio.to_thread() wrapper │  │  │
│  │  │    Converts sync → async       │  │  │
│  │  └────────────┬───────────────────┘  │  │
│  └───────────────┼───────────────────────┘  │
│                  │                           │
│                  │ 7. Calls pflow core       │
│                  ▼                           │
│  ┌──────────────────────────────────────┐  │
│  │  pflow/runtime/workflow_executor.py  │  │
│  │  execute_workflow() - SYNC           │  │
│  │  ├── Load workflow                   │  │
│  │  ├── Validate                        │  │
│  │  ├── Compile to PocketFlow          │  │
│  │  ├── Execute                         │  │
│  │  └── Return result                   │  │
│  └────────────┬─────────────────────────┘  │
│               │                             │
│               │ 8. Result bubbles back up   │
│               ▼                             │
│  ┌──────────────────────────────────────┐  │
│  │  Return structured JSON to tool      │  │
│  │  {                                    │  │
│  │    "success": true,                   │  │
│  │    "outputs": {...},                  │  │
│  │    "trace_path": "..."                │  │
│  │  }                                    │  │
│  └──────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
         │
         │ 9. FastMCP formats as MCP response
         ▼
┌─────────────────┐
│   MCP Client    │  Receives structured result
│   (AI Agent)    │
└─────────────────┘
```

## Import Flow at Startup

```
1. Python starts: python -m pflow.mcp_server.main
   │
   ▼
2. main.py imports:
   from .server import mcp        # Creates FastMCP instance
   from . import tools             # Imports tools package
   │
   ▼
3. tools/__init__.py imports:
   from . import workflow_tools    # Imports workflow_tools.py
   from . import registry_tools    # Imports registry_tools.py
   from . import settings_tools    # Imports settings_tools.py
   from . import trace_tools       # Imports trace_tools.py
   │
   ▼
4. Each tool module imports:
   from ..server import mcp        # Gets the FastMCP instance
   │
   ▼
5. Each @mcp.tool decorator registers the tool:
   @mcp.tool()                     # Registers at import time
   async def workflow_execute(...):
   │
   ▼
6. After all imports, main.py runs:
   mcp.run()                       # Start stdio server with all tools
```

## Tool File Example: workflow_tools.py

```python
"""
Workflow Tools for pflow MCP Server

This module provides tools for workflow lifecycle management including
execution, validation, saving, listing, and discovery.

Tools:
- workflow_execute: Execute workflows with JSON output and traces
- workflow_validate: Validate workflow structure without execution
- workflow_save: Save workflow to global library
- workflow_list: List all saved workflows
- workflow_discover: Find workflows using LLM matching

All tools use agent-optimized defaults:
- JSON output (always)
- Traces enabled (always)
- No auto-repair (explicit errors)
- Fresh service instances (stateless)
"""

from typing import Annotated
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
        dict | None,
        Field(description="Input parameters for workflow")
    ] = None,
    ctx: Context | None = None
) -> dict:
    """
    Execute a pflow workflow with agent-optimized defaults.

    Returns:
        dict: {
            "success": bool,
            "outputs": dict,          # Workflow outputs
            "trace_path": str         # Path to execution trace
        }

    Errors:
        Returns {"success": false, "error": {...}} on failure
    """
    try:
        if ctx:
            await ctx.info(f"Starting workflow execution: {workflow}")
            await ctx.report_progress(10, 100)

        # Call service layer (fresh instances, stateless)
        result = await execute_workflow(workflow, parameters)

        if ctx:
            await ctx.report_progress(100, 100)
            await ctx.info("Workflow execution complete")

        return {
            "success": True,
            "outputs": result.output_data,
            "trace_path": result.trace_path
        }

    except Exception as e:
        error = format_error_for_llm(e)
        if ctx:
            await ctx.error(f"Execution failed: {error}")
        return {"success": False, "error": error}


@mcp.tool()
async def workflow_validate(
    workflow: Annotated[
        str | dict,
        Field(description="Workflow JSON string or dict to validate")
    ]
) -> dict:
    """
    Validate workflow structure without execution.

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

    Returns:
        dict: {
            "success": bool,
            "path": str,             # Full path to saved workflow
            "name": str              # Workflow name
        }
    """
    try:
        # Additional security validation
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


# ... workflow_list, workflow_discover follow similar pattern
```

## Service Layer Example: workflow_service.py

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
    parameters: dict | None = None
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


# ... list_workflows, discover_workflows follow similar pattern
```

## Why This Structure?

### ✅ Advantages

1. **Clear Domain Boundaries**
   - Workflow operations in one file
   - Registry operations in another
   - Easy to find related tools

2. **Manageable File Sizes**
   - ~150-200 lines per tool file
   - Easy to read and navigate
   - Not overwhelming

3. **Stateless by Design**
   - Service layer enforces fresh instances
   - No shared state between requests
   - Prevents stale data bugs

4. **Testable**
   - Service layer can be unit tested
   - Tools can be integration tested
   - Clear separation of concerns

5. **Scalable**
   - Easy to add new tools (just add to appropriate file)
   - Can split files if they grow
   - Follows production patterns

6. **Team-Friendly**
   - Different devs can work on different domains
   - Minimal merge conflicts
   - Clear ownership

### ❌ Alternatives We Rejected

**Single File (13 tools)**:
- ❌ 600-800 lines (too large)
- ❌ Hard to navigate
- ❌ Merge conflict nightmare
- ❌ Poor organization

**13 Separate Files**:
- ❌ Too granular (over-engineering)
- ❌ Too many imports
- ❌ Hard to see relationships
- ❌ Unnecessary complexity

**Class-Based Organization**:
- ❌ Adds boilerplate (init, self)
- ❌ Tempts shared state (bad for stateless)
- ❌ Less Pythonic for simple tools
- ❌ No clear benefit for stateless functions

## Migration from Current State

If you have existing tool implementations, migration is simple:

1. **Create structure**:
   ```bash
   mkdir -p src/pflow/mcp_server/{tools,services,utils}
   touch src/pflow/mcp_server/{__init__.py,server.py,main.py}
   touch src/pflow/mcp_server/tools/__init__.py
   ```

2. **Create server.py**:
   ```python
   from fastmcp import FastMCP
   mcp = FastMCP("pflow", version="0.1.0")
   ```

3. **Move tools** to appropriate files under `tools/`

4. **Update imports** in each tool file:
   ```python
   from ..server import mcp
   ```

5. **Create tools/__init__.py**:
   ```python
   from . import workflow_tools
   from . import registry_tools
   from . import settings_tools
   from . import trace_tools
   ```

6. **Create main.py**:
   ```python
   from .server import mcp
   from . import tools

   if __name__ == "__main__":
       mcp.run()
   ```

## Testing the Structure

```bash
# Run all MCP server tests
pytest tests/test_mcp_server/ -v

# Run specific domain tests
pytest tests/test_mcp_server/test_tools/test_workflow_tools.py -v

# Run with coverage
pytest tests/test_mcp_server/ --cov=pflow.mcp_server --cov-report=html

# Test server startup
python -m pflow.mcp_server.main

# Test with MCP client
python -c "
from fastmcp.testing import Client
from pflow.mcp_server import mcp
import asyncio

async def test():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        print(f'Registered {len(tools)} tools')
        for tool in tools:
            print(f'  - {tool.name}')

asyncio.run(test())
"
```

## Conclusion

This structure provides:
- ✅ **Clarity**: Clear domain organization
- ✅ **Maintainability**: Manageable file sizes
- ✅ **Testability**: Clear test structure
- ✅ **Scalability**: Easy to extend
- ✅ **Best Practices**: Follows production patterns
- ✅ **Stateless**: Enforced by service layer
- ✅ **Performance**: No overhead vs. alternatives

**This is the recommended structure for implementing the pflow MCP server.**
