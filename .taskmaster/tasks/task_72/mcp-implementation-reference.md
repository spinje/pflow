# Task 72 MCP Server Implementation Reference

## Purpose

This document consolidates all research findings for implementing the MCP server for pflow (Task 72). It demonstrates that pflow's architecture is already MCP-ready with minimal implementation effort required.

---

## 1. Service Layer is MCP-Ready

### Key Finding from Architecture Analysis

pflow has a **well-separated service layer** (from Task 68) that requires **zero refactoring** for MCP integration.

**Evidence**:
- 99 `click.echo()` calls in CLI layer
- 0 Click references in service layer
- All services return JSON-serializable data
- OutputInterface abstraction enables multiple frontends

### Core Services Available

| Service | Location | Click Coupling | MCP Ready |
|---------|----------|----------------|-----------|
| **WorkflowManager** | `src/pflow/core/workflow_manager.py` | None | ✅ Ready |
| **Registry** | `src/pflow/registry/registry.py` | None | ✅ Ready |
| **SettingsManager** | `src/pflow/core/settings.py` | None | ✅ Ready |
| **WorkflowExecutorService** | `src/pflow/execution/executor_service.py` | None | ✅ Ready |
| **execute_workflow()** | `src/pflow/execution/workflow_execution.py` | None | ✅ Ready |

---

## 2. MCP Implementation Pattern

### Direct Service Reuse (No Extraction)

```python
from pflow.core.workflow_manager import WorkflowManager
from pflow.registry import Registry
from pflow.execution.workflow_execution import execute_workflow
from pflow.execution.null_output import NullOutput

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "workflow_list":
        wm = WorkflowManager()
        workflows = wm.list_all()
        return workflows  # Already JSON-ready

    elif name == "registry_search":
        reg = Registry()
        results = reg.search(arguments["query"])
        return [{"name": n, "score": s} for n, m, s in results]

    elif name == "workflow_execute":
        result = execute_workflow(
            workflow_ir=arguments["workflow"],
            execution_params=arguments.get("params", {}),
            output=NullOutput()  # Silent execution
        )
        return {
            "success": result.success,
            "output": result.output_data,
            "errors": result.errors
        }
```

---

## 3. MCP Tools to Implement

### Recommended 18 Tools (from existing 24 CLI commands)

#### High Priority (6 tools)
1. **`pflow_execute`** - Execute workflows
2. **`pflow_list_workflows`** - Discover saved workflows
3. **`pflow_describe_workflow`** - Workflow metadata
4. **`pflow_list_nodes`** - Available nodes
5. **`pflow_describe_node`** - Node interfaces
6. **`pflow_search_nodes`** - Find nodes

#### Medium Priority (6 tools)
7. **`pflow_list_mcp_servers`** - Server status
8. **`pflow_list_mcp_tools`** - MCP tools
9. **`pflow_get_mcp_tool_info`** - Tool details
10. **`pflow_sync_mcp_server`** - Refresh catalog
11. **`pflow_get_settings`** - Config status
12. **`pflow_check_node_visibility`** - Filtering

#### Optional (6 tools)
13-18. Additional workflow/registry management tools

---

## 4. Service API Reference

### WorkflowManager
```python
def save(name: str, workflow_ir: dict, description: str) -> Path
def load(name: str) -> dict[str, Any]  # Full metadata
def load_ir(name: str) -> dict[str, Any]  # Just IR
def list_all() -> list[dict[str, Any]]
def exists(name: str) -> bool
def delete(name: str) -> None
```

### Registry
```python
def load(include_filtered: bool = False) -> dict[str, dict]
def search(query: str) -> list[tuple[str, dict, int]]
def scan_user_nodes(scan_path: Path) -> list[dict]
```

### execute_workflow()
```python
def execute_workflow(
    workflow_ir: dict,
    execution_params: dict,
    output: OutputInterface = NullOutput(),
    enable_repair: bool = True,
    ...
) -> ExecutionResult
```

**All return types**: JSON-serializable (dicts, lists, dataclasses)

---

## 5. OutputInterface for Silent Execution

### Enables Multiple Frontends

```python
class OutputInterface(Protocol):
    def show_progress(self, message: str, is_error: bool = False) -> None
    def show_result(self, data: Any) -> None
    def show_error(self, title: str, details: str = "") -> None
    def is_interactive(self) -> bool
```

