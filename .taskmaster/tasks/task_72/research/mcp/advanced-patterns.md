# FastMCP Advanced Patterns

Research from FastMCP documentation on advanced patterns relevant to the pflow MCP server implementation.

## Middleware Patterns

### Core Middleware Hooks

FastMCP provides several middleware hook points:
- `on_message`: Processes all MCP messages
- `on_request`: Handles request-specific operations
- `on_call_tool`: Targets tool execution specifically
- Operation-specific hooks for resources, prompts, etc.

### Implementation Pattern

```python
class ExampleMiddleware(Middleware):
    async def on_message(self, context, call_next):
        # Pre-processing
        result = await call_next(context)
        # Post-processing
        return result
```

### Relevant Middleware Use Cases for pflow

1. **Logging & Monitoring**
   - Track which tools are being called
   - Measure workflow execution performance
   - Record usage statistics

2. **Error Handling**
   - Standardize error responses across all 13 tools
   - Log and track error occurrences
   - Implement consistent error formatting

3. **Rate Limiting** (if needed)
   - Control request frequency per client
   - Prevent server overload
   - Implement per-client quotas

4. **Authentication** (future consideration)
   - Verify client permissions
   - Block unauthorized tool access
   - Implement role-based controls

### Best Practices

- Implement only necessary hooks
- Keep middleware focused and single-purpose
- Handle errors gracefully
- Consider performance implications
- Use built-in middleware when possible

**Relevance for pflow**: Middleware could be useful for:
- Consistent error handling across all tools
- Logging tool usage for debugging
- Future authentication if needed

## Server Composition

### Two Composition Methods

1. **Importing (Static Composition)**
   - One-time copy of server components
   - Components are prefixed to avoid naming conflicts
   - Changes to original server are NOT reflected
   - Better performance

2. **Mounting (Dynamic Composition)**
   - Creates a live link between servers
   - Immediate reflection of changes in mounted server
   - Runtime request delegation
   - More flexible but slightly slower

### Example Pattern

```python
# Modular Server Design
weather_mcp = FastMCP(name="WeatherService")
database_mcp = FastMCP(name="DatabaseService")

main_mcp = FastMCP(name="MainApp")
main_mcp.import_server(weather_mcp, prefix="weather")
main_mcp.mount(database_mcp, prefix="db")
```

### Organizational Strategies

- Break large applications into focused servers
- Create utility servers for common functionality
- Group related tools and resources logically
- Use prefixes to prevent naming conflicts

**Relevance for pflow**: Currently NOT needed - our 13 tools are cohesive and belong in a single server. However, if we later want to split into:
- Core workflow tools (run, save, load, list)
- Registry tools (list-nodes, describe, execute)
- Settings tools (get-setting, set-setting, list-settings)
- Utility tools (validate, get-help, get-version, get-docs)

We could use composition to organize them logically while still exposing a unified interface.

**Recommendation**: Keep all 13 tools in one server for MVP. Consider composition only if we need to:
- Share tools with other MCP servers
- Split functionality for different deployment scenarios
- Create reusable utility servers

## Progress Reporting

### Core Method

```python
await ctx.report_progress(progress=current, total=total)
```

### Progress Patterns

1. **Percentage-Based Progress**
```python
percentage = (completed / total) * 100
await ctx.report_progress(progress=percentage, total=100)
```

2. **Absolute Progress**
```python
# Example: Processing 5 of 10 items
await ctx.report_progress(progress=5, total=10)
```

3. **Multi-Stage Operations**
```python
# Stage 1: Planning
await ctx.report_progress(progress=25, total=100)
# Stage 2: Validation
await ctx.report_progress(progress=50, total=100)
# Stage 3: Execution
await ctx.report_progress(progress=75, total=100)
# Stage 4: Complete
await ctx.report_progress(progress=100, total=100)
```

### Requirements

- Client must send `progressToken` in initial request
- Progress calls have no effect without token
- Implement client-side progress handling

