# MCP Tools Layer Integration Analysis

**Purpose**: Deep analysis of how the tools layer integrates with services, utils, and resources in the pflow MCP server.

**Date**: 2025-10-13

## Executive Summary

The MCP tools layer implements a **three-tier async/sync bridge architecture** that exposes pflow's synchronous functionality through asynchronous MCP tools. The design is elegant and consistent, with every component following the same patterns:

1. **Tools layer** (async) - Thin wrappers with `@mcp.tool()` decorators
2. **Services layer** (sync) - Stateless business logic with `@classmethod` methods
3. **Core pflow** (sync) - Registry, WorkflowManager, execution engine

**Key Innovation**: Perfect CLI/MCP parity through shared formatters - both interfaces return identical output.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Tools Layer (11 production tools)                      │
│  - Async wrappers with @mcp.tool()                      │
│  - Pydantic Field descriptions (LLM-visible)            │
│  - await asyncio.to_thread(service_method)              │
├─────────────────────────────────────────────────────────┤
│  Services Layer (6 services)                            │
│  - @classmethod with @ensure_stateless                  │
│  - Fresh instances per request                          │
│  - Local imports for shared formatters                  │
├─────────────────────────────────────────────────────────┤
│  Utils Layer (3 utility modules)                        │
│  - errors.py: Error sanitization                        │
│  - resolver.py: Workflow resolution                     │
│  - validation.py: Security validation                   │
├─────────────────────────────────────────────────────────┤
│  Resources Layer (1 resource)                           │
│  - instruction_resources.py: Agent instructions         │
├─────────────────────────────────────────────────────────┤
│  Core pflow (sync components)                           │
│  - Registry, WorkflowManager, execute_workflow          │
│  - Shared formatters (execution/formatters/)            │
└─────────────────────────────────────────────────────────┘
```

## 1. The Async/Sync Bridge Pattern

### Pattern Implementation

**Every tool follows the same pattern**:
```python
@mcp.tool()
async def tool_name(
    param: Annotated[Type, Field(description="Role of param")]
) -> str:
    """Tool description visible to LLMs.

    Examples:
        # All variants shown
        param="variant1"
        param={"variant": 2}

    Returns:
        What gets returned
    """
    def _sync_operation() -> str:
        """Synchronous operation."""
        return ServiceClass.method(param)

    # Bridge: Async wrapper around sync code
    result = await asyncio.to_thread(_sync_operation)
    return result
```

### Why This Pattern Works

1. **Non-blocking**: `asyncio.to_thread()` runs sync code in thread pool, doesn't block event loop
2. **Simple**: No complex async/await propagation through pflow codebase
3. **Isolated**: Each tool defines its own sync wrapper function
4. **Testable**: Can test sync logic independently of async layer

### Examples from Real Code

**discovery_tools.py** (WorkflowDiscoveryNode):
```python
@mcp.tool()
async def workflow_discover(query: str) -> str:
    def _sync_discover() -> str:
        result: str = DiscoveryService.discover_workflows(query)
        return result

    result = await asyncio.to_thread(_sync_discover)
    return result
```

**execution_tools.py** (Workflow execution):
```python
@mcp.tool()
async def workflow_execute(
    workflow: str | dict[str, Any],
    parameters: dict[str, Any] | None = None,
) -> str:
    def _sync_execute() -> str:
        return ExecutionService.execute_workflow(workflow, parameters)

    result = await asyncio.to_thread(_sync_execute)
    return result
```

**registry_tools.py** (Node description):
```python
@mcp.tool()
async def registry_describe(nodes: list[str]) -> str:
    def _sync_describe() -> str:
        result: str = RegistryService.describe_nodes(nodes)
        return result

    result = await asyncio.to_thread(_sync_describe)
    return result
```

### Pattern Consistency

**All 11 production tools use identical structure**:
- Define inner `_sync_operation()` function
- Call service method inside sync function
- Return result with type annotation
- Use `await asyncio.to_thread(_sync_operation)`
- Return result to MCP client

## 2. Services Layer Integration

### Stateless Pattern Enforcement

**All services inherit from BaseService**:
```python
class ServiceName(BaseService):
    """Service description."""

    @classmethod
    @ensure_stateless
    def method_name(cls, param: Type) -> str:
        """Method description."""
        # Create fresh instances (CRITICAL)
        instance1 = Component1()
        instance2 = Component2()

        # Use instances and return
        result = instance1.process(param)
        return result
