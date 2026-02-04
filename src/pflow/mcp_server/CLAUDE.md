# CLAUDE.md - MCP Server Module Documentation

## Executive Summary

The `src/pflow/mcp_server/` module exposes pflow's workflow building and execution capabilities as MCP (Model Context Protocol) tools for AI agents. It provides programmatic access without shell execution, with structured responses and agent-optimized defaults.

**Core Innovation**: Three-layer stateless architecture (async tools → sync services → core pflow) with perfect CLI parity via shared formatters.

**Note**: 11 production tools enabled (settings_tools and test_tools disabled by default - code kept for future use).

## Module Architecture

```
┌─────────────────────────────────────────┐
│         MCP Tools (11 enabled)           │  ← FastMCP decorators, async wrappers
│         asyncio.to_thread bridge         │
├─────────────────────────────────────────┤
│      Services Layer (6 services)         │  ← Business logic, stateless pattern
│      Fresh instances per request         │
├─────────────────────────────────────────┤
│   Core pflow (sync components)           │  ← Registry, WorkflowManager, execute_workflow
│   Shared formatters (CLI/MCP parity)     │
└─────────────────────────────────────────┘
```

## File Structure

```
src/pflow/mcp_server/
├── __init__.py                          (9 lines)   - Package exports
├── main.py                              (122 lines) - Server startup and signal handling
├── server.py                            (51 lines)  - FastMCP instance and tool/resource registration
├── tools/                               (862 lines total)
│   ├── __init__.py                      (28 lines)
│   ├── discovery_tools.py               (90 lines)  - workflow_discover, registry_discover
│   ├── execution_tools.py               (215 lines) - workflow_execute, validate, save, registry_run
│   ├── registry_tools.py                (115 lines) - registry_describe, search, list
│   ├── workflow_tools.py                (95 lines)  - workflow_list, workflow_describe
│   ├── settings_tools.py                (173 lines) - settings_get, set, show, list_env
│   └── test_tools.py                    (146 lines) - ping, test_sync_bridge, test_stateless_pattern
├── resources/                           (326 lines total)
│   ├── __init__.py                      (7 lines)
│   └── instruction_resources.py         (319 lines) - Agent instructions resources (regular + sandbox)
├── services/                            (714 lines total)
│   ├── __init__.py                      (21 lines)
│   ├── base_service.py                  (76 lines)  - Stateless pattern enforcement
│   ├── discovery_service.py             (127 lines) - LLM-powered discovery
│   ├── execution_service.py             (540 lines) - Execute, validate, save, run
│   ├── registry_service.py              (124 lines) - Node operations
│   ├── workflow_service.py              (93 lines)  - Workflow metadata
│   └── settings_service.py              (136 lines) - Settings management
└── utils/                               (427 lines total)
    ├── __init__.py                      (5 lines)
    ├── errors.py                        (171 lines) - Error sanitization
    ├── resolver.py                      (104 lines) - Workflow resolution
    └── validation.py                    (147 lines) - Security validation

Total: ~2,506 lines
```

## Core Components

### 1. Entry Points

**main.py** - Server startup and lifecycle
- `run_server()`: Starts stdio transport, installs Anthropic model wrapper, registers tools
- `configure_logging()`: Routes logs to stderr (stdout reserved for protocol)
- Signal handling: SIGTERM/SIGINT for graceful shutdown