**Relevance for pflow**: HIGHLY RELEVANT for:

1. **Workflow Execution (`run` tool)**
   - Report progress through multi-node workflows
   - Update as each node completes
   - Example: "Executing node 3 of 7"

2. **Planner Operations (`run` with natural language)**
   - Planning phase: 0-25%
   - Validation phase: 25-50%
   - Execution phase: 50-100%
   - Helps users understand long-running planning operations

3. **Multi-Workflow Operations (`list-workflows`, `validate`)**
   - Report progress when processing multiple workflows
   - Example: "Validated 15 of 42 workflows"

### Implementation Example for pflow

```python
@mcp.tool()
async def run_workflow(
    workflow: str,
    params: dict[str, Any] | None = None,
    ctx: Context
) -> str:
    """Execute a pflow workflow with progress reporting."""

    # Load workflow
    await ctx.report_progress(progress=10, total=100)

    # Validate
    await ctx.report_progress(progress=20, total=100)

    # Execute nodes (assuming 5 nodes)
    total_nodes = 5
    for i, node in enumerate(nodes):
        progress = 20 + ((i + 1) / total_nodes) * 80
        await ctx.report_progress(progress=progress, total=100)
        # Execute node...

    return result
```

**Recommendation**: Implement progress reporting for:
- `run` tool (both natural language and workflow file execution)
- Any tool that processes multiple items (list-workflows, validate)

## JSON Schema Utilities

### compress_schema Function

The `fastmcp.utilities.json_schema.compress_schema` function allows modifying JSON schemas:

```python
from fastmcp.utilities.json_schema import compress_schema

compressed = compress_schema(
    schema=original_schema,
    prune_params=["verbose", "debug"],  # Remove these parameters
    prune_defs=True,                    # Remove unused definitions
    prune_additional_properties=True,   # Remove additionalProperties: false
    prune_titles=False                  # Keep title fields
)
```

**Parameters**:
- `schema`: Input JSON schema dictionary
- `prune_params`: List of parameter names to remove
- `prune_defs`: Remove unused definitions (default True)
- `prune_additional_properties`: Remove additional properties restrictions (default True)
- `prune_titles`: Remove title fields (default False)

**Relevance for pflow**: LIMITED relevance - we're defining schemas manually with Pydantic models and type hints. This utility is more useful for:
- Dynamically generated schemas
- Schema transformation/simplification
- Removing internal parameters from public APIs

**Recommendation**: Not needed for MVP. Our schemas are simple enough to define directly with type hints.

## Security Considerations

From the middleware documentation:

1. **Authentication Middleware**
   - Verify client permissions before tool execution
   - Block unauthorized access to specific tools
   - Implement role-based access controls

2. **Input Validation**
   - Validate tool parameters in middleware
   - Sanitize user inputs before execution
   - Prevent injection attacks

3. **Error Handling**
   - Never expose internal system details in errors
   - Standardize error messages
   - Log security events separately

**Relevance for pflow**:

1. **Current State (Stateless CLI Wrapper)**
   - No authentication needed (user already has CLI access)
   - Input validation happens in pflow CLI
   - Errors should be user-friendly but not expose internals

2. **Security Pattern for pflow**
   - Trust boundary: MCP client -> pflow CLI -> system
   - Validation: Use pflow's existing validation
   - Error handling: Catch and format CLI errors

**Recommendation**: For MVP:
- No authentication (trust the MCP client)
- Rely on pflow's existing validation
- Implement error formatting middleware to hide internal details
- Log all tool calls for audit trail

## Stateless Operation Patterns

While not explicitly documented, we can infer stateless patterns from the examples:

1. **No Server-Side State**
   - Each tool call is independent
   - State is managed by the client or filesystem
   - No session management needed

2. **Context is Request-Scoped**
   - `ctx` parameter is per-request
   - Progress tokens are per-request
   - No shared state between requests