```

**BaseService provides**:
- `@ensure_stateless` decorator: Logs instance creation, validates no state
- `validate_stateless()`: Checks for instance variables (state violations)

### Fresh Instances Per Request

**Every service method creates fresh instances**:

**DiscoveryService** (discovery_service.py:38-41):
```python
node = WorkflowDiscoveryNode()       # Fresh
workflow_manager = WorkflowManager()  # Fresh
```

**ExecutionService** (execution_service.py:254-255):
```python
workflow_manager = WorkflowManager()  # Fresh
metrics_collector = MetricsCollector()  # Fresh
```

**RegistryService** (registry_service.py:40):
```python
registry = Registry()  # Fresh instance
```

**Why Fresh Instances**:
1. **Thread-safe**: No shared state between requests
2. **No stale data**: Each request sees current state
3. **Isolation**: Bugs in one request don't affect others
4. **Testable**: Easy to test without cleanup logic

### Service Responsibilities

**DiscoveryService** (127 lines):
- `discover_workflows()`: Wraps WorkflowDiscoveryNode
- `discover_components()`: Wraps ComponentBrowsingNode
- **Integration**: Uses planning nodes directly with shared store pattern
- **Output**: Markdown formatted strings (same as CLI)

**ExecutionService** (612 lines, largest service):
- `execute_workflow()`: Agent defaults (no repair, NullOutput, traces)
- `validate_workflow()`: 4-layer validation via WorkflowValidator
- `save_workflow()`: Uses workflow_save_service for consistency
- `run_registry_node()`: Direct node execution for output discovery
- **Integration**: Heavy use of formatters (10+ imports), WorkflowManager, Registry
- **Output**: Text strings (LLM-friendly, not JSON)

**RegistryService** (124 lines):
- `describe_nodes()`: Uses build_planning_context() for CLI parity
- `search_nodes()`: Uses Registry.search() with score-based matching
- `list_all_nodes()`: Uses shared formatter for grouped output
- **Integration**: Direct Registry usage, shared formatters
- **Output**: Markdown tables and lists

**WorkflowService** (93 lines):
- `list_workflows()`: Uses shared formatter
- `describe_workflow()`: Shows interface (inputs/outputs), raises ValueError with suggestions
- **Integration**: WorkflowManager, shared formatters
- **Output**: Markdown lists and interface specs

**SettingsService** (136 lines, disabled):
- `get_setting()`, `set_setting()`: Environment variable operations
- `show_all_settings()`, `list_env_variables()`: Uses SettingsManager API
- **Integration**: SettingsManager with masking support
- **Output**: JSON dicts and text strings

### Local Imports Pattern

**All services import formatters locally**:
```python
def method_name(cls, param):
    # ... logic ...

    # Import formatter inside method (not at module level)
    from pflow.execution.formatters.success_formatter import format_execution_success

    formatted = format_execution_success(...)
    return formatted
```

**Why Local Imports**:
1. **Clear dependencies**: Easy to see what each method uses
2. **Lazy loading**: Only import when needed
3. **Avoids circular imports**: Safer for shared formatters
4. **Testable**: Can mock imports per-method

### Error Handling Patterns

**Services raise exceptions, tools convert to MCP responses**:

**Service layer** (execution_service.py:243-244):
```python
if error_response or workflow_ir is None:
    error_msg = error_response.get("error", {}).get("message", "Unknown error")
    raise ValueError(error_msg)
```

**Tools layer** (execution_tools.py catches and handles):
```python
# Tools wrap service calls in try/except
try:
    result = await asyncio.to_thread(_sync_execute)
    return result
except ValueError as e:
    # MCP automatically converts exceptions to error responses
    raise
