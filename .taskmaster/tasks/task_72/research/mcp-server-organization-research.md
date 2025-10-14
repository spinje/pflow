# MCP Server Tool Organization Research

**Date**: 2025-10-11
**Researcher**: Claude Code
**Purpose**: Determine best practices for organizing 13 pflow MCP tools across files

## Executive Summary

After analyzing existing research files, real-world MCP server implementations on GitHub, and FastMCP best practices, I've identified clear patterns for organizing MCP server tools. The recommendation is to **use a hybrid modular approach** with tools organized by functional domain into separate files under a `tools/` directory.

## Key Findings

### 1. FastMCP Decorator Patterns with Multiple Files

#### The Central Server Pattern (Recommended)

FastMCP's best practice is to create a **centralized server instance** that is imported by tool modules:

```python
# src/pflow/mcp_server/server.py
from fastmcp import FastMCP

# Single source of truth - exported for tool modules
mcp = FastMCP(
    name="pflow",
    version="0.1.0",
    instructions="Exposes pflow workflow building and execution capabilities"
)
```

```python
# src/pflow/mcp_server/tools/workflow_tools.py
from ..server import mcp
from typing import Annotated
from pydantic import Field

@mcp.tool()
async def workflow_execute(
    workflow: Annotated[str | dict, Field(description="Workflow JSON or name")],
    parameters: dict | None = None
) -> dict:
    """Execute a pflow workflow."""
    # Implementation
    return {"success": True}

@mcp.tool()
async def workflow_validate(workflow: str | dict) -> dict:
    """Validate workflow structure."""
    # Implementation
    return {"valid": True}
```

```python
# src/pflow/mcp_server/main.py
from .server import mcp

# Import tool modules to trigger decorator registration
from . import tools  # This triggers all tool imports

if __name__ == "__main__":
    mcp.run()
```

**Key Insight**: Tools are registered **at import time** when Python executes the decorator. The main entry point just needs to ensure tool modules are imported.

### 2. Alternative Pattern: Instance Method Registration

From the research files (`tool-implementation.md`), there's an alternative pattern using class-based organization:

```python
# ❌ WRONG - Don't decorate instance methods directly
class WorkflowTools:
    @mcp.tool  # This breaks method binding
    def workflow_execute(self, workflow: str) -> dict:
        pass

# ✅ CORRECT - Register after instance creation
class WorkflowTools:
    def __init__(self, mcp_instance: FastMCP):
        self.mcp = mcp_instance
        # Register instance methods as tools
        self.mcp.tool(self.workflow_execute)
        self.mcp.tool(self.workflow_validate)

    def workflow_execute(self, workflow: str) -> dict:
        """Execute workflow."""
        return {"success": True}

    def workflow_validate(self, workflow: str) -> dict:
        """Validate workflow."""
        return {"valid": True}

# Usage
workflow_tools = WorkflowTools(mcp)
```

**Trade-offs**:
- **Class-based**: Better for tools that share state/dependencies, more OOP-style
- **Module-based**: Simpler, more Pythonic, less boilerplate, preferred for stateless tools

### 3. Real-World Examples

#### FHIR MCP Server (Production Example)
Uses **router composition** with separate modules:
```
app/
├── mcp/
│   └── v1/
│       ├── mcp.py           # Main router composition
│       └── tools/
│           ├── patient.py
│           ├── observation.py
│           ├── encounter.py
│           └── ...
```

Pattern: Each resource type has its own tool file, imported and mounted in central router.

#### GitHub MCP Server (Official Production)
Organizes tools by **functional domain**:
- Actions toolset (workflow runs, jobs, logs)
- Code Security toolset (vulnerability scanning, advisories)
- Issues toolset (create, update, list issues)
- Pull Requests toolset (create, review, merge PRs)
- Repositories toolset (manage repos, branches, releases)

Pattern: **Toolsets** group related operations, with configuration to enable/disable entire toolsets.

#### Mix Server Example (Tutorial Pattern)
```
mix_server/
├── data/              # Sample data files
├── tools/             # Tool definitions
│   ├── csv_tools.py
│   └── parquet_tools.py
├── utils/             # Shared utilities
├── server.py          # Server instance
├── main.py            # Entry point
└── README.md
```

Pattern: Simple directory structure with tools by file type/domain.

### 4. Performance Implications

**No performance difference** between single file vs. multiple files:
- Tools are registered at import time (one-time cost)
- Runtime execution is identical regardless of file organization
- Python's module caching means imports are cheap
- Network transport overhead dominates any file structure overhead