3. **Filesystem as State Store**
   - Workflows saved to `~/.pflow/workflows/`
   - Settings stored in `~/.pflow/settings.json`
   - Each tool call reads/writes to filesystem

**Relevance for pflow**: PERFECT match - pflow is already stateless:
- All state is in filesystem (`~/.pflow/`)
- Each CLI command is independent
- No in-memory state between invocations

**Recommendation**: Our stateless CLI-wrapping approach aligns perfectly with MCP best practices. No changes needed.

## Code Examples

### Complete Middleware Stack Example

```python
from fastmcp import FastMCP
from fastmcp.middleware import Middleware

class LoggingMiddleware(Middleware):
    async def on_call_tool(self, context, call_next):
        tool_name = context.request.params.name
        print(f"Tool called: {tool_name}")

        try:
            result = await call_next(context)
            print(f"Tool completed: {tool_name}")
            return result
        except Exception as e:
            print(f"Tool failed: {tool_name} - {e}")
            raise

class ErrorFormattingMiddleware(Middleware):
    async def on_call_tool(self, context, call_next):
        try:
            return await call_next(context)
        except Exception as e:
            # Format error for user-friendly display
            error_msg = self._format_error(e)
            raise Exception(error_msg)

    def _format_error(self, error: Exception) -> str:
        # Remove internal details, keep user-relevant info
        return str(error).split('\n')[0]

mcp = FastMCP("pflow")
mcp.add_middleware(LoggingMiddleware())
mcp.add_middleware(ErrorFormattingMiddleware())
```

### Progress Reporting in Long-Running Tool

```python
@mcp.tool()
async def run_workflow(
    workflow: str,
    params: dict[str, Any] | None = None,
    ctx: Context | None = None
) -> str:
    """Execute a pflow workflow with progress reporting."""

    # Only report progress if context provided
    async def report(progress: float):
        if ctx:
            await ctx.report_progress(progress=progress, total=100)

    await report(10)  # Started

    # Load workflow
    wf = load_workflow(workflow)
    await report(20)

    # Validate
    validate_workflow(wf)
    await report(30)

    # Execute nodes
    total_nodes = len(wf.nodes)
    for i, node in enumerate(wf.nodes):
        progress = 30 + ((i + 1) / total_nodes) * 70
        await report(progress)
        execute_node(node)

    return "Workflow completed successfully"
```

### Simple Server Composition (If Needed Later)

```python
# Split into focused servers
workflow_server = FastMCP("pflow-workflows")
# Add: run, save, load, list-workflows, validate

registry_server = FastMCP("pflow-registry")
# Add: list-nodes, describe-node, execute-node

settings_server = FastMCP("pflow-settings")
# Add: get-setting, set-setting, list-settings

# Compose into main server
main_server = FastMCP("pflow")
main_server.import_server(workflow_server, prefix="wf")
main_server.import_server(registry_server, prefix="registry")
main_server.import_server(settings_server, prefix="settings")

# Tools would be called as:
# - wf_run
# - wf_save
# - registry_list_nodes
# - settings_get_setting
```

## Summary of Relevant Patterns

### Must Implement
1. **Progress Reporting** for `run` tool
   - Critical for user experience during workflow execution
   - Shows planning/validation/execution phases

### Should Implement
1. **Error Formatting Middleware**
   - Standardize error messages across all tools
   - Hide internal details from MCP clients

2. **Logging Middleware**
   - Track tool usage for debugging
   - Create audit trail

### Consider for Future
1. **Authentication Middleware** (post-MVP)
   - If pflow becomes multi-user
   - If exposing to untrusted clients

2. **Server Composition** (if needed)
   - Only if we need to split tools across services
   - Not needed for current 13-tool set

### Not Needed
1. **JSON Schema Utilities**
   - Our schemas are simple enough for direct definition

2. **Rate Limiting** (for MVP)
   - Single-user, local execution
   - Can add later if needed