```

**Three error response types**:
1. **ValueError**: Validation errors, not found errors
2. **FileExistsError**: Workflow already exists (save without force)
3. **RuntimeError**: Execution failures with formatted error text

## 3. Utils Layer Integration

### Three Utility Modules

**errors.py** (171 lines) - Error sanitization:
```python
def sanitize_parameters(params: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive values recursively."""
    # Check keys against SENSITIVE_KEYS (from core/security_utils)
    # Truncate very long strings (potential keys/tokens)
    # Return sanitized dict
```

**resolver.py** (104 lines) - Workflow resolution:
```python
def resolve_workflow(workflow: str | dict[str, Any]) -> tuple[dict | None, str | None, str]:
    """Resolve workflow reference to IR.

    Resolution order:
    1. Dict → Use as IR ("direct")
    2. String → Try as library name ("library")
    3. String → Try as file path ("file")
    4. Return error with suggestions
    """
```

**validation.py** (147 lines) - Security validation:
```python
def validate_file_path(path_str: str, allow_absolute: bool = False) -> tuple[bool, str | None]:
    """Prevent path traversal attacks."""
    # Check for .., ~, null bytes, absolute paths
    # Resolve path and check for escaping
    # Return (is_valid, error_message)

def generate_dummy_parameters(inputs: dict[str, Any]) -> dict[str, Any]:
    """Create placeholders for validation."""
    # Returns {"key": "__validation_placeholder__"}

def validate_execution_parameters(params: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate execution parameters for safety."""
    # Check parameter names (shell-safe characters)
    # Check size (1MB limit)
    # Check for code injection patterns
```

### Utils Usage in Services

**ExecutionService uses all three utils**:

**resolver.py** (execution_service.py:33-80):
```python
def _resolve_and_validate_workflow(workflow, parameters):
    # Resolve workflow to IR
    workflow_ir, error, source = resolve_workflow(workflow)

    # Validate parameters
    validated_params = parameters or {}
    if parameters:
        is_valid, error = validate_execution_parameters(parameters)
```

**validation.py** (execution_service.py:330):
```python
# Generate dummy parameters for validation
inputs = workflow_ir.get("inputs", {})
dummy_params = generate_dummy_parameters(inputs)
```

**errors.py** (via formatters, indirect usage):
```python
# Formatters use sanitize_parameters() when formatting errors
formatted = format_execution_errors(
    result,
    sanitize=True,  # Triggers parameter sanitization
)
```

### Security Layers

**Three security checks**:
1. **Path validation** (validation.py): Blocks `..`, `~`, null bytes
2. **Parameter validation** (validation.py): Shell-safe names, 1MB limit, injection detection
3. **Error sanitization** (errors.py): Removes paths, tokens, API keys from LLM output

**Sensitive data patterns** (SENSITIVE_KEYS from core/security_utils):
```python
SENSITIVE_KEYS = [
    "password", "token", "api_key", "secret", "apikey",
    "access_token", "refresh_token", "auth", "credential",
    "private_key", "client_secret", "bearer", "session",
    "cookie", "authorization",
]
```

## 4. Resource Layer Integration

### Single Resource: Agent Instructions

**instruction_resources.py** (105 lines):
```python
@mcp.resource("pflow://instructions")
def get_agent_instructions() -> str:
    """Complete agent instructions for building workflows.

    Returns:
        Full markdown content from ~/.pflow/instructions/AGENT_INSTRUCTIONS.md
    """
    # Read instruction file (66KB comprehensive guide)
    # Return content directly (no formatting needed)
    # Fallback: Return helpful CLI commands if file missing
```

**Resource Pattern vs Tools**:
- **Resources**: Read-only data (GET-like), always available, no execution
- **Tools**: Actions with side effects (POST-like), invoked on demand

**Why Instructions as Resource**:
1. Agents consult when needed (no execution overhead)
2. Content is static (no dynamic generation)
3. Large content (66KB) - better as resource than tool response
4. Always available (agents can read before first tool call)

## 5. Core pflow Integration

### Direct Core Imports

**Services import core components directly**:

**From core/** (workflow_manager, validators, schemas):
```python
from pflow.core.workflow_manager import WorkflowManager
from pflow.core.workflow_validator import WorkflowValidator
from pflow.core.ir_schema import normalize_ir
from pflow.core.metrics import MetricsCollector
from pflow.core.suggestion_utils import find_similar_items
from pflow.core.security_utils import SENSITIVE_KEYS
```

**From execution/** (workflow execution, output handlers):
```python
from pflow.execution.workflow_execution import execute_workflow
from pflow.execution.null_output import NullOutput
```

**From registry/** (node discovery):
```python
from pflow.registry import Registry
```

**From runtime/** (node loading):
```python
from pflow.runtime.compiler import import_node_class
```

**From planning/** (discovery nodes):
```python
from pflow.planning.nodes import WorkflowDiscoveryNode, ComponentBrowsingNode
from pflow.planning.context_builder import build_planning_context
```

### Shared Formatters (CLI/MCP Parity)

**10 shared formatters** (from execution/formatters/):

**discovery_formatter.py**:
- `format_discovery_result()`: Workflow match with confidence score
- `format_no_matches_with_suggestions()`: No matches with workflow suggestions

**success_formatter.py**:
- `format_execution_success()`: Success dict with outputs/metrics
- `format_success_as_text()`: Text version for LLMs

**error_formatter.py**:
- `format_execution_errors()`: Error dict with checkpoint/errors/metrics

**validation_formatter.py**:
- `format_validation_success()`: "✓ Workflow is valid"
- `format_validation_failure()`: Errors with auto-generated suggestions

**workflow_save_formatter.py**:
- `format_save_success()`: Success message with location/execution hint

**registry_search_formatter.py**:
- `format_search_results()`: Markdown table with matching nodes

**registry_list_formatter.py**:
- `format_registry_list()`: Nodes grouped by package (Core/MCP/User)

**registry_run_formatter.py**:
- `format_node_output()`: Node output structure with template paths
- `format_node_not_found_error()`: Node not found with suggestions
- `format_execution_error()`: Node execution error

**node_output_formatter.py**:
- `format_node_output()`: Structure mode with template path traversal

**Pattern**: All formatters RETURN strings/dicts, never print (CLI uses click.echo, MCP returns directly).

### Agent-Optimized Defaults

**ExecutionService overrides CLI defaults**:

**CLI defaults**:
```python
execute_workflow(
    enable_repair=True,   # Auto-repair on errors
    output=CliOutput(),   # Interactive progress
)
```

**MCP defaults** (execution_service.py:258-262):
```python
execute_workflow(
    enable_repair=False,  # Explicit errors (agents handle repair)
    output=NullOutput(),  # Silent execution (no progress bars)
    # Trace always saved to ~/.pflow/debug/workflow-trace-*.json
)
```

**Why different defaults**:
1. **enable_repair=False**: Agents need explicit errors with checkpoints to understand failures
2. **output=NullOutput()**: MCP protocol handles responses, no interactive output needed
3. **Trace auto-saved**: Always save for debugging (MCP clients can access files)
4. **Text output**: LLMs parse natural language better than JSON

## 6. Integration Patterns Summary

### Pattern 1: Async/Sync Bridge
```python
# Tools layer (async)
@mcp.tool()
async def tool_name(param: Type) -> str:
    def _sync_operation() -> str:
        return ServiceClass.method(param)
    return await asyncio.to_thread(_sync_operation)
```

### Pattern 2: Stateless Services
```python
# Services layer (sync)
class ServiceName(BaseService):
    @classmethod
    @ensure_stateless
    def method_name(cls, param: Type) -> str:
        # Fresh instances
        instance1 = Component1()
        instance2 = Component2()

        # Use and return
        return instance1.process(param)
```

### Pattern 3: Local Formatter Imports
```python
# Inside service methods
def method_name(cls, param):
    # ... logic ...
    from pflow.execution.formatters.X import format_Y
    return format_Y(result)
```

### Pattern 4: Error Conversion
```python
# Services raise exceptions
if error:
    raise ValueError("Descriptive message")

# Tools let MCP convert to error responses
try:
    result = await asyncio.to_thread(_sync_execute)
    return result
except ValueError as e:
    raise  # MCP converts to error response automatically
```

### Pattern 5: Workflow Resolution
```python
# Utils resolve workflow input variants
workflow_ir, error, source = resolve_workflow(workflow)
# source: "direct" (dict), "library" (name), "file" (path)

# Services handle resolution at entry point
def execute_workflow(cls, workflow, parameters):
    workflow_ir, error, source = resolve_workflow(workflow)
    if error:
        raise ValueError(error)
    # Continue with resolved IR...
```

### Pattern 6: Security Validation
```python
# Three-layer security checks
# 1. Path validation (at entry point)
is_valid, error = validate_file_path(path)

# 2. Parameter validation (before execution)
is_valid, error = validate_execution_parameters(params)

# 3. Error sanitization (before return to LLM)
sanitized = sanitize_parameters(result)
```

## 7. Key Integration Points

### Tools → Services
- **Call pattern**: `await asyncio.to_thread(ServiceClass.method, param)`
- **Error handling**: Services raise exceptions, tools let MCP convert
- **Type safety**: Pydantic Field descriptions in tools, service methods validate

### Services → Utils
- **errors.py**: Services use formatters that call sanitize_parameters()
- **resolver.py**: Services call resolve_workflow() at entry point
- **validation.py**: Services call validation functions before core operations

### Services → Core
- **Fresh instances**: Create new Registry(), WorkflowManager(), MetricsCollector()
- **Direct calls**: execute_workflow(), WorkflowValidator.validate(), build_planning_context()
- **Shared formatters**: Local imports from execution/formatters/

### Services → Resources
- **No direct integration**: Resources are independent (agents read directly)
- **Instruction resource**: Provides context agents use when calling tools

### Core → Formatters
- **Formatters return**: Never print, always return strings/dicts
- **CLI usage**: click.echo(formatter_result)
- **MCP usage**: return formatter_result

## 8. Critical Behaviors

### Discovery-First Workflow
1. `workflow_discover()` → Check for existing workflows (avoid rebuilding)
2. `registry_discover()` → Find nodes for building (LLM selection)
3. `registry_run()` → Test node to reveal output structure
4. Build workflow using discovered structure
5. `workflow_execute()` → Execute built workflow
6. `workflow_save()` → Save to library for reuse

### Validation Layers
**WorkflowValidator.validate()** runs 4 checks:
1. **Structural**: IR schema compliance (Pydantic)
2. **Data flow**: Execution order, cycles, dependencies
3. **Template**: `${variable}` resolution
4. **Node types**: Registry verification

**generate_dummy_parameters()**: Creates `__validation_placeholder__` for validation without real data.

### Workflow Resolution Order
1. **Dict input** → Use as IR (`"direct"`)
2. **String** → Try as library name (`"library"`)
3. **String** → Try as file path (`"file"`)
4. **Failure** → Return suggestions using substring matching

### Error Sanitization Always Applied
**Before returning to LLM**:
1. Check keys against SENSITIVE_KEYS (15 patterns)
2. Redact matching values → `"<REDACTED>"`
3. Truncate very long strings (>100 chars) → `"value[:20]...<truncated>"`
4. Recursively sanitize nested dicts

## 9. Why This Architecture Works

### Separation of Concerns
- **Tools**: Async bridge, parameter descriptions (LLM interface)
- **Services**: Business logic, stateless pattern (thread-safe)
- **Utils**: Security, validation, resolution (shared utilities)
- **Resources**: Read-only data (agent guidance)
- **Core**: Workflow engine (single source of truth)

### Consistency Through Patterns
- **Every tool**: Same async/sync bridge structure
- **Every service**: @classmethod with @ensure_stateless
- **Every method**: Fresh instances per request
- **Every formatter**: Local import, return (not print)

### CLI/MCP Parity
- **Shared formatters**: Identical output for both interfaces
- **Same validation**: Both use WorkflowValidator.validate()
- **Same discovery**: Both use build_planning_context()
- **Same execution**: Both call execute_workflow() (different defaults)

### Thread Safety
- **No shared state**: Fresh instances per request
- **No module-level singletons**: Create instances in methods
- **No caching**: Each request sees current state
- **Thread pool isolation**: asyncio.to_thread prevents blocking

### Security by Design
- **Three-layer validation**: Path, parameter, error sanitization
- **Sensitive data patterns**: 15 keys automatically redacted
- **LLM-safe output**: Never expose paths, tokens, API keys
- **Size limits**: 1MB parameter limit prevents memory attacks

### Testability
- **Stateless**: Easy to test without cleanup
- **Fresh instances**: No test pollution
- **Local imports**: Can mock per-method
- **Error conversion**: Test services independently of tools

## 10. Common Pitfalls Avoided

### ❌ Don't Store State
```python
# WRONG: Instance variables violate stateless pattern
class Service(BaseService):
    def __init__(self):
        self.registry = Registry()  # ❌ State

    def method(self):
        return self.registry.load()  # ❌ Uses stored state
```

```python
# CORRECT: Fresh instances per request
class Service(BaseService):
    @classmethod
    @ensure_stateless
    def method(cls):
        registry = Registry()  # ✓ Fresh instance
        return registry.load()
```

### ❌ Don't Skip Async Bridge
```python
# WRONG: Direct sync call blocks event loop
@mcp.tool()
async def tool_name(param):
    return ServiceClass.method(param)  # ❌ Blocks
```

```python
# CORRECT: Use asyncio.to_thread
@mcp.tool()
async def tool_name(param):
    def _sync():
        return ServiceClass.method(param)
    return await asyncio.to_thread(_sync)  # ✓ Non-blocking
```

### ❌ Don't Create Custom Formatters
```python
# WRONG: Custom formatting breaks CLI/MCP parity
def execute_workflow(cls, workflow):
    result = execute_workflow(...)
    return f"Success: {result.outputs}"  # ❌ Custom format
```

```python
# CORRECT: Use shared formatters
def execute_workflow(cls, workflow):
    result = execute_workflow(...)
    from pflow.execution.formatters.success_formatter import format_execution_success
    return format_execution_success(...)  # ✓ CLI parity
```

### ❌ Don't Expose Sensitive Data
```python
# WRONG: Expose errors without sanitization
def method(cls):
    try:
        return execute()
    except Exception as e:
        return str(e)  # ❌ May contain paths, tokens
```

```python
# CORRECT: Use shared formatters with sanitization
def method(cls):
    try:
        return execute()
    except Exception as e:
        from pflow.execution.formatters.error_formatter import format_execution_errors
        return format_execution_errors(..., sanitize=True)  # ✓ Safe
```

### ❌ Don't Assume Dict Input
```python
# WRONG: Assume workflow is always dict
def execute(cls, workflow: dict):
    return execute_workflow(workflow)  # ❌ Fails on name/path
```

```python
# CORRECT: Use resolver
def execute(cls, workflow: str | dict):
    workflow_ir, error, source = resolve_workflow(workflow)
    if error:
        raise ValueError(error)
    return execute_workflow(workflow_ir)  # ✓ Handles all inputs
```

### ❌ Don't Skip Validation
```python
# WRONG: Execute without parameter validation
def execute(cls, workflow, parameters):
    return execute_workflow(workflow, parameters)  # ❌ Unsafe
```

```python
# CORRECT: Validate before execution
def execute(cls, workflow, parameters):
    if parameters:
        is_valid, error = validate_execution_parameters(parameters)
        if not is_valid:
            raise ValueError(error)
    return execute_workflow(workflow, parameters)  # ✓ Safe
```

## 11. Testing Integration Points

### Mock at Service Layer
```python
# Test tools by mocking services
@pytest.fixture
def mock_execution_service(monkeypatch):
    def mock_execute(*args, **kwargs):
        return "✓ Success"

    monkeypatch.setattr(
        "pflow.mcp_server.services.execution_service.ExecutionService.execute_workflow",
        mock_execute
    )
```

### Test Service Logic Independently
```python
# Test services with real Registry, WorkflowManager
def test_registry_service():
    # Services create fresh instances - no setup needed
    result = RegistryService.describe_nodes(["test-node"])
    assert "test-node" in result
```

### Test Utils in Isolation
```python
# Test utils without services
def test_resolver():
    # Direct IR
    ir, error, source = resolve_workflow({"nodes": []})
    assert ir is not None
    assert source == "direct"

    # Library name
    ir, error, source = resolve_workflow("workflow-name")
    # ...
```

### Verify Fresh Instances
```python
# Test stateless pattern
def test_stateless_enforcement():
    class TestService(BaseService):
        def __init__(self):
            self.state = "bad"  # Instance variable

    # validate_stateless() catches this
    service = TestService()
    with pytest.raises(AssertionError):
        BaseService.validate_stateless(service)
```

## 12. Future Enhancements

### Potential Additions
1. **Caching layer**: Cache Registry.load() results (invalidate on file changes)
2. **Metrics collection**: Track tool usage, execution times
3. **Rate limiting**: Prevent abuse of expensive operations (metadata generation)
4. **Batch operations**: Execute multiple workflows in one call
5. **Streaming responses**: Stream large outputs (node execution with binary data)

### Architecture Stability
Current architecture is **stable and proven**:
- 11 production tools working correctly
- Perfect CLI/MCP parity verified
- Stateless pattern prevents bugs
- Security layers protect sensitive data
- Shared formatters ensure consistency

**Don't change core patterns without strong justification** - the async/sync bridge, stateless services, and shared formatters are the foundation of this system's reliability.

## Conclusion

The MCP tools layer integration is a **masterclass in layered architecture**:

1. **Async/sync bridge**: Clean separation between MCP protocol (async) and pflow core (sync)
2. **Stateless services**: Thread-safe, testable, no bugs from shared state
3. **Shared formatters**: Perfect CLI/MCP parity without code duplication
4. **Security by design**: Three validation layers protect sensitive data
5. **Fresh instances**: Each request starts clean, no pollution between calls

**The key insight**: Don't try to make pflow async - build a thin async bridge that calls sync code safely. This architecture is simple, testable, and scales well.

**When adding new tools**:
1. Follow the async/sync bridge pattern exactly
2. Create service method with @ensure_stateless
3. Use fresh instances for all components
4. Import formatters locally for CLI parity
5. Validate inputs with utils layer
6. Let MCP convert exceptions to error responses

The architecture is **proven, stable, and ready for production use**.