**Implementations**:
- **CLI**: `CliOutput` (terminal colors, Click integration)
- **MCP**: `NullOutput` (silent execution) ← Already exists!
- **Future**: WebOutput, REPLOutput

---

## 6. Code Comparison: CLI vs MCP

### Example: List Workflows

**CLI Implementation** (14 lines):
```python
@workflow.command(name="list")
@click.option("--json", "output_json", is_flag=True)
def list_workflows(output_json: bool) -> None:
    wm = WorkflowManager()
    workflows = wm.list_all()

    if output_json:
        click.echo(json.dumps(workflows, indent=2))
    else:
        click.echo("Saved Workflows:")
        for wf in workflows:
            click.echo(f"\n{wf['name']}")
            click.echo(f"  {wf.get('description', '')}")
```

**MCP Implementation** (3 lines):
```python
@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "workflow_list":
        wm = WorkflowManager()
        return wm.list_all()  # MCP handles JSON
```

**70% code reduction** - no formatting needed

---

## 7. Implementation Effort Estimate

### Time Breakdown

**No Refactoring needed**: 0 days ✅
**MCP server setup**: 2-3 days
**Tool handlers** (18 tools): 3-5 days
**Testing**: 2-3 days
**Documentation**: 1-2 days

**Total**: 8-13 days

**Comparison**: Typical CLI tools require 3-5 days of extraction work. pflow requires **zero extraction** - just implement MCP protocol handlers.

---

## 8. WorkflowManager.save() for MCP

### MCP Tool Implementation Example

```python
from pflow.core.workflow_manager import WorkflowManager
from pflow.core.ir_schema import validate_ir, ValidationError
from pflow.core.exceptions import WorkflowExistsError, WorkflowValidationError

def save_workflow_tool(
    name: str,
    workflow_ir: dict[str, Any],
    description: str | None = None,
    overwrite: bool = False
) -> dict[str, Any]:
    """Save a workflow to the user's workflow library."""

    # Step 1: Validate IR
    try:
        validated_ir = validate_ir(workflow_ir)
    except ValidationError as e:
        return {
            "success": False,
            "error": "invalid_ir",
            "message": str(e)
        }

    # Step 2: Save with WorkflowManager
    wm = WorkflowManager()

    # Handle overwrite
    if overwrite and wm.exists(name):
        wm.update_ir(name, validated_ir)
        return {
            "success": True,
            "name": name,
            "operation": "updated"
        }

    # Save new
    try:
        file_path = wm.save(name, validated_ir, description)
        return {
            "success": True,
            "name": name,
            "path": file_path,
            "operation": "created"
        }
    except WorkflowExistsError:
        return {
            "success": False,
            "error": "workflow_exists",
            "message": f"Workflow '{name}' already exists"
        }
    except WorkflowValidationError as e:
        return {
            "success": False,
            "error": "invalid_name",
            "message": str(e)
        }
```

---

## 9. Tool Handler Patterns

### Pattern 1: Simple Data Retrieval
```python
async def list_workflows_tool(arguments: dict) -> list[dict]:
    """MCP tool: List all saved workflows"""
    wm = WorkflowManager()
    return wm.list_all()
```

### Pattern 2: Search/Filter
```python
async def search_nodes_tool(arguments: dict) -> list[dict]:
    """MCP tool: Search for nodes"""
    registry = Registry()
    results = registry.search(arguments["query"])
    return [
        {"name": name, "metadata": meta, "score": score}
        for name, meta, score in results
    ]
```

### Pattern 3: Execution with NullOutput
```python
async def execute_tool(arguments: dict) -> dict:
    """MCP tool: Execute workflow"""
    wm = WorkflowManager()
    ir = wm.load_ir(arguments["name"])

    result = await asyncio.to_thread(
        execute_workflow,
        workflow_ir=ir,
        execution_params=arguments.get("inputs", {}),
        output=NullOutput(),  # Silent!
        validate=False  # For deterministic MCP behavior
    )

    return {
        "success": result.success,
        "outputs": result.shared_after,
        "errors": result.errors,
        "duration": result.duration
    }
```

---

## 10. Error Handling for MCP

### Structured Error Responses

```python
# Success response
{
  "success": true,
  "data": {...},
  "message": "Operation successful"
}

# Error responses
{
  "success": false,
  "error": "workflow_exists" | "invalid_name" | "invalid_ir" | "not_found",
  "message": "Human-readable error message",
  "details": {  # Optional
    "field": "name",
    "rule": "max_length",
    "limit": 50
  }
}
```

