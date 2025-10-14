# MCP Server Organization Research - Executive Summary

**Date**: 2025-10-11
**Question**: How should MCP servers organize their tools across files?
**Answer**: **4 files organized by functional domain** (not 13 files, not 1 file)

---

## Quick Answer

For pflow's 13 tools, use **4 tool files** grouped by functional domain:

```
tools/
├── workflow_tools.py    # 6 tools (execute, validate, save, list, discover)
├── registry_tools.py    # 5 tools (discover, search, describe, list, run)
├── settings_tools.py    # 2 tools (get, set)
└── trace_tools.py       # 1 tool (read)
```

**Why?** This balances maintainability (not too many files) with clarity (not one giant file).

---

## Key Research Findings

### 1. FastMCP Decorator Pattern (Central Server)

**Best Practice**: Create a central server instance that tool modules import

```python
# server.py - THE single source of truth
from fastmcp import FastMCP
mcp = FastMCP("pflow", version="0.1.0")

# tools/workflow_tools.py - Import and use
from ..server import mcp

@mcp.tool()
async def workflow_execute(workflow: str) -> dict:
    """Execute workflow."""
    return {"success": True}
```

**Key Insight**: Tools register **at import time** via decorators. No manual registration needed.

### 2. Real-World Examples

**GitHub MCP Server** (Official Production):
- Organized by **functional domain** (Actions, Issues, PRs, Repos, Security)
- Each domain is a "toolset" that can be enabled/disabled
- Clean grouping of related operations

**FHIR MCP Server** (Healthcare Production):
- Organized by **resource type** (Patient, Observation, Encounter)
- Router composition pattern with separate modules
- Mounted into central router

**Mix Server** (Tutorial Example):
```
tools/
├── csv_tools.py       # CSV operations
└── parquet_tools.py   # Parquet operations
```
- Simple domain-based organization
- Clear separation by file type

**Pattern**: All production servers use **multiple files grouped by domain/functionality**.

### 3. Import Patterns

**Recommended**: Package init auto-import

```python
# tools/__init__.py
from . import workflow_tools
from . import registry_tools
from . import settings_tools
from . import trace_tools

# main.py
from .server import mcp
from . import tools  # Auto-imports all via __init__.py

if __name__ == "__main__":
    mcp.run()
```

**Why?** Clean, automatic, maintainable, no wildcards.

### 4. Performance

**No performance difference** between 1 file vs. multiple files:
- Tools register once at import (one-time cost)
- Runtime execution identical
- Python module caching is efficient
- Network transport overhead >> file structure overhead

**Conclusion**: Choose organization for **maintainability**, not performance.

### 5. Stateless Pattern (Critical!)

**Problem**: Sharing service instances between requests causes stale data

```python
# ❌ WRONG - Shared state
class ToolProvider:
    def __init__(self):
        self.manager = WorkflowManager()  # STALE!

    @mcp.tool()
    async def execute(self, workflow: str) -> dict:
        return self.manager.execute(workflow)  # Uses stale manager

# ✅ CORRECT - Fresh instances
@mcp.tool()
async def workflow_execute(workflow: str) -> dict:
    manager = WorkflowManager()  # Fresh every request
    return manager.execute(workflow)
```

**Solution**: Use **service layer** with fresh instances per request.

### 6. Service Layer Pattern

**Purpose**: Stateless async wrappers around pflow's sync services

```python
# services/workflow_service.py
async def execute_workflow(workflow: str, parameters: dict) -> dict:
    """Execute workflow with fresh instances."""
    # Fresh manager (stateless)
    manager = WorkflowManager()

    # Wrap sync pflow code in async
    result = await asyncio.to_thread(
        core_execute,
        workflow,
        parameters,
        trace=True,        # Agent defaults
        json_output=True,  # Agent defaults
        auto_repair=False  # Agent defaults
    )

    return result

# tools/workflow_tools.py
@mcp.tool()
async def workflow_execute(workflow: str, params: dict) -> dict:
    """Execute workflow tool."""
    return await execute_workflow(workflow, params)
```

**Benefits**:
- ✅ Stateless (fresh instances)
- ✅ Agent defaults built-in
- ✅ Async wrapping of sync code
- ✅ Testable independently
- ✅ Decoupled from pflow internals

---

## Recommended Structure