**server.py** - FastMCP instance with agent guidance
- `mcp = FastMCP("pflow", instructions="...")`: Single global server instance with server-level instructions
- **Server Instructions**: Critical workflow guidance injected into agent's system prompt by MCP clients
  - ALWAYS run `workflow_discover` first
  - If 95%+ match → execute directly (don't rebuild)
  - If building new → read `pflow://instructions` resource first
- `register_tools()`: Imports tool and resource modules to trigger decorator registration
- Pattern: Import-time registration via `@mcp.tool()` and `@mcp.resource()`

### 2. Tools Layer (11 Production Tools)

All tools use async/sync bridge: `await asyncio.to_thread(service_method)`

**Note**: settings_tools (4 tools) and test_tools (3 tools) are disabled by default - code kept for future use.

**discovery_tools.py** (2 tools):
- `workflow_discover(query)`: Find workflows using LLM matching (WorkflowDiscoveryNode)
- `registry_discover(task)`: Find nodes using LLM selection (ComponentBrowsingNode)

**execution_tools.py** (4 tools):
- `workflow_execute(workflow, parameters)`: Execute with agent defaults (no repair, JSON, traces)
- `workflow_validate(workflow)`: Validate structure (schema, data flow, templates, node types)
- `workflow_save(workflow_file, name, force)`: Save to library
- `registry_run(node_type, parameters)`: Test node to discover output structure

**registry_tools.py** (3 tools):
- `registry_describe(nodes)`: Detailed specs using CLI's build_planning_context()
- `registry_search(pattern)`: Search nodes by pattern
- `registry_list()`: All nodes grouped by package

**workflow_tools.py** (2 tools):
- `workflow_list(filter_pattern)`: List saved workflows
- `workflow_describe(name)`: Show workflow interface (inputs/outputs)

**settings_tools.py** (4 tools) - **DISABLED**:
- `settings_get(key)`: Get environment variable
- `settings_set(key, value)`: Set environment variable
- `settings_show()`: Show all settings
- `settings_list_env(show_values)`: List env vars (masked by default)

**test_tools.py** (3 tools) - **DISABLED**:
- `ping(echo, error)`: Server health check
- `test_sync_bridge(delay_seconds)`: Test async/sync bridge
- `test_stateless_pattern()`: Verify fresh instances

### 3. Resources Layer (2 Resources)

**MCP Resources** provide read-only data that agents can access at any time. Unlike tools (which perform actions), resources expose information.

**instruction_resources.py** (2 resources):
- `pflow://instructions`: Complete agent instructions for building workflows (full system access)
- `pflow://instructions/sandbox`: Instructions for sandboxed/isolated environments (restricted access)

**Resource Pattern**:
```python
@mcp.resource("pflow://uri")
def get_resource() -> str:
    """Docstring visible to agents."""
    return content  # Return full content
```

#### Regular Agent Instructions (`pflow://instructions`)

**For agents with FULL system access**:
- **Path**: `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` (package resources, then `~/.pflow/instructions/` for user customization)
- **Size**: ~66KB comprehensive guide
- **Access Level**: ✅ Full (settings.json, traces, workflow library)
- **Content**: 10-step development loop, patterns, troubleshooting, examples
- **Key Capabilities**:
  - Can use `pflow settings set-env` commands
  - Can read trace files from `~/.pflow/debug/`
  - Can save/load workflows from user library
  - Full CLI command reference
- **Fallback**: Complete CLI guide including settings and trace commands

#### Sandbox Agent Instructions (`pflow://instructions/sandbox`)

**For agents in ISOLATED environments**:
- **Path**: `src/pflow/mcp_server/resources/instructions/mcp-sandbox-agent-instructions.md` (package resources, then `~/.pflow/instructions/` for user customization)
- **Size**: ~50-66KB (estimated, adapted guide)
- **Access Level**: ❌ Restricted (no settings.json, no traces, limited library)
- **Content**: Same workflow building process, adapted for sandboxed environments
- **Key Constraints**:
  - CANNOT use `pflow settings` commands
  - CANNOT access trace files
  - MUST pass credentials as workflow inputs
  - Limited/isolated workflow library access
- **Use Cases**: Containers, web-based AI, CI/CD, multi-tenant systems
- **Fallback**: Sandbox-specific guidance with credentials-as-inputs pattern

#### Key Differences

| Aspect | Regular Agents | Sandbox Agents |
|--------|---------------|----------------|
| **Settings access** | ✅ Read/write settings.json | ❌ No settings.json access |
| **Trace files** | ✅ Read from ~/.pflow/debug/ | ❌ No trace access |
| **Workflow library** | ✅ Full library access | ⚠️ Limited/isolated |
| **API key pattern** | Settings or inputs | **Must use inputs only** |
| **CLI commands** | Full reference | Restricted subset |
| **Guidance style** | "Store in settings.json" | "Pass as `api_key=VALUE`" |

#### Multi-Layer Guidance Strategy

1. **Server Instructions** (InitializeResult) - Short imperative rules, injected into system prompt
2. **Resource Metadata** (title/description) - Makes resource purpose clear when listed
3. **Resource Docstrings** - Clarifies full vs sandbox access (agents see this)
4. **Tool Descriptions** - Each tool reinforces discovery-first pattern
5. **Resource Content** - Complete guides with detailed best practices

**Path Resolution** (both resources):
- Checks project root first: `.pflow/instructions/{filename}` (development)
- Falls back to user home: `~/.pflow/instructions/{filename}` (production)
- Returns appropriate fallback if neither exists

**Why Resources vs Tools**:
- **Resources** = Read-only data (GET-like), always available
- **Tools** = Actions with side effects (POST-like), invoked on demand
- Instructions fit resource pattern: agents consult when needed, no execution required

### 4. Services Layer (6 Services)

All inherit from `BaseService`, all methods are `@classmethod` with `@ensure_stateless` decorator.

**base_service.py**:
- Enforces stateless pattern (no instance variables)
- `@ensure_stateless` decorator logs instance creation
- `validate_stateless()` checks for state violations

**discovery_service.py**:
- `discover_workflows()`: Wraps WorkflowDiscoveryNode
- `discover_components()`: Wraps ComponentBrowsingNode
- Fresh instances: WorkflowDiscoveryNode, ComponentBrowsingNode, WorkflowManager

**execution_service.py**:
- `execute_workflow()`: Agent defaults (enable_repair=False, NullOutput, trace auto-saved)
- `validate_workflow()`: 4-layer validation via WorkflowValidator
- `save_workflow()`: Uses workflow_save_service for consistency
- `run_registry_node()`: Direct node execution for output discovery
- Fresh instances: WorkflowManager, MetricsCollector, Registry

**registry_service.py**:
- `describe_nodes()`: Uses build_planning_context() for CLI parity
- `search_nodes()`: Uses Registry.search()
- `list_all_nodes()`: Uses shared formatter
- Fresh instances: Registry

**workflow_service.py**:
- `list_workflows()`: Uses shared formatter
- `describe_workflow()`: Uses shared formatter, raises ValueError with suggestions
- Fresh instances: WorkflowManager

**settings_service.py**:
- `get_setting()`, `set_setting()`: Environment variable operations
- `show_all_settings()`, `list_env_variables()`: Uses SettingsManager API
- Fresh instances: SettingsManager

### 5. Utilities

**errors.py** - Error sanitization for LLM safety:
- `sanitize_error_message()`: Removes paths, tokens, API keys
- `sanitize_parameters()`: Redacts sensitive values recursively
- Uses SENSITIVE_KEYS from core/security_utils

**resolver.py** - Workflow resolution:
- `resolve_workflow()`: dict → markdown content (has newline) → library name → file path (with suggestions)
- `get_workflow_suggestions()`: Find similar names using substring matching

**validation.py** - Security validation:
- `validate_file_path()`: Path traversal prevention
- `generate_dummy_parameters()`: Placeholder values for structural validation
- `validate_execution_parameters()`: Shell-safe names, size limits, injection detection

## Key Patterns

### 1. Stateless Pattern

**Every request creates fresh instances**:
```python
@classmethod
@ensure_stateless
def execute_workflow(cls, workflow, parameters):
    workflow_manager = WorkflowManager()  # Fresh
    metrics_collector = MetricsCollector()  # Fresh
    # ... use and return ...
```

**Why**: Prevents state pollution, thread-safe, no stale data between requests.

### 2. Async/Sync Bridge

**Consistent pattern across all tools**:
```python
@mcp.tool()
async def tool_name(param: Type):
    """Tool description."""
    def _sync_operation() -> ReturnType:
        return ServiceClass.method(param)

    result = await asyncio.to_thread(_sync_operation)
    return result
```

**Why**: pflow is sync, MCP protocol is async. asyncio.to_thread bridges without blocking event loop.

### 3. CLI/MCP Parity

**Shared formatters from execution/formatters/**:
- All tools import formatters locally in methods
- 10 formatters ensure identical output (text/markdown/JSON)
- Pattern: Formatters RETURN (str/dict), never print

**Examples**:
- Registry search: Both use `format_search_results()` → identical markdown table
- Workflow validation: Both use `format_validation_failure()` → identical text output
- Node execution: Both use `format_node_output(format_type="structure")` → identical template paths

### 4. Security

**Three layers**:
1. **Path validation** (utils/validation.py): Blocks `..`, `~`, null bytes, absolute paths (configurable)
2. **Parameter sanitization**: Shell-safe names, 1MB limit, code injection detection
3. **Error sanitization** (utils/errors.py): Removes paths, tokens, API keys before returning to LLM

**Sensitive data patterns**: 15 keys (password, token, api_key, secret, etc.) automatically redacted.

## Integration Points

### With pflow Core

**Direct imports**:
- `core.workflow_manager.WorkflowManager` - Workflow lifecycle
- `core.workflow_validator.WorkflowValidator` - 4-layer validation
- `core.workflow_save_service` - Shared save operations (CLI/MCP)
- `core.suggestion_utils` - "Did you mean" suggestions
- `core.security_utils` - SENSITIVE_KEYS constant
- `registry.Registry` - Node discovery
- `execution.workflow_execution.execute_workflow` - Workflow execution
- `execution.null_output.NullOutput` - Silent execution
- `runtime.compiler.import_node_class` - Node loading

### With FastMCP

**Server initialization**:
- Single instance: `mcp = FastMCP("pflow")`
- Tool registration: `@mcp.tool()` decorator on async functions
- Resource registration: `@mcp.resource("uri://path")` decorator on sync/async functions
- Stdio transport: `mcp.run("stdio")` manages own event loop
- Type hints: Pydantic Field descriptions generate MCP tool schema

### With Planning System

**Discovery tools**:
- Uses WorkflowDiscoveryNode, ComponentBrowsingNode directly
- Requires Anthropic model wrapper: `install_anthropic_model()` called in main.py
- Context builder: Uses build_planning_context() for node descriptions

## Agent-Optimized Defaults

**Built-in behaviors (no flags needed)**:
- **No auto-repair**: `enable_repair=False` always, agents get explicit errors with checkpoints
- **Silent execution**: `output=NullOutput()` instead of interactive progress
- **Trace auto-saved**: Always saves to `~/.pflow/debug/workflow-trace-*.json`
- **JSON-first**: All tools return structured dict or formatted string (not Click output)
- **Auto-normalization**: Workflow IR gets `ir_version`, `edges` automatically

**Execution differences from CLI**:
```python
# MCP
result = execute_workflow(
    enable_repair=False,        # Explicit errors
    output=NullOutput(),        # Silent
    # Returns dict with outputs/errors/trace_path
)

# CLI
result = execute_workflow(
    enable_repair=True,         # Auto-repair default
    output=CliOutput(),         # Interactive progress
    # Displays results via Click
)
```

## Critical Behaviors

### 1. Tool Discovery Pattern

**Discovery-first workflow**:
1. `workflow_discover(query)` → Check for existing workflows (avoid rebuilding)
2. `registry_discover(task)` → Find nodes for building (LLM selection)
3. `registry_run(node_type)` → Test node to reveal output structure (critical for MCP nodes)
4. `workflow_execute()` → Execute built workflow
5. `workflow_save()` → Save to library for reuse

### 2. Error Handling

**Services return structured errors**:
```python
# Service layer
return {
    "success": False,
    "error": {
        "type": "validation",
        "message": "Invalid workflow",
    },
}
```

**Tools convert to MCP responses**: Tools layer wraps service calls in try/except, handles conversion.

**Sanitization always applied**: All errors sanitized before returning to LLM (paths, tokens, keys removed).

### 3. Workflow Resolution

**Resolution order (utils/resolver.py)**:
1. Dict input → Use as IR (`"direct"`)
2. String with newline → Raw markdown content → parse (`"content"`)
3. String ending `.pflow.md` → File path → read and parse (`"file"`)
4. Single-line string → Try as library name (`"library"`), then as file path (`"file"`)
5. Failure → Return suggestions using substring matching

### 4. Validation Layers

**WorkflowValidator.validate() runs 4 checks**:
1. Structural validation: IR schema compliance
2. Data flow validation: Execution order, cycles, dependencies
3. Template validation: `${variable}` resolution
4. Node type validation: Registry verification

**generate_dummy_parameters()**: Creates `__validation_placeholder__` values for validation without real data.

## Testing

**Test location**: `tests/test_mcp_server/`

**Current coverage**:
- `test_tool_registration.py` - Tool registration verification
- `test_validation_service.py` - Validation logic (8 regression guards)
- `test_registry_run_errors.py` - Error handling patterns
- `test_instruction_resources.py` - Instruction resources (22 tests - regular + sandbox + differences)

**Test boundaries**:
- Mock at service layer: Service methods return predictable results
- Test tools layer: Async/sync bridge, error conversion, MCP response format
- Integration: Real Registry, WorkflowManager with temp files

## Best Practices

### When Working in This Module

1. **Maintain stateless pattern**: All service methods must be `@classmethod`, create fresh instances
2. **Use shared formatters**: Import from `execution/formatters/` for CLI/MCP parity
3. **Async bridge consistently**: Always use `asyncio.to_thread()` for sync pflow code
4. **Sanitize errors**: Apply `sanitize_error_message()` before returning to LLM
5. **Validate inputs**: Use `validation.py` functions for path and parameter security
6. **Fresh instances pattern**: Create Registry(), WorkflowManager() inside service methods
7. **Local imports**: Import formatters inside methods for clear dependencies
8. **Document defaults**: Tool docstrings must state agent-optimized behaviors
9. **Test stateless**: Verify no instance variables with BaseService.validate_stateless()
10. **Security first**: Validate paths, check parameter names, sanitize sensitive data

### Common Pitfalls to Avoid

1. **Don't store state**: No instance variables in services (violates stateless pattern)
2. **Don't skip async bridge**: Direct sync calls will block event loop
3. **Don't create custom formatters**: Reuse `execution/formatters/` for CLI parity
4. **Don't expose sensitive data**: Always sanitize errors before returning
5. **Don't assume dict input**: Use resolver.resolve_workflow() to handle all input types
6. **Don't skip validation**: Use validation.py functions for security
7. **Don't wrap mcp.run() in asyncio.run()**: FastMCP manages its own event loop
8. **Don't forget fresh instances**: Each request needs new Registry/WorkflowManager

### Integration Points to Remember

- **Tools**: Async wrappers with `@mcp.tool()` decorator
- **Services**: Stateless `@classmethod` with fresh instances
- **Formatters**: Shared with CLI from `execution/formatters/`
- **Core**: WorkflowManager, Registry, execute_workflow, validators
- **Security**: validation.py, errors.py, SENSITIVE_KEYS
- **FastMCP**: Single instance, stdio transport, signal handling

This module enables AI agents to build and execute workflows programmatically with the same capabilities as the CLI, while maintaining security, consistency, and stateless operation.
