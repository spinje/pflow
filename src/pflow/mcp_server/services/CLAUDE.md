# MCP Services Layer

## Purpose

Stateless business logic layer that bridges async MCP tools with synchronous pflow core components. All methods are classmethods that create fresh instances per request, ensuring thread safety without locks.

## Critical Pattern: Stateless Services

**Every service MUST:**
1. Inherit from `BaseService`
2. Use `@classmethod` + `@ensure_stateless` decorator
3. Create fresh instances inside method body (never reuse)
4. Never store instance variables

**Why this matters:**
- Thread safety without locks (each request isolated)
- No stale data (fresh Registry/WorkflowManager every call)
- No hidden dependencies or state pollution
- Predictable behavior across concurrent requests

**Example:**
```python
@classmethod
@ensure_stateless
def execute_workflow(cls, workflow, parameters):
    # ✅ Create fresh instances per request
    workflow_manager = WorkflowManager()
    metrics_collector = MetricsCollector()
    registry = Registry()

    # Use and return (no state stored)
    result = execute_workflow(workflow_ir=ir, ...)
    return format_result(result)
```

**What breaks this pattern:**
```python
# ❌ Module-level singleton
_registry = Registry()

# ❌ Instance variables
def __init__(self):
    self._cache = {}

# ❌ Reusing instances across calls
_manager = WorkflowManager()
```

## Service Architecture

Six services with single responsibilities:

- **BaseService** - Pattern enforcement via `@ensure_stateless` decorator
- **DiscoveryService** - LLM-powered workflow/component discovery (uses planning nodes)
- **ExecutionService** - Execute, validate, save workflows + test nodes
- **RegistryService** - Node discovery, search, description
- **WorkflowService** - Workflow listing and metadata
- **SettingsService** - Environment variable management

## Integration Patterns

### 1. Shared Formatters (CLI/MCP Parity)

**Import formatters locally** (inside methods, not module-level):
```python
def execute_workflow(cls, ...):
    from pflow.execution.formatters.success_formatter import format_execution_success
    from pflow.execution.formatters.error_formatter import format_execution_errors

    # Use formatter
    return format_execution_success(result, mode="text")
```

**Why local imports:**
- Avoid circular dependencies
- Clear where formatters are used
- Same imports as CLI (easy to verify parity)

**Available formatters** (`execution/formatters/`):
- `success_formatter` - Execution results with metrics
- `error_formatter` - Failed execution with checkpoints
- `validation_formatter` - Validation errors/warnings
- `discovery_formatter` - Discovery results
- `node_output_formatter` - Node execution structure
- `workflow_save_formatter` - Save success messages
- `workflow_list_formatter` - Workflow listings
- `workflow_describe_formatter` - Workflow interfaces
- `registry_list_formatter` - Registry listings
- `registry_search_formatter` - Search results

### 2. Core pflow Components

**Common fresh instances:**
```python
# Workflow operations
workflow_manager = WorkflowManager()
validator = WorkflowValidator()

# Discovery
registry = Registry()

# Execution
metrics_collector = MetricsCollector()
output = NullOutput()  # Silent execution for MCP

# Planning (discovery services only)
node = WorkflowDiscoveryNode()
node = ComponentBrowsingNode()
```

**Shared store pattern** (planning nodes only):
```python
shared = {
    "user_input": query,
    "workflow_manager": workflow_manager,
}
action = node.run(shared)
result = shared.get("discovery_result")  # Extract result
```

### 3. Utils Layer

Services use MCP utils for security and convenience:

```python
from ..utils.resolver import resolve_workflow  # Multi-source loading
from ..utils.validation import validate_execution_parameters  # Security
from ..utils.validation import generate_dummy_parameters  # Validation placeholders
```

Core utilities (shared with CLI):
```python
from pflow.core.suggestion_utils import format_did_you_mean
from pflow.core.workflow_save_service import save_workflow_with_options
from pflow.core.security_utils import SENSITIVE_KEYS
```

## Error Handling Patterns

**Services raise exceptions, tools convert to MCP errors:**

```python
# In service
if not workflow_manager.exists(name):
    suggestion = format_did_you_mean(name, all_names, item_type="workflow")
    raise ValueError(f"Workflow '{name}' not found.\n{suggestion}")

# Tool layer lets MCP handle exception conversion automatically
```

**Error types:**
- `ValueError` - Invalid input, not found, validation failures
- `FileExistsError` - Workflow name conflicts
- `RuntimeError` - Execution failures
- `TypeError` - Unexpected data types (formatter safety)

## Agent-Optimized Defaults

**ExecutionService.execute_workflow()** has MCP-specific defaults:

```python
# Auto-configured (no flags needed)
enable_repair=False         # Explicit errors (no silent fixes)
output=NullOutput()         # Silent execution
# Trace auto-saved to ~/.pflow/debug/
# Auto-normalization of IR
```

**Why different from CLI:**
- Agents need explicit errors to debug
- No progress output needed (agents parse final result)
- Always want traces (harder for AI to debug)
- IR version consistency (prevent validation errors)