```
src/pflow/mcp_server/
├── __init__.py                # Package exports
├── server.py                  # FastMCP instance (central)
├── main.py                    # Entry point
├── tools/                     # 4 tool files
│   ├── __init__.py           # Auto-imports
│   ├── workflow_tools.py     # 6 tools
│   ├── registry_tools.py     # 5 tools
│   ├── settings_tools.py     # 2 tools
│   └── trace_tools.py        # 1 tool
├── services/                  # Stateless service wrappers
│   ├── __init__.py
│   ├── workflow_service.py
│   ├── registry_service.py
│   └── settings_service.py
└── utils/                     # Shared utilities
    ├── __init__.py
    ├── errors.py             # Error formatting
    └── validation.py         # Input validation
```

### Why 4 Files (Not 13, Not 1)?

**Why not 1 file?**
- ❌ 600-800 lines (too large)
- ❌ Hard to navigate
- ❌ Merge conflicts
- ❌ Poor separation of concerns

**Why not 13 files?**
- ❌ Too granular (over-engineering)
- ❌ Too many imports
- ❌ Hard to see relationships
- ❌ Overkill for 13 simple tools

**Why 4 files?**
- ✅ Natural domain grouping (workflow, registry, settings, trace)
- ✅ Manageable file sizes (~150-200 lines each)
- ✅ Easy to navigate
- ✅ Clear boundaries
- ✅ Room to grow
- ✅ Follows production patterns

---

## Tool Organization Within Files

Each tool file should follow this pattern:

```python
"""
Module docstring: List all tools and their purpose
"""

# Imports
from typing import Annotated
from pydantic import Field
from fastmcp import Context

from ..server import mcp
from ..services.workflow_service import execute_workflow

# Tool 1
@mcp.tool()
async def workflow_execute(
    workflow: Annotated[str | dict, Field(description="Workflow JSON or name")],
    parameters: dict | None = None,
    ctx: Context | None = None
) -> dict:
    """
    Clear docstring (becomes tool description for AI).

    Args and Returns documented.
    """
    if ctx:
        await ctx.info("Starting execution")

    result = await execute_workflow(workflow, parameters)

    return {"success": True, "result": result}

# Tool 2, Tool 3, etc.
```

**Key Elements**:
1. Module docstring listing all tools
2. Imports at top (server, services, types)
3. One `@mcp.tool()` per function
4. Clear docstrings (AI sees these)
5. Type hints with `Field` for better schemas
6. Optional `Context` for logging/progress
7. Structured return values (dicts)

---

## Alternatives Considered

### Alternative 1: Class-Based Organization

```python
class WorkflowTools:
    def __init__(self, mcp: FastMCP):
        self.mcp = mcp
        self.mcp.tool(self.workflow_execute)

    def workflow_execute(self, workflow: str) -> dict:
        return {"success": True}

tools = WorkflowTools(mcp)
```

**Verdict**: ❌ Rejected
- Adds boilerplate (init, self)
- Tempts shared state (breaks stateless)
- Less Pythonic for simple tools
- No clear benefit over module functions

### Alternative 2: Server Composition

```python
# Split into mini-servers, then compose
workflow_server = FastMCP("workflows")
registry_server = FastMCP("registry")

main_server = FastMCP("pflow")
main_server.import_server(workflow_server, prefix="wf")
main_server.import_server(registry_server, prefix="reg")
```

**Verdict**: ⏳ Future consideration
- Useful if splitting services across teams
- Useful for reusable server modules
- **Not needed for MVP** (13 cohesive tools)
- Keep for v2.0+ if needed

---

## Testing Strategy

Mirror the tool organization:

```
tests/test_mcp_server/
├── test_server_setup.py           # Server initialization
├── test_tools/
│   ├── test_workflow_tools.py     # All 6 workflow tools
│   ├── test_registry_tools.py     # All 5 registry tools
│   ├── test_settings_tools.py     # 2 settings tools
│   └── test_trace_tools.py        # 1 trace tool
├── test_services/                 # Service layer unit tests
│   ├── test_workflow_service.py
│   ├── test_registry_service.py
│   └── test_settings_service.py
└── test_integration/              # End-to-end tests
    └── test_full_workflow_cycle.py
```

**Test Pattern** (from FastMCP docs):
```python
import pytest
from fastmcp import FastMCP
from fastmcp.testing import Client

@pytest.mark.asyncio
async def test_workflow_execute():
    """Test workflow execution tool."""
    # Fresh server for isolated test
    mcp = FastMCP("test-server")

    # Import tool module (triggers registration)
    from pflow.mcp_server.tools import workflow_tools

    async with Client(mcp) as client:
        result = await client.call_tool(
            "workflow_execute",
            {"workflow": "test-workflow.json"}
        )

        assert result.data["success"] is True
```