**Maintainability Impact**:
- Multiple files: Easier to navigate, better separation of concerns
- Single file: Simpler for small servers (<10 tools), but becomes unwieldy at scale
- Best practice: Organize by domain/functionality, not arbitrarily

### 5. Import Patterns

#### Pattern 1: Explicit Imports (Recommended)
```python
# main.py
from .server import mcp

# Import specific tool modules
from .tools import workflow_tools
from .tools import registry_tools
from .tools import settings_tools

if __name__ == "__main__":
    mcp.run()
```

**Pros**: Clear dependencies, IDE-friendly, explicit control
**Cons**: Must update imports when adding new tool files

#### Pattern 2: Package Init Import
```python
# tools/__init__.py
from . import workflow_tools
from . import registry_tools
from . import settings_tools

# main.py
from .server import mcp
from . import tools  # Triggers all tools via __init__.py

if __name__ == "__main__":
    mcp.run()
```

**Pros**: Automatic import of all tools in package
**Cons**: Less explicit, harder to see dependencies

#### Pattern 3: Wildcard Import (Not Recommended)
```python
# main.py
from .server import mcp
from .tools import *  # Import everything

if __name__ == "__main__":
    mcp.run()
```

**Pros**: Very simple
**Cons**: "Hacky", violates Python best practices, linting errors, unclear namespace

**Recommendation**: Use Pattern 2 (Package Init) for clean, maintainable imports.

### 6. Tool Grouping Strategies

Based on real-world servers, there are three main grouping strategies:

#### Strategy A: By Resource/Entity Type
Used by: FHIR server, database servers
```
tools/
├── patient_tools.py      # All patient operations
├── observation_tools.py  # All observation operations
└── encounter_tools.py    # All encounter operations
```

#### Strategy B: By Operation Type
Used by: File servers, simple utilities
```
tools/
├── read_tools.py    # All read operations
├── write_tools.py   # All write operations
└── delete_tools.py  # All delete operations
```

#### Strategy C: By Functional Domain
Used by: GitHub MCP server, AWS servers, complex platforms
```
tools/
├── workflow_tools.py   # Workflow lifecycle (execute, save, list, validate)
├── registry_tools.py   # Node discovery and execution
├── settings_tools.py   # Configuration management
└── trace_tools.py      # Debugging and tracing
```

**For pflow**: Strategy C (Functional Domain) is the best fit because our 13 tools naturally group into:
- **Workflow domain** (6 tools): execute, validate, save, list, discover
- **Registry domain** (5 tools): discover, search, describe, list, run
- **Settings domain** (2 tools): get, set
- **Trace domain** (1 tool): read (could be in utilities)

### 7. Recommended File Structure for pflow

```
src/pflow/mcp_server/
├── __init__.py                    # Package init, exports main entry point
├── server.py                      # FastMCP server instance (central)
├── main.py                        # Entry point with mcp.run()
├── tools/                         # Tool implementations
│   ├── __init__.py               # Auto-imports all tool modules
│   ├── workflow_tools.py         # 6 workflow tools
│   ├── registry_tools.py         # 5 registry tools
│   ├── settings_tools.py         # 2 settings tools
│   └── trace_tools.py            # 1 trace tool (or could merge into utilities)
├── services/                      # Service layer (stateless wrappers)
│   ├── __init__.py
│   ├── workflow_service.py       # WorkflowManager integration
│   ├── registry_service.py       # Registry integration
│   └── settings_service.py       # Settings file access
└── utils/                         # Shared utilities
    ├── __init__.py
    ├── errors.py                 # Error formatting
    └── validation.py             # Input validation
```

**Rationale**:
1. **`server.py`**: Single source of truth for FastMCP instance
2. **`tools/`**: One file per functional domain (4 files for 13 tools)
3. **`services/`**: Stateless service wrappers ensure fresh instances per request
4. **`utils/`**: Shared error handling, validation, formatting
5. **`main.py`**: Simple entry point that imports tools and calls `mcp.run()`

### 8. Tool Organization Within Files

Each tool file should follow this structure:

