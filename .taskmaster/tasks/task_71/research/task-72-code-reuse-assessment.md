# Task 72 MCP Server - Code Reuse Assessment

## Executive Summary

**Verdict**: Extracting service functions now would provide **MINIMAL benefit** for Task 72. The MCP server already requires only thin wrappers due to existing architecture.

**Recommendation**: **DO NOT extract** service functions as separate task. Proceed with Task 72 implementation directly.

## Key Findings

### 1. MCP Tool Requirements Analysis

Task 72 requires **5 MCP tools**:

1. **browse_components** - Search nodes and workflows
2. **list_library** - List saved workflows
3. **describe_workflow** - Get workflow interface
4. **execute** - Run workflows with checkpoints
5. **save_to_library** - Promote draft to library

### 2. Existing Service Layer Assessment

**Discovery**: pflow ALREADY HAS a clean service layer extracted in Task 68!

#### Core Services Available:

**WorkflowExecutorService** (`execution/executor_service.py`):
```python
def execute_workflow(
    workflow_ir: dict,
    execution_params: dict,
    shared_store: Optional[dict] = None,
    workflow_name: Optional[str] = None,
    stdin_data: Optional[Any] = None,
    output_key: Optional[str] = None,
    metrics_collector: Optional[Any] = None,
    trace_collector: Optional[Any] = None,
    validate: bool = True,
) -> ExecutionResult
```
✅ **Already isolated from CLI**
✅ **Returns structured ExecutionResult**
✅ **Can use NullOutput for silent execution**

**WorkflowManager** (`core/workflow_manager.py`):
```python
def save(name, workflow_ir, description, metadata) -> Path
def load(name) -> dict  # Full metadata
def load_ir(name) -> dict  # Just IR
def list_all() -> list[dict]
def exists(name) -> bool
def delete(name) -> None
def update_ir(name, new_ir) -> None
```
✅ **Pure data operations**
✅ **No CLI dependencies**
✅ **Already returns structured data**

**Registry** (`registry/registry.py`):
```python
def load(include_filtered=False) -> dict
def search(query) -> list[tuple[str, dict, int]]
def get_metadata(key, default) -> Any
```
✅ **No CLI coupling**
✅ **Already returns structured data**

### 3. Data Format Analysis

**MCP Requirement**: JSON/structured responses
**Current State**: ALL service classes already return structured data!

**Evidence**:
- `WorkflowExecutorService` returns `ExecutionResult` dataclass
- `WorkflowManager` methods return dicts/lists
- `Registry` methods return structured data
- CLI commands have `--json` flags using the SAME underlying data

**Conclusion**: No extraction needed - services already provide both formats!

### 4. Code Duplication Estimate

**Without Service Extraction**: ~50 lines of wrapper code
**With Service Extraction**: ~50 lines of wrapper code + 100 lines of extraction + tests

**Why?**: The services are ALREADY extracted! MCP implementation would be:

```python
# This is ALL that's needed for each tool:

async def execute_tool(arguments: dict) -> dict:
    """MCP tool: Execute workflow"""
    # Create service instance
    service = WorkflowExecutorService(output_interface=NullOutput())

    # Call existing service method
    result = await asyncio.to_thread(
        service.execute_workflow,
        workflow_ir=load_workflow(arguments["name"]),
        execution_params=arguments.get("inputs", {})
    )

    # Convert ExecutionResult to MCP format
    return {
        "success": result.success,
        "outputs": result.shared_after,
        "checkpoint": result.errors if not result.success else None
    }
```

### 5. Stateless Requirements

**MCP Requirement**: Fresh instances per request
**Current Architecture**: Services ALREADY support this!

```python
# Each MCP request can simply:
wm = WorkflowManager()  # Fresh instance
registry = Registry()   # Fresh instance
service = WorkflowExecutorService(output_interface=NullOutput())
```

**No state pollution risk** - services don't hold cross-request state!

## Detailed Tool-by-Tool Analysis

### Tool 1: browse_components

**MCP Needs**:
- Search nodes by query
- Filter workflows by pattern
- Return structured metadata