---

## Security Best Practices

### 1. Input Validation

```python
from pydantic import Field

@mcp.tool()
async def workflow_save(
    name: Annotated[str, Field(
        pattern=r"^[\w\-]+$",         # Alphanumeric, dash, underscore
        min_length=1,
        max_length=100,
        description="Workflow name"
    )],
    workflow: dict
) -> dict:
    """Save workflow with validated name."""
    # Pydantic validates automatically
    # Additional check for path traversal
    if any(c in name for c in ['/', '\\', '..', '~']):
        raise ValueError(f"Invalid characters: {name}")

    return await save_workflow(name, workflow)
```

### 2. Error Formatting

```python
from fastmcp import ToolError

@mcp.tool()
async def workflow_execute(workflow: str) -> dict:
    """Execute with proper error handling."""
    try:
        result = await execute_workflow(workflow)
        return {"success": True, "result": result}
    except ValidationError as e:
        # User-friendly error (LLM visible)
        raise ToolError(f"Invalid workflow: {e}")
    except Exception as e:
        # Hide internals
        raise ToolError(f"Execution failed: {str(e)}")
```

### 3. Stateless Operation

```python
# ✅ ALWAYS create fresh instances
@mcp.tool()
async def workflow_execute(workflow: str) -> dict:
    manager = WorkflowManager()  # Fresh
    registry = Registry()         # Fresh
    return await execute(manager, registry, workflow)

# ❌ NEVER share instances
_shared_manager = WorkflowManager()  # BAD!

@mcp.tool()
async def workflow_execute(workflow: str) -> dict:
    return await _shared_manager.execute(workflow)  # STALE!
```

---

## Implementation Checklist

- [ ] Create directory structure (`tools/`, `services/`, `utils/`)
- [ ] Create `server.py` with FastMCP instance
- [ ] Create `main.py` entry point
- [ ] Create `tools/__init__.py` with auto-imports
- [ ] Implement `workflow_tools.py` (6 tools)
- [ ] Implement `registry_tools.py` (5 tools)
- [ ] Implement `settings_tools.py` (2 tools)
- [ ] Implement `trace_tools.py` (1 tool)
- [ ] Create service layer (`workflow_service.py`, etc.)
- [ ] Create utilities (`errors.py`, `validation.py`)
- [ ] Write unit tests (one per tool file)
- [ ] Write integration tests (full cycle)
- [ ] Verify stateless operation (concurrent requests)
- [ ] Test with real MCP client (Claude Code)
- [ ] Document each tool with clear docstrings
- [ ] Run `make test` and `make check`

---

## Key Takeaways

1. **Use 4 files** grouped by functional domain (workflow, registry, settings, trace)
2. **Central server pattern** (`server.py` exports FastMCP instance)
3. **Package init imports** (`tools/__init__.py` auto-imports modules)
4. **Service layer** enforces stateless operation with fresh instances
5. **Module-level functions** (not classes) for simple, Pythonic tools
6. **Real-world validation** - Production servers use this exact pattern
7. **No performance penalty** - Organization is for humans, not machines
8. **Clear testing strategy** - Mirror tool organization in tests

---

## References

**Research Files**:
- `mcp-server-organization-research.md` - Full detailed analysis
- `recommended-file-structure.md` - Visual structure and examples
- `server-basics.md` - FastMCP server patterns
- `tool-implementation.md` - Tool definition patterns
- `advanced-patterns.md` - Progress reporting, middleware
- `error-handling-testing.md` - Testing patterns

**Real-World Examples**:
- GitHub MCP Server: https://github.com/github/github-mcp-server
- FHIR MCP Server: https://github.com/the-momentum/fhir-mcp-server
- Official MCP Servers: https://github.com/modelcontextprotocol/servers
- FastMCP Discussions: #948, #1312

**Documentation**:
- FastMCP: https://gofastmcp.com/servers/tools
- MCP Protocol: https://modelcontextprotocol.io/examples

---

## Conclusion

After extensive research of FastMCP documentation, production MCP servers, and Python best practices, the clear recommendation is:

**Use 4 tool files organized by functional domain with a service layer for stateless operation.**

This approach:
- ✅ Follows production patterns (GitHub, FHIR, AWS servers)
- ✅ Balances maintainability and clarity
- ✅ Enforces stateless operation
- ✅ Scales to future tools
- ✅ Provides clear testing strategy
- ✅ Has zero performance penalty
- ✅ Is Pythonic and idiomatic

**This structure is recommended for the pflow MCP server implementation.**