```python
"""
Workflow Tools for pflow MCP Server

Tools for workflow lifecycle management:
- workflow_execute: Execute workflows with JSON output
- workflow_validate: Validate workflow structure
- workflow_save: Save workflow to library
- workflow_list: List saved workflows
- workflow_discover: Find workflows using LLM
"""

from typing import Annotated
from pydantic import Field
from fastmcp import Context

from ..server import mcp
from ..services.workflow_service import execute_workflow, save_workflow, list_workflows

# Tool 1: workflow_execute
@mcp.tool()
async def workflow_execute(
    workflow: Annotated[str | dict, Field(description="Workflow JSON or name")],
    parameters: Annotated[dict | None, Field(description="Input parameters")] = None,
    ctx: Context | None = None
) -> dict:
    """
    Execute a pflow workflow with agent-optimized defaults.

    Returns structured JSON with outputs and execution trace.
    """
    if ctx:
        await ctx.info("Starting workflow execution")

    # Fresh service instance (stateless)
    result = await execute_workflow(workflow, parameters)

    if ctx:
        await ctx.info("Workflow execution complete")

    return {
        "success": True,
        "outputs": result.output_data,
        "trace_path": result.trace_path
    }

# Tool 2: workflow_validate
@mcp.tool()
async def workflow_validate(
    workflow: Annotated[str | dict, Field(description="Workflow to validate")]
) -> dict:
    """Validate workflow structure without execution."""
    # Implementation
    pass

# ... more tools
```

**Key patterns**:
- Module docstring explains all tools in file
- Imports at top (server, services, types)
- One tool definition per decorator
- Clear tool docstrings (become descriptions)
- Type annotations with Field for better schemas
- Context parameter for logging/progress (optional)

### 9. Testing Organization

Tests should mirror the tool organization:

```
tests/test_mcp_server/
├── __init__.py
├── test_server_setup.py          # Server initialization tests
├── test_tools/
│   ├── __init__.py
│   ├── test_workflow_tools.py    # Tests for all 6 workflow tools
│   ├── test_registry_tools.py    # Tests for all 5 registry tools
│   ├── test_settings_tools.py    # Tests for 2 settings tools
│   └── test_trace_tools.py       # Tests for trace tool
├── test_services/
│   ├── test_workflow_service.py
│   ├── test_registry_service.py
│   └── test_settings_service.py
└── test_integration/
    └── test_full_workflow_cycle.py  # End-to-end tests
```

**Testing pattern from FastMCP docs**:
```python
import pytest
from fastmcp import FastMCP
from fastmcp.testing import Client

@pytest.mark.asyncio
async def test_workflow_execute():
    """Test workflow execution tool."""
    # Fresh server for isolated test
    mcp = FastMCP("test-server")

    # Import tool module to register tools
    from pflow.mcp_server.tools import workflow_tools

    async with Client(mcp) as client:
        result = await client.call_tool(
            "workflow_execute",
            {"workflow": "test-workflow.json"}
        )

        assert result.data["success"] is True
```

### 10. Security and Best Practices

#### Stateless Operation (Critical)
```python
# ✅ CORRECT - Fresh instance per request
async def workflow_execute(workflow: str, parameters: dict = None) -> dict:
    manager = WorkflowManager()  # Fresh instance
    registry = Registry()         # Fresh instance
    result = execute_workflow(manager, registry, workflow, parameters)
    return result

# ❌ WRONG - Shared state (will go stale)
class ToolProvider:
    def __init__(self):
        self.manager = WorkflowManager()  # Shared across requests!

    def workflow_execute(self, workflow: str) -> dict:
        # Using stale manager - BAD!
        return self.manager.execute(workflow)
```

#### Input Validation
```python
from pydantic import Field, validator

@mcp.tool()
async def workflow_save(
    name: Annotated[str, Field(
        pattern=r"^[\w\-]+$",
        min_length=1,
        max_length=100,
        description="Workflow name (alphanumeric, dash, underscore)"
    )],
    workflow: dict
) -> dict:
    """Save workflow with validated name."""
    # Pydantic validates 'name' automatically
    # Additional security check
    if any(c in name for c in ['/', '\\', '..', '~']):
        raise ValueError(f"Invalid characters in name: {name}")

    # Save workflow
    return {"saved": True}
```

#### Error Formatting
```python
from fastmcp import ToolError

@mcp.tool()
async def workflow_execute(workflow: str) -> dict:
    """Execute workflow with proper error handling."""
    try:
        result = execute_workflow_internal(workflow)
        return {"success": True, "result": result}
    except ValidationError as e:
        # User-friendly error (visible to LLM)
        raise ToolError(f"Invalid workflow: {e}")
    except Exception as e:
        # Generic error (hide internals)
        raise ToolError(f"Execution failed: {str(e)}")
```

## Recommendations for pflow MCP Server

### Primary Recommendation: Modular Organization

**Use 4 tool files organized by functional domain**:

1. **`workflow_tools.py`** (6 tools):
   - `workflow_execute`
   - `workflow_validate`
   - `workflow_save`
   - `workflow_list`
   - `workflow_discover`