**Existing Services**:
```python
registry = Registry()
nodes = registry.load()
workflows = WorkflowManager().list_all()
# Apply search/filtering
```

**Wrapper Code**: ~15 lines (just formatting)

---

### Tool 2: list_library

**MCP Needs**:
- List all saved workflows
- Filter by pattern

**Existing Service**:
```python
wm = WorkflowManager()
workflows = wm.list_all()  # Already returns list[dict]
# Apply pattern filtering if needed
```

**Wrapper Code**: ~10 lines

---

### Tool 3: describe_workflow

**MCP Needs**:
- Get workflow interface
- Return inputs/outputs metadata

**Existing Service**:
```python
wm = WorkflowManager()
metadata = wm.load(name)  # Returns full metadata dict
ir = metadata["ir"]
# Extract inputs/outputs from IR
```

**Wrapper Code**: ~12 lines

---

### Tool 4: execute

**MCP Needs**:
- Execute workflow with parameters
- Return checkpoint on failure
- Silent execution (no console output)
- enable_repair=False for deterministic behavior

**Existing Service**:
```python
service = WorkflowExecutorService(output_interface=NullOutput())
result = service.execute_workflow(
    workflow_ir=ir,
    execution_params=inputs,
    validate=False  # enable_repair=False
)
# result.success, result.shared_after, result.errors already available
```

**Wrapper Code**: ~20 lines (includes workflow loading logic)

**CRITICAL**: NullOutput already exists! (`execution/null_output.py`)

---

### Tool 5: save_to_library

**MCP Needs**:
- Move draft to library
- Atomic operations
- Validate draft exists

**Existing Service**:
```python
wm = WorkflowManager()
# Load from draft directory
draft_ir = wm.load_ir(draft_name)  # From ~/.pflow/workflows/
# Save to library with new name
wm.save(final_name, draft_ir, description, metadata)
# Delete draft
wm.delete(draft_name)
```

**Wrapper Code**: ~15 lines (error handling for atomic operation)

---

## Code Reuse Opportunities Matrix

| MCP Tool | Existing Service | Lines of Wrapper | Lines if Extracted | Benefit |
|----------|------------------|------------------|-------------------|---------|
| browse_components | Registry.load() + WM.list_all() | 15 | 15 + 30 extraction | ❌ None |
| list_library | WorkflowManager.list_all() | 10 | 10 + 20 extraction | ❌ None |
| describe_workflow | WorkflowManager.load() | 12 | 12 + 15 extraction | ❌ None |
| execute | WorkflowExecutorService.execute_workflow() | 20 | 20 + 40 extraction | ❌ None |
| save_to_library | WorkflowManager save/delete | 15 | 15 + 25 extraction | ❌ None |
| **TOTAL** | - | **72 lines** | **72 + 130 lines** | **❌ Negative** |

## Code Duplication Analysis

**Without extraction**: ~72 lines of MCP wrapper code
**With extraction**: ~72 lines wrapper + ~130 lines extraction + ~100 lines tests = ~302 lines total

**Duplication prevented**: **0 lines** (services already isolated!)

**Time saved in Task 72**: **~0 hours** (wrappers equally easy either way)

**Time cost of extraction**: **3-5 hours** (extraction + tests + documentation)

**ROI**: **Negative** - extraction would add complexity without benefit

## Critical Insight: Task 68 Already Did This!

**From `execution/CLAUDE.md`**:
> "WorkflowExecutorService extracted from CLI (Task 68 Phase 1), handles all execution logic."

**Task 68 created**:
- `WorkflowExecutorService` - Isolated execution service
- `ExecutionResult` - Structured result dataclass
- `NullOutput` - Silent output for non-interactive use
- `OutputInterface` - Abstract display layer

**This IS the service extraction!** The work was already done!

## Comparison: CLI vs MCP Usage

### CLI Code Pattern (main.py):
```python
# CLI creates CliOutput for display
output = CliOutput(output_controller)

# Calls service
service = WorkflowExecutorService(output_interface=output)
result = service.execute_workflow(workflow_ir=ir, ...)

# Formats output for terminal
if result.success:
    click.echo(f"✓ Success: {result.output_data}")
```