## Critical Rules

### Rule 1: Type Safety for Formatters

Formatters expect specific types. Type narrow before calling:

```python
# ✅ Safe
if not isinstance(result, dict):
    raise TypeError(f"Expected dict, got {type(result)}")
return format_discovery_result(result)  # Now safe

# ❌ Crashes if result is string
return format_discovery_result(result)
```

### Rule 2: Never Return Mixed Types

Service methods must return consistent types:

```python
# ❌ Wrong - returns dict OR string
def run_node(...) -> str:
    if error:
        return {"error": "..."}  # Dict!
    return "success"  # String!

# ✅ Correct - always string
def run_node(...) -> str:
    if error:
        return format_error(...)  # String
    return format_success(...)  # String
```

### Rule 3: Fresh Instances Every Time

Never reuse core components across service calls:

```python
# ❌ Stale data across requests
class RegistryService:
    registry = Registry()  # Shared state!

# ✅ Fresh data per request
@classmethod
def search_nodes(cls, pattern):
    registry = Registry()  # New instance
    return registry.search(pattern)
```

## Common Pitfalls

### Pitfall 1: Skipping Validation

**Problem:** Missing validation checks cause cryptic errors at runtime

```python
# ❌ No validation
def describe_workflow(cls, name):
    manager = WorkflowManager()
    return manager.load_ir(name)  # Crashes if not found

# ✅ Validate with suggestions
def describe_workflow(cls, name):
    manager = WorkflowManager()
    if not manager.exists(name):
        suggestion = format_did_you_mean(name, manager.list_all())
        raise ValueError(f"Not found: {name}\n{suggestion}")
    return manager.load_ir(name)
```

### Pitfall 2: Wrong Registry Format Assumptions

**Problem:** Registry stores `{"module": "path.to.file", "class_name": "NodeClass"}`

```python
# ❌ Wrong assumption
node_module = metadata["module"]  # "path.to.file"
NodeClass = importlib.import_module(node_module)  # Not a class!

# ✅ Use proven helper
from pflow.runtime.compiler import import_node_class
NodeClass = import_node_class(node_type)
```

### Pitfall 3: Forgetting Dummy Parameters

**Problem:** Validation fails on templates without parameter values

```python
# ❌ Missing parameters for template validation
errors = WorkflowValidator.validate(workflow_ir)  # Templates fail!

# ✅ Generate placeholders
from ..utils.validation import generate_dummy_parameters
dummy = generate_dummy_parameters(workflow_ir.get("inputs", {}))
errors = WorkflowValidator.validate(workflow_ir, extracted_params=dummy)
```

### Pitfall 4: Not Using Shared Formatters

**Problem:** Creating MCP-specific formatting duplicates CLI logic

```python
# ❌ Duplicate logic
result = f"Found {len(workflows)} workflows:\n"
for w in workflows:
    result += f"  - {w['name']}\n"

# ✅ Use shared formatter
from pflow.execution.formatters.workflow_list_formatter import format_workflow_list
return format_workflow_list(workflows)
```

### Pitfall 5: Not Extracting All ExecutionResult Fields

**Problem:** When formatters add parameters, must update both CLI and MCP call sites.

```python
# ❌ Missing new ExecutionResult fields
formatted = format_execution_success(
    shared_storage=result.shared_after,
    metrics_collector=metrics_collector,
)

# ✅ Extract ALL fields (Task 85: status, warnings)
formatted = format_execution_success(
    shared_storage=result.shared_after,
    metrics_collector=metrics_collector,
    status=result.status,      # New field
    warnings=result.warnings,  # New field
)
```

**Fix locations:** CLI `cli/main.py` line ~476, MCP `execution_service.py` line ~143

## Testing Strategy

**Mock at service layer** (not core components):

```python
# Test tool → service boundary
@patch.object(ExecutionService, 'execute_workflow')
def test_tool(mock_execute):
    mock_execute.return_value = "✓ Success"
    result = await workflow_execute("test")
    assert result == "✓ Success"

# Test service → core boundary with real components
def test_service():
    registry = Registry()  # Real instance
    nodes = RegistryService.list_all_nodes()
    assert "shell" in nodes
```

## When Adding New Service Methods

1. **Start with signature:**
   ```python
   @classmethod
   @ensure_stateless
   def new_method(cls, param: str) -> str:
   ```

2. **Create fresh instances:**
   ```python
   workflow_manager = WorkflowManager()
   registry = Registry()
   ```

3. **Import formatters locally:**
   ```python
   from pflow.execution.formatters.X import format_Y
   ```

4. **Validate inputs with suggestions:**
   ```python
   if not exists:
       suggestion = format_did_you_mean(...)
       raise ValueError(f"Not found\n{suggestion}")
   ```

5. **Use shared formatters for output:**
   ```python
   return format_Y(result)
   ```

6. **Let exceptions propagate** (tool layer converts to MCP errors)