2. **`registry_tools.py`** (5 tools):
   - `registry_discover`
   - `registry_search`
   - `registry_describe`
   - `registry_list`
   - `registry_run`

3. **`settings_tools.py`** (2 tools):
   - `settings_get`
   - `settings_set`

4. **`trace_tools.py`** (1 tool):
   - `trace_read`

### Import Pattern: Package Init

**`tools/__init__.py`**:
```python
"""
pflow MCP Server Tools

Imports all tool modules to trigger decorator registration.
"""

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

**`main.py`**:
```python
"""pflow MCP Server Entry Point"""

from .server import mcp
from . import tools  # Triggers all tool imports via __init__.py

if __name__ == "__main__":
    mcp.run()
```

### Service Layer Pattern

Create a **service layer** that provides stateless functions wrapping pflow's core services:

```python
# services/workflow_service.py
"""Stateless workflow service functions for MCP tools."""

from pflow.core.workflow_manager import WorkflowManager
from pflow.runtime.workflow_executor import execute_workflow as core_execute
import asyncio

async def execute_workflow(workflow: str | dict, parameters: dict | None) -> dict:
    """
    Execute workflow with agent-optimized defaults.

    Creates fresh instances - stateless operation.
    """
    # Fresh WorkflowManager instance
    manager = WorkflowManager()

    # Execute in thread pool (pflow's execute is sync)
    result = await asyncio.to_thread(
        core_execute,
        workflow,
        parameters or {},
        trace=True,        # Always trace for agents
        json_output=True,  # Always JSON for agents
        auto_repair=False  # No auto-repair for agents
    )

    return result
```

**Benefits**:
1. **Stateless**: Fresh instances per request (no stale state)
2. **Agent defaults**: Built into service layer (no parameters needed)
3. **Async wrapping**: Converts sync pflow code to async for FastMCP
4. **Testable**: Services can be unit tested independently
5. **Decoupled**: Tools don't directly import pflow internals

### Why This Approach?

**1. Maintainability**:
- 4 files is manageable (not 13, not 1)
- Clear domain boundaries
- Easy to find tools by purpose
- Each file is focused (~150-200 lines)

**2. Performance**:
- No performance penalty vs. single file
- Import overhead is negligible
- Tools register once at startup

**3. Scalability**:
- Easy to add new tools (just add to appropriate file)
- Can split files further if needed
- Follows production MCP server patterns

**4. Team Collaboration**:
- Different developers can work on different tool files
- Merge conflicts minimized
- Clear ownership boundaries

**5. Testing**:
- One test file per tool file
- Easy to run tests for specific domains
- Clear test organization

### Alternative: Single File (Not Recommended)

For completeness, here's why single file doesn't work for 13 tools:

**Problems**:
- File becomes 600-800 lines (unwieldy)
- Hard to navigate
- Merge conflicts in team settings
- All tools in one namespace
- Difficult to maintain over time

**When single file works**:
- <5 simple tools
- Personal projects
- Proof-of-concept servers
- Quick prototypes

**pflow has 13 tools across 3-4 domains → modular approach is correct.**

## Conclusion

Based on comprehensive research of FastMCP documentation, real-world production MCP servers (GitHub, FHIR, AWS), and Python best practices:

**Recommended approach for pflow**:
1. ✅ **Modular organization**: 4 files by functional domain
2. ✅ **Central server pattern**: Single `server.py` with exported FastMCP instance
3. ✅ **Package init imports**: Clean, automatic tool registration
4. ✅ **Service layer**: Stateless wrappers for pflow services
5. ✅ **Standard structure**: `tools/`, `services/`, `utils/` directories
6. ✅ **Instance methods**: NOT needed (module-level functions are simpler)

**Avoid**:
1. ❌ Single file with 13 tools (too large)
2. ❌ 13 separate files (too granular)
3. ❌ Wildcard imports (non-Pythonic)
4. ❌ Shared state between requests (stateless is critical)
5. ❌ Class-based organization without clear benefit (adds complexity)

This approach balances **simplicity, maintainability, performance, and scalability** while following established patterns from production MCP servers.

## References

- FastMCP Documentation: https://gofastmcp.com/servers/tools
- FastMCP GitHub: https://github.com/jlowin/fastmcp
- GitHub MCP Server: https://github.com/github/github-mcp-server
- FHIR MCP Server: https://github.com/the-momentum/fhir-mcp-server
- MCP Official Servers: https://github.com/modelcontextprotocol/servers
- FastMCP Discussion #948: Modular tools organization
- FastMCP Discussion #1312: Multiple tool files best practices
- Research files in `.taskmaster/tasks/task_72/research/mcp/`