### MCP Code Pattern (Task 72):
```python
# MCP creates NullOutput for silent execution
output = NullOutput()

# Calls SAME service
service = WorkflowExecutorService(output_interface=output)
result = await asyncio.to_thread(
    service.execute_workflow, workflow_ir=ir, ...
)

# Returns structured JSON
return {
    "success": result.success,
    "outputs": result.shared_after,
    "checkpoint": result.errors if not result.success else None
}
```

**Difference**: Only the output interface and result formatting!

## Architectural Validation

### Question: Can the same service function provide both formats?
**Answer**: ✅ YES - already proven by existing architecture!

**Evidence**:
1. `WorkflowExecutorService` is display-agnostic
2. `CliOutput` vs `NullOutput` demonstrates interface pattern
3. `ExecutionResult` is already structured data
4. CLI `--json` flags use same underlying services

### Question: Are there state dependencies?
**Answer**: ✅ NO - services are inherently stateless!

**Evidence**:
1. Services instantiated per request
2. No class-level state stored
3. All state passed via parameters
4. Fresh Registry/WorkflowManager per call

### Question: Would extraction save time in Task 72?
**Answer**: ❌ NO - extraction already complete!

**Reasoning**:
1. Services already isolated in Task 68
2. MCP wrappers are thin regardless
3. No shared logic between tools (different services)
4. Extraction would ADD complexity, not reduce it

## Recommendation: Proceed Directly to Task 72

### Why No Extraction Needed:

1. **Services Already Exist**: Task 68 created the service layer
2. **Zero Duplication**: Each tool uses different service methods
3. **Thin Wrappers**: ~15 lines per tool is acceptable
4. **No Shared Logic**: Tools don't share implementation code
5. **Time Negative**: Extraction would waste 3-5 hours
6. **Complexity Increase**: Extra abstraction layer with no benefit

### What Task 72 Should Do:

```python
# src/pflow/mcp_server/server.py

from mcp import FastMCP
from pflow.core.workflow_manager import WorkflowManager
from pflow.registry import Registry
from pflow.execution import WorkflowExecutorService, NullOutput

mcp = FastMCP("pflow")

@mcp.tool()
async def execute(name: str, inputs: dict | None = None) -> dict:
    """Execute workflow by name."""
    # Load workflow
    wm = WorkflowManager()
    try:
        ir = wm.load_ir(name)
    except FileNotFoundError:
        # Try draft directory
        ir = load_from_draft(name)

    # Execute with silent output
    service = WorkflowExecutorService(output_interface=NullOutput())
    result = await asyncio.to_thread(
        service.execute_workflow,
        workflow_ir=ir,
        execution_params=inputs or {},
        validate=False  # enable_repair=False for MCP
    )

    # Return MCP format
    return {
        "success": result.success,
        "outputs": result.shared_after,
        "checkpoint": {
            "completed_nodes": result.shared_after.get("__execution__", {}).get("completed_nodes", []),
            "failed_node": result.shared_after.get("__execution__", {}).get("failed_node")
        } if not result.success else None
    }

# Repeat pattern for other 4 tools...
```

**Total Code**: ~250 lines for all 5 tools + FastMCP setup
**Dependencies**: Existing services only
**Tests**: Integration tests with FastMCP
**Time Estimate**: 8-12 hours (as originally planned)

## Final Verdict

**Question**: Would extracting service functions now materially benefit Task 72?

**Answer**: **NO - Services already extracted in Task 68!**

**Impact on Task 72**:
- Time saved: 0 hours (wrappers equally simple)
- Code reduced: 0 lines (no duplication exists)
- Complexity reduced: Negative (adds unnecessary layer)

**Recommended Action**:
✅ **Proceed directly to Task 72 implementation**
❌ **Do NOT create separate extraction task**

The architecture is already optimal for MCP integration. Task 72 can proceed immediately using existing services!