### Exception Mapping

| pflow Exception | MCP Error Code | Message |
|----------------|----------------|---------|
| `WorkflowNotFoundError` | `not_found` | "Workflow '{name}' not found" |
| `WorkflowExistsError` | `workflow_exists` | "Workflow already exists" |
| `WorkflowValidationError` | `invalid_name` or `invalid_ir` | Specific validation error |
| `ValidationError` | `invalid_ir` | "Invalid workflow structure" |

---

## 11. Testing Strategy

### Service Layer Tests (Already Exist)
- ✅ WorkflowManager operations
- ✅ Registry search/load
- ✅ Execution flow
- ✅ Error handling

### MCP Integration Tests (Need to Create)

```python
def test_mcp_list_workflows():
    """Test MCP list_workflows tool"""
    result = await call_tool("workflow_list", {})
    assert isinstance(result, list)
    assert all("name" in wf for wf in result)

def test_mcp_execute_workflow():
    """Test MCP execute tool"""
    result = await call_tool("workflow_execute", {
        "name": "test-workflow",
        "inputs": {"param": "value"}
    })
    assert "success" in result
    assert "outputs" in result

def test_mcp_save_workflow_conflict():
    """Test MCP save handles conflicts"""
    # Save once
    result1 = await call_tool("save_workflow", {
        "name": "test",
        "workflow_ir": valid_ir
    })
    assert result1["success"] is True

    # Save again without overwrite
    result2 = await call_tool("save_workflow", {
        "name": "test",
        "workflow_ir": valid_ir
    })
    assert result2["success"] is False
    assert result2["error"] == "workflow_exists"
```

---

## 12. Implementation Checklist

### Phase 1: MCP Server Setup (2-3 days)
- [ ] Install FastMCP dependency
- [ ] Create `src/pflow/mcp_server/` directory
- [ ] Implement basic server with 1-2 tools
- [ ] Test MCP protocol integration

### Phase 2: Core Tools (3-4 days)
- [ ] `pflow_execute` - Workflow execution
- [ ] `pflow_list_workflows` - List saved workflows
- [ ] `pflow_describe_workflow` - Workflow metadata
- [ ] `pflow_list_nodes` - Available nodes
- [ ] `pflow_describe_node` - Node details
- [ ] `pflow_search_nodes` - Search functionality

### Phase 3: Additional Tools (1-2 days)
- [ ] MCP server management tools
- [ ] Settings/configuration tools
- [ ] Optional workflow management tools

### Phase 4: Testing & Documentation (2-3 days)
- [ ] Integration tests for all tools
- [ ] MCP protocol compliance testing
- [ ] Usage documentation
- [ ] Example workflows

---

## 13. Key Advantages of Current Architecture

### Why pflow is MCP-Ready

1. **Service Layer Exists** - No extraction needed (from Task 68)
2. **Zero Click Coupling** - Services have no CLI dependencies
3. **Data-Oriented APIs** - JSON-serializable return types
4. **Output Abstraction** - OutputInterface for multiple frontends
5. **Structured Exceptions** - Machine-readable error information
6. **NullOutput Exists** - Silent execution already implemented

### Comparison with Typical Projects

**Typical CLI → MCP migration**:
- 3-5 days extracting business logic from CLI
- 2-3 days creating service layer
- 1-2 days refactoring for statelessness
- Total: 6-10 days before MCP work

**pflow**:
- 0 days extraction (already done!)
- 0 days service creation (exists!)
- 0 days refactoring (already stateless!)
- Total: Jump directly to MCP implementation

---

## Summary

**pflow's architecture is Grade A+ for MCP integration**:

✅ **Service layer exists** - WorkflowManager, Registry, ExecutorService
✅ **Zero CLI coupling** - Services have no Click dependencies
✅ **Data-oriented APIs** - JSON-serializable return types
✅ **Output abstraction** - Multiple frontend support
✅ **MCP-ready** - Direct import and use

**Implementation is straightforward**:
- No refactoring required
- Thin wrappers around existing services
- 18 tools × ~20 lines each = ~360 lines total
- Testing with existing service test coverage
- 8-13 days total effort

The hard work (service extraction) was already done in Task 68!
