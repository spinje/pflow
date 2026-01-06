# Code Locations for JSON String Parameter Bug

## Primary Fix Locations

### 1. CLI Parameter Parsing (for `registry run`)

**File:** `src/pflow/cli/main.py`

**Function:** `infer_type()` - Line ~2193

```python
def infer_type(value: str) -> Any:
    """Infer type from string value."""
    # ...
    # Line ~2223: JSON detection - THIS IS WHERE EAGER PARSING HAPPENS
    if value.startswith(("[", "{")):
        try:
            return json.loads(value)  # <-- Always parses, ignores target type
        except json.JSONDecodeError:
            pass
    return value
```

**Function:** `parse_workflow_params()` - Line ~2233

```python
def parse_workflow_params(args: tuple[str, ...]) -> dict[str, Any]:
    """Parse key=value parameters from command arguments."""
    params = {}
    for arg in args:
        if "=" in arg:
            key, value = arg.split("=", 1)
            params[key] = infer_type(value)  # <-- Uses infer_type
    return params
```

### 2. Registry Run Command

**File:** `src/pflow/cli/registry_run.py`

**Function:** `_validate_parameters()` - Line ~59

```python
def _validate_parameters(params: tuple[str, ...]) -> dict[str, Any]:
    """Parse and validate parameters from key=value format."""
    execution_params = parse_workflow_params(params)  # <-- Calls main.py
    # ... validation ...
    return execution_params
```

**Function:** `_prepare_node_execution()` - Line ~127

```python
def _prepare_node_execution(
    resolved_node: str, execution_params: dict[str, Any], registry: Registry
) -> tuple[Any, dict[str, Any]]:
    """Prepare node instance for execution."""
    # ...
    # RECOMMENDED FIX LOCATION: Add type coercion here
    # After loading node_class but before set_params

    enhanced_params = _inject_special_parameters(...)
    if enhanced_params:
        node.set_params(enhanced_params)  # <-- Params already parsed as dicts
    return node, enhanced_params
```

### 3. Workflow Execution (Template Resolution)

**File:** `src/pflow/runtime/template_resolver.py`

This handles `${variable}` resolution in workflow params. The issue here is that JSON objects in the workflow file are already dicts by the time they reach template resolution.

**File:** `src/pflow/runtime/compiler.py`

**Function:** `_resolve_node_params()` or similar - Where node params are prepared for execution.

## Registry Schema Access

**File:** `src/pflow/registry/registry.py`

**Class:** `Registry`

```python
def load(self) -> dict:
    """Load registry from file."""
    # Returns dict with node schemas
    # Each node has 'interface' -> 'params' -> [{'key': str, 'type': str, ...}]
```

**Example access:**
```python
registry = Registry()
nodes = registry.load()
node_schema = nodes.get('mcp-discord-execute_action')
params = node_schema['interface']['params']
# params = [{'key': 'path_params', 'type': 'str', ...}, ...]
```

## MCP Node Execution

**File:** `src/pflow/nodes/mcp/node.py`

**Class:** `MCPNode`

**Method:** `prep()` - Line ~75

```python
def prep(self, shared: dict) -> dict:
    """Prepare MCP tool execution."""
    # Line ~141: Extract user parameters
    tool_args = {k: v for k, v in self.params.items() if not k.startswith("__")}
    # tool_args already contains dicts if that's what was passed
    # MCPNode passes these directly to session.call_tool()
```

**Method:** `_exec_async_stdio()` - Line ~205

```python
async def _exec_async_stdio(self, prep_res: dict) -> dict:
    # Line ~248-249: Call the MCP tool
    result = await session.call_tool(prep_res["tool"], prep_res["arguments"])
    # If arguments["path_params"] is a dict, MCP tool will fail
```

## Type Definitions

**File:** `src/pflow/mcp/types.py`

```python
class ParamSchema(TypedDict, total=False):
    """Parameter schema for pflow registry."""
    key: str
    type: str  # <-- This is what we check: 'str', 'dict', 'list', etc.
    required: bool
    description: Optional[str]
    default: Any
```

## Recommended New Code Location

Create a new helper function, suggested location:

**Option A:** `src/pflow/cli/registry_run.py` (for CLI only)

```python
def _coerce_params_to_schema(
    params: dict[str, Any],
    node_id: str,
    registry: Registry
) -> dict[str, Any]:
    """Coerce parameter types based on node schema."""
    # Implementation here
```

**Option B:** `src/pflow/core/param_coercion.py` (new file, shared)

```python
"""Parameter type coercion utilities."""

def coerce_params_to_schema(
    params: dict[str, Any],
    param_schemas: list[dict]
) -> dict[str, Any]:
    """Coerce parameters based on declared types.

    If a param is declared as 'str' but value is dict/list,
    serialize to JSON string.
    """
    # Implementation here
```

This would be imported by both CLI and workflow execution code.

## Test File Locations

**Existing test files to check/extend:**
- `tests/test_cli/test_main.py` - CLI parsing tests
- `tests/test_cli/test_registry.py` - Registry command tests
- `tests/test_runtime/test_template_resolver.py` - Template resolution tests

**New test file to create:**
- `tests/test_cli/test_param_coercion.py` or
- `tests/test_core/test_param_coercion.py`

## Debugging Tips

### Print What MCP Node Receives

Add temporary debug in `src/pflow/nodes/mcp/node.py`:

```python
def prep(self, shared: dict) -> dict:
    # ... existing code ...
    tool_args = {k: v for k, v in self.params.items() if not k.startswith("__")}

    # DEBUG: Print what types we're passing
    for k, v in tool_args.items():
        print(f"DEBUG: {k} = {type(v).__name__}: {v!r}")

    # ... rest of method ...
```

### Trace CLI Parsing

Add temporary debug in `src/pflow/cli/main.py`:

```python
def infer_type(value: str) -> Any:
    result = _actual_infer_type(value)
    print(f"DEBUG infer_type: {value!r} -> {type(result).__name__}: {result!r}")
    return result
```
