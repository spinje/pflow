# MCP Server Organization - Quick Reference Card

**One-page cheat sheet for implementing pflow MCP server**

---

## 📁 File Structure (Copy This)

```
src/pflow/mcp_server/
├── __init__.py
├── server.py              # FastMCP("pflow", version="0.1.0")
├── main.py                # mcp.run()
├── tools/
│   ├── __init__.py       # Auto-imports all modules
│   ├── workflow_tools.py  # 6 tools
│   ├── registry_tools.py  # 5 tools
│   ├── settings_tools.py  # 2 tools
│   └── trace_tools.py     # 1 tool
├── services/
│   ├── __init__.py
│   ├── workflow_service.py
│   ├── registry_service.py
│   └── settings_service.py
└── utils/
    ├── __init__.py
    ├── errors.py
    └── validation.py
```

---

## 🎯 Core Patterns

### 1. Central Server (server.py)
```python
from fastmcp import FastMCP
mcp = FastMCP("pflow", version="0.1.0")
```

### 2. Tool Definition (tools/workflow_tools.py)
```python
from ..server import mcp

@mcp.tool()
async def workflow_execute(workflow: str, params: dict = None) -> dict:
    """Execute workflow with agent defaults."""
    return await execute_workflow(workflow, params)
```

### 3. Service Layer (services/workflow_service.py)
```python
async def execute_workflow(workflow: str, params: dict) -> dict:
    """Stateless wrapper - fresh instances."""
    manager = WorkflowManager()  # Fresh!
    result = await asyncio.to_thread(core_execute, workflow, params)
    return result
```

### 4. Entry Point (main.py)
```python
from .server import mcp
from . import tools  # Triggers registration

if __name__ == "__main__":
    mcp.run()
```

### 5. Auto-Import (tools/__init__.py)
```python
from . import workflow_tools
from . import registry_tools
from . import settings_tools
from . import trace_tools
```

---

## ✅ Critical Rules

### ALWAYS
- ✅ Create fresh instances (stateless)
- ✅ Use async for I/O operations
- ✅ Return structured dicts
- ✅ Type all parameters with Field()
- ✅ Write clear docstrings (AI sees these)
- ✅ Format errors for LLM visibility

### NEVER
- ❌ Share service instances between requests
- ❌ Use classes without clear benefit
- ❌ Decorate instance methods directly
- ❌ Return raw exceptions
- ❌ Skip input validation
- ❌ Use print() instead of ctx.info()

---

## 🔧 Tool Template

```python
@mcp.tool()
async def tool_name(
    param: Annotated[str, Field(description="Param description")],
    optional: Annotated[int | None, Field(description="Optional param")] = None,
    ctx: Context | None = None
) -> dict:
    """
    Clear description for AI.

    Args:
        param: Parameter description
        optional: Optional parameter description
        ctx: MCP context for logging

    Returns:
        dict: {"success": bool, "data": Any}
    """
    try:
        if ctx:
            await ctx.info("Starting operation")

        # Call service layer (fresh instances)
        result = await service_function(param, optional)

        if ctx:
            await ctx.info("Operation complete")

        return {"success": True, "data": result}

    except Exception as e:
        error = format_error_for_llm(e)
        if ctx:
            await ctx.error(f"Failed: {error}")
        return {"success": False, "error": error}
```

---

## 🧪 Testing Template

```python
import pytest
from fastmcp import FastMCP
from fastmcp.testing import Client

@pytest.mark.asyncio
async def test_tool():
    mcp = FastMCP("test-server")
    from pflow.mcp_server.tools import workflow_tools

    async with Client(mcp) as client:
        result = await client.call_tool(
            "workflow_execute",
            {"workflow": {...}}
        )
        assert result.data["success"] is True
```

---

## 🚨 Common Mistakes

### Mistake 1: Shared State
```python
# ❌ WRONG
manager = WorkflowManager()  # Shared!

@mcp.tool()
async def execute(workflow: str) -> dict:
    return manager.execute(workflow)  # STALE!

# ✅ CORRECT
@mcp.tool()
async def execute(workflow: str) -> dict:
    manager = WorkflowManager()  # Fresh!
    return manager.execute(workflow)
```

### Mistake 2: Decorating Instance Methods
```python
# ❌ WRONG
class Tools:
    @mcp.tool  # Breaks method binding!
    def execute(self, workflow: str) -> dict:
        pass

# ✅ CORRECT
class Tools:
    def __init__(self, mcp: FastMCP):
        mcp.tool(self.execute)  # Register after init

    def execute(self, workflow: str) -> dict:
        pass
```

### Mistake 3: Not Using Context
```python
# ❌ WRONG
@mcp.tool()
async def execute(workflow: str) -> dict:
    print("Executing")  # User can't see this!
    return result

# ✅ CORRECT
@mcp.tool()
async def execute(workflow: str, ctx: Context) -> dict:
    await ctx.info("Executing")  # LLM sees this!
    return result
```

---

## 📊 Tool Organization

### Group by Functional Domain

| File | Tools | Purpose |
|------|-------|---------|
| `workflow_tools.py` | 6 | Workflow lifecycle (execute, validate, save, list, discover) |
| `registry_tools.py` | 5 | Node operations (discover, search, describe, list, run) |
| `settings_tools.py` | 2 | Configuration (get, set) |
| `trace_tools.py` | 1 | Debugging (read) |

**Total**: 4 files for 13 tools

---

## 🎓 Key Concepts

### Stateless Operation
Every request gets fresh service instances. No shared state between requests.

### Service Layer
Async wrappers that:
- Create fresh instances
- Convert sync → async
- Apply agent defaults
- Keep tools simple

### Agent Defaults
Built into service layer:
- Always JSON output
- Always save traces
- Never auto-repair
- Always normalize

### Decorator Registration
Tools register at import time via `@mcp.tool()`. No manual registration needed.

---

## 🚀 Quick Start

1. **Create structure**:
   ```bash
   mkdir -p src/pflow/mcp_server/{tools,services,utils}
   ```

2. **Copy templates** from `implementation-templates.md`

3. **Fill in integration** with pflow services

4. **Test**:
   ```bash
   pytest tests/test_mcp_server/ -v
   ```

5. **Run**:
   ```bash
   python -m pflow.mcp_server.main
   ```

---

## 📚 Full Documentation

- **Quick answer**: `RESEARCH-SUMMARY.md`
- **Full analysis**: `mcp-server-organization-research.md`
- **Visual diagrams**: `recommended-file-structure.md`
- **Code templates**: `implementation-templates.md`
- **Navigation**: `README.md`

---

## 💡 Remember

- **4 files** by domain (not 13, not 1)
- **Fresh instances** every request (stateless)
- **Service layer** enforces good patterns
- **Type everything** (FastMCP uses types for schemas)
- **Document clearly** (AI reads your docstrings)
- **Test thoroughly** (use in-memory client)

---

**This structure follows production patterns from GitHub, FHIR, and AWS MCP servers.**

*Print this page and keep it handy during implementation!*
